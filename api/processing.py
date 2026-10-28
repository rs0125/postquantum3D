"""Bounded upload processing using the repository's canonicalizer and ML-DSA format."""

import base64
import binascii
import io
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import oqs
import trimesh

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from postquantum3d.canonicalize import MeshCanonicalizer
from postquantum3d.sign import ALGORITHM

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_VERTICES = 50_000
MAX_FACES = 100_000
MAX_DISTANCE_VERTICES = 1_500
FORMATS = {".obj", ".stl", ".ply", ".glb"}


class MeshInputError(ValueError):
    """An uploaded mesh or signature cannot be processed."""


class UploadCanonicalizer(MeshCanonicalizer):
    """Use the exact algorithm, with a resource guard on its quadratic fallback."""

    def _phase6_hash_distances(self):
        if len(self._vertices) > MAX_DISTANCE_VERTICES:
            raise MeshInputError(
                f"This mesh needs the pairwise-distance fallback. Reduce it to "
                f"{MAX_DISTANCE_VERTICES:,} vertices or fewer for this local dashboard."
            )
        return super()._phase6_hash_distances()


def clean_filename(filename):
    return Path((filename or "mesh.obj").replace("\\", "/")).name[:160]


def load_mesh(content, filename):
    extension = Path(filename).suffix.lower()
    if extension not in FORMATS:
        raise MeshInputError("Choose an OBJ, STL, PLY, or self-contained GLB mesh.")
    if not content:
        raise MeshInputError("The uploaded mesh is empty.")
    if len(content) > MAX_FILE_BYTES:
        raise MeshInputError("The mesh exceeds the 20 MB upload limit.")
    try:
        mesh = trimesh.load(
            io.BytesIO(content), file_type=extension[1:], force="mesh",
            resolver={}, allow_remote=False, skip_materials=True,
        )
        if not isinstance(mesh, trimesh.Trimesh) or len(mesh.vertices) < 3 or not len(mesh.faces):
            raise MeshInputError("The file must contain a mesh with vertices and triangular faces.")
        if len(mesh.vertices) > MAX_VERTICES or len(mesh.faces) > MAX_FACES:
            raise MeshInputError("Use a mesh with at most 50,000 vertices and 100,000 triangles.")
        if not np.isfinite(mesh.vertices).all():
            raise MeshInputError("Mesh coordinates must be finite numbers.")
        if mesh.faces.min() < 0 or mesh.faces.max() >= len(mesh.vertices):
            raise MeshInputError("The mesh contains invalid face indices.")
        radius = np.linalg.norm(mesh.vertices - mesh.vertices.mean(axis=0), axis=1).max()
        if not np.isfinite(radius) or radius < 1e-12:
            raise MeshInputError("The mesh has no usable spatial extent.")
        return mesh
    except MeshInputError:
        raise
    except Exception as exc:
        raise MeshInputError("Could not read this mesh. Check the file format and geometry.") from exc


def fingerprint(mesh):
    try:
        return UploadCanonicalizer(mesh).canonicalize()
    except MeshInputError:
        raise
    except (ValueError, np.linalg.LinAlgError) as exc:
        raise MeshInputError("This geometry could not be canonicalized.") from exc


def verify_digest(digest, signature, public_key):
    # The existing sign.py signs the UTF-8 hex fingerprint, not the raw digest.
    with oqs.Signature(ALGORITHM) as verifier:
        try:
            return bool(verifier.verify(digest.encode("utf-8"), signature, public_key))
        except (ValueError, RuntimeError):
            return False


def preview_vertices(mesh):
    vertices = np.array(mesh.vertices, dtype=float)
    vertices -= (vertices.min(axis=0) + vertices.max(axis=0)) / 2
    vertices /= np.ptp(vertices, axis=0).max() / 2
    return np.round(vertices, 6).tolist()


