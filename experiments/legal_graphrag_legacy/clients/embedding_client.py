from sentence_transformers import SentenceTransformer

class EmbeddingClient:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(EmbeddingClient, cls).__new__(cls)
            print("⏳ Đang khởi tạo model BGE-M3 (Singleton)...")
            cls._instance.model = SentenceTransformer("BAAI/bge-m3")
        return cls._instance

    def embed_query(self, text):
        return self.model.encode(text).tolist()
