# Geometric Canonicalization Theory

## Problem Statement

A 3D mesh is defined by a set of vertex positions $V = \{v_1, v_2, \ldots, v_n\} \subset \mathbb{R}^3$ together with face connectivity. When the same mesh passes through different export pipelines — different DCCs (Blender, Maya, Houdini), file formats (OBJ, FBX, glTF), or coordinate conventions (Y-up vs Z-up) — the raw vertex data changes under a similarity transform:

$$V' = s \cdot R \cdot V + t$$

where $s \in \mathbb{R}^+$ is a uniform scale, $R \in O(3)$ is an orthogonal matrix (rotation or improper rotation), and $t \in \mathbb{R}^3$ is a translation. The mesh geometry is identical, but a bitwise hash of the vertex buffer will differ.

**Goal**: Define a function $\mathcal{H} : \mathcal{M} \to \{0,1\}^{256}$ such that

$$\mathcal{H}(V) = \mathcal{H}(s \cdot R \cdot V + t) \quad \forall s > 0,\; R \in O(3),\; t \in \mathbb{R}^3$$

while maintaining collision resistance: geometrically distinct meshes should produce distinct hashes with overwhelming probability.

## Degrees of Freedom

The similarity group $\text{Sim}(3)$ in three dimensions has 7 continuous degrees of freedom:

| DOF | Group | Parameters |
|---|---|---|
| Translation | $\mathbb{R}^3$ | 3 |
| Rotation | $SO(3)$ | 3 |
| Uniform scale | $\mathbb{R}^+$ | 1 |

Additionally, there is a discrete degree of freedom from reflection ($\det(R) = -1$), and the combinatorial degree of freedom from vertex ordering ($n!$ permutations).

The canonicalization pipeline removes these one at a time.

## Phase 1: Translation Invariance

**Operation**: Subtract the centroid $\bar{v} = \frac{1}{n}\sum_{i=1}^n v_i$.

**Proof**: For translated vertices $V' = V + t$:

$$\bar{v}' = \frac{1}{n}\sum (v_i + t) = \bar{v} + t$$

$$v_i' - \bar{v}' = (v_i + t) - (\bar{v} + t) = v_i - \bar{v}$$

The centroid-subtracted vertices are independent of $t$. This removes 3 DOF.

## Phase 2: Scale Invariance

**Operation**: Divide all centered vertices by $r_{\max} = \max_i \|v_i - \bar{v}\|$.

**Proof**: For scaled vertices $V' = s \cdot V$ (already centered):

$$r'_{\max} = \max_i \|s \cdot v_i\| = s \cdot r_{\max}$$

$$\frac{s \cdot v_i}{s \cdot r_{\max}} = \frac{v_i}{r_{\max}}$$

The normalized vertices are independent of $s$. This removes 1 DOF.

**Singularity**: If $r_{\max} = 0$, all vertices coincide at the origin. The pipeline raises `ValueError` — a degenerate mesh with no spatial extent cannot be meaningfully hashed.

## Phase 3: Rotation Invariance

This is the most complex phase and has two sub-strategies depending on the spectral properties of the vertex covariance matrix.

### Covariance Matrix

For centered vertices arranged as an $(n \times 3)$ matrix $V$, define:

$$C = \frac{1}{n} V^T V$$

$C$ is a $3 \times 3$ real symmetric positive semi-definite matrix. Its eigendecomposition is $C = E \Lambda E^T$ where $\Lambda = \text{diag}(\lambda_1, \lambda_2, \lambda_3)$ and $E = [e_1 \; e_2 \; e_3]$ is an orthogonal matrix of eigenvectors.

### Rotation Invariance of Eigenvalues

For rotated vertices $V' = V R^T$ (right-multiplication convention for row-vector layout):

$$C' = \frac{1}{n} (VR^T)^T (VR^T) = \frac{1}{n} R V^T V R^T = R C R^T$$

The eigenvalues of $C'$ are identical to those of $C$ (similarity transform preserves spectrum). The eigenvectors of $C'$ are $R \cdot e_i$. This means:

$$V' \cdot E' = V R^T \cdot R E = V E$$

Projecting rotated vertices onto rotated eigenvectors recovers the original projection. The PCA-aligned coordinates are rotation-invariant.

### Coordinate Path (Non-Degenerate Case)

When all three eigenvalues are **distinct and non-zero**, the eigenvectors are uniquely determined up to sign. The sign ambiguity is resolved by the **sum-of-cubes rule**:

$$S_j = \sum_{i=1}^n (v_i \cdot e_j)^3$$

If $S_j < 0$, flip $e_j \to -e_j$. If $S_j = 0$ (perfectly antisymmetric distribution — probability zero for real meshes), fall back to an argmax rule.

**Why cubes instead of the simpler $\sum (v_i \cdot e_j)$?**

The first-moment sum $\sum (v_i \cdot e_j) = 0$ always, because the vertices are centered. The second moment $\sum (v_i \cdot e_j)^2 = n \lambda_j$ is always positive, carrying no sign information. The third moment (sum of cubes) is the lowest odd moment that is non-trivially sign-sensitive.

Furthermore, cubing amplifies large projections relative to small ones, making the sum dominated by the "extremal" vertices of the mesh. This is far more robust than the argmax rule (which depends on a single vertex and is fragile to antipodal ties).

### Distance Path (Degenerate Case)

When eigenvalues are **repeated** or **near-zero**, PCA cannot produce a stable frame:

