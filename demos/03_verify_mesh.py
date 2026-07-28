#!/usr/bin/env python3
"""
Demo 3 — Verify a Signed Mesh
==============================

Verifies one or more OBJ files against their ``.sig.json`` sidecars
using the public key from ``demo_keys/``.

Usage:
    python demos/03_verify_mesh.py                           # verify all test meshes
    python demos/03_verify_mesh.py test_meshes/bunny.obj     # verify one mesh
"""

import sys
from pathlib import Path

# -- path fixup --
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from postquantum3d.sign import verify_mesh

KEY_DIR = ROOT / "demo_keys"
MESH_DIR = ROOT / "test_meshes"


def verify_one(mesh_path: Path) -> bool:
    pub = KEY_DIR / "public.key"
    sig_path = mesh_path.with_suffix(mesh_path.suffix + ".sig.json")

    if not pub.exists():
        print("  ERROR: Run 01_generate_keys.py first.")
        sys.exit(1)
    if not sig_path.exists():
        print(f"  SKIP  {mesh_path.name}  (no sidecar found)")
        return True

    result = verify_mesh(mesh_path, pub, sig_path)
    status = "PASS" if result else "FAIL"
    print(f"  [{status}]  {mesh_path.name}")
    return result


def main() -> None:
    print("=" * 60)
    print("  ML-DSA-44 Mesh Verification")
    print("=" * 60)
    print()

    if len(sys.argv) > 1:
        targets = [Path(p) for p in sys.argv[1:]]
    else:
        targets = sorted(MESH_DIR.glob("*.obj"))

    all_ok = True
    for mesh_path in targets:
        if not verify_one(mesh_path):
            all_ok = False

    print()
    if all_ok:
        print("  All meshes verified successfully.")
    else:
        print("  WARNING: One or more meshes FAILED verification.")
    print("=" * 60)
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
