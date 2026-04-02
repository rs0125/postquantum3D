# postquantum3D

Cryptographic canonicalization pipeline for 3D meshes. Takes any 3D mesh and produces a deterministic SHA-256 fingerprint that is **invariant to rotation, translation, and uniform scale**.

Two geometrically identical meshes that differ only by how they were exported (different world-space position, orientation, or scale) will always produce the **exact same hash**.

## The Problem

When a 3D mesh passes through an export pipeline — different DCCs (Blender, Maya, Houdini), file formats (OBJ, FBX, glTF), or coordinate conventions (Y-up vs Z-up) — the raw vertex data changes even though the geometry is identical. A mesh translated by `(100, 0, 0)`, scaled by `3x`, and rotated `45` on Y is still the same bunny. But a naive hash of the vertex buffer will be completely different.

This makes it impossible to answer: *"Is this the same mesh I've seen before?"*

## The Solution

`MeshCanonicalizer` strips away every degree of freedom that doesn't affect geometry, one at a time:

```
Phase 1 — Center        Remove 3 DOF (translation)      Subtract centroid
Phase 2 — Normalize     Remove 1 DOF (uniform scale)    Divide by max radius
Phase 3 — PCA Align     Remove 3 DOF (rotation)         Eigenvector alignment
Phase 4 — Truncate      Remove float noise               Floor to 4 decimal places
Phase 5 — Sort          Remove vertex ordering           Lexicographic sort
Phase 6 — Hash          Produce fingerprint              SHA-256
```

The result is a single 64-character hex string that serves as a canonical identity for the mesh geometry.

## Quick Start

```bash
pip install trimesh numpy scipy
```

### Python API

```python
import trimesh
from postquantum3d import MeshCanonicalizer

mesh = trimesh.load("model.obj", force="mesh")
canon = MeshCanonicalizer(mesh)
fingerprint = canon.canonicalize()

print(fingerprint)
# e.g. "b50b58d62243bf2ff5fe1259f0a56389ab4d670f40f1ce5b21ffc4090d7a79f6"
```

### CLI

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

