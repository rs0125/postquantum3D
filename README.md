# postquantum3D

Post-quantum provenance pipeline for 3D mesh assets. Produces a **geometry-canonical fingerprint** (SHA-256) that is invariant to rotation, translation, and uniform scale, then binds it to an identity via an **ML-DSA-44** digital signature (FIPS 204 / Dilithium).

Two geometrically identical meshes that differ only by how they were exported will always produce the **exact same hash** — and a single signature covers every possible re-export of that geometry.

## The Problem

When a 3D mesh passes through an export pipeline — different DCCs (Blender, Maya, Houdini), file formats (OBJ, FBX, glTF), or coordinate conventions (Y-up vs Z-up) — the raw vertex data changes even though the geometry is identical. A mesh translated by `(100, 0, 0)`, scaled by `3x`, and rotated `45°` on Y is still the same bunny. But a naive hash of the vertex buffer will be completely different.

This makes it impossible to answer: *"Is this the same mesh I signed, or has someone tampered with it?"*

## The Solution

### Stage 1: Canonical Fingerprinting

`MeshCanonicalizer` strips away every degree of freedom that doesn't affect geometry:

```
Phase 1 — Center        Remove 3 DOF (translation)      Subtract centroid
Phase 2 — Normalize     Remove 1 DOF (uniform scale)    Divide by max radius
Phase 3 — PCA Align     Remove 3 DOF (rotation)         Eigenvector alignment
Phase 4 — Truncate      Remove float noise               Floor to 4 decimal places
Phase 5 — Sort          Remove vertex ordering           Lexicographic sort
Phase 6 — Hash          Produce fingerprint              SHA-256
```

### Stage 2: Post-Quantum Signature

`sign_mesh()` signs the canonical fingerprint with ML-DSA-44 and writes a `.sig.json` sidecar. `verify_mesh()` recomputes the fingerprint from the mesh and checks the signature.

```
Mesh ──▶ Canonicalize ──▶ SHA-256 ──▶ ML-DSA-44 Sign ──▶ .sig.json
                                              │
Mesh ──▶ Canonicalize ──▶ SHA-256 ──▶ ML-DSA-44 Verify ◀─ .sig.json + public key
                                              │
                                         True / False
```

## Quick Start

### Install Dependencies

```bash
pip install trimesh numpy scipy liboqs-python
```

