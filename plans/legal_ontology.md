# Legal Ontology — Canonical Contract

> **Status**: FROZEN — changes require an ADR and version bump  
> **Version**: 1.14.0
> **Frozen date**: 2026-08-15
> **Scope**: Vietnamese business law, centered on Luật Doanh nghiệp and related normative documents

This file is the only source of truth for graph labels, relation names, required properties, and validation boundaries.

Dependency order:

```text
legal_ontology.md
  -> infra/neo4j/init/01_schema_init.cypher
  -> Pydantic extraction models
  -> prompts
  -> ontology validator
  -> graph consistency validator
  -> confidence scorer
  -> Neo4j repository
  -> Neo4j Python driver
  -> Neo4j
```

`plans/archive/02_ontology_specification_superseded.md` is historical. It must not be used as an implementation reference.

---

## 1. Architecture

### 1.1 Graph Layers

```text
STRUCTURAL LAYER
Document, Issuer, AttachedInstrument, Appendix, Part, Chapter, Section, Subsection, Article, Clause, Point
Relations: ISSUED_BY, CONTAINS, AMENDS, REPEALS, REPLACES, GUIDES, REFERS_TO

SEMANTIC LAYER
LegalConcept, LegalSubject, LegalAction
Relations: DEFINES, REGULATES, REQUIRES

RUNTIME REASONING LAYER
Obligation, Right, Condition, Exception
Relations: HAS_CONDITION, HAS_EXCEPTION
```

The structural layer is persisted first and is stable. The semantic layer is persisted when extraction confidence passes the decision gate. Runtime reasoning labels remain valid ontology labels, but they are not Phase 1 LLM extraction targets.

### 1.2 Validation Stack

```text
LLM
  -> Pydantic
  -> Ontology Validator
  -> Graph Consistency Validator
  -> Confidence Scorer
  -> Neo4j Repository
  -> Neo4j Python Driver
  -> Neo4j
```

Responsibilities:

| Layer | Responsibility |
|---|---|
| LLM | Proposes extraction candidates only |
| Pydantic | Enforces JSON shape, scalar types, ID pattern, and relation enum |
| Ontology Validator | Enforces node required fields, relation type, direction, allowed endpoints, required relation properties |
| Graph Consistency Validator | Enforces cross-record consistency: duplicate IDs, dangling endpoints, cycles, document registry lookup, temporal conflict checks |
| Confidence Scorer | Scores accepted candidates; it does not relax ontology rules |
| Neo4j Repository | Accepts only validated payloads and emits `MERGE` queries |
| Neo4j Python Driver | Transport only |
| Neo4j Community Edition | Stores graph, uniqueness constraints, lookup indexes, full-text indexes, and vector indexes |

---

## 2. Node Contract

Required means mandatory before `Neo4jRepository.merge(...)`. Neo4j Community Edition does not enforce property existence.

### 2.1 Structural Nodes

