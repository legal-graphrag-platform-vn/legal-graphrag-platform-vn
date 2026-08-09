"""Canonical Neo4j schema bootstrap initializer."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from neo4j import Driver, GraphDatabase


def parse_cypher_statements(script: str) -> list[str]:
    """Parse cypher script into standalone statements, stripping comments."""
    # Remove single-line comments // ...
    cleaned = re.sub(r"//.*$", "", script, flags=re.MULTILINE)
    # Split by semicolon
    raw_statements = cleaned.split(";")
    statements: list[str] = []
    for stmt in raw_statements:
        trimmed = stmt.strip()
        if trimmed:
            statements.append(trimmed)
    return statements


def initialize_canonical_schema(
    driver: Driver,
    schema_path: Path | str | None = None,
) -> dict[str, Any]:
    """Apply all constraints and indexes from 01_schema_init.cypher."""
    if schema_path is None:
        schema_path = (
            Path(__file__).resolve().parents[3]
            / "infra"
            / "neo4j"
            / "init"
            / "01_schema_init.cypher"
        )
    schema_file = Path(schema_path)
    if not schema_file.exists():
        raise FileNotFoundError(f"Schema file not found at: {schema_file}")

    content = schema_file.read_text(encoding="utf-8")
    statements = parse_cypher_statements(content)

    applied = 0
    errors: list[str] = []

    with driver.session() as session:
        for stmt in statements:
            try:
                session.run(stmt)
                applied += 1
            except Exception as e:
                errors.append(f"{stmt[:50]}... -> {e}")

    return {
        "applied_statements": applied,
        "total_statements": len(statements),
        "errors": errors,
    }
