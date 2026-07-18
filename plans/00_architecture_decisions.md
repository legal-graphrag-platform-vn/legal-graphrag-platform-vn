# Architecture Decision Records (ADR)

> **Mục đích**: Ghi lại 17 quyết định kiến trúc đã được chốt (frozen), kèm lập luận rõ ràng  
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
2. Quan hệ như `GUIDES` (Nghị định hướng dẫn Luật) là đặc thù của hệ thống pháp luật Việt Nam.
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
1. **Semantic precision**: Câu hỏi về "hiệu lực" chỉ cần traverse `AMENDS/REPLACES`, không cần `DEFINES`.
2. **2-hop mặc định**: Đủ bao phủ 90%+ câu hỏi pháp luật thực tế (A → hướng dẫn B → có hiệu lực C).
3. **Mở rộng khi cần**: Multi-hop intent cho phép tới 3-hop khi câu hỏi cần suy luận nhiều bước.
4. **Đây là novelty của RC3**: Traversal Policy là cơ chế phân biệt GraphRAG của đề tài với naive graph search.

### 2-hop Default: Lý do

```
2-hop bao phủ:
  Luật DN 2020 (Điều 17) 
      → GUIDES → Nghị định 01/2021 (hop 1)
      → CONTAINS → Điều 5 NĐ 01 (hop 2)

3-hop cho multi-hop:
  Điều 17 LDN 2020
      → GUIDES → NĐ 01/2021 (hop 1)
      → GUIDES → TT 01/2021 (hop 2)
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
> *"Đề tài sử dụng bộ Ground Truth tự xây dựng từ văn bản pháp luật chính thức. Current committed scope là 50 câu hỏi tổng quát + 25 câu hỏi temporal; target full scope là 100 câu hỏi tổng quát + 50 câu hỏi temporal, cộng 20-30 trường hợp đánh giá XAI. Hệ thống đề xuất được so sánh với baseline Vector RAG trên cùng bộ dữ liệu, đảm bảo tính công bằng và có thể tái hiện."*

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
| 08 | Neo4j native vector (no Qdrant) | Fit to scale; unified query; đơn giản hóa pipeline | RC3 |
| 09 | ~~Chapter = property~~ → **Chapter = node** (Rev.1 2026-07-06) | Structural fidelity; CONTAINS chain đầy đủ; hỗ trợ trích dẫn theo Chương | RC1 |
| 10 | Definition = attribute của Concept | Không có use case traverse qua Definition | RC1 |
| 11 | Contribution framing vendor-neutral | Contribution ở pipeline design, không ở tooling | RC3 |
| 12 | Ablation qua dimension nghiên cứu | Giá trị học thuật cao hơn so sánh database | RC5 |

---

## ADR-08: Retriever Architecture

### Problem
Retrieval layer cần kết hợp vector search + graph traversal + temporal filter. Có thể dùng Neo4j native vector index hoặc tách Qdrant (vector) + Neo4j (graph).

### Options Considered

| Option | Mô Tả | Vấn Đề |
|---|---|---|
| A) Neo4j + Qdrant riêng biệt | Qdrant cho vector, Neo4j cho graph | 2 round trips, sync issue, 2 services |
| **B) Neo4j native vector index** | Một query: vector + graph + temporal | Phù hợp với scale ~5000 clauses |

### ✅ Decision: Option B — Neo4j native vector index

### Rationale
1. **Fit to scale**: ~5000 clauses không phải bài toán performance — là bài toán correctness.
2. **Graph là core, vector là entry point**: Tách vector store = tách entry point ra khỏi core reasoning.
3. **Unified query**: Một Cypher query thực hiện vector search → temporal filter → graph traversal atomically.
4. **Operational simplicity**: 1 database, 1 schema, 0 sync issue.

### Interface Pattern
Dù dùng Neo4j native, vẫn thiết kế theo interface:
```python
class RetrieverInterface(ABC):
    def retrieve(self, query, temporal_ctx) -> RetrievalContext: pass

class Neo4jRetriever(RetrieverInterface):
    """Main implementation — unified query"""
    pass
