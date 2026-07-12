from __future__ import annotations

import pytest

from src.infrastructure.neo4j.m3_runtime import (
    M3RuntimeGuardError,
    require_destructive_opt_in,
    require_integration_opt_in,
    validate_disposable_uri,
)


@pytest.mark.parametrize("uri", ["bolt://localhost:7688", "neo4j://127.0.0.1:7688"])
def test_disposable_uri_accepts_only_frozen_local_target(uri: str) -> None:
    assert validate_disposable_uri(uri) == uri


@pytest.mark.parametrize(
    "uri",
    [
        "bolt://localhost:7687",
        "bolt://localhost",
        "bolt://neo4j.example:7688",
        "bolt://user:secret@localhost:7688",
        "bolt://localhost:7688?region=x",
        "http://localhost:7688",
    ],
)
def test_disposable_uri_rejects_unsafe_targets(uri: str) -> None:
    with pytest.raises(M3RuntimeGuardError):
        validate_disposable_uri(uri)


def test_integration_and_destructive_opt_ins_are_separate() -> None:
    require_integration_opt_in({"RUN_NEO4J_INTEGRATION": "1"})
    require_destructive_opt_in({"RUN_M3_DESTRUCTIVE": "1", "CONFIRM_M3_RESET": "YES"})

    with pytest.raises(M3RuntimeGuardError):
        require_integration_opt_in({"RUN_M3_DESTRUCTIVE": "1"})
    with pytest.raises(M3RuntimeGuardError):
        require_destructive_opt_in({"RUN_NEO4J_INTEGRATION": "1", "CONFIRM_M3_RESET": "YES"})