| Node | Required fields | Optional fields | Enums |
|---|---|---|---|
| `Document` | `id`, `doc_type`, `number`, `normative`, `legal_status`, `effective_from`, `issuer_name` | `title`, `issued_date`, `effective_to`, `expiry_date`, `sector`, `field`, `signer_title`, `signer_name`, `source_url`, `updated_at` | `doc_type`: `Constitution`, `Law`, `Ordinance`, `Resolution`, `Decree`, `Decision`, `Circular`, `JointCircular`; `legal_status`: `ACTIVE`, `NOT_YET_EFFECTIVE`, `PARTIALLY_EFFECTIVE`, `REPLACED`, `REPEALED`, `EXPIRED` |
| `Issuer` | `id`, `name`, `branch` | none | `branch`: `LEGISLATIVE`, `EXECUTIVE`, `JUDICIAL`, `OTHER` |
| `AttachedInstrument` | `id`, `scope`, `heading`, `adoption_text`, `content_raw`, `instrument_kind` | `title`, `updated_at` | `instrument_kind`: `REGULATION`, `CHARTER`, `STANDARD` |
| `Appendix` | `id`, `scope`, `heading`, `content_raw`, `appendix_kind`, `effective_from`, `legal_status` | `number`, `title`, `effective_to`, `updated_at`, `embedding` and embedding provenance | `scope`: normalized owner-local designator; `appendix_kind`: `LEGAL_CONTENT`, `FORM`, `LIST`, `TABLE`, `UNCLASSIFIED`; `legal_status`: `ACTIVE`, `AMENDED`, `REPEALED` |
| `Part` | `id`, `number`, `title` | none | none |
| `Chapter` | `id`, `number`, `title` | none | none |
| `Section` | `id`, `number`, `title` | none | none |
| `Subsection` | `id`, `number`, `title` | none | none |
| `Article` | `id`, `number`, `content_raw`, `effective_from`, `legal_status` | `title`, `effective_to`, `part`, `chapter`, `chapter_title`, `section`, `subsection`, `updated_at`, `embedding` and embedding provenance | `legal_status`: `ACTIVE`, `AMENDED`, `REPEALED` |
| `Clause` | `id`, `number`, `content_raw`, `effective_from`, `legal_status` | `effective_to`, `updated_at`, `embedding` and embedding provenance | `legal_status`: `ACTIVE`, `AMENDED`, `REPEALED` |
| `Point` | `id`, `label`, `content_raw` | `effective_from`, `effective_to`, `legal_status`, `updated_at` | `legal_status`: `ACTIVE`, `AMENDED`, `REPEALED` when present |

Rules:

| Rule | Contract |
|---|---|
| `Issuer` creation | Writer derives `Issuer` from `Document.issuer_name`; LLM does not extract it directly |
| `Issuer.id` | Slug of normalized issuer name; this is the `MERGE` key, not `name` |
| Temporal denormalization | `Appendix`, `Article`, and `Clause` carry `effective_from`, `effective_to`, and `legal_status` for retrieval filtering |
| Point temporal scope | Optional Point temporal fields are schema-reserved only. The current parser/payload builder does not emit them; runtime validity is inherited from the nearest `Clause` until point-level evidence is implemented and evaluated |
| Grouping heading contract | `Part`, `Section`, and `Subsection` are created only from accepted headings in their canonical parent context; `title` is mandatory and is never replaced by a display fallback |
| Grouping-node scope | `Part`, `Chapter`, `Section`, and `Subsection` do not carry temporal fields or embeddings |
| Attached-instrument ownership | An `AttachedInstrument` is created only from a controlled full-line heading (`Quy chế`, `Quy định`, `Điều lệ`, `Chuẩn mực`) followed within three non-empty lines by explicit `ban hành kèm theo` evidence naming a supported host document kind. It has exactly one `Document` parent and at least one parsed Article. Uppercase text alone never opens this scope. |
| Attached-instrument retrieval | `AttachedInstrument` is an ownership node, not a Phase 1 embedding/citation unit. Its Article/Clause descendants carry inherited temporal metadata and provide citable retrieval evidence. |
| Appendix ownership | An `Appendix` is created only from an explicit full-line appendix heading in canonical source. An inline mention such as `theo Phụ lục I` never opens an Appendix. Every Appendix has exactly one `Document` or `AttachedInstrument` parent and owns any structural descendants parsed inside its source span. |
| Appendix content | `content_raw` preserves the complete canonical Appendix body. `Appendix.embedding` is nullable and may be populated only when the Appendix has no citable `Article` descendants; structured descendants are embedded at Article/Clause level to avoid duplicate retrieval evidence. |
| Non-ontology source sections | `TABLE_OF_CONTENTS` and `UNPARSED_BODY` remain parser artifacts with source spans and hashes. They do not create graph nodes, relations, embeddings, or extraction checkpoints. |
| Embeddings | `Appendix.embedding`, `Article.embedding`, and `Clause.embedding` are nullable `float[1024]` under the current BGE-M3 contract; grouping nodes and `Point` have no embedding |

### 2.2 Semantic Nodes

