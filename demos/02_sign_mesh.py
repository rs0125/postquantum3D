#!/usr/bin/env python3
"""
Demo 2 — Sign a 3D Mesh
========================

Signs one or more OBJ files using the private key from ``demo_keys/``.
Produces a ``.sig.json`` sidecar next to each mesh.

Usage:
    python demos/02_sign_mesh.py                           # signs all test meshes
    python demos/02_sign_mesh.py test_meshes/bunny.obj     # sign one mesh
"""

import json
import sys
from pathlib import Path

# -- path fixup --
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from postquantum3d.sign import sign_mesh

KEY_DIR = ROOT / "demo_keys"
MESH_DIR = ROOT / "test_meshes"


def sign_one(mesh_path: Path) -> None:
    priv = KEY_DIR / "private.key"
    if not priv.exists():
        print("  ERROR: Run 01_generate_keys.py first.")
        sys.exit(1)

    sig_path = sign_mesh(mesh_path, priv)
    sidecar = json.loads(sig_path.read_text())

    print(f"\n  Asset:      {mesh_path.name}")
    print(f"  Hash:       {sidecar['geometric_hash']}")
    print(f"  Signature:  {sidecar['signature_b64'][:48]}...")
    print(f"  Sidecar:    {sig_path}")


def main() -> None:
    print("=" * 60)
    print("  ML-DSA-44 Mesh Signing")
    print("=" * 60)

    if len(sys.argv) > 1:
        targets = [Path(p) for p in sys.argv[1:]]
    else:
        targets = sorted(MESH_DIR.glob("*.obj"))

    for mesh_path in targets:
        sign_one(mesh_path)

    print()
    print(f"  Signed {len(targets)} mesh(es).  Run 03_verify_mesh.py next.")
    print("=" * 60)


if __name__ == "__main__":
    main()
