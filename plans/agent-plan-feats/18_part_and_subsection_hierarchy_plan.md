# Plan 18 — Part and Subsection Canonical Hierarchy

> Status: IMPLEMENTED — runtime contract complete; live corpus reparse/migration remains an operator action
> Date: 2026-08-01
> Target ontology: v1.8.0
> Proposed ADR: ADR-25
> Depends on: ADR-22 structural reference resolution, ADR-23 Section hierarchy,
> ADR-24 external reference materialization, `plans/legal_ontology.md`, and
> `plans/agent-plan-feats/17_external_structural_reference_materialization_plan.md`

## 1. Goal

Extend the canonical legal hierarchy with the two missing structural levels:

```text
Phần      -> Part
Tiểu mục  -> Subsection
```

The resulting ontology must represent all seven canonical parent chains from a
`Document` to an `Article` that are required by the current layout rules while
preserving the already-supported direct paths:

```text
1. Document -> Part -> Chapter -> Section -> Subsection -> Article
2. Document -> Part -> Chapter -> Section -> Article
3. Document -> Part -> Chapter -> Article
4. Document -> Chapter -> Section -> Subsection -> Article
5. Document -> Chapter -> Section -> Article
6. Document -> Chapter -> Article
7. Document -> Article
```

`Clause` and `Point` remain optional descendants of `Article`:

```text
Article -> Clause     # optional
Clause  -> Point      # optional
```

Therefore, the seven items above are canonical **parent chains to Article**,
not a claim that every Article must contain a Clause or every Clause a Point.

## 2. Legal and Corpus Basis

### 2.1 Historical six-layout evidence

