"""
Cryptographic Canonicalization Pipeline for 3D Meshes
=====================================================

Purpose:
    Transform any 3D mesh into a mathematically deterministic canonical state
    that is invariant to arbitrary rotation, translation, and uniform scale.
    Two geometrically-identical meshes that differ only by a rigid-body
    transform + uniform scale MUST produce the same SHA-256 hash.

Mathematical Foundation:
    The pipeline removes each degree of freedom one at a time:
        Phase 1  – Translation  (3 DOF)  → subtract centroid
        Phase 2  – Scale        (1 DOF)  → normalize to unit sphere
        Phase 3  – Rotation     (3 DOF)  → PCA alignment (coordinate path)
                                           OR distance-based invariant
        Phase 4  – Float noise  (∞ DOF)  → truncate / round to fixed precision
        Phase 5  – Vertex order (n! DOF) → lexicographic sort
        Phase 6  – Hash                  → SHA-256 fingerprint

Two Hashing Paths:
    COORDINATE PATH (default, for non-degenerate eigenvalues):
        PCA aligns the mesh to a canonical frame.  Sign disambiguation
        uses sum-of-cubed-projections.  Then truncate coordinates, sort
        vertices, and hash the coordinate string.

    DISTANCE PATH (fallback, when ANY eigenvalue pair is degenerate):
        PCA cannot produce a stable frame when eigenvalues are repeated.
        Instead of aligning coordinates, we hash a rotation-invariant
        representation: the sorted list of pairwise distances + origin
        distances, rounded to PRECISION decimal places.  Distances are
        exactly preserved by rotation (||Rv_i - Rv_j|| = ||v_i - v_j||),
        with only ULP-level float noise (~1e-15) that is safely absorbed
        by rounding at 1e-4 resolution.
"""

from __future__ import annotations

import hashlib
import logging
from copy import deepcopy
from pathlib import Path

import numpy as np
import trimesh

logger = logging.getLogger(__name__)

# Relative tolerance for treating eigenvalues as degenerate.
EIGEN_TOL = 1e-6


