# Plan 15 — Structural Reference Resolution and Appendix Preservation

> Status: IMPLEMENTED IN CODE; ARTIFACT MIGRATION AND RESEARCH EVALUATION PENDING
> Ontology: v1.6.0 / ADR-22

## Objective

```text
Crawler -> Structural Parser -> Source Context -> Deterministic Resolver
-> Entity Linking / LLM fallback -> Atomic Bundle Validation -> REFERS_TO
```

Parser owns structure and coordinates. Resolver owns deterministic endpoint identity. The LLM handles semantic or
ambiguous references only. Validators decide whether a complete relation bundle enters the graph.

## Contracts

- Preserve Appendix source as `ParsedDocument.unparsed_sections`; do not create Appendix graph nodes.
- Source offsets are 0-based, start-inclusive, end-exclusive over NFC/LF canonical `source.txt`.
- `REFERS_TO.extraction_method` is `RULE`, `ENTITY_LINKING`, or `LLM`.
- Common provenance: citation text/type, extraction method, created timestamp, and reference bundle ID.
- Rule/linker/LLM provenance is conditionally validated by method.
- Multi-target references are atomic: all target edges pass or no edge is accepted.
- Same-document explicit references are RULE; curated cross-document references are ENTITY_LINKING.
- Parallel citations are retained for evidence but collapsed by endpoint triple for path topology.

## Implementation Stages

1. Preserve Appendix in crawler output and partition it before hierarchy parsing.
2. Add source spans to Article, Clause, Point, reference mentions, and unparsed sections.
3. Resolve relative Point/Clause/Article references without provider calls.
4. Persist deterministic resolver checkpoints so unchanged normalization preserves timestamps and hashes.
5. Materialize complete rule bundles through schema, ontology, endpoint, and consistency validation.
6. Suppress equivalent LLM candidates while retaining audit records.
7. Reuse content-identical legacy semantic checkpoints for offline v1.6.0 normalization.
8. Validate payload, rebuild only disposable Neo4j, write twice, and regenerate graph evidence.

## Required Tests

- Appendix is preserved and never attached to the final legal unit.
- Source spans reproduce the exact canonical source substring.
- `d` and `đ` remain distinct Point targets.
- Missing one target rejects a complete list reference.
- Rule relations require resolver provenance but not fake LLM fields.
- LLM relations still require confidence, model, checkpoint, and timestamp provenance.
- Repeated offline normalization makes zero provider calls and preserves payload hashes.
- Parallel citations cannot inflate graph path ranking.

## Research Evaluation

Build a locally reviewed benchmark of at least 120 reference mentions, split by document into 80 development and
40 held-out test cases. Compare rule-only, Gemini-only, Qwen-only, and resolver-first plus LLM fallback using exact
target-set match, edge precision/recall/F1, atomic-list accuracy, unresolved rate, false-positive rate, provider calls,
tokens, latency, and estimated cost.

## Deferred

Appendix nodes, embeddings, retrieval, citations, and graph reasoning require a separate ADR and ontology migration.
Gate 7 and M3-B13 remain OPEN; Milestone A remains NOT PASSED.
