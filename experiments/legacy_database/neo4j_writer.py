"""Guarded Neo4j write path.

The writer accepts only validated payloads. Raw payloads are rejected before
any MERGE statement can be emitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from src.shared.ontology.validators import (
    OntologyValidator,
    _VALIDATION_TOKEN,
    ValidatedGraphPayload,
    ValidatedNode,
    ValidatedRelation,
)
from src.shared.ontology.payload_consistency_validator import validate_payload_consistency_or_raise


class WriteAttemptError(TypeError):
    """Raised when a raw payload bypasses the shared validation gate."""


class SessionProtocol(Protocol):
    def run(self, cypher: str, **parameters: Any) -> Any: ...


@dataclass(slots=True)
class Neo4jWriter:
    """Emit MERGE queries only for validated graph payloads."""

    session: SessionProtocol

    def write(self, payload: ValidatedGraphPayload) -> None:
        if not isinstance(payload, ValidatedGraphPayload) or payload.validation_token is not _VALIDATION_TOKEN:
            raise WriteAttemptError(
                "Neo4jWriter.write expects a ValidatedGraphPayload. "
                "Use GraphIngestionService.ingest(...) or validate_graph_payload(...) first."
            )

        for node in payload.nodes:
            self._merge_node(node)
        for relation in payload.relations:
            self._merge_relation(relation)

    def _merge_node(self, node: ValidatedNode) -> None:
        properties = {key: value for key, value in node.properties.items() if key != "type"}
        cypher = (
            f"MERGE (n:{node.node_type} {{id: $id}}) "
            "SET n += $properties"
        )
        self.session.run(cypher, id=node.id, properties=properties)

    def _merge_relation(self, relation: ValidatedRelation) -> None:
        properties = dict(relation.properties)
        relation_id = properties.get("relation_id")
        if not relation_id:
            raise WriteAttemptError(f"Validated relation missing relation_id: {relation.relation_type}")

        cypher = (
            "MATCH (head {id: $head_id}) "
            "MATCH (tail {id: $tail_id}) "
            f"MERGE (head)-[r:{relation.relation_type} {{relation_id: $relation_id}}]->(tail) "
            "SET r += $properties"
        )
        self.session.run(
            cypher,
            head_id=relation.head_id,
            tail_id=relation.tail_id,
            relation_id=relation_id,
            properties=properties,
        )


@dataclass(slots=True)
class GraphIngestionService:
    """Single ingestion surface that forces all raw writes through validation."""

    validator: OntologyValidator
    writer: Neo4jWriter

    def ingest(self, payload: dict[str, Any] | ValidatedGraphPayload) -> ValidatedGraphPayload:
        if isinstance(payload, ValidatedGraphPayload):
            validated = payload
        else:
            validate_payload_consistency_or_raise(payload)
            validated = self.validator.validate_graph_payload(payload)
        self.writer.write(validated)
        return validated
