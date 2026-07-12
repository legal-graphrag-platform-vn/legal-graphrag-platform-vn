# M3 Gate 4 to Milestone A Execution Plan

> Status: Gate 4 tooling implemented; disposable runtime execution pending
> Created: 2026-07-12
> Pilot: `L59_2020`
> Graph ID: `ldn_2020`
> Parent: `06_m3_runtime_acceptance_and_milestone_a_plan.md`
> Blocker authority: `06_m3_blocker_register.md`

## 1. Objective

Complete the runtime part of M3 without touching the current development Neo4j
database until the pilot has passed every disposable-database gate.

Execution path:

```text
validated canonical payload
-> dedicated disposable Neo4j
-> schema verification
-> guarded write twice
-> idempotency and temporal verification
-> Neo4j integration tests
-> BGE-M3 embeddings
-> vector smoke queries
-> online graph-quality report
-> tracked Milestone A evidence
-> four-document minimum corpus
-> Milestone A sign-off
```

This plan does not start Phase 2 and does not promote prototype retrieval code.

---

## 2. Verified Starting State

### 2.1 Gate 2 extraction baseline (ontology v1.5.1)

```text
provider configured = gemini-flash-lite-latest
provider resolved model = gemini-3.1-flash-lite
Article checkpoints = 218 unique rows
extracted = 1743
accepted = 775
review = 434
rejected = 534
accepted LLM CONTAINS = 0
accepted unresolved endpoints = 0
accepted structural aliases = 0
semantic type conflicts = 35 IDs / 218 relations moved to review
accepted REFERS_TO = 67
REFERS_TO missing provenance = 0
artifact publication = atomic active-set pointer
provider called during v1.5.1 regeneration = false
two-run decision/entity-index hashes = identical
```

### 2.2 Gate 3 canonical payload baseline

Node counts:

| Label | Expected |
|---|---:|
| Document | 1 |
| Issuer | 1 |
| Chapter | 10 |
| Article | 218 |
| Clause | 897 |
| Point | 822 |
| LegalAction | 209 |
| LegalConcept | 102 |
| LegalSubject | 73 |
| Total | 2,333 |

Relation counts:

| Relation | Expected |
|---|---:|
| ISSUED_BY | 1 |
| CONTAINS | 1,947 |
| DEFINES | 120 |
| REGULATES | 535 |
| REQUIRES | 53 |
| REFERS_TO | 67 |
| Total | 2,723 |

Integrity baseline:

```text
duplicate node IDs = 0
duplicate relation identities = 0
dangling endpoints = 0
ontology violations = 0
embedding targets = 1115 (218 Article + 897 Clause)
```

### 2.3 Test baseline

```text
fast tests = 174 passed
Neo4j integration tests = 4 deselected
targeted Ruff = passed
targeted git diff check = passed
```

The next open blocker is `M3-B06`: stale/unverified Neo4j runtime state.

---

## 3. Safety Decision: Dedicated Disposable Database

### 3.1 Selected approach

Do not run `make clean` against the current `graphrag-neo4j` instance.

Create a dedicated M3 runtime:

```text
container = graphrag-neo4j-m3
HTTP = localhost:7475
Bolt = localhost:7688
database = neo4j
storage = Docker named volume `graphrag-neo4j-m3-data`
```

All M3 write, embedding, graph-quality, and integration commands must explicitly
use:

```text
NEO4J_URI=bolt://localhost:7688
```

The existing development endpoint `bolt://localhost:7687` is out of scope for
this execution.

### 3.2 Required guardrails

- M3 destructive commands require the literal confirmation token
  `CONFIRM_M3_RESET=YES`.
- Reset command verifies the Compose service identity, target container name
  `graphrag-neo4j-m3`, and named volume `graphrag-neo4j-m3-data`.
- Reset command rejects Bolt port `7687`.
- Integration tests reject `NEO4J_URI=bolt://localhost:7687`.
- Integration tests require `RUN_NEO4J_INTEGRATION=1`.
- No active application module contains `MATCH (n) DETACH DELETE n`.
- Test cleanup is scoped to a unique `test_<uuid>_` prefix generated per test.
- Runtime evidence records URI, container name, image version, and git commit,
  but never records passwords.

