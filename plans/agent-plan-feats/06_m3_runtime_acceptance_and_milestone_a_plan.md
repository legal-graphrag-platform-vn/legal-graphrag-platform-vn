# Detailed Implementation Plan — M3 Runtime Acceptance and Milestone A

> Parent roadmap: `plans/07_implementation_timeline.md` — Phase 1 M3  
> Current canonical ontology: `plans/legal_ontology.md` v1.5.0  
> Pipeline contract: `plans/04_graph_construction_pipeline.md`  
> Dataset contract: `plans/08_dataset_and_scope.md`  
> Embedding contract: BGE-M3/1024 approved by ADR-20
> Status: BLOCKED; must pass before Phase 2 retrieval starts
> Official blocker register: `06_m3_blocker_register.md`

## Current Status — STOP

```text
Phase 1 M3: BLOCKED
Milestone A: NOT PASSED
Phase 2: BLOCKED / prototype only
Canonical graph: STALE
Graph-quality report: STALE
Neo4j evidence: STALE
```

Official open blockers are maintained in `06_m3_blocker_register.md`. Current
summary:

- Gate 2 extraction is blocked by model availability/quota and empty artifacts.
- The current Neo4j graph, embeddings, graph-quality report, and evidence are stale.
- Integration tests, Milestone A evidence, and the four-document corpus remain open.
- Phase 2 remains blocked until every register item is closed.

Existing Phase 2 code may remain as prototype code, but it must not be counted as
active Phase 2 progress or accepted Milestone B work. The current graph, quality
report, and Neo4j results are disposable stale evidence and must not be used for
Milestone A reporting.

Resolution order:

1. Run extraction until accepted semantic relation count is greater than zero.
2. Validate the payload, rebuild Neo4j, and prove write idempotency.
3. Re-embed Article/Clause nodes with BGE-M3/1024 and run top-5 vector smoke checks.
4. Regenerate graph-quality, run disposable-database integration tests, and create
   the tracked Milestone A summary.
5. Complete the four-document minimum corpus, then sign off Milestone A.

---

## 1. Objective

Complete the runtime portion of M3 and prove that the implemented graph-construction
stack works end to end against Neo4j Community Edition:

```text
canonical web metadata + source.txt
  -> hierarchy.json
  -> accepted extraction artifacts
  -> validated graph payload
  -> idempotent Neo4j write
  -> Article/Clause embeddings
  -> vector-search sanity check
  -> graph-quality report
  -> Milestone A evidence
```

This phase is not complete when code exists or unit tests pass. It is complete only
when a real pilot document passes all gates below and the minimum curated corpus can
run without bypassing validation.

---

## 2. Scope Boundary

### In scope

- dependency and environment readiness for `write`, `embed`, and `graph-quality`
- Neo4j schema bootstrap verification
- canonical metadata and ID normalization for the pilot document
- extraction decision artifacts required by the writer
- payload-only validation before database access
- guarded and idempotent Neo4j writes
- configured-dimension Article/Clause embeddings, with BGE-M3/1024 as the default target
- real graph-quality metrics queried from Neo4j
- pilot execution on Luật Doanh nghiệp 2020
- expansion to the four-document minimum demo corpus
- tracked Milestone A evidence summary

### Out of scope

- Phase 2 intent classification
- vector + graph hybrid retrieval implementation
- temporal query answering
- BM25 fusion and reranking
- answer generation, citations, and UI
- fine-tuning extraction or reasoning models
- ingesting all 89 discovery-pool documents
- runtime reasoning nodes: `Obligation`, `Right`, `Condition`, `Exception`

The 89-document crawl pool is an input discovery pool. It must not be treated as
the curated research corpus or bulk-ingested automatically.

---

## 3. Current Baseline

### Implemented

