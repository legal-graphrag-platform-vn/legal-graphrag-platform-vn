# Architecture Decision Records (ADR)

> **Mục đích**: Ghi lại 7 quyết định kiến trúc đã được chốt (frozen), kèm lập luận rõ ràng  
> **Định dạng**: Problem → Options → Decision → Rationale → Trade-offs  
> **Cách dùng**: Khi hội đồng hỏi "Tại sao em chọn cách này?", trả lời bằng document này

---

> [!IMPORTANT]
> Đây là **thiết kế nghiên cứu**, không phải thiết kế kỹ thuật đơn thuần.  
> Mỗi quyết định phải có **lập luận học thuật**, không phải chỉ "vì tiện" hay "vì quen".

---

## ADR-01: Ontology Design

### Problem
Biểu diễn tri thức pháp luật doanh nghiệp VN trong Knowledge Graph đòi hỏi một schema phù hợp với đặc thù của hệ thống pháp luật VN — vốn có cấu trúc phân cấp nghiêm ngặt (Luật → Nghị định → Thông tư) và ngữ nghĩa quan hệ phức tạp (sửa đổi, thay thế, hướng dẫn, viện dẫn).

### Options Considered

| Option | Mô Tả | Vấn Đề |
|---|---|---|
| A) Dùng schema generic | Subject-Predicate-Object đơn giản | Mất ngữ nghĩa pháp lý, không phân biệt được loại văn bản |
| B) Dùng chuẩn quốc tế (Akoma Ntoso, LKIF) | Ontology pháp luật quốc tế | Không phù hợp hệ thống pháp luật VN, cấu trúc khác |
| **C) Domain-specific ontology** | Tự xây dựng cho pháp luật doanh nghiệp VN | Tốn effort, nhưng phù hợp nhất |

### ✅ Decision: Option C — Domain-specific ontology

### Rationale
1. Hệ thống pháp luật VN có cấu trúc riêng không ánh xạ 1-1 với chuẩn quốc tế (ví dụ: "Khoản" không tương đương "Paragraph" trong Akoma Ntoso).
2. Quan hệ như `IMPLEMENTED_BY` (Nghị định hướng dẫn Luật) là đặc thù của hệ thống pháp luật Việt Nam.
3. Tự xây ontology = đóng góp nghiên cứu RC1.
4. Có thể tham chiếu chuẩn quốc tế trong related work để định vị contribution.

### Trade-offs
- ✅ Phù hợp với domain
- ✅ Là contribution của đề tài
- ❌ Cần validate với legal expert
- ❌ Khó generalize sang lĩnh vực pháp luật khác (nhưng có thể mở rộng — future work)

### Justification cho hội đồng
> *"Các ontology quốc tế như Akoma Ntoso được thiết kế cho hệ thống pháp luật châu Âu, không phản ánh đúng cấu trúc phân cấp và quan hệ đặc thù của văn bản quy phạm pháp luật Việt Nam. Do đó, đề tài đề xuất một domain-specific ontology như là đóng góp nghiên cứu đầu tiên."*

---

## ADR-02: Chunking Strategy

### Problem
RAG truyền thống chia văn bản thành các chunk theo số token (512, 1024 token). Với văn bản pháp luật, cách này tạo ra **ngữ nghĩa pháp lý không hoàn chỉnh** — một điều khoản bị cắt giữa chừng mất đi tính pháp lý.

### Options Considered

| Option | Mô Tả | Vấn Đề |
|---|---|---|
| A) Token-based chunking | Cắt theo 512/1024 tokens | Phá vỡ ranh giới pháp lý, mất ngữ cảnh |
| B) Sentence-based chunking | Cắt theo câu | Câu pháp lý thường dài, không đủ ngữ cảnh |
| C) Sliding window | Overlap giữa các chunk | Duplicate context, không giải quyết vấn đề semantic |
| **D) Hierarchical chunking** | Chunk theo Điều → Khoản → Điểm | Mỗi chunk = một đơn vị pháp lý hoàn chỉnh |

### ✅ Decision: Option D — Hierarchical Chunking

