"""
Post-Quantum Signature Pipeline for 3D Meshes
==============================================

Provides ML-DSA-44 (Dilithium) signing and verification of 3D mesh assets
using the canonical geometric fingerprint from ``MeshCanonicalizer``.

Workflow:
    1. ``generate_keys()``  – create an ML-DSA-44 keypair and persist to disk.
    2. ``sign_mesh()``      – canonicalize a mesh, sign its hash, and write a
                              JSON sidecar (``.sig.json``).
    3. ``verify_mesh()``    – recompute the canonical hash and verify the
                              sidecar signature against a public key.

Dependencies:
    - liboqs-python (``import oqs``) for ML-DSA-44 post-quantum signatures.
    - trimesh for mesh loading.
    - The ``MeshCanonicalizer`` from this package for deterministic hashing.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import oqs
import trimesh

from postquantum3d.canonicalize import MeshCanonicalizer

logger = logging.getLogger(__name__)

ALGORITHM = "ML-DSA-44"


def generate_keys(key_dir: Path) -> None:
    """Generate an ML-DSA-44 keypair and save both keys to *key_dir*.

    Creates two files inside *key_dir*:
        - ``public.key``  – raw public-key bytes.
        - ``private.key`` – raw secret-key bytes.

    Args:
        key_dir: Directory in which to write the key files.
                 Created (including parents) if it does not exist.
    """
    key_dir = Path(key_dir)
    key_dir.mkdir(parents=True, exist_ok=True)

    signer = oqs.Signature(ALGORITHM)
    public_key: bytes = signer.generate_keypair()
    private_key: bytes = signer.export_secret_key()

    key_dir.joinpath("public.key").write_bytes(public_key)
    key_dir.joinpath("private.key").write_bytes(private_key)

    logger.info(
        "Generated %s keypair in %s  |  pub=%d bytes  priv=%d bytes",
        ALGORITHM,
        key_dir,
        len(public_key),
        len(private_key),
    )


def sign_mesh(mesh_path: Path, private_key_path: Path) -> Path:
    """Sign a 3D mesh and write a JSON sidecar with the signature.

    The mesh is loaded, canonicalized to a deterministic SHA-256 fingerprint,
    and that fingerprint is signed with the ML-DSA-44 private key.  The
    resulting metadata is written as ``<mesh_filename>.sig.json`` next to the
    original mesh file.

    Args:
        mesh_path:        Path to the mesh file (any format trimesh supports).
        private_key_path: Path to the raw ML-DSA-44 private key on disk.

    Returns:
        Path to the newly created ``.sig.json`` sidecar file.
    """
    mesh_path = Path(mesh_path)
    private_key_path = Path(private_key_path)

    # --- Load & canonicalize ---
    mesh: trimesh.Trimesh = trimesh.load(str(mesh_path), force="mesh")
    canonicalizer = MeshCanonicalizer(mesh)
    geometric_hash: str = canonicalizer.canonicalize()

    # --- Sign the canonical hash ---
    private_key: bytes = private_key_path.read_bytes()
    signer = oqs.Signature(ALGORITHM, private_key)
    signature: bytes = signer.sign(geometric_hash.encode("utf-8"))

    # --- Build sidecar metadata ---
    metadata: dict[str, str] = {
        "asset_name": mesh_path.name,
        "algorithm": ALGORITHM,
        "geometric_hash": geometric_hash,
        "signature_b64": base64.b64encode(signature).decode("ascii"),
    }

    sig_path: Path = mesh_path.with_suffix(mesh_path.suffix + ".sig.json")
    sig_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    logger.info(
        "Signed %s  |  hash=%s…  |  sidecar=%s",
        mesh_path.name,
        geometric_hash[:16],
        sig_path.name,
    )
    return sig_path


def verify_mesh(
    mesh_path: Path,
    public_key_path: Path,
    sig_path: Path,
) -> bool:
    """Verify a mesh against its ``.sig.json`` sidecar and a public key.

    Re-canonicalizes the mesh to obtain the local geometric hash, then checks
    the ML-DSA-44 signature stored in the sidecar against the public key.

    Args:
        mesh_path:       Path to the mesh file to verify.
        public_key_path: Path to the raw ML-DSA-44 public key on disk.
        sig_path:        Path to the ``.sig.json`` sidecar.

    Returns:
        ``True`` if the signature is valid for the current mesh geometry,
        ``False`` otherwise (tampered geometry, tampered signature, or wrong key).
    """
    mesh_path = Path(mesh_path)
    public_key_path = Path(public_key_path)
    sig_path = Path(sig_path)

    # --- Load mesh and recompute canonical hash ---
    mesh: trimesh.Trimesh = trimesh.load(str(mesh_path), force="mesh")
    canonicalizer = MeshCanonicalizer(mesh)
    local_hash: str = canonicalizer.canonicalize()

    # --- Load sidecar and decode signature ---
    sidecar: dict[str, str] = json.loads(sig_path.read_text(encoding="utf-8"))
    signature: bytes = base64.b64decode(sidecar["signature_b64"])

    # --- Verify ---
    public_key: bytes = public_key_path.read_bytes()
    verifier = oqs.Signature(ALGORITHM)

    try:
        is_valid: bool = verifier.verify(
            local_hash.encode("utf-8"),
            signature,
            public_key,
        )
    except Exception:
        logger.warning("Signature verification raised an exception for %s", mesh_path.name)
        return False

    logger.info(
        "Verified %s  |  result=%s  |  local_hash=%s…",
        mesh_path.name,
        is_valid,
        local_hash[:16],
    )
    return is_valid