| Area | Current source | State |
|---|---|---|
| CLI | `src/pipeline/main.py` | `parse`, `extract`, `write`, `embed`, `graph-quality` exist |
| Payload builder | `src/pipeline/persistence/payload_builder.py` | Builds structural + accepted semantic payload |
| Ontology contract | `src/shared/ontology/contract.py` | Shared constants source |
| Write validation | `src/shared/ontology/validators.py` | Produces guarded `ValidatedGraphPayload` |
| Payload consistency | `src/shared/ontology/payload_consistency_validator.py` | Checks IDs, endpoints, relation identity |
| Neo4j writer | `src/infrastructure/neo4j/writer.py` | MERGE-safe guarded writer |
| Embedding generator | `src/infrastructure/embedding/embedding_generator.py` | Validates vectors against configured schema dimension |
| Embedding writer | `src/infrastructure/neo4j/embedding_writer.py` | Verifies vector indexes before update |
| Graph quality | `src/pipeline/reports/graph_quality.py` | Reads written graph from Neo4j |
| Schema bootstrap | `infra/neo4j/init/01_schema_init.cypher` | CE constraints and indexes |
| Unit tests | `src/pipeline/tests/` | Current suite passes locally |

### Pilot data observed at plan creation

Filesystem identity:

```text
raw_doc_code = L59_2020
data/raw/L59_2020/
data/processed/L59_2020/
```

Canonical parsed baseline after local raw-source cleanup:

```text
Article = 218
Chapter = 10
Clause = 897
Point = 822
```

Structural graph count contract before semantic extraction:

```text
Document = 1
Issuer = 1
Chapter = 10
Article = 218
Clause = 897
Point = 822
Article + Clause embedding targets = 1,115
```

### Historical blockers at plan creation

This list records the implementation state when the plan was written. Current
gate status must be established by the acceptance commands and tracked Milestone A
evidence, not inferred from this historical list.

1. `data/raw/L59_2020/metadata.json` has `doc_id = L59_2020` but no canonical
   `raw_doc_code` or `graph_id`.
2. `data/processed/L59_2020/hierarchy.json` currently has
   `document.id = L59_2020`; ontology naming requires `ldn_2020`.
3. The pilot processed directory currently has only `hierarchy.json`; writer input
   `accepted.jsonl` and `entity_index.json` do not exist yet.
4. `src/pipeline/requirements.txt` does not declare `neo4j` or
   the selected embedding provider/runtime, although M3 commands require them.
5. Temporal fields are currently passed to Neo4j as ISO strings. Phase 2 query
   templates compare them with Neo4j `Date`, so write-time conversion must be
   defined and tested before Milestone A.
6. Payload builder currently prefixes Issuer IDs as `issuer_<slug>`, while the
   ontology contract defines the ID as the normalized slug itself, for example
   `quoc_hoi`.
7. Graph-quality reporting does not yet expose Article semantic coverage, graph
   density, or average degree required by the roadmap.
8. `infra/README.md` still describes an older Neo4j version and contains stale
   bootstrap wording; `infra/Makefile` schema verification must be checked against
   Neo4j 5.26 syntax.
9. ADR-20, ontology v1.5.0, and tech stack select BGE-M3/1024, while pipeline
   settings and Neo4j schema still bind runtime implementation to BKAI/768.
10. Active CLI commands use `--doc-id` for parse/extract but `--raw-doc-code` for
    later M3 commands, creating ambiguity with canonical `graph_id`.

No write or embedding run may be used as Milestone A evidence until these blockers
are resolved.

---

## 4. Gate 0 — Runtime and Infrastructure Readiness

The embedding decision detailed in section 9 is an execution prerequisite for
this gate. It appears near Gate 5 for readability, but ADR approval, ontology
versioning, and schema dimension migration must be completed before Gate 0 exits
and before the pilot write begins.

### 4.1 Dependency contract

Update active pipeline dependencies so a clean environment can execute every M3
command:

```text
neo4j
torch
FlagEmbedding or sentence-transformers, selected by EMBEDDING_PROVIDER
```

Requirements rules:

- `neo4j` is required by the infrastructure writer and graph-quality command.
- the embedding runtime is selected explicitly by `EMBEDDING_PROVIDER`; BGE-M3
  should use `FlagEmbedding` unless the recorded smoke test proves the
  `sentence-transformers` wrapper has equivalent behavior