```
Interface cho phép: unit test với mock, swap backend nếu cần, không khóa kiến trúc.

### Justification cho hội đồng
> *"Với quy mô ~5000 clauses, kiến trúc unified storage cho phép thực hiện semantic retrieval, graph expansion và temporal filtering trong một query duy nhất. Với quy mô lớn hơn, interface-based design cho phép thay thế bằng vector database chuyên dụng mà không ảnh hưởng các tầng còn lại."*

---

## ADR-09: Chapter/Section Representation

### Problem
Văn bản pháp luật VN có cấu trúc Phần → Chương → Mục → Điều → Khoản → Điểm. Có nên tạo node riêng cho Chương/Mục không?

### ~~Decision v1 (2026-06-29, SUPERSEDED)~~: ~~Chapter = Property trên Article~~

> ⚠️ Quyết định này đã được **đảo ngược** bởi Rev.1 bên dưới.

---

### ✅ Decision Rev.1 (2026-07-06, FROZEN): Chapter = Node trong Structural Layer

Per **`legal_ontology.md v1.1.0`** — CONTAINS chain đầy đủ:

```cypher
// Structural hierarchy — Chapter là node thực sự
(:Document)-[:CONTAINS]->(:Chapter {
  id: "ldn_2020_ch2",
  number: "II",
  title: "Thành lập doanh nghiệp"
})-[:CONTAINS]->(:Article {
  id: "ldn_2020_art17",
  number: "17",
  title: "..."
})

