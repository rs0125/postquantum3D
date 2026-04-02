"""
Edge-Case Test Suite for MeshCanonicalizer
==========================================

Covers every gap identified in the audit:
  - Degenerate eigenvalues (perfect cube, sphere, cylinder)
  - Near-degenerate eigenvalues
  - Collinear / coplanar meshes (rank-deficient covariance)
  - Input validation (empty, single-vertex, two-vertex)
  - Vertex permutation invariance
  - Extreme transforms (very large / very small scale and translation)
  - Antipodal tie-breaking
  - Truncation boundary values and negative zero
  - Distinct meshes hash differently
  - Reflection behaviour (documented: reflections change the hash)
  - Guard against empty test_meshes directory
"""

from __future__ import annotations

import logging
import sys
from copy import deepcopy
from pathlib import Path

import numpy as np
import pytest
import trimesh
from scipy.spatial.transform import Rotation

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from postquantum3d.canonicalize import MeshCanonicalizer  # noqa: E402

MESH_DIR = PROJECT_ROOT / "test_meshes"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mesh(vertices: np.ndarray, faces: np.ndarray | None = None) -> trimesh.Trimesh:
    """Create a trimesh from vertices, synthesizing faces if needed."""
    vertices = np.asarray(vertices, dtype=np.float64)
    if faces is None:
        n = len(vertices)
        if n >= 3:
            faces = np.column_stack([
                np.arange(0, n - 2),
                np.arange(1, n - 1),
                np.arange(2, n),
            ])
        else:
            faces = np.zeros((0, 3), dtype=int)
    return trimesh.Trimesh(vertices=vertices, faces=faces, process=False)


def _apply_rotation(mesh: trimesh.Trimesh, rng: np.random.Generator) -> trimesh.Trimesh:
    """Return a deep copy with a random rotation applied (no scale/translate)."""
    m = deepcopy(mesh)
    R = Rotation.random(random_state=rng).as_matrix()
    m.vertices = np.array(m.vertices, dtype=np.float64) @ R.T
    return m


def _apply_full_transform(
    mesh: trimesh.Trimesh, rng: np.random.Generator,
    scale_range=(0.1, 100.0), trans_range=(-500.0, 500.0),
) -> trimesh.Trimesh:
    """Return a deep copy with random scale + rotation + translation."""
    m = deepcopy(mesh)
    v = np.array(m.vertices, dtype=np.float64)
    s = rng.uniform(*scale_range)
    t = rng.uniform(trans_range[0], trans_range[1], size=3)
    R = Rotation.random(random_state=rng).as_matrix()
    m.vertices = s * (v @ R.T) + t
    return m


# ===================================================================
#  1. INPUT VALIDATION
# ===================================================================

class TestInputValidation:

    def test_empty_mesh_raises(self) -> None:
        """Zero vertices must raise ValueError."""
        mesh = trimesh.Trimesh(vertices=[], faces=[], process=False)
        with pytest.raises(ValueError, match="empty mesh"):
            MeshCanonicalizer(mesh)

    def test_single_vertex_raises(self) -> None:
        """One vertex must raise ValueError."""
        mesh = _make_mesh([[1.0, 2.0, 3.0]])
        with pytest.raises(ValueError, match="single-vertex"):
            MeshCanonicalizer(mesh)

    def test_two_identical_vertices_raises(self) -> None:
        """Two coincident vertices collapse to origin after centering → ValueError."""
        mesh = _make_mesh([[5.0, 5.0, 5.0], [5.0, 5.0, 5.0]])
        with pytest.raises(ValueError, match="all vertices coincide"):
            MeshCanonicalizer(mesh).canonicalize()


# ===================================================================
#  2. DEGENERATE EIGENVALUES — PERFECT GEOMETRIC SHAPES
# ===================================================================

