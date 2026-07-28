"""
Test Suite for Post-Quantum Signature Pipeline
===============================================

Verifies the cryptographic guarantees of the ML-DSA-44 signing and
verification pipeline:

    1. **End-to-end**: sign → verify round-trip succeeds.
    2. **Tampered geometry**: modifying a single vertex invalidates the signature.
    3. **Tampered signature**: flipping a byte in the signature is detected.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Make the src/ package importable from the tests/ directory.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from postquantum3d.sign import generate_keys, sign_mesh, verify_mesh  # noqa: E402

MESH_DIR = Path(__file__).resolve().parent.parent / "test_meshes"


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _setup_keys(tmp_path: Path) -> tuple[Path, Path]:
    """Generate a keypair in *tmp_path* and return (public, private) paths."""
    key_dir = tmp_path / "keys"
    generate_keys(key_dir)
    return key_dir / "public.key", key_dir / "private.key"


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestSignaturePipeline:
    """Cryptographic correctness tests for the ML-DSA-44 mesh pipeline."""

    def test_end_to_end_verification(self, tmp_path: Path) -> None:
        """Sign cube.obj and verify – the round-trip must succeed."""
        pub, priv = _setup_keys(tmp_path)

        mesh_path = MESH_DIR / "cube.obj"
        sig_path = sign_mesh(mesh_path, priv)

        assert sig_path.exists(), "Sidecar .sig.json was not created"
        assert verify_mesh(mesh_path, pub, sig_path) is True

    def test_tampered_geometry_fails(self, tmp_path: Path) -> None:
        """Shifting one vertex in bunny.obj must break verification."""
        pub, priv = _setup_keys(tmp_path)

        original = MESH_DIR / "bunny.obj"
        sig_path = sign_mesh(original, priv)

        # --- Create a tampered copy ---
        tampered = tmp_path / "bunny_tampered.obj"
        lines = original.read_text(encoding="utf-8").splitlines(keepends=True)

        first_vertex_modified = False
        with tampered.open("w", encoding="utf-8") as fh:
            for line in lines:
                if not first_vertex_modified and line.startswith("v "):
                    parts = line.split()
                    # Add 1.0 to the X-coordinate of the very first vertex
                    x = float(parts[1]) + 1.0
                    fh.write(f"v {x} {parts[2]} {parts[3]}\n")
                    first_vertex_modified = True
                else:
                    fh.write(line)

        assert first_vertex_modified, "No vertex line found in bunny.obj"
        assert verify_mesh(tampered, pub, sig_path) is False

    def test_tampered_signature_fails(self, tmp_path: Path) -> None:
        """Flipping a character in the base64 signature must be detected."""
        pub, priv = _setup_keys(tmp_path)

        mesh_path = MESH_DIR / "cube.obj"
        sig_path = sign_mesh(mesh_path, priv)

        # --- Tamper with the signature ---
        sidecar: dict[str, str] = json.loads(
            sig_path.read_text(encoding="utf-8")
        )
        original_b64: str = sidecar["signature_b64"]

        # Flip the first alphanumeric character to a different one.
        match = re.search(r"[A-Za-z0-9]", original_b64)
        assert match is not None, "No alphanumeric character in signature_b64"
        idx = match.start()
        replacement = "A" if original_b64[idx] != "A" else "B"
        tampered_b64 = original_b64[:idx] + replacement + original_b64[idx + 1 :]

        sidecar["signature_b64"] = tampered_b64

        tampered_sig = tmp_path / "cube.obj.sig.json"
        tampered_sig.write_text(
            json.dumps(sidecar, indent=2), encoding="utf-8"
        )

        assert verify_mesh(mesh_path, pub, tampered_sig) is False
