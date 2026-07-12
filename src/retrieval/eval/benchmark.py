import json
import logging
from typing import Dict, List

from src.retrieval.eval.metrics import calculate_mrr, calculate_ndcg_at_k, calculate_recall_at_k
from src.retrieval.retriever.hybrid import HybridRetriever

logger = logging.getLogger(__name__)


class BenchmarkRunner:
    """
    Chạy bộ câu hỏi chuẩn (dev split) qua Retriever và tính toán các chỉ số Ablation.
    """

    def __init__(self, retriever: HybridRetriever):
        self.retriever = retriever

    def run(self, dataset_path: str, top_k: int = 5) -> Dict[str, float]:
        """
        Chạy benchmark. 
        Dataset format: [{"query": "...", "expected_ids": ["id1", "id2"]}]
        """
        with open(dataset_path, "r", encoding="utf-8") as f:
            dataset = json.load(f)
            
        total_queries = len(dataset)
        sum_recall = 0.0
        sum_mrr = 0.0
        sum_ndcg = 0.0
        
        for item in dataset:
            query = item["query"]
            expected_ids = item["expected_ids"]
            
            # Gọi Retriever
            context = self.retriever.retrieve(query, top_k=20, final_k=top_k)
            retrieved_ids = [unit.id for unit in context.retrieved_units]
            
            # Tính metrics cho từng câu hỏi
            recall = calculate_recall_at_k(retrieved_ids, expected_ids, k=top_k)
            mrr = calculate_mrr(retrieved_ids, expected_ids)
            ndcg = calculate_ndcg_at_k(retrieved_ids, expected_ids, k=top_k)
            
            sum_recall += recall
            sum_mrr += mrr
            sum_ndcg += ndcg
            
        # Trả về kết quả trung bình
        results = {
            f"Recall@{top_k}": sum_recall / total_queries if total_queries else 0.0,
            "MRR": sum_mrr / total_queries if total_queries else 0.0,
            f"nDCG@{top_k}": sum_ndcg / total_queries if total_queries else 0.0,
            "Total_Queries": total_queries
        }
        
        return results
