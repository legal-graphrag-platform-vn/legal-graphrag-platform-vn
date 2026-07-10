# Detailed Implementation Plan — Graph Construction Pipeline

> Target spec: `plans/04_graph_construction_pipeline.md`  
> Canonical ontology: `plans/legal_ontology.md` v1.5.0
> Status: implemented M3 contract; paths updated after monorepo package flattening

---

## 1. Summary

This plan extends the current source tree instead of replacing it.

The active graph-construction path remains:

```text
web crawl -> raw source.txt + metadata.json
  -> hierarchy parser
  -> LLM extraction
  -> schema validation
  -> relation enrichment
  -> label normalization
  -> ontology validation
  -> graph consistency validation
  -> confidence scoring
  -> decision gate
  -> graph payload builder
  -> write-time ontology validation
  -> Neo4j writer
  -> embedding fill
```

The active source now covers crawl, parse, extract, schema validation, relation enrichment, label normalization, ontology validation, scoring, JSON output, guarded Neo4j writes, embeddings, and graph-quality reporting. Remaining M3 work is runtime verification against Neo4j and Milestone A acceptance.

`prototypes/legal_graphrag_legacy` is prototype/reference code only. It must not become active graph-construction code without explicit migration and contract validation.

---

## 2. Current Source Boundary

Use these modules as the implementation anchors:

| Area | Current source | Role |
|---|---|---|
| CLI | `src/pipeline/main.py` | Active crawl/parse/extract/write/embed/graph-quality/ingest entrypoint |
| Crawler | `src/pipeline/crawler/` | Web crawl -> `data/raw/<doc_id>` |
| Parser | `src/pipeline/parser/` | `source.txt` + metadata -> `hierarchy.json` |
| Extraction | `src/pipeline/extraction/` | two-pass LLM extraction |
| Pipeline orchestration | `src/pipeline/pipeline/orchestrator.py` | validation, enrichment, scoring, JSONL output |
| Shared ontology contract | `src/shared/ontology/contract.py` | canonical constants for extraction and write validation |
| Write-time validator | `src/shared/ontology/validators.py` | canonical payload validation before writer |
| Neo4j writer | `src/infrastructure/neo4j/writer.py` | guarded `MERGE` writer |
| Prototype | `prototypes/legal_graphrag_legacy/` | quarantined reference only |

Implementation rule: Neo4j writes must go through `GraphIngestionService.ingest(...)` or an equivalent shared validation gate. No active pipeline code may call the Neo4j driver directly for graph writes.

---

## 3. Implementation Changes

### 3.1 Quarantine `prototypes/legal_graphrag_legacy`

The former `src/legal-graphrag` prototype is isolated under `prototypes/legal_graphrag_legacy`.

Required actions:

- Remove nested `.git` from the prototype before staging in the parent repo.
- Remove generated `__pycache__` files.
- Remove hardcoded API key material from `temp/test_router_api.py`.
- Rotate/revoke any real API key that has already appeared in the prototype.
- Keep `temp/` scripts out of active imports.
- Do not import `prototypes/legal_graphrag_legacy` from `src/` or `apps/`.

Explicitly forbidden active patterns:

- `BaseNode`
- `entity_vector`
- embedding model/dimension outside the canonical configured contract
- `MATCH (n) DETACH DELETE n`
- direct dynamic-label `MERGE` from raw JSON
- legacy uppercase graph IDs such as `LDN2020_D17`

Allowed reuse later:

- intent routing idea
- graph traversal idea
- answer-generation prompt idea
- conversation memory idea

Those ideas belong in retrieval/reasoning work, not M3 graph construction.

### 3.2 Align Pipeline and Write-Time Validators

The repo uses two validation stages backed by one shared ontology contract:

- extraction-stage validation through `src/shared/ontology/extraction_validator.py`
- write-time validation through `src/shared/ontology/validators.py`

They must agree on Phase 1 persistence.

