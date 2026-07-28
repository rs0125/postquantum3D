# Post-Quantum Digital Signatures

## Motivation: The Quantum Threat

Shor's algorithm (1994) demonstrates that a sufficiently large quantum computer can factor integers and compute discrete logarithms in polynomial time, breaking RSA, ECDSA, and EdDSA. For 3D asset provenance — where signed meshes may need to remain verifiable for years or decades — classical signature schemes face a "harvest now, decrypt later" threat: an adversary can store signed sidecars today and forge signatures once quantum hardware matures.

NIST's Post-Quantum Cryptography standardization process (2016–2024) selected ML-DSA (Module-Lattice Digital Signature Algorithm, formerly CRYSTALS-Dilithium) as the primary post-quantum signature standard, published as FIPS 204 in August 2024.

## ML-DSA (FIPS 204)

### Mathematical Foundation

ML-DSA is a lattice-based signature scheme built on the hardness of the **Module Learning With Errors (MLWE)** and **Module Short Integer Solution (MSIS)** problems over polynomial rings.

**Ring structure**: Operations take place in the ring $R_q = \mathbb{Z}_q[X] / (X^n + 1)$ where $n = 256$ and $q = 8380417$. Elements of $R_q$ are polynomials of degree $< 256$ with coefficients in $\mathbb{Z}_q$. The quotient by $(X^n + 1)$ enables efficient multiplication via the Number Theoretic Transform (NTT).

**Module structure**: Keys and signatures are vectors of ring elements. For ML-DSA-44, the module dimensions are $(k, \ell) = (4, 4)$, meaning the public matrix $A$ is $4 \times 4$ over $R_q$.

### Key Generation

1. Sample a random matrix $A \in R_q^{k \times \ell}$ (expanded from a seed via SHAKE-128).
2. Sample short secret vectors $s_1 \in R_q^\ell$ and $s_2 \in R_q^k$ with coefficients bounded by $\eta = 2$.
3. Compute $t = A s_1 + s_2$.
4. Public key: $(A, t)$. Secret key: $(A, t, s_1, s_2)$.

The public key encodes a noisy linear relation $t \approx A s_1$. Recovering $s_1$ from $(A, t)$ requires solving MLWE, which is believed to be hard even for quantum computers.

### Signing (Fiat-Shamir with Aborts)

ML-DSA uses the **Fiat-Shamir with aborts** paradigm:

1. Sample a masking vector $y \in R_q^\ell$ with large coefficients (bounded by $\gamma_1$).
2. Compute $w = Ay$.
3. Derive a challenge $c = H(\text{msg} \| w_{\text{high}})$ — a sparse polynomial with exactly $\tau$ non-zero coefficients in $\{-1, +1\}$.
4. Compute $z = y + c \cdot s_1$.
5. **Rejection sampling**: If $z$ has any coefficient exceeding $\gamma_1 - \beta$ (where $\beta = \tau \eta$), **abort and restart from step 1**. This ensures the distribution of $z$ is independent of the secret key $s_1$ (zero-knowledge property).
6. Output signature $\sigma = (z, c)$ (plus auxiliary hint bits).

The expected number of iterations before a valid signature is produced is approximately 4–7 for ML-DSA-44.

### Verification

