# Legal Ontology — Canonical Contract

> **Status**: FROZEN — changes require an ADR and version bump  
> **Version**: 1.5.1
> **Frozen date**: 2026-07-12
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
Document, Issuer, Chapter, Article, Clause, Point
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
| `Document` | `id`, `doc_type`, `number`, `normative`, `legal_status`, `effective_from`, `issuer_name` | `effective_to`, `jurisdiction`, `source_url`, `document_uri`, `gazette_number` | `doc_type`: `Constitution`, `Law`, `Ordinance`, `Resolution`, `Decree`, `Decision`, `Circular`, `JointCircular`; `legal_status`: `ACTIVE`, `NOT_YET_EFFECTIVE`, `PARTIALLY_EFFECTIVE`, `REPLACED`, `REPEALED`, `EXPIRED` |
| `Issuer` | `id`, `name`, `branch` | none | `branch`: `LEGISLATIVE`, `EXECUTIVE`, `JUDICIAL`, `OTHER` |
| `Chapter` | `id`, `number`, `title` | none | none |
| `Article` | `id`, `number`, `content_raw`, `effective_from`, `legal_status` | `title`, `effective_to`, `embedding` | `legal_status`: `ACTIVE`, `AMENDED`, `REPEALED` |
| `Clause` | `id`, `number`, `content_raw`, `effective_from`, `legal_status` | `effective_to`, `embedding` | `legal_status`: `ACTIVE`, `AMENDED`, `REPEALED` |
| `Point` | `id`, `label`, `content_raw` | none | none |

Rules:

| Rule | Contract |
|---|---|
| `Issuer` creation | Writer derives `Issuer` from `Document.issuer_name`; LLM does not extract it directly |
| `Issuer.id` | Slug of normalized issuer name; this is the `MERGE` key, not `name` |
| Temporal denormalization | `Article` and `Clause` carry `effective_from`, `effective_to`, and `legal_status` for retrieval filtering |
| Point temporal scope | Phase 1 does not store temporal fields on `Point`; point-level amendments are normalized to the nearest `Clause` |
| Embeddings | `Article.embedding` and `Clause.embedding` are nullable `float[1024]` under the current BGE-M3 contract; `Point` has no embedding |

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
| `Article` | `Article` |
| `Clause` | `Clause` |
| `Point` | `Point` |

Extraction types are input schema labels, not Neo4j labels. The writer or repository mapping layer must normalize them before persistence.

Phase 1 persistence is limited to `Document`, `Issuer`, `Chapter`, `Article`, `Clause`, `Point`, `LegalConcept`, `LegalSubject`, and `LegalAction`. Runtime reasoning labels (`Obligation`, `Right`, `Condition`, `Exception`) are valid ontology labels, but they must not be persisted by the Phase 1 extraction pipeline.

---

## 3. Relation Contract

Only these relation names are current. Relation names use active voice.

| Relation | From | To | Required properties | Enforced by Neo4j CE | Enforced by Python |
|---|---|---|---|---|---|
| `ISSUED_BY` | `Document` | `Issuer` | none | no | yes |
| `CONTAINS` | `Document`, `Chapter`, `Article`, `Clause` | `Chapter`, `Article`, `Clause`, `Point` by allowed pair | none | no | yes |
| `AMENDS` | `Document`, `Article`, `Clause` | `Document`, `Article`, `Clause` | `effective_from` | indexed only | yes |
| `REPEALS` | `Document` | `Document`, `Article`, `Clause` | `effective_from` | indexed only | yes |
| `REPLACES` | `Document` | `Document` | `effective_from` | indexed only | yes |
| `GUIDES` | `Document` | `Document` | none | no | yes, with whitelist |
| `REFERS_TO` | `Article`, `Clause`, `Point` | `Article`, `Clause`, `Point`, `Document` | `confidence`, `llm_model`, `created_at`, `citation_text`, `citation_type` | no | yes |
| `DEFINES` | `Article`, `Clause` | `LegalConcept` | `confidence`, `llm_model`, `created_at` | no | yes |
| `REGULATES` | `Article`, `Clause` | `LegalSubject`, `LegalAction` | `confidence`, `llm_model`, `created_at` | no | yes |
| `REQUIRES` | `LegalSubject` | `LegalConcept`; `Obligation` only in runtime/future phase | `confidence`, `llm_model`, `created_at` | no | yes |
| `HAS_CONDITION` | `LegalAction`, `Obligation`, `Right` | `Condition` | `confidence`, `llm_model`, `created_at` | no | yes |
| `HAS_EXCEPTION` | `Article`, `Clause`, `LegalAction` | `Exception` | `confidence`, `llm_model`, `created_at` | no | yes |

`REFERS_TO.citation_type` must be one of `DIRECT`, `INDIRECT`, `RANGE`.

Semantic relation provenance is mandatory. The confidence scorer produces `confidence`; the extraction or runtime layer must provide `llm_model` and `created_at` before repository write.

For extracted relations, provenance is immutable evidence from the Article checkpoint:

- `confidence` is the raw extracted relation confidence.
- `llm_model` is `<provider>:<resolved_model>` from the checkpoint, never the model currently configured in the environment.
- `created_at` is the checkpoint `completed_at` normalized to UTC. It records extraction completion time, not legal effective time.
- Missing checkpoint provenance is a hard validation failure. The normalizer must not invent defaults.

`REFERS_TO` preserves distinct citations between the same endpoints. Its stable relation identity discriminator is
`citation_type` plus normalized `citation_text`. Citation normalization uses Unicode NFC, trims leading and trailing
whitespace, and collapses internal whitespace while preserving Vietnamese text. Mutable provenance (`confidence`,
`llm_model`, `created_at`) must not participate in relation identity.

### 3.1 Temporal Relation Direction

Temporal relations always use active voice from the newer legal unit to the older affected legal unit:

```cypher
(new_doc_or_unit)-[:AMENDS {effective_from}]->(old_doc_or_unit)
(new_doc)-[:REPEALS {effective_from}]->(old_doc_or_unit)
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
| `Chapter.id` | `{doc_id}_ch{N}` | `ldn_2020_ch2` |
| `Article.id` | `{doc_id}_art{N}` | `ldn_2020_art17` |
| `Clause.id` | `{doc_id}_art{N}_cl{K}` | `ldn_2020_art17_cl1` |
| `Point.id` | `{doc_id}_art{N}_cl{K}_p{letter}` | `ldn_2020_art17_cl1_pa` |
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
| Vector indexes | `Article.embedding`, `Clause.embedding` with the selected concrete schema dimension; current contract is BGE-M3/1024 |

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

> **Migration status (2026-07-10)**: ADR-20 and ontology v1.5.0 select
> BGE-M3/1024. Existing code or databases still configured for BKAI/768 are in a
> migration state and are not Milestone A compliant. Recreate both vector indexes
> and re-embed Article/Clause before writing BGE-M3 vectors.

| Area | Expected state |
|---|---|
| Structural uniqueness | `Document`, `Issuer`, `Chapter`, `Article`, `Clause`, `Point` by `id` |
| Phase 1 semantic uniqueness | `LegalConcept`, `LegalSubject`, `LegalAction` by `id` |
| Runtime reasoning labels | No bootstrap requirement until persisted by a runtime reasoning component |
| Relation indexes | `AMENDS.effective_from`, `REPEALS.effective_from`, `REPLACES.effective_from` |
| Vector indexes | `article_embedding`, `clause_embedding`, 1024 dimensions, cosine |

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
