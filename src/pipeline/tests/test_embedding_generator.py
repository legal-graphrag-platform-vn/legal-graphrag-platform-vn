from __future__ import annotations

import pytest

from unittest.mock import Mock

from src.embedding.embedding_generator import (
    EmbeddingDimensionError,
    build_clause_embedding_text,
    embedding_targets,
    embedding_texts_by_node_id,
    validate_embedding_dimension,
)
from src.embedding.neo4j_embedding_writer import Neo4jEmbeddingWriter


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


def test_embedding_dimension_must_be_768() -> None:
    with pytest.raises(EmbeddingDimensionError):
        validate_embedding_dimension([0.1, 0.2], expected_dimension=768)


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


def test_vector_index_verification_fails_when_required_index_missing() -> None:
    session = Mock()
    session.run.return_value = [{"name": "article_embedding", "state": "ONLINE"}]

    with pytest.raises(RuntimeError, match="clause_embedding"):
        Neo4jEmbeddingWriter(session=session).verify_vector_indexes()


def test_vector_index_verification_fails_when_index_is_offline() -> None:
    session = Mock()
    session.run.return_value = [
        {"name": "article_embedding", "state": "POPULATING"},
        {"name": "clause_embedding", "state": "ONLINE"},
    ]

    with pytest.raises(RuntimeError, match="POPULATING"):
        Neo4jEmbeddingWriter(session=session).verify_vector_indexes()