Required changes:

- Treat `src/shared/ontology/contract.py` as the constants authority and `src/shared/ontology/validators.py` as the write-time validation authority.
- Keep pipeline validator focused on relation validation before scoring.
- Ensure both validators reject legacy aliases.
- Ensure both validators reject extraction labels after Step 3.6.
- Keep shared-contract and parity tests to prevent drift between validation stages.
- Ensure Phase 1 rejects runtime-only persistence:
  - `Obligation`
  - `Right`
  - `Condition`
  - `Exception`
- Ensure Phase 1 `REQUIRES` only accepts:

```text
LegalSubject -> LegalConcept
```

`LegalSubject -> Obligation` remains future/runtime scope and must not be accepted by the Phase 1 write payload validator.

Minimum drift guard:

```text
test_pipeline_and_root_validator_contracts_match()
```

This test must compare relation enums, legacy alias rejection, label normalization rules, Phase 1 persisted labels, runtime-only labels, `GUIDES_WHITELIST`, and `REQUIRES` valid pairs.

### 3.3 Add Graph Payload Builder

Add a graph payload builder after extraction and before writer validation.

Suggested module:

```text
src/pipeline/persistence/payload_builder.py
```

Input:

```text
data/processed/<doc_id>/hierarchy.json
data/processed/<doc_id>/accepted.jsonl
data/processed/<doc_id>/entity_index.json
```

No unsafe fallback:

```text
write command must not read extract.jsonl unless every selected record has decision = "accepted"
```

Preferred M3 behavior: `write` reads only `accepted.jsonl`. `extract.jsonl` is an audit log, not a writer input.

Only schema-valid, ontology-valid, consistency-valid, accepted records may be converted to write payload relations.

Semantic entity source:

- `entity_index.json` is generated during extraction from validated entity extraction output.
- It stores normalized entity objects keyed by entity ID.
- Payload builder reads `accepted.jsonl` plus `entity_index.json`.
- Only semantic entities referenced by accepted relations are written.
- If `entity_index.json` is missing or a referenced semantic entity is missing, `write` must fail fast instead of inventing a node.

`entity_index.json` shape:

```json
{
  "entity_id": {
    "id": "von_dieu_le",
    "type": "LegalConcept",
    "label": "Vốn điều lệ",
    "name": "Vốn điều lệ",
    "aliases": [],
    "description": null
  }
}
```

Output shape:

```python
{
    "nodes": [...],
    "relations": [...]
}
```

Node generation rules:

- Build one `Document` node from `ParsedDocument.document`.
- The `Document` node must include all required ontology fields before payload validation:
  - `id`
  - `doc_type`
  - `number`
  - `normative`
  - `legal_status`
  - `effective_from`
  - `issuer_name`
- Raw metadata must be mapped before payload output:
  - `metadata.type` -> `Document.doc_type`
  - `metadata.status` -> `Document.legal_status`
  - `metadata.normative` or derived value -> `Document.normative`
  - `metadata.issuer_name` -> `Document.issuer_name`
  - `metadata.effective_from` -> `Document.effective_from`
  - `metadata.number` -> `Document.number`
- Missing any required `Document` field is a hard failure before write-time validation.
- Derive one `Issuer` node from `Document.issuer_name`.
- Build `Chapter` nodes only when article chapter metadata exists.
- Build `Article` nodes for every parsed article.
- Build `Clause` nodes for every parsed clause.
- Build `Point` nodes for every parsed point.
- Build semantic nodes from accepted extracted entities.
- Normalize semantic labels before payload output:
  - `Entity` -> `LegalSubject`
  - `Concept` -> `LegalConcept`
  - `Action` -> `LegalAction`

Structural relation generation rules:

- `Document -[:ISSUED_BY]-> Issuer`
- `Document -[:CONTAINS]-> Chapter` when chapters exist
- `Chapter -[:CONTAINS]-> Article` when article belongs to a chapter
- `Document -[:CONTAINS]-> Article` when no chapter is present
- `Article -[:CONTAINS]-> Clause`
- `Clause -[:CONTAINS]-> Point`

