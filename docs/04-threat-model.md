# Threat Model and Security Analysis

## Scope

This document defines the security goals, adversary model, and attack surface for the postquantum3D provenance pipeline. The pipeline is designed to provide **integrity** and **authenticity** guarantees for 3D mesh assets in environments where:

- Assets pass through untrusted intermediaries (cloud storage, CDNs, marketplaces).
- Long-term verifiability is required (years to decades).
- Quantum computing may become a practical threat within the asset's lifetime.

## Security Goals

### G1: Geometric Integrity

An adversary who modifies the mesh geometry (adding, removing, or displacing vertices) cannot produce a valid signature for the modified mesh without access to the signing key.

**Formal statement**: Given a signed pair $(M, \sigma)$ and a modified mesh $M' \neq M$ (where inequality is defined in the canonical geometric sense — after removing similarity-transform DOF), the adversary cannot produce $\sigma'$ such that $\text{verify}(M', \sigma', pk) = \text{true}$ without knowledge of $sk$.

### G2: Signature Unforgeability

An adversary who has access to the public key and any number of valid (mesh, signature) pairs cannot forge a valid signature for a new mesh.

**Formal basis**: EUF-CMA (Existential Unforgeability under Chosen Message Attack) security of ML-DSA-44, proven under MLWE/MSIS hardness in the QROM.

### G3: Post-Quantum Resistance

The above guarantees hold against adversaries with access to large-scale quantum computers capable of running Shor's and Grover's algorithms.

**Formal basis**: ML-DSA-44 at NIST Level 2 provides 128-bit security against quantum adversaries (core-SVP hardness $\geq 2^{128}$).

## Adversary Model

### Capabilities

| Capability | Assumed? |
|---|---|
| Intercept and read mesh files and sidecars | Yes |
| Modify mesh files in transit or at rest | Yes |
| Modify sidecar files in transit or at rest | Yes |
| Access to the public key | Yes |
| Access to polynomially many valid (mesh, signature) pairs | Yes |
| Access to a large-scale quantum computer | Yes (G3) |
| Access to the private signing key | **No** |
| Ability to compromise the signing environment during key generation | **No** |

### Non-Goals (Out of Scope)

| Property | Status | Rationale |
|---|---|---|
| **Confidentiality** | Out of scope | Meshes and sidecars are not encrypted. The pipeline provides integrity, not secrecy. |
| **Availability** | Out of scope | An adversary can delete meshes or sidecars. The pipeline does not prevent denial of service. |
| **Timestamping** | Out of scope | The sidecar does not include a trusted timestamp. An adversary can re-sign an old mesh with a current key. Timestamping requires an external TSA. |
| **Key revocation** | Out of scope | There is no built-in mechanism to revoke compromised keys. Key lifecycle management requires external PKI. |
| **Non-repudiation** | Partial | The signer cannot deny having signed a mesh (assuming the private key was not compromised), but there is no binding to a real-world identity without a certificate chain. |

## Attack Surface Analysis

### A1: Geometry Tampering

**Attack**: Modify vertex positions in the mesh file to alter the geometry while keeping the original sidecar.

**Defense**: The verifier recomputes the canonical hash from the mesh file and checks it against the signature. Any geometric change (above the truncation threshold of $5 \times 10^{-5}$ relative to the bounding sphere) produces a different hash, and the signature verification fails.

**Residual risk**: Geometric changes below the truncation threshold ($< 5 \times 10^{-5}$ of the bounding sphere) are invisible to the pipeline. For a 1-meter mesh, this corresponds to $< 0.05$ mm — below the precision of most 3D scanning and modeling workflows.

### A2: Sidecar Tampering

**Attack**: Modify the `geometric_hash` or `signature_b64` fields in the sidecar to match a different mesh.

**Defense**: Modifying `geometric_hash` alone is useless — the verifier ignores this field and recomputes the hash. Modifying `signature_b64` requires forging an ML-DSA-44 signature, which is computationally infeasible under MLWE/MSIS hardness.

### A3: Substitution Attack

**Attack**: Replace the mesh file entirely with a different mesh, and provide a valid sidecar for the replacement.

**Defense**: Producing a valid sidecar requires signing the canonical hash of the replacement mesh with the private key. Without the private key, this reduces to EUF-CMA forgery of ML-DSA-44.

### A4: Replay Attack

**Attack**: Re-use a valid (mesh, sidecar) pair from a previous signing operation.

