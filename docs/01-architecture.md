# Architecture Overview

## System Design

postquantum3D implements a two-stage cryptographic provenance pipeline for 3D mesh assets. The first stage produces a **geometry-canonical fingerprint** — a deterministic SHA-256 digest invariant to rigid-body transforms and uniform scale. The second stage binds that fingerprint to an **identity** via a post-quantum digital signature (ML-DSA-44 / FIPS 204).

```
                                ┌──────────────────────────────┐
                                │       3D Mesh Asset          │
                                │  (.obj, .stl, .ply, .glTF)  │
                                └──────────────┬───────────────┘
                                               │
                              ┌────────────────▼────────────────┐
                              │   Stage 1: Canonicalization      │
                              │                                  │
                              │  Phase 1  Center (−translation)  │
                              │  Phase 2  Normalize (−scale)     │
                              │  Phase 3  PCA Align (−rotation)  │
                              │     ├─ coordinate path ──┐       │
                              │     └─ distance path ──┐ │       │
                              │  Phase 4  Truncate      │ │       │
                              │  Phase 5  Sort          │ │       │
                              │  Phase 6  SHA-256 ◄─────┘─┘       │
                              └────────────────┬────────────────┘
                                               │
                                    64-char hex digest
                                               │
                              ┌────────────────▼────────────────┐
                              │   Stage 2: Signature             │
                              │                                  │
                              │  ML-DSA-44 (Dilithium2)          │
                              │  FIPS 204, NIST PQC Level 2      │
                              │                                  │
                              │  sign(hash, sk) → σ              │
                              │  verify(hash, σ, pk) → bool      │
                              └────────────────┬────────────────┘
                                               │
                              ┌────────────────▼────────────────┐
                              │   Sidecar: .sig.json             │
                              │                                  │
                              │  { asset_name, algorithm,        │
                              │    geometric_hash, signature_b64 }│
                              └─────────────────────────────────┘
```

## Module Decomposition

| Module | Responsibility | Dependencies |
|---|---|---|
| `canonicalize.py` | Geometry-canonical hashing. Stateless pipeline that maps a `trimesh.Trimesh` to a SHA-256 string. | numpy, trimesh |
| `sign.py` | Key management, signing, and verification. Thin orchestration layer over `canonicalize.py` and `liboqs`. | oqs, trimesh, canonicalize |

The two modules are deliberately separated: canonicalization is a pure geometric operation with no cryptographic dependencies, making it independently testable and reusable for non-signature use cases (asset deduplication, content-addressable storage).

## Data Flow

### Signing

```
mesh file  ──load──▶  trimesh.Trimesh
                          │
              MeshCanonicalizer.canonicalize()
                          │
                    SHA-256 hex string
                          │
                   encode("utf-8")
                          │
               oqs.Signature("ML-DSA-44", sk).sign(msg)
                          │
                    raw signature bytes
                          │
                   base64.b64encode()
                          │
                    .sig.json sidecar
```

### Verification

```
mesh file  ──load──▶  trimesh.Trimesh
                          │
              MeshCanonicalizer.canonicalize()
                          │
                    local SHA-256 hex string
                          │
                   encode("utf-8")
                          │         .sig.json  ──▶  base64.b64decode() ──▶ sig bytes
                          │                                                    │
               oqs.Signature("ML-DSA-44").verify(msg, sig, pk) ◄──────────────┘
                          │
                   True / False
```

The critical property: the verifier **recomputes** the canonical hash from scratch. It never trusts the `geometric_hash` field in the sidecar. The sidecar hash exists only for diagnostic purposes (e.g., logging which hash was signed). This means that even if an attacker modifies both the mesh and the sidecar hash, verification still fails because the signature was computed over the original hash.

## Key Sizes and Performance Characteristics

| Parameter | ML-DSA-44 |
|---|---|
| Public key | 1,312 bytes |
| Secret key | 2,560 bytes |
| Signature | 2,420 bytes |
| NIST security level | 2 (~128-bit post-quantum) |
| Keygen | ~0.1 ms |
| Sign | ~0.3 ms |
| Verify | ~0.2 ms |

The dominant cost in the pipeline is **mesh canonicalization** (loading, PCA, sorting), not the cryptographic operations. For a 35,000-vertex mesh like the Stanford Bunny, canonicalization takes ~50ms while signing takes <1ms.

## Sidecar Format

The `.sig.json` sidecar is a self-contained attestation:

```json
{
  "asset_name": "bunny.obj",
  "algorithm": "ML-DSA-44",
  "geometric_hash": "b50b58d62243bf2ff5fe1259f0a56389ab4d670f40f1ce5b21ffc4090d7a79f6",
  "signature_b64": "RkFLRV9TSUdOQVRVUkVfREFUQQ==..."
}
```

| Field | Purpose |
|---|---|
| `asset_name` | Human-readable label (not used in verification) |
| `algorithm` | Signature algorithm identifier for forward compatibility |
| `geometric_hash` | The canonical hash that was signed (diagnostic only — verifier recomputes) |
| `signature_b64` | Base64-encoded ML-DSA-44 signature over the UTF-8 encoding of `geometric_hash` |

The sidecar is designed to be portable: it can be transmitted alongside the mesh file, embedded in a database, or attached to a blockchain transaction. The only external dependency for verification is the public key.

## Trust Model

The pipeline establishes a chain of trust:

1. **Geometric identity**: The canonical hash binds a specific mesh geometry to a unique identifier, regardless of how the mesh was exported.
2. **Authorship attestation**: The ML-DSA-44 signature binds that identifier to a specific private key holder.
3. **Tamper evidence**: Any modification to the geometry, the signature, or the use of a different key causes verification to fail.

What the pipeline does *not* provide:
- **Timestamp authority**: The sidecar does not include a trusted timestamp. A signing timestamp can be added via an external TSA.
- **Key revocation**: There is no built-in revocation mechanism. Key management (PKI, certificate chains) is an orthogonal concern.
- **Confidentiality**: The mesh and sidecar are not encrypted. The signature provides integrity and authenticity, not secrecy.