The guard is split into three responsibilities:

```python
validate_disposable_uri(uri)
require_integration_opt_in(environment)
verify_m3_container_identity(container_name, host_ports, image, volume)
```

`validate_disposable_uri` is pure and accepts only explicit localhost or
`127.0.0.1` with Bolt port 7688. It rejects missing ports, port 7687, remote
hosts, query-string routing, and credential-bearing URIs.

`require_integration_opt_in` requires `RUN_NEO4J_INTEGRATION=1` for integration tests.
Destructive reset uses a separate authorization contract and requires both
`RUN_M3_DESTRUCTIVE=1` and `CONFIRM_M3_RESET=YES`.

`verify_m3_container_identity` uses Docker inspect and verifies:

```text
container name = graphrag-neo4j-m3
image = neo4j:5.26.28-community
published HTTP port = 7475
published Bolt port = 7688
mounted volume = graphrag-neo4j-m3-data -> /data
```

URI validation never claims to infer Docker/container identity.

### 3.3 New infra commands

Add dedicated Make targets under `infra/Makefile`:

```text
m3-up
m3-status
m3-init-schema
m3-verify-schema
m3-reset
m3-down
m3-logs
```

Required behavior:

| Command | Behavior |
|---|---|
| `m3-up` | Start only `graphrag-neo4j-m3`, wait until healthy |
| `m3-status` | Print container state and health |
| `m3-init-schema` | Apply canonical bootstrap to disposable DB |
| `m3-verify-schema` | Print constraints/index names, states, vector options |
| `m3-reset` | Refuse unless confirmation token and disposable identity match |
| `m3-down` | Stop container without deleting data |
| `m3-logs` | Stream only M3 container logs |

`m3-reset` is Compose-service based and works when the container is running,
stopped, or absent. Its fixed order is:

```text
validate opt-in and confirmation token
validate Compose service/container/volume names from frozen config
if container exists, inspect runtime identity and reject any mismatch
docker compose -f docker-compose.m3.yml down
remove only named volume graphrag-neo4j-m3-data
verify development container/volume were not targeted
exit without automatically starting a new container
```

The caller then runs `m3-up`. `m3-reset` never depends on first starting the
container.

### 3.4 Stop conditions

Stop before any write if:

```text
the target URI is 7687
the target container identity cannot be verified
the M3 container is not healthy
schema bootstrap fails
any required index is missing or not ONLINE
vector dimensions are not 1024
vector similarity is not cosine
payload dry-run no longer matches Gate 3 baseline
```

---

## 4. Pre-Gate Implementation Hardening

These changes must be implemented and tested before starting the disposable DB.

### 4.1 Runtime target guard

Add the three separate guards defined in section 3.2. Pure URI validation lives
in application/infrastructure Python; Docker identity verification lives in the
infra command layer and may invoke `docker inspect`.

It must reject:

```text
bolt://localhost:7687
non-local hostnames
missing explicit integration opt-in
unknown container identity
```

Normal non-destructive CLI commands may use configured Neo4j targets; only M3
reset/integration execution requires all three guards.

### 4.2 Runtime snapshot command

Add a read-only CLI command:

```bash
python -m src.pipeline.main graph-snapshot --raw-doc-code L59_2020
```

Output:

```text
data/reports/L59_2020/snapshots/<timestamp>.json
```

The command requires an explicit output name for acceptance evidence:

```bash
python -m src.pipeline.main graph-snapshot \
  --raw-doc-code L59_2020 \
  --output write_1.json
```

`--output` accepts a file name only, rejects path traversal, and writes under
`data/reports/L59_2020/snapshots/`. Timestamp naming is allowed only for ad-hoc
debug snapshots, not acceptance evidence.

Snapshot fields:

```text
timestamp
git_commit
neo4j_uri_without_credentials
graph_id
node_id_count
node_id_sha256
relation_id_count
relation_id_sha256
graph_projection_sha256
payload_projection_sha256
embedding_state_sha256
node_count_by_label
relation_count_by_type
missing_relation_id_count
duplicate_node_id_count
duplicate_relation_id_count
legacy_label_count
legacy_relation_count
Article/Clause/Point counts
temporal_property_type_breakdown
embedding coverage
```

