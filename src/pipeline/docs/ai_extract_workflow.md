# Quy Trình Trích Xuất và Xác Thực Thực Thể/Quan Hệ bằng LLM (AI Extract Workflow)

Tài liệu này mô tả chi tiết luồng xử lý của các module **AI Extraction**, **Validation**, **Scoring**, và **Decision Gate** thuộc Graph Construction Pipeline trong hệ thống Legal GraphRAG VN.

---

## 1. Sơ đồ Luồng Hoạt Động (Workflow Diagram)

```text
[ Dữ liệu hierarchy.json ]
            │
            ▼
    [ orchestrator.py ] ──► Lặp qua từng Điều luật (Article)
            │
            ├──► llm_extractor.py: Pass 1 (Entity Extraction)
            │         │
            │         ▼ [ Danh sách Entity ID ]
            │
            ├──► llm_extractor.py: Pass 2 (Relation Extraction)
            │         │
            │         ▼ [ Quan hệ kèm Evidence ]
            │
            ├──► schema_validator.py & ontology_validator.py
            │         │
            │         ▼ [ Kết quả xác thực (True/False) ]
            │
            ├──► confidence_scorer.py (Chấm điểm từ 0.0 đến 1.0)
            │         │
            │         ▼ [ Điểm Confidence Score ]
            │
            └──► Cổng quyết định (Decision Gate):
                      │
                      ├──► Điểm >= 0.7 ──► accepted.jsonl (Tự động duyệt)
                      ├──► Điểm 0.3 - 0.7 ──► review_queue.jsonl (Chờ duyệt thủ công)
                      └──► Điểm < 0.3 ──► rejected.jsonl (Tự động từ chối)
```

---

## 2. Chi Tiết Các Bước Xử Lý

### Bước 1: Trích xuất 2-pass bằng LLM (2-Pass LLM Extraction)

