"""Async application service for read-only legal document exploration."""

from __future__ import annotations

import asyncio
import re
from functools import partial
from typing import Any, Protocol

from api.models import (
    ArticleDetail,
    ArticleResponse,
    ChapterDetail,
    ClauseDetail,
    DocumentDetail,
    DocumentListResponse,
    DocumentRelation,
    DocumentSummary,
    GraphData,
    GraphEdge,
    GraphNode,
    PageMeta,
    PointDetail,
)
from services.errors import BackendDocumentNotFoundError
from services.interfaces import AsyncRetrievalRunner


class DocumentBrowserRepo(Protocol):
    def list_documents(self, **parameters: object) -> dict[str, Any]: ...

    def get_document(self, document_id: str) -> dict[str, Any] | None: ...

    def get_article(self, article_id: str) -> dict[str, Any] | None: ...

    def get_graph(self, document_id: str, depth: int) -> dict[str, Any] | None: ...

    def graph_edges(self, node_ids: list[str]) -> list[dict[str, Any]]: ...

    def close(self) -> None: ...


class Neo4jDocumentBrowserService:
    def __init__(
        self,
        repo: DocumentBrowserRepo,
        runner: AsyncRetrievalRunner,
    ) -> None:
        self._repo = repo
        self._runner = runner

    async def list_documents(
        self,
        page: int,
        page_size: int,
        filters: dict,
    ) -> DocumentListResponse:
        result = await self._runner.run(
            partial(
                self._repo.list_documents,
                page=page,
                page_size=page_size,
                doc_type=filters.get("doc_type"),
                issuer=filters.get("issuer"),
                status=filters.get("status"),
                year=filters.get("year"),
            )
        )
        return DocumentListResponse(
            items=[DocumentSummary(**item) for item in result["items"]],
            pagination=PageMeta(page=page, page_size=page_size, total=result["total"]),
        )

    async def get_document_detail(self, doc_id: str) -> DocumentDetail:
        result = await self._runner.run(partial(self._repo.get_document, doc_id))
        if result is None:
            raise BackendDocumentNotFoundError(f"Document not found: {doc_id}")
        return _document_detail(result)

    async def get_article(self, article_id: str) -> ArticleResponse:
        result = await self._runner.run(partial(self._repo.get_article, article_id))
        if result is None:
            raise BackendDocumentNotFoundError(f"Article not found: {article_id}")
        row = result["article"]
        article = ArticleDetail(
            id=row["article_id"],
            number=str(row["article_number"]),
            title=row.get("article_title"),
            content_raw=row.get("article_content_raw") or "",
            clauses=_article_clauses(result["children"]),
        )
        return ArticleResponse(
            document=DocumentSummary(**_document_fields(row)),
            article=article,
            related_units=[],
        )

    async def get_document_graph(
        self,
        doc_id: str,
        depth: int,
        node_limit: int,
        edge_limit: int,
    ) -> GraphData:
        result = await self._runner.run(partial(self._repo.get_graph, doc_id, depth))
        if result is None:
            raise BackendDocumentNotFoundError(f"Document not found: {doc_id}")
        all_nodes = sorted(result["nodes"], key=_graph_node_key)
        selected_nodes = all_nodes[:node_limit]
        node_ids = [str(node["id"]) for node in selected_nodes]
        all_edges = await self._runner.run(partial(self._repo.graph_edges, node_ids))
        selected_edges = all_edges[:edge_limit]
        return GraphData(
            nodes=[
                GraphNode(
                    id=str(node["id"]),
                    label=str(node["label"]),
                    properties={
                        key: value
                        for key, value in {
                            "number": node.get("number"),
                            "title": node.get("title"),
                            "name": node.get("name"),
                        }.items()
                        if value is not None
                    },
                )
                for node in selected_nodes
            ],
            edges=[GraphEdge(**edge) for edge in selected_edges],
            truncated=(
                len(selected_nodes) < len(all_nodes)
                or len(selected_edges) < len(all_edges)
            ),
            total_nodes=len(all_nodes),
            total_edges=len(all_edges),
        )

    async def aclose(self) -> None:
        await asyncio.to_thread(self._repo.close)


