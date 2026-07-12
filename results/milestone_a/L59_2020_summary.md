# Milestone A Pilot Evidence — L59_2020

> Status: PILOT GATES PASS — clean evidence commit and four-document corpus remain open
> Generated: 2026-07-13
> Git commit: `3e18d8e2e02af3f52e99ee7a95334878de9022aa` plus current uncommitted implementation

## Contract

- raw_doc_code: `L59_2020`
- graph_id: `ldn_2020`
- ontology: `v1.5.1`
- ADR: `ADR-21`
- Neo4j: `5.26.28-community`, disposable `bolt://localhost:7688`
- embedding: `BAAI/bge-m3`, `flag_embedding`, 1024 dimensions, normalized

## Gate 2

| Metric | Value |
|---|---:|
| Article checkpoints | 218 |
| Extracted | 1743 |
| Accepted | 775 |
| Review | 434 |
| Rejected | 534 |
| Accepted REFERS_TO | 67 |
| REFERS_TO missing provenance | 0 |

Artifacts were regenerated offline from checkpoints with `provider_called=false`.
Two normalization runs produced identical decision and entity-index hashes.

## Gate 3

| Node | Count |
|---|---:|
| Document | 1 |
| Issuer | 1 |
| Chapter | 10 |
| Article | 218 |
| Clause | 897 |
| Point | 822 |
| LegalAction | 209 |
| LegalConcept | 102 |
| LegalSubject | 73 |
| Total | 2333 |

| Relation | Count |
|---|---:|
| ISSUED_BY | 1 |
| CONTAINS | 1947 |
| DEFINES | 120 |
| REGULATES | 535 |
| REQUIRES | 53 |
| REFERS_TO | 67 |
| Total | 2723 |

Duplicate node IDs, duplicate relation identities, dangling endpoints, missing
relation IDs, and ontology violations are all zero.

## Gate 4

- Schema verifier: passed, including 1024/cosine vector indexes.
- Write 1/write 2 node and relation counts: identical.
- `node_id_sha256`: `44391892a03c671c9bd7bcf09b868660bb1b37f4feffde48bf146464a2466675`
- `relation_id_sha256`: `35faac7b85225ab70cc5ee8ccc8c72799ff37612987388dedc2740d9ef37047f`
- `payload_projection_sha256`: `67d0318fbb32b3c0f7ad9b4842515b2c5cd074f4021cebba32338103795f0091`
- `graph_projection_sha256`: `67d0318fbb32b3c0f7ad9b4842515b2c5cd074f4021cebba32338103795f0091`
- Integration tests: `4 passed` against disposable Neo4j.
- Fast tests: `174 passed`; static checks passed.
- Pre/post integration legal and embedding digests: identical.

Temporal storage types:

```text
node.effective_from = DATE
node.issued_date = DATE
relation.created_at = ZONED DATETIME
```

## Gate 5

- Article embedding coverage: `218/218 = 1.0`
- Clause embedding coverage: `897/897 = 1.0`
- Resume run: `updated=0`, `skipped=1115`
- `embedding_state_sha256`: `18d63fd1fdde659ca4d10b066882ff1e359ce7dccae4ad33daa57800652da5e4`
- Legal graph projection remained unchanged after embedding.

Vector smoke top-1 results:

| Query | Article top-1 | Clause top-1 |
|---|---|---|
| quyền thành lập và quản lý doanh nghiệp | `ldn_2020_art17` | `ldn_2020_art17_cl1` |
| vốn điều lệ của công ty trách nhiệm hữu hạn | `ldn_2020_art75` | `ldn_2020_art75_cl1` |
| đăng ký thay đổi nội dung đăng ký doanh nghiệp | `ldn_2020_art30` | `ldn_2020_art30_cl4` |

Manual relevance judgements: `30/30` complete, reviewer `lamdx4`.
All three queries and both vector indexes pass relevant@5.

## Graph Quality

- Source: Neo4j
- Ontology violations: 0
- Duplicate node/relation identities: 0
- Dangling endpoints: 0
- Full graph connected components: 1
- Article semantic coverage: 0.2431192661
- Article/Clause semantic orphans: 628
- Semantic entity orphans: 0
- Semantic-only connected components: 801
- Semantic edge accounting: `775 = 746 topology edges + 29 REFERS_TO edges excluded because a Point endpoint is outside the semantic topology universe`

The semantic orphan metrics are quality observations, not schema violations.

## Remaining Gates

1. Create a clean evidence commit and regenerate the final commit-bound snapshot.
2. Sign off this pilot summary.
3. Complete the four-document minimum corpus and external-reference reconciliation.
4. Do not start Phase 2 until Milestone A is explicitly signed off.
