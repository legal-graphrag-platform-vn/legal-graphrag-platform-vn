from src.application.retrieval_factory import (
    RetrievalApplicationSettings,
    create_retrieval_runtime,
    inspect_retrieval_capabilities,
)
from src.retrieval.config import RetrievalConfig
from src.shared.retrieval_contract import RetrievalFilters


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class FakeSession:
    def __init__(self, indexes):
        self._indexes = indexes

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return None

    def run(self, query, **parameters):
        if "SHOW INDEXES" in query:
            return FakeResult(self._indexes)
        return FakeResult([])


class FakeDriver:
    def __init__(self, indexes):
        self._indexes = indexes
        self.closed = 0
        self.verified = 0

    def verify_connectivity(self):
        self.verified += 1

    def session(self):
        return FakeSession(self._indexes)

    def close(self):
        self.closed += 1


def test_disabled_dependencies_are_not_required_or_loaded() -> None:
    driver = FakeDriver(
        [
            {
                "name": "legal_article_clause_fulltext",
                "type": "FULLTEXT",
                "state": "ONLINE",
                "options": {},
            }
        ]
    )
    embedding_calls = 0

    def embedding_factory(**kwargs):
        nonlocal embedding_calls
        embedding_calls += 1
        raise AssertionError("disabled vector provider must not load")

    handle = create_retrieval_runtime(
        RetrievalConfig(
            vector_enabled=False,
            fulltext_enabled=True,
            intent_classifier_enabled=False,
        ),
        RetrievalApplicationSettings(NEO4J_URI="bolt://example:7687"),
        driver_factory=lambda uri, auth: driver,
        embedding_factory=embedding_factory,
    )
    handle.close()

    assert embedding_calls == 0
    assert driver.verified == 1
    assert driver.closed == 1


def test_factory_passes_explicit_reranker_contract() -> None:
    driver = FakeDriver(
        [
            {
                "name": "legal_article_clause_fulltext",
                "type": "FULLTEXT",
                "state": "ONLINE",
                "options": {},
            }
        ]
    )
    calls = []

    def reranker_factory(model_name, **kwargs):
        calls.append((model_name, kwargs))
        return object()

    handle = create_retrieval_runtime(
        RetrievalConfig(
            vector_enabled=False,
            fulltext_enabled=True,
            reranker_enabled=True,
            reranker_fp16=False,
            reranker_max_length=384,
            reranker_normalize=True,
            intent_classifier_enabled=False,
        ),
        RetrievalApplicationSettings(NEO4J_URI="bolt://example:7687"),
        driver_factory=lambda uri, auth: driver,
        reranker_factory=reranker_factory,
    )
    handle.close()

    assert calls == [
        (
            "BAAI/bge-reranker-v2-m3",
            {"use_fp16": False, "max_length": 384, "normalize": True},
        )
    ]


def test_vector_index_dimension_mismatch_fails_startup(monkeypatch) -> None:
    indexes = [
        {
            "name": name,
            "type": "VECTOR",
            "state": "ONLINE",
            "options": {"indexConfig": {"vector.dimensions": 768}},
        }
        for name in ("appendix_embedding", "article_embedding", "clause_embedding")
    ]
    indexes.append(
        {
            "name": "legal_article_clause_fulltext",
            "type": "FULLTEXT",
            "state": "ONLINE",
            "options": {},
        }
    )
    driver = FakeDriver(indexes)
    monkeypatch.setattr(
        "src.application.retrieval_factory.importlib.util.find_spec",
        lambda package: object(),
    )
    try:
        create_retrieval_runtime(
            RetrievalConfig(),
            RetrievalApplicationSettings(NEO4J_URI="bolt://example:7687"),
            driver_factory=lambda uri, auth: driver,
        )
    except Exception as exc:
        assert "does not match" in str(exc)
    else:
        raise AssertionError("Wrong vector dimension should fail startup")
    assert driver.closed == 1


def test_partial_factory_failure_closes_driver() -> None:
    driver = FakeDriver([])
    try:
        create_retrieval_runtime(
            RetrievalConfig(vector_enabled=False, fulltext_enabled=True),
            RetrievalApplicationSettings(NEO4J_URI="bolt://example:7687"),
            driver_factory=lambda uri, auth: driver,
        )
    except Exception as exc:
        assert "Missing enabled retrieval indexes" in str(exc)
    else:
        raise AssertionError("Missing enabled dependency should fail startup")
    assert driver.closed == 1


def _fulltext_only_driver() -> FakeDriver:
    return FakeDriver(
        [
            {
                "name": "legal_article_clause_fulltext",
                "type": "FULLTEXT",
                "state": "ONLINE",
                "options": {},
            }
        ]
    )


def test_intent_classifier_wired_when_enabled() -> None:
    driver = _fulltext_only_driver()
    sentinel = object()
    calls = 0

    def classifier_factory():
        nonlocal calls
        calls += 1
        return sentinel

    handle = create_retrieval_runtime(
        RetrievalConfig(
            vector_enabled=False,
            fulltext_enabled=True,
            intent_classifier_enabled=True,
        ),
        RetrievalApplicationSettings(NEO4J_URI="bolt://example:7687"),
        driver_factory=lambda uri, auth: driver,
        classifier_factory=classifier_factory,
    )
    try:
        assert calls == 1
        assert handle._runtime._router._classifier is sentinel
    finally:
        handle.close()


def test_intent_classifier_absent_when_disabled() -> None:
    driver = _fulltext_only_driver()

    def classifier_factory():
        raise AssertionError("classifier must not be built when disabled")

    handle = create_retrieval_runtime(
        RetrievalConfig(
            vector_enabled=False,
            fulltext_enabled=True,
            intent_classifier_enabled=False,
        ),
        RetrievalApplicationSettings(NEO4J_URI="bolt://example:7687"),
        driver_factory=lambda uri, auth: driver,
        classifier_factory=classifier_factory,
    )
    try:
        assert handle._runtime._router._classifier is None
    finally:
        handle.close()


def test_capability_inspection_closes_driver() -> None:
    driver = FakeDriver([])

    capabilities = inspect_retrieval_capabilities(
        RetrievalFilters(document_ids=["ldn_2020"]),
        RetrievalApplicationSettings(NEO4J_URI="bolt://example:7687"),
        driver_factory=lambda uri, auth: driver,
    )

    assert capabilities["guides_relations_available"] is False
    assert capabilities["multiple_versions_available"] is False
    assert driver.verified == 1
    assert driver.closed == 1
