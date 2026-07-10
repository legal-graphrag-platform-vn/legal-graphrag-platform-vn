from clients.neo4j_client import Neo4jClient
from clients.embedding_client import EmbeddingClient
from core.traversal_policies import TRAVERSAL_POLICIES, MANDATORY_RELATIONS

class GraphRetriever:
    def __init__(self):
        self.db = Neo4jClient()
        self.embedder = EmbeddingClient()
        
    def find_entry_points(self, query, top_k=3):
        print("⏳ [Retriever] Đang tìm Điểm Neo (Vector Search)...")
        vector = self.embedder.embed_query(query)
        cypher = """
        CALL db.index.vector.queryNodes('entity_vector', $top_k, $query_vector) YIELD node, score
        RETURN node.id AS id, node.name AS name, score
        """
        results = self.db.execute_query(cypher, top_k=top_k, query_vector=vector)
        anchor_ids = [record["id"] for record in results]
        return anchor_ids
        
    def traverse_graph(self, anchor_ids, intent, temporal):
        print(f"⏳ [Retriever] Đang càn quét Đồ thị (Graph Traversal) với intent '{intent}'...")
        policy = TRAVERSAL_POLICIES.get(intent, TRAVERSAL_POLICIES["factual"]) # Fallback
        
        all_relations = list(set(policy["relations"] + MANDATORY_RELATIONS))
        rel_filter = "|".join(all_relations)
        max_depth = policy["max_depth"]
        
        temporal_type = temporal.get("temporal_type") if (temporal and temporal.get("has_temporal")) else None
        
        # Hybrid Filter: Hard filter cho mặc định/validity_check, Soft filter (gom hết) cho còn lại
        use_hard_filter = (not temporal_type) or (temporal_type == "validity_check")
        
        if use_hard_filter:
            print("⏳ [Retriever] Áp dụng Lọc Cứng (Hard Filter): Chỉ gom các văn bản ĐANG HIỆN HÀNH.")
        else:
            print("⏳ [Retriever] Áp dụng Lọc Mềm (Soft Filter): Gom toàn bộ các phiên bản lịch sử.")
            
        node_query = f"""
        MATCH (start_node:BaseNode) WHERE start_node.id IN $anchor_ids
        MATCH path = (start_node)-[:{rel_filter}*0..{max_depth}]-(end_node:BaseNode)
        UNWIND nodes(path) AS n
        WITH DISTINCT n
        """
        
        if use_hard_filter:
            node_query += "WHERE n.effective_to IS NULL\n"
            
        node_query += "RETURN n.name AS name, n.text AS text, n.description AS description, n.effective_from AS effective_from, n.effective_to AS effective_to\n"
        
        edge_query = f"""
        MATCH (start_node:BaseNode) WHERE start_node.id IN $anchor_ids
        MATCH path = (start_node)-[:{rel_filter}*1..{max_depth}]-(end_node:BaseNode)
        UNWIND relationships(path) AS rel
        WITH DISTINCT rel
        RETURN startNode(rel).name AS start_name, type(rel) AS rel_type, endNode(rel).name AS end_name, rel.note AS note
        """
        
        nodes = self.db.execute_query(node_query, anchor_ids=anchor_ids)
        edges = self.db.execute_query(edge_query, anchor_ids=anchor_ids)
        
        return self._format_context(nodes, edges)
        
    def _format_context(self, nodes, edges):
        context_text = "--- NGỮ CẢNH TỪ KNOWLEDGE GRAPH ---\n\n[THÔNG TIN CÁC THỰC THỂ]\n"
        for n in nodes:
            name = n["name"]
            desc = n["text"] if n["text"] else n["description"]
            
            # Đính kèm nhãn dán thời gian để LLM đối chiếu trong trường hợp Soft Filter
            date_info = []
            if n.get("effective_from"):
                date_info.append(f"Từ {n['effective_from']}")
            if n.get("effective_to"):
                date_info.append(f"đến {n['effective_to']}")
            date_str = f" [{' - '.join(date_info)}]" if date_info else ""
            
            context_text += f"- {name}{date_str}: {desc}\n" if desc else f"- {name}{date_str}\n"
                
        context_text += "\n[MỐI LIÊN HỆ GIỮA CÁC THỰC THỂ]\n"
        for e in edges:
            note_str = f" | Ghi chú: {e['note']}" if e['note'] else ""
            context_text += f"- ({e['start_name']}) --[{e['rel_type']}]--> ({e['end_name']}){note_str}\n"
            
        return context_text