### Rationale
1. **Đơn vị ngữ nghĩa pháp lý tự nhiên**: Một "Khoản" (Clause) là đơn vị ngữ nghĩa hoàn chỉnh trong pháp luật — có thể tồn tại độc lập, có thể bị sửa đổi độc lập, có thể được viện dẫn độc lập.
2. **Mapping 1-1 với Knowledge Graph**: Mỗi chunk = một node trong graph → không cần mapping phức tạp giữa vector search và graph.
3. **Citation chính xác**: Khi retrieve được chunk, biết ngay đó là "Khoản 1, Điều 17, Luật Doanh nghiệp 2020" — không cần post-processing.
4. **Temporal validity**: Mỗi chunk có `effective_from/to` riêng → temporal filter hoạt động ở cấp độ đơn vị ngữ nghĩa.

### Implementation

```
Hierarchy levels và khi nào dùng:

Điều (Article)    → Chunk khi hỏi về chủ đề tổng quát
Khoản (Clause)    → Chunk chính — unit cơ bản nhất ⭐
Điểm (Point)      → Chunk khi cần chi tiết cụ thể

Adaptive sizing:
- Điều có ≤ 3 khoản ngắn → chunk ở level Điều
- Điều có > 3 khoản       → chunk ở level Khoản
- Khoản có > 5 điểm       → chunk ở level Điểm
```

### Trade-offs
- ✅ Semantic integrity — mỗi chunk có nghĩa pháp lý đầy đủ
- ✅ Trực tiếp map với Knowledge Graph nodes
- ✅ Citation tự động và chính xác
- ✅ Đây là **contribution** (khác biệt với token-based RAG)
- ❌ Chunk size không đồng đều (một Điều có thể rất dài)
- ❌ Cần parser chính xác để detect ranh giới Điều/Khoản/Điểm

### Justification cho hội đồng
> *"Token-based chunking phá vỡ tính toàn vẹn ngữ nghĩa của văn bản pháp luật — một điều khoản bị cắt ngang không còn giá trị pháp lý. Đề tài đề xuất hierarchical chunking theo cấu trúc phân cấp của văn bản pháp luật VN, đảm bảo mỗi đơn vị được truy xuất là một đơn vị pháp lý hoàn chỉnh và có thể được trích dẫn chính xác."*

### So Sánh Với Related Work
| Approach | RAG truyền thống | **Đề tài này** |
|---|---|---|
| Chunking | Token-based (512 tokens) | Hierarchical (Điều/Khoản/Điểm) |
| Chunk identity | Không có (offset-based) | Có (Article ID, Clause ID) |
| Citation | Approximate ("đoạn văn gần...") | Chính xác ("Khoản 1, Điều 17") |
| Temporal | Không có | effective_from / effective_to |

---

## ADR-03: Entity & Relation Extraction

### Problem
Chuyển đổi văn bản pháp luật tự nhiên thành triple (head, relation, tail) là bài toán Information Extraction có độ chính xác không tuyệt đối.

### Options Considered

| Option | Mô Tả | Vấn Đề |
|---|---|---|
| A) Rule-based (Regex + NLP) | Pattern matching theo cấu trúc câu | Không handle ngôn ngữ tự nhiên phức tạp |
| B) Fine-tuned NER model | Huấn luyện model riêng | Cần nhiều labeled data, tốn thời gian |
| **C) LLM + Validation** | LLM extract + schema/ontology validate | Balance tốt nhất |
| D) LLM only | Không validate | Hallucination không được kiểm soát |

### ✅ Decision: Option C — LLM + JSON Schema + Ontology Validation

### Rationale
1. LLM hiểu ngôn ngữ tự nhiên pháp lý tốt hơn rule-based.
2. JSON Schema Validation đảm bảo format đúng — loại bỏ hallucination về cấu trúc.
3. Ontology Validation đảm bảo ngữ nghĩa đúng — loại bỏ relation không tồn tại trong ontology.
4. Không cần labeled data để train model riêng.

