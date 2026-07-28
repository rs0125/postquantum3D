# Provenance Pipeline Design

## The 3D Asset Provenance Problem

Digital 3D assets traverse complex supply chains: artists create them in DCCs (Blender, Maya, ZBrush), studios exchange them via cloud platforms, game engines import and re-export them, and end users consume them across VR/AR devices. At each stage, the asset may be re-exported with different coordinate conventions, scaled to different units, or rotated to match a scene. The fundamental question at each handoff is:

> *"Is this the same asset that was originally authored, or has it been tampered with?"*

Classical approaches — hashing the raw file bytes, embedding watermarks, or comparing vertex buffers — all fail because they cannot distinguish legitimate export transforms from malicious modifications. A mesh rotated 90 degrees and re-exported to a different format is the same asset, but its bytes are completely different.

## Design Principles

### Principle 1: Geometry Is Ground Truth

The pipeline treats the **vertex positions** (after removing similarity-transform DOF) as the sole identity of a mesh. Face connectivity, normals, UVs, and vertex colors are intentionally excluded. This is appropriate for provenance tracking because:

- Geometry is the most semantically meaningful component of a mesh.
- Re-export pipelines often regenerate normals, recompute UVs, and reindex faces.
- A mesh with identical vertices but different face winding is the "same mesh" for provenance purposes.

For applications where topology matters (e.g., rigging verification), the pipeline can be extended with a separate topology hash.

### Principle 2: Sign Once, Verify Anywhere

The sidecar format is self-contained: given the mesh file, the `.sig.json` sidecar, and the public key, verification requires no external services, no network access, and no state. This enables offline verification in air-gapped environments, CI/CD pipelines, and embedded systems.

### Principle 3: Post-Quantum by Default

The pipeline uses ML-DSA-44 exclusively. There is no classical fallback. This is a deliberate choice: for assets with a multi-decade lifetime, "quantum-safe from day one" avoids the need for a future migration that would invalidate all existing signatures.

### Principle 4: Minimal Trust Assumptions

The only trusted components are:
1. The private key (assumed secret).
2. The implementation correctness of the canonicalization pipeline and ML-DSA-44.

The verifier trusts nothing else: not the sidecar's `geometric_hash` field (recomputed locally), not the transport channel, not the file format, not the mesh's metadata.

## Pipeline Stages in Detail

### Stage 0: Asset Authoring (External)

The artist creates a 3D mesh in their DCC of choice. The pipeline imposes no requirements on the authoring workflow.

### Stage 1: Key Provisioning

```bash
python demos/01_generate_keys.py
```

A studio or individual generates an ML-DSA-44 keypair. The private key is stored securely (ideally in an HSM or encrypted keystore). The public key is distributed to all parties who need to verify assets.

**Key distribution** is an orthogonal concern. Options include:
- Embedding the public key in a smart contract or blockchain.
- Publishing it in a DNS TXT record (DANE-style).
- Including it in a PKI certificate signed by a CA.
- Distributing it out-of-band (USB, QR code).

### Stage 2: Signing

```bash
python demos/02_sign_mesh.py model.obj
```

The signer:
1. Loads the mesh file.
2. Canonicalizes it (removing translation, scale, rotation, float noise, vertex ordering).
3. Signs the resulting SHA-256 hash with ML-DSA-44.
4. Writes the sidecar alongside the mesh.

The signer does not need to preserve the original mesh file. The signature covers the *canonical geometry*, not the raw bytes. If the asset is later re-exported with a different rotation or scale, the sidecar remains valid.

### Stage 3: Distribution (Untrusted)

The mesh file and sidecar travel through untrusted channels:
- Cloud storage (S3, GCS, Azure Blob).
- CDN distribution.
- Email, Slack, or file-sharing services.
- Version control (Git LFS).
- Marketplace platforms (Sketchfab, TurboSquid, Unity Asset Store).

The pipeline assumes that an adversary can read, modify, or replace both the mesh and sidecar at any point during distribution.

### Stage 4: Verification

```bash
python demos/03_verify_mesh.py model.obj
```

The verifier:
1. Loads the mesh file and recomputes the canonical hash from scratch.
2. Loads the sidecar and decodes the base64 signature.
3. Verifies the signature against the canonical hash using the public key.
4. Returns `True` (asset is authentic and unmodified) or `False` (tampered or wrong key).

### Stage 5: Tamper Response (Application-Specific)

What happens when verification fails is application-specific:
- **CI/CD pipeline**: Fail the build, alert the team.
- **Game engine import**: Reject the asset, log a warning.
- **Marketplace**: Flag the listing for review.
- **Forensic analysis**: Compare the recomputed hash against the sidecar's `geometric_hash` to determine whether the geometry or the signature was tampered with.