- the provider must expose or verify its output dimension before any Neo4j write
- unit tests continue to use fake encoders and must not download model weights
- PDF/OCR packages must not be described as part of the active crawl-to-text path.
  Remove them from active requirements or move them to an explicitly optional
  compatibility group if they are still needed for isolated experiments.
- CI must install the same declared requirements used by local M3 commands.

### 4.2 Environment contract

Runtime secrets remain untracked.

```text
repo-root .env:
  GEMINI_API_KEY
  NEO4J_URI
  NEO4J_USER
  NEO4J_PASSWORD

infra/.env:
  NEO4J_PASSWORD
  NEO4J_HTTP_PORT
  NEO4J_BOLT_PORT
```

The application and container passwords must match. Commands must fail clearly
when a required secret is missing; they must not log secret values.

### 4.3 Neo4j bootstrap

Use Neo4j `5.26.28-community` from `infra/docker-compose.yml`.

```bash
cd infra
make up
make init-schema
make verify-schema
```

Required verification:

- all nine Phase 1 uniqueness constraints exist
- all vector indexes exist and are `ONLINE`
- vector dimensions match configured `EMBEDDING_DIM` with cosine similarity;
  after the approved BGE-M3 migration the expected dimension is 1024
- semantic lookup indexes exist
- all canonical M3 relation types have `relation_id` indexes
- legacy relation aliases have no active schema objects
- bootstrap remains idempotent when `make init-schema` is run twice

Infrastructure cleanup in this gate:

- update `infra/README.md` to the actual Neo4j image version
- describe schema init as idempotent
- point historical ontology references to `plans/archive/`
- make `make verify-schema` use valid Neo4j 5.26 `YIELD -> RETURN -> ORDER BY`
  syntax

### Gate 0 exit criteria

- a fresh environment imports all M3 modules
- Neo4j container is healthy
- schema verification succeeds twice
- both vector indexes are `ONLINE`
- no runtime command fails due to an undeclared dependency
- `EMBEDDING_MODEL`, `EMBEDDING_PROVIDER`, `EMBEDDING_DIM`, ontology, settings,
  and schema bootstrap describe the same embedding contract

---

## 5. Gate 1 — Canonical Data Readiness

### 5.1 Add a curated corpus manifest

Create one tracked manifest, for example:

```text
configs/corpus/curated_v1.json
```

Each document entry must include at least:

```json
{
  "raw_doc_code": "L59_2020",
  "graph_id": "ldn_2020",
  "number": "59/2020/QH14",
  "doc_type": "Law",
  "required": true,
  "gold_annotation": true
}
```

The manifest contains the ten curated documents from
`plans/08_dataset_and_scope.md`. It must report missing crawl inputs instead of
silently substituting discovery-pool documents.

### 5.2 Add a data-readiness validator

Add a deterministic preflight command or service that validates metadata before
parse/extract:

```bash
python -m src.pipeline.main validate-data --raw-doc-code L59_2020
```

Required checks:

- `source.txt` and `metadata.json` exist
- `raw_doc_code` matches the filesystem folder
- `graph_id` is canonical snake-case and differs from raw code where expected
- `doc_type`, `number`, `normative`, `legal_status`, `effective_from`, and
  `issuer_name` can be produced without LLM guessing
- dates use ISO `YYYY-MM-DD`
- document status maps to the ontology enum
- issuer branch can be derived deterministically
- selected document exists in the curated manifest

Metadata normalization must happen in one explicit layer. The writer must not
repair missing metadata.

### 5.3 Standardize CLI filesystem identity

Every command that addresses a runtime document folder must use
`--raw-doc-code`. `graph_id` remains internal canonical metadata and must never be
used to locate `data/raw` or `data/processed`.

Target command surface:

```bash
python -m src.pipeline.main crawl --raw-doc-code L59_2020 ...
python -m src.pipeline.main parse --raw-doc-code L59_2020
python -m src.pipeline.main extract --raw-doc-code L59_2020
python -m src.pipeline.main validate-data --raw-doc-code L59_2020
python -m src.pipeline.main validate-payload --raw-doc-code L59_2020
python -m src.pipeline.main write --raw-doc-code L59_2020
python -m src.pipeline.main embed --raw-doc-code L59_2020
python -m src.pipeline.main graph-quality --raw-doc-code L59_2020
```

Migration rules:

- rename current Python parameters from `doc_id` to `raw_doc_code`
- update CLI help, README, plan examples, and tests in the same change
- do not retain a hidden `--doc-id` compatibility branch after docs and callers
  are migrated
- keep `raw_doc_code = L59_2020` and `graph_id = ldn_2020` assertions in CLI tests

### 5.4 Reparse the pilot

After metadata readiness passes:

```bash
python -m src.pipeline.main parse --raw-doc-code L59_2020
```

Required assertions:

```text
filesystem folder = data/processed/L59_2020
hierarchy.document.id = ldn_2020
hierarchy.document.doc_type = Law
hierarchy.document.normative = true
hierarchy.document.legal_status = valid ontology enum
hierarchy.document.issuer_name = Quốc hội
Article count = 218
```

The raw filesystem key remains `L59_2020`; all graph node IDs use the canonical
`ldn_2020` prefix.

### 5.5 Fix ontology naming before payload output

- `Issuer.id` must be `quoc_hoi`, not `issuer_quoc_hoi`.
- Chapter IDs normalize Roman numerals to Arabic numbers.
- Article, Clause, and Point IDs follow `legal_ontology.md` section 4.
- No `Entity`, `Concept`, or `Action` label may survive into graph payloads.

### Gate 1 exit criteria

- pilot metadata passes readiness validation
- reparsed hierarchy uses `ldn_2020`
- structural counts are recorded and manually spot-checked
- all required ontology properties exist before extraction
- curated manifest clearly separates ten selected documents from the 89-document
  discovery pool

---

## 6. Gate 2 — Extraction and Decision Artifacts

Run extraction only after Gate 1 passes:

```bash
python -m src.pipeline.main extract --raw-doc-code L59_2020
```

Required artifacts:

```text
data/processed/L59_2020/extract.jsonl
data/processed/L59_2020/accepted.jsonl
data/processed/L59_2020/review.jsonl
data/processed/L59_2020/rejected.jsonl
data/processed/L59_2020/entity_index.json
```

Artifact rules:

- every accepted record passed schema, ontology, and record-consistency validation
- every review record has a normalized `review_reason`
- every rejected record has a hard-failure reason
- `extract.jsonl` remains an audit log and is never writer input
- accepted relations use only canonical relation names
- semantic relation properties contain `confidence`, `llm_model`, and `created_at`
- `REFERS_TO` contains `citation_text` and `citation_type`
- temporal relations contain `effective_from`
- entity index resolves every semantic endpoint used by accepted relations
- no runtime-only ontology labels are persisted

Operational safeguards:

- record provider, model, prompt version, run timestamp, and threshold config
- preserve provisional thresholds `0.80/0.55` as configuration, not research
  conclusions
- log extraction duration and API usage for the thesis cost analysis
- do not fabricate accepted relations if the model produces none

### Gate 2 exit criteria

- all five artifacts exist and are parseable
- accepted records are non-empty for the pilot or the run is explicitly blocked
  for extraction-quality investigation
- decision counts reconcile with extraction totals
- zero accepted records contain legacy aliases or unresolved endpoints

---

## 7. Gate 3 — Payload Dry Run

Add a public payload validation command so payload failures are visible before any
database connection:

```bash
python -m src.pipeline.main validate-payload --raw-doc-code L59_2020
```

The command must:

1. read only `hierarchy.json`, `accepted.jsonl`, and `entity_index.json`
2. build the canonical graph payload
3. run payload-consistency validation
4. run write-time ontology validation
5. print a deterministic summary without writing Neo4j

Summary fields:

```text
raw_doc_code
graph_id
node count by label
relation count by type
accepted semantic relation count
embedding target count
duplicate node IDs
duplicate relation identities
dangling endpoints
ontology violations
```

Payload assertions for the pilot:

- `graph_id = ldn_2020`
- one Document and one Issuer
- 218 Article nodes
- deterministic structural counts match the parsed hierarchy
- every relation has a deterministic `relation_id`
- rebuilding the payload produces identical relation IDs
- no dangling endpoint, duplicate identity, legacy alias, or runtime-only label
- temporal fields are valid ISO dates before persistence conversion

### Gate 3 exit criteria

- dry run exits with code 0
- repeated dry runs produce identical summaries and relation identities
- no Neo4j session is created by the dry-run command
- raw or review extraction data cannot enter the payload

---

## 8. Gate 4 — Guarded Neo4j Write

### 8.1 Temporal property serialization

Before the first accepted write, define one infrastructure-level temporal
serialization policy:

```text
Document.effective_from/effective_to -> Neo4j Date
Article.effective_from/effective_to  -> Neo4j Date
Clause.effective_from/effective_to   -> Neo4j Date
AMENDS/REPEALS/REPLACES.effective_from -> Neo4j Date
issued_date -> Neo4j Date when persisted
created_at -> Neo4j DateTime
```

Do not mix ISO strings and Neo4j temporal values. Unit tests must assert the values
received by the driver or the Cypher conversion performed by the writer.

### 8.2 Connection lifecycle

The infrastructure layer must own both Neo4j driver and session lifecycles. CLI
commands must close both on success and failure; callers must not receive a session
whose driver cannot be closed.

### 8.3 Pilot write

```bash
python -m src.pipeline.main write --raw-doc-code L59_2020
```

Run the same command twice against the same database.

Required checks:

```cypher
MATCH (d:Document {id: 'ldn_2020'}) RETURN count(d);
MATCH (a:Article) WHERE a.id STARTS WITH 'ldn_2020_art' RETURN count(a);
MATCH (c:Clause) WHERE c.id STARTS WITH 'ldn_2020_art' RETURN count(c);
MATCH (p:Point) WHERE p.id STARTS WITH 'ldn_2020_art' RETURN count(p);
MATCH ()-[r]->() RETURN type(r), count(r) ORDER BY type(r);
MATCH ()-[r]->() WHERE r.relation_id IS NULL RETURN count(r);
```

Expected pilot baseline:

```text
Document = 1
Article = 218
Clause = 897
Point = 822
Issuer = 1
missing relation_id = 0
```

Chapter and lower-level counts may change only when parser corrections are recorded.
The previous 823-Point observation included a duplicated Point `c` around a VBPL
amendment annotation in Article 215, Clause 4. Canonical local reparse produces 822
Points with no duplicate labels.

Idempotency acceptance:

- node counts are unchanged after the second write
- relation counts are unchanged after the second write
- duplicate node ID count is zero
- duplicate `relation_id` count is zero
- writer rejects raw mappings and accepts only guarded validated payloads

Do not use broad deletion such as `MATCH (n) DETACH DELETE n` in active code. A
full reset is allowed only for an explicitly disposable local database through the
existing destructive infra command and manual confirmation.

### Gate 4 exit criteria

- write succeeds twice with identical graph counts
- canonical IDs and labels are present
- all persisted temporal properties have the agreed Neo4j temporal types
- all relationships have `relation_id`
- database contains no legacy labels or relations

---

## 9. Embedding Contract Decision

The embedding model is schema-bound. ADR-20 and ontology v1.5.0 approve BGE-M3 as
the default target and retain BKAI as the retrieval baseline; runtime implementation
and schema migration must complete before Gate 5.

Default target:

```text
EMBEDDING_MODEL = BAAI/bge-m3
EMBEDDING_PROVIDER = FlagEmbedding
EMBEDDING_DIM = 1024
normalize_embeddings = true
```

Baseline:

```text
EMBEDDING_MODEL = bkai-foundation-models/vietnamese-bi-encoder
EMBEDDING_PROVIDER = sentence-transformers
EMBEDDING_DIM = 768
normalize_embeddings = true
```

