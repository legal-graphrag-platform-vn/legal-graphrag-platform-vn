from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.infrastructure.neo4j.schema_verifier import (
    EXPECTED_CONSTRAINTS,
    EXPECTED_USER_INDEXES,
    SchemaVerificationError,
    verify_canonical_schema,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


class FakeSession:
    def __init__(
        self, *, missing_index: str | None = None, vector_dimension: int = 1024
    ) -> None:
        self.missing_index = missing_index
        self.vector_dimension = vector_dimension

    def run(self, cypher: str, **parameters):
        if cypher.startswith("SHOW CONSTRAINTS"):
            return [{"name": name} for name in EXPECTED_CONSTRAINTS]
        rows = [
            {"name": name, "type": "RANGE", "state": "ONLINE", "options": {}}
            for name in EXPECTED_CONSTRAINTS
        ]
        for name in EXPECTED_USER_INDEXES - (
            {self.missing_index} if self.missing_index else set()
        ):
            is_vector = name in {
                "appendix_embedding",
                "article_embedding",
                "clause_embedding",
            }
            rows.append(
                {
                    "name": name,
                    "type": "VECTOR" if is_vector else "RANGE",
                    "state": "ONLINE",
                    "options": {
                        "indexConfig": {
                            "vector.dimensions": self.vector_dimension,
                            "vector.similarity_function": "cosine",
                        }
                    }
                    if is_vector
                    else {},
                }
            )
        rows.append(
            {
                "name": "index_343aff4e",
                "type": "LOOKUP",
                "state": "ONLINE",
                "options": {},
            }
        )
        return rows


def test_schema_verifier_accepts_canonical_set_and_ignores_lookup_indexes() -> None:
    report = verify_canonical_schema(FakeSession())
    assert set(report.constraints) == EXPECTED_CONSTRAINTS
    assert set(report.user_indexes) == EXPECTED_USER_INDEXES


def test_schema_verifier_expected_names_match_canonical_bootstrap() -> None:
    schema = (
        REPO_ROOT / "infra" / "neo4j" / "init" / "01_schema_init.cypher"
    ).read_text(encoding="utf-8")
    constraint_names = set(re.findall(r"CREATE CONSTRAINT (\w+)", schema))
    index_names = set(
        re.findall(r"CREATE (?:INDEX|FULLTEXT INDEX|VECTOR INDEX) (\w+)", schema)
    )

    assert constraint_names == EXPECTED_CONSTRAINTS
    assert index_names == EXPECTED_USER_INDEXES


def test_appendix_migration_recreates_fulltext_index_with_new_label() -> None:
    migration = (
        REPO_ROOT / "infra" / "neo4j" / "migrations" / "1.12.0_to_1.13.0.cypher"
    ).read_text(encoding="utf-8")

    assert "DROP INDEX legal_article_clause_fulltext IF EXISTS" in migration
    assert "FOR (n:Appendix|Article|Clause)" in migration
    assert "CREATE VECTOR INDEX appendix_embedding" in migration


def test_attached_instrument_migration_adds_constraint_and_lookup_indexes() -> None:
    migration = (
        REPO_ROOT / "infra" / "neo4j" / "migrations" / "1.13.0_to_1.14.0.cypher"
    ).read_text(encoding="utf-8")

    assert "CREATE CONSTRAINT attached_instrument_id_unique" in migration
    assert "CREATE INDEX attached_instrument_scope" in migration
    assert "CREATE INDEX attached_instrument_kind" in migration


def test_schema_verifier_rejects_missing_index_and_wrong_vector_dimension() -> None:
    with pytest.raises(SchemaVerificationError, match="Missing indexes"):
        verify_canonical_schema(FakeSession(missing_index="refers_to_relation_id"))
    with pytest.raises(SchemaVerificationError, match="dimension"):
        verify_canonical_schema(FakeSession(vector_dimension=768))
