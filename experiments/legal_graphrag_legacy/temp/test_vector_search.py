from neo4j import GraphDatabase
from sentence_transformers import SentenceTransformer

# ==========================================
# CẤU HÌNH KẾT NỐI
# ==========================================
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "password123" # Nhớ đổi pass của bạn

def search_entry_nodes(query_text, top_k=3):
    # 1. Khởi tạo model BGE-M3 (Sẽ load rất nhanh nếu đã tải trước đó)
    print("Đang khởi tạo model BGE-M3...")
    model = SentenceTransformer("BAAI/bge-m3")
    
    # 2. Nhúng nguyên cả câu hỏi thành Vector
    print(f"\nCâu hỏi gốc: '{query_text}'")
    print("Đang mã hóa câu hỏi thành Vector...")
    query_vector = model.encode(query_text).tolist()
    
    # 3. Kết nối Neo4j và tìm kiếm Vector (So sánh Cosine Similarity)
    print("Đang truy vấn Neo4j Vector Index...")
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    
    # Câu lệnh Cypher dùng Native Vector Search của Neo4j
    cypher_query = """
    CALL db.index.vector.queryNodes('entity_vector', $top_k, $query_vector) YIELD node, score
    RETURN node.id AS id, node.name AS name, score
    """
    
    with driver.session() as session:
        results = session.run(cypher_query, top_k=top_k, query_vector=query_vector)
        
        print("\n" + "="*50)
        print("🎯 TÌM THẤY CÁC ĐIỂM NEO (ENTRY NODES) SAU:")
        print("="*50)
        
        for record in results:
            node_id = record["id"]
            name = record["name"]
            score = record["score"]
            
            # Neo4j Cosine Similarity trả về giá trị từ 0 đến 1 (1 là giống y hệt)
            print(f"- [Node ID]: {node_id}")
            print(f"  [Tên Node]: {name}")
            print(f"  [Độ tương đồng - Score]: {score:.4f}\n")
            
    driver.close()

if __name__ == "__main__":
    # Test Case 1: Tìm khái niệm
    search_entry_nodes("Điều kiện thành lập công ty cổ phần là gì?", top_k=3)
    
    # Test Case 2: Tìm đối tượng có tính chất phức tạp
    search_entry_nodes("Cơ quan nhà nước có được phép góp vốn bằng quyền sử dụng đất không?", top_k=3)
    
    # Test Case 3: Chệch từ khóa (Xem BGE-M3 có bắt được ngữ nghĩa không)
    search_entry_nodes("Muốn mở doanh nghiệp chung vốn thì nộp giấy tờ ở đâu?", top_k=2)
