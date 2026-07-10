# ChatLegal API Server (Python Flask)

Mã nguồn Backend phục vụ hệ thống trả lời câu hỏi RAG chuyên sâu về pháp luật Việt Nam. Hỗ trợ truyền dữ liệu dạng Server-Sent Events (SSE) streaming thời gian thực và quản lý tài liệu tham chiếu (citations/sources).

---

## 1. Yêu Cầu Hệ Thống (Prerequisites)
* **Python**: Phiên bản 3.9 trở lên.
* **Ollama (nếu chạy local)**: Hãy chắc chắn bạn đã tải Ollama và tải sẵn model `llama3` (hoặc model tùy chỉnh khác):
  ```bash
  ollama run llama3
  ```

---

## 2. Hướng Dẫn Cấu Hình và Khởi Chạy (Quick Start)

### Bước 1: Di chuyển vào thư mục dự án
Mở Terminal hoặc Command Prompt và di chuyển vào thư mục `chat-server`:
```bash
cd chat-server
```

### Bước 2: Tạo môi trường ảo Python (Virtual Environment)
```bash
python -m venv venv
```

### Bước 3: Kích hoạt môi trường ảo
* **Trên Windows (cmd):**
  ```cmd
  venv\Scripts\activate
  ```
* **Trên Windows (PowerShell):**
  ```powershell
  .\venv\Scripts\activate
  ```
* **Trên macOS / Linux:**
  ```bash
  source venv/bin/activate
  ```
*(Sau khi kích hoạt thành công, dòng lệnh của bạn sẽ có tiền tố `(venv)`)*

### Bước 4: Cài đặt các thư viện phụ thuộc
```bash
pip install -r requirements.txt
```

### Bước 5: Cấu hình biến môi trường (.env)
Sao chép cấu hình mẫu từ tệp `.env` đã được tạo sẵn trong thư mục. Mặc định hệ thống chạy bằng Ollama cổng 11434. 

Nếu bạn muốn sử dụng **Gemini** hoặc **OpenAI**, hãy đổi giá trị `LLM_PROVIDER` và dán API Key của bạn vào:
```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIzaSy... (API Key của bạn)
GEMINI_MODEL=gemini-2.5-flash
```

### Bước 6: Khởi chạy API Server
```bash
python app.py
```
*API Server sẽ bắt đầu chạy và lắng nghe tại địa chỉ: `http://localhost:5000`*

---

## 3. Danh Sách API (API Endpoint)

### **POST /api/chat**
Xử lý câu hỏi của người dùng, tìm kiếm ngữ cảnh RAG và trả về dòng kết quả stream.

* **Payload mẫu (JSON)**:
  ```json
  {
    "message": "Điều kiện thành lập công ty cổ phần là gì?",
    "history": [
      {"role": "user", "content": "Chào bạn"},
      {"role": "assistant", "content": "Xin chào! Tôi có thể giúp gì cho bạn hôm nay?"}
    ]
  }
  ```

* **Dữ liệu trả về (text/event-stream)**:
  1. Chunk đầu tiên chứa danh sách tài liệu trích dẫn (metadata):
     `data: {"type": "metadata", "sources": [{"id": "...", "title": "...", "content": "..."}]}`
  2. Các chunk tiếp theo chứa nội dung phản hồi chữ nối tiếp nhau (content):
     `data: {"type": "content", "content": "..."}`
  3. Chunk kết thúc stream:
     `data: [DONE]`

---

## 4. Quy Định Dành Cho Nhà Phát Triển / AI Agent
Trước khi viết mã nguồn mới hoặc đóng góp tính năng cho repository này, vui lòng tham khảo kỹ tệp tin **[AGENTS.md](file:///D:/Workspace/Project/legal-graphrag/gpt/chat-server/AGENTS.md)** để nắm rõ cấu trúc thư mục, quy tắc viết comment có đánh số thứ tự `# 1.   ` và chính sách bảo mật cấu hình.
