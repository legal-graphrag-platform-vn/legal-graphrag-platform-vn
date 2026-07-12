"""Neo4j updater for Article/Clause embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from src.pipeline.config import settings


class SessionProtocol(Protocol):
    def run(self, cypher: str, **parameters: Any) -> Any: ...


REQUIRED_VECTOR_INDEXES = {"article_embedding", "clause_embedding"}


@dataclass(slots=True)
class Neo4jEmbeddingWriter:
    session: SessionProtocol
    expected_dimension: int = settings.embedding_dimension

    def verify_vector_indexes(self) -> None:
        rows = list(
            self.session.run(
                (
                    "SHOW INDEXES "
                    "YIELD name, type, state, options "
                    "WHERE type = 'VECTOR' "
                    "RETURN name, state, options"
                )
            )
        )
        found = {_row_value(row, "name"): _row_value(row, "state") for row in rows}
        dimensions = {
            _row_value(row, "name"): _vector_dimensions(_row_value(row, "options"))
            for row in rows
        }
        missing = REQUIRED_VECTOR_INDEXES - set(found)
        offline = {
            name: state
            for name, state in found.items()
            if name in REQUIRED_VECTOR_INDEXES and state != "ONLINE"
        }
        if missing:
            raise RuntimeError(f"Missing required Neo4j vector indexes: {sorted(missing)}")
        if offline:
            raise RuntimeError(f"Neo4j vector indexes are not ONLINE: {offline}")
        mismatched = {
            name: dimension
            for name, dimension in dimensions.items()
            if name in REQUIRED_VECTOR_INDEXES and dimension != self.expected_dimension
        }
        if mismatched:
            raise RuntimeError(
                f"Neo4j vector index dimensions do not match {self.expected_dimension}: {mismatched}"
            )

    def reachable_embedding_state(self, graph_id: str) -> dict[str, dict[str, Any]]:
        rows = list(
            self.session.run(
                (
                    "MATCH (d:Document {id: $graph_id})-[:CONTAINS*1..4]->(n) "
                    "WHERE n:Article OR n:Clause "
                    "RETURN n.id AS id, size(n.embedding) AS vector_size, "
                    "n.embedding_model AS model, n.embedding_provider AS provider, "
                    "n.embedding_dimension AS dimension, n.embedding_normalized AS normalized, "
                    "n.embedding_content_hash AS content_hash"
                ),
                graph_id=graph_id,
            )
        )
        return {
            str(_row_value(row, "id")): {
                "vector_size": _row_value(row, "vector_size"),
                "model": _row_value(row, "model"),
                "provider": _row_value(row, "provider"),
                "dimension": _row_value(row, "dimension"),
                "normalized": _row_value(row, "normalized"),
                "content_hash": _row_value(row, "content_hash"),
            }
            for row in rows
        }

    def stale_target_ids(
        self,
        graph_id: str,
        content_hashes: dict[str, str],
        *,
        model: str,
        provider: str,
        normalized: bool,
    ) -> list[str]:
        state = self.reachable_embedding_state(graph_id)
        unknown = set(content_hashes) - set(state)
        if unknown:
            raise ValueError(f"Embedding targets are not reachable from Document {graph_id}: {sorted(unknown)[:10]}")
        return [
            node_id
            for node_id, content_hash in content_hashes.items()
            if state[node_id] != {
                "vector_size": self.expected_dimension,
                "model": model,
                "provider": provider,
                "dimension": self.expected_dimension,
                "normalized": normalized,
                "content_hash": content_hash,
            }
        ]

    def write_embeddings(
        self,
        vectors_by_node_id: dict[str, list[float]],
        graph_id: str,
        *,
        content_hashes: dict[str, str] | None = None,
        model: str | None = None,
        provider: str | None = None,
        normalized: bool = True,
    ) -> None:
        state = self.reachable_embedding_state(graph_id)
        content_hashes = content_hashes or {}
        for node_id, embedding in vectors_by_node_id.items():
            if len(embedding) != self.expected_dimension:
                raise ValueError(
                    f"Embedding for {node_id} has dimension {len(embedding)}; expected {self.expected_dimension}"
                )
            if node_id not in state:
                raise ValueError(f"Embedding target is not reachable from Document {graph_id}: {node_id}")
            if node_id not in content_hashes or not model or not provider:
                raise ValueError(f"Embedding metadata is incomplete for {node_id}")
            result = self.session.run(
                (
                    "MATCH (n) "
                    "WHERE (n:Article OR n:Clause) AND n.id = $id "
                    "SET n.embedding = $embedding, n.embedding_model = $model, "
                    "n.embedding_provider = $provider, n.embedding_dimension = $dimension, "
                    "n.embedding_normalized = $normalized, n.embedding_content_hash = $content_hash, "
                    "n.embedding_created_at = datetime($created_at) "
                    "RETURN count(n) AS updated"
                ),
                id=node_id,
                embedding=embedding,
                model=model,
                provider=provider,
                dimension=self.expected_dimension,
                normalized=normalized,
                content_hash=content_hashes[node_id],
                created_at=datetime.now(timezone.utc).isoformat(),
            )
            rows = list(result)
            if not rows or int(_row_value(rows[0], "updated") or 0) != 1:
                raise RuntimeError(f"Embedding target disappeared during write: {node_id}")


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[key]


def _vector_dimensions(options: Any) -> int | None:
    if not isinstance(options, dict):
        return None
    index_config = options.get("indexConfig") or {}
    value = index_config.get("vector.dimensions")
    return int(value) if value is not None else None