Digest contract:

```text
node_id_sha256:
  sort unique canonical node IDs by UTF-8 codepoint order
  join with newline
  hash UTF-8 bytes using SHA-256

relation_id_sha256:
  require every written relation_id non-null
  sort unique relation IDs
  join with newline
  hash UTF-8 bytes using SHA-256

graph_projection_sha256:
  canonical JSON of sorted node and relationship records
  sort object keys and records by canonical ID
  include stable legal/provenance properties
  exclude embedding values and explicitly mutable `updated_at`
  include `created_at` because extraction artifacts keep it stable
  hash UTF-8 canonical JSON using SHA-256

payload_projection_sha256:
  compute from the validated local payload using the same canonical JSON rules
  exclude only embedding and `updated_at`
```

The snapshot may store ID counts and hashes without storing the entire ID sets.
Idempotency acceptance requires all legal graph digests to match. Equal counts
alone never prove idempotency.

Graph digests must query Neo4j. Payload and graph projections both include node
IDs/labels/stable properties and relation IDs/types/source IDs/target IDs/stable
properties. Date values normalize to `YYYY-MM-DD`, DateTime values to canonical
UTC ISO-8601, and null remains null. Embedding values and embedding metadata are
excluded from the legal projection and hashed separately as
`embedding_state_sha256`.

Written-state acceptance requires direct equality:

```text
payload_projection_sha256 == graph_projection_sha256
```

### 4.3 Temporal type verification

Add explicit checks for written properties:

```text
Document.effective_from/effective_to = DATE or null
Document.issued_date = DATE or null
Article.effective_from/effective_to = DATE or null
Clause.effective_from/effective_to = DATE or null
AMENDS/REPEALS/REPLACES.effective_from = DATE
DEFINES/REGULATES/REQUIRES.created_at = LOCAL DATETIME or ZONED DATETIME
```

Use Neo4j `valueType()` in verification queries. ISO strings in these persisted
properties are a Gate 4 failure.

Verification is generated from this canonical relation-property matrix:

| Relation | Property | Required | Expected persisted type |
|---|---|---:|---|
| AMENDS | effective_from | yes | DATE |
| REPEALS | effective_from | yes | DATE |
| REPLACES | effective_from | yes | DATE |
| REFERS_TO | confidence | yes | FLOAT |
| REFERS_TO | llm_model | yes | STRING |
| REFERS_TO | created_at | yes | temporal DateTime |
| REFERS_TO | citation_text | yes | STRING |
| REFERS_TO | citation_type | yes | STRING enum DIRECT/INDIRECT/RANGE |
| DEFINES | confidence | yes | FLOAT |
| DEFINES | llm_model | yes | STRING |
| DEFINES | created_at | yes | temporal DateTime |
| REGULATES | confidence | yes | FLOAT |
| REGULATES | llm_model | yes | STRING |
| REGULATES | created_at | yes | temporal DateTime |
| REQUIRES | confidence | yes | FLOAT |
| REQUIRES | llm_model | yes | STRING |
| REQUIRES | created_at | yes | temporal DateTime |
| REQUIRES | source_article | project-required provenance | STRING canonical Article ID |

`REFERS_TO` follows the semantic provenance contract in ontology v1.5.1 and
additionally requires citation text and type. The verifier imports expected
properties from the shared ontology contract and has a parity test against this
documented matrix. Missing provenance is never repaired with runtime defaults.

### 4.4 Batched embedding command

Current embedding code encodes all 1,115 texts in one call. Replace it with a
bounded batch contract:

```bash
python -m src.pipeline.main embed \
  --raw-doc-code L59_2020 \
  --batch-size 32
```

Rules:

- Default batch size is 32 and configurable.
- Before opening a write loop, encode one representative text and verify exactly
  1,024 dimensions.
- Verify both vector indexes are `ONLINE` and 1,024-dimensional before updating
  any node.
- Process deterministic node-ID order.
- Select targets from the validated payload manifest and verify each target is an
  Article/Clause reachable from `Document{id: "ldn_2020"}` through canonical
  `CONTAINS`; ID-prefix matching alone is forbidden.
