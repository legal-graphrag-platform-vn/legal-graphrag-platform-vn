import json
import logging
from flask import Flask, request, Response
from flask_cors import CORS

from config import Config, ConfigurationError
from services.rag_service import RAGService
from providers.ollama import OllamaProvider
from providers.openai import OpenAIProvider
from providers.gemini import GeminiProvider

# 1.   Khởi tạo và cấu hình ứng dụng Flask
app = Flask(__name__)
CORS(app)  # Cho phép gọi chéo CORS từ Next.js Client (cổng 3000)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 2.   Kiểm tra tính hợp lệ của biến môi trường khi khởi chạy
try:
    Config.validate()
    logger.info(f"Cấu hình hợp lệ. Đang khởi chạy LLM Provider: {Config.LLM_PROVIDER}")
except ConfigurationError as e:
    logger.error(f"Lỗi khởi tạo cấu hình: {e}")
    # Ném ra lỗi để tránh chạy ngầm với cấu hình sai lệch
    raise e

# 3.   Khởi tạo LLM Provider tương ứng dựa trên cấu hình ENV
def get_llm_provider():
    if Config.LLM_PROVIDER == "openai":
        return OpenAIProvider()
    elif Config.LLM_PROVIDER == "gemini":
        return GeminiProvider()
    else:
        return OllamaProvider()

# 4.   Định nghĩa route API chính xử lý chat và stream câu trả lời qua SSE
@app.route("/api/chat", methods=["POST"])
def chat():
    # 1.   Lấy dữ liệu từ request JSON gửi lên từ Client
    data = request.json or {}
    message = data.get("message", "")
    history = data.get("history", [])

    if not message:
        return {"error": "Câu hỏi không được để trống"}, 400

    # 2.   Thiết lập ngữ cảnh rỗng (chưa thực hiện truy vấn RAG)
    context = ""
    sources = []

    # 3.   Định nghĩa Generator sinh dữ liệu stream dạng Server-Sent Events (SSE)
    def generate():
        provider = get_llm_provider()
        
        # A.   Gửi thông tin nguồn tài liệu trích dẫn rỗng dưới dạng metadata
        metadata = {
            "type": "metadata",
            "sources": sources
        }
        yield f"data: {json.dumps(metadata, ensure_ascii=False)}\n\n"

        # B.   Stream từng chunk câu trả lời sinh ra từ LLM
        logger.info("Bắt đầu stream câu trả lời từ LLM...")
        for chunk in provider.stream_chat(message, context, history):
            content_payload = {
                "type": "content",
                "content": chunk
            }
            yield f"data: {json.dumps(content_payload, ensure_ascii=False)}\n\n"

        # C.   Gửi tín hiệu kết thúc stream
        logger.info("Kết thúc stream câu trả lời.")
        yield "data: [DONE]\n\n"

    # 4.   Trả về HTTP Response với Content-Type là text/event-stream hỗ trợ streaming
    return Response(generate(), mimetype="text/event-stream")

# 5.   Khởi chạy Flask server
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
