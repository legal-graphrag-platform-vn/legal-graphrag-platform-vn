# Plan 17 — Corpus-Wide External Structural Reference Materialization

> Status: IMPLEMENTED — live Neo4j integration test requires the disposable runtime
> Date: 2026-07-31
> Authority: ADR-24, amended to the Phase 0 contract defined by this plan
> Ontology: v1.7.0 remains unchanged
> Progress: Phases 0–6 implemented with unit coverage and an opt-in Neo4j integration test
> Depends on: ADR-22 resolver-first references, ADR-23 Section hierarchy,
> `legal_ontology.md`, and completed per-document structural ingestion

## 1. Goal

Implement safe cross-document structural references such as:

```text
Thông tư A, Điều 1
-> điểm d khoản 3 Điều 8 Nghị định 57/2026/NĐ-CP
```

The target is a normal canonical structural node owned by another accepted
`Document`. There is no external-node label and no new graph relation:

```text
(source:Article|Clause|Point)-[:REFERS_TO]->
  (target:Document|Chapter|Section|Article|Clause|Point)
```

The implementation must enforce three separate boundaries:

```text
accepted hierarchy -> immutable registry snapshot       # identity/existence
reference candidate -> unique canonical target          # resolution
verified endpoints -> Neo4j REFERS_TO relationship      # materialization
```

Resolution and materialization state must remain independent. A target can be
resolved in a registry snapshot but fail materialization because the current
Neo4j graph is stale or incomplete.

## 2. Non-goals

This plan does not:

- add `ExternalNode`, `RegistryNode`, `EXTERNAL_REFERS_TO`, or another ontology
  label/relation;
- add `document_id` to Chapter, Section, Article, Clause, or Point;
- make `build_id`, `snapshot_hash`, or `provenance_hash` required Neo4j
  relationship properties;
- use an LLM for explicit numbered structural references;
- implement broad semantic phrases such as `các quy định khác có liên quan`;
- implement compound-list grammar expansion such as
  `điểm d, đ và e khoản 3 Điều 8`;
- claim a distributed transaction between the checkpoint store and Neo4j;
- change temporal retrieval semantics or create temporal fields on Chapter,
  Section, or Point.

Existing multi-target candidates remain atomic. If a later parser expands a
compound mention, this implementation must materialize the whole bundle or no
edge from that bundle.

## 3. Current Implementation Findings

### 3.1 Document identity is manifest-backed, not existence-backed

`src/pipeline/extraction/structural_context.py::DocumentRegistry` currently
loads aliases from `configs/corpus/curated_v1.json`. The manifest proves corpus
intent only. It does not prove that a Document or target hierarchy passed
validation or exists in Neo4j.

The current alias loop also performs substring matching and stores one identity
per alias. It can resolve a false positive or silently overwrite ambiguity.

### 3.2 External structural IDs are inferred

`StructuralReferenceResolver._resolve_external` currently resolves a document
alias and constructs IDs such as:

```text
{graph_id}_art{article}_cl{clause}_p{point}
```

It returns `RESOLVED` without proving that the target structural unit exists.
External Chapter and Section candidates remain unconditionally unresolved.

### 3.3 Per-document validation intentionally blocks external endpoints

`_rule_reference_records` validates against `set(registry.types)`, which contains
only the source document hierarchy. `record_consistency_validator` therefore
marks an external target as `missing_external_document_registry`.

`payload_builder.py`, `payload_consistency_validator.py`, and the root
`OntologyValidator.validate_graph_payload` all require relation endpoints to be
inside the same per-document payload. This is correct for normal graph payloads
and must not be relaxed with fake node descriptors.

### 3.4 The generic writer is not a relation-only external writer

`Neo4jWriter` writes nodes first and then uses unlabelled endpoint `MATCH`
queries. It does not consume the relation query result or fail on zero rows. It
accepts only a root `ValidatedGraphPayload`.

External materialization requires a separate validated relation-batch boundary;
the existing node/payload writer must remain closed.

### 3.5 Checkpoints do not track materialization

`reference_resolutions.jsonl` currently stores one resolver result and resolver
fingerprint. It has no snapshot proof, materialization state, attempt state, or
typed graph-divergence reason.

### 3.6 Planned CLI is absent

Plan 08 mentions `reconcile-external-references`, but `src/pipeline/main.py` has
no such command. The plan text also predates ADR-24 and assumes a manifest-style
document registry.

## 4. Target Data Flow

```text
Per-document canonical source
-> parse hierarchy
-> build graph payload
-> payload consistency validation
-> root ontology validation
-> write all structural nodes

ValidatedGraphPayloads for explicit corpus selection
-> select structural nodes + canonical CONTAINS edges only
-> verify one Document owner per structural unit
-> canonical sort
-> publish immutable content snapshot keyed by snapshot_hash
-> publish immutable build receipt keyed by build_id and provenance_hash

Canonical source + hierarchy + registry snapshot
-> detect explicit external structural candidates
-> exact normalized document lookup
-> exact structural-key lookup
-> 0/1/>1 resolution
-> checkpoint resolution state

RESOLVED external bundles
-> validate snapshot proof, endpoint types, ownership, different Documents,
   provenance, deterministic relation IDs, and bundle completeness
-> root-validated relation batch
-> acquire per-source checkpoint lock and re-read checkpoint/attempt history
-> Neo4j transaction MATCHes endpoints and checks existing bundle targets
-> MERGE REFERS_TO only
-> consume exact result count
-> append and fsync materialization attempt
-> compare-and-swap and fsync checkpoint materialization state
```

## 5. Registry Content and Build Contract

### 5.1 New module

Add:

```text
src/pipeline/extraction/corpus_structural_registry.py
```

Keep `StructuralRegistry` in `structural_context.py` as the document-local
registry. Remove the manifest-backed `DocumentRegistry` from deterministic
external resolution once all callers migrate. The curated manifest remains an
orchestration selector only.

### 5.2 Snapshot input boundary

The snapshot builder accepts only root `ValidatedGraphPayload` instances
produced by the existing shared ontology validator. It must not accept raw
`hierarchy.json`, raw payload dictionaries, crawler metadata, or manifest rows
as accepted structural evidence.

Refactor `_validated_payload_for_raw_doc_code` into:

```text
pure loader/validator service
-> CLI error mapping wrapper
```

