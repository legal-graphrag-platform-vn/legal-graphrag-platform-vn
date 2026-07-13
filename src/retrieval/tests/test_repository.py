from src.infrastructure.neo4j.retriever_repo import Neo4jRetrieverRepo
from src.retrieval.models import RetrievalFilters


class FakeResult:
    def __iter__(self):
        return iter([])


class FakeSession:
    def __init__(self) -> None:
        self.closed = False
        self.query = ""
        self.parameters = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True

    def run(self, query, **parameters):
        self.query = query
        self.parameters = parameters
        return FakeResult()


class FakeDriver:
    def __init__(self) -> None:
        self.last_session = None

    def session(self):
        self.last_session = FakeSession()
        return self.last_session


def test_repository_parameterizes_filters_and_closes_session() -> None:
    driver = FakeDriver()
    repo = Neo4jRetrieverRepo(driver)
    filters = RetrievalFilters(document_ids=["doc"], legal_statuses=["ACTIVE"])

    assert repo.fulltext_search("index", "query", filters=filters, k=5) == []

    session = driver.last_session
    assert session.closed is True
    assert session.parameters["document_ids"] == ["doc"]
    assert session.parameters["legal_statuses"] == ["ACTIVE"]
    assert "CONTAINS*1..3" in session.query


def test_repository_rejects_unsupported_graph_depth_before_db_session() -> None:
    driver = FakeDriver()
    repo = Neo4jRetrieverRepo(driver)

    try:
        repo.graph_expansion(
            ["entry"],
            ("REFERS_TO",),
            "outgoing",
            4,
            filters=RetrievalFilters(),
        )
    except ValueError as exc:
        assert "depth" in str(exc)
    else:
        raise AssertionError("Unsupported traversal depth should fail")
    assert driver.last_session is None
