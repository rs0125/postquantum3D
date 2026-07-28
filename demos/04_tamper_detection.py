#!/usr/bin/env python3
"""
Demo 4 — Tamper Detection Showcase
===================================

End-to-end demonstration of the full provenance pipeline:

  1. Generate a fresh ML-DSA-44 keypair.
  2. Sign a mesh (bunny.obj).
  3. Verify the untouched mesh      → PASS.
  4. Tamper with the geometry        → FAIL.
  5. Tamper with the signature       → FAIL.
  6. Verify with the wrong key       → FAIL.

Everything runs in a temporary directory — no side effects.

Usage:
    python demos/04_tamper_detection.py
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

# -- path fixup --
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from postquantum3d.sign import generate_keys, sign_mesh, verify_mesh

MESH_DIR = ROOT / "test_meshes"


def section(title: str) -> None:
    print(f"\n{'─' * 60}")
    print(f"  {title}")
    print(f"{'─' * 60}")


def main() -> None:
    print("=" * 60)
    print("  Post-Quantum 3D Asset Tamper Detection")
    print("  ML-DSA-44  |  FIPS 204  |  NIST PQC Level 2")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="pq3d_demo_") as tmp:
        tmp_path = Path(tmp)

        # ── Step 1: Key generation ──────────────────────────────
        section("Step 1  Generate ML-DSA-44 keypair")
        key_dir = tmp_path / "keys"
        generate_keys(key_dir)
        pub = key_dir / "public.key"
        priv = key_dir / "private.key"
        print(f"  Public key:   {pub.stat().st_size:,} bytes")
        print(f"  Private key:  {priv.stat().st_size:,} bytes")

        # ── Step 2: Sign the bunny ──────────────────────────────
        section("Step 2  Sign bunny.obj")
        bunny = MESH_DIR / "bunny.obj"
        sig_path = sign_mesh(bunny, priv)
        sidecar = json.loads(sig_path.read_text())
        print(f"  Geometric hash:  {sidecar['geometric_hash']}")
        print(f"  Signature:       {sidecar['signature_b64'][:48]}...")
        print(f"  Sidecar:         {sig_path.name}")

        # ── Step 3: Verify untouched ────────────────────────────
        section("Step 3  Verify untouched mesh")
        result = verify_mesh(bunny, pub, sig_path)
        print(f"  Result: {'PASS' if result else 'FAIL'}")
        assert result, "Untouched mesh should verify"

        # ── Step 4: Tamper with geometry ────────────────────────
        section("Step 4  Tamper with geometry (shift first vertex +1.0 on X)")
        tampered_mesh = tmp_path / "bunny_tampered.obj"
        lines = bunny.read_text(encoding="utf-8").splitlines(keepends=True)
        first_modified = False
        with tampered_mesh.open("w", encoding="utf-8") as fh:
            for line in lines:
                if not first_modified and line.startswith("v "):
                    parts = line.split()
                    x = float(parts[1]) + 1.0
                    fh.write(f"v {x} {parts[2]} {parts[3]}\n")
                    first_modified = True
                else:
                    fh.write(line)

        result = verify_mesh(tampered_mesh, pub, sig_path)
        print(f"  Result: {'PASS' if result else 'FAIL'}  (expected FAIL)")
        assert not result, "Tampered geometry should fail"

        # ── Step 5: Tamper with signature ───────────────────────
        section("Step 5  Tamper with signature (flip one byte)")
        tampered_sidecar = tmp_path / "bunny_badsig.sig.json"
        bad = dict(sidecar)
        sig_b64 = bad["signature_b64"]
        # Flip the first character
        replacement = "A" if sig_b64[0] != "A" else "B"
        bad["signature_b64"] = replacement + sig_b64[1:]
        tampered_sidecar.write_text(json.dumps(bad, indent=2))

        result = verify_mesh(bunny, pub, tampered_sidecar)
        print(f"  Result: {'PASS' if result else 'FAIL'}  (expected FAIL)")
        assert not result, "Tampered signature should fail"

        # ── Step 6: Wrong key ───────────────────────────────────
        section("Step 6  Verify with wrong public key")
        wrong_dir = tmp_path / "wrong_keys"
        generate_keys(wrong_dir)
        wrong_pub = wrong_dir / "public.key"

        result = verify_mesh(bunny, wrong_pub, sig_path)
        print(f"  Result: {'PASS' if result else 'FAIL'}  (expected FAIL)")
        assert not result, "Wrong key should fail"

    # ── Summary ─────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("  All 4 scenarios behaved correctly:")
    print("    1. Untouched mesh + correct key    -> PASS")
    print("    2. Tampered geometry                -> FAIL")
    print("    3. Tampered signature               -> FAIL")
    print("    4. Wrong public key                 -> FAIL")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
