---
name: legal-graphrag
description: Use for tasks in the Legal GraphRAG VN repo that touch ontology, ingestion, extraction, retrieval, Neo4j, plan docs, or pipeline behavior.
---

# Legal GraphRAG VN

Use this skill for work in this repository.

## Read First
1. `plans/README.md`
2. `plans/legal_ontology.md`
3. `.codex/rules/.rules`
4. `plans/03_architecture.md`
5. `plans/04_graph_construction_pipeline.md`
6. `plans/05_graphrag_retrieval.md`
7. `src/pipeline/README.md`

## What To Assume
- The active ingestion path is web crawl -> raw text -> parse.
- `plans/legal_ontology.md` is the source of truth.
- Extraction and reasoning are separate tasks.
- Validator rules are strict and do not get softened by scoring.

## Working Procedure
1. Identify the subsystem: ontology, ingestion, extraction, retrieval, docs, or tests.
2. Read the canonical spec for that subsystem.
3. Inspect the implementation before editing.
4. Make the smallest change that fixes the actual behavior.
5. Update the matching tests and docs in the same change.
6. Verify with the narrowest useful command or test.

## Hard Rules
- Do not reintroduce PDF-first or OCR-first behavior unless the task explicitly asks for it.
- Do not accept legacy relation aliases as current behavior.
- Do not broaden validator acceptance to match a stale prompt or stale doc.
- Do not keep dead CLI paths or dead compatibility branches.
- Do not let confidence scoring override a hard ontology or schema failure.
- Do not change one side of a contract without updating the matching prompt, validator, test, and doc.

## Area Map
- Ontology and validator: `plans/legal_ontology.md`, `src/pipeline/src/validation/ontology_validator.py`, `src/pipeline/tests/test_ontology_consistency.py`
- Ingestion and parsing: `src/pipeline/main.py`, `src/pipeline/src/crawler/`, `src/pipeline/src/parser/`
- Extraction: `src/pipeline/src/extraction/`, `src/pipeline/src/validation/`
- Retrieval and reasoning: `plans/05_graphrag_retrieval.md`, `src/pipeline/src/pipeline/`
- Roadmap and scope: `plans/07_implementation_timeline.md`, `plans/08_dataset_and_scope.md`, `plans/11_project_phases.md`

## Verification Targets
- After ontology changes, run `src/pipeline/tests/test_ontology_consistency.py`.
- After ingestion/CLI changes, check `src/pipeline/README.md` matches `src/pipeline/main.py`.
- After extraction changes, check the prompt, model schema, and validator still agree.
- After retrieval changes, check the plan docs and code still name the same traversal behavior.

## Deliverable Standard
- State what changed.
- State what was verified.
- State any remaining blocker or assumption.