| Node | Required fields | Optional fields | Phase |
|---|---|---|---|
| `LegalConcept` | `id`, `name` | `aliases`, `description` | Phase 1 |
| `LegalSubject` | `id`, `name` | `aliases`, `description` | Phase 1 |
| `LegalAction` | `id`, `name` | `aliases`, `description` | Phase 1 |
| `Obligation` | `id`, `name` | `aliases`, `description` | Runtime reasoning |
| `Right` | `id`, `name` | `aliases`, `description` | Runtime reasoning |
| `Condition` | `id`, `name` | `aliases`, `description` | Runtime reasoning |
| `Exception` | `id`, `name` | `aliases`, `description` | Runtime reasoning |

Extraction mapping:

| Pydantic extraction type | Canonical Neo4j label |
|---|---|
| `Entity` | `LegalSubject` |
| `Concept` | `LegalConcept` |
| `Action` | `LegalAction` |
| `Document` | `Document` |
| `Appendix` | `Appendix` |
| `Part` | `Part` |
| `Article` | `Article` |
| `Section` | `Section` |
| `Subsection` | `Subsection` |
| `Clause` | `Clause` |
| `Point` | `Point` |

Extraction types are input schema labels, not Neo4j labels. The writer or repository mapping layer must normalize them before persistence.

Phase 1 persistence is limited to `Document`, `Issuer`, `AttachedInstrument`, `Appendix`, `Part`, `Chapter`, `Section`, `Subsection`, `Article`, `Clause`, `Point`, `LegalConcept`, `LegalSubject`, and `LegalAction`. Runtime reasoning labels (`Obligation`, `Right`, `Condition`, `Exception`) are valid ontology labels, but they must not be persisted by the Phase 1 extraction pipeline.

---

## 3. Relation Contract

Only these relation names are current. Relation names use active voice.

| Relation | From | To | Required properties | Enforced by Neo4j CE | Enforced by Python |
|---|---|---|---|---|---|
| `ISSUED_BY` | `Document` | `Issuer` | none | no | yes |
| `CONTAINS` | structural parent labels | structural child labels by exact allowed pair | none | no | yes |
| `AMENDS` | `Document`, `Article`, `Clause`, `Point` | `Document`, `Article`, `Clause`, `Point` | `effective_from` | indexed only | yes |
| `REPEALS` | `Document`, `Article`, `Clause`, `Point` | `Document`, `Article`, `Clause`, `Point` | `effective_from` | indexed only | yes |
| `REPLACES` | `Document` | `Document` | `effective_from` | indexed only | yes |
| `GUIDES` | `Document` | `Document` | none | no | yes, with whitelist |
| `REFERS_TO` | `Appendix`, `Article`, `Clause`, `Point` | `Document`, `Appendix`, `Part`, `Chapter`, `Section`, `Subsection`, `Article`, `Clause`, `Point` | common citation/bundle provenance plus method-specific provenance | no | yes |
| `DEFINES` | `Article`, `Clause` | `LegalConcept` | `confidence`, `llm_model`, `created_at` | no | yes |
| `REGULATES` | `Article`, `Clause` | `LegalSubject`, `LegalAction` | `confidence`, `llm_model`, `created_at` | no | yes |
| `REQUIRES` | `LegalSubject` | `LegalConcept`; `Obligation` only in runtime/future phase | `confidence`, `llm_model`, `created_at` | no | yes |
| `HAS_CONDITION` | `LegalAction`, `Obligation`, `Right` | `Condition` | `confidence`, `llm_model`, `created_at` | no | yes |
| `HAS_EXCEPTION` | `Article`, `Clause`, `LegalAction` | `Exception` | `confidence`, `llm_model`, `created_at` | no | yes |

The exact Phase 1 `CONTAINS` pairs are:

```text
Document   -> Part
Document   -> Chapter
Document   -> Section
Document   -> Article
Document   -> Appendix
Document   -> AttachedInstrument
AttachedInstrument -> Appendix
AttachedInstrument -> Part
AttachedInstrument -> Chapter
AttachedInstrument -> Section
AttachedInstrument -> Article
Appendix   -> Part
Appendix   -> Chapter
Appendix   -> Section
Appendix   -> Article
Part       -> Chapter
Part       -> Section
Part       -> Article
Chapter    -> Section
Chapter    -> Article
Section    -> Subsection
Section    -> Article
Subsection -> Article
Article    -> Clause
Clause     -> Point
```