**Status**: The pipeline does not defend against replay. An old sidecar for an unchanged mesh will verify successfully. Replay protection requires external mechanisms (sequence numbers, timestamps, nonces).

### A5: Key Compromise

**Attack**: Steal the private key and sign arbitrary meshes.

**Status**: Out of scope. Key protection is a deployment concern (HSM, encrypted storage, access controls). The pipeline assumes the private key is secret.

### A6: Collision Attack on SHA-256

**Attack**: Find two geometrically different meshes $M_1 \neq M_2$ whose canonical hash strings collide: $\text{SHA-256}(s_1) = \text{SHA-256}(s_2)$.

**Defense**: SHA-256 provides $2^{128}$ collision resistance. Finding a collision requires $\sim 2^{128}$ hash evaluations (birthday bound), which is computationally infeasible.

**Note**: This is a collision on the *pre-hash string*, not on the raw vertex data. The canonicalization pipeline ensures that geometrically different meshes produce different pre-hash strings (above the truncation threshold), so the collision resistance of the overall scheme is bounded by SHA-256.

### A7: Second Preimage Attack via Canonicalization Bypass

**Attack**: Find a mesh $M'$ whose canonical representation is byte-identical to $M$ but whose raw vertex data is different (e.g., by exploiting a bug in the canonicalization pipeline).

**Defense**: The canonicalization pipeline is deterministic and bijective (up to the similarity-transform equivalence class). Two meshes in the same equivalence class are geometrically identical by definition. The test suite (257 tests) extensively validates that the pipeline is correct across edge cases, degeneracies, and extreme transforms.

**Residual risk**: A bug in the canonicalization pipeline could theoretically allow two geometrically different meshes to produce the same pre-hash string. This is mitigated by comprehensive testing but cannot be formally proven absent a machine-checked proof.

### A8: Quantum Attack on ML-DSA-44

**Attack**: Use Grover's algorithm or quantum lattice sieving to forge a signature.

**Defense**: ML-DSA-44 is designed for NIST Level 2 (128-bit post-quantum security). The best known quantum attack is Grover-accelerated BKZ lattice sieving, which requires $> 2^{128}$ quantum operations. This is beyond the capability of any foreseeable quantum computer.

## Trust Boundary Diagram

```
┌─────────────────────────────────────────────────────────┐
│                   TRUSTED ZONE                          │
│                                                         │
│   ┌──────────────┐    ┌──────────────┐                  │
│   │  Private Key  │    │  Signing Env │                  │
│   │  (HSM/disk)   │───▶│  (sign.py)   │                  │
│   └──────────────┘    └──────┬───────┘                  │
│                              │                          │
│                     .sig.json + mesh                    │
└──────────────────────────────┼──────────────────────────┘
                               │
              ─ ─ ─ ─ ─ ─ ─ ─ ┼ ─ ─ ─ ─ ─ ─ ─ ─  TRUST BOUNDARY
                               │
┌──────────────────────────────┼──────────────────────────┐
│                   UNTRUSTED ZONE                        │
│                              │                          │
│         Cloud / CDN / marketplace / transit              │
│                              │                          │
└──────────────────────────────┼──────────────────────────┘
                               │
              ─ ─ ─ ─ ─ ─ ─ ─ ┼ ─ ─ ─ ─ ─ ─ ─ ─  TRUST BOUNDARY
                               │
┌──────────────────────────────┼──────────────────────────┐
│                   VERIFICATION ZONE                     │
│                              │                          │
│   ┌──────────────┐    ┌─────▼────────┐                  │
│   │  Public Key   │───▶│  Verify Env  │                  │
│   │  (distributed)│    │  (sign.py)   │───▶ True/False   │
│   └──────────────┘    └──────────────┘                  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Sensitivity Analysis: Truncation Precision

The truncation precision parameter (PRECISION = 4) creates a tradeoff:

| PRECISION | Min detectable shift | False-positive risk | False-negative risk |
|---|---|---|---|
| 2 | $5 \times 10^{-3}$ | Very low | High (coarse geometry changes missed) |
| **4** | **$5 \times 10^{-5}$** | **Very low** | **Very low** |
| 6 | $5 \times 10^{-7}$ | Moderate (float noise may cause mismatches) | Very low |
| 8 | $5 \times 10^{-9}$ | High (float noise dominates) | Very low |

PRECISION = 4 is chosen as the sweet spot: it absorbs all practical floating-point non-determinism (~$10^{-15}$ for unit-scale values) while detecting geometric changes larger than $0.05$ mm on a 1-meter asset.
