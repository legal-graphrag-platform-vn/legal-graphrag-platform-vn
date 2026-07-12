# M3 Structural Endpoint Normalization and Canonical Re-extraction Plan

> Status: approved for implementation
> Pilot: `L59_2020`
> Parent: `06_m3_runtime_acceptance_and_milestone_a_plan.md`

## Problem

The completed extraction reconciles (`1779 = 586 accepted + 1193 rejected`) but
Gate 3 fails because accepted relations contain raw LLM structural aliases such
as `khoan_1_1`. Record validation accepted those aliases from the temporary LLM
entity list, while the payload builder correctly accepts only hierarchy-backed
structural IDs and semantic IDs from `entity_index.json`.

## Required Contract

```text
Parser owns Document/Chapter/Article/Clause/Point identity and CONTAINS.
LLM proposes semantic entities and non-CONTAINS legal relations.
Every endpoint is normalized before ontology/consistency validation.
Accepted records contain canonical endpoint IDs only.
Payload builder never guesses or repairs endpoints.
```

## Implementation

1. Build an immutable structural registry from `ParsedDocument`, including
   canonical Article, Clause, and Point IDs and per-Article prompt context.
2. Pass structural context to every provider. Prompts list the exact allowed
   structural IDs, stop extracting local structure as entities, and forbid LLM
   `CONTAINS` proposals.
3. Normalize endpoints by canonical exact match, legal structural label,
   current-document/current-Article reference, semantic entity index, or curated
   document registry. Ambiguous local endpoints are rejected; unresolved external
   citations enter review.
4. Preserve `raw_relation`, normalized `relation`, and endpoint-resolution audit
   metadata in every decision record.
5. Persist one raw result per Article in `article_extractions.jsonl`. Reuse only
   checkpoints whose graph/context/provider/model/prompt fingerprint matches.
   Provider failures preserve completed checkpoints.

Checkpoint hardening requirements:

- Duplicate Article rows are a hard failure; reader never silently chooses first/last.
- Fingerprint includes Article content, prompt version, and endpoint contract version.
- Checkpoint stores configured and provider-resolved model identities.
- A resolved-model change within one resumable run is a hard failure.
- Article and Clause legal numbers are strings so suffixed units such as `5a` are preserved.
- Semantic entities are canonicalized before relation extraction.
6. Add `normalize-extraction` to regenerate decision artifacts without provider
   calls and `archive-extraction` to quarantine invalid runs before re-extraction.
7. Make record consistency validate canonical structural/semantic IDs. Keep the
   payload builder strict and remove active raw-alias compatibility.

## Artifact Rules

- `article_extractions.jsonl`: raw provider output and resume checkpoint.
- `extract.jsonl`: full normalized decision audit.
- `accepted.jsonl`: canonical, writer-eligible relations only.
- `review.jsonl`: unresolved external/ambiguous references only.
- `rejected.jsonl`: schema, ontology, forbidden-structure, or local-resolution failures.
- `entity_index.json`: canonical Phase 1 semantic nodes only.

Current invalid artifacts are archived under
`data/processed/L59_2020/runs/pre_endpoint_normalization_<timestamp>/` and never
used by `validate-payload` or `write`.

## Tests and Acceptance

- Resolve current and cross-Article Article/Clause/Point legal labels.
- Preserve Point `d` versus `đ` identity.
- Reject `khoan_x_2`, nonexistent structural targets, and all LLM `CONTAINS`.
- Review explicit external citations absent from the registry.
- Preserve/reuse valid checkpoints and reject stale fingerprints.
- Decision counts reconcile and accepted unresolved endpoint count is zero.
- `validate-payload` reports Article 218, Clause 897, Point 822, zero dangling
  endpoints, zero duplicate identities, zero ontology violations, and zero
  LLM-created `CONTAINS` relations.

Milestone A and Phase 2 remain blocked until Gate 3 and all later M3 gates pass.