The pure service should live outside `main.py` so registry tests and commands do
not depend on Typer exits or console output.

For each selected document, the builder records both the canonical accepted
structural projection and stable provenance digests for the canonical source,
parser/validator contracts, and validated structural projection. Semantic nodes
and non-`CONTAINS` relations do not enter the registry content snapshot.

### 5.3 Content snapshot and build-receipt DTOs

Add Pydantic or frozen dataclass DTOs with explicit contract versioning:

```python
RegistryContentManifest:
    contract_version: Literal["corpus-structural-registry-v1"]
    snapshot_hash: str
    ontology_version: str
    canonicalization_version: str
    document_count: int
    structural_unit_count: int
    contains_relation_count: int

RegistryBuildReceipt:
    contract_version: Literal["corpus-structural-registry-build-v1"]
    build_id: str
    snapshot_hash: str
    provenance_hash: str
    parser_contract_version: str
    hierarchy_contract_version: str
    validator_version: str
    source_artifacts: tuple[RegistrySourceArtifact, ...]
    created_at: datetime

RegistrySourceArtifact:
    raw_doc_code: str
    document_id: str
    canonical_source_digest: str
    validated_structural_projection_digest: str

RegistryDocument:
    document_id: str
    number: str
    normalized_number: str
    doc_type: str

RegistryUnit:
    unit_id: str
    unit_type: Literal["Chapter", "Section", "Article", "Clause", "Point"]
    document_id: str
    parent_id: str
    ancestor_ids: tuple[str, ...]
    chapter_number: str | None
    section_number: str | None
    article_number: str | None
    clause_number: str | None
    point_label: str | None

RegistryEndpoint = RegistryDocument | RegistryUnit
```

`RegistryDocument` is both the document-identity record and the canonical
`Document` endpoint. `RegistryUnit` contains descendants only. Therefore
`documents.jsonl` and `units.jsonl` never represent the same Document twice.
`ancestor_ids` records accepted ownership evidence and is not persisted as graph
ontology metadata.

For endpoint evidence, a `RegistryDocument` owns itself and has an empty
`ancestor_ids` projection. A descendant `RegistryUnit` must have exactly one
Document ancestor and the complete canonical ancestor chain required by its
type.

### 5.4 Structural keys and normalization

Add shared pure normalization helpers rather than parsing node IDs:

```text
Document key = normalized document number
Chapter key  = document_id + normalized chapter number
Section key  = document_id + chapter + normalized section number
Article key  = document_id + normalized article number
Clause key   = document_id + article + normalized clause number
Point key    = document_id + article + clause + normalized legal point label
```

Requirements:

- numbers remain strings and support suffixes such as `1a`;
- Chapter Roman/Arabic normalization reuses `shared.ontology.hierarchy`;
- `d` and `đ` remain distinct legal labels; their ID components may remain
  `d` and `dd` through the existing helper;
- document-number aliases use exact Unicode-normalized matching, never substring
  matching;
- the resolver never infers existence from an ID prefix or suffix.

### 5.5 Cardinality and integrity

In-memory indexes retain candidate lists:

```text
document_alias -> tuple[RegistryDocument, ...]
structural_key -> tuple[RegistryUnit, ...]
endpoint_id    -> RegistryEndpoint
```

The structural-key index never contains `RegistryDocument`. Document references
resolve through the document-identity index and return `RegistryDocument`;
Chapter/Section/Article/Clause/Point references resolve through the structural
index and return `RegistryUnit`.

Rules:

```text
0 candidates  -> UNRESOLVED
1 candidate   -> RESOLVED
>1 candidates -> AMBIGUOUS
```

Snapshot publication hard-fails duplicate canonical node IDs, invalid
`CONTAINS` pairs, structural cycles, multiple Document owners, missing parents,
or duplicate local structural keys inside one accepted Document. Duplicate
document aliases across accepted Documents remain representable so lookup can
return `AMBIGUOUS` instead of overwriting one candidate.

The loader still implements `>1 -> AMBIGUOUS` defensively for any structural
index, even though a valid newly built snapshot should not contain duplicate
local structural keys.

### 5.6 Content address, provenance, and publication

Add setting:

```text
DATA_REGISTRY_DIR=<repo>/data/registry
```

Publish:

```text
data/registry/
  content/<snapshot_hash_hex>/
    content_manifest.json
    documents.jsonl
    units.jsonl
  builds/<build_id>/
    build_receipt.json
  current_reference_registry -> builds/<build_id>
```

`snapshot_hash` proves immutable registry content. Its canonical hash input is:

```text
registry contract version
ontology version
canonicalization version
sorted canonical RegistryDocuments
sorted canonical RegistryUnits
sorted canonical parent/ownership structure
```

`provenance_hash` proves which stable inputs and validation contracts produced a
build receipt. Its canonical hash input is:

```text
parser contract version
hierarchy contract version
validator version
sorted (document_id, canonical source-content digest) pairs
sorted (document_id, validated structural-projection digest) pairs
snapshot_hash
```

Exclude `build_id`, `created_at`, filesystem paths, symlink targets, operational
artifact UUIDs, and both output hash fields from their own hash inputs. A source
change that does not alter accepted hierarchy may keep `snapshot_hash` stable
while changing `provenance_hash`. Rebuilding identical inputs may create a new
`build_id` while retaining both hashes.

`raw_doc_code` remains receipt-level orchestration metadata and does not enter
the content snapshot or provenance hash. Renaming a source folder must not
change registry identity when canonical `document_id`, source bytes, validated
projection, and contracts are unchanged.

Resolution semantics and relation identity depend on `snapshot_hash`, never on
`build_id` or `provenance_hash`. The latter two remain audit evidence.
Hashes serialize as `sha256:<lowercase-hex>` in DTOs; filesystem paths use only
the validated lowercase hexadecimal component.

Publication requirements:

- validate `build_id` against a filename-safe allowlist;
- create a staging directory under `DATA_REGISTRY_DIR`;
- fsync/close files before atomic directory rename where supported;
- refuse to overwrite an existing content directory or `build_id` with
  different canonical content;
- allow an identical content snapshot to be reused by multiple build receipts;
- atomically switch the `current_reference_registry` pointer only after all
  content files, receipt fields, and recomputed hashes validate;
- reject path traversal and symlink escapes.

The snapshot/provenance hashes prove content identity and reproducible build
evidence, not author authentication. A build receipt is immutable; new
provenance for an existing `snapshot_hash` creates a new receipt instead of
mutating an old one.