### Trade-offs
- ✅ Không cần labeled training data
- ✅ Hai lớp validation bổ sung cho nhau
- ❌ Phụ thuộc vào chất lượng LLM và prompt
- ❌ API cost cho 20 văn bản

---

## ADR-04: Intent Classification

### Problem
Hệ thống GraphRAG cần biết loại câu hỏi để chọn Traversal Strategy phù hợp.

### Options Considered

| Option | Mô Tả | Vấn Đề |
|---|---|---|
| A) Rule-based keyword | Keyword → intent | Không robust, miss nhiều pattern |
| **B) LLM-based, fixed intent set** | Prompt LLM với 6 intent classes | Không cần train, dễ thêm/sửa intent |
| C) Fine-tuned PhoBERT | Train classifier | Cần ~200 labeled samples, 2-3 tuần |
| D) Embedding similarity | Cosine similarity với intent templates | Không chính xác với câu phức tạp |

### ✅ Decision: Option B — LLM-based với tập intent cố định

### Rationale
1. **Không huấn luyện model mới** — tập trung resource vào core research (RC1-RC4).
2. Tập intent cố định (6 classes) đủ bao phủ các dạng câu hỏi pháp luật thực tế.
3. Dễ debug: khi sai, chỉ cần sửa prompt hoặc thêm few-shot examples.
4. Có thể compare với rule-based baseline → thêm 1 ablation experiment nhỏ.

> [!NOTE]
> **Lưu ý**: Fine-tuned PhoBERT vẫn có thể làm trong tháng 3 như một **ablation study** phụ, không phải là quyết định kiến trúc chính.

### Justification cho hội đồng
> *"Mục tiêu chính của đề tài là nghiên cứu GraphRAG cho pháp luật, không phải nghiên cứu Intent Classification. Do đó, đề tài lựa chọn LLM-based classification với tập intent cố định — đủ hiệu quả cho mục tiêu thực nghiệm mà không làm lệch trọng tâm nghiên cứu."*

---

## ADR-05: Graph Traversal Strategy

### Problem
Graph Traversal không định hướng sẽ dẫn đến context explosion (quá nhiều nodes không liên quan) hoặc bỏ lỡ context quan trọng.

### Options Considered

| Option | Mô Tả | Vấn Đề |
|---|---|---|
| A) BFS không giới hạn | Traverse tất cả | Context explosion, noise |
| B) Fixed depth (3-hop tất cả relations) | Đơn giản | Không phân biệt loại câu hỏi, nhiều noise |
| **C) Intent-based, 2-hop mặc định** | Relation types và depth phụ thuộc intent | Precision cao hơn |
| D) Learned traversal | Train RL agent | Quá phức tạp cho đồ án |

### ✅ Decision: Option C — Traversal theo Intent, 2-hop mặc định, mở rộng khi cần

### Rationale
1. **Semantic precision**: Câu hỏi về "hiệu lực" chỉ cần traverse `AMENDED_BY/REPLACED_BY`, không cần `DEFINES`.
2. **2-hop mặc định**: Đủ bao phủ 90%+ câu hỏi pháp luật thực tế (A → hướng dẫn B → có hiệu lực C).
3. **Mở rộng khi cần**: Multi-hop intent cho phép tới 3-hop khi câu hỏi cần suy luận nhiều bước.
4. **Đây là novelty của RC3**: Traversal Policy là cơ chế phân biệt GraphRAG của đề tài với naive graph search.

### 2-hop Default: Lý do

```
2-hop bao phủ:
  Luật DN 2020 (Điều 17) 
      → IMPLEMENTED_BY → Nghị định 01/2021 (hop 1)
      → CONTAINS → Điều 5 NĐ01 (hop 2)

3-hop cho multi-hop:
  Điều 17 LDN 2020
      → IMPLEMENTED_BY → NĐ 01/2021 (hop 1)
      → GUIDED_BY → TT 01/2021 (hop 2)
      → CONTAINS → Điều 3 TT01 (hop 3)

4-hop thường là noise.
```

