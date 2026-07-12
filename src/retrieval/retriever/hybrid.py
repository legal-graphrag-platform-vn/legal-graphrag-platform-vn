import time

from src.retrieval.context.context_builder import ContextBuilder
from src.retrieval.context.temporal_filter import TemporalFilter
from src.retrieval.evidence.verifier import EvidenceVerifier
from src.retrieval.fusion.reciprocal_rank_fusion import ReciprocalRankFusion
from src.retrieval.models import RetrievalContext
from src.retrieval.query.query_analyzer import QueryAnalyzer
from src.retrieval.reranking.base import BaseReranker
from src.retrieval.retriever.fulltext import FullTextRetriever
from src.retrieval.retriever.graph import GraphRetriever
from src.retrieval.retriever.vector import VectorRetriever


class HybridRetriever:
    """
    Orchestrator chính của Phase 2:
    Query -> Vector + BM25 -> RRF -> Graph Expansion -> Temporal Filter -> Rerank -> Verifier -> Context
    """

    def __init__(
        self,
        query_analyzer: QueryAnalyzer,
        vector_retriever: VectorRetriever,
        fulltext_retriever: FullTextRetriever,
        graph_retriever: GraphRetriever,
        temporal_filter: TemporalFilter,
        fusion: ReciprocalRankFusion,
        reranker: BaseReranker,
        context_builder: ContextBuilder,
    ):
        self.query_analyzer = query_analyzer
        self.vector_retriever = vector_retriever
        self.fulltext_retriever = fulltext_retriever
        self.graph_retriever = graph_retriever
        self.temporal_filter = temporal_filter
        self.fusion = fusion
        self.reranker = reranker
        self.context_builder = context_builder

    def retrieve(self, query: str, top_k: int = 20, final_k: int = 10) -> RetrievalContext:
        metrics = {}
        start_time = time.time()
        
        # 1. Analyze Query
        intent, temporal_query = self.query_analyzer.analyze(query)
        metrics["intent_latency_ms"] = int((time.time() - start_time) * 1000)
        
        # 2. Vector & BM25 Search
        v_start = time.time()
        vector_results = self.vector_retriever.retrieve(query, top_k=top_k)
        metrics["vector_hits"] = len(vector_results)
        metrics["vector_latency_ms"] = int((time.time() - v_start) * 1000)
        
        f_start = time.time()
        bm25_results = self.fulltext_retriever.retrieve(query, top_k=top_k)
        metrics["bm25_hits"] = len(bm25_results)
        metrics["bm25_latency_ms"] = int((time.time() - f_start) * 1000)
        
        # 3. RRF Fusion
        fused_units = self.fusion.fuse(vector_results, bm25_results, top_n=top_k)
        
        # 4. Graph Expansion
        g_start = time.time()
        entry_ids = [u.id for u in fused_units[:5]] # Chỉ expand từ top 5 để giảm tải
        # Logic config max_depth theo intent (default 2, multi_hop 3)
        max_depth = 3 if intent.value == "multi_hop" else 2
        graph_paths = self.graph_retriever.expand(entry_ids, intent, max_depth=max_depth)
        metrics["graph_paths_count"] = len(graph_paths)
        metrics["graph_latency_ms"] = int((time.time() - g_start) * 1000)
        
        # Lấy thêm các nodes từ graph để đưa vào pool unit nếu chúng chưa có trong fused_units
        # (Ở đây ta tạm thời chỉ rerank fused_units ban đầu để tối ưu, có thể mở rộng sau)
        
        # 5. Temporal Filter
        filtered_units = self.temporal_filter.filter_and_resolve(fused_units, temporal_query)
        metrics["temporal_filtered_count"] = len(fused_units) - len(filtered_units)
        
        # 6. Reranking
        r_start = time.time()
        reranked_units = self.reranker.rerank(query, filtered_units, top_n=final_k)
        metrics["reranker_latency_ms"] = int((time.time() - r_start) * 1000)
        
        # 7. Xây dựng Context
        metrics["total_pipeline_latency_ms"] = int((time.time() - start_time) * 1000)
        context = self.context_builder.build_context(
            query=query,
            intent=intent,
            temporal=temporal_query,
            units=reranked_units,
            graph_paths=graph_paths,
            metrics=metrics
        )
        
        return context