## 6. External Candidate and Resolver Contract

### 6.1 Extend the candidate DTO

Extend `StructuralTargetCandidate` to represent every supported exact target:

```python
target_type: Document | Chapter | Section | Article | Clause | Point
document_number: str
chapter_number: str | None
section_number: str | None
article_number: str | None
clause_number: str | None
point_label: str | None
```

The DTO must validate parent requirements:

- Section requires Chapter;
- Clause requires Article;
- Point requires Article and Clause;
- Document has no child-number fields.

### 6.2 Grammar precedence

Replace trailing-segment document-number scanning with exact external
expressions. Required precedence:

```text
external Point + Clause + Article + Document
-> external Clause + Article + Document
-> external Section + Chapter + Document
-> external Chapter + Document
-> external Article + Document
-> explicit bare Document
-> existing local Section/Chapter/Point/Clause/Article patterns
```

Supported deterministic examples:

```text
điểm d khoản 3 Điều 8 Nghị định số 57/2026/NĐ-CP
khoản 3 Điều 8 của Nghị định 57/2026/NĐ-CP
Điều 8 Nghị định 57/2026/NĐ-CP
Chương V của Nghị định 57/2026/NĐ-CP
Mục 1 Chương III Nghị định 57/2026/NĐ-CP
Nghị định số 57/2026/NĐ-CP
```

Specific matches occupy the whole citation span so nested Article and Document
patterns cannot emit redundant edges. A bare Document edge is emitted only when
the mention itself targets the Document rather than a more specific structural
unit.

Compound/shared-trailing-document grammar remains deferred. The resolver must
not partially parse a deferred compound expression into a misleading single
target.

### 6.3 Resolution output

Add registry proof to resolved external results:

```python
RegistryResolutionEvidence:
    build_id: str
    snapshot_hash: str
    provenance_hash: str
    source_id: str
    source_type: str
    source_document_id: str
    source_ancestor_ids: tuple[str, ...]
    target_document_id: str
    target_id: str
    target_type: str
    target_ancestor_ids: tuple[str, ...]
```

Resolution rules:

1. Resolve the source endpoint and its unique Document ownership in the loaded
   content snapshot.
2. Resolve the exact normalized target document number to 0/1/>1 candidates.
3. Resolve the target structural key only inside the uniquely resolved target
   Document, or return the `RegistryDocument` for a Document target.
4. Validate target type and parent chain from the snapshot record.
5. Classify scope as `LOCAL` or `EXTERNAL` from the two registry-proven Document
   owners; do not trust parser-supplied scope.
6. Return `RESOLVED` only when source and target each exist uniquely in the same
   verified `snapshot_hash`.
7. Never create a canonical target ID inside the resolver as a substitute for
   lookup.

Explicit citation of the current document must route through local structural
resolution or an explicit same-document reason; it must not enter the external
materializer.

Reason codes should distinguish:

```text
target_document_not_in_snapshot
target_document_identity_ambiguous
target_structural_unit_not_found
target_structural_unit_ambiguous
target_parent_chain_mismatch
same_document_reference_not_external
source_endpoint_not_in_snapshot
source_endpoint_ambiguous
source_document_ownership_ambiguous
```

## 7. Reference Checkpoint v2

### 7.1 Schema

Replace ad-hoc rows with a versioned model:

```python
ReferenceCheckpointV2:
    contract_version: Literal["reference-checkpoint-v2"]
    reference_bundle_id: str
    mention_fingerprint: str
    resolver_name: str
    resolver_version: str
    detected_at: datetime
    reference: ResolvedReference
    resolution: ReferenceResolutionState
    materialization: ReferenceMaterializationState

ReferenceResolutionState:
    status: UNRESOLVED | RESOLVED | AMBIGUOUS
    reference_scope: LOCAL | EXTERNAL | UNKNOWN
    is_self_reference: bool
    reason_code: str
    target_ids: tuple[str, ...]
    build_id: str | None
    snapshot_hash: str | None
    provenance_hash: str | None
    resolved_at: datetime | None

ReferenceMaterializationState:
    status: NOT_APPLICABLE | PENDING | WRITTEN | FAILED | BLOCKED
    reason_code: str | None
    relation_ids: tuple[str, ...]
    attempt_count: int
    last_attempt_at: datetime | None
    written_at: datetime | None
```

State transitions:

```text
UNRESOLVED/AMBIGUOUS                    -> NOT_APPLICABLE
RESOLVED + LOCAL + self                 -> NOT_APPLICABLE/self_reference_no_edge
RESOLVED + LOCAL + not self             -> NOT_APPLICABLE for external materializer
RESOLVED + EXTERNAL                     -> PENDING
PENDING + successful durable write      -> WRITTEN
PENDING + retryable graph verification  -> FAILED
FAILED + later successful retry         -> WRITTEN
target changed after any prior write    -> BLOCKED
```

`is_self_reference` is resolver-derived and is true if and only if resolution is
`RESOLVED`, scope is `LOCAL`, exactly one target exists, and its ID equals the
source endpoint ID. It is never trusted from a parser or checkpoint input.

A new content snapshot reruns resolution. If the same mention resolves to the
same target set, preserve stable citation provenance and record the new build
evidence. If the target set changes:

```text
old target set was never durably or graph-observably written
-> append resolution audit
-> replace pending target set
-> allow normal materialization

old target set was ever WRITTEN, or matching old bundle edges exist in Neo4j
-> materialization BLOCKED
-> reason resolved_target_changed_after_materialization
-> do not create new edges
-> do not delete old edges
```

The decision must inspect durable attempt history and the current graph. The
current checkpoint status alone is not proof that an edge was never written.

### 7.2 Atomicity and audit

Continue atomic replacement of the current checkpoint file. Add an append-only
materialization-attempt log per source document so a failed checkpoint update
does not erase Neo4j outcome evidence:

```text
data/processed/<raw_doc_code>/reference_resolutions.jsonl
data/processed/<raw_doc_code>/reference_materialization_attempts.jsonl
```

Each attempt records at least:

```text
attempt_id
reference_bundle_id
build_id
snapshot_hash
provenance_hash
expected_checkpoint_hash
expected_target_ids
observed_existing_target_ids
graph_outcome = COMMITTED | NOT_COMMITTED | UNKNOWN
relation_ids
started_at
finished_at
error_code
record_hash
```

