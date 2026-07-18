# Open Questions — Bảng Quyết Định Chính Thức

> **Phiên bản**: v0.3 — tổng hợp sau review  
> **Cách dùng**: Đây là **agenda bắt buộc** cho buổi họp nhóm đầu tiên.  
> Mỗi câu hỏi phải có quyết định rõ ràng trước khi bất kỳ ai bắt đầu code.

---

## 🔴 Nhóm 1 — Phải Trả Lời Trước Khi Lập Timeline

> [!CAUTION]
> Nhóm 1 chi phối toàn bộ scope và phân công. Không chốt được nhóm này = không lập được timeline thực tế.

### Q1: Nhóm có bao nhiêu người và ai phụ trách phần nào?

`07_implementation_timeline.md` hiện tại để trống hoàn toàn phần phân công.

| Vai Trò | Phần Phụ Trách | Người |
|---|---|---|
| ? | RC2 — Graph Construction Pipeline | ❓ |
| ? | RC3 — GraphRAG Retrieval + Traversal | ❓ |
| ? | RC4 — Temporal Logic | ❓ |
| ? | RC5 — Evaluation Framework + Ground Truth | ❓ |
| ? | Frontend UI | ❓ |
| ? | Báo Cáo + Literature Review | ❓ |

**Quyết định**: _______________

---

### Q2: Scope cắt giảm đến đâu?

Nhóm cần quyết định **3 sub-question** này cùng lúc:

**Q2a: UI — React full hay Gradio đơn giản?**

| Option | Effort | Output |
|---|---|---|
| React + Cytoscape.js + Timeline Slider | ~4 tuần | Demo đẹp, phù hợp bảo vệ |
| Gradio / Streamlit | ~1 tuần | Nhanh, đủ demo chức năng |

> Phụ thuộc số người và thời gian còn lại. Nếu nhóm < 3 người hoặc < 4 tháng: chọn Gradio.

**Quyết định Q2a**: _______________

---

**Q2b: Ground Truth — full size hay giảm?**

| Option | QA chung | Temporal QA | Effort |
|---|---|---|---|
| Full (ADR-07) | 100 câu | 50 câu | ~2 tuần/người |
| Giảm (khuyến nghị nếu < 3 người) | 50 câu | 25-30 câu | ~1 tuần/người |

> Lưu ý: Giảm dataset không ảnh hưởng tính học thuật nếu justify rõ trong báo cáo.

**Quyết định Q2b**: _______________

---

**Q2c: Dataset văn bản — 4 bắt buộc hay thêm 6 mở rộng?**

| Option | Số văn bản | Risk |
|---|---|---|
| 4 văn bản bắt buộc | LDN2020 + NĐ01 + NĐ47 + TT01 | Đủ demo, graph nhỏ |
| 10 văn bản | +LDN2014 + NĐ78 + NĐ108 + ... | Graph phong phú hơn, tốn thêm 2 tuần parsing |

**Quyết định Q2c**: Chọn **10 văn bản curated** làm research corpus; 4 văn bản
là minimum demo. 89 văn bản đã crawl là discovery pool, không mặc định thuộc
curated/evaluation scope và không được commit vào Git.

---

### Q3: Baseline so sánh — 1 hay 2?

Hiện tại có **mâu thuẫn** giữa các file:

| File | Nội Dung |
|---|---|
| `ADR-07` | Chỉ so sánh với **1 baseline** (Vector RAG) |
| `RC5` trong `01_research_contributions.md` | Đã chỉnh: Vector RAG là main baseline, BM25 là optional ablation |

| Option | Pros | Cons |
|---|---|---|
| **1 baseline (Vector RAG)** | Đơn giản, báo cáo gọn | Ít so sánh hơn |
| **BM25 optional ablation** | Có thêm góc nhìn keyword retrieval | Không bắt buộc nếu thiếu thời gian |

