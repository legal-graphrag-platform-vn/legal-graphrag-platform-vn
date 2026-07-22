# Query-specific graph planning — Task 0 preflight

> Captured: 2026-07-22T09:46:05.9990324Z  
> Result: **FAILED — stop before Task 1**  
> Database: `neo4j`, Neo4j Community 5.26.28, `bolt://localhost:7688`  
> Scope: `ldn_2020`, ontology v1.6.0

## Decision

The graph contains every reviewed gold path, so missing graph connectivity is
not the immediate blocker. The proposed V1 plan shape is nevertheless
underconstrained for three of the four linear cases. In addition, all seven
`REFERS_TO` relationships in the scoped graph are stale against the ontology
v1.6.0 provenance contract.

Task 0 therefore does not pass. Per the execution-plan stop condition, Task 1
must not begin until the technical design is amended and the stale graph
artifacts are rebuilt or migrated.

## Pinned evidence

| Field | Value |
|---|---|
| Git commit | `53794883d8c87be1c202dd054ce772b0f235a537` |
| Evaluation dataset SHA-256 | `d264a3cd67a36979ec4a554527170cd8e0e74b928e6d6821b23a13949b9a1f2a` |
| Read-only projection SHA-256 | `e4b685e22e51aac3d5891937b944ed86637e03e9746ea0c4dcb8e0dd0eab541a` |
| Projection rerun | Same hash and 3,172 output lines |
| Scoped nodes | 1,126 |
| Scoped relationships | 1,132 |
| `CONTAINS` | 1,125 |
| `REFERS_TO` | 7 |

The projection hash covers deterministic scoped node ID/label rows, relation
topology/ID rows, counts, and provenance diagnostics. The normal
payload-to-graph snapshot command could not run because the validated payload
itself fails the current ontology v1.6.0 validator.

## Gold-case results

| Case | Gold path exists | Targets returned by current plan shape | Exact denotation | Evidence v1.6 complete | Result |
|---|---:|---|---:|---:|---|
| `multi_hop_01` | Yes | `art41_cl1`, `art41_cl2`, `art41_cl3` | No | No | `PLAN_UNDERCONSTRAINED` |
| `multi_hop_02` | Yes | `art145_cl1` | Yes | No | stale `REFERS_TO` provenance |
| `multi_hop_03` | Yes | `art49_cl1`, `art49_cl2`, `art49_cl3` | No | No | `PLAN_UNDERCONSTRAINED` |
| `multi_hop_04` | Yes | `art52_cl1`, `art52_cl2`, `art52_cl3` | No | No | `PLAN_UNDERCONSTRAINED` |
| `multi_hop_05` | Not evaluated | Branching one-hop | N/A | N/A | `OUT_OF_SCOPE_PLAN_SHAPE` |

All twelve legal units on the reviewed paths exist, contain non-empty legal
text, have `effective_from=2021-01-01`, `legal_status=ACTIVE`, and resolve to
Document `ldn_2020` / `59/2020/QH14`.

### Why cases 01, 03, and 04 fail

Their plan shape is only:

```text
Clause -> REFERS_TO -> Article -> CONTAINS -> Clause
```

That constraint correctly selects the referenced Article but necessarily
selects every Clause inside it. The query asks which Clause contains the
relevant rule, while `PathStepConstraint` currently expresses only relation,
direction, and next label. It has no target mention or other constraint capable
of distinguishing the reviewed gold Clause.

Allowing the answer LLM to choose among those targets would violate exact-plan
execution and would turn an ambiguous plan into an apparently successful one.

## ADR-23 amended-shape probe

The read-only probe was rerun with manually bound gold anchor and target IDs,
as required for the amended QG-0 boundary. All four linear cases returned
exactly one topology:

| Case | Gold-bound topology count | Result |
|---|---:|---|
| `multi_hop_01` | 1 | Pass |
| `multi_hop_02` | 1 | Pass |
| `multi_hop_03` | 1 | Pass |
| `multi_hop_04` | 1 | Pass |

This demonstrates that independent target binding repairs plan expressivity for
the reviewed cases. It does not demonstrate that a target linker can infer the
correct target from natural language; target binding accuracy remains a
separate calibrated metric. Task 0 remains failed because the graph evidence is
still stale against ontology v1.6.0.

## Graph viability

The graph is not empty or devoid of multi-hop structure. It contains these
simple-path counts within `ldn_2020`:

| Depth | Relation sequence | Count |
|---:|---|---:|
| 2 | `CONTAINS -> CONTAINS` | 1,937 |
| 2 | `CONTAINS -> REFERS_TO` | 7 |
| 2 | `REFERS_TO -> CONTAINS` | 13 |
| 2 | `REFERS_TO -> REFERS_TO` | 1 |
| 3 | `CONTAINS -> CONTAINS -> CONTAINS` | 1,719 |
| 3 | `CONTAINS -> CONTAINS -> REFERS_TO` | 7 |
| 3 | `CONTAINS -> REFERS_TO -> CONTAINS` | 13 |
| 3 | `CONTAINS -> REFERS_TO -> REFERS_TO` | 1 |
| 3 | `REFERS_TO -> CONTAINS -> CONTAINS` | 22 |
| 3 | `REFERS_TO -> CONTAINS -> REFERS_TO` | 2 |

These counts demonstrate connectivity only; they are not accuracy or
generalization claims. The reviewed corpus is still a single document.

## Ontology v1.6.0 artifact blocker

All seven scoped `REFERS_TO` relationships have `citation_text` and
`citation_type`, but all seven lack:

- `extraction_method`;
- `reference_bundle_id`;
- `reference_target_count`.

Consequently, the pipeline `graph-snapshot` command rejected the local
validated payload with the same ontology errors. This matches the repository
status warning that pilot v1.5.1 evidence is stale after ontology v1.6.0.

## Required next work

1. Review and accept ADR-23, which adds independent target binding. Its
   gold-bound expressivity probe passes 4/4 reviewed linear cases.
2. Rebuild or migrate the `REFERS_TO` artifacts to the ontology v1.6.0
   resolver-first provenance contract.
3. Rerun this preflight on the rebuilt pinned snapshot.
4. Start Task 1 only if all in-scope gold cases have exact denotation and
   citable evidence completeness.

No Neo4j write, reset, or schema mutation was performed during this preflight.
