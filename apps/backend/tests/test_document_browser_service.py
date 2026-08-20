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
                _node(
                    "doc_ch1_sec1",
                    "Section",
                    "1",
                    title="Quy định chung",
                ),
                _node("doc_art1", "Article", "1", title="Phạm vi"),
                _node("doc_art1_cl1", "Clause", "1", content_raw="Nội dung"),
                _node("doc_art1_cl1_pa", "Point", point_label="a"),
            ],
            "structural_edges": [
                {"source": "doc", "target": "doc_ch1"},
                # Transitional legacy edge must not duplicate an Article that is
                # already nested under a verified Section.
                {"source": "doc_ch1", "target": "doc_art1"},
                {"source": "doc_ch1", "target": "doc_ch1_sec1"},
                {"source": "doc_ch1_sec1", "target": "doc_art1"},
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
        return [{"source": "doc", "target": "doc_art1", "relation_type": "CONTAINS"}]

    def close(self) -> None:
        self.closed = True


class FullHierarchyRepo(FakeDocumentRepo):
    def get_document(self, document_id: str):
        return {
            "document": _document(),
            "nodes": [
                _node("doc_part1", "Part", "I", title="Phần một"),
                _node("doc_ch1", "Chapter", "I", title="Chương một"),
                _node("doc_ch1_sec1", "Section", "1", title="Mục một"),
                _node(
                    "doc_ch1_sec1_subsec1",
                    "Subsection",
                    "1",
                    title="Tiểu mục một",
                ),
                _node("doc_art1", "Article", "1", title="Điều một"),
            ],
            "structural_edges": [
                {"source": "doc", "target": "doc_part1"},
                {"source": "doc_part1", "target": "doc_ch1"},
                {"source": "doc_ch1", "target": "doc_ch1_sec1"},
                {"source": "doc_ch1_sec1", "target": "doc_ch1_sec1_subsec1"},
                {"source": "doc_ch1_sec1_subsec1", "target": "doc_art1"},
            ],
            "relations": [],
        }


class AppendixRepo(FakeDocumentRepo):
    def get_document(self, document_id: str):
        return {
            "document": _document(),
            "nodes": [
                # Host Document's own body — Điều 1.
                _node("doc_art1", "Article", "1", title="Phạm vi"),
                # An Appendix owned directly by the Document, containing its
                # own Chapter -> Article structure per legal_ontology.md —
                # this Article 1 is scoped by the Appendix ID and must not
                # collide or merge with the host Document's own Điều 1 above.
                _node(
                    "doc_app1",
                    "Appendix",
                    "01",
                    title="Danh mục ngành nghề",
                    content_raw="Nội dung phụ lục đầy đủ.",
                    heading="PHỤ LỤC 01",
                    appendix_kind="LIST",
                ),
                _node("doc_app1_ch1", "Chapter", "1", title="Chương phụ lục"),
                _node("doc_app1_ch1_art1", "Article", "1", title="Điều phụ lục"),
                # An Article owned directly by the Appendix (no Chapter) —
                # exercises the Appendix's own ungrouped_articles path.
                _node("doc_app1_art2", "Article", "2", title="Điều rời trong phụ lục"),
            ],
            "structural_edges": [
                {"source": "doc", "target": "doc_art1"},
                {"source": "doc", "target": "doc_app1"},
                {"source": "doc_app1", "target": "doc_app1_ch1"},
                {"source": "doc_app1_ch1", "target": "doc_app1_ch1_art1"},
                {"source": "doc_app1", "target": "doc_app1_art2"},
            ],
            "relations": [],
        }


def test_document_browser_includes_appendix_with_its_own_substructure() -> None:
    async def scenario() -> None:
        service = Neo4jDocumentBrowserService(AppendixRepo(), InlineRunner())

        detail = await service.get_document_detail("doc")

        # Host Document's own Điều 1 is untouched — no leakage from the Appendix.
        assert [article.id for article in detail.ungrouped_articles] == ["doc_art1"]

        assert len(detail.appendices) == 1
        appendix = detail.appendices[0]
        assert appendix.id == "doc_app1"
        assert appendix.number == "01"
        assert appendix.heading == "PHỤ LỤC 01"
        assert appendix.appendix_kind == "LIST"
        assert appendix.content_raw == "Nội dung phụ lục đầy đủ."

        # Appendix owns its own Chapter -> Article substructure...
        assert appendix.chapters[0].id == "doc_app1_ch1"
        assert appendix.chapters[0].articles[0].id == "doc_app1_ch1_art1"
        # ...and its own directly-owned (ungrouped) Article, scoped by the
        # Appendix ID rather than the host Document.
        assert [a.id for a in appendix.ungrouped_articles] == ["doc_app1_art2"]

    asyncio.run(scenario())


def test_document_browser_builds_canonical_hierarchy() -> None:
    async def scenario() -> None:
        service = Neo4jDocumentBrowserService(FakeDocumentRepo(), InlineRunner())
        listing = await service.list_documents(1, 20, {})
        detail = await service.get_document_detail("doc")

        assert listing.pagination.total == 1
        assert detail.id == "doc"
        assert detail.chapters[0].articles == []
        section = detail.chapters[0].sections[0]
        assert section.id == "doc_ch1_sec1"
        assert section.title == "Quy định chung"
        assert section.articles[0].id == "doc_art1"
        clause = section.articles[0].clauses[0]
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


def test_document_browser_preserves_part_and_subsection_levels() -> None:
    async def scenario() -> None:
        service = Neo4jDocumentBrowserService(FullHierarchyRepo(), InlineRunner())

        detail = await service.get_document_detail("doc")

        assert detail.chapters == []
        part = detail.parts[0]
        assert part.id == "doc_part1"
        subsection = part.chapters[0].sections[0].subsections[0]
        assert subsection.id == "doc_ch1_sec1_subsec1"
        assert subsection.articles[0].id == "doc_art1"

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
        "heading": properties.get("heading"),
        "appendix_kind": properties.get("appendix_kind"),
    }