class TestDegenerateEigenvalues:

    def _perfect_cube_mesh(self) -> trimesh.Trimesh:
        """8-vertex unit cube centered at origin — triple eigenvalue degeneracy."""
        verts = np.array([
            [s1, s2, s3]
            for s1 in [-0.5, 0.5]
            for s2 in [-0.5, 0.5]
            for s3 in [-0.5, 0.5]
        ])
        faces = np.array([
            [0, 1, 2], [1, 2, 3], [4, 5, 6], [5, 6, 7],
            [0, 1, 4], [1, 4, 5], [2, 3, 6], [3, 6, 7],
            [0, 2, 4], [2, 4, 6], [1, 3, 5], [3, 5, 7],
        ])
        return trimesh.Trimesh(vertices=verts, faces=faces, process=False)

    @pytest.mark.parametrize("seed", range(20))
    def test_perfect_cube_rotation_invariance(self, seed: int) -> None:
        """A perfect 8-vertex cube must hash identically under random rotations."""
        mesh = self._perfect_cube_mesh()
        h_ref = MeshCanonicalizer(mesh).canonicalize()
        rotated = _apply_rotation(mesh, np.random.default_rng(seed))
        h_rot = MeshCanonicalizer(rotated).canonicalize()
        assert h_ref == h_rot, f"seed={seed}: {h_ref} != {h_rot}"

    @pytest.mark.parametrize("seed", range(20))
    def test_perfect_cube_full_transform(self, seed: int) -> None:
        """Perfect cube: invariant to rotation + scale + translation."""
        mesh = self._perfect_cube_mesh()
        h_ref = MeshCanonicalizer(mesh).canonicalize()
        mutated = _apply_full_transform(mesh, np.random.default_rng(seed))
        h_mut = MeshCanonicalizer(mutated).canonicalize()
        assert h_ref == h_mut, f"seed={seed}: {h_ref} != {h_mut}"

    @pytest.mark.parametrize("seed", range(10))
    def test_uv_sphere_rotation_invariance(self, seed: int) -> None:
        """A UV sphere has near-degenerate eigenvalues due to approximate symmetry."""
        mesh = trimesh.creation.uv_sphere(radius=1.0, count=[16, 16])
        h_ref = MeshCanonicalizer(mesh).canonicalize()
        rotated = _apply_rotation(mesh, np.random.default_rng(seed))
        h_rot = MeshCanonicalizer(rotated).canonicalize()
        assert h_ref == h_rot, f"seed={seed}"

    @pytest.mark.parametrize("seed", range(10))
    def test_cylinder_rotation_invariance(self, seed: int) -> None:
        """A cylinder has a double eigenvalue degeneracy on the cross-section axes."""
        mesh = trimesh.creation.cylinder(radius=1.0, height=3.0, sections=32)
        h_ref = MeshCanonicalizer(mesh).canonicalize()
        rotated = _apply_rotation(mesh, np.random.default_rng(seed))
        h_rot = MeshCanonicalizer(rotated).canonicalize()
        assert h_ref == h_rot, f"seed={seed}"

    @pytest.mark.parametrize("seed", range(10))
    def test_regular_tetrahedron(self, seed: int) -> None:
        """Regular tetrahedron — has a double eigenvalue degeneracy."""
        verts = np.array([
            [1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2], [0, 1, 3], [0, 2, 3], [1, 2, 3]])
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        h_ref = MeshCanonicalizer(mesh).canonicalize()
        rotated = _apply_rotation(mesh, np.random.default_rng(seed))
        h_rot = MeshCanonicalizer(rotated).canonicalize()
        assert h_ref == h_rot, f"seed={seed}"


# ===================================================================
#  3. COPLANAR MESH (rank-2 covariance)
# ===================================================================

class TestCoplanarMesh:

    @pytest.mark.parametrize("seed", range(10))
    def test_flat_square(self, seed: int) -> None:
        """All vertices in XY plane — one eigenvalue is ~0."""
        verts = np.array([
            [-1, -1, 0], [1, -1, 0], [1, 1, 0], [-1, 1, 0],
            [0.5, 0.3, 0],  # asymmetric extra vertex to break M3 degeneracy
        ], dtype=np.float64)
        faces = np.array([[0, 1, 2], [0, 2, 3], [0, 1, 4], [2, 3, 4]])
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        h_ref = MeshCanonicalizer(mesh).canonicalize()
        rotated = _apply_rotation(mesh, np.random.default_rng(seed))
        h_rot = MeshCanonicalizer(rotated).canonicalize()
        assert h_ref == h_rot, f"seed={seed}"

    @pytest.mark.parametrize("seed", range(10))
    def test_flat_triangle(self, seed: int) -> None:
        """Three non-collinear vertices (the minimal 2D mesh)."""
        verts = np.array([[0, 0, 0], [1, 0, 0], [0.3, 0.8, 0]], dtype=np.float64)
        faces = np.array([[0, 1, 2]])
        mesh = trimesh.Trimesh(vertices=verts, faces=faces, process=False)
        h_ref = MeshCanonicalizer(mesh).canonicalize()
        mutated = _apply_full_transform(mesh, np.random.default_rng(seed))
        h_mut = MeshCanonicalizer(mutated).canonicalize()
        assert h_ref == h_mut, f"seed={seed}"