> [!IMPORTANT]
> Main baseline là **Naive Vector RAG**. BM25 chỉ là optional secondary ablation nếu còn thời gian.

**Quyết định**: 1 main baseline — **Naive Vector RAG**. BM25 là optional ablation, không phải baseline bắt buộc.

---

## 🟡 Nhóm 2 — Câu Hỏi Kỹ Thuật (Gợi Ý Sẵn)

> [!NOTE]
> Các câu này đã có gợi ý. Nhóm chỉ cần gật/lắc đầu và ghi vào Decision Log.

### Q4: Confidence Scoring — N=3 hay Rule-based?

> [!WARNING]
> **Mâu thuẫn hiện tại**: ADR-06 đã chốt **rule-based**, nhưng `09_open_questions.md` cũ vẫn ghi N=3.

| Option | Mô Tả | Gợi Ý |
|---|---|---|
| **Rule-based (ADR-06)** | JSON valid? + Ontology valid? + Evidence? + Entities resolve? | ✅ Explainable, không tốn API |
| Self-consistency N=3 | 3 lần gọi LLM, majority vote | Tốn 3x cost, ít explainable hơn |

**Quyết định**: Rule-based theo ADR-06; implementation hiện hành không dùng self-consistency N=3.

---

### Q5: Intent Classification — Few-shot trước, PhoBERT sau?

**Quyết định**: Runtime hiện hành dùng deterministic six-intent router. PhoBERT/XLM-R chỉ là hướng fine-tune/ablation sau khi có labeled dataset; few-shot LLM không nằm trên request path hiện tại.

---

### Q6: Threshold Human Review — giữ 0.3 / 0.7 không?

Gợi ý: **Dùng**, nhưng sẽ calibrate lại trên validation set 3 văn bản (per ADR-06).

```
< 0.3    → Auto-reject (Rejection Log)
0.3-0.7  → Human Review Queue
≥ 0.7    → Auto-accept → Neo4j
```

**Quyết định**: Runtime defaults là review `0.55`, auto-accept `0.8`; mọi thay đổi phải calibrate lại bằng validation data.

---

### Q7: Reranker — Phase 2.5 candidate selection?

Gợi ý: **Có nếu còn thời gian** — BM25 chỉ là ablation nhỏ, không thay thế main baseline Vector RAG.

**Quyết định**: Reranker thuộc Phase 2.5 retrieval roadmap. Default candidate là `bge-reranker-v2-m3`; ablation candidate là `Qwen3-Reranker-0.6B`; `gte-multilingual-reranker-base` là secondary candidate. BM25/Neo4j fulltext chỉ là optional non-model ablation.

---

### Q8: Definition — node riêng hay attribute của Concept?

| Option | Pros | Cons |
|---|---|---|
| Attribute `Concept.definition` | Đơn giản hơn, ít node hơn | Không query được "Ai định nghĩa X?" |
| Node riêng `(:Definition)` | Query phong phú hơn | Schema phức tạp hơn |

Gợi ý: **Attribute** — đơn giản hơn, đủ dùng cho use case hiện tại.

**Quyết định**: _______________

---

### Q9: Node Procedure — làm hay future work?

Gợi ý: **Future Work** — scope creep, không đủ thời gian làm sâu.

**Quyết định**: _______________

---

### Q10: Deployment — Docker Compose hay cần cloud?

Gợi ý: **Docker Compose đủ** cho đồ án tốt nghiệp.

**Quyết định**: _______________

---

### Q11: Graph Visualizer — Cytoscape.js hay đơn giản hơn?

Phụ thuộc Q2a. Nếu dùng Gradio thì dùng `pyvis` hoặc `streamlit-agraph` thay Cytoscape.js.

**Quyết định**: _______________ (sau khi chốt Q2a)

---

## 🔴 Nhóm 3 — Câu Hỏi Mới Phát Hiện (Plan Chưa Đề Cập)