- Record succeeded/failed IDs after every batch.
- Persist embedding metadata on every target:

```text
embedding_model
embedding_provider
embedding_dimension
embedding_normalized
embedding_content_hash
embedding_created_at
```

- `embedding_content_hash` hashes the exact text sent to the encoder. Article
  hash includes title + `content_raw`; Clause hash includes parent Article
  number/title + Clause number/content.
- Resume skips only when vector length and every metadata field match the current
  contract: model `BAAI/bge-m3`, provider `flag_embedding`, dimension 1024,
  normalized true, and current content hash.
- A vector with matching dimension but stale/missing metadata is re-embedded.
- `--force` re-embeds every validated target.
- Failure preserves completed batches and emits an explicit partial-coverage
  report; it does not claim Gate 5 pass.
- Point and semantic nodes remain unembedded.

### 4.5 Vector smoke command

Add:

```bash
python -m src.pipeline.main vector-smoke \
  --raw-doc-code L59_2020
```

The command embeds and queries these exact strings:

```text
quyền thành lập và quản lý doanh nghiệp
vốn điều lệ của công ty trách nhiệm hữu hạn
đăng ký thay đổi nội dung đăng ký doanh nghiệp
```

For each query and each index:

```text
query
index_name
rank
node_id
score
node title/content preview
```

Output:

```text
data/reports/L59_2020/vector_smoke_results.json
data/reports/L59_2020/vector_smoke_judgements.json
data/reports/L59_2020/vector_smoke.md
```

Machine results are immutable input to manual review. Judgements are stored
separately:

```json
{
  "query_id": "q1",
  "index_name": "article_embedding",
  "node_id": "ldn_2020_art17",
  "judgement": "relevant",
  "reason": "Directly provides the legal basis for the query",
  "reviewer": "manual",
  "reviewed_at": "ISO-8601 timestamp"
}
```

Judgement definition:

```text
relevant = directly answers the query or supplies a legal basis needed to answer
not_relevant = lexical/topical overlap without resolving the legal information need
```

Smoke acceptance:

- Every query executes successfully on both Article and Clause indexes.
- Every query has at least one relevant result in top five from at least one index.
- Each index has at least one of the three queries with relevant@5.
- Every judged row has reason, reviewer, and reviewed_at.
- Missing/null judgements cannot close Gate 5.

### 4.6 Milestone evidence command

Add:

```bash
python -m src.pipeline.main milestone-a-report \
  --raw-doc-code L59_2020
```

Inputs:

```text
extraction_run.json
extract/accepted/review/rejected counts
validate-payload summary
first/second write snapshots
embedding coverage
vector smoke report
graph-quality report
unit/integration test result summaries
git commit
ontology/schema/model versions
```

Runtime draft output:

```text
data/reports/L59_2020/milestone_a_summary.md
```

Tracked sanitized output after review:

```text
results/milestone_a/L59_2020_summary.md
```

The generator must mark every missing criterion `NOT PASSED`; it must never infer
success from absent evidence.

---

## 5. Gate 4A: Disposable Runtime and Schema

### 5.1 Start clean disposable runtime

```bash
cd infra
RUN_M3_DESTRUCTIVE=1 CONFIRM_M3_RESET=YES make m3-reset
make m3-up
make m3-status
make m3-init-schema
make m3-verify-schema
```

### 5.2 Schema acceptance

Required uniqueness constraints:

```text
doc_id_unique
iss_id_unique
ch_id_unique
art_id_unique
cls_id_unique
pnt_id_unique
lc_id_unique
ls_id_unique
la_id_unique
```

Required search/vector indexes:

```text
legal_article_clause_fulltext ONLINE
legal_point_fulltext ONLINE
article_embedding ONLINE, dimensions=1024, cosine
clause_embedding ONLINE, dimensions=1024, cosine
issued_by_relation_id ONLINE
contains_relation_id ONLINE
refers_to_relation_id ONLINE
guides_relation_id ONLINE
amends_relation_id ONLINE
repeals_relation_id ONLINE
replaces_relation_id ONLINE
defines_relation_id ONLINE
regulates_relation_id ONLINE
requires_relation_id ONLINE
```

Forbidden schema artifacts:

```text
BaseNode
entity_vector
legacy vector index names are forbidden even when configured at 1024 dimensions
AMENDED_BY / REPEALED_BY / REPLACED_BY indexes
runtime-only node constraints
```

Schema verification compares the exact expected canonical set with actual
constraints/indexes and reports these categories separately:

```text
missing
unexpected canonical or legacy names
wrong schema object type
wrong state
wrong labelsOrTypes/properties
wrong vector options
```

### 5.3 Empty baseline snapshot

Before the pilot write:

```text
Document count = 0
all canonical data node counts = 0
all relationship counts = 0
schema remains present and ONLINE
```

Store this as `write_0_empty.json`.

---

## 6. Gate 4B: Guarded Write and Idempotency

All commands use the disposable URI explicitly:

```bash
export NEO4J_URI=bolt://localhost:7688
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=<m3 disposable password>
```

### 6.1 Pre-write payload verification

Run twice:

```bash
python -m src.pipeline.main validate-payload --raw-doc-code L59_2020
python -m src.pipeline.main validate-payload --raw-doc-code L59_2020
```

Both outputs and deterministic relation IDs must match.

### 6.2 First write

```bash
python -m src.pipeline.main write --raw-doc-code L59_2020
python -m src.pipeline.main graph-snapshot \
  --raw-doc-code L59_2020 --output write_1.json
```

Store snapshot as `write_1.json`.

Expected values:

```text
nodes = 2333
relations = 2723
Article = 218
Clause = 897
Point = 822
REQUIRES = 53
missing relation_id = 0
legacy labels = 0
legacy relations = 0
```

### 6.3 Second write

Run the exact same write command again:

```bash
python -m src.pipeline.main write --raw-doc-code L59_2020
python -m src.pipeline.main graph-snapshot \
  --raw-doc-code L59_2020 --output write_2.json
```

Store snapshot as `write_2.json`.

Acceptance comparison:

```text
write_1 node counts == write_2 node counts
write_1 relation counts == write_2 relation counts
write_1 node_id_sha256 == write_2 node_id_sha256
write_1 relation_id_sha256 == write_2 relation_id_sha256
write_1 graph_projection_sha256 == write_2 graph_projection_sha256
write_1 payload_projection_sha256 == write_1 graph_projection_sha256
write_2 payload_projection_sha256 == write_2 graph_projection_sha256
duplicate node IDs = 0
duplicate relation IDs = 0
missing relation IDs = 0
```

Property timestamps may differ only where the contract explicitly updates
`updated_at`; legal provenance and `created_at` must not be silently replaced.

### 6.4 Temporal and provenance checks

Verify:

```text
all effective_from/effective_to values have Neo4j temporal types
all semantic created_at values have Neo4j datetime types
every REQUIRES has source_article
both REQUIRES edges for the same endpoints but different source_article survive
relation_id is deterministic from the correct relation discriminator
```

### 6.5 Gate 4 stop conditions

Stop before embedding if:

```text
any count differs from Gate 3 payload
second write changes counts
any temporal property is a STRING
any relation lacks relation_id
any duplicate relation_id exists
any legacy label/relation exists
any write bypasses ValidatedGraphPayload
```

---

## 7. Disposable Neo4j Integration Suite

### 7.1 Test configuration

Run only against port 7688:

```bash
RUN_NEO4J_INTEGRATION=1 \
NEO4J_URI=bolt://localhost:7688 \
pytest tests/integration -q -m integration
```

The suite must fail before test execution when URI points to 7687 or a non-local
host.

Protect the pilot with snapshots:

```bash
graph-snapshot --raw-doc-code L59_2020 --output pre_integration.json
RUN_NEO4J_INTEGRATION=1 NEO4J_URI=bolt://localhost:7688 \
  pytest tests/integration -q -m integration
graph-snapshot --raw-doc-code L59_2020 --output post_integration.json
```

Acceptance:

```text
pre/post node_id_sha256 equal
pre/post relation_id_sha256 equal
pre/post graph_projection_sha256 equal
```

### 7.2 Required integration coverage

