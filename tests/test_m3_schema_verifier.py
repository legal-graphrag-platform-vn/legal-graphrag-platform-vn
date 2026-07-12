from __future__ import annotations

import pytest

from src.infrastructure.neo4j.schema_verifier import (
    EXPECTED_CONSTRAINTS,
    EXPECTED_USER_INDEXES,
    SchemaVerificationError,
    verify_canonical_schema,
)


class FakeSession:
    def __init__(self, *, missing_index: str | None = None, vector_dimension: int = 1024) -> None:
        self.missing_index = missing_index
        self.vector_dimension = vector_dimension

    def run(self, cypher: str, **parameters):
        if cypher.startswith("SHOW CONSTRAINTS"):
            return [{"name": name} for name in EXPECTED_CONSTRAINTS]
        rows = []
        for name in EXPECTED_USER_INDEXES - ({self.missing_index} if self.missing_index else set()):
            is_vector = name in {"article_embedding", "clause_embedding"}
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
                    } if is_vector else {},
                }
            )
        rows.append({"name": "index_343aff4e", "type": "LOOKUP", "state": "ONLINE", "options": {}})
        return rows


def test_schema_verifier_accepts_canonical_set_and_ignores_lookup_indexes() -> None:
    report = verify_canonical_schema(FakeSession())
    assert set(report.constraints) == EXPECTED_CONSTRAINTS
    assert set(report.user_indexes) == EXPECTED_USER_INDEXES


def test_schema_verifier_rejects_missing_index_and_wrong_vector_dimension() -> None:
    with pytest.raises(SchemaVerificationError, match="Missing indexes"):
        verify_canonical_schema(FakeSession(missing_index="refers_to_relation_id"))
    with pytest.raises(SchemaVerificationError, match="dimension"):
        verify_canonical_schema(FakeSession(vector_dimension=768))