def _document_detail(result: dict[str, Any]) -> DocumentDetail:
    document = result["document"]
    nodes = {str(node["id"]): node for node in result["nodes"]}
    children: dict[str, list[str]] = {}
    parent: dict[str, str] = {}
    for edge in result["structural_edges"]:
        source = str(edge["source"])
        target = str(edge["target"])
        children.setdefault(source, []).append(target)
        parent[target] = source

    clauses = {
        node_id: _clause(node, children, nodes)
        for node_id, node in nodes.items()
        if node["label"] == "Clause"
    }
    articles = {
        node_id: _article(node, children, clauses)
        for node_id, node in nodes.items()
        if node["label"] == "Article"
    }
    chapters = [
        ChapterDetail(
            id=node_id,
            number=str(node.get("number") or ""),
            title=node.get("title"),
            articles=_sorted_items(
                [
                    articles[item]
                    for item in children.get(node_id, [])
                    if item in articles
                ]
            ),
        )
        for node_id, node in nodes.items()
        if node["label"] == "Chapter"
    ]
    ungrouped = [
        article
        for node_id, article in articles.items()
        if parent.get(node_id) == document["id"]
    ]
    return DocumentDetail(
        **_document_fields(document),
        chapters=sorted(chapters, key=lambda item: _number_key(item.number)),
        ungrouped_articles=_sorted_items(ungrouped),
        relations=[DocumentRelation(**relation) for relation in result["relations"]],
    )


def _article_clauses(children: list[dict[str, Any]]) -> list[ClauseDetail]:
    nodes = {str(node["id"]): node for node in children}
    point_parent: dict[str, list[str]] = {}
    for point_id in [key for key, value in nodes.items() if value["label"] == "Point"]:
        prefix = point_id.rsplit("_p", 1)[0]
        point_parent.setdefault(prefix, []).append(point_id)
    clauses = []
    for node_id, node in nodes.items():
        if node["label"] != "Clause":
            continue
        clauses.append(
            ClauseDetail(
                id=node_id,
                number=str(node.get("number") or ""),
                content_raw=node.get("content_raw") or "",
                points=[_point(nodes[item]) for item in point_parent.get(node_id, [])],
            )
        )
    return sorted(clauses, key=lambda item: _number_key(item.number))


def _article(
    node: dict[str, Any],
    children: dict[str, list[str]],
    clauses: dict[str, ClauseDetail],
) -> ArticleDetail:
    return ArticleDetail(
        id=str(node["id"]),
        number=str(node.get("number") or ""),
        title=node.get("title"),
        content_raw=node.get("content_raw") or "",
        clauses=_sorted_items(
            [
                clauses[item]
                for item in children.get(str(node["id"]), [])
                if item in clauses
            ]
        ),
    )


def _clause(
    node: dict[str, Any],
    children: dict[str, list[str]],
    nodes: dict[str, dict[str, Any]],
) -> ClauseDetail:
    node_id = str(node["id"])
    return ClauseDetail(
        id=node_id,
        number=str(node.get("number") or ""),
        content_raw=node.get("content_raw") or "",
        points=[
            _point(nodes[item])
            for item in children.get(node_id, [])
            if nodes[item]["label"] == "Point"
        ],
    )


def _point(node: dict[str, Any]) -> PointDetail:
    return PointDetail(
        id=str(node["id"]),
        label=str(node.get("point_label") or ""),
        content_raw=node.get("content_raw") or "",
    )


def _document_fields(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "id",
            "number",
            "title",
            "doc_type",
            "issuer_name",
            "issued_date",
            "effective_from",
            "status",
        )
    }


def _sorted_items(items: list[Any]) -> list[Any]:
    return sorted(items, key=lambda item: _number_key(str(item.number)))


def _number_key(value: str) -> tuple[int, str]:
    match = re.match(r"^(\d+)", value)
    return (int(match.group(1)) if match else 10**9, value.casefold())


def _graph_node_key(node: dict[str, Any]) -> tuple[int, tuple[int, str], str]:
    rank = {
        "Document": 0,
        "Chapter": 1,
        "Article": 2,
        "Clause": 3,
        "Point": 4,
        "Issuer": 5,
        "LegalConcept": 6,
        "LegalSubject": 7,
        "LegalAction": 8,
    }.get(str(node["label"]), 99)
    return rank, _number_key(str(node.get("number") or "")), str(node["id"])
