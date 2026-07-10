"""Generate and validate Article/Clause embeddings for the canonical graph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from src.pipeline.config import settings


class EncoderProtocol(Protocol):
    def encode(self, texts: list[str], normalize_embeddings: bool = True) -> Iterable[Iterable[float]]: ...


class EmbeddingDimensionError(ValueError):
    """Raised when an embedding model returns a vector with the wrong dimension."""


@dataclass(slots=True)
class EmbeddingGenerator:
    model_name: str = settings.embedding_model
    expected_dimension: int = settings.embedding_dimension
    normalize_embeddings: bool = True
    encoder: EncoderProtocol | None = None

    def encode(self, texts: list[str]) -> list[list[float]]:
        encoder = self.encoder or self._load_encoder()
        vectors = [list(vector) for vector in encoder.encode(texts, normalize_embeddings=self.normalize_embeddings)]
        for vector in vectors:
            validate_embedding_dimension(vector, self.expected_dimension)
        return vectors

    def _load_encoder(self) -> EncoderProtocol:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Install sentence-transformers to use the embed command") from exc
        return SentenceTransformer(self.model_name)


def embedding_text_for_node(node: dict) -> str | None:
    node_type = node.get("type")
    if node_type == "Article":
        return build_article_embedding_text(node)
    if node_type == "Clause":
        return build_clause_embedding_text({}, node)
    return None


def embedding_targets(payload: dict) -> list[dict]:
    return [node for node in payload.get("nodes", []) if node.get("type") in {"Article", "Clause"}]


def embedding_texts_by_node_id(payload: dict) -> dict[str, str]:
    nodes = {str(node.get("id")): node for node in payload.get("nodes", [])}
    parent_article_by_clause_id: dict[str, dict] = {}
    for relation in payload.get("relations", []):
        if relation.get("type") != "CONTAINS":
            continue
        head = nodes.get(str(relation.get("head_id")))
        tail = nodes.get(str(relation.get("tail_id")))
        if head and tail and head.get("type") == "Article" and tail.get("type") == "Clause":
            parent_article_by_clause_id[str(tail["id"])] = head

    texts: dict[str, str] = {}
    for node in embedding_targets(payload):
        node_id = str(node["id"])
        if node.get("type") == "Article":
            texts[node_id] = build_article_embedding_text(node)
        else:
            texts[node_id] = build_clause_embedding_text(parent_article_by_clause_id.get(node_id, {}), node)
    return texts


def build_article_embedding_text(article: dict) -> str:
    return "\n".join(_clean_parts(article.get("title"), article.get("content_raw")))


def build_clause_embedding_text(article: dict, clause: dict) -> str:
    article_header = " ".join(
        _clean_parts(
            f"Điều {article.get('number')}." if article.get("number") else None,
            article.get("title"),
        )
    )
    clause_header = " ".join(
        _clean_parts(
            f"Khoản {clause.get('number')}." if clause.get("number") else None,
            clause.get("content_raw") or clause.get("content"),
        )
    )
    return "\n".join(_clean_parts(article_header, clause_header))


def validate_embedding_dimension(vector: list[float], expected_dimension: int = settings.embedding_dimension) -> None:
    if len(vector) != expected_dimension:
        raise EmbeddingDimensionError(f"Expected {expected_dimension}-dim embedding, got {len(vector)}")


def _clean_parts(*parts: object) -> list[str]:
    return [str(part).strip() for part in parts if str(part or "").strip()]
