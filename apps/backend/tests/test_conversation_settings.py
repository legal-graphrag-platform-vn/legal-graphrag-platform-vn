"""Settings.validate_runtime rules for the conversation context store (Plan 19)."""

from __future__ import annotations

import pytest

from settings import Settings


_VALID_KEY = "x" * 32
_VALID_URL = "postgresql+asyncpg://u:p@localhost:5432/db"


def _grounded_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "app_mode": "graphrag",
        "neo4j_uri": "bolt://localhost:7687",
        "neo4j_user": "neo4j",
        "neo4j_password": "secret",
        "gemini_api_key": "gk",
        "answer_generation_enabled": True,
        "database_url": _VALID_URL,
        "anonymous_principal_signing_key": _VALID_KEY,
    }
    base.update(overrides)
    return Settings(**base)


def test_grounded_chat_accepts_complete_configuration() -> None:
    _grounded_settings().validate_runtime()


def test_grounded_chat_requires_database_url() -> None:
    settings = _grounded_settings(database_url=None)
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        settings.validate_runtime()


def test_grounded_chat_rejects_non_asyncpg_driver() -> None:
    settings = _grounded_settings(
        database_url="postgresql://u:p@localhost:5432/db",
    )
    with pytest.raises(RuntimeError, match="postgresql\\+asyncpg"):
        settings.validate_runtime()


def test_grounded_chat_requires_signing_key() -> None:
    settings = _grounded_settings(anonymous_principal_signing_key=None)
    with pytest.raises(RuntimeError, match="SIGNING_KEY"):
        settings.validate_runtime()


def test_grounded_chat_rejects_short_signing_key() -> None:
    settings = _grounded_settings(anonymous_principal_signing_key="x" * 31)
    with pytest.raises(RuntimeError, match="32 bytes"):
        settings.validate_runtime()


def test_pool_size_must_cover_answer_concurrency() -> None:
    settings = _grounded_settings(db_pool_size=1, answer_max_concurrency=4)
    with pytest.raises(RuntimeError, match="DB_POOL_SIZE"):
        settings.validate_runtime()


def test_conversation_store_not_required_when_answer_generation_disabled() -> None:
    settings = Settings(
        app_mode="graphrag",
        neo4j_uri="bolt://localhost:7687",
        neo4j_user="neo4j",
        neo4j_password="secret",
        answer_generation_enabled=False,
    )
    settings.validate_runtime()


def test_mock_mode_ignores_conversation_store() -> None:
    Settings(app_mode="mock").validate_runtime()
