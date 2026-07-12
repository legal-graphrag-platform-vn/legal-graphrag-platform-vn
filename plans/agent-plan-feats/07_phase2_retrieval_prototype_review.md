# Phase 2 Retrieval Prototype Review and Deferred Fix Register

> Reviewed: 2026-07-12
> Parent plan: `07_phase2_graphrag_retrieval_plan.md`
> Canonical ontology: `plans/legal_ontology.md` v1.5.0
> Canonical retrieval contract: `plans/05_graphrag_retrieval.md`
> Status: DEFERRED; do not implement until Milestone A is signed off

## Status

```text
Phase 1 M3: BLOCKED
Milestone A: NOT PASSED
Phase 2: BLOCKED / prototype only
Retrieval prototype runtime readiness: FAIL
Temporal/legal correctness: UNSAFE
```

The files under `src/retrieval/` are architecture prototypes only. They must not
be counted as active Phase 2 progress or accepted Milestone B work. Do not fix or
promote them while `06_m3_blocker_register.md` still contains open Milestone A
blockers.

## Deferred Findings

| ID | Severity | Problem | Required fix | Verification |
|---|---|---|---|---|
| P2-R01 | High | Vector retriever passes a string to `EmbeddingGenerator.encode()` and forwards the resulting batch instead of one vector | Use `encode([query])[0]`; validate 1024 dimensions before repository call | Fake encoder contract test and Neo4j vector integration test |
| P2-R02 | High | Full-text retriever calls nonexistent `article_fulltext` and `clause_fulltext` indexes | Use schema names `legal_article_clause_fulltext` and `legal_point_fulltext`, or revise schema and retrieval together | Schema-name parity test and live full-text query |
| P2-R03 | High | Document context traversal uses `CONTAINS*1..2`, missing Clause nodes under `Document -> Chapter -> Article -> Clause` | Resolve parent Document through canonical depth 1..3 without duplicate rows | Repository mapping test for Article and Clause with/without Chapter |
| P2-R04 | High | Graph traversal policies do not match the six canonical intents or ontology relations | Implement one explicit policy registry matching `plans/05_graphrag_retrieval.md` | Parameterized policy tests for all six intents |
| P2-R05 | High | `obligation` and `citation` branches are dead because they are not `IntentType` values | Remove dead branches and express their behavior inside factual/multi-hop policies | No unreachable intent branch; taxonomy parity test |
| P2-R06 | High | `comparison` and fallback traversal use unrestricted relationships; hierarchy misses `GUIDES`; factual misses `DEFINES`/`REFERS_TO` | Restrict every traversal to canonical relation allowlists and correct depth/direction | Cypher snapshot tests and ontology relation parity test |
| P2-R07 | High | Graph-expanded nodes are not added to the candidate/reranking pool | Fetch graph-expanded legal units with content/provenance and merge them before temporal filtering/reranking | Hybrid test proving graph-only relevant unit can enter final top-k |
| P2-R08 | High | Temporal filtering permits missing dates, ignores `resolved_to`, and treats year queries as January 1 only | Define strict point-in-time versus interval semantics and reject/penalize incomplete temporal metadata | Boundary tests for effective_from/effective_to and year intervals |
| P2-R09 | High | Version conflict grouping uses document number and cannot resolve versions across amending documents | Resolve through canonical IDs and temporal relation chains; preserve amendment direction | Version-chain tests for incoming/outgoing AMENDS/REPEALS/REPLACES |
| P2-R10 | High | Graph paths are always marked temporally valid | Validate every temporal node/relation in each path before producing evidence | Invalid-path rejection tests |
| P2-R11 | Medium | Evidence sufficiency threshold `0.5` is incompatible with normal RRF scores around `0.01-0.03` | Calibrate by score family or use rank/provenance-based sufficiency rules | Tests for RRF-only, reranked, graph, and temporal evidence |
| P2-R12 | Medium | Evidence provenance is lost; BM25-only results may be labelled vector evidence | Preserve per-source ranks/scores and emit separate evidence items or source lists | Provenance tests for vector-only, BM25-only, fused, graph, and rerank |
| P2-R13 | Medium | Rule-based intent classifier maps any `Điều N`/`Khoản N` query to hierarchy | Replace citation-presence heuristic with structural-question patterns and conflict precedence | Vietnamese intent fixture set covering all six classes |
| P2-R14 | Medium | Lucene special characters are not escaped | Add a tested Neo4j/Lucene query escaping layer | Tests for `:`, `/`, `(`, `)`, `+`, `-`, quotes and backslashes |
| P2-R15 | Medium | `retrieval_mode` does not reflect actual vector/BM25/graph participation; `vector_graph` is unreachable | Derive mode from recorded source participation and remove false text fallback claims | ContextBuilder mode matrix tests |
| P2-R16 | Medium | Benchmark runner executes one retriever only and does not produce ablation variants | Add explicit Vector-only, Vector+Graph, Hybrid, and Proposed configurations | Deterministic ablation report with Recall@5, MRR, nDCG |
| P2-R17 | Low | Odd `top_k` splits return fewer candidates than requested | Allocate remainder deterministically or query each source with top_k before fusion | Tests for odd/even top_k |
| P2-R18 | Test gap | Only RRF and partial temporal behavior are tested | Add repository, query analyzer, policy, hybrid, evidence, context and benchmark tests | Fast suite covers every contract before live integration |

## Canonical Traversal Requirements

When Phase 2 is unblocked, implementation must use the following policy baseline:

```text
factual:
  relations = REGULATES, DEFINES, REQUIRES, REFERS_TO
  max_depth = 2

validity:
  relations = AMENDS, REPLACES, REPEALS
  max_depth = 3
  direction depends on whether query asks what changed the old unit or what the new unit changed

hierarchy:
  relations = GUIDES, CONTAINS
  max_depth = 3
  direction = both

comparison:
  relations = AMENDS, REPLACES
  max_depth = 5
  return all temporally relevant versions

definition:
  relations = DEFINES
  max_depth = 1

multi_hop:
  relations = canonical ontology relations only
  max_depth = 3
  temporal validation required
```

`ALL` never means arbitrary database relationships. It means the canonical relation
enum from `src/shared/ontology/contract.py`, excluding legacy aliases and any
non-ontology operational relationship.

## Required Fix Order After Milestone A

1. Fix vector embedding shape, full-text index names, and Document path depth.
2. Create the canonical six-intent traversal policy registry.
3. Replace unrestricted Cypher and enforce active-voice temporal directions.
4. Add graph-expanded legal units to the candidate pool.
5. Define temporal point/interval/version conflict semantics.
6. Preserve evidence provenance and calibrate sufficiency rules.
7. Correct intent heuristics, retrieval modes, Lucene escaping, and odd top-k behavior.
8. Build the full fast contract suite.
9. Run Neo4j vector/full-text/graph integration tests.
10. Implement benchmark variants and generate the Milestone B ablation table.

## Promotion Gate

The prototype may become active Phase 2 code only when:

- Milestone A is signed off;
- every High finding above has a passing contract test;
- no retrieval module imports from `src/pipeline/`, `apps/`, or `prototypes/`;
- schema/index names match the live Neo4j bootstrap;
- temporal queries cannot silently accept unknown validity metadata;
- graph-expanded units affect final ranked results;
- benchmark variants are reproducible and use a held-out dataset.

## Review Verification

```text
retrieval tests = 4 passed
retrieval compileall = passed
import-boundary violations found = 0
runtime/schema contract blockers = present
promotion decision = rejected until deferred fixes and Milestone A sign-off
```
