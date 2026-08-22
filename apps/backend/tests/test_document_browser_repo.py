from __future__ import annotations

from src.infrastructure.neo4j.document_browser_repo import Neo4jDocumentBrowserRepo


class FakeSession:
    def __init__(self, results: list[list[dict]]) -> None:
        self._results = list(results)
        self.queries: list[str] = []

    def run(self, query: str, **parameters: object):
        self.queries.append(query)
        return self._results.pop(0)

    def __enter__(self) -> "FakeSession":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


class FakeDriver:
    def __init__(self, session: FakeSession) -> None:
        self._session = session

    def session(self) -> FakeSession:
        return self._session


def test_list_documents_excludes_nodes_without_id() -> None:
    """Crawl-stage placeholder nodes (title + source_url only, no id) must never
    surface via the document browser — they crash DocumentSummary validation
    and were never merged with the real ingested Document node."""
    session = FakeSession(results=[[{"total": 0}], []])
    repo = Neo4jDocumentBrowserRepo(FakeDriver(session))

    repo.list_documents(
        page=1, page_size=20, doc_type=None, issuer=None, status=None, year=None
    )

    assert len(session.queries) == 2
    for query in session.queries:
        assert "document.id IS NOT NULL" in query