class MeshCanonicalizer:
    """Six-phase canonicalization pipeline for trimesh objects."""

    PRECISION = 4  # decimal places kept after truncation/rounding

    def __init__(self, mesh: trimesh.Trimesh) -> None:
        # Work on a deep copy so the caller's mesh is never mutated.
        self._mesh = deepcopy(mesh)
        self._vertices: np.ndarray = np.array(
            self._mesh.vertices, dtype=np.float64
        )
        self._hash: str | None = None

        # --- Input validation ---
        n = len(self._vertices)
        if n == 0:
            raise ValueError("Cannot canonicalize an empty mesh (0 vertices).")
        if n == 1:
            raise ValueError(
                "Cannot canonicalize a single-vertex mesh (no spatial extent)."
            )

        logger.info(
            "MeshCanonicalizer initialized  |  vertex count = %d", n
        )

    # ------------------------------------------------------------------
    # Phase 1 – Translation Invariance  (subtract centroid)
    # ------------------------------------------------------------------
    # V' = V + T  →  V' - mean(V') = V - mean(V),  independent of T.
    # ------------------------------------------------------------------
    def _phase1_center(self) -> None:
        centroid = self._vertices.mean(axis=0)
        self._vertices -= centroid
        logger.info(
            "Phase 1  [Center]       | centroid removed = %s  |  "
            "new centroid magnitude = %.2e",
            centroid,
            np.linalg.norm(self._vertices.mean(axis=0)),
        )

    # ------------------------------------------------------------------
    # Phase 2 – Scale Invariance  (normalize to unit sphere)
    # ------------------------------------------------------------------
    # (sV) / max(||sV||) = V / max(||V||),  independent of s.
    # ------------------------------------------------------------------
    def _phase2_normalize(self) -> None:
        distances = np.linalg.norm(self._vertices, axis=1)
        max_dist = distances.max()
        if max_dist < 1e-12:
            raise ValueError(
                "Degenerate mesh: all vertices coincide at origin."
            )
        self._vertices /= max_dist
        logger.info(
            "Phase 2  [Normalize]    | scale divisor = %.8f  |  "
            "new max radius = %.8f",
            max_dist,
            np.linalg.norm(self._vertices, axis=1).max(),
        )

    # ------------------------------------------------------------------
    # Phase 3 – Rotation Invariance
    # ------------------------------------------------------------------
    # Returns True if the coordinate path was used (PCA succeeded),
    # False if the distance path must be used instead.
    # ------------------------------------------------------------------
    def _phase3_pca_align(self) -> bool:
        n = len(self._vertices)
        cov = self._vertices.T @ self._vertices / n

        eigenvalues, eigenvectors = np.linalg.eigh(cov)

        # Sort descending so X-axis = largest variance.
        idx = np.argsort(eigenvalues)[::-1]
        eigenvalues = eigenvalues[idx]
        eigenvectors = eigenvectors[:, idx]

        logger.info(
            "Phase 3  [PCA]          | eigenvalues (desc) = %s", eigenvalues
        )

        # --- Check for ANY degeneracy ---
        # The distance path is used whenever PCA cannot produce a stable
        # frame.  This happens in three cases:
        #   (a) Two eigenvalues are relatively close:
        #       |λ_i - λ_j| / max(|λ_i|, |λ_j|, 1e-12) < EIGEN_TOL
        #   (b) ANY eigenvalue is near-zero (rank-deficient covariance):
        #       The corresponding eigenvector spans the null-space and is
        #       arbitrary.  Even if the other eigenvalues are large and
        #       distinct, the near-zero axis is unstable.
        EIGEN_ABS_TOL = 1e-8
        has_degeneracy = False

        # Case (b): any near-zero eigenvalue
        if any(abs(ev) < EIGEN_ABS_TOL for ev in eigenvalues):
            has_degeneracy = True

        # Case (a): any pair of relatively close eigenvalues
        if not has_degeneracy:
            for i in range(3):
                for j in range(i + 1, 3):
                    denom = max(
                        abs(eigenvalues[i]), abs(eigenvalues[j]), 1e-12
                    )
                    if abs(eigenvalues[i] - eigenvalues[j]) / denom < EIGEN_TOL:
                        has_degeneracy = True
                        break
                if has_degeneracy:
                    break

        if has_degeneracy:
            logger.info(
                "Phase 3  [PCA]          | DEGENERATE eigenvalues detected "
                "→ switching to distance-based invariant path"
            )
            return False  # signal: use distance path

        # --- Non-degenerate: PCA alignment is stable ---
        # Robust sign disambiguation via sum of cubed projections.
        # S = Σᵢ (vᵢ · eⱼ)³.  Cubing preserves sign, amplifies extreme
        # vertices, and sums over ALL vertices — immune to antipodal ties.
        for j in range(3):
            projections = self._vertices @ eigenvectors[:, j]
            cube_sum = np.sum(projections ** 3)
            if cube_sum < 0:
                eigenvectors[:, j] *= -1
                logger.info(
                    "Phase 3  [sign fix]     | axis %d flipped  "
                    "(cube_sum=%.6e)",
                    j,
                    cube_sum,
                )
            elif cube_sum == 0.0:
                # Perfectly antisymmetric — argmax fallback.
                max_abs_idx = np.argmax(np.abs(projections))
                if projections[max_abs_idx] < 0:
                    eigenvectors[:, j] *= -1
                    logger.info(
                        "Phase 3  [sign fix]     | axis %d flipped "
                        "via argmax fallback",
                        j,
                    )

        self._vertices = self._vertices @ eigenvectors
        return True  # signal: use coordinate path

    # ------------------------------------------------------------------
    # Phase 4 – Precision Threshold  (deterministic truncation)
    # ------------------------------------------------------------------
    # truncate(x, d) = sign(x) · floor(|x| · 10^d) / 10^d
    # Then +0.0 to canonicalize -0.0 → +0.0.
    # ------------------------------------------------------------------
    def _phase4_truncate(self) -> None:
        factor = 10 ** self.PRECISION
        self._vertices = (
            np.sign(self._vertices)
            * np.floor(np.abs(self._vertices) * factor)
            / factor
        )
        self._vertices += 0.0
        logger.info(
            "Phase 4  [Truncate]     | precision = %d decimal places  |  "
            "sample vertex[0] = %s",
            self.PRECISION,
            self._vertices[0],
        )

    # ------------------------------------------------------------------
    # Phase 5 – Lexicographic Sorting
    # ------------------------------------------------------------------
    def _phase5_sort(self) -> None:
        order = np.lexsort(
            (
                self._vertices[:, 2],
                self._vertices[:, 1],
                self._vertices[:, 0],
            )
        )
        self._vertices = self._vertices[order]
        logger.info(
            "Phase 5  [Sort]         | vertices sorted lexicographically  |  "
            "first = %s  |  last = %s",
            self._vertices[0],
            self._vertices[-1],
        )

    # ------------------------------------------------------------------
    # Phase 6a – Coordinate-based Hash  (SHA-256 of sorted coordinates)
    # ------------------------------------------------------------------
    def _phase6_hash_coordinates(self) -> str:
        flat = self._vertices.flatten()
        canonical_str = ",".join(
            f"{v:.{self.PRECISION}f}" for v in flat
        )
        digest = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
        logger.info(
            "Phase 6a [Hash:coord]   | string length = %d chars  |  "
            "SHA-256 = %s",
            len(canonical_str),
            digest,
        )
        return digest

    # ------------------------------------------------------------------
    # Phase 6b – Distance-based Hash  (SHA-256 of sorted distances)
    # ------------------------------------------------------------------
    # When eigenvalues are degenerate, PCA cannot produce a stable frame.
    # Instead, hash a rotation-invariant descriptor: the sorted lists of
    # (a) distances from origin, and (b) pairwise inter-vertex distances.
    #
    # Distances are exactly rotation-invariant: ||Rv|| = ||v|| and
    # ||Rv_i - Rv_j|| = ||v_i - v_j||.  Float noise is ~1 ULP (~1e-16
    # for O(1) values), which is safely absorbed by rounding at 1e-4.
    #
    # We use Python's built-in round() which does banker's rounding
    # (round-half-to-even).  This is deterministic and the midpoint
    # ambiguity is irrelevant because real distances never land exactly
    # on a 0.5 × 10^{-PRECISION} boundary (they'd need to be exact
    # decimal fractions of sqrt sums — probability zero).
    # ------------------------------------------------------------------
    def _phase6_hash_distances(self) -> str:
        V = self._vertices
        n = len(V)
        p = self.PRECISION

        # Origin distances, rounded and sorted.
        origin_dists = np.linalg.norm(V, axis=1)
        origin_rounded = sorted(round(float(d), p) for d in origin_dists)

        # Pairwise distances (upper triangle), rounded and sorted.
        # For large meshes this is O(n²) — acceptable because the distance
        # path is only triggered for meshes with degenerate eigenvalues,
        # which in practice are small geometric primitives.
        pair_dists: list[float] = []
        for i in range(n):
            diff = V[i + 1 :] - V[i]
            dists = np.linalg.norm(diff, axis=1)
            pair_dists.extend(round(float(d), p) for d in dists)
        pair_dists.sort()

        # Build the hash string: prefix with "D:" to distinguish from
        # coordinate hashes (so a non-degenerate and degenerate mesh with
        # coincidentally similar data don't collide).
        parts = (
            ["D:"]
            + [f"{d:.{p}f}" for d in origin_rounded]
            + [f"{d:.{p}f}" for d in pair_dists]
        )
        canonical_str = ",".join(parts)
        digest = hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
        logger.info(
            "Phase 6b [Hash:dist]    | origin_dists=%d  pair_dists=%d  |  "
            "string length = %d chars  |  SHA-256 = %s",
            len(origin_rounded),
            len(pair_dists),
            len(canonical_str),
            digest,
        )
        return digest

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def canonicalize(self) -> str:
        """Run the full canonicalization pipeline and return a SHA-256 hash."""
        logger.info("=" * 72)
        logger.info("BEGIN canonicalization pipeline")
        logger.info("=" * 72)

        self._phase1_center()
        self._phase2_normalize()
        use_coordinate_path = self._phase3_pca_align()

        if use_coordinate_path:
            self._phase4_truncate()
            self._phase5_sort()
            self._hash = self._phase6_hash_coordinates()
        else:
            # Distance path — phases 4/5 are not needed (distances are
            # rotation-invariant; rounding + sorting happen inside 6b).
            self._hash = self._phase6_hash_distances()

        logger.info("=" * 72)
        logger.info("END canonicalization  |  final hash = %s", self._hash)
        logger.info("=" * 72)
        return self._hash

    @property
    def hash(self) -> str | None:
        """Return the hash computed by the last canonicalize() call."""
        return self._hash

    @property
    def vertices(self) -> np.ndarray:
        """Return a copy of the current (possibly canonicalized) vertices."""
        return self._vertices.copy()


# ------------------------------------------------------------------
# Convenience: run from CLI   →   python canonicalize.py mesh.obj
# ------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
    )

    if len(sys.argv) < 2:
        print("Usage: python canonicalize.py <mesh.obj>")
        sys.exit(1)

    mesh_path = Path(sys.argv[1])
    mesh = trimesh.load(str(mesh_path), force="mesh")
    canon = MeshCanonicalizer(mesh)
    result = canon.canonicalize()
    print(f"\nCanonical SHA-256:  {result}")