def process_mesh(content, filename):
    started = time.perf_counter()
    timings = {}

    def timed(name, action):
        before = time.perf_counter()
        value = action()
        timings[name] = round((time.perf_counter() - before) * 1000, 2)
        return value

    filename = clean_filename(filename)
    mesh = timed("load", lambda: load_mesh(content, filename))
    digest = timed("fingerprint", lambda: fingerprint(mesh))

    # Each upload gets a fresh keypair. Secret keys never leave the server and
    # are freed when the OQS context exits; nothing is persisted to disk.
    before = time.perf_counter()
    with oqs.Signature(ALGORITHM) as signer:
        public_key = signer.generate_keypair()
        signature = signer.sign(digest.encode("utf-8"))
    timings["sign"] = round((time.perf_counter() - before) * 1000, 2)
    original_valid = timed("verify", lambda: verify_digest(digest, signature, public_key))
    sidecar = {"asset_name": filename, "algorithm": ALGORITHM,
               "geometric_hash": digest, "signature_b64": base64.b64encode(signature).decode()}

    angle = np.deg2rad(35)
    rotation = np.array([[np.cos(angle), -np.sin(angle), 0],
                         [np.sin(angle), np.cos(angle), 0], [0, 0, 1]])
    transformed = mesh.copy()
    transformed.vertices = 1.5 * (np.asarray(mesh.vertices) @ rotation.T) + [2, -1, 0.5]
    tampered = mesh.copy()
    # Select a nonempty region even for primitives and meshes with tied X values.
    changed = np.argsort(mesh.vertices[:, 0])[-max(1, int(len(mesh.vertices) * 0.08)):]
    edited = np.array(mesh.vertices)
    edited[changed, 0] += np.ptp(mesh.vertices, axis=0).max() * 0.24
    tampered.vertices = edited

    scenarios = {
        "original": {"hash": digest, "verified": original_valid,
                     "vertices": preview_vertices(mesh), "error": None}
    }
    checks = [{"title": "Original asset", "expected": True, "actual": original_valid, "error": None}]
    before = time.perf_counter()
    for name, title, variant, expected in [
        ("transformed", "Rotate + scale + translate", transformed, True),
        ("tampered", "Edited geometry", tampered, False),
    ]:
        try:
            variant_hash = fingerprint(variant)
            verified = verify_digest(variant_hash, signature, public_key)
            error = None
        except MeshInputError as exc:
            variant_hash, verified, error = None, None, str(exc)
        scenarios[name] = {"hash": variant_hash, "verified": verified,
                           "vertices": preview_vertices(variant), "error": error}
        checks.append({"title": title, "expected": expected, "actual": verified, "error": error})

    bad_signature = bytearray(signature)
    bad_signature[0] ^= 1
    with oqs.Signature(ALGORITHM) as other_signer:
        wrong_public_key = other_signer.generate_keypair()
    checks.extend([
        {"title": "Modified signature", "expected": False,
         "actual": verify_digest(digest, bytes(bad_signature), public_key), "error": None},
        {"title": "Wrong public key", "expected": False,
         "actual": verify_digest(digest, signature, wrong_public_key), "error": None},
    ])
    timings["experiments"] = round((time.perf_counter() - before) * 1000, 2)
    return {
        "filename": filename, "size": len(content), "vertexCount": len(mesh.vertices),
        "triangleCount": len(mesh.faces), "faces": mesh.faces.tolist(),
        "changedVertices": changed.tolist(), "scenarios": scenarios, "checks": checks,
        "sidecar": sidecar, "publicKey": base64.b64encode(public_key).decode(),
        "signatureBytes": len(signature), "timings": timings,
        "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
        "processedAt": datetime.now(timezone.utc).isoformat(),
    }


def verify_upload(content, filename, sidecar_content, public_key):
    started = time.perf_counter()
    try:
        sidecar = json.loads(sidecar_content)
        if not isinstance(sidecar, dict) or sidecar.get("algorithm") != ALGORITHM:
            raise ValueError("Unsupported signature algorithm")
        if not isinstance(sidecar.get("geometric_hash"), str) or not re.fullmatch(r"[0-9a-f]{64}", sidecar["geometric_hash"]):
            raise ValueError("Invalid fingerprint")
        signature = base64.b64decode(sidecar["signature_b64"], validate=True)
        with oqs.Signature(ALGORITHM) as verifier:
            details = verifier.details
        if len(signature) != details["length_signature"] or len(public_key) != details["length_public_key"]:
            raise ValueError("Invalid key or signature length")
    except (ValueError, TypeError, KeyError, binascii.Error) as exc:
        raise MeshInputError("Use a valid ML-DSA-44 .sig.json file and its original raw public.key file.") from exc

    mesh = load_mesh(content, filename)
    digest = fingerprint(mesh)
    signature_valid = verify_digest(digest, signature, public_key)
    fingerprint_matches = digest == sidecar["geometric_hash"]
    return {
        "filename": clean_filename(filename), "verified": signature_valid and fingerprint_matches,
        "signatureValid": signature_valid, "fingerprintMatches": fingerprint_matches,
        "hash": digest, "signedHash": sidecar["geometric_hash"], "algorithm": ALGORITHM,
        "elapsedMs": round((time.perf_counter() - started) * 1000, 2),
        "verifiedAt": datetime.now(timezone.utc).isoformat(),
    }
