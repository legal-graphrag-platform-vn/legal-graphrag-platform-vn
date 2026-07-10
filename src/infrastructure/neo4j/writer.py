"""Guarded Neo4j writer for pipeline M3 graph payloads."""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol

from src.pipeline.config import settings


class WriteAttemptError(TypeError):
    """Raised when a raw payload bypasses the root write-time validation gate."""


class SessionProtocol(Protocol):
    def run(self, cypher: str, **parameters: Any) -> Any: ...


from src.shared.ontology import validators as root_validator
from src.shared.ontology.payload_consistency_validator import validate_payload_consistency_or_raise


def validate_graph_payload(payload: Mapping[str, Any]):
    return root_validator.OntologyValidator().validate_graph_payload(payload)


def _validated_graph_payload_type():
    return root_validator.ValidatedGraphPayload


def _validation_token():
    return root_validator._VALIDATION_TOKEN


@dataclass(slots=True)
class Neo4jWriter:
    session: SessionProtocol

    def write(self, payload: Any) -> None:
        if not isinstance(payload, _validated_graph_payload_type()) or payload.validation_token is not _validation_token():
            raise WriteAttemptError("Neo4jWriter.write expects a root ValidatedGraphPayload")
        for node in payload.nodes:
            self._merge_node(node)
        for relation in payload.relations:
            self._merge_relation(relation)

    def _merge_node(self, node: Any) -> None:
        cypher = f"MERGE (n:{node.node_type} {{id: $id}}) SET n += $properties"
        self.session.run(cypher, id=node.id, properties=node.properties)

    def _merge_relation(self, relation: Any) -> None:
        relation_id = relation.properties.get("relation_id")
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
            properties=relation.properties,
        )


@dataclass(slots=True)
class GraphIngestionService:
    writer: Neo4jWriter

    def ingest(self, payload: Mapping[str, Any] | Any):
        if isinstance(payload, _validated_graph_payload_type()):
            validated = payload
        else:
            validate_payload_consistency_or_raise(payload)
            validated = validate_graph_payload(payload)
        self.writer.write(validated)
        return validated


def create_neo4j_session() -> SessionProtocol:
    if not settings.neo4j_password:
        raise RuntimeError("Missing NEO4J_PASSWORD for write/embed command")
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("Install neo4j Python driver to use write/embed commands") from exc

    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    return driver.session()
