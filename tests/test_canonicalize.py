"""
Test Suite for MeshCanonicalizer
================================

Strategy:
    For each test mesh we verify the core invariance guarantee:
        hash(original) == hash(T · R · s · original)
    where T is an arbitrary translation, R is an arbitrary 3D rotation,
    and s is a uniform scale factor.

    We also run multiple random transforms per mesh to stress-test the
    pipeline's determinism.
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

# ---------------------------------------------------------------------------
# Make the src/ package importable from the tests/ directory.
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from postquantum3d.canonicalize import MeshCanonicalizer  # noqa: E402

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
MESH_DIR = PROJECT_ROOT / "test_meshes"
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Logging — write detailed pipeline output to logs/test_canonicalize.log
# AND mirror to stdout so pytest -s shows it too.
# ---------------------------------------------------------------------------
_log_file = LOG_DIR / "test_canonicalize.log"
_file_handler = logging.FileHandler(_log_file, mode="w", encoding="utf-8")
_file_handler.setLevel(logging.INFO)
_file_handler.setFormatter(
    logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s")
)

_stream_handler = logging.StreamHandler(sys.stdout)
_stream_handler.setLevel(logging.INFO)
_stream_handler.setFormatter(
    logging.Formatter("%(levelname)-8s  %(message)s")
)

_root_logger = logging.getLogger()
_root_logger.setLevel(logging.INFO)
_root_logger.addHandler(_file_handler)
_root_logger.addHandler(_stream_handler)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Mesh catalogue — all OBJ files in test_meshes/
# ---------------------------------------------------------------------------
ALL_MESHES = sorted(MESH_DIR.glob("*.obj"))
ALL_MESH_NAMES = [p.stem for p in ALL_MESHES]


# ---------------------------------------------------------------------------
# Helper: apply a random rigid-body transform + uniform scale to a mesh
# ---------------------------------------------------------------------------
def apply_random_transform(
    mesh: trimesh.Trimesh,
    rng: np.random.Generator,
) -> trimesh.Trimesh:
    """Return a deep copy of *mesh* after random translation, rotation, scale."""
    mutated = deepcopy(mesh)
    vertices = np.array(mutated.vertices, dtype=np.float64)

    # --- Uniform scale  (between 0.1 and 100) ---
    scale = rng.uniform(0.1, 100.0)

    # --- Random translation  (each axis in [-500, 500]) ---
    translation = rng.uniform(-500.0, 500.0, size=3)

    # --- Random 3D rotation via scipy ---
    rotation_matrix = Rotation.random(random_state=rng).as_matrix()

    # Apply:  V' = s · (R @ Vᵀ)ᵀ + T  =  s · (V @ Rᵀ) + T
    vertices = scale * (vertices @ rotation_matrix.T) + translation

    mutated.vertices = vertices

    logger.info(
        "Applied random transform  |  scale=%.4f  |  translation=%s  |  "
        "rotation det=%.6f",
        scale,
        translation,
        np.linalg.det(rotation_matrix),
    )
    return mutated


# ===================================================================
#  Tests
# ===================================================================


class TestCanonicalInvariance:
    """Verify that canonicalization is invariant to rigid + uniform-scale transforms."""

    # ---------------------------------------------------------------
    # Parametrized: every mesh × single random transform
    # ---------------------------------------------------------------
    @pytest.mark.parametrize("mesh_path", ALL_MESHES, ids=ALL_MESH_NAMES)
    def test_single_transform(self, mesh_path: Path) -> None:
        """Load mesh, apply ONE random transform, assert hash equality."""
        logger.info("=" * 72)
        logger.info("TEST: test_single_transform  [%s]", mesh_path.name)
        logger.info("=" * 72)

        mesh = trimesh.load(str(mesh_path), force="mesh")
        rng = np.random.default_rng(seed=42)

        hash_original = MeshCanonicalizer(mesh).canonicalize()
        logger.info("Original hash : %s", hash_original)

        mutated = apply_random_transform(mesh, rng)
        hash_mutated = MeshCanonicalizer(mutated).canonicalize()
        logger.info("Mutated  hash : %s", hash_mutated)

        logger.info("Match: %s", hash_original == hash_mutated)
        assert hash_original == hash_mutated, (
            f"Hash mismatch for {mesh_path.name}!\n"
            f"  original: {hash_original}\n  mutated:  {hash_mutated}"
        )

    # ---------------------------------------------------------------
    # Parametrized: every mesh × multiple random seeds (stress test)
    # ---------------------------------------------------------------
    @pytest.mark.parametrize("seed", [0, 7, 13, 99, 256, 1024, 9999])
    @pytest.mark.parametrize("mesh_path", ALL_MESHES, ids=ALL_MESH_NAMES)
    def test_multi_transform(self, mesh_path: Path, seed: int) -> None:
        """Stress-test: 7 different random seeds per mesh must all match."""
        logger.info("-" * 72)
        logger.info(
            "TEST: test_multi_transform  [%s]  seed=%d", mesh_path.name, seed
        )
        logger.info("-" * 72)

        mesh = trimesh.load(str(mesh_path), force="mesh")
        rng = np.random.default_rng(seed=seed)

        hash_original = MeshCanonicalizer(mesh).canonicalize()
        mutated = apply_random_transform(mesh, rng)
        hash_mutated = MeshCanonicalizer(mutated).canonicalize()

        logger.info(
            "[%s] seed=%d  |  orig=%s  |  mut=%s  |  match=%s",
            mesh_path.name,
            seed,
            hash_original,
            hash_mutated,
            hash_original == hash_mutated,
        )
        assert hash_original == hash_mutated

    # ---------------------------------------------------------------
    # Idempotency: canonicalizing twice gives the same hash
    # ---------------------------------------------------------------
    @pytest.mark.parametrize("mesh_path", ALL_MESHES, ids=ALL_MESH_NAMES)
    def test_idempotency(self, mesh_path: Path) -> None:
        """Running canonicalization twice on the same mesh yields the same hash."""
        logger.info("=" * 72)
        logger.info("TEST: test_idempotency  [%s]", mesh_path.name)
        logger.info("=" * 72)

        mesh = trimesh.load(str(mesh_path), force="mesh")
        h1 = MeshCanonicalizer(mesh).canonicalize()
        h2 = MeshCanonicalizer(mesh).canonicalize()
        logger.info("Run 1: %s", h1)
        logger.info("Run 2: %s", h2)
        assert h1 == h2

    # ---------------------------------------------------------------
    # Identity transform: deep copy without mutation still matches
    # ---------------------------------------------------------------
    @pytest.mark.parametrize("mesh_path", ALL_MESHES, ids=ALL_MESH_NAMES)
    def test_identity_transform(self, mesh_path: Path) -> None:
        """A mesh with no transform applied must hash identically to its copy."""
        logger.info("=" * 72)
        logger.info("TEST: test_identity_transform  [%s]", mesh_path.name)
        logger.info("=" * 72)

        mesh = trimesh.load(str(mesh_path), force="mesh")
        copy = deepcopy(mesh)

        h_orig = MeshCanonicalizer(mesh).canonicalize()
        h_copy = MeshCanonicalizer(copy).canonicalize()
        logger.info("Original: %s", h_orig)
        logger.info("Copy:     %s", h_copy)
        assert h_orig == h_copy