```text
schema constraints/indexes exist and vector indexes are ONLINE
write twice is idempotent
temporal serialization round-trip returns Neo4j Date/DateTime
REQUIRES provenance creates two identities for distinct source_article
embedding write/read round-trip is 1024-dimensional
graph-quality source is neo4j and metrics are non-placeholder
session and driver close on success and failure
```

### 7.3 Test isolation

Each test generates a UUID and uses:

```text
graph_id = test_<uuid>
node prefix = test_<uuid>_
```

Before cleanup, the fixture queries the full matched ID list and asserts every ID
starts with the current UUID prefix. If any matched ID falls outside the prefix,
cleanup fails without deleting anything. Fixed shared prefixes and cleanup queries
that can match `ldn_2020` are forbidden. Parallel test runs must not collide.

---

## 8. Gate 5: BGE-M3 Embedding and Vector Sanity

### 8.1 Dependency and resource preflight

```bash
uv sync --group dev --group embedding
```

Record:

```text
Python version
torch version
FlagEmbedding version
device CPU/CUDA
available RAM/VRAM
model cache path
configured model/provider/dimension
```

Expected contract:

```text
model = BAAI/bge-m3
provider = flag_embedding
dimension = 1024
normalize_embeddings = true
```

### 8.2 Batched embedding execution

```bash
python -m src.pipeline.main embed \
  --raw-doc-code L59_2020 \
  --batch-size 32
```

Expected targets:

```text
Article = 218
Clause = 897
Total = 1115
Point = 0
Semantic nodes = 0
```

### 8.3 Coverage verification

```text
Article embedded = 218 / 218 = 1.0
Clause embedded = 897 / 897 = 1.0
all stored vectors = 1024 values
no embedding exists outside Article/Clause
```

Rerun the command once. It must skip or safely overwrite valid target embeddings
without changing graph topology.

### 8.4 Vector smoke

Run `vector-smoke`, inspect top five from Article and Clause indexes, and record
manual relevance in the separate judgement artifact. Apply the exact cross-index
acceptance rules in section 4.5. This is smoke evidence only, not retrieval
evaluation.

### 8.5 Gate 5 stop conditions

```text
model output dimension != 1024
index dimension != 1024
index state != ONLINE
coverage < 1.0
Point/semantic embedding detected
vector query returns dimension/type error
all top-5 results are manually irrelevant for any required query
```

---

## 9. Gate 6: Online Graph Quality

Run:

```bash
python -m src.pipeline.main graph-quality --raw-doc-code L59_2020
```

Required outputs:

```text
data/reports/L59_2020/graph_quality.json
data/reports/L59_2020/graph_quality.md
```

Required assertions:

```text
source = neo4j
Article = 218
Clause = 897
semantic nodes > 0
semantic relations > 0
ontology violations = 0
duplicate node IDs = 0
duplicate relation identities = 0
dangling endpoints = 0
Article embedding coverage = 1.0
Clause embedding coverage = 1.0
connected components computed from full written subgraph
orphan count computed from full written subgraph
graph density and average degree include documented formulas
extraction decision totals = 1743 / 775 / 434 / 534
review reasons include semantic_type_conflict and external registry review
```

Do not merge extraction rejection rate with database ontology violation rate.

Report two topology groups:

### Full written graph

```text
nodes = all written nodes for the document subgraph
edges = all canonical relations including ISSUED_BY and CONTAINS
connected components = weak components on an undirected projection
multi-edges = retained for edge counts and average degree
density = directed E/(N*(N-1)), excluding self-loops
average degree = 2E/N on undirected projection with multi-edge multiplicity
orphan = full-graph degree zero
```

### Structural-excluded semantic graph

```text
nodes = all Article and Clause nodes in scope, all semantic nodes in the accepted
written payload, and Document nodes required by temporal or cross-document edges
edges = DEFINES, REGULATES, REQUIRES, REFERS_TO, AMENDS, REPEALS, REPLACES, GUIDES
connected components = weak components on undirected projection
multi-edges = retained because provenance-distinct REQUIRES edges are meaningful
article_clause_semantic_orphan_count = Article/Clause nodes with semantic degree zero
semantic_entity_orphan_count = LegalConcept/LegalSubject/LegalAction nodes with semantic degree zero
semantic density = directed E/(N*(N-1)), excluding self-loops
semantic average degree = 2E/N
```