Do not log credentials, full source text, or provider payloads.

Checkpoint mutation uses both a per-`raw_doc_code` advisory lock and
compare-and-swap by canonical checkpoint-file hash:

```text
acquire per-document lock
-> read checkpoint, attempt ledger, and expected checkpoint hash
-> resolve/validate/materialize
-> append + flush + fsync one complete attempt row
-> atomically replace checkpoint only when expected hash still matches
-> fsync checkpoint and parent directory
-> release lock
```

The attempt ledger append and checkpoint CAS occur under the same lock. Locking
prevents cooperating local processes from reconciling the same document at the
same time; CAS detects stale writers or non-cooperating updates.

After a successful Neo4j commit, durability order is mandatory:

```text
Neo4j commit returns success
-> append attempt row
-> flush and fsync attempt ledger
-> CAS checkpoint to WRITTEN
-> fsync checkpoint file and parent directory
```

If graph commit succeeds but ledger append/fsync fails, do not advance the
checkpoint. If the commit outcome is uncertain, append `graph_outcome=UNKNOWN`
when possible and do not mark `WRITTEN`; retry must re-read Neo4j state. If the
ledger is durable but checkpoint CAS fails, preserve both graph and ledger and
fail with a typed stale-checkpoint result rather than overwriting newer state.

There is no silent v1 fallback. Bump resolver/checkpoint contract versions and
regenerate reference checkpoints offline from canonical source and
`hierarchy.json`. Existing Article LLM checkpoints remain reusable because this
step does not call a provider.

## 8. External Bundle Validation

### 8.1 New module

Add:

```text
src/pipeline/validation/external_reference_validator.py
```

It consumes only resolved external references plus a loaded snapshot whose hash
has been recomputed successfully.

Validation order:

```text
checkpoint schema
-> snapshot hash and contract
-> source registry endpoint
-> target registry endpoint
-> different Document ownership
-> endpoint ontology types
-> REFERS_TO required provenance
-> deterministic relation identity
-> atomic bundle completeness
-> validated relation batch
```

### 8.2 Root-validated relation batch

Extend `src/shared/ontology/validators.py` with a separate tokened DTO:

```python
ValidatedExternalReference:
    relation: ValidatedRelation
    source_id: str
    source_type: str
    source_document_id: str
    source_ancestor_ids: tuple[str, ...]
    target_id: str
    target_type: str
    target_document_id: str
    target_ancestor_ids: tuple[str, ...]
    reference_bundle_id: str

ValidatedRelationBatch:
    references: tuple[ValidatedExternalReference, ...]
    registry_build_id: str
    registry_snapshot_hash: str
    registry_provenance_hash: str
    validation_token: object
```

Add a validator entry point that reuses the canonical `validate_relation`
contract with registry-proven `head_type` and `tail_type`. The wrapper preserves
the source and target Document IDs proven by the snapshot so the writer can
recheck ownership without parsing endpoint IDs. It validates relation shape and
ontology only; registry and bundle consistency remain the pipeline consistency
layer immediately before it.

Every source and target endpoint, together with unique Document ownership, must
exist in the same recomputed `registry_snapshot_hash`. Mixing source evidence
from one content snapshot with target evidence from another is a hard failure,
even if canonical IDs happen to match.

Do not add external endpoint stubs to `ValidatedGraphPayload`, and do not relax
the existing graph-payload dangling-endpoint checks.

### 8.3 Relation provenance

Resolved external rules use:

```text
extraction_method = ENTITY_LINKING
linker_name        = corpus-structural-registry
linker_version     = 1.0.0
```

Retain all current required `REFERS_TO` properties, source offsets,
`reference_bundle_id`, and `reference_target_count`. `build_id`,
`snapshot_hash`, and `provenance_hash` remain checkpoint/attempt evidence linked
by bundle ID under ontology v1.7.0. They must not participate in `relation_id`.

No confidence score or fake LLM provenance is added.

## 9. Neo4j Relation-Only Materializer

### 9.1 New adapter

Add:

```text
src/infrastructure/neo4j/reference_writer.py
```

`Neo4jExternalReferenceWriter` accepts only the root
`ValidatedRelationBatch`. It reads source/target ownership exclusively from the
tokened `ValidatedExternalReference` wrappers. A raw dictionary, raw checkpoint,
or ordinary `ValidatedGraphPayload` is rejected.

### 9.2 Transaction boundary

Extend the managed Neo4j session abstraction with a tested `execute_write`
boundary. Each `reference_bundle_id` is verified and merged in one Neo4j
transaction callback.

For all relations in the bundle:

1. Require one validated source ID and one complete expected target-ID set for
   the whole `reference_bundle_id`.
2. Group rows by validated `(source_type, target_type)` only for allowlisted
   query generation; never interpolate a raw label or relation name.
3. `MATCH` source and every target by exact label and parameterized ID.
4. Verify source ownership through
   `(sourceDocument)-[:CONTAINS*1..5]->(source)`.
5. For a Document target, verify `target.id = targetDocument.id`.
6. For every descendant target, verify
   `(targetDocument)-[:CONTAINS*1..5]->(target)`.
7. Verify source and target Document IDs differ and match snapshot evidence.
8. Measure ownership path count and distinct owner IDs before any `DISTINCT`:
   one owner/one path is canonical; one owner/multiple paths may continue with a
   divergence count; multiple owners hard-fail.
9. Require exactly the expected unique endpoint pair for every bundle member.
10. Still inside the transaction, inspect every existing outgoing `REFERS_TO`
    from the source whose `reference_bundle_id` equals the current bundle ID and
    collect its distinct target IDs.
11. Compare the existing and expected target sets before any merge:

    ```text
    existing target set is empty
    -> first materialization may proceed

    existing target set equals expected target set
    -> idempotent retry may proceed

    existing target set is non-empty and differs in any way
    -> rollback with bundle_target_conflict_in_graph
    ```

    A non-empty proper subset is an atomic-bundle integrity violation, not a
    repair opportunity.
12. Only after all endpoint, ownership, and conflicting-target checks pass,
    `MERGE` all `REFERS_TO` relations in the same transaction.
13. Consume merge results and require exactly the expected relation-ID and
    target-ID sets.

