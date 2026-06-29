# Legal GraphRAG — Kế Hoạch Đề Tài

> **Tên đề tài**: Xây dựng nền tảng AI khai thác tri thức pháp luật doanh nghiệp Việt Nam dựa trên Knowledge Graph và Temporal GraphRAG  
> **Loại**: Đồ án tốt nghiệp  
> **Domain**: Pháp luật doanh nghiệp Việt Nam  
> **Trạng thái**: Đang thảo luận plan

---

## Mục Lục Tài Liệu

> **Đọc theo thứ tự này trước buổi họp nhóm đầu tiên.**

| File | Nội dung | Ưu Tiên |
|---|---|---|
| [00_architecture_decisions.md](./00_architecture_decisions.md) | **7 quyết định kiến trúc đã chốt** (ADR) | 🔴 Đọc trước |
| [01_research_contributions.md](./01_research_contributions.md) | 5 đóng góp nghiên cứu chính | 🔴 Đọc trước |
| [02_ontology_specification.md](./02_ontology_specification.md) | Thiết kế Ontology 3 tầng | 🟡 Cần chốt |
| [03_architecture.md](./03_architecture.md) | Kiến trúc hệ thống tổng thể | 🟡 Review |
| [04_graph_construction_pipeline.md](./04_graph_construction_pipeline.md) | Pipeline xây dựng Knowledge Graph (RC2) | 🟡 Review |
| [05_graphrag_retrieval.md](./05_graphrag_retrieval.md) | GraphRAG + Traversal Policy (RC3+RC4) | 🟡 Review |
| [07_implementation_timeline.md](./07_implementation_timeline.md) | Lộ trình triển khai 5 tháng | 🟡 Điều chỉnh theo deadline |
| [08_dataset_and_scope.md](./08_dataset_and_scope.md) | Phạm vi dữ liệu và ground truth | 🔴 Cần assign người làm |
| [09_open_questions.md](./09_open_questions.md) | Câu hỏi mở — agenda họp nhóm | 🔴 Giải quyết trong họp |
| [10_tech_stack.md](./10_tech_stack.md) | Công nghệ sử dụng | 🟢 Tham khảo |

---

## USP — Điểm Khác Biệt Cốt Lõi

> Xây dựng nền tảng AI có khả năng **tự động xây dựng Legal Knowledge Graph** từ văn bản pháp luật doanh nghiệp, hỗ trợ **GraphRAG theo ngữ cảnh truy vấn và thời điểm hiệu lực pháp luật**, đồng thời cung cấp **cơ chế giải thích (XAI)** dựa trên đường suy luận trong đồ thị tri thức.

### 3 Trụ Cột

```
┌─────────────────────────────────────────────────┐
│  1. Legal Knowledge Graph tự động               │
│     PDF → Pipeline → Neo4j                      │
├─────────────────────────────────────────────────┤
│  2. Temporal GraphRAG                           │
│     Trả lời đúng theo thời điểm pháp lý         │
├─────────────────────────────────────────────────┤
│  3. Explainable AI (XAI)                        │
│     Mọi đáp án có reasoning path + citation     │
└─────────────────────────────────────────────────┘
```

---

## Câu Hỏi Nghiên Cứu Chính (Research Questions)

**RQ1**: Pipeline nào có thể tự động chuyển đổi văn bản pháp luật tiếng Việt thành Legal Knowledge Graph với độ chính xác đủ tin cậy?

**RQ2**: Chiến lược Graph Traversal dựa trên Intent có cải thiện chất lượng retrieval so với vector search thuần không?

**RQ3**: Hệ thống có thể trả lời câu hỏi pháp lý theo đúng thời điểm hiệu lực pháp luật (Temporal QA) không?

**RQ4**: Reasoning path sinh ra có đủ để giải thích câu trả lời ở mức độ citation pháp luật không?

---

## Trạng Thái Thảo Luận

- [ ] RC1 — Ontology: **Chưa chốt** node types / relation types đầy đủ
- [ ] RC2 — Pipeline: **Chưa chốt** phương pháp Confidence Scoring
- [ ] RC3 — GraphRAG: **Chưa chốt** phương pháp Intent Classification
- [ ] RC4 — Temporal: **Tương đối rõ** — edge timestamps
- [ ] RC5 — Evaluation: **Chưa chốt** ai tạo ground truth dataset
- [ ] Dataset: **Chưa chốt** danh sách 20 văn bản cụ thể
