"""Neo4j updater for Article/Clause embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class SessionProtocol(Protocol):
    def run(self, cypher: str, **parameters: Any) -> Any: ...


REQUIRED_VECTOR_INDEXES = {"article_embedding", "clause_embedding"}


@dataclass(slots=True)
class Neo4jEmbeddingWriter:
    session: SessionProtocol

    def verify_vector_indexes(self) -> None:
        rows = list(
            self.session.run(
                (
                    "SHOW INDEXES "
                    "YIELD name, type, state "
                    "WHERE type = 'VECTOR' "
                    "RETURN name, state"
                )
            )
        )
        found = {_row_value(row, "name"): _row_value(row, "state") for row in rows}
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

    def write_embeddings(self, vectors_by_node_id: dict[str, list[float]], graph_id: str) -> None:
        for node_id, embedding in vectors_by_node_id.items():
            if not node_id.startswith(f"{graph_id}_art"):
                raise ValueError(f"Embedding target is outside graph_id prefix {graph_id}: {node_id}")
            self.session.run(
                (
                    "MATCH (n) "
                    "WHERE (n:Article OR n:Clause) AND n.id = $id "
                    "SET n.embedding = $embedding"
                ),
                id=node_id,
                embedding=embedding,
            )


def _row_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return row[key]