Configuration rules:

- `EMBEDDING_MODEL`, `EMBEDDING_PROVIDER`, and `EMBEDDING_DIM` are explicit
  settings, not literals inside generator or writer code.
- Neo4j vector index dimensions must equal `EMBEDDING_DIM`.
- The embed command must fail before updating any node when model output dimension
  differs from `EMBEDDING_DIM`.
- The ontology and schema record the selected concrete dimension. Model-configurable
  does not mean a live Neo4j index can change dimensions dynamically.
- BKAI remains a baseline and can be selected explicitly for ablation; it is not
  the current default.

Approved plan contract and remaining implementation migration:

1. Preserve the ADR/model-selection evidence and add measured runtime/hardware
   details to the tracked experiment report.
2. Update pipeline config defaults, provider implementation, requirements, and
   embedding tests to match ontology v1.5.0.
3. Update `infra/neo4j/init/01_schema_init.cypher` to create both vector indexes at
   1024 dimensions.
4. Add a contract test that compares configured dimension with the concrete
   dimension in schema bootstrap.

Existing-database migration:

```cypher
DROP INDEX article_embedding IF EXISTS;
DROP INDEX clause_embedding IF EXISTS;
```

Then apply the updated schema bootstrap and wait for both recreated indexes to be
`ONLINE`. Changing dimension invalidates all existing Article/Clause embeddings;
the migration must clear or overwrite them and re-embed every target node. Changing
only application config without recreating indexes is forbidden.

Embedding-decision exit criteria:

- ADR and model-selection evidence exist
- ontology version bump is merged
- tech stack, settings, requirements, schema, and tests agree on BGE-M3/1024
- migration is tested on a disposable Neo4j database
- BKAI/768 remains available only as an explicitly selected baseline

---

## 10. Gate 5 — Embedding and Vector Sanity

Use the configured embedding contract.

Default:

```text
model = BAAI/bge-m3
provider = FlagEmbedding
dimension = 1024
normalize_embeddings = true
```

Baseline:

```text
model = bkai-foundation-models/vietnamese-bi-encoder
provider = sentence-transformers
dimension = 768
normalize_embeddings = true
```

Run:

```bash
python -m src.pipeline.main embed --raw-doc-code L59_2020
```

Required checks:

- `article_embedding` and `clause_embedding` are `ONLINE` before writes
- vector index dimensions equal configured `EMBEDDING_DIM`
- only Article and Clause nodes receive embeddings
- Point and semantic nodes do not receive embeddings
- every vector has exactly configured `EMBEDDING_DIM` values
- provider/model output dimension is checked before the first database update
- Clause embedding text includes its parent Article title
- embedding targets stay inside the canonical `ldn_2020_art...` prefix
- the expected target baseline is 1,115 vectors
- rerunning embedding updates properties without creating nodes or relations

Coverage queries:

```cypher
MATCH (a:Article)
WHERE a.id STARTS WITH 'ldn_2020_art'
RETURN count(a) AS total, count(a.embedding) AS embedded;

MATCH (c:Clause)
WHERE c.id STARTS WITH 'ldn_2020_art'
RETURN count(c) AS total, count(c.embedding) AS embedded;
```

Vector sanity check:

1. embed three representative Vietnamese legal queries
2. query both Article and Clause vector indexes
3. record top-5 IDs and scores
4. manually judge whether at least one relevant legal unit appears in top-5

Suggested pilot queries:

```text
quyền thành lập và quản lý doanh nghiệp
vốn điều lệ của công ty trách nhiệm hữu hạn
đăng ký thay đổi nội dung đăng ký doanh nghiệp
```

This is a smoke check, not the Phase 2 retrieval evaluation.

### Gate 5 exit criteria

- Article embedding coverage = 1.0
- Clause embedding coverage = 1.0
- stored vector and index dimensions match the selected embedding contract
- vector index query returns results without dimension/type errors
- top-5 sanity results are stored with the Milestone A evidence