// Traversal transparent với Chapter — dùng *1..3
MATCH (doc:Document {id: "ldn_2020"})-[:CONTAINS*1..3]->(a:Article)
```

### Rationale (Rev.1)
1. **Structural fidelity**: Chapter là thực thể thực sự tồn tại trong văn bản pháp luật VN, không chỉ là grouping label. "Chương II — Thành lập doanh nghiệp" có ý nghĩa ngữ nghĩa.
2. **Trích dẫn pháp lý**: Nhiều văn bản VN trích dẫn "theo quy định tại Chương II" — không có Chapter node thì không map được đường trích dẫn.
3. **CONTAINS chain nhất quán**: `Doc → Chapter → Article → Clause → Point` sạch hơn `Doc → Article {chapter property}`. Hội đồng hỏi tại sao graph bỏ tầng Chương sẽ khó trả lời trong bối cảnh luận văn Legal KG.
4. **Ontology mới hơn**: `legal_ontology.md v1.1.0` (2026-07-03) là kết quả sau 4+ rounds debate, supersede ADR-09 trên điểm này.
5. **Traversal không ảnh hưởng**: `CONTAINS*1..3` bao phủ cả Doc→Article (không có Chapter) lẫn Doc→Chapter→Article — backward compatible.

### Tại sao v1 sai
- Rationale v1 đúng về intent classes — nhưng confuse **retrieval logic** với **ontology design**. Ontology phải model thế giới đúng; traversal policy mới là nơi tối ưu cho retrieval.
- Property approach mất dữ liệu: không truy vấn được "tất cả Điều trong Chương II" bằng graph traversal.

### Impact
- Parser: tạo `(:Chapter)` node thay vì chỉ fill property `chapter:` trên Article.
- Schema: thêm `Chapter` node type vào `01_schema_init.cypher`.
- `article.chapter` property: xóa khỏi Article schema (không cần nữa).

---

## ADR-10: Definition Representation

### Problem
"Definition" ban đầu được coi là entity type riêng trong pipeline. Có nên tạo node `:Definition` không?

### ✅ Decision: Definition = attribute của Concept, không phải node riêng

```cypher
(:Concept {
  id: "concept_von_dieu_le",
  name: "Vốn điều lệ",
  definition: "Là tổng giá trị tài sản...",  // ← attribute
  defined_in: "ldn_2020_art4_cl22"           // ← backref để cite
})
```

### Rationale
1. Định nghĩa pháp lý là 1-1 với Concept — không có use case traverse qua Definition.
2. Làm attribute đơn giản hơn, ít node hơn.
3. `defined_in` property đủ để XAI trace về Điều luật nguồn.
4. **Action**: Xóa `"Definition"` khỏi entity type enum trong `04_graph_construction_pipeline.md` — **đã thực hiện**.

---

## ADR-11: Contribution Framing — Vendor Neutral

### Problem
RC3 ban đầu mô tả như "sử dụng Neo4j unified vector index thay vì Qdrant" → contribution phụ thuộc vendor.

### ✅ Decision: Contribution là pipeline design, không phải tooling choice

**Framing đúng:**
> *"Một Unified Hybrid Retrieval Pipeline kết hợp semantic retrieval, intent-based graph expansion và temporal reasoning trong cùng một workflow — trong đó traversal strategy phụ thuộc vào loại câu hỏi thay vì áp dụng cố định cho mọi truy vấn."*

Neo4j chỉ là implementation detail. Về lý thuyết, pipeline này có thể implement trên bất kỳ graph DB nào hỗ trợ vector.

---

## ADR-12: Ablation Study Design

### Problem
Cần ablation study để chứng minh từng thành phần của hệ thống đóng góp vào kết quả.

### ✅ Decision: Ablation theo dimension nghiên cứu, không phải so sánh database

| Ablation | Câu hỏi nghiên cứu |
|---|---|
| Graph expansion ON vs OFF | Graph có giúp gì so với vector thuần? |
| Traversal depth: 1 vs 2 vs 3 | Depth tối ưu là bao nhiêu cho legal QA? |
| Temporal filter ON vs OFF | Temporal reasoning cải thiện accuracy bao nhiêu? |
| Intent-based vs fixed traversal | Intent classification có thực sự cần không? |

### Rationale
- Các ablation này map trực tiếp vào RC3 (traversal) và RC4 (temporal).
- Giá trị nghiên cứu cao hơn so với "Neo4j vs Qdrant benchmark".
- Mỗi ablation là 1 experiment nhỏ trong RC5 evaluation framework.
- **Không implement Qdrant retriever** — không có research value cho đề tài này.

---

## Checklist Trước Khi Code

Các quyết định được coi là **FROZEN** khi:

- [ ] ADR-01: Ontology có đủ Node Types + Relation Types với ví dụ cụ thể
- [ ] ADR-02: Parser có thể detect đúng ranh giới Điều/Khoản/Điểm trên ít nhất 2 văn bản test
- [ ] ADR-03: Prompt template entity + relation extraction được review bởi cả nhóm
- [ ] ADR-04: 6 intent classes được test với 20+ câu hỏi sample
- [ ] ADR-05: Traversal Policy table được chốt (intent → relations → depth)
- [ ] ADR-06: Scoring criteria và weights được chốt (có thể điều chỉnh sau khi có validation data)
- [ ] ADR-07: Ground truth dataset plan được assign người phụ trách
- [ ] ADR-08: Verify Neo4j 5.11+ Community support vector index (`CREATE VECTOR INDEX`)
- [x] ADR-09 Rev.1: Parser tạo `(:Chapter)` node (không fill property `chapter` trên Article); `Chapter` được thêm vào `01_schema_init.cypher`
- [ ] ADR-10: `"Definition"` đã được xóa khỏi entity enum trong pipeline ✅
- [ ] ADR-11: RC3 description trong báo cáo dùng vendor-neutral framing
- [ ] ADR-12: 4 ablation experiments được lên kế hoạch trong evaluation framework

**Khi tất cả checklist trên được tick**, đề tài mới chính thức bước vào giai đoạn implementation.


---

## ADR-13: Two-Layer Ontology Architecture

**Ngày**: 2026-07-03  
**Trạng thái**: FROZEN

### Problem
Graph chỉ có Document → Article → Clause ("cây văn bản") không đủ để gọi là Knowledge Graph. Cần phân biệt rõ tầng metadata và tầng tri thức.

### Decision
Tách thành **Structural Layer** (Document, Chapter, Article, Clause, Point, Issuer) và **Semantic Layer** (LegalConcept, LegalSubject, LegalAction, Obligation, Right, Condition, Exception).

### Rationale
Semantic Layer là phần tạo ra contribution thực sự — cho phép query "Những điều nào quy định về giải thể doanh nghiệp?" thay vì chỉ keyword search.

---

## ADR-14: Issuer Node + Hybrid Extraction

**Ngày**: 2026-07-03  
**Trạng thái**: FROZEN | **Rev.1**: 2026-07-06 (fix MERGE key bug)

### Decision
`Issuer` là node riêng. LLM chỉ extract `issuer_name` string. Writer tự MERGE, **dùng id (slug đã normalize) làm MERGE key**:
```python
# Writer — normalize trước khi MERGE
def get_issuer_id(issuer_name: str) -> str:
    import unicodedata, re
    normalized = unicodedata.normalize("NFC", issuer_name.strip()).lower()
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")

