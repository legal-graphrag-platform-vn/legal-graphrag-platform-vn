# M3 / Milestone A Blocker Register

> Last verified: 2026-07-12
> Parent plan: `06_m3_runtime_acceptance_and_milestone_a_plan.md`
> Status authority for M3 blockers: this file

## Current State

```text
Phase 1 M3: BLOCKED at Gate 3
Milestone A: NOT PASSED
Phase 2: BLOCKED / prototype only
Canonical Neo4j graph: STALE
Graph-quality report: STALE
Neo4j evidence: STALE
```

Do not run or count Phase 2 work as active progress until every blocker marked
`MILESTONE BLOCKER` below is closed and the Milestone A evidence is signed off.

## Open Blockers

| ID | Problem | Status | Dependency | Close condition |
|---|---|---|---|---|
| M3-B05 | Corrected payload has not passed validation | MILESTONE BLOCKER | M3-B14 | Dry run reports canonical counts, zero duplicates, zero dangling endpoints, and zero ontology violations |
| M3-B14 | Accepted records contain noncanonical structural endpoints | MILESTONE BLOCKER | M3-B04 | LLM `CONTAINS` accepted count and unresolved accepted endpoint count are zero; all accepted endpoints resolve against hierarchy/entity registry |
| M3-B06 | Current Neo4j graph is stale | MILESTONE BLOCKER | M3-B05 | Old 756-Point graph is reset through the approved disposable/local procedure and replaced with the corrected payload |
| M3-B07 | Corrected write idempotency is unverified | MILESTONE BLOCKER | M3-B06 | Two writes produce identical node/relation counts and every relation has `relation_id` |
| M3-B08 | Embeddings are stale | MILESTONE BLOCKER | M3-B07 | All corrected Article/Clause nodes are re-embedded with BGE-M3/1024 and both coverages equal 1.0 |
| M3-B09 | Vector top-5 smoke evidence is missing | MILESTONE BLOCKER | M3-B08 | Three required queries have stored top-5 IDs, scores, and manual relevance judgements |
| M3-B10 | Graph-quality report is stale | MILESTONE BLOCKER | M3-B04, M3-B07, M3-B08 | Online Neo4j report has semantic relations/coverage > 0 and zero ontology, duplicate, dangling integrity errors |
| M3-B11 | Neo4j integration suite has not passed | MILESTONE BLOCKER | M3-B07, M3-B08 | All tests under `tests/integration/` pass against a disposable Neo4j database |
| M3-B12 | Milestone A evidence summary is missing | MILESTONE BLOCKER | M3-B05 through M3-B11 | `results/milestone_a/L59_2020_summary.md` contains all required runtime evidence |
| M3-B13 | Four-document minimum corpus is incomplete | MILESTONE BLOCKER | Pilot sign-off | All four required documents complete the pipeline end to end with per-document reports |

## Current Evidence

### Canonical local hierarchy

```text
raw_doc_code = L59_2020
graph_id = ldn_2020
Chapter = 10
Article = 218
Clause = 897
Point = 822
duplicate Point labels = 0
```

### Completed extraction (invalid for write)

```text
provider = gemini
model = gemini-flash-lite-latest
extract.jsonl = 1779
accepted.jsonl = 586
review.jsonl = 0
rejected.jsonl = 1193
entity_index entries = 795
unresolved endpoint IDs = 189
unresolved endpoint references = 718
payload failure = Accepted relation references missing entity: khoan_1_1
```

### Verification completed

```text
fast tests = 116 passed
integration tests = 4 deselected / not accepted as passed
git diff --check = passed
```

## Required Resolution Order

1. Archive the invalid pre-normalization artifacts.
2. Rerun extraction with canonical structural context and resumable Article checkpoints.
3. Close M3-B14, then run payload dry validation against the corrected 822-Point hierarchy.
4. Reset the stale local graph, write twice, and prove idempotency.
5. Re-embed Article/Clause nodes with BGE-M3/1024.
6. Run and record the three vector top-5 smoke queries.
7. Regenerate the online graph-quality report.
8. Pass the disposable-database integration suite.
9. Generate and review the tracked Milestone A evidence summary.
10. Complete the four-document minimum corpus.
11. Sign off Milestone A, then explicitly unblock Phase 2.

## Required Vector Smoke Queries

```text
quyền thành lập và quản lý doanh nghiệp
vốn điều lệ của công ty trách nhiệm hữu hạn
đăng ký thay đổi nội dung đăng ký doanh nghiệp
```

For each query, record the top-5 node IDs, scores, and a manual
`relevant` / `not relevant` judgement.

## Resolved Blockers

### M3-R06: Provider/model availability and non-empty Gate 2 artifacts

- `gemini-flash-lite-latest` completed the pilot provider run.
- Decision counts reconcile: `1779 = 586 + 0 + 1193`.
- The semantic entity index contains 795 entries.
- Gate 2 completion does not close Gate 3; the pre-normalization run is invalid
  for write because accepted endpoints are not canonical.

### M3-R01: Point identity collision `d` / `đ`

- `d` maps to `pd`.
- `đ` maps to `pdd`.
- Payload duplicate IDs with different content fail fast.

### M3-R02: Duplicate Point `c` at Article 215 Clause 4

- Local raw data repeated the same Point `c` around a VBPL amendment annotation.
- Crawler removes amendment annotation markers.
- Parser deduplicates only identical label + identical content.
- Same label with different content remains a hard failure.
- Canonical local reparse produces 822 Points with no duplicate labels.

### M3-R03: False pass after empty extraction

- `validate-payload`, `write`, `embed`, and `graph-quality` call extraction readiness.
- Empty `accepted.jsonl` blocks Gate 2 and all downstream Milestone A commands.

### M3-R04: Unsafe legal status fallback

- Unknown source status no longer defaults to `ACTIVE`.
- Metadata/manifest identity mismatch is rejected.

### M3-R05: Fatal extraction provider errors did not stop the run

- Gemini 404/model, 401/auth, 403/permission, and 429/quota errors map to
  `FatalExtractionProviderError` and are not retried.
- Orchestrator uses bounded scheduling and does not queue the full corpus upfront.
- Fatal failure cancels pending work, writes `extraction_blocked.json`, clears stale
  extraction artifacts, and returns a non-zero CLI exit.
- Real smoke run submitted only the two configured in-flight Articles and did not
  continue to Article 3.

## Sign-off Rule

Milestone A is all-or-nothing. It remains `NOT PASSED` while any `M3-B*` row is
open. Existing retrieval code may remain in the repository only as prototype code;
it is not accepted Phase 2 or Milestone B progress.
