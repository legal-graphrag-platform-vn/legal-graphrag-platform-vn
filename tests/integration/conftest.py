from __future__ import annotations

import os
import uuid

import pytest

from src.infrastructure.neo4j.m3_runtime import require_integration_opt_in, validate_disposable_uri
from src.infrastructure.neo4j.writer import create_neo4j_session
from src.pipeline.config import settings


@pytest.fixture(scope="session", autouse=True)
def disposable_m3_runtime_guard() -> None:
    require_integration_opt_in(os.environ)
    validate_disposable_uri(settings.neo4j_uri)


@pytest.fixture()
def test_prefix() -> str:
    return f"test_{uuid.uuid4().hex}_"


@pytest.fixture()
def isolated_neo4j_prefix(test_prefix: str):
    session = create_neo4j_session()

    def cleanup() -> None:
        rows = list(session.run("MATCH (n) WHERE n.id STARTS WITH $prefix RETURN n.id AS id", prefix=test_prefix))
        matched = [str(row["id"]) for row in rows]
        if any(not node_id.startswith(test_prefix) for node_id in matched):
            pytest.fail("Cleanup query matched a node outside the current UUID prefix")
        if matched:
            session.run("MATCH (n) WHERE n.id IN $ids DETACH DELETE n", ids=matched)

    cleanup()
    yield test_prefix
    cleanup()
    session.close()
