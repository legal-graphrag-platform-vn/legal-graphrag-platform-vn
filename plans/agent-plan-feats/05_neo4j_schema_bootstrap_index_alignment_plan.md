# Detailed Implementation Plan — Neo4j Schema Bootstrap Index Alignment

> Target file: `infra/neo4j/init/01_schema_init.cypher`  
> Canonical ontology: `plans/legal_ontology.md` v1.5.0
> Status: v1.4 bootstrap indexes implemented; ADR-20 vector migration to 1024 pending

---

## 1. Summary

This plan updates the Neo4j bootstrap script without changing the ontology contract.

The current schema bootstrap is already valid for M3, but it can be aligned more tightly with the active write contract:

```text
idempotent bootstrap
  -> uniqueness constraints
  -> lookup indexes
  -> temporal indexes
  -> full-text indexes
  -> vector indexes
  -> semantic lookup indexes
  -> relation_id indexes
```

The schema file must remain bootstrap-only for Neo4j Community Edition. It must not attempt to enforce property existence, relation endpoint constraints, or ontology logic that belongs in Python validation.

---

## 2. Current Source Boundary

Use these files as the contract anchors:

| Area | Current source | Role |
|---|---|---|
| Ontology contract | `plans/legal_ontology.md` | Canonical labels, relations, required properties, validation boundaries |
| Schema bootstrap | `infra/neo4j/init/01_schema_init.cypher` | Community Edition constraints and indexes only |
| Ontology constants | `src/shared/ontology/contract.py` | Single source of truth for labels, relations, and required properties |
| Write-path validation | `src/shared/ontology/validators.py` | Required fields, relation rules, and payload validation before MERGE |
| Payload consistency | `src/shared/ontology/payload_consistency_validator.py` | Duplicate IDs, relation identity, dangling endpoints, structural integrity |
| Neo4j writer | `src/infrastructure/neo4j/writer.py` | Guarded MERGE path using validated payloads |

Implementation rule: if the schema change would need ontology knowledge, it does not belong in Neo4j bootstrap unless it is a pure index/constraint already supported by Community Edition and the current write contract.

---

## 3. Required Changes

### 3.1 Make the bootstrap comment explicit about idempotency

The current header comment says the script should be run once. That is misleading because every statement already uses `IF NOT EXISTS`.

Required update:

- Replace “run once only” wording with an idempotent bootstrap note.
- Keep the execution command example.
- Make clear that the script can be rerun safely after Neo4j restart or container recreation.

This is documentation-only, but it prevents operational confusion.

### 3.2 Add semantic lookup indexes

The ontology already defines `LegalConcept`, `LegalSubject`, and `LegalAction` as Phase 1 persisted semantic labels.

Add name-based lookup indexes for semantic node resolution and graph-quality/debug workflows:

```cypher
CREATE INDEX lc_name IF NOT EXISTS FOR (c:LegalConcept) ON (c.name);
CREATE INDEX ls_name IF NOT EXISTS FOR (s:LegalSubject) ON (s.name);
CREATE INDEX la_name IF NOT EXISTS FOR (a:LegalAction) ON (a.name);
```

Why this is needed:

- entity normalization can resolve semantic duplicates faster
- graph-quality checks can inspect semantic nodes by name
- manual debugging becomes easier without scanning uniqueness-only indexes

Do not add extra semantic labels beyond Phase 1 scope.

### 3.3 Add `relation_id` indexes for writer idempotency

The M3 write contract uses deterministic `relation_id` values for relationship identity. Neo4j Community Edition cannot enforce relationship uniqueness, so the Python validator remains the authority, but bootstrap should provide supporting indexes.

Add relationship-property indexes for canonical relations that are written in M3:

```cypher
CREATE INDEX issued_by_relation_id IF NOT EXISTS FOR ()-[r:ISSUED_BY]-() ON (r.relation_id);
CREATE INDEX contains_relation_id IF NOT EXISTS FOR ()-[r:CONTAINS]-() ON (r.relation_id);
CREATE INDEX guides_relation_id IF NOT EXISTS FOR ()-[r:GUIDES]-() ON (r.relation_id);
CREATE INDEX refers_to_relation_id IF NOT EXISTS FOR ()-[r:REFERS_TO]-() ON (r.relation_id);
CREATE INDEX amends_relation_id IF NOT EXISTS FOR ()-[r:AMENDS]-() ON (r.relation_id);
CREATE INDEX repeals_relation_id IF NOT EXISTS FOR ()-[r:REPEALS]-() ON (r.relation_id);
CREATE INDEX replaces_relation_id IF NOT EXISTS FOR ()-[r:REPLACES]-() ON (r.relation_id);
CREATE INDEX defines_relation_id IF NOT EXISTS FOR ()-[r:DEFINES]-() ON (r.relation_id);
CREATE INDEX regulates_relation_id IF NOT EXISTS FOR ()-[r:REGULATES]-() ON (r.relation_id);
CREATE INDEX requires_relation_id IF NOT EXISTS FOR ()-[r:REQUIRES]-() ON (r.relation_id);
```