`liboqs-python` requires the system `liboqs` library. On Fedora: `sudo dnf install liboqs`. On Ubuntu: see [Open Quantum Safe install guide](https://github.com/open-quantum-safe/liboqs).

### Python API

```python
import trimesh
from postquantum3d import MeshCanonicalizer, generate_keys, sign_mesh, verify_mesh
from pathlib import Path

# Canonical fingerprinting (no keys needed)
mesh = trimesh.load("model.obj", force="mesh")
fingerprint = MeshCanonicalizer(mesh).canonicalize()
print(fingerprint)  # e.g. "b50b58d62243bf2ff5fe..."

# Key generation
generate_keys(Path("keys/"))

# Sign
sig_path = sign_mesh(Path("model.obj"), Path("keys/private.key"))

# Verify
is_valid = verify_mesh(Path("model.obj"), Path("keys/public.key"), sig_path)
assert is_valid
```

### Run the Demos

```bash
# Full tamper-detection showcase (self-contained, no setup needed)
python demos/04_tamper_detection.py

# Or step-by-step:
python demos/01_generate_keys.py                          # create ML-DSA-44 keypair
python demos/02_sign_mesh.py                               # sign all test meshes
python demos/03_verify_mesh.py                             # verify all test meshes
python demos/02_sign_mesh.py test_meshes/bunny.obj         # sign one mesh
python demos/03_verify_mesh.py test_meshes/bunny.obj       # verify one mesh
```

### CLI (Canonicalization Only)

```bash
python src/postquantum3d/canonicalize.py test_meshes/bunny.obj
```

### Verify Invariance

```python
import trimesh
import numpy as np
from scipy.spatial.transform import Rotation
from postquantum3d import MeshCanonicalizer

mesh = trimesh.load("bunny.obj", force="mesh")

# Simulate an export pipeline: scale, rotate, translate
mutated = mesh.copy()
R = Rotation.random().as_matrix()
mutated.vertices = 42.0 * (np.array(mutated.vertices) @ R.T) + [100, -200, 50]

h1 = MeshCanonicalizer(mesh).canonicalize()
h2 = MeshCanonicalizer(mutated).canonicalize()

assert h1 == h2  # Identical hashes — same geometry
```

## How It Works

### Canonicalization Pipeline

See [docs/02-canonicalization-theory.md](docs/02-canonicalization-theory.md) for the full mathematical treatment.

**Phase 1 — Translation Invariance**: Subtract the centroid. `V' - mean(V') = V - mean(V)`.

**Phase 2 — Scale Invariance**: Divide by max radius. `(sV) / max(||sV||) = V / max(||V||)`.

**Phase 3 — Rotation Invariance**: PCA alignment with sum-of-cubes sign disambiguation. Falls back to a distance-based invariant for degenerate eigenvalues (cubes, spheres, cylinders).

**Phase 4 — Truncation**: Floor to 4 decimal places. Absorbs floating-point non-determinism.

**Phase 5 — Sort**: Lexicographic vertex sort. Removes vertex-ordering dependence.

**Phase 6 — SHA-256**: Hash the canonical coordinate or distance string.

### Signature Pipeline

See [docs/03-post-quantum-signatures.md](docs/03-post-quantum-signatures.md) for the ML-DSA-44 mathematical background.

**ML-DSA-44** (FIPS 204) is a lattice-based signature scheme providing NIST Level 2 post-quantum security (~128-bit). It is resistant to Shor's algorithm and provides existential unforgeability under chosen-message attacks (EUF-CMA) in the quantum random oracle model.

| Parameter | ML-DSA-44 |
|---|---|
| Public key | 1,312 bytes |
| Secret key | 2,560 bytes |
| Signature | 2,420 bytes |
| NIST security level | 2 (~128-bit post-quantum) |

## What Changes the Hash (and What Doesn't)

| Operation | Hash changes? | Why |
|---|---|---|
| Translation | No | Phase 1 removes it |
| Uniform scale | No | Phase 2 removes it |
| Rotation | No | Phase 3 removes it |
| Reflection (mirror) | No | Sign disambiguation undoes it |
| Vertex reordering | No | Phase 5 sorts vertices |
| Convert OBJ to glTF | No | Vertex positions preserved |
| Non-uniform scale (stretch) | **Yes** | Changes geometry |
| Moving a vertex | **Yes** | Changes geometry |
| Adding/removing vertices | **Yes** | Changes vertex set |
| Random noise on vertices | **Yes** | Changes geometry |
| Different mesh entirely | **Yes** | Different geometry |

## Project Structure

```
postquantum3D/
├── src/
│   ├── __init__.py
│   └── postquantum3d/
│       ├── __init__.py
│       ├── canonicalize.py              # MeshCanonicalizer (geometry pipeline)
│       └── sign.py                      # ML-DSA-44 sign / verify / keygen
├── tests/
│   ├── __init__.py
│   ├── test_canonicalize.py             # Invariance tests (7 meshes × 7 seeds)
│   ├── test_edge_cases.py              # Edge cases + negative tests
│   └── test_sign.py                    # Signature pipeline tests
├── demos/
│   ├── 01_generate_keys.py            # Generate ML-DSA-44 keypair
│   ├── 02_sign_mesh.py                # Sign mesh(es)
│   ├── 03_verify_mesh.py              # Verify mesh(es)
│   └── 04_tamper_detection.py         # Full showcase (self-contained)
├── docs/
│   ├── 01-architecture.md             # System architecture overview
│   ├── 02-canonicalization-theory.md  # Mathematical foundations
│   ├── 03-post-quantum-signatures.md  # ML-DSA-44 theory
│   ├── 04-threat-model.md            # Security analysis
│   └── 05-provenance-pipeline.md     # Pipeline design & integration
├── test_meshes/                        # OBJ test models
│   ├── armadillo.obj                   # Stanford Armadillo   (49,990 verts)
│   ├── bunny.obj                       # Stanford Bunny       (34,834 verts)
│   ├── cube.obj                        # Simple cube          (14 verts)
│   ├── homer.obj                       # Homer Simpson        (6,002 verts)
│   ├── spot.obj                        # Spot the cow         (3,225 verts)
│   ├── suzanne.obj                     # Blender Suzanne      (507 verts)
│   └── teapot.obj                      # Utah Teapot          (3,241 verts)
├── logs/                               # Pipeline logs (gitignored)
├── .gitignore
└── README.md
```

## Running Tests

```bash
# Run all 257 tests
python -m pytest tests/ -v

# Canonicalization invariance tests (70 tests)
python -m pytest tests/test_canonicalize.py -v

# Edge case + negative tests (184 tests)
python -m pytest tests/test_edge_cases.py -v

# Signature pipeline tests (3 tests)
python -m pytest tests/test_sign.py -v
```

### Test Categories

**Invariance tests** (`test_canonicalize.py`) — 70 tests
- Each of 7 real-world OBJ meshes is randomly rotated, scaled, and translated with 7 different random seeds. The hash must be identical every time.

**Edge case tests** (`test_edge_cases.py`) — 184 tests

| Category | Count | What it tests |
|---|---|---|
| Input validation | 3 | Empty, single-vertex, coincident vertices |
| Perfect cube | 40 | Triple eigenvalue degeneracy, 20 seeds |
| UV sphere | 10 | Near-degenerate eigenvalues |
| Cylinder | 10 | Double eigenvalue degeneracy |
| Tetrahedron | 10 | Regular tetrahedron degeneracy |
| Coplanar mesh | 20 | Rank-2 covariance (flat geometry) |
| Collinear mesh | 10 | Rank-1 covariance (line geometry) |
| Antipodal ties | 50 | Vertices with equal ±projections |
| Vertex permutation | 1 | Shuffled vertex order |
| Extreme scale | 4 | 1e-8 to 1e8 |
| Extreme translation | 2 | 1e4 to 1e6 |
| Truncation boundaries | 2 | Negative zero, 0.00005 boundary |
| Distinct meshes | 2 | All meshes produce unique hashes |
| Reflection | 1 | Mirror preserves hash |
| Negative: vertex changes | 9 | Move, add, remove, duplicate, noise |
| Negative: scaling | 2 | Non-uniform scale (2x, 1.01x) |
| Negative: mesh pairs | 6 | Every OBJ pair hashes differently |
| Negative: primitives | 2 | Box vs sphere, cylinder vs cone |
| Negative: sensitivity | 1 | 0.005 shift detectable |
| Guard | 1 | test_meshes/ not empty |

**Signature tests** (`test_sign.py`) — 3 tests

| Test | What it proves |
|---|---|
| `test_end_to_end_verification` | Sign cube.obj → verify returns True |
| `test_tampered_geometry_fails` | Shift one vertex of bunny.obj → verify returns False |
| `test_tampered_signature_fails` | Flip one byte in signature → verify returns False |

## Documentation

Research-level documentation is in `docs/`:

| Document | Content |
|---|---|
| [01-architecture.md](docs/01-architecture.md) | System design, module decomposition, data flow, sidecar format, trust model |
| [02-canonicalization-theory.md](docs/02-canonicalization-theory.md) | Mathematical foundations: PCA alignment proof, sum-of-cubes analysis, distance-path invariance, degeneracy detection, truncation theory |
| [03-post-quantum-signatures.md](docs/03-post-quantum-signatures.md) | ML-DSA-44 / FIPS 204: MLWE/MSIS hardness, Fiat-Shamir with aborts, security parameters, comparison with classical schemes |
| [04-threat-model.md](docs/04-threat-model.md) | Security goals, adversary model, attack surface analysis (8 attack vectors), trust boundaries, precision sensitivity analysis |
| [05-provenance-pipeline.md](docs/05-provenance-pipeline.md) | Design principles, pipeline stages, re-export invariance table, integration patterns (CI/CD, CAS, blockchain, multi-party) |

## API Reference

### `MeshCanonicalizer(mesh: trimesh.Trimesh)`

Constructor. Takes a trimesh object. Deep-copies the input.

**Raises**: `ValueError` — if 0 or 1 vertices.

### `.canonicalize() -> str`

Run the full 6-phase pipeline. Returns a 64-char lowercase hex string (SHA-256).

**Raises**: `ValueError` — if all vertices coincide at the origin.

### `.hash -> str | None`

The hash from the last `canonicalize()` call, or `None`.

### `.vertices -> np.ndarray`

Copy of the internal vertex array.

### `generate_keys(key_dir: Path) -> None`

Generate an ML-DSA-44 keypair. Saves `public.key` and `private.key` to `key_dir`.

### `sign_mesh(mesh_path: Path, private_key_path: Path) -> Path`

Canonicalize a mesh, sign its hash, and write a `.sig.json` sidecar. Returns the sidecar path.

### `verify_mesh(mesh_path: Path, public_key_path: Path, sig_path: Path) -> bool`

Recompute the canonical hash and verify the sidecar signature. Returns `True` if valid.

## Known Limitations

1. **Float64 precision at extreme translations**: At offsets >1e8, centroid subtraction loses enough precision to affect PCA sign disambiguation. Reliable for translations up to ~1e6.

2. **Distance path is O(n²)**: The pairwise-distance fallback computes n(n-1)/2 distances. Only triggers for degenerate eigenvalue meshes (typically <1000 vertices).

3. **Reflection invariance**: Mirror images produce the same hash. Chirality discrimination must be added as a post-processing step if needed.

4. **Vertex-only**: Ignores face connectivity, normals, UVs, and vertex colors.

5. **No timestamp authority**: The sidecar does not include a trusted timestamp. Replay protection requires an external TSA.

6. **No key revocation**: Key lifecycle management (revocation, rotation, certificate chains) is an orthogonal concern.

## Dependencies

| Package | Version | Purpose | Required at runtime? |
|---|---|---|---|
| **numpy** | >= 1.22 | Linear algebra, array ops | Yes |
| **trimesh** | >= 3.0 | Mesh loading (OBJ, STL, PLY, glTF) | Yes |
| **liboqs-python** | matching system liboqs | ML-DSA-44 post-quantum signatures | Yes (for signing/verification) |
| **scipy** | >= 1.7 | `Rotation.random()` for test transforms | Tests only |
| **pytest** | >= 7.0 | Test runner | Tests only |
| **Python** | >= 3.10 | `match` statements, `X \| Y` union types | Yes |

## Logging

Both modules emit `INFO`-level logs:

```python
import logging
logging.basicConfig(level=logging.INFO)
```

```
Phase 1  [Center]       | centroid removed = [-0.027  0.095  0.009]
Phase 2  [Normalize]    | scale divisor = 0.11690855
Phase 3  [PCA]          | eigenvalues (desc) = [0.168 0.085 0.052]
Phase 6a [Hash:coord]   | SHA-256 = b50b58d62243...
Signed bunny.obj  |  hash=b50b58d62243...  |  sidecar=bunny.obj.sig.json
Verified bunny.obj  |  result=True  |  local_hash=b50b58d62243...
```