These pairs produce the canonical parent chains observed in the corpus: with or
without `Appendix`, `Part`, or `Chapter`, and with direct Section Articles or
`Subsection` descendants.
`Document -> Article` remains valid. Corpus-evidenced direct Section parents are
`Document -> Section` and `Part -> Section`; `Part -> Article` is also valid when
a Part contains Articles without an intermediate Chapter. `Chapter -> Subsection`
and `Document -> Subsection` remain invalid shortcuts. Every structural descendant
has exactly one direct canonical parent. Packaging documents may mix direct
`Article` children with `Part`, `Chapter`, or `Section` children, and a `Part` may
mix direct Articles with its grouping children. A `Chapter` may mix direct `Article` children with
`Section` children only for preamble Articles: every direct Article number must
sort before every Article number contained by the Chapter's Sections. A direct
Article at or after the first Section Article is invalid.

An `AttachedInstrument` owns the independent internal hierarchy of a regulation,
charter, or standard explicitly promulgated with the host Document. Descendant
identities are prefixed by its ID so restarted Article numbering cannot collide
with the host Document. It may also own an explicit Appendix.

An `Appendix` is a legal source unit, not a navigation artifact. It may directly
contain `Part`, `Chapter`, `Section`, or `Article` according to its own canonical
source structure. Descendant identities are scoped by the Appendix ID so an
`Article 1` in an Appendix cannot collide with `Article 1` in the host Document.
`TABLE_OF_CONTENTS` is explicitly excluded from the graph even when it repeats
valid Article or Chapter headings.

`REFERS_TO.citation_type` must be one of `DIRECT`, `INDIRECT`, `RANGE`.

`REFERS_TO` provenance is method-aware. Common required properties are `citation_text`, `citation_type`,
`extraction_method`, `created_at`, `reference_bundle_id`, and `reference_target_count`. The reference extraction-method
enum is `RULE`, `ENTITY_LINKING`, or `LLM`; `DIAGRAM` and `HYBRID` are not valid `REFERS_TO` methods.

Method-specific requirements:

- `RULE`: `resolver_name`, `resolver_version`, `source_unit_id`, `source_char_start`, `source_char_end`.
- `ENTITY_LINKING`: `linker_name`, `linker_version`, and `source_unit_id`.
  A host-owned citation additionally requires `source_char_start` and
  `source_char_end`. A projected citation instead requires
  `source_ownership=PROJECTED`, `host_evidence_document_id`,
  `host_evidence_source_unit_id`, `host_evidence_char_start`,
  `host_evidence_char_end`, and `projection_basis_candidate_id`.
- `LLM`: `confidence`, `llm_model`, and `checkpoint_id`.

`DIAGRAM` is the sole member of the separate document-relation extraction-method
enum. It is a deterministic source derived from an explicit
source-site category-to-relation map. It may materialize only canonical
`AMENDS`, `REPEALS`, `REPLACES`, or `GUIDES` relations after registry-backed
Document resolution. It carries `resolver_name`, `resolver_version`,
`source_category`, `source_text`, and `created_at`; temporal relations still
require `effective_from`, and `GUIDES` still requires the document-type
whitelist. A diagram builder produces validation-pending records; schema,
ontology, and consistency validation must run before the decision gate. When
the acting head Document is external and its effective date is unavailable,
the candidate goes to blocking review and cannot be materialized. Diagram
confidence never bypasses ontology or consistency validation.

Deterministic and entity-linked bundles bypass confidence scoring only. They still require schema, ontology,
endpoint, atomic-bundle, and payload consistency validation. A multi-target reference is accepted as a whole or
not accepted at all.

For projected provider relations, `source_unit_id` is always the canonical legal
source in the amended document. Host coordinates prove where the provider exposed
the evidence and never replace that legal identity. The same contract applies
whether source and target belong to the same Document or different Documents.
Projected `AMENDS` and `REPEALS` require the same host-evidence and projection-basis
properties even though their legal provenance remains `PROVIDER_HTML` rather than
`ENTITY_LINKING`.