Semantic relation generation rules:

- Read accepted extraction records.
- Use enriched relation properties from `orchestrator.py`.
- Preserve required properties:
  - `REFERS_TO`: `citation_text`, `citation_type`
  - semantic relations: `confidence`, `llm_model`, `created_at`
  - temporal relations: `effective_from`
- Do not invent missing required properties inside the writer.

ID rules:

- `Document`: existing canonical `document.id`
- `Issuer`: slug from normalized `issuer_name`
- `Chapter`: `{document.id}_ch{chapter_number_arabic}`
- `Article`: `{document.id}_art{article_number}`
- `Clause`: `{document.id}_art{article_number}_cl{clause_number}`
- `Point`: `{document.id}_art{article_number}_cl{clause_number}_p{label}`
- Semantic nodes: snake-case, no Vietnamese diacritics

Semantic ID normalization rule:

- Prefer the concept/entity normalizer when available.
- Use pre-defined mappings for known legal concepts and subjects to avoid duplicates such as `von_dieu_le`, `von_dieu_le_cong_ty`, and `vdl`.
- Fallback to `slug(label)` only when no predefined mapping exists.

Chapter normalization rule:

- Preserve the chapter display number/title for user-facing fields.
- Normalize Roman numerals for IDs.
- Example: `Chương II` -> `number = "II"` or display metadata, but `id = ldn_2020_ch2`.

Filesystem vs graph ID rule:

- CLI/path arguments use `raw_doc_code`, the folder name under `data/raw` and `data/processed`.
- Payload node IDs use canonical `graph_id`, exposed as `ParsedDocument.document.id`.
- Example: `--raw-doc-code LDN2020` reads `data/processed/LDN2020`, but writes `Document.id = ldn_2020`.

Relation idempotency rule:

- Every relationship write must be `MERGE`-safe.
- Structural relations are unique by `(head_id, relation_type, tail_id)`.
- Semantic relations are unique by `(head_id, relation_type, tail_id)`.
- Temporal relations are unique by `(head_id, relation_type, tail_id, effective_from)`.
- Add a deterministic `relation_id` property when it simplifies tests or writer guarantees:

```text
relation_id = sha1(head_id + "|" + relation_type + "|" + tail_id + "|" + effective_from_or_empty)
```

### 3.4 Add Explicit Decision Gate Output

Extend extraction output from a single `extract.jsonl` into decision-specific files.

Validation order rule:

```text
schema validation
-> relation enrichment
-> label normalization
-> ontology validation
-> graph consistency validation
-> confidence scoring
-> decision gate
```

A record may enter `accepted.jsonl` only after schema validation, ontology validation, graph consistency validation, and confidence threshold pass. Graph consistency failures must never be discovered only after `accepted.jsonl` has been written.

Output files:

```text
data/processed/<doc_id>/extract.jsonl
data/processed/<doc_id>/accepted.jsonl
data/processed/<doc_id>/review.jsonl
data/processed/<doc_id>/rejected.jsonl
```

Rules:

- `extract.jsonl` remains the full audit log.
- `accepted.jsonl` contains only records with `schema_valid=true`, `ontology_valid=true`, `consistency_valid=true`, and accepted confidence.
- `review.jsonl` contains schema-valid and ontology-valid records with consistency uncertainty or review-range confidence.
- `rejected.jsonl` contains schema-invalid, ontology-invalid, or consistency-hard-fail records.
- Confidence scoring must never override schema or ontology failure.
- Consistency hard failures must never be auto-accepted.

Each decision record must include:

```json
{
  "decision": "accepted|review|rejected",
  "review_reason": null,
  "blocking": false
}
```

Required `review_reason` values:

```text
low_confidence
missing_external_document_registry
ambiguous_citation_target
temporal_metadata_incomplete
guides_doc_type_unknown
```

Default thresholds until calibration:

```text
T_auto = 0.80
T_review = 0.55
```

These thresholds must be configuration values, not hidden literals.

These are bootstrap values only. They must be replaced after PR-curve calibration on manually annotated triples. Tests must check config behavior, not depend on hidden threshold literals.

### 3.5 Add Graph Consistency Validators

Add record-level consistency validation before confidence scoring and before any record can enter `accepted.jsonl`.

Run payload-level consistency validation again after graph payload building and before write-time ontology validation.

Suggested modules:

```text
src/pipeline/validation/record_consistency_validator.py
src/shared/ontology/payload_consistency_validator.py
```

Record-level checks:

- relation endpoints resolve against article-local entities or known document registry entries
- external document reference exists in registry or is marked for review
- temporal relation is not a self-loop
- temporal relation has enough metadata to determine direction
- `GUIDES` has enough document type information for whitelist validation

Payload-level checks:

- duplicate node IDs
- dangling relation endpoints
- invalid parent-child structural chain
- duplicate relation identity
- orphan nodes
- malformed deterministic `relation_id`

Behavior:

- Record-level hard failures go to `rejected.jsonl`.
- Record-level uncertainty goes to `review.jsonl`.
- Payload-level failures stop `write` before write-time ontology validation.
- No consistency failure can be auto-written.
- Payload-level consistency is a defensive whole-graph check; record-level consistency is the gate for `accepted.jsonl`.

### 3.6 Add Neo4j Write Command

Extend `src/pipeline/main.py` with a write command.

CLI:

```bash
python -m src.pipeline.main write --raw-doc-code <raw_doc_code>
```

Behavior:

- Read `data/processed/<raw_doc_code>/hierarchy.json`.
- Read `data/processed/<raw_doc_code>/accepted.jsonl`.
- Build graph payload.
- Run graph consistency validation.
- Run write-time `OntologyValidator.validate_graph_payload(...)`.
- Write via `GraphIngestionService.ingest(...)`.

Do not:

- call Neo4j driver directly from the CLI
- silently write records from `review.jsonl`
- write raw LLM output
- create labels outside the ontology

Optional later CLI:

```bash
python -m src.pipeline.main ingest --url <url> --doc-id <raw_doc_code> --number <number>
```

Keep this optional until `write` is tested in isolation.

### 3.7 Add Embedding Generation

Add embedding as a separate post-write step.

Suggested modules:

```text
src/pipeline/embedding/embedding_generator.py
src/infrastructure/neo4j/embedding_writer.py
```

CLI:

```bash
python -m src.pipeline.main embed --raw-doc-code <raw_doc_code>
```

Contract:

- Primary model: `BAAI/bge-m3` via `FlagEmbedding`
- Required configured dimension: 1024
- Explicit baseline: BKAI Vietnamese bi-encoder, 768-dim, with a matching baseline index run
- Write only:
  - `Article.embedding`
  - `Clause.embedding`
- Do not embed `Point`.
- Do not create `BaseNode`.
- Do not create `entity_vector`.
- Fail fast if embedding output dimension differs from configured schema dimension.
- Verify Neo4j vector indexes exist before writing embeddings.
- Update only `Article` and `Clause` nodes belonging to the current canonical document ID/prefix.
- Normalize embeddings if required by the selected embedding model and cosine retrieval behavior.

Embedding text:

- `Article`: title plus `content_raw`
- `Clause`: parent article title plus clause content

### 3.8 Keep Retrieval Prototype Out of M3

Do not connect `prototypes/legal_graphrag_legacy/core/retriever.py` to the M3 graph writer.

Retrieval will be implemented later against the canonical Neo4j schema:

```text
article_embedding
clause_embedding
Article
Clause
Document
CONTAINS
REFERS_TO
AMENDS
REPEALS
REPLACES
GUIDES
```

