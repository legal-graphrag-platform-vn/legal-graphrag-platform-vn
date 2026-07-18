# Graph Path Direction, Temporal and Reasoning Safety Plan

> Plan status: IMPLEMENTED, TARGETED VERIFICATION PASSED
> Implementation commit: `e4faa40`
> Retrieval contract: `retrieval-runtime-v2`
> Canonical ontology: `plans/legal_ontology.md` v1.5.1

## 0. Current Status

```text
Gate 7: OPEN
M3-B13: OPEN
Milestone A: NOT PASSED
Retrieval runtime v2: IMPLEMENTED
Backend retrieval integration: IMPLEMENTED
Answer generation: IMPLEMENTED
Graph-path direction/temporal safety: IMPLEMENTED
Multi-hop retrieval: PROTOTYPE
Multi-hop answer generation: FAIL-CLOSED by default
Official retrieval/answer evaluation after v2: NOT STARTED
Milestone B acceptance: NOT STARTED
```

This implementation does not close Gate 7, M3-B13, Milestone A, or Milestone B.
Evidence produced under `retrieval-runtime-v1` must be rerun before it is used as
official runtime-v2 evidence.

## 1. Implemented Contract

`GraphPath` no longer uses parallel `nodes`, `relations`, and `relation_ids`
arrays. The runtime now uses:

```python
class GraphNodeRef(BaseModel):
    node_id: str
    labels: tuple[str, ...]
    effective_from: date | None
    effective_to: date | None
    legal_status: str | None
    citable_unit_id: str | None

class GraphEdge(BaseModel):
    relation_id: str
    relation_type: str
    source_id: str
    target_id: str
    effective_from: date | None
    effective_to: date | None

class GraphPath(BaseModel):
    nodes: tuple[GraphNodeRef, ...]  # traversal order
    edges: tuple[GraphEdge, ...]     # canonical Neo4j direction
    path_description: str
```

Invariants:

- each edge connects two adjacent traversal nodes;
- edge source/target always preserve canonical Neo4j direction;
- incoming traversal renders a reverse traversal arrow without reversing the
  relationship meaning;
- relation IDs are required, canonical, and unique within a path;
- temporal relations require `effective_from`;
- Point nodes remain in explanation paths and resolve citation eligibility to
  their parent Clause;
- semantic path nodes do not automatically become legal citation evidence.

## 2. Temporal Boundary

When `query_date` exists, retrieval validates both nodes and relationships:

```text
effective_from <= query_date
effective_to is null OR query_date < effective_to
```

Temporal-invalid paths are excluded before `RetrievalContext` construction.
They contribute only to aggregate diagnostics. Malformed path data raises
`RetrievalOutputError`; it is never downgraded to an empty or valid path.

When no `query_date` exists, point-in-time filtering is not applied, but shape,
identity, canonical relation type, and required temporal properties are still
validated.

## 3. Generation Safety

`EvidenceItem.is_sufficient` was replaced by `is_eligible`:

```text
eligible = valid evidence allowed to enter projection
sufficient = intent-specific decision over the complete projected evidence set
```

Generation rules:

- hierarchy requires a verified canonical `CONTAINS` edge;
- comparison requires a shared non-null `version_family_id` or a verified
  `AMENDS`/`REPLACES` path;
- multi-hop requires a trusted `GraphReasoningRequirement`, minimum edge count,
  required relation types, and every citable intermediate legal unit;
- public `force_intent=MULTI_HOP` does not create a trusted graph requirement;
- unresolved multi-hop returns `MULTI_HOP_REQUIREMENT_UNRESOLVED`, with provider
  call count zero;
- only projected legal evidence enters the citation registry.

## 4. Verification

Implemented regression coverage includes:

- incoming traversal preserves canonical edge direction;
- direction-aware deterministic path rendering;
- future and expired relationships are rejected;
- malformed temporal values and missing temporal relation dates fail;
- disconnected edges fail shape validation;
- multi-hop without a trusted requirement fails before provider execution;
- incomplete intermediate evidence fails closed;
- comparison does not group unrelated null version families;
- backend and evaluation mappings use runtime-v2 structured paths.

Latest implementation verification:

```text
Targeted graph/retrieval/generation/backend tests: PASS (34)
Project suite excluding integration and one sandbox-specific cleanup hang:
  PASS (377), deselected (9)
Ruff check: PASS
Ruff format check: PASS
git diff --check: PASS, with existing unreadable Neo4j import-path warning
Disposable Neo4j integration after runtime-v2 migration: NOT RUN
Real-provider answer smoke after runtime-v2 migration: NOT RUN
```

## 5. Remaining Work

1. Run read-only disposable Neo4j integration tests against port 7688 and prove
   the structured Cypher projection works with the live Neo4j version.
2. Regenerate retrieval evaluation and artifact hashes under
   `retrieval-runtime-v2`.
3. Re-run real-provider answer smoke with runtime-v2 contexts.
4. Keep general multi-hop answer generation closed until a trusted query
   decomposition/requirement producer is designed and evaluated.
5. Resume four-document Gate 7 corpus work separately; only that work can close
   M3-B13 and complete Milestone A.

## 6. Deferred

- general multi-hop query decomposition;
- branching/partial-amendment temporal DAG resolution;
- corpus-complete current-validity answers;
- claim-level semantic entailment scoring;
- expanded legal-status reasoning after amendment corpus coverage exists.