1. Recompute $w' = Az - ct$.
2. Check that $c = H(\text{msg} \| w'_{\text{high}})$.
3. Check that all coefficients of $z$ are bounded.

Verification is deterministic and requires no rejection sampling.

### Security Parameters (ML-DSA-44)

| Parameter | Value | Meaning |
|---|---|---|
| $(k, \ell)$ | $(4, 4)$ | Module dimensions |
| $q$ | $8{,}380{,}417$ | Ring modulus |
| $n$ | $256$ | Polynomial degree |
| $\eta$ | $2$ | Secret key coefficient bound |
| $\gamma_1$ | $2^{17}$ | Masking coefficient bound |
| $\tau$ | $39$ | Challenge weight (number of $\pm 1$s) |
| NIST level | 2 | ~128-bit post-quantum security |
| Public key | 1,312 bytes | |
| Secret key | 2,560 bytes | |
| Signature | 2,420 bytes | |

### Security Assumptions

ML-DSA-44 at NIST Level 2 provides security equivalent to AES-128 against quantum adversaries. The concrete security reduction relies on:

1. **MLWE hardness**: Given $(A, t = As_1 + s_2)$, distinguishing $t$ from uniform is hard.
2. **MSIS hardness**: Given $A$, finding a short vector $v$ such that $Av = 0$ is hard.
3. **Quantum Random Oracle Model (QROM)**: The hash function $H$ behaves as a random oracle even when queried in superposition.

The best known quantum attack against MLWE/MSIS is Grover-accelerated lattice sieving, which provides at most a quadratic speedup over classical attacks. For ML-DSA-44 parameters, this yields $> 2^{128}$ quantum operations.

## Integration with postquantum3D

### Why ML-DSA-44?

| Consideration | Decision |
|---|---|
| **Post-quantum security** | Required for long-lived asset provenance |
| **NIST standardization** | FIPS 204 (August 2024) — regulatory acceptance |
| **Performance** | Sub-millisecond sign/verify — negligible vs. mesh canonicalization |
| **Key/signature sizes** | 1.3 KB / 2.4 KB — acceptable for sidecar files |
| **Level 2 vs 3 vs 5** | Level 2 (128-bit) suffices for asset integrity; higher levels increase sizes without clear benefit for this threat model |

### liboqs Integration

The pipeline uses `liboqs-python`, the Python binding for the Open Quantum Safe (OQS) library. `liboqs` provides a C implementation of ML-DSA-44 that passes the NIST Known Answer Tests (KATs).

```python
import oqs

# Key generation
signer = oqs.Signature("ML-DSA-44")
public_key = signer.generate_keypair()        # 1,312 bytes
secret_key = signer.export_secret_key()       # 2,560 bytes

# Signing (requires secret key in constructor)
signer = oqs.Signature("ML-DSA-44", secret_key)
signature = signer.sign(message)              # 2,420 bytes

# Verification
verifier = oqs.Signature("ML-DSA-44")
is_valid = verifier.verify(message, signature, public_key)  # bool
```

Note the asymmetric API: `sign()` takes only the message (the secret key is bound at construction), while `verify()` takes message, signature, and public key.

## Comparison with Classical Alternatives

| Scheme | Key Size | Sig Size | PQ-Secure? | Standard |
|---|---|---|---|---|
| Ed25519 | 32 B | 64 B | No | RFC 8032 |
| ECDSA P-256 | 64 B | 64 B | No | FIPS 186-5 |
| RSA-2048 | 256 B | 256 B | No | PKCS#1 |
| **ML-DSA-44** | **1,312 B** | **2,420 B** | **Yes** | **FIPS 204** |
| SPHINCS+-128f | 32 B | 17,088 B | Yes | FIPS 205 |
| FALCON-512 | 897 B | 666 B | Yes | — |

ML-DSA-44 offers the best balance of standardization status, implementation maturity, and size for the sidecar use case. SPHINCS+ has smaller keys but 7x larger signatures. FALCON has smaller signatures but is not yet a FIPS standard and has more complex constant-time implementation requirements.

## Future Considerations

1. **Algorithm agility**: The sidecar includes an `algorithm` field. Future versions can support ML-DSA-65 (Level 3) or ML-DSA-87 (Level 5) without breaking the format.

2. **Hybrid signatures**: During the transition period, a dual-signature approach (Ed25519 + ML-DSA-44) can provide security against both classical and quantum adversaries, hedging against the possibility that lattice assumptions are broken.

3. **Key management**: The current pipeline stores raw key bytes on disk. Production deployments should use HSMs, key encapsulation, or certificate chains for key lifecycle management.
