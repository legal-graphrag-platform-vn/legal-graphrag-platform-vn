"""Guarded Neo4j writer for pipeline M3 graph payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Mapping, Protocol

from src.pipeline.config import settings
from src.shared.ontology import validators as root_validator
from src.shared.ontology.payload_consistency_validator import validate_payload_consistency_or_raise


class WriteAttemptError(TypeError):
    """Raised when a raw payload bypasses the root write-time validation gate."""


class SessionProtocol(Protocol):
    def run(self, cypher: str, **parameters: Any) -> Any: ...

    def close(self) -> None: ...


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
        properties, temporal_cypher, temporal_parameters = _neo4j_properties("n", node.properties)
        cypher = f"MERGE (n:{node.node_type} {{id: $id}}) SET n += $properties {temporal_cypher}"
        self.session.run(
            cypher,
            id=node.id,
            properties=properties,
            **temporal_parameters,
        )

    def _merge_relation(self, relation: Any) -> None:
        relation_id = relation.properties.get("relation_id")
        if not relation_id:
            raise WriteAttemptError(f"Validated relation missing relation_id: {relation.relation_type}")
        properties, temporal_cypher, temporal_parameters = _neo4j_properties("r", relation.properties)
        cypher = (
            "MATCH (head {id: $head_id}) "
            "MATCH (tail {id: $tail_id}) "
            f"MERGE (head)-[r:{relation.relation_type} {{relation_id: $relation_id}}]->(tail) "
            f"SET r += $properties {temporal_cypher}"
        )
        self.session.run(
            cypher,
            head_id=relation.head_id,
            tail_id=relation.tail_id,
            relation_id=relation_id,
            properties=properties,
            **temporal_parameters,
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


@dataclass(slots=True)
class ManagedNeo4jSession:
    driver: Any
    session: SessionProtocol

    def run(self, cypher: str, **parameters: Any) -> Any:
        return self.session.run(cypher, **parameters)

    def close(self) -> None:
        try:
            self.session.close()
        finally:
            self.driver.close()


def create_neo4j_session() -> SessionProtocol:
    if not settings.neo4j_password:
        raise RuntimeError("Missing NEO4J_PASSWORD for write/embed command")
    try:
        from neo4j import GraphDatabase
    except ImportError as exc:
        raise RuntimeError("Install neo4j Python driver to use write/embed commands") from exc

    driver = GraphDatabase.driver(settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password))
    return ManagedNeo4jSession(driver=driver, session=driver.session())


DATE_PROPERTIES = {"effective_from", "effective_to", "issued_date"}
DATETIME_PROPERTIES = {"created_at", "updated_at"}


def _neo4j_properties(alias: str, raw_properties: Mapping[str, Any]) -> tuple[dict[str, Any], str, dict[str, str]]:
    properties = dict(raw_properties)
    assignments: list[str] = []
    parameters: dict[str, str] = {}
    for field in sorted(DATE_PROPERTIES | DATETIME_PROPERTIES):
        value = properties.pop(field, None)
        if value in (None, ""):
            continue
        parameter = f"{alias}_{field}"
        if field in DATE_PROPERTIES:
            serialized = _iso_date(value, field)
            assignments.append(f"SET {alias}.{field} = date(${parameter})")
        else:
            serialized = _iso_datetime(value, field)
            assignments.append(f"SET {alias}.{field} = datetime(${parameter})")
        parameters[parameter] = serialized
    return properties, " ".join(assignments), parameters


def _iso_date(value: Any, field: str) -> str:
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value)
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise WriteAttemptError(f"{field} must be ISO YYYY-MM-DD: {value}") from exc


def _iso_datetime(value: Any, field: str) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    text = str(value)
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WriteAttemptError(f"{field} must be an ISO datetime: {value}") from exc
    return text
