from typing import Any, Dict, List

from neo4j import Driver


class Neo4jRetrieverRepo:
    """
    Repository đóng gói các câu lệnh Cypher phục vụ cho quá trình Retrieval.
    """

    def __init__(self, driver: Driver):
        self.driver = driver

    def vector_search(self, index_name: str, query_embedding: List[float], k: int = 5) -> List[Dict[str, Any]]:
        """
        Thực thi Vector Search trên index tương ứng (article_embedding hoặc clause_embedding).
        Lấy kèm theo context của Document chứa unit đó.
        """
        # Node label phụ thuộc vào index. article_embedding -> Article, clause_embedding -> Clause.
        # Ta dùng OPTIONAL MATCH (d:Document)-[:CONTAINS*1..2]->(node) để lấy thông tin văn bản gốc.
        
        query = """
        CALL db.index.vector.queryNodes($index_name, $k, $query_embedding)
        YIELD node, score
        OPTIONAL MATCH (d:Document)-[:CONTAINS*1..2]->(node)
        RETURN
          node.id AS id,
          labels(node)[0] AS label,
          node.content_raw AS content_raw,
          node.title AS title,
          node.number AS unit_number,
          d.id AS document_id,
          d.number AS document_number,
          node.effective_from AS effective_from,
          node.effective_to AS effective_to,
          score
        """
        
        with self.driver.session() as session:
            result = session.run(query, index_name=index_name, k=k, query_embedding=query_embedding)
            return [dict(record) for record in result]

    def fulltext_search(self, index_name: str, text_query: str, k: int = 5) -> List[Dict[str, Any]]:
        """
        Thực thi FullText Search (BM25) trên index tương ứng.
        Lấy kèm theo context của Document.
        """
        query = """
        CALL db.index.fulltext.queryNodes($index_name, $text_query, {{limit: $k}})
        YIELD node, score
        OPTIONAL MATCH (d:Document)-[:CONTAINS*1..2]->(node)
        RETURN
          node.id AS id,
          labels(node)[0] AS label,
          node.content_raw AS content_raw,
          node.title AS title,
          node.number AS unit_number,
          d.id AS document_id,
          d.number AS document_number,
          node.effective_from AS effective_from,
          node.effective_to AS effective_to,
          score
        """
        
        with self.driver.session() as session:
            result = session.run(query, index_name=index_name, k=k, text_query=text_query)
            return [dict(record) for record in result]

    def graph_expansion(self, entry_ids: List[str], intent: str, max_depth: int = 2) -> List[Dict[str, Any]]:
        """
        Duyệt đồ thị từ các entry points (Vector/BM25) dựa trên Traversal Policy tương ứng của Intent.
        """
        
        # Traversal Direction Rules
        # definition: Article/Clause -> DEFINES -> LegalConcept
        # obligation: Article/Clause -> REGULATES/REQUIRES -> semantic nodes, + CONTAINS
        # validity: Incoming/Outgoing AMENDS/REPEALS/REPLACES
        # citation: REFERS_TO
        # hierarchy: CONTAINS
        
        policy_cypher = ""
        
        if intent == "definition":
            policy_cypher = f"MATCH path = (entry)-[:DEFINES*1..{max_depth}]->(related:LegalConcept)"
        elif intent in ["obligation", "factual"]:
            policy_cypher = f"MATCH path = (entry)-[:REGULATES|REQUIRES|CONTAINS*1..{max_depth}]->(related)"
        elif intent == "validity":
            policy_cypher = f"MATCH path = (entry)-[:AMENDS|REPEALS|REPLACES*1..{max_depth}]-(related)"
        elif intent == "citation":
            policy_cypher = f"MATCH path = (entry)-[:REFERS_TO*1..{max_depth}]->(related)"
        elif intent == "hierarchy":
            policy_cypher = f"MATCH path = (entry)-[:CONTAINS*1..{max_depth}]-(related)"
        else: # multi_hop
            policy_cypher = f"MATCH path = (entry)-[*1..{max_depth}]-(related)"
            
        query = f"""
        MATCH (entry)
        WHERE entry.id IN $entry_ids
        {policy_cypher}
        RETURN 
            [node IN nodes(path) | node.id] AS path_nodes,
            [rel IN relationships(path) | type(rel)] AS path_relations
        LIMIT 50
        """
        
        with self.driver.session() as session:
            result = session.run(query, entry_ids=entry_ids)
            return [dict(record) for record in result]
