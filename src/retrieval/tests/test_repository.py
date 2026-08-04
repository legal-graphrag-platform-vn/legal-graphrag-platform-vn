import pytest

from src.infrastructure.neo4j.retriever_repo import Neo4jRetrieverRepo
from src.retrieval.models import RetrievalFilters
from src.shared.ontology.hierarchy import MAX_DOCUMENT_TO_CITABLE_UNIT_DEPTH


class FakeResult:
    def __init__(self, rows=None) -> None:
        self.rows = rows or []

    def __iter__(self):
        return iter(self.rows)


class FakeSession:
    def __init__(self, rows=None) -> None:
        self.closed = False
        self.query = ""
        self.parameters = {}
        self.rows = rows or []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.closed = True

    def run(self, query, **parameters):
        self.query = query
        self.parameters = parameters
        return FakeResult(self.rows)


class FakeDriver:
    def __init__(self, rows=None) -> None:
        self.last_session = None
        self.rows = rows or []

    def session(self):
        self.last_session = FakeSession(self.rows)
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
    assert f"CONTAINS*1..{MAX_DOCUMENT_TO_CITABLE_UNIT_DEPTH}" in session.query


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


def test_graph_projection_preserves_canonical_edge_endpoints_and_dates() -> None:
    driver = FakeDriver()
    repo = Neo4jRetrieverRepo(driver)

    assert (
        repo.graph_expansion(
            ["entry"],
            ("AMENDS",),
            "incoming",
            2,
            filters=RetrievalFilters(query_date=None),
        )
        == []
    )

    query = driver.last_session.query
    assert "startNode(rel).id" in query
    assert "endNode(rel).id" in query
    assert "effective_from: rel.effective_from" in query
    assert "effective_to: rel.effective_to" in query
    assert "citable_unit_id" in query


def test_structural_endpoint_lookup_is_read_only_parameterized_and_stably_ordered() -> (
    None
):
    rows = [{"node_id": "article-145", "label": "Article", "document_id": "doc"}]
    driver = FakeDriver(rows)
    repo = Neo4jRetrieverRepo(driver)
    hostile_number = "145'}) MATCH (secret) RETURN secret //"

    result = repo.lookup_structural_endpoints(
        label="Article",
        document_number=None,
        article_number=hostile_number,
        clause_number=None,
        point_label=None,
        filters=RetrievalFilters(document_ids=["doc"]),
        limit=20,
    )

    assert result == rows
    session = driver.last_session
    assert session.closed is True
    assert session.parameters["article_number"] == hostile_number
    assert hostile_number not in session.query
    assert session.parameters["document_ids"] == ["doc"]
    assert session.parameters["label"] == "Article"
    assert "ORDER BY node_id" in session.query
    assert "$label IN labels(node)" in session.query
    upper_query = session.query.upper()
    assert not any(
        keyword in upper_query
        for keyword in (" CREATE ", " MERGE ", " SET ", " DELETE ")
    )


def test_exact_path_lookup_uses_static_depth_template_and_parameterized_constraints() -> (
    None
):
    driver = FakeDriver()
    repo = Neo4jRetrieverRepo(driver)
    steps = [
        {"relation": "REFERS_TO", "direction": "outgoing", "next_label": "Clause"},
        {"relation": "REFERS_TO", "direction": "incoming", "next_label": "Clause"},
    ]

    assert (
        repo.lookup_exact_paths(
            anchor_id="anchor'}) MATCH (secret) //",
            target_id="target",
            steps=steps,
            filters=RetrievalFilters(document_ids=["doc"]),
            limit=21,
        )
        == []
    )

    session = driver.last_session
    assert session.parameters["anchor_id"] == "anchor'}) MATCH (secret) //"
    assert session.parameters["target_id"] == "target"
    assert session.parameters["relation_1"] == "REFERS_TO"
    assert session.parameters["direction_2"] == "incoming"
    assert session.parameters["next_label_2"] == "Clause"
    assert session.parameters["limit"] == 21
    assert "target mention" not in session.query.lower()
    assert "MATCH path = (node_0)-[edge_1]-(node_1)-[edge_2]-(node_2)" in session.query
    assert "startNode(edge_1)" in session.query
    assert "endNode(edge_1)" in session.query
    assert "ORDER BY" in session.query
    assert "LIMIT $limit" in session.query
    assert "secret" not in session.query
    upper_query = session.query.upper()
    assert not any(
        keyword in upper_query
        for keyword in (" CREATE ", " MERGE ", " SET ", " DELETE ")
    )


def test_exact_path_lookup_rejects_unsupported_depth_without_opening_session() -> None:
    driver = FakeDriver()
    repo = Neo4jRetrieverRepo(driver)

    with pytest.raises(ValueError, match="depth"):
        repo.lookup_exact_paths(
            anchor_id="anchor",
            target_id="target",
            steps=[
                {
                    "relation": "REFERS_TO",
                    "direction": "outgoing",
                    "next_label": "Clause",
                }
            ],
            filters=RetrievalFilters(),
            limit=21,
        )

    assert driver.last_session is None


def test_exact_path_lookup_has_a_distinct_static_depth_three_template() -> None:
    driver = FakeDriver()
    repo = Neo4jRetrieverRepo(driver)

    repo.lookup_exact_paths(
        anchor_id="anchor",
        target_id="target",
        steps=[
            {"relation": "REFERS_TO", "direction": "outgoing", "next_label": "Clause"},
            {"relation": "REFERS_TO", "direction": "outgoing", "next_label": "Clause"},
            {
                "relation": "DEFINES",
                "direction": "outgoing",
                "next_label": "LegalConcept",
            },
        ],
        filters=RetrievalFilters(),
        limit=21,
    )

    assert "-[edge_3]-(node_3)" in driver.last_session.query
    assert driver.last_session.parameters["relation_3"] == "DEFINES"
