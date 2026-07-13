# M3 / Milestone A Blocker Register

> Last verified: 2026-07-12
> Parent plan: `06_m3_runtime_acceptance_and_milestone_a_plan.md`
> Status authority for M3 blockers: this file

## Current State

```text
Phase 1 M3: pilot signed off; BLOCKED on corpus completion
Milestone A: NOT PASSED
Phase 2 implementation: ACTIVE on signed-off pilot data
Phase 2 acceptance: BLOCKED by M3-B13
Canonical Neo4j pilot graph: VERIFIED on disposable M3 runtime
Graph-quality report: CURRENT
Neo4j pilot evidence: SIGNED OFF from source commit 3ab2baa
```

Retrieval development and pilot-only evaluation may proceed on `L59_2020`.
Do not close Milestone A, accept Milestone B, or report corpus-level Phase 2
results until every `MILESTONE BLOCKER` below is closed.

## Open Blockers

| ID | Problem | Status | Dependency | Close condition |
|---|---|---|---|---|
| M3-B13 | Four-document minimum corpus is incomplete | MILESTONE BLOCKER | Pilot sign-off | All four required documents complete the pipeline end to end with per-document reports |

## Closed Milestone Blockers

| ID | Evidence | Scope | Status |
|---|---|---|---|
| M3-B06 | Disposable runtime healthy; canonical schema verified; corrected 2333-node graph written | pilot | CLOSED |
| M3-B07 | Write 1/write 2 ID and projection digests identical; payload projection equals graph projection | pilot | CLOSED |
| M3-B08 | BGE-M3/1024 coverage Article 1.0 and Clause 1.0; resume updated 0 | pilot | CLOSED |
| M3-B09 | 30/30 human judgements; q1–q3 and both indexes relevant@5 pass | pilot | CLOSED |
| M3-B10 | Online report: zero ontology, duplicate, and dangling violations | pilot | CLOSED |
| M3-B11 | 4 integration tests passed; pre/post pilot digests identical | pilot | CLOSED |
| M3-B12 | Source commit `3ab2baa`; clean-at-runtime evidence; signed summary; evidence ref `m3-pilot-L59_2020` | pilot | CLOSED |

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

### Superseded extraction baseline (v1.5.0)

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

### Current canonical extraction and payload (ontology v1.5.1)

```text
source = 218 Article checkpoints; provider_called = false
extract.jsonl = 1743
accepted.jsonl = 775
review.jsonl = 434
rejected.jsonl = 534
accepted REFERS_TO = 67
REFERS_TO missing provenance = 0
REFERS_TO llm_model = gemini:gemini-3.1-flash-lite
payload nodes = 2333
payload relations = 2723
duplicate node IDs = 0
duplicate relation identities = 0
dangling endpoints = 0
ontology violations = 0
two-run decision/entity-index hashes = identical
```

### Verification completed

```text
fast tests = 174 passed
integration tests = 4 passed against disposable Neo4j
git diff --check = passed
disposable Compose config = validated offline
unsafe reset without opt-in = rejected
M3 URI/schema/snapshot guards = implemented and unit-tested
payload projection equals graph projection
write 1/write 2 digests are identical
Article/Clause embedding coverage = 1.0 / 1.0
embedding resume = updated 0 / skipped 1115
online graph-quality integrity errors = 0
integration pre/post pilot digests are identical
vector judgement validator = 30/30 PASS
semantic edge accounting = 775 total = 746 topology + 29 Point-endpoint REFERS_TO exclusions
```

## Required Resolution Order

1. Implement and verify the disposable runtime guards and schema tooling in Plan 08.
2. Reset the stale disposable/local graph, write twice, and prove payload-to-graph projection equality.
3. Re-embed Article/Clause nodes with BGE-M3/1024.
4. Run and record the three vector top-5 smoke queries.
5. Regenerate the online graph-quality report.
6. Pass the disposable-database integration suite without changing the pilot graph.
7. Generate and review the tracked Milestone A evidence summary.
8. Complete the four-document minimum corpus and reconcile external references.
9. Sign off Milestone A, then explicitly unblock Phase 2 corpus evaluation and
   Milestone B acceptance.

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

### M3-R07: Canonical endpoint normalization and Gate 3 payload validation

- Full extraction completed with 218 unique Article checkpoints using resolved
  model `gemini-3.1-flash-lite`.
- Decision counts reconcile: `1743 = 775 accepted + 434 review + 534 rejected`.
- LLM `CONTAINS`, accepted unresolved endpoints, and accepted structural aliases
  are all zero.
- 35 global semantic type conflicts moved 218 relations to review instead of
  silently choosing the last observed type.
- Payload counts: Article 218, Clause 897, Point 822.

### M3-R08: Ontology v1.5.1 `REFERS_TO` provenance migration

- ADR-21 and ontology v1.5.1 require semantic provenance plus citation metadata.
- Active v1.5.0 artifacts are archived as superseded; checkpoints remain the immutable source.
- Two offline normalizations produced identical decision and entity-index hashes.
- All 67 accepted `REFERS_TO` relations contain checkpoint-derived provenance.
- Gate 2 and Gate 3 pass under ontology v1.5.1; Gate 4 remains blocked.
- Payload integrity: zero duplicate nodes, duplicate relation identities,
  dangling endpoints, and ontology violations.
- `REQUIRES` identity includes `source_article`, preserving distinct legal
  provenance for otherwise identical semantic endpoint pairs.
- Fast suite: 139 passed; 4 Neo4j integration tests remain separately gated.

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
open. Pilot retrieval work is development evidence only; it is not accepted
Milestone B or corpus-level Phase 2 evidence.
