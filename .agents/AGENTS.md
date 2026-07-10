# Architectural Import Rules

This repository enforces strict clean architecture boundaries. Do NOT violate these import rules when modifying or creating new files.

- `src/pipeline/` can import from `src/shared/`.
- `src/pipeline/` CANNOT import from `apps/`.
- `apps/` CANNOT import from `src/pipeline/` (the pipeline is batch-only).
- `prototypes/` cannot import from anywhere in `src/` (except temporary data references) and vice versa.
- All validators must use `src/shared/ontology/contract.py` as the single source of truth.
