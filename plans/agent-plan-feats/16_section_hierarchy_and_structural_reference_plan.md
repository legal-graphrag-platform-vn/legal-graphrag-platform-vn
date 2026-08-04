# Plan 16 — Section Hierarchy and Structural References

> Status: IMPLEMENTED IN CODE; CURATED ARTIFACT REPARSE AND DATABASE MIGRATION PENDING
> Ontology: v1.7.0 / ADR-23
> Scope: canonical pipeline, Neo4j write/retrieval, document browser, tests, and report

## 1. Objective

Complete the structural-reference boundary for local `Chapter`/`Section`
targets while preserving the existing ontology and fail-closed write path:

```text
sanitize canonical source
-> parse Document/Chapter/Section/Article/Clause/Point
-> parse deterministic structural references
-> expand each supported mention to an atomic target
-> resolve against accepted structural registry
-> checkpoint unresolved or unsupported targets
-> validate the complete bundle
-> materialize source -[:REFERS_TO]-> target
-> retrieve with temporal filtering unchanged
```

This migration does not add a relation type, database product, LLM dependency,
temporal model, or embedding target.

## 2. Evidence and Locked Contracts

The raw-corpus discovery probe found:

```text
80 Mục headings
19 documents containing Mục
80/80 headings under an active Chương
80/80 headings with a recoverable legal title
0 Mục outside Chương
```

Therefore the v1.7.0 corpus contract is:

- `Section.title` is required. `"Mục 1"` is display text only, never a stored
  substitute for a missing legal title.
- Canonical hierarchy is `Chapter -> Section -> Article`.
- `Document -> Section` is invalid.
- `Document -> Article` and `Chapter -> Article` remain valid when the source
  has no Section.
- Registry keys are exact local dictionaries. Duplicate Section number within
  one Chapter is a hierarchy-integrity error and must hard-fail.
- Corpus-wide document aliases may be ambiguous; local accepted hierarchy may
  not silently overwrite duplicates.
- `REFERS_TO` sources remain `Article|Clause|Point`; targets are
  `Document|Chapter|Section|Article|Clause|Point`.
- `Section` receives no temporal fields, embedding, full-text index, or vector
  index.

## 3. Data Flow Before and After

Before v1.7.0:

```text
Raw source with Mục
-> parser skips Mục grouping
-> Chapter -> Article
-> resolver supports Article/Clause/Point only
-> browser flattens all Chapter Articles
```

After v1.7.0:

```text
Raw source with Mục
-> strict heading recognition and title evidence
-> ParsedDocument.sections + Article.section
-> Chapter -> Section -> Article payload
-> local Chapter/Section deterministic resolution
-> atomic validation/checkpoint
-> REFERS_TO to verified Chapter/Section
-> browser returns Chapter.articles plus Chapter.sections[].articles
```

## 4. DTO, Schema, and ID Changes

Parser DTOs:

```text
Section:
  required: number, title, chapter
  provenance: source_start_char, source_end_char

Article:
  optional: section

ParsedDocument:
  sections: list[Section] = []
```

Graph node:

```text
(:Section {
  id: "ldn_2020_ch3_sec1",
  number: "1",
  title: "CÔNG TY TRÁCH NHIỆM HỮU HẠN ..."
})
```

ID builders normalize Chapter Roman numerals and Section suffixes centrally:

```text
Chapter.id = {doc}_ch{normalized_chapter}
Section.id = {doc}_ch{normalized_chapter}_sec{normalized_section}
```

Neo4j bootstrap adds only `Section.id` uniqueness. Property existence and
relation endpoint integrity remain application-layer checks before every
`MERGE`.

API DTOs add `SectionDetail`; `ChapterDetail.articles` stays for backward
compatibility and `ChapterDetail.sections` contains nested Section Articles.

## 5. Parser Rules

Supported full-line headings:

```text
Mục 1
MỤC 1
Mục 1.
Mục 1: Quy định chung
Mục 1. Quy định chung
Mục 1a
```

Title acquisition:

1. Use non-empty inline title.
2. Otherwise inspect the next non-empty line.
3. Reject any structural boundary as a title.
4. Require bold formatting evidence or uppercase evidence.
5. Enforce a bounded maximum of 240 canonical characters.
6. Hard-fail missing title, duplicate Section, Section before Chapter, or a
   Section containing no Article.

Because matching is a full-line structural-boundary rule, inline citation text
such as `theo Mục 1 Chương III` cannot become a Section heading.

## 6. Registry and Resolver

Local registry indexes accepted hierarchy only:

```text
chapters[chapter_number] -> chapter_id
sections[(chapter_number, section_number)] -> section_id
article_chapters[article_id] -> chapter_id
article_sections[article_id] -> section_id
```

Resolution is exact:

```text
0 target -> UNRESOLVED
1 target -> RESOLVED
duplicate accepted local key -> hard hierarchy failure
```

Grammar precedence is locked:

```text
external Section + Chapter + document
-> external Chapter + document
-> local Section + Chapter
-> Chương này
-> explicit local Chapter
-> existing Point/Clause/Article grammar
```

Supported local cases:

```text
Chương này
Chương V của Luật này
Mục 1 Chương III
Mục 1 của Chương III
```