Other semantic relation provenance is mandatory. The confidence scorer produces `confidence`; the extraction or runtime layer must provide `llm_model` and `created_at` before repository write.

For extracted relations, provenance is immutable evidence from the Article checkpoint:

- `confidence` is the raw extracted relation confidence.
- `llm_model` is `<provider>:<resolved_model>` from the checkpoint, never the model currently configured in the environment.
- `created_at` is the checkpoint `completed_at` normalized to UTC. It records extraction completion time, not legal effective time.
- Missing checkpoint provenance is a hard validation failure. The normalizer must not invent defaults.

For deterministic references, `created_at` comes from a resolver checkpoint and is reused while the mention
fingerprint and resolver version remain unchanged. Rule provenance must not be represented by a fake LLM model
or artificial confidence score.

`REFERS_TO` preserves distinct citations between the same endpoints. Its stable relation identity discriminator is
`citation_type` plus normalized `citation_text`. Citation normalization uses Unicode NFC, trims leading and trailing
whitespace, and collapses internal whitespace while preserving Vietnamese text. Mutable provenance (`confidence`,
`llm_model`, `created_at`, resolver/linker versions, and extraction method) must not participate in relation
identity. Retrieval path topology collapses parallel citations by source, relation type, and target while citation
presentation preserves every distinct relation identity.

### 3.1 Temporal Relation Direction

Temporal relations always use active voice from the newer legal unit to the older affected legal unit:

```cypher
(new_doc_or_unit)-[:AMENDS {effective_from}]->(old_doc_or_unit)
(new_doc_or_unit)-[:REPEALS {effective_from}]->(old_doc_or_unit)
(new_doc)-[:REPLACES {effective_from}]->(old_doc)
```

To find newer changes that affect an existing node:

```cypher
MATCH (newer)-[:AMENDS|REPEALS|REPLACES]->(old {id: $id})
RETURN newer
```

To find what a new amending document changed:

```cypher
MATCH (newer {id: $id})-[:AMENDS|REPEALS|REPLACES]->(old)
RETURN old
```

### 3.2 `GUIDES` Whitelist

`GUIDES` uses a whitelist instead of a numeric `level` property. `level` must not be stored in Neo4j.

`GUIDES_WHITELIST` is an operational whitelist for this project scope, not a complete legal hierarchy model for all Vietnamese normative documents. It covers the document type pairs observed or expected in the selected corpus.

```python
GUIDES_WHITELIST = {
    ("Constitution", "Law"),
    ("Constitution", "Ordinance"),
    ("Law", "Decree"),
    ("Law", "Decision"),
    ("Law", "Circular"),
    ("Ordinance", "Decree"),
    ("Resolution", "Decree"),
    ("Decree", "Circular"),
    ("Decree", "Decision"),
    ("Decree", "JointCircular"),
    ("Decision", "Circular"),
}
```

### 3.3 Legacy Relation Aliases

These names may appear in archived data, old docs, or generated samples only. They are not accepted by current validators.

| Legacy alias | Canonical relation |
|---|---|
| `AMENDED_BY` | `AMENDS` |
| `REPEALED_BY` | `REPEALS` |
| `REPLACED_BY` | `REPLACES` |
| `IMPLEMENTED_BY` | `GUIDES` |
| `GUIDED_BY` | `GUIDES` |
| `REFERENCES` | `REFERS_TO` |

Any current pipeline, test, prompt, or repository code that emits a legacy alias is non-compliant.

---

## 4. Naming

