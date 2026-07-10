import json
import sys
from neo4j import GraphDatabase

# Cấu hình hiển thị tiếng Việt trên Terminal Windows
sys.stdout.reconfigure(encoding='utf-8')

# ========================================
# 1. CẤU HÌNH KẾT NỐI NEO4J
# ========================================
# Sửa lại URI, Username và Password theo môi trường Neo4j của bạn
URI = "bolt://localhost:7687"
AUTH = ("neo4j", "password123") # Thay "password123" bằng mật khẩu của bạn

def build_graph(file_path):
    # ========================================
    # 2. ĐỌC DỮ LIỆU JSON
    # ========================================
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    entities = data.get('entities', [])
    relations = data.get('relations', [])
    
    print(f"📥 Đã đọc {len(entities)} entities và {len(relations)} relations từ {file_path}")

    # Khởi tạo kết nối với Neo4j
    driver = GraphDatabase.driver(URI, auth=AUTH)
    
    try:
        # TÙY CHỌN: Xóa toàn bộ dữ liệu cũ (Uncomment dòng dưới nếu muốn dọn sạch DB trước khi chạy)
        # driver.execute_query("MATCH (n) DETACH DELETE n")
        # print("🧹 Đã dọn dẹp database cũ.")

        # ========================================
        # 3. TẠO NODES (THỰC THỂ)
        # ========================================
        for entity in entities:
            e_id = entity['id']
            e_type = entity['type'] # Neo4j Node Label: Document, Concept, Organization...
            e_name = entity['name']
            e_desc = entity.get('description', '')
            
            # Gộp các thuộc tính lại để lưu vào Neo4j
            props = entity.get('properties', {})
            props['id'] = e_id
            props['name'] = e_name
            props['description'] = e_desc

            # Dùng MERGE để tạo mới nếu chưa có, hoặc cập nhật nếu đã tồn tại
            query = f"""
            MERGE (n:`{e_type}` {{id: $id}})
            SET n += $props
            """
            
            driver.execute_query(query, id=e_id, props=props)
            print(f"🟢 Đã tạo Node: [{e_type}] {e_name}")

        # ========================================
        # 4. TẠO RELATIONSHIPS (QUAN HỆ)
        # ========================================
        for rel in relations:
            head_id = rel['head']
            tail_id = rel['tail']
            rel_type = rel['type'] # Quan hệ: QUY_DINH, BAN_HANH...

            # TÌm 2 node đã tạo và nối chúng lại
            query = f"""
            MATCH (a {{id: $head_id}})
            MATCH (b {{id: $tail_id}})
            MERGE (a)-[r:`{rel_type}`]->(b)
            """
            
            driver.execute_query(query, head_id=head_id, tail_id=tail_id)
            print(f"🔗 Đã tạo Relation: ({head_id}) -[{rel_type}]-> ({tail_id})")
            
    except Exception as e:
        print(f"❌ Lỗi khi thao tác với Neo4j: {e}")
    finally:
        driver.close()
        print("\n✅ HOÀN TẤT XÂY DỰNG GRAPH TRÊN NEO4J!")

if __name__ == "__main__":
    # Đọc từ file JSON chứa entity & relation (bạn có thể thay bằng extracted_data.json)
    build_graph("test.json")
