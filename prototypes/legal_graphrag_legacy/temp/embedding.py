import json
from FlagEmbedding import BGEM3FlagModel
import numpy as np

# ========================================
# 1. DỮ LIỆU JSON CỦA BẠN (Copy từ output)
# ========================================
json_data = {
  "entities": [
    {
      "id": "DN2020",
      "type": "Document",
      "name": "Luật Doanh nghiệp 2020",
      "description": "Văn bản quy định về thành lập, tổ chức quản lý và hoạt động của doanh nghiệp thuộc các thành phần kinh tế tại Việt Nam.",
      "properties": { "so_hieu": "59/2020/QH14", "ngay_ban_hanh": "17/06/2020" }
    },
    {
      "id": "CONCEPT_DN",
      "type": "Concept",
      "name": "Doanh nghiệp",
      "description": "Tổ chức có tên riêng, có tài sản, có trụ sở giao dịch ổn định, được thành lập hoặc đăng ký thành lập theo quy định của pháp luật.",
      "properties": {}
    }
  ],
  "relations": [
    { "head": "DN2020", "type": "QUY_DINH", "tail": "CONCEPT_DN" }
  ]
}

# ========================================
# 2. TẠO VĂN BẢN ĐỂ EMBED
# ========================================
def build_embedding_text(entity):
    """
    Tạo văn bản để embed từ entity, theo đúng chiến lược đã thống nhất:
    Type + Tên + Description + Thuộc tính (static)
    """
    # Bắt đầu với Type và Tên
    text_parts = [f"Type: {entity['type']}. Tên: {entity['name']}."]
    
    # Thêm Description
    if entity.get('description'):
        text_parts.append(f" Mô tả: {entity['description']}")
    
    # Thêm Properties (chỉ lấy các field static, không lấy số liệu động)
    if entity.get('properties') and len(entity['properties']) > 0:
        props_str = ", ".join([f"{k}={v}" for k, v in entity['properties'].items()])
        text_parts.append(f" Thuộc tính: {props_str}")
    
    return "".join(text_parts)

# Tạo văn bản embed cho từng entity
embed_texts = []
for entity in json_data['entities']:
    text = build_embedding_text(entity)
    embed_texts.append(text)
    print(f"📝 Entity [{entity['id']}]: {text[:150]}...")
    print()

# ========================================
# 3. EMBEDDING VỚI BGE-M3
# ========================================
print("="*60)
print("🔄 ĐANG TẠO EMBEDDING VỚI BGE-M3...")
print("="*60)

# Khởi tạo model (lần đầu sẽ tải model ~2.2GB)
model = BGEM3FlagModel('BAAI/bge-m3', use_fp16=True)

# Embed tất cả entity
embeddings = model.encode(embed_texts)['dense_vecs']

# ========================================
# 4. IN KẾT QUẢ
# ========================================
print("\n✅ EMBEDDING THÀNH CÔNG!")
print(f"📊 Số entity: {len(embeddings)}")
print(f"📐 Kích thước vector: {len(embeddings[0])} dimensions")
print("\n" + "="*60)

# In chi tiết từng entity
for i, entity in enumerate(json_data['entities']):
    print(f"\n📌 Entity: {entity['id']} - {entity['name']}")
    print(f"   Vector shape: {embeddings[i].shape}")
    print(f"   Vector sample (first 10 values): {embeddings[i][:10].round(4)}")
    print(f"   Norm: {np.linalg.norm(embeddings[i]):.4f}")

# ========================================
# 5. TEST SIMILARITY (Giả lập Query)
# ========================================
print("\n" + "="*60)
print("🧪 TEST TÌM KIẾM NGỮ NGHĨA (SIMILARITY SEARCH)")
print("="*60)

# Giả sử người dùng hỏi: "Công ty là gì?"
query = "Công ty là gì?"
query_embedding = model.encode(query)['dense_vecs']

# Tính similarity với từng entity
def cosine_similarity(a, b):
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

print(f"\n🔍 Query: \"{query}\"")
print("-" * 40)
for i, entity in enumerate(json_data['entities']):
    sim = cosine_similarity(query_embedding, embeddings[i])
    print(f"   Similarity với [{entity['id']}] {entity['name']}: {sim:.4f}")

# ========================================
# 6. LƯU VECTOR DB (Giả lập)
# ========================================
# Trong thực tế, bạn sẽ lưu vào FAISS/Qdrant/ChromaDB
print("\n" + "="*60)
print("💾 LƯU VECTOR DB (RA FILE JSON)")
print("="*60)

# Ví dụ mock data để lưu
vector_db_mock = []
for i, entity in enumerate(json_data['entities']):
    vector_db_mock.append({
        "id": entity['id'],
        "name": entity['name'],
        "type": entity['type'],
        "vector": embeddings[i].tolist(),  # Chuyển numpy array sang list
        "description": entity['description'],
        "properties": entity['properties']
    })

output_file = "vector_db_mock.json"
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(vector_db_mock, f, ensure_ascii=False, indent=2)

print(f"\n📦 Đã lưu toàn bộ dữ liệu và vector vào file: {output_file}")