---

## 11. Gate 6 — Complete Graph Quality Reporting

Extend the online reporter to include every M3 roadmap metric.

### Required metric groups

Node and relation counts:

- counts by canonical node label
- counts by canonical relation type
- structural node count
- semantic node count

Integrity:

- ontology violation count and rate on written relations
- duplicate node ID count
- duplicate relation identity count
- dangling endpoint count
- orphan node count inside the written document subgraph
- connected component count

Coverage and topology:

- percentage of Articles with at least one non-`CONTAINS` relation
- Article and Clause embedding coverage
- graph density, with the exact directed/undirected convention documented
- average degree, with the exact convention documented

Extraction decision quality:

- extracted relation total
- accepted/review/rejected counts
- acceptance, review, and rejection rates
- top rejection and review reasons

Database ontology violation rate and extraction rejection rate are different
metrics and must not be merged into one number.

Run:

```bash
python -m src.pipeline.main graph-quality --raw-doc-code L59_2020
```

Outputs:

```text
data/reports/L59_2020/graph_quality.json
data/reports/L59_2020/graph_quality.md
```

Runtime reports remain ignored. Add a sanitized tracked summary for thesis and
Milestone A evidence:

```text
results/milestone_a/L59_2020_summary.md
```

### Gate 6 exit criteria

- both runtime report files exist
- source is explicitly `neo4j`, not local payload inference
- ontology violation count = 0
- duplicate node and relation identity counts = 0
- embedding coverage = 1.0 for Article and Clause
- connected component and orphan metrics include structural, Issuer, and semantic
  nodes in the written subgraph
- all metric formulas are documented and test-covered

---

## 12. Gate 7 — Expand to the Curated Corpus

Do not run all 89 discovery documents. Scale in this order:

```text
1 pilot document
  -> 4-document minimum demo corpus
  -> 10-document curated research corpus
```

The four minimum documents are those selected in
`plans/08_dataset_and_scope.md`. If any raw source is missing, crawl that exact
document and record it as missing readiness work; do not substitute another law.

For each document:

1. validate metadata and manifest entry
2. parse and manually spot-check hierarchy
3. extract and reconcile decision artifacts
4. dry-run payload validation
5. write twice and verify idempotency
6. embed and verify coverage
7. generate graph-quality report

Batch execution may be added only after the pilot passes all gates. Batch mode must
continue processing independent documents while recording per-document failures,
but Milestone A fails if any required document fails.

### Gate 7 exit criteria

- four required documents run end to end without unhandled exceptions
- every required document has a report
- graph contains at least 500 nodes and 300 valid relations
- no required document uses noncanonical IDs
- failures are explicit and reproducible
- curated ten-document status is reported as complete or remaining work; it is not
  required to misrepresent the four-document minimum gate

---

## 13. Milestone A Acceptance Matrix

| ID | Acceptance criterion | Evidence |
|---|---|---|
| A-1 | Pilot has exactly 218 Article nodes | Cypher count + tracked summary |
| A-2 | Canonical structural and semantic relations are written | Relation breakdown |
| A-3 | Second write creates no duplicate node or relation | Before/after count diff |
| A-4 | All relationships have deterministic `relation_id` | Cypher missing-ID count = 0 |
| A-5 | Article and Clause embeddings match configured schema dimension with 100% coverage | Coverage report + vector dimension check |
| A-6 | Both configured-dimension vector indexes are `ONLINE` and top-5 smoke queries return results | Query log |
| A-7 | Written graph has zero ontology violations | Graph-quality report |
| A-8 | Duplicate and dangling integrity metrics are zero | Graph-quality report |
| A-9 | Graph topology and semantic coverage metrics are computed, not placeholders | JSON + Markdown report |
| A-10 | Four minimum documents complete the pipeline | Per-document execution matrix |
| A-11 | Unit tests and M3 integration tests pass | CI/local test output |
| A-12 | No Phase 2 code was required to make M3 pass | Scope review |

Milestone A is all-or-nothing. Do not mark Phase 1 M3 complete when only A-1 or the
unit test suite passes.

