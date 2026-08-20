import json
import os
from neo4j import GraphDatabase

# ==========================================
# CẤU HÌNH KẾT NỐI NEO4J
# Bạn hãy thay đổi username và password cho đúng với máy của bạn nhé!
# ==========================================
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password123"

def create_graph_from_json(file_path):
    # 1. Đọc file JSON
    print(f"Đang đọc file dữ liệu: {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    entities = data.get("entities", [])
    relations = data.get("relations", [])
    
    print(f"Tìm thấy {len(entities)} Entities và {len(relations)} Relations.")
    
    # 2. Kết nối tới Neo4j
    print("Đang kết nối tới Neo4j...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    with driver.session() as session:
        # Xóa toàn bộ database cũ (CẢNH BÁO: Chỉ dùng cho môi trường test)
        # Bỏ comment dòng dưới nếu muốn xóa sạch đồ thị cũ trước khi import
        session.run("MATCH (n) DETACH DELETE n")
        
        # 3. Tạo Nodes (Entities)
        print("Đang import Entities...")
        for entity in entities:
            node_id = entity.pop("id")
            node_label = entity.pop("type", "Entity") # Lấy type làm Label, mặc định là Entity
            
            # Xây dựng câu lệnh Cypher động để set các thuộc tính
            set_clause = ", ".join([f"n.{key} = ${key}" for key in entity.keys()])
            
            query = f"""
            MERGE (n:`{node_label}` {{id: $id}})
            SET {set_clause}
            """
            
            # Thêm id vào lại dictionary để truyền param
            entity["id"] = node_id
            session.run(query, **entity)
            
        # 4. Tạo Edges (Relationships)
        print("Đang import Relationships...")
        for rel in relations:
            source_id = rel.pop("source")
            target_id = rel.pop("target")
            rel_type = rel.pop("type", "RELATED_TO")
            
            # Xây dựng câu lệnh Cypher động để set thuộc tính cho cạnh
            set_clause = ""
            if len(rel) > 0:
                set_clause = "SET " + ", ".join([f"r.{key} = ${key}" for key in rel.keys()])
                
            query = f"""
            MATCH (source {{id: $source_id}})
            MATCH (target {{id: $target_id}})
            MERGE (source)-[r:`{rel_type}`]->(target)
            {set_clause}
            """
            
            # Thêm source_id và target_id vào để truyền param
            rel["source_id"] = source_id
            rel["target_id"] = target_id
            session.run(query, **rel)
            
    driver.close()
    print(" Import thành công! Mở Neo4j Browser để xem kết quả.")

if __name__ == "__main__":
    json_file = "test.json"
    create_graph_from_json(json_file)
