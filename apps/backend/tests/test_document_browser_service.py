from __future__ import annotations

import asyncio
from datetime import date

import pytest

from services.document_browser_service import Neo4jDocumentBrowserService
from services.errors import BackendDocumentNotFoundError


class InlineRunner:
    async def run(self, call):
        return call()

    async def aclose(self) -> int:
        return 0


class FakeDocumentRepo:
    def __init__(self) -> None:
        self.closed = False

    def list_documents(self, **parameters):
        return {"items": [_document()], "total": 1}

    def get_document(self, document_id: str):
        if document_id == "missing":
            return None
        return {
            "document": _document(),
            "nodes": [
                _node("doc_ch1", "Chapter", "1"),
                _node("doc_art1", "Article", "1", title="Phạm vi"),
                _node("doc_art1_cl1", "Clause", "1", content_raw="Nội dung"),
                _node("doc_art1_cl1_pa", "Point", point_label="a"),
            ],
            "structural_edges": [
                {"source": "doc", "target": "doc_ch1"},
                {"source": "doc_ch1", "target": "doc_art1"},
                {"source": "doc_art1", "target": "doc_art1_cl1"},
                {"source": "doc_art1_cl1", "target": "doc_art1_cl1_pa"},
            ],
            "relations": [],
        }

    def get_article(self, article_id: str):
        return None

    def get_graph(self, document_id: str, depth: int):
        if document_id == "missing":
            return None
        return {
            "nodes": [
                _node("concept", "LegalConcept", name="Khái niệm"),
                _node("doc_art1", "Article", "1"),
                _node("doc", "Document", "59/2020/QH14"),
            ]
        }

    def graph_edges(self, node_ids: list[str]):
        return [
            {"source": "doc", "target": "doc_art1", "relation_type": "CONTAINS"}
        ]

    def close(self) -> None:
        self.closed = True


def test_document_browser_builds_canonical_hierarchy() -> None:
    async def scenario() -> None:
        service = Neo4jDocumentBrowserService(FakeDocumentRepo(), InlineRunner())
        listing = await service.list_documents(1, 20, {})
        detail = await service.get_document_detail("doc")

        assert listing.pagination.total == 1
        assert detail.id == "doc"
        assert detail.chapters[0].articles[0].id == "doc_art1"
        clause = detail.chapters[0].articles[0].clauses[0]
        assert clause.id == "doc_art1_cl1"
        assert clause.points[0].label == "a"

    asyncio.run(scenario())


def test_document_graph_limits_nodes_and_reports_truncation() -> None:
    async def scenario() -> None:
        service = Neo4jDocumentBrowserService(FakeDocumentRepo(), InlineRunner())
        graph = await service.get_document_graph("doc", 1, 2, 10)

        assert [node.id for node in graph.nodes] == ["doc", "doc_art1"]
        assert graph.total_nodes == 3
        assert graph.truncated is True
        assert graph.edges[0].relation_type == "CONTAINS"

    asyncio.run(scenario())


def test_document_browser_not_found_is_typed_and_repo_closes() -> None:
    async def scenario() -> None:
        repo = FakeDocumentRepo()
        service = Neo4jDocumentBrowserService(repo, InlineRunner())

        with pytest.raises(BackendDocumentNotFoundError):
            await service.get_document_detail("missing")
        await service.aclose()
        assert repo.closed is True

    asyncio.run(scenario())


def _document() -> dict[str, object]:
    return {
        "id": "doc",
        "number": "59/2020/QH14",
        "title": "Luật thử nghiệm",
        "doc_type": "Law",
        "issuer_name": "Quốc hội",
        "issued_date": date(2020, 7, 1),
        "effective_from": date(2021, 1, 1),
        "status": "ACTIVE",
    }


def _node(
    node_id: str,
    label: str,
    number: str | None = None,
    **properties: object,
) -> dict[str, object]:
    return {
        "id": node_id,
        "label": label,
        "number": number,
        "title": properties.get("title"),
        "content_raw": properties.get("content_raw", ""),
        "point_label": properties.get("point_label"),
        "name": properties.get("name"),
    }