| Element | Convention | Example |
|---|---|---|
| `Document.id` | snake-case slug | `ldn_2020` |
| `AttachedInstrument.id` | `{doc_id}_inst{kind}_{source_order}` | `nd39_1995_instcharter_1` |
| Attached-instrument descendant | Prefix the ordinary structural suffix with `{attached_instrument_id}` | `nd39_1995_instcharter_1_art1` |
| `Appendix.id` | `{doc_id}_app{normalized_designator}`; an unnumbered Appendix uses `{doc_id}_appx{source_order}` | `tt38_2014_app01_tdg`, `qd113_2008_appx1` |
| Appendix descendant | Prefix the ordinary structural suffix with `{appendix_id}` | `tt38_2014_app01_tdg_art1`, `tt38_2014_app01_tdg_art1_cl1` |
| `Part.id` | `{owner_id}_part{normalized_part}`, where owner is Document, AttachedInstrument, or Appendix | `nd34_2016_part2`, `qd113_2008_appx1_part2` |
| `Chapter.id` | `{owner_id}_ch{N}`, where owner is Document, AttachedInstrument, or Appendix | `ldn_2020_ch2`, `qd113_2008_appx1_ch2` |
| `Section.id` | `{owner_id}_ch{N}_sec{M}` when under Chapter; `{owner_id}_sec{M}` when no Chapter exists | `ldn_2020_ch3_sec1`, `tt38_2014_app01_tdg_sec1` |
| `Subsection.id` | `{section_id}_subsec{K}` | `ttlt178_2015_sec1_subsec1`, `nd34_2016_ch5_sec3_subsec1` |
| `Article.id` | `{owner_id}_art{N}`, where owner is Document, AttachedInstrument, or Appendix | `ldn_2020_art17`, `tt38_2014_app01_tdg_art1` |
| `Clause.id` | `{article_id}_cl{K}` | `ldn_2020_art17_cl1`, `tt38_2014_app01_tdg_art1_cl1` |
| `Point.id` | `{clause_id}_p{letter}` | `ldn_2020_art17_cl1_pa` |
| Semantic node ID | snake-case, no Vietnamese diacritics | `von_dieu_le` |
| `Issuer.id` | snake-case slug | `quoc_hoi` |
| Relation | `SCREAMING_SNAKE_CASE`, active voice | `AMENDS`, `REFERS_TO` |

---

## 5. Enforcement Model

### 5.1 Neo4j Community Edition

The bootstrap script must create only:

| Category | Allowed in bootstrap |
|---|---|
| Uniqueness constraints | `id` uniqueness for persisted labels |
| Lookup indexes | frequently filtered scalar properties |
| Temporal indexes | `effective_from`, `effective_to` filters |
| Relationship property indexes | `AMENDS`, `REPEALS`, `REPLACES` temporal lookup |
| Full-text indexes | `content_raw`, `title` search |
| Vector indexes | `Appendix.embedding`, `Article.embedding`, `Clause.embedding` with the selected concrete schema dimension; current contract is BGE-M3/1024 |

The database bootstrap must not be treated as a full ontology validator in Community Edition.

### 5.2 Python Application Layer

Python must validate before any `MERGE`:

| Validation | Owner |
|---|---|
| Required node properties | Ontology Validator |
| Node enum values | Ontology Validator |
| Relation enum | Pydantic and Ontology Validator |
| Relation endpoint types | Ontology Validator |
| Relation required properties | Ontology Validator |
| Duplicate IDs and dangling endpoints | Graph Consistency Validator |
| No self-loop where forbidden | Ontology Validator |
| No `AMENDS` cycle | Graph Consistency Validator |
| `GUIDES` whitelist | Ontology Validator |
| Temporal conflict checks | Graph Consistency Validator |

### 5.3 Future Enterprise Edition

If the project moves to Neo4j Enterprise Edition, property existence and type constraints may be added as defense in depth. That change is additive and must not replace application-layer validation.

---

## 6. Bootstrap Compatibility Notes

`infra/neo4j/init/01_schema_init.cypher` must match this contract:

> **Runtime status (2026-07-17)**: the signed-off pilot schema, indexes, and
> Appendix/Article/Clause embeddings use BGE-M3/1024. Any stale or external database still
> configured for BKAI/768 remains incompatible with this contract and must recreate
> all three vector indexes and re-embed eligible Appendix/Article/Clause nodes before use.

