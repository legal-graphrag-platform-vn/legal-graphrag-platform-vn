"""Read-only canonical lookup port for explicit references (Plan 19 §4).

The lookup confirms a parsed reference against Neo4j using parameterized queries
and verifies the parent chain via :CONTAINS. Canonical identity is never inferred
from an id prefix. The Neo4j adapter is import-safe; live behaviour is exercised
by integration tests, while the resolver's unit tests use an in-memory fake.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, TypeVar

from resolution.models import ExpectedUnitType, ExplicitReference, ResolvedCandidate
from src.shared.ontology.hierarchy import (
    MAX_DOCUMENT_TO_ARTICLE_DEPTH,
)

_ResultT = TypeVar("_ResultT")


class SyncCallRunner(Protocol):
    """Minimal runner surface: offload a blocking call to a worker thread."""

    async def run(self, call: Callable[[], _ResultT]) -> _ResultT: ...


_UNIT_DEPTH = 3  # article -> clause -> point spans at most a few CONTAINS hops.
_LOOKUP_LIMIT = 20


class CanonicalLookupPort(Protocol):
    async def lookup(
        self, reference: ExplicitReference
    ) -> tuple[ResolvedCandidate, ...]: ...


def build_canonical_label(
    *,
    article_number: str | None,
    clause_number: str | None,
    point_label: str | None,
    document_number: str | None,
    document_title: str | None,
    document_id: str,
) -> str:
    parts: list[str] = []
    if article_number:
        parts.append(f"Điều {article_number}")
    if clause_number:
        parts.append(f"Khoản {clause_number}")
    if point_label:
        parts.append(f"Điểm {point_label}")
    document_label = document_number or document_title or document_id
    if parts:
        return f"{' '.join(parts)} {document_label}".strip()
    return document_label


def row_to_candidate(row: dict[str, Any]) -> ResolvedCandidate:
    article_id = row.get("article_id")
    clause_id = row.get("clause_id")
    point_id = row.get("point_id")
    if point_id:
        node_id, node_type = point_id, ExpectedUnitType.POINT
    elif clause_id:
        node_id, node_type = clause_id, ExpectedUnitType.CLAUSE
    elif article_id:
        node_id, node_type = article_id, ExpectedUnitType.ARTICLE
    else:
        node_id, node_type = row["document_id"], ExpectedUnitType.DOCUMENT
    return ResolvedCandidate(
        node_id=node_id,
        node_type=node_type,
        canonical_label=build_canonical_label(
            article_number=row.get("article_number"),
            clause_number=row.get("clause_number"),
            point_label=row.get("point_label"),
            document_number=row.get("document_number"),
            document_title=row.get("document_title"),
            document_id=row["document_id"],
        ),
        document_id=row["document_id"],
        document_number=row.get("document_number"),
        article_id=article_id,
        article_number=row.get("article_number"),
        clause_id=clause_id,
        clause_number=row.get("clause_number"),
        point_id=point_id,
        point_label=row.get("point_label"),
        document_metadata={
            "doc_type": row.get("doc_type"),
            "issuer_name": row.get("issuer_name"),
            "legal_status": row.get("legal_status"),
        },
    )


def _build_query(reference: ExplicitReference) -> tuple[str, dict[str, Any]]:
    params: dict[str, Any] = {}
    lines = ["MATCH (document:Document)"]
    predicates: list[str] = []
    if reference.document_number:
        predicates.append("document.number = $document_number")
        params["document_number"] = reference.document_number
    if reference.law_name:
        predicates.append("toLower(document.title) CONTAINS toLower($law_name)")
        params["law_name"] = reference.law_name
    if reference.law_year:
        predicates.append("toString(document.issued_date) CONTAINS toString($law_year)")
        params["law_year"] = reference.law_year
    if predicates:
        lines.append("WHERE " + " AND ".join(predicates))

    ancestor = "document"
    if reference.article_number:
        lines.append(
            f"MATCH ({ancestor})-[:CONTAINS*1..{MAX_DOCUMENT_TO_ARTICLE_DEPTH}]->"
            "(article:Article {number: $article_number})"
        )
        params["article_number"] = reference.article_number
        ancestor = "article"
    if reference.clause_number:
        lines.append(
            f"MATCH ({ancestor})-[:CONTAINS*1..{_UNIT_DEPTH}]->"
            "(clause:Clause {number: $clause_number})"
        )
        params["clause_number"] = reference.clause_number
        ancestor = "clause"
    if reference.point_label:
        lines.append(
            f"MATCH ({ancestor})-[:CONTAINS*1..{_UNIT_DEPTH}]->"
            "(point:Point {label: $point_label})"
        )
        params["point_label"] = reference.point_label

    has_article = reference.article_number is not None
    has_clause = reference.clause_number is not None
    has_point = reference.point_label is not None
    projection = [
        "document.id AS document_id",
        "document.number AS document_number",
        "document.title AS document_title",
        "document.doc_type AS doc_type",
        "document.issuer_name AS issuer_name",
        "document.legal_status AS legal_status",
        ("article.id AS article_id" if has_article else "null AS article_id"),
        (
            "article.number AS article_number"
            if has_article
            else "null AS article_number"
        ),
        ("clause.id AS clause_id" if has_clause else "null AS clause_id"),
        ("clause.number AS clause_number" if has_clause else "null AS clause_number"),
        ("point.id AS point_id" if has_point else "null AS point_id"),
        ("point.label AS point_label" if has_point else "null AS point_label"),
    ]
    lines.append("RETURN DISTINCT " + ", ".join(projection))
    lines.append("ORDER BY document_id, article_id, clause_id, point_id")
    lines.append(f"LIMIT {_LOOKUP_LIMIT}")
    return "\n".join(lines), params


class Neo4jCanonicalLookupRepo:
    """Synchronous, parameterized Neo4j canonical lookup."""

    def __init__(self, driver: Any) -> None:
        self._driver = driver

    def lookup(self, reference: ExplicitReference) -> list[dict[str, Any]]:
        query, params = _build_query(reference)
        with self._driver.session() as session:
            return [dict(record) for record in session.run(query, **params)]


class Neo4jCanonicalLookup:
    """Async adapter that offloads the sync lookup onto the retrieval runner."""

    def __init__(
        self,
        repo: Neo4jCanonicalLookupRepo,
        runner: SyncCallRunner,
    ) -> None:
        self._repo = repo
        self._runner = runner

    async def lookup(
        self, reference: ExplicitReference
    ) -> tuple[ResolvedCandidate, ...]:
        rows = await self._runner.run(lambda: self._repo.lookup(reference))
        
        if len(rows) > 1 and reference.law_name:
            target_title = reference.law_name.lower().strip()
            exact_rows = []
            for row in rows:
                doc_title = row.get("document_title")
                if doc_title and doc_title.lower().strip() == target_title:
                    exact_rows.append(row)
            
            if exact_rows:
                rows = exact_rows
                
        return tuple(row_to_candidate(row) for row in rows)
