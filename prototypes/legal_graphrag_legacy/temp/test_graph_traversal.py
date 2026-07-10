from neo4j import GraphDatabase
from traversal_policies import TRAVERSAL_POLICIES, MANDATORY_RELATIONS
import sys

sys.stdout.reconfigure(encoding='utf-8')

# ==========================================
# CẤU HÌNH KẾT NỐI
# ==========================================
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password123"

def build_context_from_graph(anchor_ids, intent="factual"):
    print(f"1. Đang lấy chiến lược Traversal cho Intent: '{intent}'...")
    policy = TRAVERSAL_POLICIES.get(intent)
    relations = policy["relations"]
    max_depth = policy["max_depth"]
    # Gộp thêm MANDATORY_RELATIONS (AMENDS, REPLACES, REPEALS)
    # Đây là bắt buộc để luôn lấy được phiên bản luật mới nhất / tình trạng hiệu lực
    all_relations = list(set(relations + MANDATORY_RELATIONS))
    
    # Format chuỗi quan hệ cho Cypher (VD: "REGULATES|DEFINES|AMENDS|REPLACES")
    rel_filter = "|".join(all_relations)
    
    print(f"   => Luật chơi: Chỉ quét qua các cạnh [{rel_filter}]")
    print(f"   => Bán kính tối đa: {max_depth} hops")
    print(f"   => Các Điểm Neo xuất phát: {anchor_ids}\n")

    # ========================================================
    # 2. XÂY DỰNG CYPHER QUERIES (Sử dụng Native Variable-length Path)
    # ========================================================
    
    # Query 1: Lấy tất cả các Node ĐỘC LẬP trong Subgraph
    node_query = f"""
    MATCH (start_node:BaseNode) WHERE start_node.id IN $anchor_ids
    MATCH path = (start_node)-[:{rel_filter}*0..{max_depth}]-(end_node:BaseNode)
    UNWIND nodes(path) AS n
    RETURN DISTINCT n.name AS name, n.text AS text, n.description AS description
    """
    
    # Query 2: Lấy tất cả các Relationships ĐỘC LẬP trong Subgraph
    edge_query = f"""
    MATCH (start_node:BaseNode) WHERE start_node.id IN $anchor_ids
    MATCH path = (start_node)-[:{rel_filter}*1..{max_depth}]-(end_node:BaseNode)
    UNWIND relationships(path) AS rel
    WITH DISTINCT rel
    RETURN startNode(rel).name AS start_name, type(rel) AS rel_type, endNode(rel).name AS end_name, rel.note AS note
    """
    
    print("2. Đang càn quét Đồ thị Neo4j bằng Multi-Source BFS...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    context_text = ""
    
    with driver.session() as session:
        # Lấy Nodes
        nodes_result = session.run(node_query, anchor_ids=anchor_ids)
        nodes_data = [record for record in nodes_result]
        
        # Lấy Edges
        edges_result = session.run(edge_query, anchor_ids=anchor_ids)
        edges_data = [record for record in edges_result]
        
        print(f"   ✅ Đã gom được {len(nodes_data)} Nodes và {len(edges_data)} Relationships pháp lý!")
        
        # ========================================================
        # 3. ĐÓNG GÓI NGỮ CẢNH (CONTEXT ASSEMBLY)
        # ========================================================
        context_text += "--- NGỮ CẢNH TỪ KNOWLEDGE GRAPH ---\n\n"
        
        context_text += "[THÔNG TIN CÁC THỰC THỂ]\n"
        for n in nodes_data:
            name = n["name"]
            # Lấy nội dung từ trường text (của Article) hoặc description (của Term/Actor)
            desc = n["text"] if n["text"] else n["description"]
            if desc:
                context_text += f"- {name}: {desc}\n"
            else:
                context_text += f"- {name}\n"
                
        context_text += "\n[MỐI LIÊN HỆ GIỮA CÁC THỰC THỂ]\n"
        for e in edges_data:
            start = e["start_name"]
            end = e["end_name"]
            rel_type = e["rel_type"]
            note = e["note"]
            
            if note:
                context_text += f"- ({start}) --[{rel_type}]--> ({end}) | Ghi chú: {note}\n"
            else:
                context_text += f"- ({start}) --[{rel_type}]--> ({end})\n"

    driver.close()
    return context_text

if __name__ == "__main__":
    # ========================================================
    # GIẢ LẬP: Sau Bước 2 (Vector Search), chúng ta bắt được 2 ID:
    # 1. CT_CoQuanNhaNuoc (Cơ quan nhà nước)
    # 2. TN_TaiSanGopVon (Tài sản góp vốn)
    # Từ câu hỏi gốc: "Cơ quan nhà nước có được phép góp vốn bằng quyền sử dụng đất không?"
    # ========================================================
    
    mock_anchor_ids = ["CT_CoQuanNhaNuoc", "TN_TaiSanGopVon"]
    
    # Chạy hàm Gom Context
    final_context = build_context_from_graph(mock_anchor_ids, intent="factual")
    
    print("\n" + "="*70)
    print("📦 CONTEXT ĐÃ ĐÓNG GÓI SẴN SÀNG ĐỂ BƠM CHO LLM:")
    print("="*70)
    print(final_context)
