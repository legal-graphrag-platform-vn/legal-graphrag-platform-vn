import json
from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

# ==========================================
# CẤU HÌNH
# ==========================================
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password123" # Đổi mật khẩu của bạn

def main():
    # 1. Khởi tạo model BGE-M3
    print("Đang tải model BAAI/bge-m3 (Sẽ mất chút thời gian lần đầu)...")
    # bge-m3 cực kỳ mạnh cho tiếng Việt và text dài
    model = SentenceTransformer("BAAI/bge-m3")
    dim = model.get_sentence_embedding_dimension() # BGE-M3 là 1024 chiều
    print(f"✅ Tải model thành công! Số chiều Vector: {dim}")

    # 2. Đọc file
    print("\nĐang đọc file luat_doanh_nghiep.json...")
    with open('luat_doanh_nghiep.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    entities = data.get("entities", [])
    relations = data.get("relations", [])
    
    # 3. Tạo Vector Embedding cho Nodes
    print("Đang nhúng Vector (Embedding) cho các Node...")
    for entity in entities:
        # Gom toàn bộ các properties (trừ id và type) thành một chuỗi Key-Value
        # VD: "name: Luật DN | code: 59/2020 | text: Tổ chức cá nhân..."
        props = []
        for key, value in entity.items():
            if key not in ["id", "type", "embedding"] and value is not None:
                props.append(f"{key}: {value}")
        
        text_to_embed = " | ".join(props)
        
        # Chạy model sinh vector
        vector = model.encode(text_to_embed).tolist()
        entity["embedding"] = vector # Lưu luôn mảng float vào dict

    # 4. Đẩy lên Neo4j
    print("\nĐang kết nối Neo4j và đẩy dữ liệu...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    with driver.session() as session:
        # Xóa sạch db cũ & Index cũ
        session.run("MATCH (n) DETACH DELETE n")
        try:
            session.run("DROP INDEX entity_vector IF EXISTS")
        except:
            pass
            
        print("Đang tạo Nodes...")
        for entity in entities:
            node_id = entity.pop("id")
            node_label = entity.pop("type", "Entity")
            
            # LƯU Ý QUAN TRỌNG: 
            # Gắn thêm một Label chung là `BaseNode` cho tất cả các Node.
            # Lý do: Vector Index của Neo4j yêu cầu index trên 1 Label cụ thể.
            query = f"""
            MERGE (n:`{node_label}`:BaseNode {{id: $node_id}})
            SET n += $props
            """
            session.run(query, node_id=node_id, props=entity)
            
        print("Đang tạo Edges...")
        for rel in relations:
            source_id = rel.pop("source")
            target_id = rel.pop("target")
            rel_type = rel.pop("type", "RELATED_TO")
            
            query = f"""
            MATCH (source {{id: $source_id}})
            MATCH (target {{id: $target_id}})
            MERGE (source)-[r:`{rel_type}`]->(target)
            SET r += $props
            """
            session.run(query, source_id=source_id, target_id=target_id, props=rel)
            
        print("\nĐang thiết lập Native Vector Index trên Neo4j...")
        index_query = f"""
        CREATE VECTOR INDEX entity_vector IF NOT EXISTS
        FOR (n:BaseNode) ON (n.embedding)
        OPTIONS {{indexConfig: {{
          `vector.dimensions`: {dim},
          `vector.similarity_function`: 'cosine'
        }}}}
        """
        session.run(index_query)
        
    driver.close()
    print("✅ Hoàn tất! Tất cả dữ liệu và Vector đã nằm trong Neo4j.")

if __name__ == "__main__":
    main()