External cases such as `Chương V của Nghị định 57/2026/NĐ-CP` and
`Mục 1 Chương III Nghị định 57/2026/NĐ-CP` are stored as structured unresolved
candidates with existing `UNRESOLVED` status and reason codes
`external_chapter_resolution_not_supported` or
`external_section_resolution_not_supported`. No current-document fallback,
fake node, or edge is allowed.

Broad phrases such as `các quy định khác có liên quan` remain source text only
because they do not identify one unique target.

## 7. Validation, Write, and Reconciliation

All new nodes and relations pass the existing root validator and payload
consistency validator. Deterministic references retain resolver/linker
provenance and atomic bundle semantics.

Write order for a reparsed document:

```text
validate complete payload
-> MERGE Chapter/Section/Article and CONTAINS chains
-> verify every exact Chapter->Section->Article chain
-> delete only the corresponding legacy Chapter->Article edge
-> preserve every legacy edge if chain verification is incomplete
```

The reconciliation query is parameterized, accepts only the root
`ValidatedGraphPayload`, and is idempotent. Re-running it after cleanup deletes
zero additional edges.

## 8. Query and Retrieval Changes

Named shared bounds replace scattered hard-coded depth assumptions:

```python
MAX_DOCUMENT_TO_ARTICLE_DEPTH = 3
MAX_DOCUMENT_TO_CITABLE_UNIT_DEPTH = 4
MAX_DOCUMENT_HIERARCHY_DEPTH = 5
```

Repositories still check labels and path meaning. They support all valid paths:

```text
Document -> Article
Document -> Chapter -> Article
Document -> Chapter -> Section -> Article
```

Vector/full-text retrieval continues to rank Article/Clause only. Traversal may
follow verified `REFERS_TO` edges to Chapter/Section, while the existing
temporal validation/filtering remains on Document/Article/Clause.

## 9. Implementation Map

- Ontology and validation: `src/shared/ontology/contract.py`,
  `validators.py`, `payload_consistency_validator.py`, `hierarchy.py`.
- Parser: `src/pipeline/parser/models.py`, `patterns.py`,
  `hierarchy_parser.py`.
- Resolver/checkpoints: `src/pipeline/extraction/structural_context.py`,
  `structural_references.py`, `models.py`, `llm_extractor.py`, `prompts.py`,
  and `src/pipeline/pipeline/orchestrator.py`.
- Payload/write: `src/pipeline/persistence/payload_builder.py`,
  `src/infrastructure/neo4j/writer.py`, `hierarchy_reconciler.py`, and
  `src/pipeline/main.py`.
- Read paths: Neo4j document, embedding, retrieval, and graph-quality
  repositories.
- UI contract: backend API/service plus frontend document DTO and explorer.
- Bootstrap/report: `infra/neo4j/init/01_schema_init.cypher`, schema verifier,
  canonical plan docs, and Neo4j report.

## 10. Migration Order

1. Land ADR-23 and ontology v1.7.0 shared contracts.
2. Apply/restart schema bootstrap and verify `sec_id_unique` exists.
3. Run discovery-only corpus probe; do not write arbitrary raw documents.
4. Reparse only curated, ready canonical sources to regenerate
   `hierarchy.json`, resolver checkpoints, decisions, entity index, and payload.
5. Validate complete payloads before any write.
6. Write new Section nodes and hierarchy edges.
7. Run guarded legacy-edge reconciliation.
8. Re-run payload/write/reconciliation to prove idempotency.
9. Regenerate graph-quality and retrieval evidence before changing milestone
   status.

This code change does not automatically rewrite checked-in processed artifacts
or mutate a live database.

## 11. Test Matrix

- Ontology: Section required fields, valid/invalid `CONTAINS`, polymorphic
  `REFERS_TO`, schema uniqueness.
- Heading parser: case variants, punctuation, inline/next-line titles, suffix
  numbers, long legal titles, citation false positives, missing title,
  duplicate, outside-Chapter, and empty Section.
- DTO compatibility: old hierarchy JSON with no `sections` still validates and
  writes its prior direct parent edge.
- Registry: exact Chapter parent, canonical IDs, duplicate hard-fail, parent
  mismatch unresolved.
- Resolver: `Chương này`, explicit local Chapter, local Section+Chapter,
  external precedence, structured unresolved candidate, broad-text no edge.
- Acceptance: Article 89 resolves Point a/b of Clause 1 Article 88, Chapter IV,
  Section 1 Chapter III, and Chapter V.
- Checkpoint/bundle: unresolved candidate serialized; resolved bundles remain
  atomic and method-aware.
- Payload: exact `Chapter -> Section -> Article` chain and no redundant direct
  edge for a Section Article.
- Reconciliation: delete only after verified chain; missing chain preserves
  legacy edge; rerun is idempotent.
- Query/API/UI: depth constants rendered into Cypher, Section label projection,
  nested API response, direct Chapter Articles backward compatible, frontend
  type/build.

## 12. Deferred from This Plan

- External Chapter/Section materialization across documents. ADR-24 now defines
  the accepted corpus-wide registry and materialization contract, but its code
  remains outside this completed Section/local-reference plan.
- Compound-list expansion such as `điểm d, đ và e khoản 3 Điều 8`.
- Any Section temporal property, embedding, or full-text/vector index.
- `Document -> Section -> Article` unless a later corpus probe and ADR require
  it.
- New relation names such as `EXTERNAL_REFERS_TO`.
