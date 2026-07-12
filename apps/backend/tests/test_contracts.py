"""
Contract tests — FastAPI backend mock mode.
Chạy: cd apps/backend && PYTHONPATH=. pytest tests/ -v
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from main import create_app
from settings import Settings


@pytest.fixture(scope="module")
def client():
    """TestClient với APP_MODE=mock — không cần Neo4j."""
    app = create_app(Settings(app_mode="mock"))
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Settings & Startup
# ---------------------------------------------------------------------------

def test_mock_mode_starts_without_neo4j():
    """Mock mode không cần NEO4J_* config."""
    app = create_app(Settings(app_mode="mock"))
    with TestClient(app) as client:
        resp = client.get("/docs")
        assert resp.status_code == 200


def test_graphrag_mode_fails_when_credentials_missing():
    """graphrag mode phải raise khi thiếu NEO4J_*."""
    with pytest.raises(RuntimeError, match="NEO4J"):
        create_app(Settings(app_mode="graphrag"))


# ---------------------------------------------------------------------------
# Chat SSE Contract
# ---------------------------------------------------------------------------

def test_chat_sse_contains_named_events(client: TestClient):
    """Stream phải chứa event: metadata và event: token."""
    with client.stream("POST", "/api/v1/chat", json={"message": "Điều kiện thành lập công ty?"}
    ) as resp:
        assert resp.status_code == 200
        raw = resp.read().decode("utf-8")

    assert "event: metadata" in raw
    assert "event: token" in raw
    assert "event: done" in raw


def test_chat_sse_metadata_sent_only_once(client: TestClient):
    """event: metadata chỉ được gửi 1 lần."""
    with client.stream("POST", "/api/v1/chat", json={"message": "test"}) as resp:
        raw = resp.read().decode("utf-8")

    assert raw.count("event: metadata") == 1


def test_chat_sse_headers_correct(client: TestClient):
    """Response headers phải đúng cho SSE."""
    with client.stream("POST", "/api/v1/chat", json={"message": "test"}) as resp:
        assert resp.headers["content-type"] == "text/event-stream; charset=utf-8"
        assert resp.headers.get("cache-control") == "no-cache"


def test_chat_sse_unicode_tieng_viet(client: TestClient):
    """Unicode tiếng Việt phải được encode đúng, không bị escape thành \\uXXXX."""
    with client.stream("POST", "/api/v1/chat", json={"message": "test"}) as resp:
        raw = resp.read().decode("utf-8")
    # Các từ tiếng Việt phải xuất hiện dưới dạng UTF-8 thật, không phải \\uXXXX
    assert "\\u" not in raw or "công" in raw  # ensure_ascii=False hoạt động
    assert "Điều" in raw or "điều" in raw or "nghiệp" in raw


def test_chat_no_answer_field_in_metadata(client: TestClient):
    """Metadata event không được chứa answer field."""
    import json
    with client.stream("POST", "/api/v1/chat", json={"message": "test"}) as resp:
        raw = resp.read().decode("utf-8")

    # Parse metadata event
    for line in raw.split("\n"):
        if line.startswith("data: ") and "intent" in line:
            data = json.loads(line[6:])
            assert "answer" not in data
            break


# ---------------------------------------------------------------------------
# Query Contract
# ---------------------------------------------------------------------------

def test_query_response_has_no_answer_field(client: TestClient):
    """RetrievalResponse không được có field `answer`."""
    resp = client.post("/api/v1/query", json={"query": "công ty cổ phần"})
    assert resp.status_code == 200
    data = resp.json()
    assert "answer" not in data
    assert "retrieved_units" in data
    assert "intent" in data
    assert "retrieval_mode" in data


def test_query_accepts_temporal_date(client: TestClient):
    """Query với temporal_date phải được chấp nhận."""
    resp = client.post(
        "/api/v1/query",
        json={"query": "Điều 111", "temporal_date": "2020-06-17"},
    )
    assert resp.status_code == 200


def test_query_top_k_max_enforced(client: TestClient):
    """top_k > 50 phải bị reject."""
    resp = client.post("/api/v1/query", json={"query": "test", "top_k": 100})
    assert resp.status_code == 422


def test_query_empty_message_rejected(client: TestClient):
    """Query rỗng phải bị reject."""
    resp = client.post("/api/v1/query", json={"query": ""})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Document List Contract
# ---------------------------------------------------------------------------

def test_document_list_returns_pagination_meta(client: TestClient):
    """Response phải có pagination metadata."""
    resp = client.get("/api/v1/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "pagination" in data
    assert "page" in data["pagination"]
    assert "total" in data["pagination"]


def test_document_list_filter_by_status(client: TestClient):
    """Filter by status=ACTIVE chỉ trả ACTIVE items."""
    resp = client.get("/api/v1/documents?status=ACTIVE")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["items"]:
        assert item["status"] == "ACTIVE"


def test_document_list_filter_by_doc_type(client: TestClient):
    """Filter by doc_type=Law chỉ trả Law items."""
    resp = client.get("/api/v1/documents?doc_type=Law")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["items"]:
        assert item["doc_type"] == "Law"


def test_document_list_filter_by_year(client: TestClient):
    """Filter by year=2021 chỉ trả items có effective_from bắt đầu bằng 2021."""
    resp = client.get("/api/v1/documents?year=2021")
    assert resp.status_code == 200
    data = resp.json()
    for item in data["items"]:
        assert item.get("effective_from", "").startswith("2021")


# ---------------------------------------------------------------------------
# Document Detail Contract
# ---------------------------------------------------------------------------

def test_document_detail_has_chapter_hierarchy(client: TestClient):
    """DocumentDetail phải có chapters với articles."""
    resp = client.get("/api/v1/documents/ldn_2020")
    assert resp.status_code == 200
    data = resp.json()
    assert "chapters" in data
    assert len(data["chapters"]) > 0
    assert "articles" in data["chapters"][0]


def test_document_detail_has_ungrouped_articles_field(client: TestClient):
    """DocumentDetail phải có ungrouped_articles field (có thể rỗng)."""
    resp = client.get("/api/v1/documents/ldn_2020")
    assert resp.status_code == 200
    data = resp.json()
    assert "ungrouped_articles" in data


def test_document_detail_has_relations(client: TestClient):
    """DocumentDetail phải có relations."""
    resp = client.get("/api/v1/documents/ldn_2020")
    assert resp.status_code == 200
    data = resp.json()
    assert "relations" in data


# ---------------------------------------------------------------------------
# Graph Contract
# ---------------------------------------------------------------------------

def test_document_graph_returns_nodes_and_edges(client: TestClient):
    """Graph endpoint phải trả nodes và edges."""
    resp = client.get("/api/v1/documents/ldn_2020/graph")
    assert resp.status_code == 200
    data = resp.json()
    assert "nodes" in data
    assert "edges" in data
    assert "truncated" in data


def test_document_graph_depth_limit_enforced(client: TestClient):
    """depth > 2 phải bị reject."""
    resp = client.get("/api/v1/documents/ldn_2020/graph?depth=3")
    assert resp.status_code == 422


def test_document_graph_node_limit_enforced(client: TestClient):
    """node_limit > 500 phải bị reject."""
    resp = client.get("/api/v1/documents/ldn_2020/graph?node_limit=501")
    assert resp.status_code == 422


def test_document_graph_edge_limit_enforced(client: TestClient):
    """edge_limit > 1000 phải bị reject."""
    resp = client.get("/api/v1/documents/ldn_2020/graph?edge_limit=1001")
    assert resp.status_code == 422


def test_document_graph_truncated_flag(client: TestClient):
    """Khi limit nhỏ hơn total data, truncated=True."""
    resp = client.get("/api/v1/documents/ldn_2020/graph?node_limit=1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["truncated"] is True
    assert data["total_nodes"] is not None
    assert data["total_nodes"] > 1


# ---------------------------------------------------------------------------
# Article Contract
# ---------------------------------------------------------------------------

def test_article_endpoint_returns_parent_document(client: TestClient):
    """ArticleResponse phải chứa parent DocumentSummary."""
    resp = client.get("/api/v1/articles/ldn_2020_art111")
    assert resp.status_code == 200
    data = resp.json()
    assert "document" in data
    assert "article" in data
    assert "number" in data["document"]
    assert "number" in data["article"]


# ---------------------------------------------------------------------------
# Contract Parity
# ---------------------------------------------------------------------------

def test_document_legal_status_matches_ontology():
    """DocumentLegalStatus enum phải match src/shared/ontology/contract.py."""
    import sys
    sys.path.insert(0, "../..")
    from api.models import DocumentLegalStatus
    from src.shared.ontology.contract import DOCUMENT_LEGAL_STATUSES

    api_values = {s.value for s in DocumentLegalStatus}
    assert api_values == DOCUMENT_LEGAL_STATUSES, (
        f"Mismatch! API: {api_values}, Ontology: {DOCUMENT_LEGAL_STATUSES}"
    )