[Article 62 of Decree 34/2016/ND-CP](https://luatvietnam.vn/hanh-chinh/nghi-dinh-34-2016-nd-cp-huong-dan-luat-ban-hanh-van-ban-quy-pham-phap-luat-105351-d1.html)
explicitly listed six layouts:

```text
Part -> Chapter -> Section -> Subsection -> Article -> Clause -> Point
Part -> Chapter -> Section -> Article -> Clause -> Point
Chapter -> Section -> Subsection -> Article -> Clause -> Point
Chapter -> Section -> Article -> Clause -> Point
Chapter -> Article -> Clause -> Point
Article -> Clause -> Point
```

That decree is historical evidence and a high-value parser fixture, not the
current legal authority. Its real content contains headings such as `Mục 3`,
`Tiểu Mục 1`, `Tiểu Mục 2`, and `Điều 77`.

### 2.2 Current authority and the seventh path

[Article 63 of Decree 78/2025/ND-CP](https://xaydungchinhsach.chinhphu.vn/toan-van-nghi-dinh-78-2025-nd-cp-quy-dinh-chi-tiet-mot-so-dieu-luat-ban-hanh-van-ban-quy-pham-phap-luat-119250408202647634.htm)
defines composition rules rather than six closed combinations:

```text
Document -> Part or Chapter or direct Article-level content
Part     -> Chapter
Chapter  -> Section or no Section
Section  -> Subsection or no Subsection
Article  -> Clause or no Clause
Clause   -> Point or no Point
```

Because a `Chapter` under a `Part` may have no `Section`, the current rule also
permits:

```text
Document -> Part -> Chapter -> Article
```

This is the seventh canonical parent chain and is a mandatory acceptance case.

### 2.3 Contract wording

All implementation and report documents must use this wording:

> The ontology supports seven canonical hierarchy paths under the current
> composition rules. Six were explicitly listed by Decree 34/2016/ND-CP; the
> path `Document -> Part -> Chapter -> Article` follows from Article 63 of
> Decree 78/2025/ND-CP, under which a Chapter may have no Section.

Do not describe Decree 34/2016/ND-CP as the current authority and do not say that
the current law is limited to six closed layouts.

## 3. Scope

This plan includes:

- canonical `Part` and `Subsection` nodes;
- deterministic heading parsing and accepted hierarchy output;
- all seven parent chains to `Article`;
- payload building, ontology validation, Neo4j writing, and schema bootstrap;
- corpus structural registry and local/external reference resolution;
- verified `REFERS_TO` targets at `Part` and `Subsection` level;
- hierarchy-aware retrieval ownership queries;
- backend/frontend document browsing for the two new levels;
- idempotent reparse and graph reconciliation;
- documentation, fixtures, and end-to-end test coverage.

## 4. Non-goals

This plan does not:

- add a new relationship type; hierarchy still uses `CONTAINS` and citations
  still use `REFERS_TO`;
- create citation-only or fake `Part`/`Subsection` nodes;
- infer structural existence from a generated canonical ID;
- add embeddings to `Part`, `Chapter`, `Section`, `Subsection`, or `Point`;
- add temporal properties to structural grouping nodes;
- require `document_id` to be denormalized on every structural node;
- use an LLM for explicit numbered structural references;
- interpret vague text such as `các phần khác có liên quan` as a unique target;
- model annex internal headings as `Part` or `Subsection` without separate
  accepted parser evidence.

## 5. Current Repository Findings

### 5.1 Ontology

`src/shared/ontology/contract.py` currently persists:

```text
Document, Issuer, Chapter, Section, Article, Clause, Point,
LegalConcept, LegalSubject, LegalAction
```

`Part` and `Subsection` are absent from:

- `PHASE1_PERSISTED_LABELS`;
- `NODE_REQUIRED_FIELDS`;
- `CONTAINS.valid_pairs`;
- `REFERS_TO.allowed_tail`;
- schema constraints and schema verification expectations.

### 5.2 Parser

`src/pipeline/parser/models.py` has explicit `Section` records, while Article
records carry Chapter/Section context. There is no accepted `Part` or
`Subsection` DTO.

`src/pipeline/parser/hierarchy_parser.py` tracks:

```text
current_chapter -> current_section -> current_article -> current_clause -> current_point
```

It must gain `current_part` and `current_subsection`. The parser module docstring
mentions `Phần`, but runtime patterns and state do not implement it; that prose
must not be treated as capability evidence.

### 5.3 Canonical IDs and depths

`src/shared/ontology/hierarchy.py` only provides Chapter/Section helpers and
currently assumes these bounded depths:

```text
MAX_DOCUMENT_TO_ARTICLE_DEPTH = 3
MAX_DOCUMENT_TO_CITABLE_UNIT_DEPTH = 4
MAX_DOCUMENT_HIERARCHY_DEPTH = 5
```

The deepest accepted path after this migration has seven edges from Document to
Point, so hard-coded `*1..5` ownership queries are no longer sufficient.

### 5.4 Registry and external writer

`src/pipeline/extraction/corpus_structural_registry.py` currently accepts only:

```text
Chapter | Section | Article | Clause | Point
```

The content snapshot contract and external endpoint validator/writer must be
versioned for `Part` and `Subsection`. Existing v1 snapshots remain immutable;
they are not mutated in place.

### 5.5 Document browser

The current browser supports root Chapters, direct Articles, Sections, and
direct Chapter Articles. It lacks DTOs and query projections for Part and
Subsection. This is a display/query gap, not a reason to flatten graph edges.

## 6. Locked Ontology Contract

### 6.1 Node labels and required properties

Add:

```text
Part:
  required: id, number, title

Subsection:
  required: id, number, title
```

`title` is mandatory for both nodes. If a recognized heading has no accepted
title, parsing fails as a data-quality/parser error; the parser must not persist
`Phần I` or `Tiểu mục 1` as a fabricated legal title.

Example nodes:

```json
{
  "label": "Part",
  "id": "nd34_2016_part2",
  "number": "II",
  "title": "THỂ THỨC, KỸ THUẬT TRÌNH BÀY VĂN BẢN"
}
```

```json
{
  "label": "Subsection",
  "id": "nd34_2016_ch5_sec3_subsec1",
  "number": "1",
  "title": "TRÌNH BÀY VĂN BẢN SỬA ĐỔI, BỔ SUNG MỘT SỐ ĐIỀU"
}
```

### 6.2 Canonical `CONTAINS` pairs

The complete structural set becomes:

```text
Document   -> Part
Document   -> Chapter
Document   -> Article
Part       -> Chapter
Chapter    -> Section
Chapter    -> Article
Section    -> Subsection
Section    -> Article
Subsection -> Article
Article    -> Clause
Clause     -> Point
```

Do not add:

```text
Document -> Section
Document -> Subsection
Part -> Section
Part -> Article
Chapter -> Subsection
Subsection -> Clause
```

### 6.3 Canonical parent rules

Every accepted structural node has exactly one direct canonical structural
parent:

```text
Part       <- Document
Chapter    <- Document | Part
Section    <- Chapter
Subsection <- Section
Article    <- Document | Chapter | Section | Subsection
Clause     <- Article
Point      <- Clause
```

Multiple paths to the same owning Document are allowed only when they are the
same canonical parent chain. Multiple direct structural parents are an
integrity failure.

Each grouping parent also has one accepted child mode:

```text
Document -> Part children | Chapter children | Article children
Part     -> Chapter children
Chapter  -> Section children | Article children
Section  -> Subsection children | Article children
```

A single Document, Chapter, or Section must not mix the alternatives shown on
the same line. The ontology permits every relation pair across the corpus, while
the payload validator enforces one composition mode for each concrete parent.

### 6.4 `REFERS_TO`

Keep the canonical direction:

```text
(Article|Clause|Point)-[:REFERS_TO]->(target)
```

Extend the target allowlist to:

```text
Document | Part | Chapter | Section | Subsection | Article | Clause | Point
```

Source labels remain `Article|Clause|Point`. No new relation is introduced.

### 6.5 No embedding or temporal expansion

`Part` and `Subsection` are grouping/navigation/reference endpoints. They do not
receive embeddings or content-level temporal fields in this migration. Temporal
validation continues through their owning `Document` and existing citable
units.

## 7. Parser and DTO Design

### 7.1 Models

Update `src/pipeline/parser/models.py` with:

```python
class Part(BaseModel):
    number: LegalNumber
    title: str
    source_start_char: int
    source_end_char: int

class Subsection(BaseModel):
    number: LegalNumber
    title: str
    chapter: str
    section: str
    source_start_char: int
    source_end_char: int
```

Extend `Article` with nullable structural context:

```python
part: str | None
subsection: str | None
```

Extend `Section` with the owning Part context when its Chapter is inside a Part.
Extend `ParsedDocument` with:

```python
parts: list[Part]
subsections: list[Subsection]
```

The serialized hierarchy contract must receive a new explicit version. Old
payloads without Part/Subsection remain readable only as legacy inputs; they do
not prove that a raw source containing these headings was fully parsed.

### 7.2 Heading grammar

Add full-line, case-insensitive patterns for at least:

```text
PHẦN I
Phần I.
Phần I: Tiêu đề
Phần thứ nhất
Phần thứ nhất. Tiêu đề

TIỂU MỤC 1
Tiểu mục 1.
Tiểu Mục 1: Tiêu đề
Tiểu mục 1a
```

Title extraction order:

```text
inline title
-> next non-empty line within one bounded structural lookahead
-> require formatting/title evidence and maximum canonical length
-> reject when the next line is another structural boundary or body content
```

Do not require all-uppercase text, but uppercase/bold formatting may be evidence.
Do not recognize inline citations such as `theo Tiểu mục 1 Mục 3` as headings.
Existing quote-depth protection must apply to Part and Subsection detection.

### 7.3 Normalization

Add shared helpers in `src/shared/ontology/hierarchy.py`:

```python
normalize_part_number(value)
normalize_subsection_number(value)
part_id(document_id, part_number)
subsection_id(document_id, chapter_number, section_number, subsection_number)
```

Part normalization must equate supported Roman, Arabic, and Vietnamese ordinal
forms when they are legally equivalent, for example `I`, `1`, and `thứ nhất`.
Unknown but syntactically accepted suffixes use deterministic Unicode-aware
slugging. Normalization collisions and duplicate canonical keys hard-fail.

Existing canonical IDs for Document, Chapter, Section, Article, Clause, and
Point must not change. In particular, adding Part ownership must not rename an
already canonical Chapter or Article ID.

### 7.4 State machine

The parser state becomes:

```text
current_part
-> current_chapter
-> current_section
-> current_subsection
-> current_article
-> current_clause
-> current_point
```

Boundary transitions:

- new Part flushes and clears Chapter/Section/Subsection state;
- new Chapter retains current Part and clears Section/Subsection;
- new Section requires current Chapter and clears Subsection;
- new Subsection requires current Section;
- Article chooses the deepest active parent;
- a Chapter inside Part may receive Article directly;
- a root Chapter may receive Article directly;
- an Article may appear directly under Document only when no grouping state is
  active;
- after a parent has accepted one child mode, encountering a conflicting child
  mode for that same parent is a hierarchy-integrity error.

### 7.5 Parser integrity

Hard-fail:

- Part or Subsection missing an accepted title;
- duplicate Part number in a Document;
- duplicate Subsection number in the same Section;
- Subsection without an active Section;
- Section without an active Chapter;
- Article referring to a missing structural record;
- orphan Part/Section/Subsection with no descendant Article;
- the same Chapter assigned to two Parts;
- mixed Part/Chapter/Article child modes in one Document;
- mixed Section/Article child modes in one Chapter;
- mixed Subsection/Article child modes in one Section;
- a structural heading recognized inside quoted amendment text.

## 8. Payload, Validation, and Neo4j Write

### 8.1 Payload builder

Update `src/pipeline/persistence/payload_builder.py` to emit structural nodes and
edges in parent-first order:

```text
Document
-> Part
-> Chapter
-> Section
-> Subsection
-> Article
-> Clause
-> Point
```

The builder must choose exactly one direct parent for every Article using the
deepest accepted context. It must never emit both `Section -> Article` and
`Subsection -> Article` for the same Article.

### 8.2 Shared ontology validation

Update:

- `src/shared/ontology/contract.py`;
- `src/shared/ontology/validators.py` and re-export modules;
- `src/shared/ontology/payload_consistency_validator.py`;
- `src/pipeline/validation/schema_validator.py`;
- extraction label/schema allowlists that enumerate structural labels.

Required checks:

- exact node type and required property validation;
- allowed `CONTAINS` pairs only;
- exact one-parent rule;
- acyclic canonical hierarchy;
- every descendant has one owning Document;
- all relation endpoints exist in the accepted payload;
- type inference checks `Subsection`-specific IDs before `Section`, and `Part`
  before generic structural fallbacks.

### 8.3 Schema bootstrap and verifier

Update:

- `infra/neo4j/init/01_schema_init.cypher`;
- `src/infrastructure/neo4j/schema_verifier.py`;
- `tests/integration/test_neo4j_schema.py`;
- `tests/test_m3_schema_verifier.py`.

Add unique `id` constraints for `Part` and `Subsection`. Neo4j Community schema
bootstrap is not sufficient for required-property/type enforcement; the
application validator must still run before every node or relationship write.

### 8.4 Writer

Update `src/infrastructure/neo4j/writer.py` to accept the two labels without
weakening the existing validated-payload boundary. Node writes remain
idempotent `MERGE` by canonical `id`; canonical `CONTAINS` edges remain
idempotent and are created only between validated existing payload endpoints.

## 9. Registry and Structural Reference Resolution

### 9.1 Registry v2

Introduce `corpus-structural-registry-v2`; do not mutate v1 snapshots.

Extend `RegistryUnit.unit_type` with:

```text
Part | Subsection
```

Add structural indexes:

```text
Part key       = document_id + normalized part number
Subsection key = document_id + chapter + section + normalized subsection number
```

Accepted ancestry must prove:

```text
Part       -> one Document
Subsection -> one Section -> one Chapter -> one Document
```

If the Chapter is inside a Part, that Part must appear in the immutable
`ancestor_ids`. Registry snapshot hashes include the new canonical structural
projection; provenance hashes include the updated parser/hierarchy contracts.

### 9.2 Grammar and AST

Extend deterministic structural candidates for:

```text
Phần này
Phần II của Luật này
Tiểu mục 1 Mục 3 Chương VI
Tiểu mục 1 của Mục 3 Chương VI
Phần II Nghị định 78/2025/NĐ-CP
Tiểu mục 1 Mục 3 Chương VI Nghị định 34/2016/NĐ-CP
```

External expressions must be matched before local expressions so an explicit
document number is never discarded and resolved against the current Document.
`Phần này` resolves through the closest accepted Part ancestor. Explicit local
Subsection resolution must validate both Section and Chapter parents.

### 9.3 Resolution and materialization

Preserve the existing contract:

```text
0 candidate  -> UNRESOLVED
1 candidate  -> RESOLVED
>1 candidate -> AMBIGUOUS
```

The resolver may return `RESOLVED` only from one immutable snapshot record. It
must not use a manifest, inferred ID, or citation-created node as existence
evidence.

Update:

- `src/pipeline/validation/external_reference_validator.py`;
- `src/infrastructure/neo4j/reference_writer.py`;
- `src/pipeline/pipeline/external_reference_reconciliation.py`.

The writer must `MATCH` both endpoints, validate exact labels and canonical
Document ownership through `CONTAINS`, then only `MERGE` `REFERS_TO`. It must
never `MERGE` Part/Subsection endpoint nodes.

## 10. Query Depths and Ownership Semantics

Update shared bounded depths based on semantics, not one global magic number:

```python
MAX_DOCUMENT_TO_ARTICLE_DEPTH = 5
MAX_DOCUMENT_TO_RETRIEVAL_UNIT_DEPTH = 6   # deepest Article/Clause entry
MAX_DOCUMENT_HIERARCHY_DEPTH = 7           # deepest Point ownership
```

If compatibility requires retaining `MAX_DOCUMENT_TO_CITABLE_UNIT_DEPTH`, its
new value must cover the deepest permitted `Point` path, i.e. `7`, and its name
must be documented precisely.

All ownership queries must additionally validate path label sequences. Depth
alone is not evidence of a canonical path. Supported query paths must include
all seven Article parent chains and their optional Clause/Point descendants.

Multiple paths leading to the same Document owner may continue only if they
represent the same direct-parent hierarchy; emit a divergence metric/warning.
Multiple owning Documents hard-fail.

## 11. Retrieval and Document Browser

### 11.1 Retrieval

Update retrieval queries that ascend from Article/Clause/Point to Document.
Vector/full-text entry points remain Article and Clause; Part/Subsection are
reached through graph traversal or verified `REFERS_TO`, not embedding search.

Temporal filtering remains attached to the owning Document and existing
content-level rules. Do not add temporal fields to grouping nodes merely to
simplify a query.

### 11.2 Backend DTOs

Update:

- `src/infrastructure/neo4j/document_browser_repo.py`;
- `apps/backend/services/document_browser_service.py`;
- `apps/backend/api/routes/documents.py`;
- backend document-browser tests and mock data.

Target projection:

```text
DocumentDetail
  parts: list[PartDetail]
  chapters: list[ChapterDetail]          # root Chapters only
  ungrouped_articles: list[ArticleDetail]

PartDetail
  chapters: list[ChapterDetail]

ChapterDetail
  sections: list[SectionDetail]
  ungrouped_articles: list[ArticleDetail]

SectionDetail
  subsections: list[SubsectionDetail]
  ungrouped_articles: list[ArticleDetail]

SubsectionDetail
  articles: list[ArticleDetail]
```

This projection explicitly supports `Part -> Chapter -> Article`: the Chapter
inside a Part can use its existing `ungrouped_articles` field.

### 11.3 Frontend

Update:

- `apps/frontend/src/types/documents.ts`;
- `apps/frontend/src/lib/api/documents.ts`;
- the Document Detail renderer and its tests/fixtures.

Render Part and Subsection as collapsible structural headings. Preserve direct
Articles at Document, Chapter, and Section levels. Deep links and citations
continue to use canonical graph IDs.

## 12. Idempotent Migration and Reconciliation

Existing raw sources may already contain `Phần` and `Tiểu mục`, while processed
hierarchies and Neo4j flattened or omitted them. Therefore this is a reparse
migration, not only an ontology/schema update.

### 12.1 Migration order

```text
1. Approve ADR-25 and bump legal ontology to v1.8.0.
2. Add shared labels, ID helpers, parent rules, and bounded depths.
3. Add parser DTOs/state/patterns and fixture tests.
4. Add payload and root-validation support.
5. Add Neo4j schema constraints and writer support.
6. Add registry v2 and reference resolver/writer support.
7. Add retrieval and document-browser support.
8. Reparse canonical source for every selected document.
9. Validate hierarchy and graph payload from scratch.
10. Write Part/Subsection nodes and new canonical CONTAINS chains.
11. Verify new chains and unique Document ownership.
12. Remove only exact superseded flattened CONTAINS edges.
13. Build a new immutable registry v2 snapshot.
14. Reconcile unresolved/local/external references against that snapshot.
15. Run offline, disposable-Neo4j, retrieval, API, and frontend gates.
16. Update ontology/report/runtime docs together.
```

### 12.2 Safe edge cleanup

Extend `src/infrastructure/neo4j/hierarchy_reconciler.py` with narrow rules:

```text
Document -> Chapter
may be removed only when
Document -> Part -> Chapter exists and is uniquely verified.

Section -> Article
may be removed only when
Section -> Subsection -> Article exists and is uniquely verified.
```

Do not remove:

- `Document -> Article` merely because another part of the same Document uses
  Part/Chapter;
- `Chapter -> Article` in the required seventh path;
- `Chapter -> Article` in the existing root-Chapter path;
- `Section -> Article` for Sections that legitimately have no Subsection;
- any edge when the replacement chain is missing, ambiguous, or invalid.

Each cleanup query must be idempotent, return exact affected counts, and be
covered by rollback/failure tests.

## 13. Implementation Phases and Files

### Phase 0 — Contract and authority

- add ADR-25;
- update `plans/legal_ontology.md` to v1.8.0;
- update Plans 03/04/05 and report wording to distinguish historical six from
  current seven-path support.

### Phase 1 — Shared ontology and identity

- `src/shared/ontology/contract.py`;
- `src/shared/ontology/hierarchy.py`;
- validators and exports;
- ontology/schema parity tests.

### Phase 2 — Parser and accepted hierarchy

- `src/pipeline/parser/models.py`;
- `src/pipeline/parser/patterns.py`;
- `src/pipeline/parser/hierarchy_parser.py`;
- parser CLI serialization and fixtures.

### Phase 3 — Payload and graph persistence

- `src/pipeline/persistence/payload_builder.py`;
- payload/root consistency validators;
- Neo4j schema, verifier, writer, reconciler, and graph-quality report.

### Phase 4 — Registry and references

- `src/pipeline/extraction/corpus_structural_registry.py`;
- `src/pipeline/extraction/structural_references.py`;
- external reference validation, reconciliation, checkpoint compatibility, and
  relation-only writer.

### Phase 5 — Retrieval and browsing

- hierarchy/ownership Cypher queries;
- document browser repository/service/routes;
- frontend DTO/API/renderers and fixtures.

### Phase 6 — Corpus migration and documentation

- reparse selected corpus;
- verify and reconcile graph;
- publish registry v2 snapshot;
- update README, architecture, graph schema report, and runbooks.

## 14. Test Matrix

### 14.1 Seven canonical Article parent chains

Every row must pass parser -> payload -> validator -> writer fixture coverage:

| # | Canonical path | Required evidence |
|---|---|---|
| 1 | D -> Part -> Chapter -> Section -> Subsection -> Article | historical explicit layout |
| 2 | D -> Part -> Chapter -> Section -> Article | historical explicit layout |
| 3 | D -> Part -> Chapter -> Article | current Article 63 inference |
| 4 | D -> Chapter -> Section -> Subsection -> Article | historical explicit layout |
| 5 | D -> Chapter -> Section -> Article | historical explicit layout |
| 6 | D -> Chapter -> Article | historical explicit layout |
| 7 | D -> Article | historical explicit layout |

For representative rows, test Article with and without Clause, and Clause with
and without Point.

### 14.2 Heading parser

- inline and next-line Part title;
- inline and next-line Subsection title;
- case variants and punctuation;
- Roman, Arabic, Vietnamese ordinal Part forms;
- suffix forms such as `Tiểu mục 1a`;
- heading-like citation inside body text is not a boundary;
- heading-like text inside quoted amendment content is not a boundary;
- missing title, duplicate, orphan, and invalid-parent failures;
- real Decree 34 fixture around `Mục 3 -> Tiểu Mục 1 -> Điều 77`.

### 14.3 Payload and ontology

- both new labels require `id`, `number`, and `title`;
- all and only canonical `CONTAINS` pairs pass;
- each Article receives exactly one direct structural parent;
- old payload without Part/Subsection still validates when its raw-source
  contract does not claim those headings;
- a legacy payload cannot be reused as proof for a source digest that changed;
- ID inference identifies Subsection before Section and Part correctly;
- ownership traversal succeeds at depths 1 through 7.

### 14.4 Registry and references

- Part/Subsection enter registry only from accepted structural payloads;
- snapshot v1 remains immutable and v2 hashes are deterministic;
- 0/1/>1 candidate behavior;
- `Phần này` ancestor resolution;
- exact local Part/Subsection resolution;
- external document context takes precedence over local grammar;
- wrong Section/Chapter parent returns unresolved;
- missing target does not create a fake node;
- Neo4j writer matches exact Part/Subsection endpoint labels and ownership.

### 14.5 Migration

- reparse creates missing Part/Subsection nodes;
- repeated migration creates no duplicate nodes or edges;
- `Document -> Chapter` cleanup only after verified Part chain;
- `Section -> Article` cleanup only after verified Subsection chain;
- `Part -> Chapter -> Article` retains `Chapter -> Article`;
- direct Document/Chapter/Section Articles remain intact;
- ambiguous ownership prevents cleanup and materialization.

### 14.6 Retrieval and UI

- ownership lookup for every canonical path;
- retrieval through `REFERS_TO` to Part/Subsection;
- temporal filtering still uses the owning Document;
- API serializes root Chapters and Chapters inside Parts distinctly;
- a Chapter inside Part renders direct Articles without Section;
- Section renders either direct Articles or Subsections according to its accepted child mode;
- old documents without Part/Subsection render unchanged.
- invalid mixed child modes are rejected before the browser projection is
  built; DTO collections support the alternative canonical layouts, not a
  flattened mixed hierarchy.

## 15. Acceptance Criteria

Implementation is complete only when:

1. `Part` and `Subsection` are canonical persisted labels with application-layer
   required-property enforcement and Neo4j ID constraints.
2. All seven parent chains to Article pass deterministic parser, payload,
   validator, and writer tests.
3. `Document -> Part -> Chapter -> Article` has an explicit acceptance fixture.
4. Clause and Point remain optional and their existing canonical IDs/relations
   are backward compatible.
5. Every structural endpoint has exactly one canonical parent and one owning
   Document.
6. Registry v2 proves Part/Subsection existence from accepted hierarchy; no
   manifest or inferred ID is used as existence evidence.
7. Local and external Part/Subsection references resolve with 0/1/>1 semantics
   and materialize only between verified existing endpoints.
8. Reparse/reconciliation is idempotent and never deletes a legitimate direct
   Document, Chapter, or Section Article edge.
9. Retrieval ownership queries support the maximum seven-edge hierarchy and
   validate label/path semantics.
10. Backend and frontend expose Part/Subsection without flattening or losing
    direct Articles.
11. The graph schema report and canonical planning documents state that Decree
    34/2016 provides historical six-layout evidence while Decree 78/2025 is the
    current rule supporting seven canonical Article parent chains.

## 16. Deferred Questions

The following remain out of scope and require separate evidence/ADR work:

- structure inside annexes and attached forms;
- headings below Point or nonstandard list markers;
- ranges such as `từ Tiểu mục 1 đến Tiểu mục 3`;
- semantic references to unnamed Parts/Subsections;
- temporal versioning of structural grouping nodes;
- corpus-specific malformed headings that cannot be resolved by deterministic
  grammar and formatting evidence.

## 17. Implementation Result

Implemented on 2026-08-01 across the canonical runtime contract:

- ontology v1.8 labels, required fields, relation allowlists, IDs, and depths;
- deterministic parser/model support for all seven Article parent chains;
- parent-first payload creation and root hierarchy consistency validation;
- Neo4j uniqueness constraints, schema verification, guarded hierarchy cleanup,
  graph-quality counts, and ownership queries;
- immutable corpus registry v2 with legacy v1 read compatibility;
- local/external Part/Subsection resolution and relation-only external writes;
- retrieval traversal plus backend/frontend document browser projection;
- ADR-25, canonical ontology, active plans, and both schema reports.

Live corpus reparse, registry publication, and Neo4j migration are intentionally
not claimed by this code change. They remain explicit operator actions against
the selected canonical-source corpus and target database.
