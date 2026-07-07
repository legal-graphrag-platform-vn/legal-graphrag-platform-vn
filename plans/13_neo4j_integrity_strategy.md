# Neo4j Integrity Strategy

## Community Edition

Neo4j Community Edition remains the persistence layer for this phase, so all mandatory property checks must happen in the application layer before any `MERGE` call.

## Enforcement Model

- Validate required node properties in the ontology validator.
- Validate relation type, direction, and required edge properties in the same shared gate.
- Validate graph consistency before repository write: duplicate IDs, dangling relation endpoints, temporal conflicts, and cycle rules.
- Run confidence scoring only after schema and ontology validation; scoring must not relax hard ontology rules.
- Allow the Neo4j bootstrap script to create only uniqueness constraints and indexes.
- Reject raw write attempts that do not pass through the validated ingestion stack.

Current stack:

```text
LLM -> Pydantic -> Ontology Validator -> Graph Consistency Validator
    -> Confidence Scorer -> Neo4j Repository -> Neo4j Python Driver -> Neo4j
```

## Enterprise Edition

If the deployment target moves to Enterprise later, database-level existence and type constraints can be added as an optional defense-in-depth layer.

That change would be additive only. It must not replace application-layer validation.