Any missing endpoint, wrong label, wrong owner, same-document endpoint, zero
result, multiple endpoint result, or incomplete bundle raises a typed error.
The callback must fail before commit and create no edge from that bundle.

Checkpoint/ledger preflight and the transaction check are both mandatory. The
ledger blocks a changed target even when an old edge was later deleted; the
transaction catches an old committed edge when Neo4j succeeded but checkpoint
or ledger persistence previously failed. Neither check replaces the other.

The materializer must never execute:

```cypher
MERGE (source {id: ...})
MERGE (target {id: ...})
```

Only this operation is allowed after endpoint verification:

```cypher
MERGE (source)-[r:REFERS_TO {relation_id: row.relation_id}]->(target)
SET r += row.properties
```

### 9.3 Idempotency, concurrency, and failure windows

The existing deterministic `relation_id` makes materialization at-least-once
and retry-safe.

Failure handling:

```text
Neo4j transaction fails
-> no bundle edge committed
-> append/fsync NOT_COMMITTED attempt when possible
-> CAS checkpoint FAILED with typed reason

Neo4j commits, attempt ledger fsync succeeds, checkpoint CAS fails
-> checkpoint may remain PENDING
-> durable attempt and graph state prove the outcome
-> retry verifies the same target set and MATCHes/MERGEs the same relation IDs
-> no duplicate edge
-> checkpoint becomes WRITTEN

Neo4j commits, attempt ledger write/fsync fails
-> do not advance checkpoint
-> retry inspects existing graph target set in a fresh transaction
-> write a recovered idempotent attempt before checkpoint CAS

Neo4j commit outcome is uncertain
-> do not claim WRITTEN
-> record UNKNOWN when durable logging is possible
-> retry verifies graph state before choosing COMMITTED or NOT_COMMITTED
```

Per-document advisory locking serializes cooperating reconciliation processes.
The checkpoint CAS prevents a stale process from overwriting a newer resolution
after it regains the lock. Neo4j transaction conflict checks remain the final
authority for the current bundle target set.

### 9.4 Orchestration commit protocol

The reconciliation service owns the cross-store ordering; the Neo4j writer does
not write filesystem state:

```text
resolve and validate immutable inputs
-> acquire per-document lock
-> reload checkpoint and durable attempt history
-> verify expected checkpoint hash
-> preflight prior successful target history
-> execute one Neo4j transaction for one atomic bundle
-> classify COMMITTED / NOT_COMMITTED / UNKNOWN
-> append one complete attempt row under O_APPEND
-> flush + fsync ledger (and fsync parent directory on first creation)
-> CAS atomic checkpoint replacement using expected hash
-> fsync replacement and parent directory
-> release lock
```

The Neo4j transaction result returns the observed pre-write target set, final
target set, relation IDs, endpoint owner IDs, and ownership-path divergence
count. The orchestrator persists those returned facts; it must not reconstruct
them from requested rows after commit.

Typed outcome mapping:

```text
source/target missing, label mismatch, retryable graph divergence
-> FAILED

old target observed or durable prior WRITTEN target differs
-> BLOCKED / resolved_target_changed_after_materialization

non-empty partial bundle observed
-> BLOCKED / partial_materialized_bundle_in_graph

multiple Document owners
-> BLOCKED / endpoint_document_ownership_ambiguous_in_graph

checkpoint CAS lost
-> no state overwrite; command fails stale_checkpoint_compare_and_swap

attempt append/fsync failure after graph commit
-> checkpoint not advanced; command fails attempt_ledger_not_durable

commit outcome uncertain
-> checkpoint not advanced; UNKNOWN attempt when possible; verify on retry
```

An attempt row is accepted as audit evidence only when it is schema-valid,
newline-terminated, and its canonical `record_hash` verifies. The writer may
advance the checkpoint only after the ledger-file fsync returns successfully. A
truncated or hash-invalid final JSONL row is never interpreted as `COMMITTED`;
recovery reports ledger corruption and uses Neo4j inspection before any repair
or checkpoint transition.

The writer reports created, matched-existing, failed, and skipped bundle counts.
It must not turn a zero-row write into success.

## 10. CLI and Operational Workflow

### 10.1 `build-reference-registry`

Add a command that accepts an explicit corpus selection:

```bash
uv run python -m src.pipeline.main build-reference-registry \
  --build-id registry-build-v17-20260731-001 \
  --raw-doc-code L59_2020 \
  --raw-doc-code ND01_2021 \
  --raw-doc-code ND47_2021 \
  --raw-doc-code TT01_2021
```

Support either repeated `--raw-doc-code` or an explicit `--manifest` selection,
not both. Manifest mode must fail if any selected document is missing or invalid;
it must never silently publish a partial snapshot.

The command:

- validates every per-document payload through the root gate;
- extracts only accepted structural nodes and canonical `CONTAINS` ownership;
- publishes/reuses immutable content and creates an immutable build receipt;
- prints document/unit/relation counts, collisions, build ID, snapshot hash,
  and provenance hash;
- does not open Neo4j and does not call an LLM.

### 10.2 `reconcile-external-references`

Implement the existing planned command name with separated internal stages:

```bash
# Resolve and report only; no Neo4j mutation
uv run python -m src.pipeline.main reconcile-external-references \
  --build-id registry-build-v17-20260731-001 \
  --raw-doc-code TT01_2021

# Resolve, validate, and materialize
uv run python -m src.pipeline.main reconcile-external-references \
  --build-id registry-build-v17-20260731-001 \
  --raw-doc-code TT01_2021 \
  --apply
```

Default behavior is dry-run. `--apply` is required for Neo4j writes.

The command:

- reloads canonical source and hierarchy for selected source documents;
- reruns deterministic reference detection without calling an LLM;
- loads and verifies the immutable registry snapshot;
- updates resolution checkpoints;
- in dry-run mode, reports intended bundles and graph-independent validation;
- in apply mode, acquires the source-document lock, opens Neo4j, materializes a
  bundle, fsyncs its attempt row, then CAS-updates materialization state;
- touches only explicit external structural references;
- leaves low-confidence semantic reviews and unrelated extraction decisions
  unchanged;
- exits nonzero when any selected bundle fails materialization.

### 10.3 `reference-status`

Add a read-only status command:

```bash
uv run python -m src.pipeline.main reference-status \
  --raw-doc-code TT01_2021
```

