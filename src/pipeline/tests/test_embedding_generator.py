from __future__ import annotations

import pytest

from unittest.mock import Mock

from src.infrastructure.embedding.embedding_generator import (
    EmbeddingDimensionError,
    EmbeddingGenerator,
    EmbeddingProviderError,
    build_clause_embedding_text,
    embedding_content_hash,
    embedding_targets,
    embedding_texts_by_node_id,
    validate_embedding_dimension,
)
from src.infrastructure.neo4j.embedding_writer import Neo4jEmbeddingWriter


def test_embedding_targets_include_only_article_and_clause() -> None:
    payload = {
        "nodes": [
            {"type": "Article", "id": "a"},
            {"type": "Clause", "id": "c"},
            {"type": "Point", "id": "p"},
            {"type": "LegalConcept", "id": "x"},
        ]
    }

    assert [node["id"] for node in embedding_targets(payload)] == ["a", "c"]


def test_embedding_dimension_must_match_configured_schema() -> None:
    with pytest.raises(EmbeddingDimensionError):
        validate_embedding_dimension([0.1, 0.2], expected_dimension=1024)


def test_embedding_defaults_match_bge_m3_contract() -> None:
    generator = EmbeddingGenerator()

    assert generator.model_name == "BAAI/bge-m3"
    assert generator.provider == "flag_embedding"
    assert generator.expected_dimension == 1024


def test_unknown_embedding_provider_fails_fast() -> None:
    with pytest.raises(EmbeddingProviderError, match="unsupported"):
        EmbeddingGenerator(provider="unsupported")._load_encoder()


def test_clause_embedding_text_includes_parent_article_title() -> None:
    text = build_clause_embedding_text(
        {"number": "17", "title": "Quyền thành lập doanh nghiệp"},
        {"number": "1", "content_raw": "Tổ chức, cá nhân có quyền thành lập doanh nghiệp."},
    )

    assert "Quyền thành lập doanh nghiệp" in text
    assert "Tổ chức, cá nhân có quyền" in text


def test_embedding_texts_by_node_id_uses_parent_article_context() -> None:
    payload = {
        "nodes": [
            {"type": "Article", "id": "ldn_2020_art17", "number": "17", "title": "Quyền thành lập", "content_raw": "Điều 17"},
            {"type": "Clause", "id": "ldn_2020_art17_cl1", "number": "1", "content_raw": "Khoản 1"},
        ],
        "relations": [
            {"head_id": "ldn_2020_art17", "type": "CONTAINS", "tail_id": "ldn_2020_art17_cl1", "properties": {}}
        ],
    }

    texts = embedding_texts_by_node_id(payload)

    assert "Quyền thành lập" in texts["ldn_2020_art17_cl1"]
    assert "Khoản 1" in texts["ldn_2020_art17_cl1"]


def test_embedding_content_hash_changes_with_exact_encoder_text() -> None:
    assert embedding_content_hash("Điều 17") != embedding_content_hash("Điều 17 ")


def test_embedding_resume_requires_all_metadata_and_reachability() -> None:
    session = Mock()
    session.run.return_value = [
        {
            "id": "ldn_2020_art17",
            "vector_size": 1024,
            "model": "BAAI/bge-m3",
            "provider": "flag_embedding",
            "dimension": 1024,
            "normalized": True,
            "content_hash": "same",
        }
    ]
    writer = Neo4jEmbeddingWriter(session=session)

    assert writer.stale_target_ids(
        "ldn_2020",
        {"ldn_2020_art17": "same"},
        model="BAAI/bge-m3",
        provider="flag_embedding",
        normalized=True,
    ) == []
    assert writer.stale_target_ids(
        "ldn_2020",
        {"ldn_2020_art17": "changed"},
        model="BAAI/bge-m3",
        provider="flag_embedding",
        normalized=True,
    ) == ["ldn_2020_art17"]

    with pytest.raises(ValueError, match="not reachable"):
        writer.stale_target_ids(
            "ldn_2020",
            {"outside": "hash"},
            model="BAAI/bge-m3",
            provider="flag_embedding",
            normalized=True,
        )


def test_vector_index_verification_fails_when_required_index_missing() -> None:
    session = Mock()
    session.run.return_value = [
        {
            "name": "article_embedding",
            "state": "ONLINE",
            "options": {"indexConfig": {"vector.dimensions": 1024}},
        }
    ]

    with pytest.raises(RuntimeError, match="clause_embedding"):
        Neo4jEmbeddingWriter(session=session).verify_vector_indexes()


def test_vector_index_verification_fails_when_index_is_offline() -> None:
    session = Mock()
    session.run.return_value = [
        {"name": "article_embedding", "state": "POPULATING"},
        {
            "name": "clause_embedding",
            "state": "ONLINE",
            "options": {"indexConfig": {"vector.dimensions": 1024}},
        },
    ]

    with pytest.raises(RuntimeError, match="POPULATING"):
        Neo4jEmbeddingWriter(session=session).verify_vector_indexes()


def test_vector_index_verification_fails_on_dimension_mismatch() -> None:
    session = Mock()
    session.run.return_value = [
        {
            "name": "article_embedding",
            "state": "ONLINE",
            "options": {"indexConfig": {"vector.dimensions": 768}},
        },
        {
            "name": "clause_embedding",
            "state": "ONLINE",
            "options": {"indexConfig": {"vector.dimensions": 1024}},
        },
    ]

    with pytest.raises(RuntimeError, match="768"):
        Neo4jEmbeddingWriter(session=session).verify_vector_indexes()