The M3 writer must produce data that retrieval can use later, but M3 does not need to implement answer generation.

### 3.9 Add Graph Quality Report

Add a lightweight graph quality report after write and embedding.

Optional CLI:

```bash
python -m src.pipeline.main graph-quality --raw-doc-code <raw_doc_code>
```

Minimum metrics:

- document count
- article count
- clause count
- semantic node count
- relation count by type
- ontology violation rate after write payload validation
- duplicate node ID count
- duplicate relation identity count
- orphan node count
- embedding coverage for `Article` and `Clause`
- connected component count for the written document subgraph

The report may be JSON first. A human-readable Markdown summary can be added later.

Output paths:

```text
data/reports/<raw_doc_code>/graph_quality.json
data/reports/<raw_doc_code>/graph_quality.md
```

---

## 4. Public Interfaces and Contracts

### CLI Additions

Add:

```bash
python -m src.pipeline.main write --raw-doc-code <raw_doc_code>
python -m src.pipeline.main embed --raw-doc-code <raw_doc_code>
python -m src.pipeline.main graph-quality --raw-doc-code <raw_doc_code>
```

Keep existing:

```bash
python -m src.pipeline.main crawl ...
python -m src.pipeline.main crawl-search ...
python -m src.pipeline.main parse ...
python -m src.pipeline.main extract ...
python -m src.pipeline.main ingest ...
```

### Payload Builder Interface

Recommended callable:

```python
build_graph_payload(
    parsed_document: ParsedDocument,
    accepted_records: list[dict],
    entity_index: dict[str, dict],
    *,
    raw_doc_code: str,
) -> dict
```

Return:

```python
{
    "nodes": list[dict],
    "relations": list[dict],
}
```

### Writer Boundary

Only this write path is allowed:

```python
payload = build_graph_payload(parsed, accepted_records, entity_index, raw_doc_code=raw_doc_code)
payload_consistency_validator.validate(payload)
validated_payload = OntologyValidator().validate_graph_payload(payload)
Neo4jWriter(session).write(validated_payload)
```

If using `GraphIngestionService`, it must accept or internally create a `ValidatedGraphPayload`. The writer must never receive a raw dict payload after validation has already produced `validated_payload`.

The writer must continue rejecting raw payloads that do not pass the shared validation gate.

---

## 5. Test Plan

### Unit Tests

Add:

```text
src/pipeline/tests/test_payload_builder.py
src/pipeline/tests/test_record_consistency_validator.py
src/pipeline/tests/test_payload_consistency_validator.py
src/pipeline/tests/test_write_cli.py
src/pipeline/tests/test_embedding_generator.py
src/pipeline/tests/test_graph_quality_report.py
```

Extend:

```text
src/pipeline/tests/test_ontology_consistency.py
tests/test_ontology_consistency.py
tests/test_writer_guard.py
```

Required scenarios:

- `Document` creates derived `Issuer` and `ISSUED_BY`.
- `Document` missing `doc_type`, `number`, `normative`, `legal_status`, `effective_from`, or `issuer_name` fails before write.
- `Document -> Chapter -> Article -> Clause -> Point` produces canonical `CONTAINS`.
- Document without chapters falls back to `Document -> Article`.
- `Chương II` becomes chapter ID suffix `ch2`, not `chII`.
- Parser metadata maps `type -> doc_type`, `status -> legal_status`, and preserves `normative`.
- `--raw-doc-code LDN2020` reads `data/processed/LDN2020` while payload uses `Document.id = ldn_2020`.
- Payload builder reads `entity_index.json` and fails if an accepted relation references a missing semantic entity.
- Semantic IDs prefer the concept/entity normalizer and only fallback to `slug(label)` when no mapping exists.
- `Entity`, `Concept`, and `Action` never appear in final payload.
- `LegalSubject -> LegalConcept` `REQUIRES` passes.
- `Entity -> Entity` `REQUIRES` fails.
- `LegalSubject -> Obligation` fails in Phase 1.
- `REFERS_TO` without `citation_text` or `citation_type` fails.
- Semantic relation without `confidence`, `llm_model`, or `created_at` fails.
- Temporal relation without `effective_from` fails.
- Legacy aliases fail.
- Pipeline and root validator contracts match for relation enum, `GUIDES_WHITELIST`, runtime-only labels, label normalization, legacy aliases, and `REQUIRES` pairs.
- Records cannot enter `accepted.jsonl` without record-level `consistency_valid=true`.
- Payload-level consistency rejects duplicate node IDs, dangling endpoints, duplicate relation identity, invalid structural chain, orphan nodes, and malformed `relation_id`.
- `review.jsonl` records include a standardized `review_reason`.
- Raw writer call raises `WriteAttemptError`.
- `write` CLI uses validated payload objects and guarded writer boundary, not direct Neo4j driver calls.
- Relation writes are idempotent by deterministic relation identity.
- Embedding generator accepts vectors matching configured schema dimension.
- Embedding generator rejects model/config/schema dimension mismatch.
- `embed` verifies required vector indexes exist before updates.
- `graph-quality` writes `data/reports/<raw_doc_code>/graph_quality.json` and optionally `.md`.
- No active code path references `BaseNode` or `entity_vector`.

### Verification Commands

Run from repo root:

```bash
python -m unittest tests/test_ontology_consistency.py tests/test_writer_guard.py
```

Run from `src/pipeline`:

```bash
./.venv/bin/python -m pytest tests/test_ontology_consistency.py tests/test_orchestrator.py tests/test_parser.py tests/test_parser_cli.py
```

After M3 additions, add the new tests to the pipeline pytest command.

---

## 6. Acceptance Criteria

M3 is complete when:

- `crawl -> parse -> extract -> write` can write a document graph to Neo4j using only validated payloads.
- Re-running `write` does not create duplicate nodes or duplicate relations.
- Relations are merge-safe by `(head_id, relation_type, tail_id)` and temporal relations include `effective_from` in identity.
- `embed` fills `Article.embedding` and `Clause.embedding` with configured-dimension vectors.
- `graph-quality` can generate metrics after write/embed.
- `graph-quality` writes reports under `data/reports/<raw_doc_code>/`.
- Payload builder cannot write semantic nodes unless they are present in `entity_index.json`.
- No runtime-only labels are persisted by Phase 1.
- No legacy relation aliases are accepted.
- No prototype schema (`BaseNode`, `entity_vector`) appears in active implementation.
- Invalid graph payloads never reach `MERGE`.
- Docs and CLI agree on implemented behavior.

---

## 7. Implementation Order

1. Clean/quarantine `prototypes/legal_graphrag_legacy`.
2. Align Phase 1 behavior in pipeline and root validators.
3. Add shared contract or parity tests for validator drift.
4. Add record-level consistency validator before decision gate.
5. Add decision-gate output files and `entity_index.json`.
6. Add graph payload builder.
7. Add payload-level consistency validator.
8. Add `write` CLI using guarded writer.
9. Add embedding generator and `embed` CLI.
10. Add graph quality report.
11. Add and run tests.
12. Update `src/pipeline/README.md` and `plans/04_graph_construction_pipeline.md` with exact commands.

---

## 8. Assumptions

- `plans/legal_ontology.md` remains the source of truth.
- Neo4j Community Edition remains bootstrap-only for constraints and indexes.
- Required properties, relation endpoints, and type semantics are enforced in Python before writes.
- `src/pipeline` remains the active graph-construction implementation.
- `prototypes/legal_graphrag_legacy` remains prototype/reference code until explicitly migrated.
- Embedding primary remains BGE-M3/1024; BKAI/768 remains an explicit baseline only.
- Thresholds are provisional until evaluated against manually annotated gold triples.