> [!CAUTION]
> Đây là **lỗ hổng thực sự** trong plan. Nếu không giải quyết trước khi code, sẽ bị chặn giữa chừng hoặc ra kết quả evaluation sai.

### Q12: Web crawl có khi nào trả về `source.txt` rỗng hoặc thiếu câu chữ?

**Vấn đề**: `04_graph_construction_pipeline.md` giả định crawler lấy được raw text ổn định từ vbpl.vn. Nếu HTML đổi cấu trúc, nội dung tải chậm, hoặc selector sai, `source.txt` có thể rỗng hay bị cắt cụt.

**Cần kiểm tra**: Crawl thử 10 văn bản trong danh sách, kiểm tra:
```bash
# Kiểm tra nhanh source.txt
wc -c data/raw/*/source.txt
head -n 20 data/raw/*/source.txt
# Nếu output rỗng hoặc quá ngắn → cần sửa crawler / retry / fallback selector
```

| Kết quả | Action |
|---|---|
| Tất cả source.txt đầy đủ | Không cần thay đổi pipeline |
| Có 1-2 source.txt bị thiếu | Thêm retry / fallback selector vào crawler |
| Nhiều văn bản bị thiếu | Cân nhắc đổi chiến lược crawl hoặc thay nguồn dữ liệu |

> [!WARNING]
> Nguồn tin cậy nhất để crawl raw text: **vbpl.vn** (Cơ sở dữ liệu văn bản pháp luật quốc gia). Ưu tiên tải từ đây.

**Action cần làm**: Kiểm tra 10 văn bản trước buổi họp. Ghi kết quả vào đây.

**Kết quả kiểm tra**: _______________

---

### Q13: Temporal Traversal với DAG (không phải chain tuyến tính)

**Vấn đề**: Plan hiện tại giả định amendments theo chain tuyến tính:
```
A ←[AMENDS t1]← B ←[AMENDS t2]← C
```

Nhưng thực tế pháp luật có thể tạo ra DAG:
```
A ←[AMENDS t1, partial: khoản 1]← B
A ←[AMENDS t2, partial: khoản 3]← C
```
Lúc này, tại thời điểm t3 > t2 > t1, phiên bản hợp lệ của A là:
- Khoản 1: lấy từ B (theo t1)
- Khoản 3: lấy từ C (theo t2)
- Khoản 2, 4, 5...: vẫn lấy từ A gốc

Cypher `AMENDS*1..5` với `priority: latest` sẽ **xử lý sai** trường hợp này.

**3 Options:**

| Option | Mô Tả | Khuyến Nghị |
|---|---|---|
| A) **Giả định chain tuyến tính** | Document limitation trong báo cáo | ✅ Thực tế nhất cho đồ án |
| B) Thiết kế DAG traversal | Xử lý đúng, query phức tạp hơn | Thêm 2-3 tuần |
| C) Atomic amendment nodes | Mỗi amendment = 1 node riêng biệt | Thay đổi schema hoàn toàn |

**Quyết định**: Option A — giả định chain tuyến tính, ghi rõ limitation trong báo cáo. Đây là assumption hợp lý cho scope đồ án; DAG amendment là future work.

> [!NOTE]
> Câu trong báo cáo: *"Đề tài giả định mỗi điều khoản chỉ có một chuỗi sửa đổi tuyến tính tại mỗi thời điểm. Xử lý trường hợp đa luồng sửa đổi song song là một hướng mở rộng trong tương lai."*