Hàm [process_article](file:///D:/Workspace/Project/legal-graphrag/pipline/src/pipeline/orchestrator.py#L37) điều phối luồng gọi thông qua [extract_article](file:///D:/Workspace/Project/legal-graphrag/pipline/src/extraction/llm_extractor.py#L30) để chia việc trích xuất thành 2 bước riêng biệt nhằm cải thiện độ chính xác và tránh quá tải ngữ cảnh cho LLM:

*   **Pass 1: Trích xuất thực thể (Entity Extraction)**:
    *   Sử dụng [ENTITY_EXTRACTION_PROMPT](file:///D:/Workspace/Project/legal-graphrag/pipline/src/extraction/prompts.py#L11).
    *   Yêu cầu LLM nhận diện các thực thể thuộc 6 lớp thực thể: `Document`, `Article`, `Clause`, `Point`, `Concept`, và `Entity`.
*   **Pass 2: Trích xuất mối quan hệ (Relation Extraction)**:
    *   Sử dụng [RELATION_EXTRACTION_PROMPT](file:///D:/Workspace/Project/legal-graphrag/pipline/src/extraction/prompts.py#L26).
    *   Đưa danh sách thực thể đã tìm thấy từ Pass 1 làm đầu vào cho Pass 2.
    *   Yêu cầu LLM liên kết các thực thể bằng relation vocabulary canonical: `CONTAINS`, `AMENDS`, `REPEALS`, `REPLACES`, `GUIDES`, `REFERS_TO`, `DEFINES`, `REGULATES`, `REQUIRES`.
    *   LLM bắt buộc phải cung cấp một chuỗi `evidence` trích xuất trực tiếp từ văn bản gốc làm căn cứ.

**Hỗ trợ đa LLM Provider**:
Hệ thống sử dụng cơ chế Factory [get_provider](file:///D:/Workspace/Project/legal-graphrag/pipline/src/extraction/providers/__init__.py#L9) để khởi tạo provider thích hợp dựa vào cấu hình `llm_provider`:
*   **Google Gemini ([GeminiProvider](file:///D:/Workspace/Project/legal-graphrag/pipline/src/extraction/providers/gemini_provider.py#L29))**: Sử dụng thư viện `google-genai` truyền trực tiếp Pydantic schema vào tham số `response_schema` để ép kiểu JSON chặt chẽ ở cấp độ API.
*   **OpenAI-Compatible ([OpenAICompatibleProvider](file:///D:/Workspace/Project/legal-graphrag/pipline/src/extraction/providers/openai_provider.py#L30))**: Hỗ trợ MiniMax, Qwen, hoặc OpenAI. Nếu mô hình không hỗ trợ Structured Outputs, hệ thống tự động fallback sang chế độ JSON thô kèm prompt mô tả schema, sau đó làm sạch và chuẩn hóa ID thực thể bằng regex.

---

### Bước 2: Xác Thực Schema & Ontology (Validation)

Mỗi quan hệ sau khi trích xuất sẽ được đưa qua hai tầng lọc nghiệp vụ:
1.  **JSON Schema Validation ([schema_validator.py](file:///D:/Workspace/Project/legal-graphrag/pipline/src/validation/schema_validator.py))**:
    *   Đảm bảo kiểu dữ liệu và định dạng khớp chuẩn xác với các mô hình Pydantic [ExtractedRelation](file:///D:/Workspace/Project/legal-graphrag/pipline/src/extraction/models.py#L42).
2.  **Ontology Validation ([ontology_validator.py](file:///D:/Workspace/Project/legal-graphrag/pipline/src/validation/ontology_validator.py))**:
    *   Kiểm tra ràng buộc giữa cặp thực thể (`valid_pairs`): Ví dụ, quan hệ `CONTAINS` chỉ được đi từ `Article` $\rightarrow$ `Clause`, không được đi ngược lại hay nối giữa thực thể khác.
    *   Ngăn chặn tự lặp (`no_self_loop`): Không cho phép thực thể tự liên kết với chính nó đối với các quan hệ như `CONTAINS`, `AMENDS`, `REPLACES`.
    *   Whitelist tài liệu cho quan hệ `GUIDES`: quan hệ hướng dẫn chỉ hợp lệ khi cặp `doc_type` nằm trong `GUIDES_WHITELIST`.

---

### Bước 3: Đánh Giá Điểm Tin Cậy (Confidence Scoring)

Hệ thống tính toán điểm số tổng hợp cuối cùng từ $0.0$ đến $1.0$ thông qua module [confidence_scorer.py](file:///D:/Workspace/Project/legal-graphrag/pipline/src/scoring/confidence_scorer.py) dựa trên 5 tiêu chí:

| Tiêu chí | Trọng số | Phương pháp tính toán |
| :--- | :---: | :--- |
| **Schema Valid** | $0.3$ | Đạt $1.0$ nếu khớp hoàn hảo định dạng Pydantic Schema; ngược lại $0.0$. |
| **Ontology Valid** | $0.3$ | Đạt $1.0$ nếu thỏa mãn tất cả quy tắc ràng buộc quan hệ đồ thị; ngược lại $0.0$. |
| **Evidence Present** | $0.2$ | Tính toán trùng lặp cục bộ (Token Overlap) hoặc tìm kiếm chuỗi con (Exact Substring) giữa chuỗi bằng chứng (`evidence`) của LLM với văn bản gốc của Điều luật. Không tốn chi phí gọi API LLM phụ. |
| **Entities Resolvable** | $0.1$ | Tỷ lệ thực thể đầu (`head`) và cuối (`tail`) có thể đối chiếu (resolve) được trong danh sách thực thể đã biết của đồ thị. |
| **Direction Correct** | $0.1$ | Đạt $1.0$ nếu chiều quan hệ đồ thị phù hợp với nghiệp vụ đã quy định trong Ontology; ngược lại $0.0$. |

---

### Bước 4: Phân Loại và Cổng Quyết Định (Decision Gate)

Kết quả trích xuất được định tuyến tự động vào các luồng lưu trữ JSONL riêng biệt dựa trên ngưỡng cấu hình tại [Settings](file:///D:/Workspace/Project/legal-graphrag/pipline/src/config.py#L16):

*   **Tự động chấp nhận (`accepted.jsonl`)**: Các mối quan hệ có chất lượng và bằng chứng rõ ràng (Confidence $\ge 0.7$), sẵn sàng để nạp (ingest) vào cơ sở dữ liệu đồ thị Neo4j.
*   **Hàng đợi kiểm duyệt (`review_queue.jsonl`)**: Các liên kết có độ tin cậy vừa phải ($0.3 \le$ Confidence $< 0.7$), cần chuyên viên pháp lý xem xét và chỉnh sửa bằng tay thông qua giao diện admin UI.
*   **Từ chối tự động (`rejected.jsonl`)**: Các liên kết bị sai schema, vi phạm nghiêm trọng ontology hoặc không có bằng chứng văn bản (Confidence $< 0.3$).

---

## 3. Các Case Biên và Giới Hạn Hiện Tại (Edge Cases & Limitations)

*   **Thiếu Document Registry liên văn bản (M1+M2)**: 
    *   Do M1+M2 hoạt động độc lập trên từng tài liệu và chưa tích hợp Database Đồ thị (Neo4j), mối quan hệ `GUIDES` giữa tài liệu hiện tại với các văn bản khác sẽ chưa có dữ liệu kiểm chứng `doc_type` đầy đủ. Hệ thống sẽ gắn nhãn `tail_doc_type=None` và đẩy các liên kết này vào `review_queue.jsonl` thay vì tự động chấp nhận sai. Đây là thiết kế an toàn có chủ đích.
*   **Sai lệch định dạng ID thực thể (ID Normalization)**:
    *   LLM đôi khi sinh ra các ID chứa ký tự tiếng Việt có dấu, khoảng trắng hoặc ký tự đặc biệt làm gãy Schema. Hệ thống đã tích hợp bộ chuẩn hóa ID tự động chuyển đổi văn bản sang ký tự không dấu và dạng `snake_case` trước khi kiểm tra hợp lệ.