---

## 14. Test Plan

### Unit and contract tests

Add or extend tests for:

- default root data paths and module CLI entrypoint
- curated manifest validation
- metadata normalization to canonical graph IDs
- hard failure for missing required metadata
- CLI commands use `--raw-doc-code`; `--doc-id` is not part of the migrated command surface
- `Issuer.id = quoc_hoi`
- temporal value conversion to Neo4j Date/DateTime
- embedding provider selection and output-dimension discovery
- hard failure when model output dimension differs from `EMBEDDING_DIM`
- parity between configured dimension and vector-index bootstrap dimension
- BGE-M3/1024 default and BKAI/768 explicit baseline
- deterministic payload summary
- payload dry run creates no database session
- writer driver/session cleanup on success and exception
- graph-quality coverage, density, average degree, and decision-rate formulas

### Integration tests

Add tests marked separately from the fast suite:

```text
tests/integration/test_neo4j_schema.py
tests/integration/test_neo4j_write_idempotency.py
tests/integration/test_embedding_roundtrip.py
tests/integration/test_graph_quality_online.py
```

Integration tests use a disposable Neo4j Community container and must never point
to a shared or production database.

### Verification commands

```bash
python -m pytest src/pipeline/tests -q
python -m pytest src/pipeline/tests/integration -q -m integration
python -m src.pipeline.main --help
git diff --check
```

---

## 15. Implementation Order

1. Complete the tracked BGE-M3 vs BKAI experiment report referenced by ADR-20.
2. Add missing runtime dependencies and provider-aware BGE-M3/1024 configuration.
3. Fix infra documentation and schema verification syntax.
4. Migrate/recreate vector indexes on a disposable database and verify dimensions.
5. Standardize all document-folder CLI flags to `--raw-doc-code`.
6. Add curated manifest and data-readiness validation.
7. Canonicalize pilot metadata and reparse `L59_2020` to `ldn_2020` graph IDs.
8. Fix Issuer ID convention and add regression coverage.
9. Add temporal property serialization and connection lifecycle ownership.
10. Run extraction and reconcile decision artifacts.
11. Add payload dry-run command and pass it for the pilot.
12. Write the pilot twice and prove idempotency.
13. Generate configured-dimension embeddings and run vector-index smoke queries.
14. Complete graph-quality metrics and write reports.
15. Run the four-document minimum corpus.
16. Produce the tracked Milestone A evidence summary.
17. Update `plans/07_implementation_timeline.md` and `plans/11_project_phases.md`
    only after the acceptance matrix passes.

---

## 16. Stop Conditions

Stop and fix the current gate before continuing when any of these occurs:

- metadata cannot produce canonical required fields deterministically
- hierarchy uses raw filesystem codes as Neo4j IDs
- accepted records contain unresolved endpoints or legacy aliases
- payload validation fails
- writer needs to invent required properties
- temporal values are stored with mixed Neo4j types
- second write changes node or relation counts
- embedding config, ontology, or Neo4j index dimensions disagree
- BGE-M3 is selected without the required ADR and ontology version bump
- vector indexes are missing, offline, or dimension-mismatched
- embedding coverage is below 1.0 without a documented failed node list
- graph-quality reports placeholder constants
- ontology violations or duplicate identities are non-zero
- a discovery-pool document is silently substituted for a curated document

---

## 17. Handoff to Phase 2

Phase 2 may begin only after Milestone A is signed off. Its stable input contract is:

```text
Neo4j graph with canonical IDs and labels
  + valid temporal Date properties
  + canonical active-voice relations
  + Article/Clause embeddings matching configured schema dimension
  + ONLINE vector and full-text indexes
  + measured graph-quality baseline
```

The first Phase 2 plan should then cover only:

```text
2.1 Vector retrieval baseline
2.2 Graph expansion
2.3 Temporal filtering
2.4 BM25/full-text fusion
2.5 Optional reranker
```

Do not combine Phase 2 implementation with unresolved M3 acceptance work.
