from typing import List

from src.infrastructure.neo4j.retriever_repo import Neo4jRetrieverRepo
from src.retrieval.models import GraphPath, IntentType


class GraphRetriever:
    """
    Graph Expansion based on Intent's Traversal Policy.
    """

    def __init__(self, repo: Neo4jRetrieverRepo):
        self.repo = repo

    def expand(self, entry_ids: List[str], intent: IntentType, max_depth: int = 2) -> List[GraphPath]:
        """
        Duyệt đồ thị từ các ID lấy được từ Vector/BM25.
        """
        if not entry_ids:
            return []
            
        raw_results = self.repo.graph_expansion(entry_ids, intent.value, max_depth=max_depth)
        
        graph_paths = []
        for record in raw_results:
            path_nodes = record.get("path_nodes", [])
            path_relations = record.get("path_relations", [])
            
            # Khởi tạo path_description để giải thích Reasoning
            desc = " -> ".join([f"({n})" for n in path_nodes])
            
            graph_paths.append(GraphPath(
                nodes=path_nodes,
                relations=path_relations,
                path_description=f"Path: {desc}",
                is_temporal_valid=True # Sẽ được filter lại bởi Temporal Filter sau
            ))
            
        return graph_paths