Report counts by resolution status, reference scope, self-reference flag,
materialization status, reason code, build ID, snapshot/provenance hashes,
target Document, blocked conflicts, ownership-path divergence, and stale build
usage. Output stable JSON for CI/report tooling.

### 10.4 Full operational order

```text
for every selected document:
  validate-data
  parse
  extract/normalize
  validate-payload
  write                       # structural nodes exist first

build-reference-registry      # content snapshot + immutable build receipt
reconcile-external-references # dry-run
reference-status
reconcile-external-references --apply
reference-status
graph-quality / corpus report
```

## 11. Reporting and Retrieval

### 11.1 Graph quality

Extend graph-quality/corpus reporting with:

```text
external_reference_detected_count
external_reference_resolved_count
external_reference_ambiguous_count
external_reference_unresolved_count
external_reference_pending_count
external_reference_written_count
external_reference_failed_count
external_reference_blocked_count
external_reference_local_count
external_reference_external_count
external_reference_self_count
registry_build_id
registry_snapshot_hash
registry_provenance_hash
registry_graph_divergence_count
ownership_path_divergence_count
unknown_graph_outcome_count
```

Per-document graph payload counts remain payload-local. External relation-only
ledger/reporting must be included explicitly in corpus-level expected graph
counts so the new edges are not reported as unexplained drift.

### 11.2 Retrieval

No traversal-policy or ontology relation change is required. Existing retrieval
already traverses `REFERS_TO`. Add an integration regression proving a query path
can cross Documents through a materialized edge while retaining canonical edge
direction and existing temporal filtering on citable units.

## 12. Files to Add or Modify

### New files

```text
src/pipeline/extraction/corpus_structural_registry.py
src/pipeline/validation/external_reference_validator.py
src/pipeline/pipeline/reference_checkpoint_store.py
src/infrastructure/neo4j/reference_writer.py
src/pipeline/tests/test_corpus_structural_registry.py
src/pipeline/tests/test_external_reference_validator.py
src/pipeline/tests/test_external_reference_reconciliation.py
src/pipeline/tests/test_external_reference_writer.py
tests/integration/test_external_reference_materialization.py
```

### Existing files

```text
src/pipeline/config.py
  add DATA_REGISTRY_DIR

src/shared/ontology/hierarchy.py
  add shared structural-number/key normalization helpers

src/pipeline/extraction/structural_context.py
  retain local StructuralRegistry; remove manifest registry from explicit
  external resolution after migration

src/pipeline/extraction/structural_references.py
  extend target DTO, exact external grammar, snapshot-backed resolver,
  no inferred target IDs

src/pipeline/pipeline/orchestrator.py
  emit checkpoint v2 and keep external refs outside local graph payload

src/pipeline/pipeline/artifact_store.py
  add/reuse atomic content/receipt publication helpers

src/pipeline/persistence/payload_builder.py
  expose a pure validated per-document payload loader; do not admit external
  dangling endpoints into normal payloads

src/pipeline/validation/record_consistency_validator.py
  keep local payload rules; route resolved external candidates to the dedicated
  external validator

src/shared/ontology/validators.py
  add tokened ValidatedRelationBatch and relation-batch validation entry point

src/infrastructure/neo4j/writer.py
  expose managed execute_write lifecycle; keep normal graph writer closed

src/pipeline/main.py
  add registry, reconcile, and status commands

src/pipeline/reports/graph_quality.py
src/pipeline/reports/milestone_a.py
  include external resolution/materialization evidence

src/pipeline/README.md
plans/04_graph_construction_pipeline.md
plans/07_implementation_timeline.md
plans/agent-plan-feats/08_m3_gate4_to_milestone_a_execution_plan.md
plans/README.md
plans/00_architecture_decisions.md
  align implemented commands, evidence flow, and ADR-24 status
```

`plans/legal_ontology.md` stays at v1.7.0 unless implementation makes snapshot
properties mandatory on graph relationships. If that boundary changes, stop and
perform a separate ontology ADR/version bump before coding it.

## 13. Implementation Order

### Phase 0 — Amend the accepted contract before code (completed)

1. Amend ADR-24 to replace ambiguous `snapshot_id` semantics with `build_id`,
   `snapshot_hash`, and `provenance_hash`.
2. Remove `SELF_REFERENCE` from resolution status and define
   `reference_scope` plus resolver-derived `is_self_reference`.
3. Add `BLOCKED`, target-change reconciliation rules, graph-side conflicting
   target verification, ownership-path divergence reporting, and the mandatory
   graph -> ledger fsync -> checkpoint CAS order.
4. Record explicitly that this is a pipeline/checkpoint amendment only;
   ontology v1.7.0 and the `REFERS_TO` relation contract remain unchanged.

### Phase 1 — Pure contracts and registry builder

1. Add structural key normalization helpers and tests.
2. Add disjoint `RegistryDocument`/`RegistryUnit` DTOs and the
   `RegistryEndpoint` union.
3. Add canonical serialization and independent snapshot/provenance hashers.
4. Add immutable content-snapshot and build-receipt loaders/publishers.
5. Refactor pure validated-payload loading out of the CLI.
6. Build snapshot only from root `ValidatedGraphPayload` structural projection.
7. Add duplicate, ownership, path, hash, deterministic-order, and filesystem
   safety tests.

### Phase 2 — Snapshot-backed detection and resolution

1. Extend `StructuralTargetCandidate`.
2. Add exact external grammar in specificity order.
3. Remove trailing document-number scanning and inferred external target IDs.
4. Resolve Document and structural keys through the immutable snapshot.
5. Resolve source and target, including their unique Document ownership, from
   the exact same `snapshot_hash`.
6. Add exact 0/1/>1, scope/self invariants, and no-local-fallback tests.

### Phase 3 — Checkpoint v2

1. Introduce typed resolution/materialization state models.
2. Separate mention fingerprint from snapshot-dependent resolution evidence.
3. Implement per-document advisory locking and canonical checkpoint hashing.
4. Implement append/flush/fsync attempt rows and CAS checkpoint publication.
5. Implement target-change preflight from current state plus durable attempt
   history; do not treat cached current status as proof of `never written`.
6. Reject stale v1 reference checkpoints and regenerate offline.

### Phase 4 — Validation and relation batch

1. Implement snapshot-proof and bundle validator.
2. Add root `ValidatedRelationBatch` token boundary.
3. Reuse canonical `REFERS_TO` provenance and relation-ID functions.
4. Prove normal `ValidatedGraphPayload` behavior remains unchanged.

