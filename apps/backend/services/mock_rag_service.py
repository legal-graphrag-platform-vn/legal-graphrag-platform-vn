"""
MockRAGService — dùng fixture JSON từ mock_data/.
Load fixture một lần trong __init__, không đọc file mỗi request.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

from api.models import (
    ArticleResponse,
    ChatRequest,
    ChatStreamEvent,
    ChatMetadataData,
    ChatTokenData,
    DocumentDetail,
    DocumentListResponse,
    DocumentSummary,
    GraphData,
    QueryRequest,
    RetrievalResponse,
)

MOCK_DATA_DIR = Path(__file__).resolve().parent.parent / "mock_data"


def _load(filename: str) -> dict:
    # 1.   Đọc fixture JSON một lần
    return json.loads((MOCK_DATA_DIR / filename).read_text(encoding="utf-8"))


class MockRAGService:
    def __init__(self, data_dir: Path = MOCK_DATA_DIR):
        # 2.   Load toàn bộ fixture vào memory khi khởi tạo service
        self._retrieval = _load("retrieval_context.json")
        self._doc_list = _load("document_list.json")
        self._doc_detail = _load("document_detail.json")
        self._doc_graph = _load("document_graph.json")

    async def retrieve(
        self,
        request: QueryRequest,
    ) -> RetrievalResponse:
        # 3.   Giữ schema thật; fixture chỉ mô phỏng nội dung retrieval
        response = RetrievalResponse(**self._retrieval)
        limit = request.top_k or len(response.retrieved_units)
        return response.model_copy(
            update={
                "query": request.query,
                "retrieved_units": response.retrieved_units[:limit],
            }
        )

    async def stream_chat(
        self,
        request: ChatRequest,
    ) -> AsyncIterator[ChatStreamEvent]:
        # 4.   Yield metadata event đầu tiên (1 lần duy nhất)
        metadata = ChatMetadataData(
            sources=[],
            intent="factual",
            retrieval_mode="mock",
        )
        yield ChatStreamEvent(event="metadata", data=metadata.model_dump(mode="json"))

        # 5.   Stream mock tokens word by word
        mock_text = (
            "Theo Điều 111 Luật Doanh nghiệp 59/2020/QH14, "
            "công ty cổ phần là doanh nghiệp có vốn điều lệ được chia thành các phần bằng nhau gọi là cổ phần, "
            "với số lượng cổ đông tối thiểu là 03 và không hạn chế số lượng tối đa."
        )
        for word in mock_text.split():
            yield ChatStreamEvent(
                event="token",
                data=ChatTokenData(content=word + " ").model_dump(mode="json"),
            )

        # 6.   Done event cuối cùng
        yield ChatStreamEvent(event="done", data={})

    async def list_documents(
        self,
        page: int,
        page_size: int,
        filters: dict,
    ) -> DocumentListResponse:
        # 7.   Apply minimal filter simulation để contract test có ý nghĩa
        all_items = list(self._doc_list["items"])

        if filters.get("status"):
            all_items = [i for i in all_items if i.get("status") == filters["status"]]
        if filters.get("doc_type"):
            all_items = [
                i for i in all_items if i.get("doc_type") == filters["doc_type"]
            ]
        if filters.get("year"):
            year_str = str(filters["year"])
            all_items = [
                i
                for i in all_items
                if (i.get("effective_from") or "").startswith(year_str)
            ]
        if filters.get("issuer"):
            issuer_q = filters["issuer"].lower()
            all_items = [
                i for i in all_items if issuer_q in (i.get("issuer_name") or "").lower()
            ]

        total = len(all_items)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = all_items[start:end]

        return DocumentListResponse(
            items=page_items,
            pagination={"page": page, "page_size": page_size, "total": total},
        )

    async def get_document_detail(self, doc_id: str) -> DocumentDetail:
        # 8.   Trả về fixture detail (không phân biệt doc_id trong mock)
        return DocumentDetail(**self._doc_detail)

    async def get_article(self, article_id: str) -> ArticleResponse:
        # 9.   Tìm article trong fixture detail
        detail = DocumentDetail(**self._doc_detail)
        # Tạo DocumentSummary từ DocumentDetail
        summary = DocumentSummary(
            id=detail.id,
            number=detail.number,
            title=detail.title,
            doc_type=detail.doc_type,
            issuer_name=detail.issuer_name,
            issued_date=detail.issued_date,
            effective_from=detail.effective_from,
            status=detail.status,
        )

        # 10.   Tìm article theo article_id trong chapters
        for chapter in detail.chapters:
            for article in chapter.articles:
                if article.id == article_id:
                    return ArticleResponse(document=summary, article=article)

        # 11.   Tìm trong ungrouped_articles
        for article in detail.ungrouped_articles:
            if article.id == article_id:
                return ArticleResponse(document=summary, article=article)

        # 12.   Fallback: trả article đầu tiên nếu không tìm thấy
        first_article = detail.chapters[0].articles[0] if detail.chapters else None
        if first_article:
            return ArticleResponse(document=summary, article=first_article)

        raise ValueError(f"Article {article_id} not found in mock data")

    async def get_document_graph(
        self,
        doc_id: str,
        depth: int,
        node_limit: int,
        edge_limit: int,
    ) -> GraphData:
        # 13.   Apply hard limits trên mock data để test truncation logic
        all_nodes = self._doc_graph.get("nodes", [])
        all_edges = self._doc_graph.get("edges", [])

        nodes = all_nodes[:node_limit]
        edges = all_edges[:edge_limit]
        total_nodes = len(all_nodes)
        total_edges = len(all_edges)

        return GraphData(
            nodes=nodes,
            edges=edges,
            truncated=(len(nodes) < total_nodes or len(edges) < total_edges),
            total_nodes=total_nodes,
            total_edges=total_edges,
        )