| Area | Expected state |
|---|---|
| Structural uniqueness | `Document`, `Issuer`, `AttachedInstrument`, `Appendix`, `Part`, `Chapter`, `Section`, `Subsection`, `Article`, `Clause`, `Point` by `id` |
| Phase 1 semantic uniqueness | `LegalConcept`, `LegalSubject`, `LegalAction` by `id` |
| Runtime reasoning labels | No bootstrap requirement until persisted by a runtime reasoning component |
| Relation indexes | `AMENDS.effective_from`, `REPEALS.effective_from`, `REPLACES.effective_from` |
| Vector indexes | `appendix_embedding`, `article_embedding`, `clause_embedding`, 1024 dimensions, cosine |

---

## 7. Ontology Principles

1. Node labels represent legal concepts or legal text units, not implementation artifacts.
2. Relationship types represent legal semantics with explicit direction.
3. Extraction schema labels are allowed at the Pydantic boundary only; Neo4j labels are canonical labels.
4. Validator logic such as `GUIDES_WHITELIST` is application behavior, not persisted graph metadata.
5. Denormalized temporal fields exist for retrieval performance and must remain consistent with temporal relations.
6. Every persisted semantic edge carries provenance.
7. The ontology contract leads implementation; bootstrap scripts and validators follow it.
8. Embedding model output dimension, application configuration, and Neo4j vector index dimension must match before embedding writes.

---

## 8. Change Log

| Version | Date | Change | Reason |
|---|---|---|---|
| 1.0.0 | 2026-07-03 | Initial frozen schema | Ontology design baseline |
| 1.1.0 | 2026-07-03 | Added `issuer_name`, `GUIDES` whitelist, `Action` extraction type, active-voice relation direction | Reviewer feedback |
| 1.2.0 | 2026-07-06 | Added nullable `embedding: float[768]` to `Article` and `Clause`; clarified `Point` has no embedding | Retrieval schema alignment |
| 1.3.0 | 2026-07-07 | Aligned with Neo4j Community Edition integrity strategy and denormalized temporal fields | Write-path implementation |
| 1.4.0 | 2026-07-07 | Rewrote as canonical contract; added validation stack, relation matrix, enforcement boundaries, and legacy alias quarantine | Remove ambiguity between frozen spec, schema bootstrap, and validators |
| 1.5.0 | 2026-07-10 | Selected BGE-M3/1024 as the primary embedding contract; retained BKAI/768 as an explicit baseline | Model-selection smoke test and ADR-20 |
| 1.5.1 | 2026-07-12 | Made `REFERS_TO` provenance mandatory and defined citation-based deterministic identity | ADR-21 and Gate 4 evidence review |
| 1.6.0 | 2026-07-18 | Added resolver-first structural references, atomic bundles, and method-aware `REFERS_TO` provenance | ADR-22 |
| 1.7.0 | 2026-07-31 | Added corpus-verified `Section` hierarchy, Chapter/Section reference targets, and guarded hierarchy migration | ADR-23 |
| 1.8.0 | 2026-08-01 | Added canonical `Part` and `Subsection`, seven Article parent chains, registry v2, and verified reference/browser support | ADR-25 |
| 1.8.1 | 2026-08-08 | Allowed direct preamble Articles before Section Articles within the same Chapter while retaining ordered mixed-mode validation | ADR-28 and BLHS 2015 Chapter XXIII |
| 1.9.0 | 2026-08-10 | Synchronized executable metadata fields, reserved optional Point temporal fields, and fail-closed deterministic diagram relation provenance | ADR-29 |
| 1.10.0 | 2026-08-12 | Extended `AMENDS` and `REPEALS` to the smallest evidenced structural unit, including `Point`; unresolved provider endpoints remain outside graph persistence | ADR-32 |
| 1.11.0 | 2026-08-15 | Added corpus-evidenced `Document -> Section`, `Part -> Section`, `Part -> Article`, and packaging-document mixed root structure | ADR-33 |
| 1.12.0 | 2026-08-15 | Added dual provenance for projected provider relations and atomic multi-target reconciliation | ADR-34 |
| 1.13.0 | 2026-08-15 | Added citable `Appendix` ownership, Appendix-scoped structural identity, and explicit exclusion of table-of-contents artifacts | ADR-35 |
| 1.14.0 | 2026-08-15 | Added evidenced `AttachedInstrument` ownership for regulations, charters, and standards promulgated with a host Document | ADR-36 |
