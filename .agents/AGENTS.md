# Architectural Import Rules

This repository enforces strict clean architecture boundaries. Do **not** violate these import rules when modifying or creating files.

## Allowed Dependencies

* `apps/backend/` may import from:

  * `src/retrieval/`
  * `src/generation/`
  * `src/infrastructure/`
  * `src/shared/`

* `src/pipeline/` may import from:

  * `src/infrastructure/`
  * `src/shared/`

* `src/retrieval/` may import from:

  * `src/infrastructure/`
  * `src/shared/`

* `src/generation/` may import from:

  * `src/infrastructure/`
  * `src/shared/`

* `src/infrastructure/` may import from:

  * `src/shared/`

* `src/shared/` must not import from any other project package.

## Forbidden Dependencies

* `apps/` must not import from `src/pipeline/`.

  * The pipeline is batch-only and must not be used by runtime apps.

* `src/pipeline/` must not import from `apps/`.

* `src/infrastructure/` must not import from:

  * `apps/`
  * `src/pipeline/`
  * `src/retrieval/`
  * `src/generation/`

* `src/shared/` must not import from:

  * `apps/`
  * `src/pipeline/`
  * `src/infrastructure/`
  * `src/retrieval/`
  * `src/generation/`

* `prototypes/` must not be imported by runtime code.

  * No imports from `apps/`, `src/pipeline/`, `src/infrastructure/`, `src/retrieval/`, `src/generation/`, or `src/shared/` into `prototypes/`.
  * No imports from `prototypes/` into `apps/` or `src/`.

## Ontology Contract Rule

All ontology validators, graph payload builders, and graph writers must use:

```text
src/shared/ontology/contract.py
```

as the single source of truth for ontology constants, including:

* relation enums
* valid node labels
* runtime-only labels
* legacy aliases
* required node fields
* required relation properties
* `GUIDES` whitelist
* Phase 1 `REQUIRES` valid pairs

Do not duplicate ontology constants in pipeline, writer, retrieval, or tests.

## Writer Boundary Rule

Neo4j graph writes must go through the guarded writer path only.

Allowed:

```text
payload builder
-> payload consistency validation
-> write-time ontology validation
-> validated payload
-> infrastructure Neo4j writer
```

Forbidden:

* direct Neo4j driver writes from CLI commands
* direct Neo4j driver writes from `apps/backend/`
* writing raw LLM extraction output
* writing `review.jsonl` or `extract.jsonl` directly
* creating graph labels or relation types outside the ontology contract

## Prototype Rule

`prototypes/` contains archived or experimental code only.

Code in `prototypes/` may be read for ideas, but must not become part of the active runtime or pipeline without being migrated into the proper package and made compliant with these import rules.

## Python Dependency Management

Use `uv` for Python dependency and environment management.

- Add runtime dependencies to `pyproject.toml`.
- Add development/test dependencies to the `dev` dependency group.
- Add embedding/model dependencies to the `embedding` dependency group.
- Do not run or document ad-hoc `pip install ...` commands unless explicitly debugging.
- Commit `uv.lock`.
- Do not commit `.venv/`.
- Use `uv run` for project commands.
