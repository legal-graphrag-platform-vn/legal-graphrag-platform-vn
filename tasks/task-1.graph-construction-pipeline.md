# Task 1: Graph Construction Pipeline

**Giao cho:** Team Data / Backend  
**Repo triển khai:** [`legal-graphrag-platform-vn/pipeline`](https://github.com/legal-graphrag-platform-vn/pipeline)  
**Tài liệu tham chiếu:**
- Ontology: [`plans/02_ontology_specification.md`](../plans/02_ontology_specification.md)
- Kiến trúc: [`plans/03_architecture.md`](../plans/03_architecture.md)
- Đặc tả kỹ thuật: [`plans/04_graph_construction_pipeline.md`](../plans/04_graph_construction_pipeline.md)

---

## Bài toán

Chuyển đổi văn bản pháp luật Việt Nam (PDF) thành một **Legal Knowledge Graph** có cấu trúc trong Neo4j. Đây là tầng nền tảng của toàn bộ hệ thống — nếu Graph sai, mọi thứ ở tầng Retrieval và Generation đều sai theo.

Luồng dữ liệu cần build:

```
PDF văn bản pháp luật
        │
        ▼
[1] Hierarchy Parser  ←── bóc tách Phần/Chương/Điều/Khoản/Điểm
        │
        ▼
[2] LLM Extraction    ←── Entity + Relation (hai pass riêng biệt)
        │
        ▼
[3] Validation        ←── JSON Schema + Ontology Constraint check
        │
        ▼
[4] Confidence Score  ←── Rule-based, đánh điểm từng extraction
        │
        ▼
[5] Neo4j Writer      ←── Ghi node/edge + tạo embedding vector
        │
        ▼
[6] Crawler           ←── Tự động hoá việc lấy PDF + metadata từ web
```

> **Thứ tự ưu tiên**: [1] → [5] trước (core end-to-end), rồi mới [6] (automation).

---

## Ontology cần biết trước khi code

Toàn bộ spec nằm trong [`02_ontology_specification.md`](../plans/02_ontology_specification.md). Tóm tắt những điểm quan trọng nhất:

### Node types
| Node | ID Convention | Có Embedding? |
|---|---|---|
| `:Document:Law / :Decree / :Circular / :Resolution / :Decision` | `LDN2020`, `ND01_2021` | Không |
| `:Article` | `LDN2020_D17` | ✅ 768 dims |
| `:Clause` | `LDN2020_D17_K1` | ✅ 768 dims (unit chính) |
| `:Point` | `LDN2020_D17_K1_Pa` | Không |
| `:Concept` | `concept_von_dieu_le` | Không |
| `:Entity:CompanyType / :Authority / :PersonType` | `entity_cong_ty_tnhh` | Không |

Tất cả Article, Clause, Point đều có: `effective_from`, `effective_to`, `status`.

### Relation types (9 loại — không thêm, không bớt)

```
CONTAINS, AMENDED_BY, REPLACED_BY, REPEALED_BY,
IMPLEMENTED_BY, REFERENCES, DEFINES, REGULATES, REQUIRES
```

**Các ràng buộc quan trọng** (validator phải enforce):
- `AMENDED_BY` chỉ tồn tại ở cấp Article/Clause, **không** có `Document→Document`.
- `REPLACED_BY` chỉ dùng ở cấp Document hoặc Article, phải **cùng loại node**.
- `IMPLEMENTED_BY` dùng rule cấp bậc: `head.level > tail.level` (Law=3, Decree=2, Circular=1).
- `REQUIRES.tail` cho phép cả Concept và Entity.
- Các quan hệ temporal (`AMENDED_BY`, `REPLACED_BY`, `REPEALED_BY`) **bắt buộc** có property `effective_from`.

### Invariant bắt buộc

```python
# Mọi relation trong RELATION_ENUM phải có đúng 1 entry trong CONSTRAINTS.
# Kiểm tra bằng unit test — xem spec chi tiết trong 04_graph_construction_pipeline.md
assert RELATION_ENUM == set(CONSTRAINTS.keys())
```

---

## Milestones

> **Nguyên tắc**: Mỗi Milestone chứng minh đúng 1 thứ. Nếu M1 chưa pass thì không được bắt đầu M2.  
> Lý do: LLM phụ thuộc parser output. Neo4j phụ thuộc LLM output. Lỗi ở đâu phải biết ngay.

---

### 🟢 Milestone 1 — Parser Core (Không LLM, Không DB)

**Câu hỏi cần trả lời**: *"Chúng ta có thể bóc tách cấu trúc văn bản pháp luật VN ra JSON phân cấp chính xác không?"*

**Việc cần làm**:
1. Lấy 1 file PDF thủ công (tải tay, chưa cần Crawler).
2. Viết Hierarchy Parser nhận diện ranh giới: `Chương → Điều → Khoản → Điểm`.
3. Output ra JSON theo đúng format đã định nghĩa (xem `04_graph_construction_pipeline.md` mục Output Format).

**Không làm ở bước này**: LLM, Neo4j, Validation, Crawler — tất cả đều chưa đụng vào.

**Exit criteria M1**:
- Parser chạy không crash trên ít nhất 2 văn bản luật dài (không phải văn bản mẫu ngắn).
- JSON output có đủ cấu trúc phân cấp: Article → Clause → Point.
- Kiểm tra thủ công: mở PDF gốc, so sánh nội dung Điều 1, Điều 17 với JSON output — phải khớp.

---

### 🟡 Milestone 2 — LLM Extraction + Validation (Không DB)

**Câu hỏi cần trả lời**: *"LLM có thể extract đúng Entity và Relation từ text pháp luật VN không? Và Validator có chặn được dữ liệu sai không?"*

**Việc cần làm** (input lấy từ JSON của M1):
1. Viết prompt và gọi LLM (two-pass: entity trước, relation sau).
2. JSON Schema Validator: ép kiểu đúng format.
3. Ontology Validator: kiểm tra `valid_pairs`, `required_properties`.
4. Confidence Scorer (rule-based, 5 tiêu chí).
5. Decision Gate: auto-accept / human review / reject.
6. Unit tests ontology consistency (ít nhất 6 test cases — xem spec trong `04_graph_construction_pipeline.md`).

**Không làm ở bước này**: Neo4j, Crawler — chưa cần thiết để prove LLM pipeline.

**Exit criteria M2**:
- In ra terminal danh sách triples `(head)-[RELATION]->(tail)` extract được từ 1 văn bản.
- Cố tình đưa vào extraction sai (`Article→Document AMENDED_BY`) — Validator phải reject.
- 6/6 unit tests ontology pass.

---

### 🔴 Milestone 3 — Neo4j Write + Crawler (Hoàn thiện)

**Câu hỏi cần trả lời**: *"Pipeline có thể chạy tự động end-to-end từ URL đến Graph không?"*

**Việc cần làm** (kết nối toàn bộ M1 + M2):
1. Neo4j Writer: ghi node/edge từ validated triples của M2.
2. Embedding: tạo vector cho Article và Clause, lưu vào Neo4j Vector Index.
3. Crawler: tự động tải PDF + scrape metadata từ web (ngày hiệu lực, tình trạng).
4. Ghép toàn bộ luồng vào `main.py`.

**Exit criteria M3**:
- `python main.py --doc_url <url>` chạy end-to-end không lỗi.
- Mở Neo4j Browser: graph có đủ node/edge, temporal properties (`effective_from`) điền đúng.
- Embedding đã được lưu vào Vector Index (verify bằng Cypher query `CALL db.index.vector.queryNodes(...)`).


---


## Cấu trúc repo đề xuất

Đây là gợi ý — được phép điều chỉnh miễn là có lý do rõ ràng trong báo cáo:

```
pipeline/
├── src/
│   ├── parser/         # PDF → JSON hierarchy
│   ├── extraction/     # Prompt templates + LLM calls
│   ├── validation/     # JSON Schema + OntologyValidator
│   ├── scoring/        # ConfidenceScorer
│   ├── database/       # Neo4j writer + embedding
│   └── crawler/        # Web scraper (Milestone 3)
├── tests/
│   └── test_ontology_consistency.py  # BẮT BUỘC
├── data/
│   ├── raw/            # PDF + metadata.json
│   └── processed/      # JSON sau extraction
├── main.py
├── requirements.txt
└── REPORT.md           # BẮT BUỘC — xem phần dưới
```

**Code rules bắt buộc**:
- Type hinting trên mọi function (`def parse(path: str) -> dict:`).
- Dùng `logging` thay vì `print`. Log rõ từng step.
- Các module không được gọi chéo trực tiếp — dữ liệu đi qua dict/Pydantic model.
- Retry logic cho LLM API calls (timeout, rate limit).

---

## Yêu cầu báo cáo (`REPORT.md`)

Sau mỗi Milestone, cập nhật `REPORT.md` ngay trong repo. Đây không phải tài liệu hướng dẫn — đây là **tài liệu kỹ thuật** để người đọc hiểu *tại sao* hệ thống được build như vậy.

Báo cáo phải trả lời 3 nhóm câu hỏi sau:

---

### A. Bài toán & Thách thức thực tế

*Đây là phần quan trọng nhất. Không viết chung chung — viết cụ thể những gì đã xảy ra khi thực sự code.*

- Khi parse PDF thực tế, gặp những format nào khó nhận diện ranh giới Điều/Khoản? Giải quyết bằng cách nào?
- LLM có thực sự trả về đúng JSON schema không, hay phải xử lý thêm? Tỉ lệ fail JSON parse là bao nhiêu?
- Hallucination phổ biến nhất của LLM với văn bản pháp luật VN là gì? (Sai relation type? Sai entity ID? Bịa Article không tồn tại?)
- Với `IMPLEMENTED_BY` dùng rule `head.level > tail.level`, đã gặp edge case nào không? (Ví dụ: văn bản không rõ loại?)

---

### B. Quyết định kỹ thuật & Lý do (tại sao impl như thế?)

*Bạn được toàn quyền chọn công nghệ. Nhưng mỗi quyết định phải được giải thích.*

Trả lời ít nhất 4 trong các câu hỏi sau:

1. **Thư viện parse PDF**: Chọn tool gì (PyMuPDF, pdfplumber, unstructured.io...)? So sánh đã cân nhắc là gì? Với văn bản pháp luật VN scan hay text-based, cái nào hoạt động tốt hơn?
2. **LLM model & strategy**: Chọn model nào? Two-pass (entity trước, relation sau) hay single-pass? Lý do?
3. **Cấu trúc OntologyValidator**: Implement `valid_pairs` dạng dict tra cứu hay dạng function? Tại sao? Có dễ mở rộng không nếu thêm relation type mới?
4. **Confidence threshold**: Chọn ngưỡng 0.3 và 0.7 hay thay đổi? Dựa trên dữ liệu nào để quyết định?
5. **Crawler strategy**: Scrape từ vbpl.vn hay thuvienphapluat.vn? Gặp anti-bot không? Giải quyết thế nào?
6. **Kiến trúc tổng thể**: Cấu trúc folder thực tế có khác đề xuất không? Tại sao thay đổi?

---

### C. Hướng dẫn chạy & Luồng dữ liệu (Code Walkthrough)

*Người đọc phải có thể chạy được project chỉ bằng tài liệu này.*

1. Hướng dẫn cài đặt step-by-step (Neo4j setup, env vars, `pip install`).
2. Lệnh chạy từng Milestone.
3. Giải thích data flow: file nào gọi hàm nào, object nào được truyền giữa các module, dữ liệu biến đổi ra sao từ PDF thô → JSON → neo4j node.
4. Cách chạy unit tests và interpret kết quả.
