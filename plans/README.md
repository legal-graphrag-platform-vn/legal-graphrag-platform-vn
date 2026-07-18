# Legal GraphRAG — Kế Hoạch Đề Tài

> **Tên đề tài**: Xây dựng nền tảng AI khai thác tri thức pháp luật doanh nghiệp Việt Nam dựa trên Knowledge Graph và Temporal GraphRAG  
> **Loại**: Đồ án tốt nghiệp  
> **Domain**: Pháp luật doanh nghiệp Việt Nam  
> **Trạng thái**: Pilot M3 evidence v1.5.1 đã sign-off nhưng stale sau ontology v1.6.0; resolver-first migration đang triển khai; Gate 7/M3-B13 còn mở

---

## Mục Lục Tài Liệu

> **Đọc theo thứ tự này trước buổi họp nhóm đầu tiên.**

| File | Nội dung | Ưu Tiên |
|---|---|---|
| **[legal_ontology.md](./legal_ontology.md)** | **Ontology Contract FROZEN v1.6.0 — Source of Truth** | 🔴 Đọc trước |
| [00_architecture_decisions.md](./00_architecture_decisions.md) | ADR — các quyết định kiến trúc | 🔴 Đọc trước |
| [01_research_contributions.md](./01_research_contributions.md) | 5 đóng góp nghiên cứu chính | 🔴 Đọc trước |
| [03_architecture.md](./03_architecture.md) | Kiến trúc hệ thống tổng thể | 🟡 Review |
| [04_graph_construction_pipeline.md](./04_graph_construction_pipeline.md) | Pipeline xây dựng Knowledge Graph (RC2) | 🟡 Review |
| [05_graphrag_retrieval.md](./05_graphrag_retrieval.md) | GraphRAG + Traversal Policy (RC3+RC4) | 🟡 Review |
| [07_implementation_timeline.md](./07_implementation_timeline.md) | Lộ trình triển khai | 🟡 Điều chỉnh theo deadline |
| [08_dataset_and_scope.md](./08_dataset_and_scope.md) | Phạm vi dữ liệu và ground truth | 🔴 Cần assign người làm |
| [09_open_questions.md](./09_open_questions.md) | Câu hỏi mở — agenda họp nhóm | 🔴 Giải quyết trong họp |
| [10_tech_stack.md](./10_tech_stack.md) | Công nghệ sử dụng | 🟢 Tham khảo |

> Historical ontology drafts live under `plans/archive/`. Do not use archived files for implementation; the only active ontology contract is `legal_ontology.md`.

## Current Execution Map (2026-07-17)

| Area | Current authority | Status |
|---|---|---|
| Ontology | `legal_ontology.md` v1.6.0 | Frozen; artifacts require migration |
| M3 blockers | `agent-plan-feats/06_m3_blocker_register.md` | Pilot closed; M3-B13 open |
| M3 execution/evidence | `agent-plan-feats/08_m3_gate4_to_milestone_a_execution_plan.md` | Pilot evidence historical; corpus gate open |
| Retrieval runtime | `agent-plan-feats/09_phase2_retrieval_runtime_and_intent_router_plan.md` | Runtime-v2 implemented; official evaluation pending |
| Backend integration | `agent-plan-feats/10_phase2_backend_retrieval_integration_plan.md` | Implemented; runtime-v2 integration rerun pending |
| Answer generation | `agent-plan-feats/11_phase2_answer_generation_plan.md` | Implemented; runtime-v2 QA rerun pending |
| Frontend pilot | `agent-plan-feats/12_frontend_pilot_completion_plan.md` | Implemented pilot; acceptance remains separate |
| Context projection | `agent-plan-feats/13_answer_context_evidence_compaction_plan.md` | Implemented |
| Graph-path safety | `agent-plan-feats/14_graph_path_direction_temporal_and_reasoning_safety_plan.md` | Implemented; current path contract |

Plans 04-07 under `agent-plan-feats/` document earlier migrations, reviews, and
decisions. They remain useful audit history but do not override the authorities
listed above.

---

## USP — Điểm Khác Biệt Cốt Lõi

> Xây dựng nền tảng AI có khả năng **tự động xây dựng Legal Knowledge Graph** từ văn bản pháp luật doanh nghiệp, hỗ trợ **GraphRAG theo ngữ cảnh truy vấn và thời điểm hiệu lực pháp luật**, đồng thời cung cấp **cơ chế giải thích (XAI)** dựa trên đường suy luận trong đồ thị tri thức.

### 3 Trụ Cột

```
┌─────────────────────────────────────────────────┐
│  1. Legal Knowledge Graph tự động               │
│     Web Crawl → Pipeline → Neo4j                │
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

- [x] RC1 — Ontology: **FROZEN v1.6.0** — xem [legal_ontology.md](./legal_ontology.md)
- [ ] RC2 — Pipeline: **Pilot M3 đã sign-off; chờ corpus 4 văn bản (M3-B13)**
- [ ] RC3 — GraphRAG: **Runtime v2 và intent taxonomy 6 lớp đã triển khai; official evaluation chưa chạy lại** — xem [05_graphrag_retrieval.md](./05_graphrag_retrieval.md)
- [ ] RC4 — Temporal: **Tương đối rõ** — edge timestamps + legal_status
- [ ] RC5 — Evaluation: **Chưa chốt** ai tạo ground truth dataset
- [x] Dataset: **Chốt 10 văn bản curated**; 4 văn bản là minimum demo, 89 văn bản crawl hiện có chỉ là discovery pool — xem [08_dataset_and_scope.md](./08_dataset_and_scope.md)
