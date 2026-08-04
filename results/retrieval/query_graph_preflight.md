# Query-specific graph planning — Task 0 preflight rerun

> Captured: 2026-07-23T13:00:29.3463526Z
>
> Result: **PASSED — Task 1 may begin**
>
> Database: `neo4j`, Neo4j Community 5.26.28, `bolt://localhost:7688`
>
> Scope: `ldn_2020`, ontology v1.6.0

## Decision

Graph artifacts and the reviewed evaluation contract now agree. The three
exact-linear 2-step cases in V1 each return one topology when both endpoints
are bound independently. `multi_hop_03` now follows the resolver-first
representation and is a direct atomic Clause-to-Clause reference, so it remains
evaluation evidence but is not counted as a 2–3-step V1 planning case.

Task 0 passes. Task 1 may begin. QG-0 remains a later gate because it requires
the exact executor produced by Task 4.

## Pinned evidence

| Field | Value |
|---|---|
| Git commit | `48feb5510d25669fccbdb6995642ef296931f72d` |
| Evaluation dataset SHA-256 | `52b37c628826dfdc6f289596b28a0407b5652424615267ab510a971ed0447e41` |
| Graph projection SHA-256 | `294cf005d4d5926d5d09c9388236ff23d92cd6b845eeaef89a4d263f6280e291` |
| Projection rerun | Same hash; payload projection match |
| Scoped nodes | 2,224 |
| Scoped relationships | 3,042 |
| `REFERS_TO` | 377 |
| Artifact verification | `PASS` |

## Gold-case results

| Case | Shape | Gold path | Topologies | Exact | Evidence v1.6 | Result |
|---|---|---|---:|---:|---:|---|
| `multi_hop_01` | linear depth 2 | `art38_cl1 -> art41 -> art41_cl2` | 1 | Yes | Yes | Pass |
| `multi_hop_02` | linear depth 2 | `art145_cl3 -> art145_cl2 -> art145_cl1` | 1 | Yes | Yes | Pass |
| `multi_hop_03` | direct reference | `art57_cl1 -> art49_cl2` | 1 | Yes | Yes | Out of V1 plan shape |
| `multi_hop_04` | linear depth 2 | `art68_cl2 -> art52 -> art52_cl1` | 1 | Yes | Yes | Pass |
| `multi_hop_05` | branching one-hop | two branches to `art53_cl6/cl7` | 2 | N/A | Yes | Out of V1 plan shape |

All 11 distinct legal units used by cases 01–04 exist and have non-empty
`content_raw`, `effective_from`, and `legal_status`.

## Resolver-first correction for `multi_hop_03`

The citation text is `khoản 2 và khoản 3 Điều 49`. Resolver v2.0.1 emits two
atomic direct `REFERS_TO` edges with one `reference_bundle_id` and
`reference_target_count=2`. The reviewed answer target for this query is Clause
2. The old intermediate Article edge is not restored because it would duplicate
the citation and weaken the canonical reference representation.

## Provenance and repeatability

- 377/377 `REFERS_TO` relationships contain common provenance.
- No `RULE` relationship is missing resolver or source-span provenance.
- No `LLM` relationship is missing checkpoint provenance.
- Two consecutive read-only graph snapshots produced the same projection hash.
- Payload and Neo4j projections match; duplicate node/relation IDs are zero.

No Neo4j write, reset, or schema mutation was performed during this rerun.
