# Review Record: L59_2020 Retrieval 30-Query Dataset

## Status

```text
Dataset: APPROVED
Human sign-off: COMPLETE by lamdx4 at 2026-07-13T22:00:00+07:00
Official evaluation: NOT STARTED
Gate 7 / M3-B13: OPEN
Milestone A: NOT PASSED
```

Review source:
`configs/evaluation/retrieval_pilot_l59_2020.json`.

Artifact verification:
`results/retrieval/L59_2020_30q_artifact_verification.json`.

The artifact verifier reads the active accepted extraction export and canonical
hierarchy, then queries the scoped capability snapshot from the disposable
Neo4j runtime. The current verification status is `PASS` with input hashes
recorded in the report. The five graph cases require seven distinct accepted
`REFERS_TO` edges because `multi_hop_02` contains two sequential references and
`multi_hop_05` contains two branches.

The approved dataset uses only the local canonical hierarchy under
`data/processed/L59_2020/hierarchy.json`. It does not use web search or fixture
data as legal gold.

## Review Rules

For every case, verify:

1. The query expresses the declared intent without relying on `force_intent`.
2. Every `gold_relevance.unit_id` directly or materially supports the query.
3. Relevance grade `3` means direct legal basis, `2` means material supporting
   basis, and `1` means useful secondary context. Article and descendant units
   are automatically grouped under one structural legal-basis group, so parent
   and Clause hits cannot inflate metrics. The grouped grade is the highest
   grade among units actually returned; returning only a grade-2 Article does
   not inherit the grade-3 judgement of a missing Clause.
4. An unsupported case has no fabricated gold and names the exact unavailable
   capability.
5. The wording is natural Vietnamese and does not reveal the expected ID.

The legal gold and capability expectations were confirmed during human review.
The dataset-level review and all case-level reviews now use:

```json
{
  "reviewer": "lamdx4",
  "status": "approved",
  "reviewed_at": "2026-07-13T22:00:00+07:00"
}
```

Any dataset edit after `source_commit` requires a new source commit and a full
evaluation rerun.

## Case Matrix

| ID | Intent | Expected | Capability | Gold units |
|---|---|---|---|---|
| `factual_01` | factual | supported | `hybrid_seed_and_semantic_graph` | `art7_cl1`, `art7` |
| `factual_02` | factual | supported | `hybrid_seed_and_semantic_graph` | `art8_cl3`, `art8` |
| `factual_03` | factual | supported | `hybrid_seed_and_semantic_graph` | `art17_cl2`, `art17` |
| `factual_04` | factual | supported | `hybrid_seed_and_semantic_graph` | `art10_cl1`, `art10` |
| `factual_05` | factual | supported | `hybrid_seed_and_semantic_graph` | `art207_cl1`, `art207_cl2`, `art207` |
| `definition_01` | definition | supported | `lexical_definition` | `art4_cl3`, `art4` |
| `definition_02` | definition | supported | `lexical_definition` | `art4_cl34`, `art4` |
| `definition_03` | definition | supported | `lexical_definition` | `art4_cl10`, `art4` |
| `definition_04` | definition | supported | `lexical_definition` | `art4_cl18`, `art4` |
| `definition_05` | definition | supported | `lexical_definition` | `art12_cl1`, `art12` |
| `multi_hop_01` | multi_hop | supported | `semantic_multi_hop_graph` | `art38_cl1` -> `REFERS_TO` -> `art41` -> `CONTAINS` -> `art41_cl2` |
| `multi_hop_02` | multi_hop | supported | `semantic_multi_hop_graph` | `art145_cl3` -> `REFERS_TO` -> `art145_cl2` -> `REFERS_TO` -> `art145_cl1` |
| `multi_hop_03` | multi_hop | supported | `semantic_multi_hop_graph` | `art57_cl1` -> `REFERS_TO` -> `art49` -> `CONTAINS` -> `art49_cl2` |
| `multi_hop_04` | multi_hop | supported | `semantic_multi_hop_graph` | `art68_cl2` -> `REFERS_TO` -> `art52` -> `CONTAINS` -> `art52_cl1` |
| `multi_hop_05` | multi_hop | supported | `semantic_multi_hop_graph` | branching one-hop: `art52_cl1` -> `REFERS_TO` -> `art53_cl6/cl7` |
| `validity_01`, `02`, `04` | validity | unsupported | `corpus_complete_current_validity` | none; do not fabricate |
| `validity_03`, `05` | validity | supported | `scoped_temporal_metadata` | `art217`, `art30` |
| `hierarchy_01`, `02` | hierarchy | unsupported | `guides_relations` | none; do not fabricate |
| `hierarchy_03`-`hierarchy_05` | hierarchy | supported | `structural_hierarchy` | `art17`, `art30` parent/child units |
| `comparison_01`-`comparison_05` | comparison | unsupported | `multiple_versions` | none; do not fabricate |

All IDs in the JSON use the complete canonical prefix `ldn_2020_`; abbreviated
IDs in this table are display-only.

## Automated Dataset Checks

The source test suite verifies:

```text
case count = 30
five cases per canonical intent
all query IDs unique
all supported cases have non-empty graded gold
all unsupported cases expect an unavailable capability
all gold unit IDs resolve in the L59_2020 hierarchy
all natural-language queries route to their declared intent
all declared capabilities match canonical pilot artifacts
four multi-hop cases require at least two graph edges and resolve through
accepted REFERS_TO and canonical structural CONTAINS relations
the fifth graph case is explicitly typed as a branching one-hop reference and
requires both gold branches
supported validity cases contain machine-readable query date, subject, scope,
expected decision, temporal evidence source, and required temporal metadata
supported hierarchy cases contain machine-readable CONTAINS parent/child gold
structural grouping preserves the relevance grade of the units actually
returned and counts a parent/Clause group once
official evaluation rejects pending review
```

Automated checks do not replace human legal relevance review.

## Artifact Evidence Required For Sign-Off

The artifact verification report must retain all of the following:

```text
all declared graph paths matched against accepted.jsonl and hierarchy.json
seven accepted REFERS_TO edge records with citation provenance
every accepted REFERS_TO edge has a deterministic canonical relation_id and
identity discriminator; mutable provenance is excluded from identity
all hierarchy gold relations matched, including art17_cl2 -> art17_cl2_pa
document metadata source ldn_2020 with effective_from and legal_status
nullable effective_to represented explicitly as null
field_presence distinguishes an absent effective_to property from a stored
value, and normalization declares the absent property open-ended
predicate_evaluation records interval checks, subject-level legal status,
computed validity, expected validity, and match result
scoped Neo4j capability snapshot
guides_relations_available = false
multiple_versions_available = false
verification.status = PASS
source_commit is recorded
working_tree_state is recorded
generated_at, verifier contract/source commit, command hash, runtime config
hash, capability query hash, database name, and Neo4j version are recorded
Gate 7 = OPEN
M3-B13 = OPEN
Milestone A = NOT PASSED
official_evaluation = NOT STARTED
```

Any change to the dataset, accepted extraction set, hierarchy, graph snapshot,
or scoped Neo4j capabilities invalidates the corresponding input hash and
requires regenerating this report before human sign-off.