### Phase 5 — Neo4j materializer

1. Add `execute_write` lifecycle to the managed session.
2. Implement label-allowlisted source/target verification queries.
3. Handle target Document identity separately from descendant ownership paths.
4. Measure ownership path multiplicity before deduplication; warn for one owner
   with multiple paths and hard-fail multiple owners.
5. Inside the same transaction, compare existing and expected target sets for
   `reference_bundle_id` before any merge.
6. Verify all bundle members before any bundle merge.
7. Consume exact result/target sets and raise typed failures.
8. Implement commit -> attempt append/fsync -> checkpoint CAS/fsync ordering.
9. Test idempotent retry, target conflict, uncertain commit, ledger failure, and
   checkpoint-after-commit failure.

### Phase 6 — CLI, reports, and docs

1. Add `build-reference-registry`.
2. Add dry-run/apply `reconcile-external-references`.
3. Add `reference-status`.
4. Add reporting metrics and corpus evidence.
5. Replace the stale Plan 08 pseudo-command contract with the implemented CLI.
6. Update ADR-24 implementation status only after code and integration evidence
   pass.

### Phase 7 — Curated migration

1. Complete validated writes for all explicitly selected corpus Documents.
2. Archive old reference checkpoints.
3. Build and record the first build ID, snapshot hash, and provenance hash.
4. Run external reconciliation dry-run and review ambiguous/unresolved reasons.
5. Apply materialization.
6. Run the same apply command again and prove zero duplicate edges and stable
   relation IDs.
7. Capture corpus graph snapshots and status reports.

## 14. Test Matrix

### Registry snapshot

- same accepted content in different input order produces the same hash;
- structural change produces a different hash;
- timestamp and build ID do not alter either stable hash;
- source content change with unchanged accepted hierarchy preserves
  `snapshot_hash` but changes `provenance_hash`;
- parser/validator version change preserves `snapshot_hash` when content is
  unchanged but changes `provenance_hash`;
- changing only `raw_doc_code` preserves both stable hashes;
- two builds may have different build IDs with identical snapshot/provenance
  hashes;
- `RegistryDocument` exists only in `documents.jsonl`, never `units.jsonl`;
- structural-key indexes exclude Document endpoints;
- manifest-only Document is not registered;
- raw/unvalidated payload is rejected;
- direct `Document -> Article` is accepted;
- `Document -> Chapter -> Article` is accepted;
- `Document -> Chapter -> Section -> Article` is accepted;
- Article/Clause/Point ownership is recovered correctly;
- Document target is represented without a parent path;
- duplicate node ID, local structural key, parent, or owner hard-fails;
- duplicate Document number resolves as ambiguous instead of overwriting;
- `d` and `đ` remain distinct;
- existing identical snapshot publication is idempotent;
- existing content is reused without mutating its prior build receipts;
- same build ID with different receipt or hashes is rejected;
- path traversal and symlink escape are rejected;
- partial snapshot publication never advances the current pointer.

### Resolver

- external Document, Chapter, Section, Article, Clause, and Point resolve;
- missing target Document is `UNRESOLVED`;
- duplicate target Document identity is `AMBIGUOUS`;
- missing target unit is `UNRESOLVED`;
- wrong Section/Clause/Point parent chain is unresolved;
- external expression never falls back to the current Document;
- explicit same-Document number does not enter external materialization;
- exact offsets and citation text survive normalization;
- a trailing number outside the citation expression is not captured;
- specific Point/Clause/Article matches suppress nested generic matches;
- deferred compound grammar does not create a partial misleading edge;
- broad text creates no candidate.

### Checkpoint state

- resolved external reference starts `PENDING`;
- status enum is only `UNRESOLVED|RESOLVED|AMBIGUOUS`;
- self reference is `RESOLVED + LOCAL + is_self_reference=true`;
- same-document different-target reference is `RESOLVED + LOCAL + false`;
- unresolved explicit external reference retains scope `EXTERNAL` when the
  cited external Document identity is syntactically known;
- unresolved, ambiguous, self, and local references are `NOT_APPLICABLE` to the
  external materializer;
- successful write becomes `WRITTEN`;
- missing graph target remains resolution `RESOLVED` but materialization
  `FAILED`;
- retry can transition `FAILED -> WRITTEN`;
- same snapshot/result preserves stable citation provenance;
- new build evidence is recorded without changing relation identity;
- target change before any durable/graph-observed write replaces pending state
  after audit;
- target change after any prior write becomes `BLOCKED` and creates/deletes no
  edge;
- `ever_written` is recovered from durable attempts and graph inspection, not
  only current checkpoint status;
- malformed, duplicate, or legacy checkpoint rows are rejected;
- advisory lock serializes cooperating same-document reconciliations;
- stale expected checkpoint hash makes CAS fail without lost update;
- atomic file replacement preserves the prior checkpoint on failure;
- graph commit followed by ledger fsync failure does not mark checkpoint
  `WRITTEN`;
- durable attempt followed by CAS failure remains recoverable.

### Validation

- invalid source/target labels fail;
- source and target in the same Document fail external validation;
- build receipt, provenance hash, or snapshot hash mismatch fails;
- source or target absent from snapshot fails;
- source and target evidence from different snapshot hashes fails;
- source/target ownership mismatch fails;
- incomplete multi-target bundle fails atomically;
- malformed relation ID or target count fails;
- required ENTITY_LINKING provenance is enforced;
- confidence and fake LLM provenance are not required or invented.

### Writer unit tests

- raw relation batch is rejected;
- only root-tokened `ValidatedRelationBatch` is accepted;
- source and target use `MATCH`, never `MERGE`;
- relation uses deterministic `MERGE`;
- IDs/properties are parameterized;
- labels come only from allowlists;
- source ownership path is verified;
- Document target uses identity equality;
- descendant target uses canonical `CONTAINS` ownership;
- one owner through multiple paths records divergence before endpoint
  deduplication;
- multiple Document owners fail instead of being hidden by `DISTINCT`;
- existing empty target set permits first write;
- existing target set equal to expected set permits idempotent retry;
- existing non-empty different target set rolls back before relation merge;
- existing proper subset of expected bundle is an integrity failure;
- zero result raises and is not reported as success;
- multiple result raises integrity failure;
- wrong label, owner, or same Document rolls back;
- one invalid member rolls back the whole bundle;
- rerun matches the existing relation without duplication;
- session/transaction resources close on success and failure.

