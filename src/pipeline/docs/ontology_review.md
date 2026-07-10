# Historical Review: Legal Ontology Migration Notes (v1.1.0)

Bản ghi này là ghi chú lịch sử cho migration v1.1.0. Source of truth hiện hành là `plans/legal_ontology.md` v1.4.0.

---

## 1. Các Thay Đổi Cốt Lõi (Key Changes)

### A. Chuyển đổi tên quan hệ sang Thể chủ động (Active Voice)
*   **Sự thay đổi**: Toàn bộ tên quan hệ chuyển từ dạng bị động sang chủ động để đồng bộ ngữ nghĩa tự nhiên trong đồ thị:
    *   `AMENDED_BY` $\rightarrow$ `AMENDS`
    *   `REPEALED_BY` $\rightarrow$ `REPEALS`
    *   `REPLACED_BY` $\rightarrow$ `REPLACES`
    *   `IMPLEMENTED_BY` (hoặc `GUIDED_BY`) $\rightarrow$ `GUIDES`
    *   `REFERENCES` $\rightarrow$ `REFERS_TO`

### B. Mở rộng tầng Structural Layer
*   **Bổ sung node `Issuer`**: Lưu trữ cơ quan ban hành riêng biệt.
*   **Bổ sung quan hệ `ISSUED_BY`**: Đi từ `Document` $\rightarrow$ `Issuer`.
*   **Logic Validator mới cho `GUIDES`**:
    *   Thay thế việc so khớp mức độ ưu tiên bằng số nguyên (`head_doc_level > tail_doc_level`) thành ma trận whitelist tĩnh `GUIDES_WHITELIST`.
    *   Giúp loại bỏ hoàn toàn các trường hợp không hợp lệ như `Law -GUIDES- Law`.

### C. Mở rộng tầng Semantic Layer & Extraction Type mới
*   **Extraction Type mới `Action`**: Cho phép LLM trích xuất các hành vi pháp lý (động từ như *thành lập*, *góp vốn*).
*   **Map Ontology mới tại Writer**:
    *   `Entity` $\rightarrow$ `LegalSubject`
    *   `Concept` $\rightarrow$ `LegalConcept`
    *   `Action` $\rightarrow$ `LegalAction`
*   **Bổ sung các quan hệ Semantic**:
    *   `HAS_CONDITION` (điều kiện)
    *   `HAS_EXCEPTION` (ngoại lệ)

---

## 2. Ảnh hưởng đến các file mã nguồn (Codebase Impact)

Nếu đồng ý triển khai bản Ontology 1.1.0 này, các cấu trúc sau đây cần được sửa đổi đồng bộ:

### 1. Pydantic Models & Enum (`src/extraction/models.py`)
*   Cập nhật enum `RelationType` để đổi tên và thêm các quan hệ mới.
*   Cập nhật enum `EntityType` để thêm loại `"Action"`.

### 2. Prompt Templates (`src/extraction/prompts.py`)
*   Cập nhật `ENTITY_EXTRACTION_PROMPT` hướng dẫn LLM nhận dạng và trích xuất thực thể `Action`.
*   Cập nhật `RELATION_EXTRACTION_PROMPT` với danh sách quan hệ chủ động và các quan hệ mới (`HAS_CONDITION`, `HAS_EXCEPTION`).

### 3. Ontology Validator (`src/validation/ontology_validator.py`)
*   Viết lại ma trận `CONSTRAINTS` dựa trên cấu trúc §3.1 & §3.2.
*   Triển khai whitelist `GUIDES_WHITELIST` và hàm `validate_guides()` để thay thế so sánh mức số nguyên cũ.

### 4. Orchestrator (`src/pipeline/orchestrator.py`)
*   Cập nhật logic sinh thuộc tính động (`properties`) cho các mối quan hệ (ví dụ đổi `AMENDED_BY` thành `AMENDS`).

### 5. Unit Tests (`tests/test_ontology_consistency.py` & `tests/test_orchestrator.py`)
*   Sửa đổi toàn bộ dữ liệu mock và assertions khớp với tên quan hệ chủ động mới để tránh làm gãy bộ tests.

---

## 3. Câu hỏi và Đề xuất Thảo luận

1. **Trích xuất `ISSUED_BY`**:
   * *Đề xuất*: Theo spec §2.1, `Issuer` được tự động tạo bởi Writer từ thuộc tính `issuer_name` của Document, LLM không trích xuất riêng. Tuy nhiên, spec §3.1 lại liệt kê quan hệ `ISSUED_BY: Document -> Issuer`.
   * *Câu hỏi*: Chúng ta có cần LLM trích xuất quan hệ `ISSUED_BY` ở cấp độ bài viết không, hay việc này sẽ do Writer tự sinh hoàn toàn khi import dữ liệu vào Neo4j? (Khuyến nghị: **Do Writer tự sinh**, không cần bắt LLM trích xuất vì metadata ban hành của văn bản đã có sẵn từ Crawler).

2. **Các node `Obligation`, `Right`, `Condition`, `Exception`**:
   * *Đề xuất*: Theo spec §4, LLM chỉ trích xuất 3 loại đơn giản (`Entity`, `Concept`, `Action`).
   * *Câu hỏi*: Với các quan hệ liên quan tới `Obligation`, `Right`, `Condition`, `Exception` trong §3.2, LLM sẽ sử dụng nhãn nào để biểu diễn chúng ở đầu ra? Ví dụ: với `HAS_CONDITION`, thực thể đích (`Condition`) sẽ được LLM phân loại là `Concept` ở Pass 1, rồi Writer tự map thành `Condition` khi gặp quan hệ `HAS_CONDITION`?
