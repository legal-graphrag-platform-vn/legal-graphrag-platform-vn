# Nguyên Tắc Phát Triển Máy Chủ (Backend Developer & Agent Guidelines)

Tài liệu này định nghĩa cấu trúc thư mục, quy tắc viết code và hướng dẫn dành cho AI Agents khi tham gia phát triển repo `chat-server`.

---

## 1. Cấu Trúc Thư Mục (Server Structure)

```text
chat-server/
├── AGENTS.md                  # Hướng dẫn lập trình Backend (nằm trong repo này)
├── requirements.txt           # Quản lý dependencies (flask, flask-cors, httpx, python-dotenv)
├── app.py                     # Entry point chính, cấu hình CORS & API Router
├── config.py                  # Đọc và xác thực cấu hình từ biến môi trường (ENV)
├── providers/                 # LLM Providers (Hỗ trợ đa cung cấp)
│   ├── base.py                # Abstract Base Provider
│   ├── ollama.py              # Ollama Local Provider (Mặc định)
│   ├── openai.py              # OpenAI API Provider
│   └── gemini.py              # Google Gemini API Provider
└── services/                  # Logic nghiệp vụ bổ trợ
    └── rag_service.py         # Tìm kiếm, trích xuất ngữ cảnh (Mock/Thực tế)
```

---

## 2. Quy Tắc Lập Trình (Server Coding Rules)

### 2.1. Quy tắc viết comment theo bước (Bắt buộc cho Backend)
Khi viết các logic nghiệp vụ hoặc xử lý từng bước ở server, tất cả comment cho từng bước phải bắt đầu bằng số thứ tự được canh lề rõ ràng để dễ đọc luồng xử lý:
```python
# 1.   Khởi tạo connection tới LLM provider
# 2.   Truy vấn Vector Database để lấy context liên quan
# 3.   Tạo prompt template kết hợp câu hỏi và context
# 4.   Gọi LLM và trả về stream
```

### 2.2. Bảo mật & Quản lý Biến Môi Trường (Environment Variables)
* **Tuyệt đối không hardcode** API Key, mật khẩu, Token hoặc cấu hình nhạy cảm vào code.
* Nếu thiếu các cấu hình môi trường quan trọng khi khởi động (ví dụ: `OPENAI_API_KEY` khi chọn dùng OpenAI, hoặc `GEMINI_API_KEY` khi chọn dùng Gemini), hệ thống phải ném ra một ngoại lệ rõ ràng (`ConfigurationError` hoặc `ValueError`) để ngăn chặn server chạy với cấu hình sai lệch, thay vì sử dụng một giá trị giả lập mặc định.

### 2.3. Thiết Kế Đa Cung Cấp (Multi-provider LLM)
* Mọi Provider kết nối mô hình ngôn ngữ phải kế thừa từ lớp trừu tượng `BaseLLMProvider` trong `providers/base.py`.
* Định nghĩa phương thức `stream_chat(prompt, context, history)` nhận vào prompt, ngữ cảnh RAG và lịch sử chat, trả về một Python Generator sinh ra các text chunk.

### 2.4. Server-Sent Events (SSE) Streaming
* API Endpoint `/api/chat` nhận dữ liệu JSON chứa câu hỏi (`message`) và lịch sử (`history`), trả về `Response(generator(), mimetype='text/event-stream')`.
* Dữ liệu sinh ra từ generator bắt buộc tuân thủ định dạng chunk SSE sau:
  * Chunk chứa thông tin nguồn tài liệu trích dẫn (gửi đầu tiên):
    `data: {"type": "metadata", "sources": [{"id": "...", "title": "...", "content": "...", "page": "...", "url": "..."}]}\n\n`
  * Chunk chứa nội dung text (gửi liên tiếp):
    `data: {"type": "content", "content": "..."}\n\n`
  * Chunk kết thúc stream (gửi cuối cùng):
    `data: [DONE]\n\n`