### Neo4j integration

- ingest two structural Documents, resolve one external Point, and create one
  canonical cross-document edge;
- materialize targets of each allowed type, including Document and Section;
- remove target before write and prove no fake node or edge is created;
- corrupt ownership path and prove materialization fails;
- run twice and prove stable relation count and IDs;
- seed an old bundle target and prove a changed target is blocked in the same
  Neo4j transaction;
- commit graph while suppressing ledger/checkpoint persistence and prove retry
  discovers the existing target set;
- persist a successful attempt while failing checkpoint CAS and prove recovery;
- return uncertain commit outcome and prove no false `WRITTEN` state;
- simulate checkpoint failure after commit and prove retry recovery;
- retrieval traverses the edge in canonical direction and preserves temporal
  validation;
- test cleanup touches only the integration namespace.

### CLI

- explicit document selection is deterministic;
- manifest selection fails on any missing/invalid selected document;
- registry build does not open Neo4j or call an LLM;
- reconcile dry-run performs no Neo4j mutation;
- reconcile apply does not call an LLM;
- unrelated review/rejected records remain byte-stable;
- status JSON ordering and counts are deterministic;
- partial bundle failure returns nonzero;
- secrets and raw provider payloads are absent from logs.

### Persistence and concurrency

- graph commit is followed by attempt append/flush/fsync before checkpoint CAS;
- checkpoint write cannot report `WRITTEN` when durable attempt logging fails;
- first creation of the attempt ledger fsyncs the parent directory;
- checkpoint atomic replacement fsyncs the replacement file and parent
  directory;
- two same-document reconciliation processes serialize through the advisory
  lock;
- a stale expected checkpoint hash loses CAS without modifying the current
  checkpoint;
- retry after crash between graph commit and ledger append recovers from graph
  state;
- retry after crash between ledger fsync and checkpoint CAS recovers from the
  durable attempt;
- graph outcome `UNKNOWN` never becomes `WRITTEN` without subsequent graph
  verification;
- truncated or hash-invalid final attempt row never proves `COMMITTED` and
  triggers typed ledger-corruption recovery.

## 15. Acceptance Criteria

Implementation is accepted only when all are true:

```text
AC-01 Registry content is built exclusively from root-validated accepted
      structural payloads.
AC-02 RegistryDocument is the only Document endpoint representation;
      RegistryUnit contains descendants only.
AC-03 snapshot_hash deterministically identifies canonical registry content and
      is verified on every load.
AC-04 build_id identifies an immutable build receipt; provenance_hash covers
      stable source/projection and parser/validator evidence independently of
      snapshot_hash.
AC-05 Manifest membership, raw_doc_code, or an inferred canonical ID can never
      produce RESOLVED.
AC-06 Document and structural lookup follow exact 0/1/>1 semantics.
AC-07 Source and target endpoints and their unique owners exist in the same
      verified snapshot_hash before external resolution succeeds.
AC-08 Resolution status is UNRESOLVED|RESOLVED|AMBIGUOUS; scope and
      is_self_reference are independent resolver-derived fields.
AC-09 Resolution and materialization states are stored independently, including
      BLOCKED for target-change reconciliation conflicts.
AC-10 Normal per-document payload validation remains closed to dangling external
      endpoints.
AC-11 Relation-only writer accepts only a root-validated relation batch.
AC-12 Neo4j transaction verifies exact labels, ownership, and owner/path
      cardinality before relation creation.
AC-13 The same Neo4j transaction compares existing and expected target sets for
      reference_bundle_id before any MERGE.
AC-14 Any non-empty unequal graph target set rolls back; an old target is never
      silently deleted or accompanied by a new target.
AC-15 Writer never MERGEs source or target nodes.
AC-16 Zero/multiple endpoint or multiple-owner result is a typed failure, not
      success; one owner through multiple paths emits divergence evidence.
AC-17 Multi-target bundles remain atomic.
AC-18 Reconciliation is idempotent by deterministic relation_id and exact bundle
      target-set equality.
AC-19 A target change is allowed only when neither durable attempts nor Neo4j
      prove any prior materialization; otherwise it becomes BLOCKED.
AC-20 Successful durability order is Neo4j commit -> attempt append/fsync ->
      checkpoint CAS/fsync.
AC-21 Advisory lock plus checkpoint-hash CAS prevents cooperating concurrency
      and stale checkpoint overwrite.
AC-22 Neo4j/ledger/checkpoint failure windows and UNKNOWN commit outcomes are
      recoverable without false WRITTEN state.
AC-23 No ontology node/relation or denormalized document_id is introduced.
AC-24 Existing local structural reference and retrieval tests remain green.
AC-25 Full Python fast suite, targeted integration suite, Ruff, format check,
      and git diff check pass.
AC-26 ADR-24 is amended before code and marked implemented only after migration
      evidence exists.
```

## 16. Verification Commands

During implementation, run targeted tests after each phase, then:

```bash
uv run pytest -q \
  src/pipeline/tests/test_corpus_structural_registry.py \
  src/pipeline/tests/test_structural_references.py \
  src/pipeline/tests/test_external_reference_validator.py \
  src/pipeline/tests/test_external_reference_reconciliation.py \
  src/pipeline/tests/test_external_reference_writer.py

uv run pytest -q

uv run ruff check <changed-python-files>
uv run ruff format --check <changed-python-files>
git diff --check
```

Run Neo4j integration tests only against the disposable integration database
and existing namespace/URI guards:

```bash
uv run pytest -q -m integration \
  tests/integration/test_external_reference_materialization.py
```

Do not weaken or skip tests because a local dependency or integration service is
unavailable; report the exact blocker and preserve the targeted evidence.

## 17. Remaining Deferred Work

- compound/shared-trailing-document AST expansion;
- LLM/entity-linking reconciliation for genuinely ambiguous semantic citations;
- automatic deletion of an old edge when a newer snapshot resolves the same
  mention to a different target;
- cryptographic signing/authentication of registry snapshots;
- distributed transactions or exactly-once delivery across storage systems;
- relationship-level mandatory snapshot provenance requiring ontology v1.8+;
- Document ownership denormalization on structural nodes;
- a web UI for unresolved/ambiguous/materialization-failure review.