Both groups must expose node/edge counts alongside formulas. Full-graph
connectivity cannot be used as evidence of semantic connectivity because
`CONTAINS` connects almost every structural unit.

---

## 10. Pilot Evidence and Sign-off

Generate the draft evidence report, then manually fill vector judgements and test
commands.

Required report sections:

```text
timestamp and git commit
raw_doc_code and graph_id
ontology/schema/prompt/endpoint contract versions
configured and resolved LLM model
embedding model/provider/dimension
Gate 2 decision and conflict counts
Gate 3 payload baseline
schema/index verification
write_1/write_2 count comparison
temporal type verification
integration test result
embedding coverage
vector top-5 and manual relevance
graph-quality summary
known caveats
open blockers
```

Pilot sign-off requires all of these:

```text
Gate 2 PASS
Gate 3 PASS
Gate 4 PASS
integration suite PASS
Gate 5 PASS
Gate 6 PASS
tracked pilot evidence reviewed
```

Blockers are closed individually; range closure is forbidden:

| Blocker | Required evidence | Scope | Closure rule |
|---|---|---|---|
| M3-B06 | disposable identity + empty/write snapshots | pilot | close only after canonical graph replaces stale evidence |
| M3-B07 | write_1/write_2 digest equality | pilot | close only after all graph/property digests match |
| M3-B08 | embedding metadata and 1.0 coverage | pilot | close only after model/content-aware resume verification |
| M3-B09 | machine results + complete manual judgements | pilot | close only after vector smoke criteria pass |
| M3-B10 | online full + semantic-only graph-quality reports | pilot | close only with zero integrity/ontology violations |
| M3-B11 | disposable integration output + pre/post pilot digest equality | pilot | close only when tests pass and pilot is unchanged |
| M3-B12 | reviewed tracked pilot summary | pilot | close only when all referenced evidence exists |
| M3-B13 | four per-document reports + corpus reconciliation summary | corpus | close only after all four documents and corpus checks pass |

Each closure update records evidence path, scope, timestamp, git commit, and
reviewer. Pilot completion does not close M3-B13.

---

## 11. Gate 7: Four-Document Minimum Corpus

Required documents:

```text
L59_2020
ND01_2021
ND47_2021
TT01_2021
```

For each document run:

```text
validate-data
parse
manual hierarchy spot-check
smoke extraction
full extraction
validate-payload
write twice
embed
vector/coverage check
graph-quality
per-document evidence report
```

### 11.1 Corpus external-reference reconciliation

Per-document extraction may leave `missing_external_document_registry` review
records when the target document has not yet passed validation. After all four
canonical Document nodes are registered, run:

```bash
python -m src.pipeline.main reconcile-external-references \
  --corpus milestone-a
```

The command:

```text
loads only review records with external-registry reasons
resolves document/article/clause targets against the accepted four-document registry
preserves raw relation and previous decision audit
reruns endpoint normalization, ontology validation, consistency, scoring, and decision
atomically regenerates decision artifacts for affected source documents
prints changed review->accepted/rejected counts
does not call an LLM
does not modify unrelated low-confidence or semantic-type-conflict reviews
```

After reconciliation:

```text
re-run validate-payload for every affected source document
write every affected source document idempotently
capture corpus snapshot before and after the rewrite
regenerate per-document graph quality
run corpus-level integrity and semantic conflict checks
```

Corpus acceptance:

```text
corpus dangling endpoints = 0
writer-eligible unresolved external references = 0
duplicate semantic IDs = 0
accepted semantic type conflicts = 0
all cross-document relation endpoints exist
pre/post reconciliation rewrites are idempotent
```

Required tracked report:

```text
results/milestone_a/corpus_summary.md
```

Corpus rules:

- Do not substitute discovery-pool documents.
- Do not write a document whose payload fails.
- Continue independent documents after one failure, but keep Milestone A blocked.
- Shared semantic entities are merged by canonical ID only after type conflicts are
  resolved or moved to review.
- External references become writer-eligible only when both endpoint documents
  exist in the accepted graph and registry lookup is verified.

Milestone A requires all four documents to pass end to end.

---

## 12. Test Plan for New Gate Tooling