**Repeated eigenvalues** ($\lambda_i \approx \lambda_j$): The corresponding eigenvectors span a $k$-dimensional eigenspace. Any orthonormal basis of this eigenspace is equally valid, and `numpy.linalg.eigh` returns an arbitrary one that is sensitive to ULP-level perturbations in the input. The Davis-Kahan $\sin\theta$ theorem quantifies this:

$$\sin\theta(E, \hat{E}) \leq \frac{\|\Delta C\|}{\text{gap}}$$

where $\text{gap} = \min_{i \neq j} |\lambda_i - \lambda_j|$. As $\text{gap} \to 0$, even machine-epsilon perturbations cause $O(1)$ eigenvector rotations.

**Near-zero eigenvalues** ($|\lambda_i| < \epsilon$): The corresponding eigenvector direction is effectively arbitrary — it spans the null space of the covariance. Even if the other eigenvalues are large and distinct, one unstable axis contaminates the entire frame.

**Solution**: Hash a rotation-invariant descriptor that never requires a coordinate frame. Pairwise inter-vertex distances are exactly rotation-invariant:

$$\|R v_i - R v_j\| = \|R(v_i - v_j)\| = \|v_i - v_j\|$$

because orthogonal matrices preserve norms. The descriptor consists of:

1. **Origin distances**: $\{d_i = \|v_i\|\}_{i=1}^n$, sorted.
2. **Pairwise distances**: $\{d_{ij} = \|v_i - v_j\|\}_{i < j}$, sorted.

Both are rounded to $10^{-4}$ precision (PRECISION = 4) and hashed with a `"D:"` prefix to prevent hash collisions between the two paths.

**Complexity**: The pairwise distance computation is $O(n^2)$. This is acceptable because the distance path only triggers for geometrically degenerate meshes (cubes, spheres, cylinders), which in practice have far fewer vertices than organic meshes.

### Degeneracy Detection Criteria

| Condition | Threshold | Rationale |
|---|---|---|
| $\|\lambda_i\| < 10^{-8}$ | Absolute | Near-zero eigenvalue: null-space eigenvector is arbitrary |
| $\frac{\|\lambda_i - \lambda_j\|}{\max(\|\lambda_i\|, \|\lambda_j\|)} < 10^{-6}$ | Relative | Repeated eigenvalues: eigenspace basis is arbitrary |

The relative threshold $10^{-6}$ is set conservatively above the IEEE-754 double precision unit roundoff ($\sim 10^{-16}$) to account for accumulated floating-point error in the covariance computation.

## Phase 4: Truncation

**Operation**: Truncate each coordinate to 4 decimal places:

$$\text{trunc}(x) = \text{sign}(x) \cdot \lfloor |x| \cdot 10^4 \rfloor / 10^4$$

Then add $+0.0$ to canonicalize IEEE-754 negative zero ($-0.0 + 0.0 = +0.0$).

**Rationale**: After PCA alignment, two mathematically-identical meshes may differ at the ULP level (~$10^{-16}$) due to different floating-point evaluation orders. Truncation at $10^{-4}$ absorbs this noise while preserving geometric detail at the sub-millimeter level (for unit-sphere normalized meshes).

**Why truncation instead of rounding?** Rounding has a midpoint ambiguity: a value exactly at $k + 0.5 \times 10^{-4}$ may round up or down depending on the rounding mode (even/odd, towards positive infinity, etc.). Truncation towards zero has no ambiguity — it always floors $|x|$.

## Phase 5: Lexicographic Sort

**Operation**: Sort the vertex array by $(x, y, z)$ in lexicographic order.

This removes the $n!$ permutation degree of freedom from vertex ordering. After truncation, vertex coordinates are discrete-valued, so the sort is deterministic.

## Phase 6: SHA-256

**Coordinate path**: Flatten the sorted vertex array and format as a comma-separated string:

```
"0.1234,0.5678,0.9012,0.1235,..."
```

Compute `SHA-256(string.encode("utf-8"))`.

**Distance path**: Concatenate the `"D:"` prefix, sorted origin distances, and sorted pairwise distances as a comma-separated string. Compute SHA-256.

## Collision Resistance

The pipeline's collision resistance rests on two foundations:

1. **Geometric separability**: Two meshes with different geometry (after removing similarity-transform DOF) must produce different pre-hash strings. The truncation precision ($10^{-4}$) bounds the minimum detectable geometric difference: a vertex displacement of $> 0.5 \times 10^{-4}$ in the unit-sphere-normalized frame is guaranteed to change at least one coordinate in the pre-hash string.

2. **SHA-256 collision resistance**: Given distinct pre-hash strings, SHA-256 provides $2^{128}$ collision resistance — no known attack can find two distinct inputs with the same digest.

The overall collision probability is bounded by the geometric precision threshold. For meshes differing by more than $\sim 5 \times 10^{-5}$ relative to the bounding sphere, the pipeline guarantees distinct hashes (assuming SHA-256 is collision-free).

## Limitations

1. **Reflection invariance**: The pipeline uses $O(3)$ (including improper rotations) rather than $SO(3)$. A mesh and its mirror image produce the same hash. This is by design for export-pipeline invariance (some DCCs flip handedness), but prevents chirality discrimination.

2. **Vertex-only**: The pipeline ignores face connectivity, normals, UVs, and vertex colors. Two meshes with identical vertex positions but different topology hash identically.

3. **Precision floor**: Geometric differences smaller than $5 \times 10^{-5}$ relative to the bounding sphere are invisible to the pipeline.

4. **Float64 limits at extreme translations**: At offsets $> 10^8$, centroid subtraction loses enough precision ($\sim 10^{-7}$) to affect PCA sign disambiguation.
