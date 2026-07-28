#!/usr/bin/env python3
"""
Demo 1 — Generate an ML-DSA-44 Keypair
=======================================

Creates a post-quantum keypair and saves it to ``demo_keys/``.
Run this first before signing or verifying.

Usage:
    python demos/01_generate_keys.py
"""

import sys
from pathlib import Path

# -- path fixup --
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from postquantum3d.sign import generate_keys

KEY_DIR = ROOT / "demo_keys"


def main() -> None:
    print("=" * 60)
    print("  ML-DSA-44 Key Generation")
    print("=" * 60)

    generate_keys(KEY_DIR)

    pub = KEY_DIR / "public.key"
    priv = KEY_DIR / "private.key"

    print(f"\n  Public key:  {pub}  ({pub.stat().st_size:,} bytes)")
    print(f"  Private key: {priv}  ({priv.stat().st_size:,} bytes)")
    print(f"\n  Algorithm:   ML-DSA-44  (FIPS 204 / Dilithium2)")
    print(f"  Security:    NIST Level 2  (~128-bit post-quantum)")
    print()
    print("  Keys written.  Run 02_sign_mesh.py next.")
    print("=" * 60)


if __name__ == "__main__":
    main()