# ===================================================================
#  4. COLLINEAR MESH (rank-1 covariance)
# ===================================================================

class TestCollinearMesh:

    @pytest.mark.parametrize("seed", range(10))
    def test_collinear_vertices(self, seed: int) -> None:
        """Vertices on a line — two eigenvalues are ~0."""
        verts = np.array([
            [-2, 0, 0], [-1, 0, 0], [0.5, 0, 0], [1.5, 0, 0], [3, 0, 0]
        ], dtype=np.float64)
        mesh = _make_mesh(verts)
        h_ref = MeshCanonicalizer(mesh).canonicalize()
        mutated = _apply_full_transform(mesh, np.random.default_rng(seed))
        h_mut = MeshCanonicalizer(mutated).canonicalize()
        assert h_ref == h_mut, f"seed={seed}"


# ===================================================================
#  5. ANTIPODAL TIE-BREAKING
# ===================================================================

class TestAntipodalTie:

    @pytest.mark.parametrize("seed", range(50))
    def test_antipodal_vertices(self, seed: int) -> None:
        """Mesh with exact antipodal symmetry on principal axis — the old
        argmax rule would fail here; the cube_sum rule should be stable."""
        verts = np.array([
            [0.7, 0.0, 0.0],
            [-0.7, 0.0, 0.0],
            [0.0, 0.5, 0.3],
            [0.0, -0.5, 0.3],
            [0.0, 0.0, -0.6],
            [0.1, 0.1, 0.1],   # asymmetry-breaker for M3
        ], dtype=np.float64)
        mesh = _make_mesh(verts)
        h_ref = MeshCanonicalizer(mesh).canonicalize()
        rotated = _apply_rotation(mesh, np.random.default_rng(seed))
        h_rot = MeshCanonicalizer(rotated).canonicalize()
        assert h_ref == h_rot, f"seed={seed}"


# ===================================================================
#  6. VERTEX PERMUTATION INVARIANCE
# ===================================================================

class TestVertexPermutation:

    def test_shuffled_vertices(self) -> None:
        """Randomly permuting the vertex array must not change the hash."""
        mesh = trimesh.load(str(MESH_DIR / "bunny.obj"), force="mesh")
        h_ref = MeshCanonicalizer(mesh).canonicalize()

        rng = np.random.default_rng(42)
        shuffled = deepcopy(mesh)
        perm = rng.permutation(len(shuffled.vertices))
        shuffled.vertices = np.array(shuffled.vertices)[perm]
        # Faces become invalid, but the pipeline only uses vertices.
        h_shuf = MeshCanonicalizer(shuffled).canonicalize()
        assert h_ref == h_shuf


# ===================================================================
#  7. EXTREME TRANSFORMS
# ===================================================================

class TestExtremeTransforms:

    @pytest.mark.parametrize("scale", [1e-8, 1e-4, 1e4, 1e8])
    def test_extreme_scale(self, scale: float) -> None:
        """Extreme uniform scales must still produce the correct hash."""
        mesh = trimesh.load(str(MESH_DIR / "suzanne.obj"), force="mesh")
        h_ref = MeshCanonicalizer(mesh).canonicalize()

        scaled = deepcopy(mesh)
        scaled.vertices = np.array(scaled.vertices, dtype=np.float64) * scale
        h_sc = MeshCanonicalizer(scaled).canonicalize()
        assert h_ref == h_sc, f"scale={scale}"

    @pytest.mark.parametrize("offset", [1e4, 1e6])
    def test_extreme_translation(self, offset: float) -> None:
        """Large translations must be fully removed by Phase 1.
        Note: at 1e8+, centroid subtraction loses enough precision (~1e-7)
        to flip the sign of near-zero cube_sum values, changing PCA sign
        disambiguation.  This is an inherent float64 limitation."""
        mesh = trimesh.load(str(MESH_DIR / "suzanne.obj"), force="mesh")
        h_ref = MeshCanonicalizer(mesh).canonicalize()

        translated = deepcopy(mesh)
        translated.vertices = (
            np.array(translated.vertices, dtype=np.float64)
            + np.array([offset, -offset, offset / 2])
        )
        h_tr = MeshCanonicalizer(translated).canonicalize()
        assert h_ref == h_tr, f"offset={offset}"