# Cypher
MERGE (i:Issuer {id: $issuer_id})
ON CREATE SET i.name = $issuer_name, i.branch = $branch
MERGE (doc)-[:ISSUED_BY]->(i)
```

### Rationale (Rev.1)
- **MERGE by `id` (slug), không by `name`**: `MERGE {name: ...}` là exact string match trong Cypher — `"Bộ Tư pháp"` ≠ `"Bộ Tư Pháp"` sẽ tạo 2 node riêng. Claim cũ *"Neo4j normalize tự động qua MERGE"* là **sai về mặt kỹ thuật**.
- **`branch` sourcing**: Ưu tiên cào từ metadata có cấu trúc trên vbpl.vn (issuer dropdown/mã cơ quan cố định). Fallback: `ISSUER_BRANCH_LOOKUP` cứng cho ~20 cơ quan phổ biến trong luật doanh nghiệp + fuzzy match + default `OTHER`.
- Zero thêm LLM complexity — giữ nguyên.

---

## ADR-15: Validator Tách Khỏi Ontology

**Ngày**: 2026-07-03  
**Trạng thái**: FROZEN

### Decision
`GUIDES_WHITELIST` chỉ sống trong Validator rule engine Python code, không phải property trong Neo4j node. Numeric `DOCUMENT_LEVELS`/precedence là legacy option và không dùng trong ontology v1.5.1.

### Rationale
Ontology mô hình hóa thực thể của thế giới pháp lý, không phải logic kiểm tra. `level=3` trên Issuer node là implementation artifact, không phải ontology concept.

---

## ADR-16: Extraction Schema ≠ Ontology

**Ngày**: 2026-07-03  
**Trạng thái**: FROZEN

### Decision
LLM extract 3 type đơn giản: `Entity | Concept | Action`. Writer map sang Ontology nodes phức tạp hơn: `LegalSubject | LegalConcept | LegalAction`.

### Rationale
Prompt đơn giản → LLM output ổn định hơn. Writer là nơi normalize, không phải LLM.

---

## ADR-17: Relation Naming — Active Voice

**Ngày**: 2026-07-03  
**Trạng thái**: FROZEN

### Decision
Đổi sang active voice: `AMENDS`, `REPEALS`, `REPLACES`, `GUIDES`, `REFERS_TO`.

### Old → New Mapping
| Cũ | Mới |
|---|---|
| `AMENDED_BY` | `AMENDS` |
| `REPLACED_BY` | `REPLACES` |
| `REPEALED_BY` | `REPEALS` |
| `IMPLEMENTED_BY` | `GUIDES` |

### Rationale
`(A)-[:AMENDS]->(B)` đọc tự nhiên: "A amends B" — A là văn bản mới hơn. Direction của relation có semantic rõ ràng.


---

## ADR-18: Temporal Modeling — Hybrid Denormalization & Future Snapshot

**Ngày**: 2026-07-07  
**Trạng thái**: FROZEN

### Decision
1. **Denormalization**: Gắn `effective_from`, `effective_to`, `legal_status` trực tiếp lên `Article` và `Clause` nodes (không chỉ ở Document). Neo4j Writer sẽ tự tính toán (cascade) các property này khi insert các relation `AMENDS`, `REPEALS`.
2. **Future Extension**: Định hướng tương lai cho large-scale deployment là sử dụng Snapshot Builder (FRBR-style) làm cache view phục vụ retrieval siêu tốc mà không phá vỡ Raw Graph (Source of truth). Không thêm `Snapshot` vào ontology v1.5.1; Snapshot Builder là future architecture, không thuộc ontology hiện tại.

### Rationale
- **Với đồ án hiện tại**: Sử dụng Denormalized Graph làm Source of Truth cân bằng giữa độ phức tạp và giá trị nghiên cứu. Tránh việc kéo dài thêm thời gian với một khối lượng code khổng lồ của Snapshot Builder (RC6).
- **Với kiến trúc tương lai**: `Snapshot` layer có thể được thiết kế như projection/cache riêng, đảm bảo Hybrid Retriever có thể kết hợp Raw Graph (cho reasoning) và Snapshot (cho querying) sau này mà không làm sai ontology v1.5.1.

---

## ADR-19: Knowledge Representation Strategy

**Ngày**: 2026-07-07  
**Trạng thái**: FROZEN

### Decision
Only stable legal facts are persisted inside the Knowledge Graph. Context-dependent reasoning is delegated to runtime LLM reasoning.

### Knowledge Classification

Quyết định những gì được lưu vào Graph (Layer 1) và những gì được suy luận tại Runtime (Layer 3):

| Knowledge             | Store in Graph? | Reason            |
| --------------------- | --------------- | ----------------- |
| Document hierarchy    | ✅               | Stable            |
| Citation              | ✅               | Stable            |
| Amendment             | ✅               | Stable            |
| Legal concept         | ✅               | Stable            |
| Legal entity          | ✅               | Stable            |
| Obligation            | ❌               | Context dependent |
| Exception             | ❌               | Context dependent |
| Comparative reasoning | ❌               | Generated         |
| Multi-hop reasoning   | ❌               | Generated         |
| Interpretation        | ❌               | Generated         |

### Alternatives Considered

**Option A: Everything inside Graph (LKIF-style, Akoma Ntoso)**
- *Pros*: Hoàn toàn deterministic, queryable trực tiếp bằng Cypher, explainability tuyệt đối.
- *Cons*: Dẫn đến "Ontology Explosion" (tạo ra hàng ngàn relation như `OBLIGES_IF`, `PERMITS_UNLESS`). Cực kỳ khó parse bằng NLP/LLM hiện tại, không thể maintain và mở rộng sang domain khác.

**Option B: Everything delegated to LLM (Pure RAG)**
- *Pros*: Cực kỳ linh hoạt, dễ mở rộng domain, không cần thiết kế ontology.
- *Cons*: LLM phải tự đọc và tổng hợp lại toàn bộ cấu trúc văn bản, dẫn đến Hallucination cao, không deterministic, phụ thuộc hoàn toàn vào context window.

**Option C: Hybrid (Chosen)**
- Kết hợp cả hai để tận dụng điểm mạnh của Graph (độ chính xác, cấu trúc) và LLM (suy luận logic, xử lý ngoại lệ).

### Rationale
Việc tách bạch rõ ràng giữa **Stable Knowledge** (Lưu trữ) và **Runtime Reasoning** (Suy luận động) giúp luận văn có một kiến trúc phân tầng vững chắc. Sự phân tách này tránh bùng nổ schema trong khi vẫn duy trì được khả năng giải thích (explainability) thông qua bằng chứng từ Graph.

---

## ADR-20: Embedding Model and Schema Dimension

**Ngày**: 2026-07-10
**Trạng thái**: FROZEN

### Decision

Chọn embedding contract hiện hành:

```text
Primary model: BAAI/bge-m3
Primary provider: FlagEmbedding
EMBEDDING_DIM: 1024
normalize_embeddings: true
```

Giữ baseline để ablation:

```text
Baseline model: bkai-foundation-models/vietnamese-bi-encoder
Baseline provider: sentence-transformers
Baseline dimension: 768
```

`EMBEDDING_MODEL`, `EMBEDDING_PROVIDER`, và `EMBEDDING_DIM` là cấu hình runtime,
nhưng Neo4j vector index vẫn là schema-bound. Contract hiện hành dùng BGE-M3/1024;
chuyển sang model có dimension khác bắt buộc phải cập nhật ontology, schema bootstrap,
recreate vector indexes, và re-embed toàn bộ Article/Clause.

### Rationale

Smoke test trên query pháp luật doanh nghiệp cho thấy BGE-M3 trả kết quả phù hợp
hơn BKAI Vietnamese bi-encoder. BGE-M3 được chọn làm primary cho Milestone A;
BKAI được giữ làm baseline để báo cáo trade-off và ablation thay vì fallback ngầm.

Model-configurable không có nghĩa Neo4j index tự thay đổi dimension. Một database
chỉ được chứa embeddings phù hợp với dimension đã cấu hình cho vector indexes hiện
hành.

### Migration

1. Bump ontology contract lên v1.5.0.
2. Đổi `article_embedding` và `clause_embedding` từ 768 sang 1024 dimensions.
3. Đổi pipeline default model/provider/dimension sang BGE-M3/FlagEmbedding/1024.
4. Drop và recreate hai vector indexes trên database đã dùng schema cũ.
5. Re-embed toàn bộ Article/Clause; không tái sử dụng vector 768 cũ.
6. Thêm contract test giữa settings, model output dimension và schema bootstrap.

### Consequences

- Tốn memory và thời gian embedding nhiều hơn BKAI/768.
- Cần `torch` và `FlagEmbedding` cho primary provider.
- BKAI/768 chỉ chạy khi được chọn rõ cho baseline và dùng schema/index tương ứng.
- M3 không được nghiệm thu nếu code/config/schema còn lệch dimension.

---

## ADR-21: `REFERS_TO` Provenance and Citation Identity

**Ngày**: 2026-07-12
**Trạng thái**: FROZEN

### Decision

`REFERS_TO` tuân theo provenance contract chung của semantic relations và bắt buộc có:

```text
confidence
llm_model
created_at
citation_text
citation_type
```

Nguồn của provenance là checkpoint đã tạo candidate relation:

```text
confidence  = raw extracted relation confidence
llm_model   = <checkpoint.provider>:<checkpoint.resolved_model>
created_at  = checkpoint.completed_at normalized to UTC
```

Normalizer không được thay bằng model đang cấu hình, `datetime.now()`, hoặc confidence mặc định.
Thiếu bất kỳ provenance bắt buộc nào là hard failure. `created_at` là thời điểm hoàn tất extraction,
không phải thời điểm pháp lý có hiệu lực (`effective_from`).

Mỗi citation khác nhau giữa cùng hai endpoint được giữ thành relation riêng. Stable discriminator là:

```text
citation_type + "|" + normalize_citation_text(citation_text)
```

`normalize_citation_text` dùng Unicode NFC, trim và collapse whitespace, nhưng giữ nguyên nội dung tiếng Việt.
`confidence`, `llm_model`, và `created_at` không tham gia `relation_id`. Hai citation giống nhau sau normalization
được merge deterministic.

### Migration

1. Bump ontology contract lên v1.5.1.
2. Mở rộng executable shared relation contract và write-time validation.
3. Archive decision artifacts v1.5.0 với trạng thái `superseded`.
4. Regenerate decision artifacts từ Article checkpoints; không gọi provider.
5. Chạy normalization hai lần và so sánh decision, entity-index, relation-ID và payload projection digests.
6. Chạy lại Gate 2 và Gate 3 trước khi mở Gate 4.

### Consequences

- Artifacts Gate 2/Gate 3 v1.5.0 chỉ còn là historical baseline.
- Checkpoint thiếu provider, resolved model hoặc completed timestamp không thể tái sử dụng.
- Cùng endpoint pair có thể có nhiều `REFERS_TO`, nhưng chỉ khi citation discriminator khác nhau.
- Gate 4 vẫn bị block cho đến khi artifacts v1.5.1 được regenerate và validate thành công.

---

## ADR-22: Resolver-First Legal References and Method-Aware Provenance

**Ngày**: 2026-07-18
**Trạng thái**: ACCEPTED

### Decision

Relative structural references are resolved before LLM extraction. The parser owns source hierarchy and source
coordinates; the resolver owns canonical endpoint identity; the LLM handles only semantic or ambiguous references;
validators retain final authority over graph persistence.

The graph keeps one semantic relation, `REFERS_TO`. Discovery method is represented by `extraction_method`:
`RULE`, `ENTITY_LINKING`, or `LLM`. `HYBRID` is not introduced because no canonical flow materializes it.
Multi-target mentions share a deterministic `reference_bundle_id` and are accepted atomically.

Source coordinates are zero-based, start-inclusive, end-exclusive offsets over Unicode-NFC `source.txt` with LF
newlines. Rule-resolved relations use resolver checkpoint provenance and never receive fabricated LLM metadata.

Appendix content is preserved as `UnparsedSection` with source provenance but is not persisted to the graph in this
ontology version.

### Consequences

- Deterministic references no longer depend on LLM output.
- Existing v1.5.1 decision artifacts are historical and require offline normalization.
- Parallel citations remain separate graph relationships, while retrieval collapses them for topology/path ranking.
- Appendix retrieval and reasoning require a separate ontology migration.
