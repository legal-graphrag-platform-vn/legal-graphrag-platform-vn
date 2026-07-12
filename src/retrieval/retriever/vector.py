from typing import List

from src.infrastructure.embedding.embedding_generator import EmbeddingGenerator
from src.infrastructure.neo4j.retriever_repo import Neo4jRetrieverRepo
from src.retrieval.models import RetrievedUnit


class VectorRetriever:
    """
    Vector Retriever sử dụng Neo4j Vector Index (article_embedding, clause_embedding).
    """

    def __init__(self, repo: Neo4jRetrieverRepo, embedding_generator: EmbeddingGenerator):
        self.repo = repo
        self.embedding_generator = embedding_generator

    def retrieve(self, query: str, top_k: int = 10) -> List[RetrievedUnit]:
        """
        Mã hoá query và tìm kiếm trên cả 2 index Article và Clause.
        """
        # 1. Embed query
        query_embedding = self.embedding_generator.encode(query)

        # 2. Query Neo4j (Article & Clause)
        # Trong thực tế, có thể query song song hoặc lấy mỗi bên k/2.
        half_k = max(1, top_k // 2)
        
        article_results = self.repo.vector_search("article_embedding", query_embedding, k=half_k)
        clause_results = self.repo.vector_search("clause_embedding", query_embedding, k=half_k)
        
        raw_results = article_results + clause_results
        
        # 3. Map sang RetrievedUnit
        retrieved_units = []
        for record in raw_results:
            label = record.get("label", "Article")
            # Parse dates
            effective_from = record.get("effective_from")
            effective_to = record.get("effective_to")
            
            # Map unit_number
            unit_number = str(record.get("unit_number")) if record.get("unit_number") else None
            article_number = unit_number if label == "Article" else None
            clause_number = unit_number if label == "Clause" else None
            
            # Tạo citation label
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
                vector_score=record.get("score", 0.0),
                citation_label=citation_label
            )
            retrieved_units.append(unit)
            
        # Sắp xếp lại theo vector score giảm dần và lấy top_k (đề phòng k lẻ)
        retrieved_units.sort(key=lambda x: x.vector_score or 0.0, reverse=True)
        return retrieved_units[:top_k]