Rules:

- These are indexes only, not uniqueness constraints.
- Python validation still rejects missing or malformed `relation_id`.
- The schema must not introduce any relation alias indexes.

### 3.4 Keep the full-text index contract simple

The current full-text index is acceptable for M3 as long as the retrieval code keeps using `content_raw`.

No mandatory change is required here.

Optional cleanup if the team wants stricter label-property matching:

- split `Article|Clause` and `Point` into separate full-text indexes
- keep `Point` indexed only on `content_raw`

This is optional and should not block the bootstrap patch.

### 3.5 Add a temporal-property type note

The schema and writer should stay consistent on temporal fields.

Add a short comment note clarifying that:

- `effective_from` and `effective_to` should be stored consistently by the writer
- retrieval queries must use the same temporal representation

This is a documentation guard, not a schema enforcement rule.

Do not add property existence constraints or type constraints for temporal fields in Community Edition bootstrap.

---

## 4. Constraints and Non-Goals

### 4.1 Must keep in bootstrap

- uniqueness constraints
- lookup indexes
- temporal indexes
- full-text index
- vector indexes
- semantic lookup indexes
- relation_id indexes

### 4.2 Must not move into bootstrap

- property existence constraints for required ontology fields
- relation endpoint constraints
- GUIDES whitelist enforcement
- runtime reasoning labels
- legacy relation alias acceptance
- point-level temporal enforcement
- embedding generation logic

### 4.3 Must not change

- canonical ontology in `plans/legal_ontology.md`
- write-time validation in Python
- payload consistency validation in Python
- guarded writer boundary

---

## 5. Implementation Steps

### Step 1: Update header comment

- Rewrite the top comment to say the file is idempotent.
- Keep the source-of-truth note pointed at `plans/legal_ontology.md`.
- Keep the operational command example intact.

### Step 2: Add semantic name indexes

- Insert the `LegalConcept`, `LegalSubject`, and `LegalAction` name indexes in the lookup index section.
- Keep naming consistent with existing index style.

### Step 3: Add relation_id indexes

- Insert a dedicated relation identity index section after temporal indexes.
- Add indexes for the canonical Phase 1 relation set used by M3 writes.
- Keep the section comment explicit that this supports idempotent writer semantics in Python.

### Step 4: Add temporal comment note

- Add a brief comment near temporal indexes or writer-related comments.
- Clarify the storage representation must match writer and retrieval expectations.

### Step 5: Verify bootstrap stays bootstrap-only

- Ensure no ontology logic is introduced into the Cypher file.
- Ensure no legacy aliases or runtime labels are added.

### Step 6: Apply ADR-20 vector dimension migration

- Change `article_embedding` and `clause_embedding` to 1024 dimensions.
- Drop/recreate existing 768-dimensional vector indexes on disposable/dev databases.
- Re-embed every Article and Clause after index recreation.
- Add a parity test between ontology/config dimension and schema bootstrap.
- Keep BKAI/768 only as an explicit baseline using a matching separate index run.

---

## 6. Verification

After the patch, verify:

1. `infra/neo4j/init/01_schema_init.cypher` still reads as bootstrap-only.
2. The file contains the new semantic name indexes.
3. The file contains the new `relation_id` indexes.
4. No property-existence constraints were added.
5. No legacy alias names were introduced.
6. `SHOW CONSTRAINTS` and `SHOW INDEXES` remain idempotent when the script is rerun.
7. Root and pipeline write paths still rely on Python validation for required properties and relation identity.

Suggested manual verification commands:

```cypher
SHOW CONSTRAINTS;
SHOW INDEXES YIELD name, type, state, labelsOrTypes, properties RETURN name, type, state, labelsOrTypes, properties ORDER BY type, name;
SHOW VECTOR INDEXES;
```

Expected outcomes:

- semantic lookup indexes exist for `LegalConcept`, `LegalSubject`, and `LegalAction`
- `relation_id` indexes exist for the canonical M3 relations
- vector indexes for `Article.embedding` and `Clause.embedding` remain online
- vector indexes use the current ontology dimension: BGE-M3/1024

---

## 7. Exit Criteria

This plan is complete when:

- the bootstrap comment matches idempotent behavior
- semantic lookup indexes are present
- `relation_id` indexes are present
- Article and Clause vector indexes use 1024 dimensions under ADR-20
- ontology/config/schema dimension parity test passes
- schema bootstrap still avoids runtime ontology enforcement
- the guarded M3 write boundary remains unchanged