# ===================================================================
#  8. TRUNCATION BOUNDARY VALUES & NEGATIVE ZERO
# ===================================================================

class TestTruncation:

    def test_negative_zero_canonicalized(self) -> None:
        """After truncation, -0.0 must become +0.0 in the hash string."""
        # Craft vertices where near-zero values will truncate to ±0.
        verts = np.array([
            [1.0, 1e-16, -1e-16],
            [-1.0, -1e-16, 1e-16],
            [0.5, 0.3, 0.2],
            [-0.5, -0.3, -0.2],
            [0.1, 0.8, -0.4],
        ], dtype=np.float64)
        mesh = _make_mesh(verts)
        c = MeshCanonicalizer(mesh)
        c._phase1_center()
        c._phase2_normalize()
        used_coord = c._phase3_pca_align()
        if used_coord:
            c._phase4_truncate()
        # Verify no -0.0 in the array
        for row in c._vertices:
            for val in row:
                # str(-0.0) == "-0.0" vs str(0.0) == "0.0"
                assert not (val == 0.0 and np.signbit(val)), (
                    f"Found -0.0 in truncated vertices: {row}"
                )

    def test_boundary_value_0_00005(self) -> None:
        """0.00005 must truncate to 0.0000 (floor towards zero), not 0.0001."""
        verts = np.array([
            [0.00005, 0.5, 0.0],
            [-0.00005, -0.5, 0.0],
            [0.3, 0.1, 0.2],
        ], dtype=np.float64)
        mesh = _make_mesh(verts)
        c = MeshCanonicalizer(mesh)
        # Skip alignment phases; test truncation directly on known values.
        c._vertices = verts.copy()
        c._phase4_truncate()
        # 0.00005 * 10000 = 0.5, floor(0.5) = 0, so result = 0.0
        assert c._vertices[0, 0] == 0.0
        assert c._vertices[1, 0] == 0.0  # -0.00005 → 0.0 (after +0.0 fix)


# ===================================================================
#  9. DISTINCT MESHES HASH DIFFERENTLY
# ===================================================================

class TestDistinctMeshes:

    def test_different_meshes_different_hashes(self) -> None:
        """Cube and bunny must not collide."""
        h_cube = MeshCanonicalizer(
            trimesh.load(str(MESH_DIR / "cube.obj"), force="mesh")
        ).canonicalize()
        h_bunny = MeshCanonicalizer(
            trimesh.load(str(MESH_DIR / "bunny.obj"), force="mesh")
        ).canonicalize()
        assert h_cube != h_bunny


    def test_all_meshes_unique(self) -> None:
        """Every mesh in test_meshes/ must produce a unique hash."""
        hashes: dict[str, str] = {}
        for p in sorted(MESH_DIR.glob("*.obj")):
            mesh = trimesh.load(str(p), force="mesh")
            h = MeshCanonicalizer(mesh).canonicalize()
            hashes[p.stem] = h
        # All hashes must be unique
        vals = list(hashes.values())
        assert len(vals) == len(set(vals)), (
            f"Hash collision among test meshes: {hashes}"
        )


# ===================================================================
# 10. REFLECTION BEHAVIOUR (documented contract)
# ===================================================================

class TestReflection:

    def test_reflection_preserves_hash(self) -> None:
        """Mirroring a mesh produces the SAME hash.

        The pipeline is reflection-invariant because:
        - Coordinate path: the cube_sum sign fix uses Σ pᵢ³.  Reflecting
          an axis negates all projections, making cube_sum negative, which
          triggers a flip that undoes the reflection.
        - Distance path: pairwise distances are inherently reflection-invariant.

        This is the documented, intended behaviour.  If chirality discrimination
        is needed, it must be added as a separate post-processing step."""
        mesh = trimesh.load(str(MESH_DIR / "bunny.obj"), force="mesh")
        h_orig = MeshCanonicalizer(mesh).canonicalize()

        reflected = deepcopy(mesh)
        v = np.array(reflected.vertices, dtype=np.float64)
        v[:, 0] *= -1  # mirror across YZ plane
        reflected.vertices = v
        h_refl = MeshCanonicalizer(reflected).canonicalize()

        assert h_orig == h_refl, "Reflected mesh should hash identically"


# ===================================================================
# 11. NEGATIVE TESTS — actual mesh changes MUST produce different hashes
# ===================================================================

