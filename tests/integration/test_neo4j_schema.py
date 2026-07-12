from __future__ import annotations

import pytest

from src.infrastructure.neo4j.schema_verifier import verify_canonical_schema
from src.infrastructure.neo4j.writer import create_neo4j_session


pytestmark = pytest.mark.integration


def test_neo4j_constraints_and_indexes() -> None:
    session = create_neo4j_session()
    try:
        report = verify_canonical_schema(session)
    finally:
        session.close()

    assert "doc_id_unique" in report.constraints
    assert "article_embedding" in report.user_indexes
    assert "clause_embedding" in report.user_indexes
