from typing import List

from src.infrastructure.neo4j.retriever_repo import Neo4jRetrieverRepo
from src.retrieval.models import RetrievedUnit


class FullTextRetriever:
    """
    FullText Retriever sử dụng Neo4j Full-Text Search (BM25) (article_fulltext, clause_fulltext).
    """

    def __init__(self, repo: Neo4jRetrieverRepo):
        self.repo = repo

    def retrieve(self, query: str, top_k: int = 10) -> List[RetrievedUnit]:
        """
        Tìm kiếm BM25 trên cả 2 index Article và Clause.
        """
        # Trong Neo4j Lucene queries, cần chú ý escape special characters nếu có.
        # Ở đây ta giả định string đã an toàn hoặc Neo4j handle tự động.
        
        half_k = max(1, top_k // 2)
        
        article_results = self.repo.fulltext_search("article_fulltext", query, k=half_k)
        clause_results = self.repo.fulltext_search("clause_fulltext", query, k=half_k)
        
        raw_results = article_results + clause_results
        
        retrieved_units = []
        for record in raw_results:
            label = record.get("label", "Article")
            effective_from = record.get("effective_from")
            effective_to = record.get("effective_to")
            
            unit_number = str(record.get("unit_number")) if record.get("unit_number") else None
            article_number = unit_number if label == "Article" else None
            clause_number = unit_number if label == "Clause" else None
            
            doc_number = record.get("document_number", "Unknown Document")
            citation_label = f"{label} {unit_number}, {doc_number}"
            
            unit = RetrievedUnit(
                id=record["id"],
                label=label,
                content_raw=record.get("content_raw", ""),
                title=record.get("title"),
                document_id=record.get("document_id", ""),
                document_number=doc_number,
                article_number=article_number,
                clause_number=clause_number,
                effective_from=effective_from.to_native() if hasattr(effective_from, 'to_native') else effective_from,
                effective_to=effective_to.to_native() if hasattr(effective_to, 'to_native') else effective_to,
                bm25_score=record.get("score", 0.0),
                citation_label=citation_label
            )
            retrieved_units.append(unit)
            
        # Sắp xếp lại theo BM25 score giảm dần
        retrieved_units.sort(key=lambda x: x.bm25_score or 0.0, reverse=True)
        return retrieved_units[:top_k]