### Unit tests

```text
disposable target rejects port 7687
URI guard cannot infer container identity
reset requires confirmation token
Docker guard verifies exact image, ports, and named volume
snapshot metrics are deterministic
snapshot excludes credentials
snapshot digests detect equal-count/different-ID graphs
canonical property digest excludes only approved mutable fields
write snapshot comparison catches count changes
temporal type report rejects STRING values
embedding batches preserve deterministic order
embedding dimension preflight occurs before DB update
embedding resume requires matching model/provider/normalized/content hash metadata
embedding target must be payload-backed and Document-reachable
vector smoke keeps machine results and manual judgements separate
integration UUID cleanup refuses out-of-prefix matches
external reconciliation changes only registry-blocked review records
blocker closure requires its own evidence path
evidence report marks missing inputs NOT PASSED
REQUIRES source_article identity remains distinct
```

### Integration tests

```text
dedicated container guard works
schema bootstrap is idempotent
write twice is idempotent
equal graph digests prove pilot identity, not only counts
temporal values round-trip with Neo4j types
vector indexes are ONLINE/1024/cosine
embedding round-trip succeeds
online graph-quality succeeds
integration pre/post snapshots prove pilot unchanged
test cleanup cannot delete pilot nodes
```

### Verification commands

```bash
pytest -q
RUN_NEO4J_INTEGRATION=1 NEO4J_URI=bolt://localhost:7688 \
  pytest tests/integration -q -m integration
ruff check <changed files>
git diff --check -- <changed files>
```

---

## 13. Execution Order

1. Freeze disposable Compose identity, image, ports, and named volume.
2. Implement pure URI guard, integration opt-in guard, and Docker identity guard.
3. Add payload/node/relation/canonical-property digest tooling and named snapshots.
4. Add embedding model/provider/content-hash metadata and safe resume contract.
5. Add UUID-isolated integration fixtures and pre/post pilot snapshots.
6. Add separated vector results and manual judgement artifacts.
7. Add external-reference corpus reconciliation and corpus report contract.
8. Add exact schema expected-set verification and ontology property matrix parity.
9. Pass fast tests and targeted static checks.
10. Reset/start only the disposable M3 container and named volume.
11. Apply schema, compare exact expected set, and capture empty snapshot.
12. Run payload dry validation twice and compare payload hashes.
13. Write pilot twice and compare node, relation, and canonical-property digests.
14. Verify temporal types, required properties, provenance, and legacy counts.
15. Snapshot pilot, run UUID-isolated integration suite, and prove pilot unchanged.
16. Run content/model-aware batched embedding and verify coverage/metadata.
17. Run vector smoke on both indexes and complete separate manual judgements.
18. Generate full-graph and structural-excluded semantic graph-quality reports.
19. Generate and review tracked pilot evidence; close pilot blockers individually.
20. Execute the four-document minimum corpus.
21. Reconcile cross-document references and idempotently rewrite affected sources.
22. Generate corpus-level integrity and evidence report; close M3-B13 only if passed.
23. Sign off Milestone A, then explicitly unblock Phase 2.

---

## 14. Explicit Non-Goals

This execution must not:

```text
reset or write the current port-7687 development DB
start Phase 2 retrieval implementation
use prototype retrieval as Milestone A evidence
embed Point or semantic nodes
weaken ontology validation to improve acceptance counts
auto-accept semantic type conflicts
write review/rejected extraction records
run all 89 discovery documents
claim Milestone A from pilot-only evidence
store credentials in reports
```

---

## 15. Approval Boundary

Plan review approves implementation of tooling and disposable infrastructure.

The first destructive action is limited to:

```text
RUN_M3_DESTRUCTIVE=1 CONFIRM_M3_RESET=YES make m3-reset
```

and only after all separate guards pass:

```text
URI = explicit local Bolt 7688
destructive opt-in = RUN_M3_DESTRUCTIVE=1 and CONFIRM_M3_RESET=YES
Compose service/container = graphrag-neo4j-m3
image = neo4j:5.26.28-community
volume = graphrag-neo4j-m3-data mounted at /data
```

No command may reset the existing `graphrag-neo4j` instance, its bind-mounted
storage, or port 7687.