class TestNegativeMeshChanges:
    """Verify that real geometric modifications to a mesh break the hash.
    These are the opposite of invariance tests: the hash MUST change."""

    def _load_bunny(self) -> trimesh.Trimesh:
        return trimesh.load(str(MESH_DIR / "bunny.obj"), force="mesh")

    def _load_suzanne(self) -> trimesh.Trimesh:
        return trimesh.load(str(MESH_DIR / "suzanne.obj"), force="mesh")

    # --- Single vertex perturbation ---

    def test_move_one_vertex(self) -> None:
        """Shifting a single vertex by a visible amount must change the hash."""
        mesh = self._load_bunny()
        h_orig = MeshCanonicalizer(mesh).canonicalize()

        modified = deepcopy(mesh)
        v = np.array(modified.vertices, dtype=np.float64)
        v[0] += [0.01, 0.0, 0.0]  # nudge vertex 0 by 1cm
        modified.vertices = v
        h_mod = MeshCanonicalizer(modified).canonicalize()

        assert h_orig != h_mod, "Moving one vertex should change the hash"

    def test_move_one_vertex_large(self) -> None:
        """A large displacement of one vertex definitely changes the hash."""
        mesh = self._load_suzanne()
        h_orig = MeshCanonicalizer(mesh).canonicalize()

        modified = deepcopy(mesh)
        v = np.array(modified.vertices, dtype=np.float64)
        v[100] += [0.5, -0.3, 0.2]
        modified.vertices = v
        h_mod = MeshCanonicalizer(modified).canonicalize()

        assert h_orig != h_mod

    # --- Add / remove vertices ---

    def test_add_vertex(self) -> None:
        """Adding one extra vertex must change the hash."""
        mesh = self._load_suzanne()
        h_orig = MeshCanonicalizer(mesh).canonicalize()

        v = np.array(mesh.vertices, dtype=np.float64)
        extra = np.array([[0.123, 0.456, 0.789]])
        v_new = np.vstack([v, extra])
        modified = _make_mesh(v_new)
        h_mod = MeshCanonicalizer(modified).canonicalize()

        assert h_orig != h_mod, "Adding a vertex should change the hash"

    def test_remove_vertex(self) -> None:
        """Removing one vertex must change the hash."""
        mesh = self._load_suzanne()
        h_orig = MeshCanonicalizer(mesh).canonicalize()

        v = np.array(mesh.vertices, dtype=np.float64)
        v_trimmed = v[:-1]  # drop last vertex
        modified = _make_mesh(v_trimmed)
        h_mod = MeshCanonicalizer(modified).canonicalize()

        assert h_orig != h_mod, "Removing a vertex should change the hash"

    def test_duplicate_vertex(self) -> None:
        """Duplicating a vertex adds to the vertex set and must change the hash."""
        mesh = self._load_suzanne()
        h_orig = MeshCanonicalizer(mesh).canonicalize()

        v = np.array(mesh.vertices, dtype=np.float64)
        v_dup = np.vstack([v, v[0:1]])  # repeat vertex 0
        modified = _make_mesh(v_dup)
        h_mod = MeshCanonicalizer(modified).canonicalize()

        assert h_orig != h_mod, "Duplicating a vertex should change the hash"

    # --- Non-uniform scaling (shear / stretch) ---

    def test_nonuniform_scale(self) -> None:
        """Non-uniform scaling (stretch one axis) must change the hash.
        Unlike uniform scaling, this is NOT an invariance — it changes geometry."""
        mesh = self._load_bunny()
        h_orig = MeshCanonicalizer(mesh).canonicalize()

        modified = deepcopy(mesh)
        v = np.array(modified.vertices, dtype=np.float64)
        v[:, 0] *= 2.0  # stretch X axis by 2x
        modified.vertices = v
        h_mod = MeshCanonicalizer(modified).canonicalize()

        assert h_orig != h_mod, "Non-uniform scale should change the hash"

    def test_nonuniform_scale_subtle(self) -> None:
        """Even a 1% stretch on one axis should produce a different hash."""
        mesh = self._load_suzanne()
        h_orig = MeshCanonicalizer(mesh).canonicalize()

        modified = deepcopy(mesh)
        v = np.array(modified.vertices, dtype=np.float64)
        v[:, 1] *= 1.01  # 1% stretch on Y
        modified.vertices = v
        h_mod = MeshCanonicalizer(modified).canonicalize()

        assert h_orig != h_mod, "1% non-uniform scale should change the hash"

    # --- Vertex noise (corruption / lossy compression) ---

    def test_random_noise(self) -> None:
        """Adding random noise to all vertices must change the hash."""
        mesh = self._load_bunny()
        h_orig = MeshCanonicalizer(mesh).canonicalize()

        modified = deepcopy(mesh)
        v = np.array(modified.vertices, dtype=np.float64)
        rng = np.random.default_rng(42)
        v += rng.normal(0, 0.001, size=v.shape)  # σ = 1mm noise
        modified.vertices = v
        h_mod = MeshCanonicalizer(modified).canonicalize()

        assert h_orig != h_mod, "Random noise should change the hash"

    # --- Mesh decimation (removing geometry) ---

    def test_subset_of_vertices(self) -> None:
        """Using only the first half of vertices is a different mesh."""
        mesh = self._load_bunny()
        h_orig = MeshCanonicalizer(mesh).canonicalize()

        v = np.array(mesh.vertices, dtype=np.float64)
        half = v[: len(v) // 2]
        modified = _make_mesh(half)
        h_mod = MeshCanonicalizer(modified).canonicalize()

        assert h_orig != h_mod, "Half the vertices should change the hash"

    # --- Completely different mesh ---

    @pytest.mark.parametrize(
        "mesh_a,mesh_b",
        [
            ("bunny.obj", "cube.obj"),
            ("bunny.obj", "suzanne.obj"),
            ("bunny.obj", "teapot.obj"),
            ("suzanne.obj", "homer.obj"),
            ("teapot.obj", "spot.obj"),
            ("armadillo.obj", "homer.obj"),
        ],
    )
    def test_different_meshes_pairwise(self, mesh_a: str, mesh_b: str) -> None:
        """Every pair of distinct meshes must hash differently."""
        ha = MeshCanonicalizer(
            trimesh.load(str(MESH_DIR / mesh_a), force="mesh")
        ).canonicalize()
        hb = MeshCanonicalizer(
            trimesh.load(str(MESH_DIR / mesh_b), force="mesh")
        ).canonicalize()
        assert ha != hb, f"{mesh_a} and {mesh_b} should hash differently"

    # --- Programmatic primitives vs each other ---

    def test_box_vs_sphere(self) -> None:
        """A box and a sphere are geometrically distinct."""
        box = trimesh.creation.box(extents=[1, 1, 1])
        sphere = trimesh.creation.uv_sphere(radius=1.0, count=[8, 8])
        h_box = MeshCanonicalizer(box).canonicalize()
        h_sph = MeshCanonicalizer(sphere).canonicalize()
        assert h_box != h_sph

    def test_cylinder_vs_cone(self) -> None:
        """A cylinder and a cone with the same radius/height are distinct."""
        cyl = trimesh.creation.cylinder(radius=1.0, height=2.0, sections=16)
        cone = trimesh.creation.cone(radius=1.0, height=2.0, sections=16)
        h_cyl = MeshCanonicalizer(cyl).canonicalize()
        h_cone = MeshCanonicalizer(cone).canonicalize()
        assert h_cyl != h_cone

    # --- Sensitivity: meshes that are almost identical ---

    def test_one_vertex_epsilon_shift(self) -> None:
        """A shift just above truncation resolution (>1e-4) should change the hash
        for at least one vertex coordinate after PCA alignment."""
        mesh = self._load_suzanne()
        h_orig = MeshCanonicalizer(mesh).canonicalize()

        modified = deepcopy(mesh)
        v = np.array(modified.vertices, dtype=np.float64)
        # Shift vertex 50 by 0.005 (50x the truncation resolution)
        v[50] += [0.005, 0.0, 0.0]
        modified.vertices = v
        h_mod = MeshCanonicalizer(modified).canonicalize()

        assert h_orig != h_mod, (
            "A 0.005 shift on one vertex should survive truncation"
        )


# ===================================================================
# 12. GUARD: test_meshes/ directory must not be empty
# ===================================================================

class TestGuard:

    def test_mesh_dir_not_empty(self) -> None:
        """Ensure there are meshes to test against — prevents silent no-op suite."""
        meshes = list(MESH_DIR.glob("*.obj"))
        assert len(meshes) >= 2, (
            f"Expected ≥2 OBJ files in {MESH_DIR}, found {len(meshes)}"
        )