### Justification cho hội đồng
> *"Traversal Policy mapping từ intent sang tập quan hệ cụ thể cho phép hệ thống tập trung vào đúng chiều ngữ nghĩa của câu hỏi, thay vì traverse mọi quan hệ. Giới hạn 2-hop mặc định được chọn dựa trên phân tích cấu trúc hệ thống văn bản pháp luật VN, trong đó đa số câu hỏi thực tế chỉ cần đi qua tối đa 2 cấp quan hệ."*

---

## ADR-06: Confidence Scoring

### Problem
LLM extraction có thể sai. Cần cơ chế phân loại extraction nào đủ tin cậy để auto-import, cái nào cần human review.

### Options Considered

| Option | Mô Tả | Vấn Đề |
|---|---|---|
| A) Self-consistency (N=3 LLM runs) | Majority vote qua nhiều lần gọi | Tốn 3x API cost, không giải thích được |
| B) Log-probability | Token log-probs | Không phải LLM nào cũng expose |
| **C) Rule-based multi-criteria** | Kết hợp nhiều tiêu chí, threshold trên validation set | Explainable, không tốn thêm API |
| D) Critic LLM | LLM 2 đánh giá LLM 1 | Đắt nhất |

### ✅ Decision: Option C — Rule-based confidence kết hợp nhiều tiêu chí

### Rationale
1. **Explainability**: Biết tại sao confidence thấp (schema fail? ontology fail? evidence missing?) — có thể fix có chủ đích.
2. **Không tốn thêm API calls**: Toàn bộ criteria đều compute-local.
3. **Threshold on validation set**: Không arbitrary — justify bằng precision/recall tradeoff trên 3 văn bản annotated.
4. **Phù hợp với nguyên tắc "thiết kế nghiên cứu"**: Threshold được chọn dựa trên dữ liệu, không phải cảm tính.

### Scoring Criteria

```
Confidence Score = weighted combination of:

1. JSON Schema Valid?          → 0 or 1           (weight: 0.3)
2. Ontology Valid?             → 0 or 1           (weight: 0.3)
3. Evidence in text?           → 0.0 – 1.0        (weight: 0.2)
   (LLM: "Does this evidence sentence support this relation?")
4. Entities resolvable?        → fraction resolved (weight: 0.1)
   (All head/tail IDs exist in current graph or document)
5. Relation direction correct? → 0 or 1           (weight: 0.1)

Total Confidence ∈ [0, 1]
```

### Threshold Calibration

```
Dùng 3 văn bản gold standard (annotated thủ công):
- Vẽ Precision-Recall curve theo threshold
- Chọn threshold tối ưu theo F1
- Report threshold + PR curve trong luận văn

Ví dụ kết quả:
  threshold=0.3: P=0.72, R=0.91, F1=0.80
  threshold=0.5: P=0.85, R=0.78, F1=0.81  ← optimal
  threshold=0.7: P=0.93, R=0.61, F1=0.74
```

### Justification cho hội đồng
> *"Thay vì chọn threshold theo cảm tính, đề tài hiệu chỉnh threshold trên tập validation được annotate thủ công, dựa trên đường cong Precision-Recall. Cách tiếp cận này đảm bảo quyết định có cơ sở thực nghiệm."*

---

## ADR-07: Evaluation Strategy

### Problem
Làm sao chứng minh hệ thống GraphRAG tốt hơn Vector RAG thuần? Và "tốt hơn" theo nghĩa nào?

### Options Considered

| Option | Mô Tả | Vấn Đề |
|---|---|---|
| A) Chỉ demo | Chạy vài câu và show kết quả | Không có giá trị học thuật |
| B) Chỉ dùng RAGAS | Chạy RAGAS metrics | Không đủ cho Temporal + XAI |
| C) So sánh với LLM khác | GPT-4o vs Llama vs... | Lệch focus — đây không phải bài benchmark LLM |
| **D) 4-level evaluation vs baseline** | So sánh với Vector RAG baseline trên ground truth tự xây | Đúng hướng nghiên cứu |

### ✅ Decision: Option D — So sánh với baseline Vector RAG trên Ground Truth tự xây