## Invariance Under Re-Export

A critical property of the pipeline is that a signed mesh remains verifiable after legitimate re-export operations:

| Re-export Operation | Sidecar Still Valid? | Why |
|---|---|---|
| Rotate 90 on Y | Yes | Phase 3 removes rotation |
| Scale to centimeters | Yes | Phase 2 removes uniform scale |
| Translate to scene origin | Yes | Phase 1 removes translation |
| Convert OBJ to glTF | Yes | Vertex positions are preserved |
| Flip Y-up to Z-up | Yes | Equivalent to a rotation |
| Re-index faces | Yes | Pipeline ignores face connectivity |
| Regenerate normals | Yes | Pipeline ignores normals |
| Mirror (flip handedness) | Yes | Pipeline is reflection-invariant |
| **Non-uniform scale** | **No** | **Changes geometry** |
| **Edit vertices** | **No** | **Changes geometry** |
| **Decimate mesh** | **No** | **Removes vertices** |
| **Subdivide mesh** | **No** | **Adds vertices** |

## Integration Patterns

### Pattern 1: CI/CD Asset Validation

```yaml
# .github/workflows/asset-check.yml
- name: Verify mesh provenance
  run: python demos/03_verify_mesh.py assets/**/*.obj
```

Every mesh in the repository is verified on push. If an artist accidentally commits a modified mesh without re-signing, the pipeline catches it.

### Pattern 2: Content-Addressable Storage

```python
from postquantum3d import MeshCanonicalizer
import trimesh

mesh = trimesh.load("model.obj", force="mesh")
key = MeshCanonicalizer(mesh).canonicalize()
storage.put(key, mesh_bytes)  # Deduplicated by geometry
```

Two meshes that are geometrically identical (regardless of export transforms) map to the same storage key. This enables automatic deduplication in large asset libraries.

### Pattern 3: Blockchain-Anchored Provenance

```
┌───────────┐     sign      ┌──────────────┐     anchor     ┌────────────┐
│  Mesh +   │──────────────▶│   .sig.json   │──────────────▶│ Blockchain  │
│  Artist   │               │   sidecar     │  (hash of     │ (immutable  │
│  (local)  │               │               │   sidecar)    │  timestamp) │
└───────────┘               └──────────────┘               └────────────┘
```

The sidecar's SHA-256 hash (or the geometric hash directly) can be anchored on a blockchain to provide a trusted timestamp. This closes the replay-attack gap identified in the threat model.

### Pattern 4: Multi-Party Signing

For assets that pass through multiple stages (modeling → rigging → texturing → QA), each stage can produce its own sidecar with its own keypair:

```
model.obj.modeling.sig.json     # Signed by modeler
model.obj.rigging.sig.json      # Signed by rigger (after rigging, re-sign)
model.obj.qa.sig.json           # Signed by QA (final approval)
```

Each sidecar independently attests that the geometry was authentic at the time of signing. If the geometry changes between stages (e.g., vertex edits during rigging), the earlier sidecars become invalid — correctly reflecting that the geometry was modified.

## Performance Characteristics

| Operation | Mesh Size | Time |
|---|---|---|
| Key generation | — | ~0.1 ms |
| Canonicalize + Sign | 14 verts (cube) | ~2 ms |
| Canonicalize + Sign | 3,225 verts (spot) | ~15 ms |
| Canonicalize + Sign | 34,834 verts (bunny) | ~55 ms |
| Canonicalize + Sign | 49,990 verts (armadillo) | ~80 ms |
| Verify | 34,834 verts (bunny) | ~55 ms |

The bottleneck is always mesh loading and canonicalization. The ML-DSA-44 sign/verify operations add $< 1$ ms regardless of mesh size.

## Open Questions and Future Work

1. **Topology hashing**: Extend the pipeline with an optional face-connectivity hash for applications where mesh topology matters.

2. **Incremental signing**: For large asset libraries, batch-sign meshes and produce a Merkle tree of canonical hashes, allowing efficient verification of individual assets within the batch.

3. **Attribute binding**: Extend the sidecar to sign additional metadata (author, license, creation date) alongside the geometric hash. This requires careful design to avoid binding metadata that legitimately changes across re-exports.

4. **Cross-format canonical hashing**: Support canonical hashing of non-mesh 3D representations (point clouds, NURBS surfaces, volumetric data).

5. **Threshold signing**: Enable multi-party signing where $k$ of $n$ parties must agree to produce a valid signature (e.g., artist + QA + manager). ML-DSA threshold signing is an active research area.
