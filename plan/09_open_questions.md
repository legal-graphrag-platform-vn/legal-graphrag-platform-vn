# Câu Hỏi Mở — Cần Nhóm Quyết Định

> **Mục đích**: Tổng hợp tất cả các quyết định kỹ thuật và thiết kế chưa được chốt  
> **Cách dùng**: Dùng file này làm agenda cho buổi họp nhóm đầu tiên

---

## 🔴 Ưu Tiên Cao — Cần Chốt Trước Khi Code

### Q1: Phương pháp Confidence Scoring?

Liên quan đến: RC2 — Graph Construction Pipeline

| Option | Mô Tả | Trade-off |
|---|---|---|
| **A) Self-consistency N=3** | Chạy LLM 3 lần, majority vote | Tốn 3x API cost |
| **B) Log-probability** | Dùng token log-probs | Không phải LLM nào hỗ trợ |
| **C) Critic LLM** | LLM 2 đánh giá output LLM 1 | Chất lượng cao, đắt nhất |

**Gợi ý**: Option A — self-consistency N=3  
**Quyết định**: ?

---

### Q2: Phương pháp Intent Classification?

Liên quan đến: RC3 — Traversal Policy (toàn bộ GraphRAG phụ thuộc vào đây)

| Option | Mô Tả | Trade-off |
|---|---|---|
| **A) Few-shot LLM** | 5-10 ví dụ trong prompt | Dễ implement, latency cao |
| **B) Fine-tuned PhoBERT** | Train trên ~200 câu labeled | Chất lượng cao, cần tạo dataset |
| **C) Rule-based** | Keyword matching | Nhanh, không scalable |

**Gợi ý**: Option A trước, sau đó so sánh với B (thêm experiment)  
**Quyết định**: ?

---

### Q3: Threshold cho Human Review?

Liên quan đến: RC2 — Graph Construction Pipeline

- Confidence < ? → Auto-reject
- ? ≤ Confidence < ? → Human Review Queue
- Confidence ≥ ? → Auto-accept

**Gợi ý**: Auto-reject < 0.3, Human Review 0.3-0.7, Auto-accept ≥ 0.7  
**Quyết định**: ?

---

### Q4: Ai phụ trách tạo Ground Truth Dataset?

Liên quan đến: RC5 — Evaluation (không có dataset → không có evaluation → không có research)

| Task | Effort | Người Phụ Trách |
|---|---|---|
| Annotate Gold Graph (3 văn bản) | ~3 ngày/người | ? |
| Viết 100 QA pairs | ~2 ngày/người | ? |
| Viết 50 Temporal QA | ~2 ngày/người | ? |
| Viết 20-30 XAI cases | ~1 ngày/người | ? |

**Quyết định**: ?

---

### Q5: Danh sách 10 văn bản cụ thể?

Liên quan đến: `08_dataset_and_scope.md`

Xem file dataset để biết danh sách đề xuất. Cần:
- Xác nhận 4 văn bản bắt buộc
- Chọn thêm 6 văn bản mở rộng
- Verify có thể tải/thu thập được

**Quyết định**: ?

---

## 🟡 Ưu Tiên Trung Bình — Cần Chốt Trong Tháng 1

### Q6: Reranker loại gì?

Liên quan đến: RC3 — Hybrid Retriever

| Option | Mô Tả | Trade-off |
|---|---|---|
| **A) BM25 hybrid** | Combine BM25 + vector score | Nhanh, đơn giản, baseline tốt |
| **B) Cross-encoder** | BERT/PhoBERT reranks pairs | Chất lượng cao, chậm hơn |
| **C) LLM-based** | LLM score từng chunk | Linh hoạt, tốn cost |

**Gợi ý**: A làm baseline, B là main method → có thêm 1 experiment  
**Quyết định**: ?

---

### Q7: `Definition` — node riêng hay attribute của Concept?

Liên quan đến: RC1 — Ontology