> [!NOTE]
> **Bổ sung — PARTIALLY_EFFECTIVE propagation** (2026-07-06): Tương tự giả định chain tuyến tính, hệ thống giả định `PARTIALLY_EFFECTIVE` propagation xuống Article/Clause **được annotate thủ công** cho 4 văn bản bắt buộc — không xây dựng logic tự động nhận diện điều khoản chuyển tiếp (transitional provisions). Lý do: với 4 văn bản known corpus, số case PARTIALLY_EFFECTIVE có thể đếm thủ công; logic tự động đòi hỏi parser nhận diện được loại điều khoản "bãi bỏ Điều X, sửa Khoản Y Điều Z" — vượt scope M3.
>
> Câu limitation bổ sung trong báo cáo: *"Trong trường hợp văn bản ở trạng thái PARTIALLY_EFFECTIVE, hệ thống yêu cầu human annotation xác định từng Article/Clause bị ảnh hưởng — tự động hóa bước này là hướng phát triển tiếp theo."*
>
> **Metric đo lường** (Milestone A, Tuần 3 — Graph Quality Evaluation):
> ```cypher
> // AMENDS Propagation Consistency Rate
> // = 1 - (cặp AMENDS có old.effective_to không khớp / tổng AMENDS edges)
> MATCH (newer)-[r:AMENDS]->(old)
> WHERE old.effective_to IS NOT NULL
>   AND old.effective_to <> r.effective_from
> RETURN count(*) as inconsistent_count
> ```
> Target: inconsistent_count = 0 sau mỗi pipeline run.

**Quyết định**: **Option A** — chain tuyến tính + PARTIALLY_EFFECTIVE annotation thủ công + ghi limitation (ADR context: Q13, 2026-07-06)



---

### Q14: ID Canonicalization cho Concept/Entity — Evaluation Level 1

**Vấn đề**: Không giống Article/Clause (có số điều, số khoản để derive ID tự động), Concept và Entity được sinh ra bởi LLM. 

Nếu:
- Gold annotation: `concept_von_dieu_le`
- LLM extraction: `concept_von_dieu_le_cong_ty` hoặc `concept_vdl`

**String matching sẽ = 0** dù về ngữ nghĩa là cùng 1 concept → Precision/Recall đo sai.

**3 Options:**

| Option | Cách Làm | Effort |
|---|---|---|
| A) **Pre-defined concept list** | Xây trước ~50-100 concept pháp lý phổ biến, cả gold và LLM đều map vào list này | ✅ Thấp, evaluation chính xác |
| B) Fuzzy string matching | Edit distance hoặc cosine similarity của embedding | Trung bình, vẫn có false positives |
| C) LLM-as-judge | LLM quyết định 2 entity có cùng nghĩa không | Cao, tốn cost |

**Khuyến nghị**: Option A — xây trước pre-defined concept list ~50-100 entries cho domain luật doanh nghiệp. Cả gold annotation và LLM extraction đều phải normalize về danh sách này.

> [!IMPORTANT]
> Quyết định này ảnh hưởng đến **RC5 Level 1 Evaluation**. Nếu không giải quyết, con số Relation Precision/Recall sẽ không phản ánh đúng chất lượng pipeline.

**Quyết định**: _______________

---

### Q15: Vietnamese Legal NLP Related Work — Đã Search Chưa?

**Vấn đề**: Đề tài khẳng định ontology cho pháp luật doanh nghiệp VN là "chưa có ai làm". Cần verify trước khi bảo vệ.

**Cần search các từ khóa sau** (Google Scholar, Semantic Scholar, ACL Anthology):

```
"Vietnamese legal" NLP
"legal QA Vietnam" 
"Vietnamese legal question answering"
"pháp luật Việt Nam" knowledge graph
ViLegalQA
VLSP legal NLP shared task
```