assert h1 == h2  # Identical hashes
```

## How It Works

### Phase 1 — Translation Invariance (Center)

Subtract the centroid from all vertices.

```
V' = V + T  →  V' - mean(V') = V - mean(V)
```

The translation `T` cancels out. The mesh is now centered at the origin.

### Phase 2 — Scale Invariance (Normalize)

Divide all vertices by the maximum Euclidean distance from the origin.

```
(sV) / max(||sV||) = V / max(||V||)
```

The uniform scale factor `s` cancels out. The mesh is now bounded in a unit sphere.

### Phase 3 — Rotation Invariance (PCA Alignment)

Compute the covariance matrix `C = VᵀV / n` and its eigenvectors. Project vertices onto the eigenvector basis to align the mesh to its principal axes.

```
C' = (RV)ᵀ(RV) / n = VᵀRᵀRV / n = VᵀV / n = C
```

The eigenvalues are rotation-invariant, so the alignment undoes any rotation `R`.

**Sign disambiguation**: Eigenvectors are defined up to `±1`. We resolve this by computing `S = Σ(vᵢ · eⱼ)³` for each eigenvector. If `S < 0`, flip the eigenvector. The sum-of-cubes rule is robust to antipodal vertex ties (unlike the simpler argmax rule).

**Degeneracy handling**: When eigenvalues are repeated (perfect cube, sphere, cylinder) or near-zero (coplanar/collinear meshes), PCA cannot produce a stable frame. In these cases, the pipeline switches to a **distance-based invariant path** — see below.

### Phase 4 — Precision Threshold (Truncate)

Truncate all coordinates to 4 decimal places using floor-towards-zero:

```
truncate(x) = sign(x) · floor(|x| · 10⁴) / 10⁴
```

This eliminates floating-point non-determinism from different computation orders. A `+0.0` is added to canonicalize IEEE-754 negative zero.

### Phase 5 — Lexicographic Sort

Sort the vertex array by X, then Y, then Z. This removes dependence on the arbitrary vertex ordering in the source file.

### Phase 6 — SHA-256 Hash

Flatten the sorted vertex array into a comma-separated string and compute its SHA-256 digest.

## Two Hashing Paths

### Coordinate Path (default)

Used when all three eigenvalues of the covariance matrix are distinct and non-zero. This is the common case for organic meshes (characters, scanned objects, terrain).

**Pipeline**: Center → Normalize → PCA Align → Truncate → Sort → Hash coordinates

### Distance Path (fallback)

Used when eigenvalues are degenerate (repeated or near-zero). This triggers for geometrically symmetric shapes like perfect cubes, spheres, cylinders, and tetrahedra, as well as coplanar or collinear vertex sets.

Instead of aligning coordinates (which PCA cannot do stably), we hash a **rotation-invariant descriptor**: the sorted list of all pairwise inter-vertex distances plus origin distances, rounded to 4 decimal places.

Pairwise distances are exactly rotation-invariant: `||Rv_i - Rv_j|| = ||v_i - v_j||`. The ~1e-16 float noise from computing distances on rotated coordinates is safely absorbed by rounding at 1e-4 resolution.

**Pipeline**: Center → Normalize → Detect degeneracy → Hash sorted distances

## What Changes the Hash (and What Doesn't)

| Operation | Hash changes? | Why |
|---|---|---|
| Translation | No | Phase 1 removes it |
| Uniform scale | No | Phase 2 removes it |
| Rotation | No | Phase 3 removes it |
| Reflection (mirror) | No | Sign disambiguation undoes it |
| Vertex reordering | No | Phase 5 sorts vertices |
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
│       └── canonicalize.py          # MeshCanonicalizer (the pipeline)
├── tests/
│   ├── __init__.py
│   ├── test_canonicalize.py         # Invariance tests across 7 OBJ meshes
│   └── test_edge_cases.py           # Edge cases + negative tests (254 tests)
├── test_meshes/                     # OBJ test models
│   ├── armadillo.obj                # Stanford Armadillo   (49,990 verts)
│   ├── bunny.obj                    # Stanford Bunny       (34,834 verts)
│   ├── cube.obj                     # Simple cube          (14 verts)
│   ├── homer.obj                    # Homer Simpson        (6,002 verts)
│   ├── spot.obj                     # Spot the cow         (3,225 verts)
│   ├── suzanne.obj                  # Blender Suzanne      (507 verts)
│   └── teapot.obj                   # Utah Teapot          (3,241 verts)
├── logs/                            # Pipeline logs (gitignored)
├── .gitignore
└── README.md
```

## Running Tests

```bash
# Run all 254 tests
python -m pytest tests/ -v

# Run just the invariance tests (7 meshes × 7 seeds × 4 test types)
python -m pytest tests/test_canonicalize.py -v

# Run just the edge case + negative tests
python -m pytest tests/test_edge_cases.py -v
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

## Known Limitations

1. **Float64 precision at extreme translations**: At offsets >1e8, centroid subtraction loses enough precision (~1e-7) to affect PCA sign disambiguation. The pipeline is reliable for translations up to ~1e6.

2. **Distance path is O(n²)**: The pairwise-distance fallback computes n(n-1)/2 distances. This only triggers for meshes with degenerate eigenvalues (geometric primitives, typically <1000 vertices), so it's fast in practice. Organic meshes always take the O(n) coordinate path.

3. **Reflection invariance**: The pipeline treats a mesh and its mirror image as identical. If chirality discrimination is needed (distinguishing left glove from right glove), it must be added as a post-processing step.

4. **Vertex-only**: The pipeline hashes vertex positions only. It does not consider face connectivity, normals, UVs, or vertex colors. Two meshes with identical vertices but different face topology will hash identically.

## Mathematical Details

### Why PCA Works for Rotation Invariance

The covariance matrix of a point cloud is defined as:

```
C = VᵀV / n
```

where `V` is the `(n, 3)` centered vertex matrix. For any rotation matrix `R`, the rotated cloud `RV` has covariance:

```
C' = (RV)ᵀ(RV) / n = VᵀRᵀRV / n = VᵀV / n = C
```

So `C` and `C'` have identical eigenvalues. The eigenvectors of `C'` are `R` times those of `C`. When we project the rotated vertices onto the eigenvectors of `C'`, the rotation `R` cancels:

```
V_canonical = (RV) @ eigvecs(C') = (RV) @ (R · eigvecs(C)) = V @ eigvecs(C)
```

This is why PCA-aligned coordinates are rotation-invariant.

### Why Sum-of-Cubes Beats Argmax for Sign Disambiguation

The original sign rule was: find the vertex with the largest absolute projection onto eigenvector `eⱼ`, and ensure its projection is positive. This fails when two vertices have equal-magnitude but opposite-sign projections (e.g., `+0.7` and `-0.7`). After rotation, floating-point noise can swap which vertex "wins" the `argmax`, flipping the sign decision.

The sum-of-cubes rule computes:

```
S = Σᵢ (vᵢ · eⱼ)³
```

Cubing preserves sign, amplifies large projections, and sums over all `n` vertices. A single vertex swap cannot flip the sign of a sum over thousands of terms. The rule fails only when `S` is exactly zero (a perfectly antisymmetric distribution), which is handled by an argmax fallback.

### Why the Distance Path is Necessary

When two eigenvalues are equal (e.g., `λ₁ = λ₂`), the corresponding eigenvectors span a 2D eigenspace. Any orthonormal basis of that eigenspace is equally valid. `numpy.linalg.eigh` returns an arbitrary basis that changes depending on the input matrix — and the rotated covariance matrix, while mathematically identical, differs at the ULP level. This makes the eigenvectors unstable:

```
Davis-Kahan bound:  sin(θ) ≤ ||ΔC|| / gap
```

When `gap → 0`, even machine-epsilon perturbations cause large eigenvector rotations. No sign-fixing or moment-based realignment can resolve a continuous `SO(k)` ambiguity with discrete decisions.

The distance path avoids this entirely by never computing a frame. Pairwise distances `||vᵢ - vⱼ||` are exactly rotation-invariant (orthogonal matrices preserve norms). The only noise source is floating-point evaluation of the norm, which is ~1 ULP (~1e-16 for O(1) values) — safely absorbed by rounding at 1e-4.

### Degeneracy Detection Criteria

The pipeline switches to the distance path when any of these hold:

| Condition | Catches | Example |
|---|---|---|
| `\|λᵢ\| < 1e-8` | Near-zero eigenvalue (rank-deficient covariance) | Coplanar mesh, collinear mesh |
| `\|λᵢ - λⱼ\| / max(\|λᵢ\|, \|λⱼ\|) < 1e-6` | Repeated eigenvalues | Perfect cube, sphere, cylinder |

### Truncation vs Rounding

The coordinate path uses **truncation** (floor towards zero):

```
truncate(x) = sign(x) · floor(|x| · 10⁴) / 10⁴
```

Truncation is chosen over rounding because rounding has a midpoint ambiguity: values exactly at `0.5 × 10⁻⁴` can round up or down depending on the rounding mode (banker's rounding, round-half-up, etc.). Truncation has no ambiguity — it always moves towards zero.

The distance path uses **rounding** (`round()`, banker's rounding) because:
1. Distances are always non-negative, avoiding the sign complexity of truncation
2. The midpoint ambiguity is irrelevant — real distances from rotated float coordinates never land exactly on a `0.5 × 10⁻⁴` boundary
3. Rounding has better average-case error than truncation, reducing the chance of a distance crossing a precision boundary

### IEEE-754 Negative Zero

After truncation, values near zero can become `-0.0` (e.g., `sign(-1e-16) · floor(0) / 10⁴ = -0.0`). While `-0.0 == 0.0` in Python arithmetic, their string representations differ: `"-0.0000"` vs `"0.0000"`. Since the hash is computed from the string, this would break determinism.

The fix: add `+0.0` to the entire array after truncation. IEEE-754 guarantees `-0.0 + 0.0 = +0.0`.

## Use Cases

- **Asset deduplication**: Identify duplicate meshes in a large asset library regardless of how they were exported or transformed
- **Content-addressable storage**: Use the hash as a key to store/retrieve mesh data, similar to how Git hashes file contents
- **Change detection**: Compare hashes across pipeline stages to detect whether geometry was actually modified vs just re-exported
- **Provenance tracking**: Establish a canonical identity for a mesh that persists across format conversions and coordinate system changes
- **Mesh comparison in CI/CD**: Automate checks that an export pipeline produces geometrically identical output across versions

## API Reference

### `MeshCanonicalizer(mesh: trimesh.Trimesh)`

Constructor. Takes a trimesh object. The input mesh is deep-copied and never mutated.

**Raises**:
- `ValueError` — if the mesh has 0 vertices ("empty mesh") or 1 vertex ("single-vertex mesh")

### `.canonicalize() -> str`

Run the full 6-phase pipeline. Returns a 64-character lowercase hex string (SHA-256 digest).

**Raises**:
- `ValueError` — if all vertices coincide at the origin after centering ("Degenerate mesh: all vertices coincide at origin")

### `.hash -> str | None`

The hash from the last `canonicalize()` call, or `None` if not yet called.

### `.vertices -> np.ndarray`

A copy of the internal vertex array (which may be in a partially or fully canonicalized state depending on whether `canonicalize()` has been called).

### `PRECISION: int = 4`

Class attribute. Number of decimal places used for truncation (coordinate path) and rounding (distance path). Can be overridden on the class before instantiation.

### Module constant: `EIGEN_TOL: float = 1e-6`

Relative tolerance for eigenvalue degeneracy detection. Two eigenvalues are considered degenerate if their relative difference is below this threshold.

## Logging

The pipeline emits detailed `INFO`-level logs via the `postquantum3d.canonicalize` logger. To see the full phase-by-phase output:

```python
import logging
logging.basicConfig(level=logging.INFO)
```

Example output:

```
Phase 1  [Center]       | centroid removed = [-0.027  0.095  0.009]  |  new centroid magnitude = 5.33e-16
Phase 2  [Normalize]    | scale divisor = 0.11690855  |  new max radius = 1.00000000
Phase 3  [PCA]          | eigenvalues (desc) = [0.168 0.085 0.052]
Phase 3  [sign fix]     | axis 2 flipped  (cube_sum=-3.42e-02)
Phase 4  [Truncate]     | precision = 4 decimal places  |  sample vertex[0] = [ 0.2737  0.118  -0.0399]
Phase 5  [Sort]         | vertices sorted lexicographically  |  first = [-0.7711  0.2226 -0.0463]  |  last = [0.8787 0.3099 0.3205]
Phase 6a [Hash:coord]   | string length = 785466 chars  |  SHA-256 = b50b58d62243...
```

The test suite writes logs to `logs/test_canonicalize.log` for post-run inspection.

## Dependencies

| Package | Version | Purpose | Required at runtime? |
|---|---|---|---|
| **numpy** | >= 1.22 | Linear algebra, array ops | Yes |
| **trimesh** | >= 3.0 | Mesh loading (OBJ, STL, PLY, glTF) | Yes |
| **scipy** | >= 1.7 | `Rotation.random()` for test transforms | Tests only |
| **pytest** | >= 7.0 | Test runner | Tests only |
| **Python** | >= 3.10 | `match` statements, `X \| Y` union types | Yes |