**Option A**: Node riêng `(:Definition)-[:DEFINES]->(:Concept)`  
**Option B**: Attribute của Concept `(:Concept {definition: "..."})`

**Trade-off**: Option A cho phép query "Ai định nghĩa X?" nhưng phức tạp hơn  
**Quyết định**: ?

---

### Q8: Có node `Procedure` (thủ tục hành chính) không?

Liên quan đến: RC1 — Ontology Scope

Pháp luật doanh nghiệp có nhiều thủ tục hành chính (đăng ký, thay đổi, giải thể).  
Nếu có node `Procedure`:
- Graph phong phú hơn
- Complexity tăng
- Cần thêm relation types

**Quyết định**: ?

---

### Q9: Deployment target?

Liên quan đến: Architecture + Effort estimate

| Option | Mô Tả |
|---|---|
| **A) Local only** | Chạy trên máy demo, không có cloud |
| **B) Docker Compose** | Đóng gói, chạy được trên bất kỳ máy nào |
| **C) Cloud (AWS/GCP/Azure)** | Có URL public |

**Gợi ý**: Option B — Docker Compose là đủ cho đồ án tốt nghiệp  
**Quyết định**: ?

---

### Q10: Graph Visualizer — D3.js hay Cytoscape.js?

Liên quan đến: Frontend UI

| Library | Pros | Cons |
|---|---|---|
| **D3.js** | Cực kỳ linh hoạt, đẹp | Khó học, boilerplate nhiều |
| **Cytoscape.js** | Chuyên cho graph, dễ hơn | Ít custom hơn |
| **Sigma.js** | Performance tốt với graph lớn | Ít tài liệu hơn |

**Gợi ý**: Cytoscape.js — phù hợp hơn cho knowledge graph visualization  
**Quyết định**: ?

---

## 🟢 Ưu Tiên Thấp — Có Thể Quyết Định Sau

### Q11: Ontology Evolution — làm hay để Future Work?

Nếu làm: thêm ~3-4 tuần, nhưng graph có thể update schema  
Nếu để future work: đơn giản hơn nhưng thiếu 1 contribution  
**Gợi ý**: Future Work  

### Q12: Fine-tuned PhoBERT cho Intent Classification?

Nếu làm: thêm ~2 tuần tạo dataset + train  
Nếu không: chỉ dùng few-shot LLM  
**Gợi ý**: Làm nếu còn thời gian tháng 3, dùng làm thêm 1 ablation study  

### Q13: LLM-as-judge dùng model nào?

Cho Evaluation Level 2-3  
| GPT-4o | Gemini 1.5 Pro | Llama3 local |  
**Gợi ý**: Gemini 1.5 Pro (đồng nhất với extraction model)  

---

## Meeting Agenda Template

Dùng cho buổi họp nhóm đầu tiên:

```
1. Review 5 Research Contributions — 15 phút
2. Chốt Q1, Q2, Q3 (Confidence Scoring, Intent, Threshold) — 20 phút
3. Chốt Q4 (Ground Truth assignment) — 20 phút
4. Chốt Q5 (Dataset list) — 15 phút
5. Timeline review — 10 phút
6. AOB — 10 phút
```

---

## Decision Log (Cập Nhật Sau Khi Chốt)

| # | Câu Hỏi | Quyết Định | Người Quyết | Ngày |
|---|---|---|---|---|
| Q1 | Confidence Scoring | ? | ? | ? |
| Q2 | Intent Classification | ? | ? | ? |
| Q3 | Human Review Threshold | ? | ? | ? |
| Q4 | Ground Truth Dataset owner | ? | ? | ? |
| Q5 | Document list | ? | ? | ? |
| Q6 | Reranker | ? | ? | ? |
| Q7 | Definition node | ? | ? | ? |
| Q8 | Procedure node | ? | ? | ? |
| Q9 | Deployment | ? | ? | ? |
| Q10 | Graph Visualizer | ? | ? | ? |
