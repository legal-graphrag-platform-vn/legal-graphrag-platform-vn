"""Read-only verification of the canonical Neo4j Community bootstrap schema."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


EXPECTED_CONSTRAINTS = {
    "doc_id_unique", "ch_id_unique", "art_id_unique", "cls_id_unique", "pnt_id_unique",
    "iss_id_unique", "lc_id_unique", "ls_id_unique", "la_id_unique",
}
EXPECTED_USER_INDEXES = {
    "doc_number", "doc_doc_type", "doc_normative", "doc_legal_status", "doc_issuer_name",
    "art_number", "art_legal_status", "cls_legal_status", "issuer_name_idx",
    "lc_name", "ls_name", "la_name", "doc_temporal", "art_temporal", "cls_temporal",
    "amends_from", "replaces_from", "repeals_from", "issued_by_relation_id",
    "contains_relation_id", "refers_to_relation_id", "guides_relation_id",
    "amends_relation_id", "repeals_relation_id", "replaces_relation_id",
    "defines_relation_id", "regulates_relation_id", "requires_relation_id",
    "legal_article_clause_fulltext", "legal_point_fulltext", "article_embedding", "clause_embedding",
}
VECTOR_INDEXES = {"article_embedding", "clause_embedding"}
FORBIDDEN_LEGACY_INDEXES = {"legal_fulltext", "entity_vector"}


class SessionProtocol(Protocol):
    def run(self, cypher: str, **parameters: Any) -> Any: ...


class SchemaVerificationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class SchemaVerificationReport:
    constraints: tuple[str, ...]
    user_indexes: tuple[str, ...]


def verify_canonical_schema(session: SessionProtocol) -> SchemaVerificationReport:
    constraints = {str(row["name"]) for row in session.run("SHOW CONSTRAINTS YIELD name RETURN name")}
    index_rows = list(
        session.run("SHOW INDEXES YIELD name, type, state, options RETURN name, type, state, options")
    )
    user_rows = [row for row in index_rows if str(row["type"]).upper() != "LOOKUP"]
    indexes = {str(row["name"]) for row in user_rows}
    errors: list[str] = []

    missing_constraints = EXPECTED_CONSTRAINTS - constraints
    unexpected_constraints = constraints - EXPECTED_CONSTRAINTS
    missing_indexes = EXPECTED_USER_INDEXES - indexes
    legacy_indexes = FORBIDDEN_LEGACY_INDEXES & indexes
    unexpected_indexes = indexes - EXPECTED_USER_INDEXES - EXPECTED_CONSTRAINTS
    if missing_constraints:
        errors.append(f"Missing constraints: {sorted(missing_constraints)}")
    if unexpected_constraints:
        errors.append(f"Unexpected constraints: {sorted(unexpected_constraints)}")
    if missing_indexes:
        errors.append(f"Missing indexes: {sorted(missing_indexes)}")
    if legacy_indexes:
        errors.append(f"Forbidden legacy indexes: {sorted(legacy_indexes)}")
    if unexpected_indexes:
        errors.append(f"Unexpected user indexes: {sorted(unexpected_indexes)}")

    by_name = {str(row["name"]): row for row in user_rows}
    for name in EXPECTED_USER_INDEXES & indexes:
        if str(by_name[name]["state"]).upper() != "ONLINE":
            errors.append(f"Index is not ONLINE: {name}")
    for name in VECTOR_INDEXES & indexes:
        row = by_name[name]
        if str(row["type"]).upper() != "VECTOR":
            errors.append(f"Index is not VECTOR: {name}")
            continue
        config = (row["options"] or {}).get("indexConfig", {})
        if config.get("vector.dimensions") != 1024:
            errors.append(f"Vector dimension mismatch: {name}")
        if str(config.get("vector.similarity_function", "")).lower() != "cosine":
            errors.append(f"Vector similarity mismatch: {name}")

    if errors:
        raise SchemaVerificationError("; ".join(errors))
    return SchemaVerificationReport(tuple(sorted(constraints)), tuple(sorted(indexes)))