**Các nguồn cần check:**
- ACL Anthology (https://aclanthology.org/) — search "Vietnamese legal"
- Semantic Scholar — search "Vietnamese legal NLP"
- VLSP Workshop proceedings (2020-2024)
- VNU-HCM, HUST thesis/papers on legal NLP

**Expected findings** (dự đoán):
- Có thể có keyword search / basic QA cho luật VN
- Ít khả năng có Knowledge Graph + Temporal + XAI kết hợp
- Ontology chuyên biệt cho luật doanh nghiệp VN rất có thể là contribution mới

> [!WARNING]
> **Phải làm trước khi viết Section 2 (Related Work) của báo cáo.** Nếu có paper tương tự, cần điều chỉnh cách định vị contribution.

**Action**: Ai phụ trách Literature Review search và tổng hợp kết quả?  
**Deadline**: Trước khi viết báo cáo (cuối tháng 1 theo timeline).  
**Kết quả**: _______________

---

## Decision Log (Điền Sau Khi Họp)

| Q | Câu Hỏi Tóm Tắt | Quyết Định | Nguồn | Ngày |
|---|---|---|---|---|
| Q1 | Phân công nhóm | TBD — cần họp nhóm | — | — |
| Q2a | UI: React hay Gradio? | TBD — phụ thuộc số người | — | — |
| Q2b | Ground truth: 100 hay 50 câu? | **50 QA + 25 temporal** (giảm scope) | 11_project_phases.md | 2026-07 |
| Q2c | Dataset: 4 hay 10 văn bản? | **10 curated; 4 minimum demo; crawl pool tách khỏi evaluation scope** | 08_dataset_and_scope.md | 2026-07 |
| Q3 | Baseline: 1 hay 2? | **1 baseline (Vector RAG)** | ADR-07 | 2026-07 |
| Q4 | Confidence: rule-based hay N=3? | **Rule-based** (JSON valid + Ontology valid + Evidence + Entities resolve) | ADR-06 | 2026-07 |
| Q5 | Intent: few-shot + PhoBERT ablation? | **Few-shot LLM main, PhoBERT là ablation** nếu còn thời gian | ADR-05 | 2026-07 |
| Q6 | Threshold: 0.3 / 0.7? | **Giữ 0.3/0.7**, calibrate lại trên validation set | ADR-06 | 2026-07 |
| Q7 | Reranker Phase 2.5? | **Có nếu còn thời gian** — `bge-reranker-v2-m3` default, `Qwen3-Reranker-0.6B` ablation, BM25/fulltext optional non-model ablation | 05_graphrag_retrieval.md, 10_tech_stack.md | 2026-07 |
| Q8 | Definition: node hay attribute? | **Attribute** (`Concept.definition`) — ADR-10 xóa Definition node | ADR-10 | 2026-07 |
| Q9 | Procedure: future work? | **Future Work** — ghi rõ trong §8 legal_ontology.md | ADR, legal_ontology.md §8 | 2026-07 |
| Q10 | Deployment: Docker Compose? | **Docker Compose** đủ cho đồ án | 11_project_phases.md P5-1 | 2026-07 |
| Q11 | Visualizer: Cytoscape.js? | TBD — sau khi chốt Q2a | — | — |
| Q12 | Raw text crawl: `source.txt` có ổn định không? | TBD — cần kiểm tra 10 văn bản | — | — |
| Q13 | Temporal DAG: giả định chain + limitation? | **Giả định chain tuyến tính** + ghi limitation trong báo cáo | Q13 gợi ý Option A | 2026-07 |
| Q14 | Concept ID: dùng pre-defined list? | **Pre-defined list ~50-100 concepts** | Q14 gợi ý Option A | 2026-07 |
| Q15 | Related work VN legal NLP: ai search? | TBD — assign trước khi viết báo cáo | — | — |

---

## Thứ Tự Ưu Tiên Giải Quyết

```
TRƯỚC buổi họp nhóm:
  └── Q12: Kiểm tra raw text crawl (ai đó làm luôn, 30 phút)
  └── Q15: Bắt đầu search related work (có thể song song)

TRONG buổi họp nhóm:
  ├── Q1  → Q2a, Q2b, Q2c (chain dependency)
  ├── Q3  → update ADR-07 và RC5 cho nhất quán
  ├── Q13 → quyết định approach + viết limitation statement
  ├── Q14 → quyết định pre-defined concept list
  └── Q4-Q11 → gật/lắc đầu nhanh

SAU buổi họp:
  └── Update tất cả file plan cho nhất quán với decisions
  └── Bắt đầu implementation
```