### Rationale
1. **Research question rõ ràng**: RQ2, RQ3, RQ4 đều cần có baseline để so sánh.
2. **Ground truth từ văn bản chính thức**: Đảm bảo tính pháp lý của dataset — không phải synthetic.
3. **4 tầng evaluation**: Mỗi tầng đo một khía cạnh khác nhau của hệ thống → holistic assessment.
4. **Baseline Vector RAG**: Là cách tiếp cận phổ biến nhất hiện nay → kết quả so sánh có ý nghĩa thực tiễn.

### Baseline Design

```
Baseline: Naive Vector RAG
  - Chunking: Token-based (512 tokens, 50 overlap)
  - Retrieval: Cosine similarity top-K
  - Generation: Same LLM, same prompt (chỉ khác context)
  - KHÔNG có: intent, graph traversal, temporal filter

Proposed: Temporal GraphRAG
  - Chunking: Hierarchical
  - Retrieval: Hybrid (vector + graph traversal theo intent)
  - Generation: Same LLM
  - CÓ: intent, traversal policy, temporal filter, XAI
```

### Expected Results (Hypothesis)

| Metric | Baseline | Proposed | Hypothesis |
|---|---|---|---|
| Factual QA Faithfulness | ~0.75 | ~0.85 | GraphRAG context chính xác hơn |
| Temporal Accuracy | ~0.40 | ~0.80 | Baseline không có temporal filter |
| Citation Completeness | ~0.50 | ~0.80 | Graph paths cho citation chính xác |
| Context Recall | ~0.65 | ~0.75 | Graph expansion recover thêm context |

> [!NOTE]
> Đây là **hypothesis**, không phải kết quả thực. Cần experiment để verify.

### Justification cho hội đồng
> *"Đề tài sử dụng bộ Ground Truth tự xây dựng từ văn bản pháp luật chính thức, bao gồm 100 câu hỏi tổng quát, 50 câu hỏi temporal, và 20-30 trường hợp đánh giá XAI. Hệ thống đề xuất được so sánh với baseline Vector RAG trên cùng bộ dữ liệu, đảm bảo tính công bằng và có thể tái hiện."*

---

## Tổng Hợp 7 Quyết Định

| ADR | Quyết Định | Lý Do Cốt Lõi | Contribution |
|---|---|---|---|
| 01 | Domain-specific Ontology | Hệ thống pháp luật VN có đặc thù riêng | RC1 |
| 02 | Hierarchical Chunking | Đơn vị ngữ nghĩa pháp lý ≠ token count | RC2 (+ contribution riêng) |
| 03 | LLM + Validation Pipeline | Balance: không cần labeled data, vẫn có quality control | RC2 |
| 04 | LLM-based Intent (no new model) | Tập trung resource vào GraphRAG, không lệch focus | RC3 |
| 05 | Intent-based Traversal, 2-hop default | Precision > Recall; 2-hop bao phủ 90% use cases | RC3 |
| 06 | Rule-based Confidence + threshold calibration | Explainable + threshold justified by data | RC2 |
| 07 | 4-level evaluation vs Vector RAG baseline | Holistic + có baseline rõ ràng để so sánh | RC5 |

---

## Checklist Trước Khi Code

Bảy quyết định trên được coi là **FROZEN** khi:

- [ ] ADR-01: Ontology có đủ Node Types + Relation Types với ví dụ cụ thể
- [ ] ADR-02: Parser có thể detect đúng ranh giới Điều/Khoản/Điểm trên ít nhất 2 văn bản test
- [ ] ADR-03: Prompt template entity + relation extraction được review bởi cả nhóm
- [ ] ADR-04: 6 intent classes được test với 20+ câu hỏi sample
- [ ] ADR-05: Traversal Policy table được chốt (intent → relations → depth)
- [ ] ADR-06: Scoring criteria và weights được chốt (có thể điều chỉnh sau khi có validation data)
- [ ] ADR-07: Ground truth dataset plan được assign người phụ trách

**Khi tất cả 7 checklist trên được tick**, đề tài mới chính thức bước vào giai đoạn implementation.
