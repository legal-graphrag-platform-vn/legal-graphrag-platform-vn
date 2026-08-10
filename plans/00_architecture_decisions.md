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

---

## ADR-23: `Section` Hierarchy and Local Chapter/Section References

**Ngày**: 2026-07-31
**Trạng thái**: ACCEPTED

### Decision

Ontology v1.7.0 persists `Section` (`Mục`) as a structural node with required
`id`, `number`, and legal `title`:

```text
Document -> Chapter -> Section -> Article -> Clause -> Point
```

The canonical Section ID is
`{document_id}_ch{normalized_chapter}_sec{normalized_section}`. A Section is
created only from a structural heading in canonical source, never from a
citation. Its title is mandatory; failure to recover the legal title is a
parser/data-quality failure, not permission to invent `"Mục N"` as title.

The corpus probe found 80 `Mục` headings across 19 raw documents, all 80 under
an active `Chương`, and all 80 with a recoverable title. Therefore v1.7.0
supports `Chapter -> Section -> Article` only. This is a verified corpus
contract, not a universal statement about every Vietnamese legal document.

`REFERS_TO` retains its canonical relation name and direction. Its target set
is extended to `Chapter` and `Section`; sources remain `Article`, `Clause`, and
`Point`. Deterministic grammar resolves local `Chương này`, `Chương V của Luật
này`, `Mục 1 Chương III`, and `Mục 1 của Chương III`. External Chapter/Section
mentions are parsed before local patterns but remain unresolved checkpoints in
this migration; they do not fall back to the current document and do not create
fake nodes or edges.

The old direct `Document -> Article` and `Chapter -> Article` pairs remain
valid for structures without Section. Reparsed Articles inside a Section use
`Section -> Article`. Cleanup of an old `Chapter -> Article` edge is guarded:
the writer verifies the exact `Chapter -> Section -> Article` chain first and
preserves the legacy edge if verification fails.

Named traversal bounds are shared by repositories:

```text
MAX_DOCUMENT_TO_ARTICLE_DEPTH = 3
MAX_DOCUMENT_TO_CITABLE_UNIT_DEPTH = 4
MAX_DOCUMENT_HIERARCHY_DEPTH = 5
```

Every query must still check labels/path semantics; depth alone does not define
a valid hierarchy.

### Consequences

- Existing canonical raw sources containing `Mục` must be reparsed; changing
  only schema and resolver code does not migrate old hierarchy artifacts.
- `Section` has no temporal fields, embedding, full-text index, or vector index.
- The browser/API returns both direct Chapter Articles and nested Sections.
- External Chapter/Section materialization and compound-list expansion were
  deferred by this ADR pending corpus-wide unique endpoint verification.
  ADR-24 now defines the accepted external-materialization contract; compound
  grammar expansion remains a separate implementation scope.

---

## ADR-24: Corpus-Wide External Structural Reference Materialization

**Ngày**: 2026-07-31
**Trạng thái**: IMPLEMENTED; live Neo4j integration verification pending
**Amendment**: 2026-07-31 — registry/build identity, reconciliation, and
cross-store durability contract hardened before implementation

### Context

An external structural reference targets a canonical structural unit owned by a
different `Document` in the same accepted corpus. It does not target an external
system and does not introduce an `ExternalNode`, `RegistryNode`, or a new
relationship type.

ADR-23 deliberately left external Chapter/Section materialization deferred.
This decision defines the corpus-wide identity, resolution, validation, and
write contract required to materialize external targets safely. It does not
change the Section hierarchy or local-reference decisions of ADR-23.
The implementation sequence and acceptance matrix are defined in
`agent-plan-feats/17_external_structural_reference_materialization_plan.md`.

### Decision

#### Registry content and build evidence

The structural registry is built only from hierarchy units that have passed:

```text
canonical source
-> hierarchy parse
-> schema and ontology validation
-> accepted structural units
-> immutable registry content
-> immutable build receipt
```

Identity and provenance use three separate values:

```text
build_id         human-readable identifier for one registry build receipt
snapshot_hash    content address of canonical accepted registry content
provenance_hash  digest of stable source, projection, parser, and validator evidence
```

`snapshot_hash` covers the registry/ontology/canonicalization contract,
canonical Documents, descendant structural units, and canonical
parent/ownership structure. `provenance_hash` covers stable canonical-source and
validated-structural-projection digests plus parser/hierarchy/validator contract
versions and the resulting `snapshot_hash`. Neither hash includes `build_id`,
`created_at`, filesystem paths, symlink targets, or operational artifact UUIDs.

Two builds may have different `build_id` values while sharing the same content
and provenance hashes. A source or parser change that preserves the accepted
hierarchy may preserve `snapshot_hash` while changing `provenance_hash`. Existing
content and build receipts are never mutated in place.

Document representation is disjoint:

```text
RegistryEndpoint = RegistryDocument | RegistryUnit
RegistryDocument = document identity and canonical Document endpoint
RegistryUnit     = Part | Chapter | Section | Subsection | Article | Clause | Point only
```

`documents.jsonl` stores `RegistryDocument`; `units.jsonl` stores descendants.
The structural-key index never contains Document. Therefore there is one source
of truth for a Document endpoint.

The registry must not treat any of the following as existence evidence:

- a corpus manifest, crawler metadata, or `raw_doc_code`;
- a canonical-looking ID derived from citation text;
- a parser candidate that has not passed validation and acceptance;
- a node that is not owned by an accepted canonical `CONTAINS` hierarchy.

Canonical IDs remain deterministic and are created through shared helpers. A
structural unit is registered only after acceptance; generating a canonical ID
does not prove that the node or target exists.

Document aliases retain all candidates. Valid local hierarchy rejects duplicate
structural keys instead of overwriting one candidate. Resolution uses exact
normalized identities and the following cardinality contract:

```text
0 candidates  -> UNRESOLVED
1 candidate   -> RESOLVED
>1 candidates -> AMBIGUOUS
```

Both source and target endpoints, including their unique Document ownership,
must exist in the same verified `snapshot_hash`. Source evidence from one
content snapshot cannot be combined with target evidence from another even when
their inferred IDs match.

#### Resolution and materialization state

Resolution state and materialization state are independent. Resolution state is:

```text
resolution_status = UNRESOLVED | RESOLVED | AMBIGUOUS
reference_scope   = LOCAL | EXTERNAL | UNKNOWN
is_self_reference = boolean derived by the resolver
```

`is_self_reference=true` if and only if resolution is `RESOLVED`, scope is
`LOCAL`, exactly one target exists, and that target ID equals the source ID.
`SELF_REFERENCE` is not a resolution status. A local reference to a different
endpoint remains `RESOLVED + LOCAL + false`.

Materialization state is:

```text
NOT_APPLICABLE | PENDING | WRITTEN | FAILED | BLOCKED
```

Each reference checkpoint stores at least resolution/materialization state,
reason codes, `build_id`, `snapshot_hash`, and `provenance_hash`. A
registry-resolved target missing from Neo4j stays `RESOLVED` and becomes
`FAILED/target_endpoint_missing_in_graph`; it does not revert to `UNRESOLVED`.

When a newer build changes the resolved target set:

```text
old target was never durably or graph-observably written
-> audit the old resolution
-> replace pending targets
-> allow materialization

old target was ever WRITTEN or still exists for the bundle in Neo4j
-> BLOCKED/resolved_target_changed_after_materialization
-> create no new edge
-> delete no old edge
```

The decision inspects durable attempt history and Neo4j state. Current
checkpoint status alone is not evidence that a target was never written.

#### Neo4j verification and relation-only write

Before materializing `REFERS_TO`, one Neo4j transaction must:

- `MATCH` exact source and target IDs with allowlisted labels;
- require source type `Article|Clause|Point`;
- require target type
  `Document|Part|Chapter|Section|Subsection|Article|Clause|Point`;
- verify source and target ownership against registry-proven Document IDs;
- require source and target Documents to differ;
- verify every member of the atomic bundle before any relation merge;
- inspect existing `REFERS_TO` targets for the same source and
  `reference_bundle_id` before writing.

Document ownership is verified through canonical hierarchy rather than a
denormalized `document_id` property:

```text
(sourceDocument)-[:CONTAINS*1..7]->(source)
target type Document: targetDocument = target
other target types:   (targetDocument)-[:CONTAINS*1..7]->(target)
```

The query must measure ownership-path count and distinct Document owners before
deduplication:

```text
one owner, one path       -> canonical
one owner, multiple paths -> continue with divergence warning/count
multiple owners           -> hard-fail
```

`WITH DISTINCT` must not hide ownership divergence.

For one atomic bundle, the transaction compares existing graph targets with the
complete expected target set:

```text
existing set is empty         -> first write may proceed
existing set equals expected  -> idempotent retry may proceed
existing set is non-empty and unequal, including a proper subset
-> rollback before MERGE
```

The writer must never `MERGE` source or target. Only validated relations may be
merged after all checks:

```text
MATCH verified source
MATCH verified target
MERGE (source)-[:REFERS_TO {relation_id: $relation_id}]->(target)
```

The application consumes the transaction result and requires the exact expected
endpoint, target, and relation-ID sets. Zero rows, unexpected multiplicity,
wrong labels/owners, partial bundles, or conflicting old targets are typed
failures and commit no new bundle edge.

#### Cross-store durability and concurrency

The checkpoint store and Neo4j are separate systems, so this decision does not
claim a distributed atomic transaction. Materialization remains at-least-once
and idempotent through deterministic `relation_id`, atomic bundles, and exact
target-set comparison.

Every cooperating reconciliation process uses a per-source-document advisory
lock plus checkpoint compare-and-swap by canonical checkpoint-file hash. The
append-only materialization-attempt ledger and checkpoint CAS execute under the
same lock.

After Neo4j returns a successful commit, persistence order is mandatory:

```text
Neo4j transaction commits
-> append one schema-valid, hashed attempt row
-> flush and fsync attempt ledger
-> CAS checkpoint using the expected checkpoint hash
-> fsync checkpoint replacement and parent directory
```

The attempt record includes the bundle/build/hash evidence, expected and
observed target sets, relation IDs, expected checkpoint hash, timestamps, typed
outcome, and record hash. A truncated or hash-invalid row never proves a
successful write.

Failure rules are fail-closed:

- graph commit plus ledger/fsync failure never advances the checkpoint;
- durable ledger plus checkpoint-CAS failure preserves graph and ledger and
  never overwrites newer checkpoint state;
- uncertain Neo4j commit records `UNKNOWN` when possible and never becomes
  `WRITTEN` until a fresh transaction verifies graph state;
- retry inspects both durable attempts and current bundle targets in Neo4j.

Existing method-aware `REFERS_TO` provenance and atomic bundle validation remain
mandatory. `build_id`, `snapshot_hash`, and `provenance_hash` remain
checkpoint/attempt evidence linked through `reference_bundle_id`; making them
required relationship properties would require a later ontology ADR/version
bump.

### Consequences

- The corpus manifest remains discovery/orchestration input, not structural
  existence evidence.
- A corpus-wide content snapshot and immutable build receipt must be published
  after accepted structural ingestion and before external reconciliation.
- Ingesting a new target Document can trigger retry only for checkpoints keyed
  by its normalized document identity; a full corpus re-resolution is not
  required.
- Registry/graph divergence, ownership-path divergence, blocked target changes,
  uncertain commits, and stale checkpoint updates are observable through typed
  state/reason codes instead of being collapsed into `UNRESOLVED`.
- A successful graph commit is not reflected as `WRITTEN` until its attempt row
  is durable and checkpoint CAS succeeds.
- Automatic replacement or deletion of a previously materialized target is
  outside this ADR; it requires explicit reconciliation policy and audit.
- No ontology node or relationship type is added; verified external references
  remain canonical `source -[:REFERS_TO]-> target` edges.
- This ADR defines the external materialization contract. Compound-list grammar
  expansion remains a separate implementation scope, while any resulting
  multi-target bundle must continue to materialize atomically.

---

## ADR-25: Canonical `Part` and `Subsection` Hierarchy

**Status:** Accepted

**Date:** 2026-08-01

**Ontology version:** 1.8.0

### Context

The v1.7 hierarchy represented `Document`, `Chapter`, `Section`, `Article`,
`Clause`, and `Point`, but could not preserve the legal headings `Phần` and
`Tiểu mục`. Flattening those headings loses exact ownership, prevents verified
references to those units, and makes the document browser disagree with source
structure.

Article 62 of Decree 34/2016/ND-CP is historical evidence for six explicitly
listed layouts. Article 63 of Decree 78/2025/ND-CP is the current composition
rule and permits a Chapter to omit a Section. Together they require seven
canonical parent chains to Article, including
`Document -> Part -> Chapter -> Article`.

### Decision

Add persisted structural labels:

```text
Part        required: id, number, title
Subsection  required: id, number, title
```

The exact structural `CONTAINS` pairs are:

```text
Document   -> Part | Chapter | Article
Part       -> Chapter
Chapter    -> Section | Article
Section    -> Subsection | Article
Subsection -> Article
Article    -> Clause
Clause     -> Point
```

Every descendant has exactly one direct canonical parent. Each concrete
Document, Chapter, and Section uses one child mode and does not mix the
alternatives shown above. `Document -> Article` remains valid.

Canonical IDs are deterministic. Adding Part ownership does not rename an
existing Chapter or Article:

```text
Part        {document_id}_part{normalized_part}
Subsection  {document_id}_ch{chapter}_sec{section}_subsec{subsection}
```

`REFERS_TO` retains its existing direction and relation type. Its target
allowlist expands to `Part` and `Subsection`; these targets are materialized
only when the immutable corpus registry and Neo4j endpoint checks both verify
them. Registry content uses `corpus-structural-registry-v2`; v1 snapshots remain
read-only legacy snapshots.

Ownership queries use shared semantic bounds: Article depth 5, retrieval-unit
depth 6, and deepest citable/hierarchy depth 7. Depth alone is not structural
evidence; validators enforce exact parent-label pairs.

Migration reparses canonical source and writes the accepted hierarchy first.
Only after the replacement chain exists may reconciliation remove legacy
shortcuts:

```text
Document -> Chapter  after Document -> Part -> Chapter
Section  -> Article  after Section -> Subsection -> Article
```

`Chapter -> Article` is preserved for the valid
`Document -> Part -> Chapter -> Article` and `Document -> Chapter -> Article`
paths.

### Consequences

- Parser, payload, validator, schema, registry, reference resolver/writer,
  retrieval ownership, API, and UI share one v1.8 hierarchy contract.
- `Part`, `Chapter`, `Section`, and `Subsection` remain non-embedded,
  non-temporal grouping nodes.
- A recognized Part or Subsection without an accepted legal title is a parser
  failure; display fallback text is never persisted as the title.
- Citation text cannot create a structural node. Missing or ambiguous targets
  remain unresolved checkpoints.
- Existing documents without Part/Subsection continue to use their canonical
  direct paths without fake grouping nodes.

---

## ADR-26: Bind target độc lập cho query plan multi-hop chính xác

**Ngày**: 2026-07-22
**Trạng thái**: ACCEPTED

### Bối cảnh

Preflight query-graph ở Task 0 chứng minh rằng cấu trúc plan ban đầu
`anchor + các bước relation/direction/label có thứ tự` không thể xác định duy
nhất target cho ba query đã được review. Với `multi_hop_01`, `multi_hop_03` và
`multi_hop_04`, cấu trúc
`Clause -> REFERS_TO -> Article -> CONTAINS -> Clause` trả về mọi Clause trong
Article được viện dẫn. Gold path có tồn tại, nhưng chỉ các constraint về
relation và label thì chưa thể biểu diễn Clause nào trả lời query.

Nếu cho phép answer model chọn target sau execution, một plan mơ hồ có thể bị
coi là đã thỏa mãn, đồng thời vi phạm boundary về exact-path membership.

### Quyết định

Một query plan exact-linear V1 phải chứa cả:

1. `AnchorMention`, xác định điểm bắt đầu traversal; và
2. `TargetMention` bắt buộc, mô tả legal unit hoặc semantic endpoint mà query
   cần đi tới.

Planner chỉ sinh mention text và label thuộc allowlist; không bao giờ sinh
canonical ID hoặc Cypher. Binding thuộc retrieval sẽ resolve anchor và target
độc lập. Structural mention dùng controlled hierarchy lookup; semantic mention
dùng full-text/vector retrieval đã calibration và bị giới hạn bởi corpus,
target label cùng temporal filter.

Chỉ tạo `BoundSemanticPlan` khi cả hai endpoint đều resolve duy nhất. Exact
executor sau đó truyền bound anchor ID và bound target ID dưới dạng parameter
vào static template depth 2 hoặc 3, rồi revalidate mọi topology trả về. Nếu có
nhiều exact topology thì trả `AMBIGUOUS_PATH`; nếu không có kết quả thì trả
`NO_PATH`.

Không bao giờ được dùng việc path có tồn tại làm evidence rằng một anchor hoặc
target candidate đúng về semantic. Binding accuracy và path execution accuracy
phải được đo riêng.

### Các phương án đã cân nhắc

**Chỉ dùng các bước relation/direction/label**

- Loại vì Task 0 trả ba target Clause ở ba trong bốn linear case đã review.

**Để answer generation chọn trong mọi Clause có thể đi tới**

- Loại vì generation sẽ quyết định retrieval có đủ hay không, qua đó bypass cơ
  chế exact-path membership theo nguyên tắc fail-closed.

**Thêm target predicate tùy ý hoặc Cypher do LLM sinh**

- Loại khỏi V1 vì làm rộng executable surface, làm yếu query parameterization và
  khiến validation khó hơn đáng kể.

**Thu hẹp V1 chỉ còn `multi_hop_02`**

- Không chọn làm hướng chính vì phương án này né tránh thay vì giải quyết khoảng
  trống về target denotation đã được review. Đây vẫn là fallback nếu target
  binding không đạt các calibration threshold đã preregister.

### Hệ quả

- `UnlinkedSemanticPlan` bổ sung `TargetMention` bắt buộc nhưng vẫn không chứa
  graph ID.
- `BoundSemanticPlan` mang đúng một anchor và một target đã resolve duy nhất;
  candidate list chỉ là diagnostic của linker, không phải trusted plan.
- Runtime reason code bổ sung `UNBOUND_TARGET` và `AMBIGUOUS_TARGET`.

### Xác nhận

Quyết định được chấp nhận ngày 2026-07-23 sau khi resolver v2.0.1 và graph
ontology v1.6.0 được rebuild. Task 0 rerun xác nhận ba exact-linear case còn
thuộc V1 đều có đúng một topology khi bind độc lập anchor và target. Case
`multi_hop_03` nay là direct `Clause -> REFERS_TO -> Clause`, nên được giữ trong
evaluation dataset nhưng không còn được dùng làm bằng chứng cho plan 2 bước.
- QG-0 dùng gold endpoint được bind thủ công để cô lập correctness của executor.
- QG-1 báo cáo anchor binding, target binding và exact-path denotation thành các
  metric riêng.
- V1 vẫn không bao gồm branching, join, target predicate, legal entailment và
  automatic constraint relaxation.

---

## ADR-27: Query Processing và phạm vi Multi-Hop Execution

**Ngày**: 2026-08-08
**Trạng thái**: ACCEPTED

### Bối cảnh

`QueryProcessor` (five-field contract, chạy bằng Gemini, provider-swappable qua
`build_text_generator`) từng thay resolver+rewriter deterministic ở Stage 1.
Cách ghép này tạo hai pipeline cạnh tranh quyền xác định nghĩa của câu hỏi và
cho phép feature flag bỏ qua canonical reference resolution.

Thứ tự chuẩn là:

```text
Current query + server-owned HistoryContext
→ deterministic canonical reference resolution
→ clarification hoặc canonical standalone query
→ optional QueryProcessor decomposition
```

Query Processor không nhận raw conversation history và không có quyền tạo hay
thay canonical ID. Output decomposition của nó vẫn dùng five-field contract:

```text
status                ready | needs_clarification
standalone_query      câu hỏi đã self-contained (khi ready)
plan_type             single | parallel | comparison | multi_hop
subqueries[]          mỗi item: { id, query, intent, depends_on }
clarification_question câu hỏi làm rõ (khi needs_clarification)
```

Sau khi sửa bug fan-out tuần tự (subqueries self-contained nay chạy đồng thời
bằng `asyncio.gather`), vấn đề mở còn lại là: **`depends_on` có nghĩa gì ở
runtime?** Câu test duy nhất quyết định phạm vi: *sau khi q1 chạy xong, request
của q2 có thay đổi dựa trên output của q1 không?* Không → concurrent là đủ. Có →
mới là data dependency thật.

Từ "multi-hop" bị dùng lẫn cho bốn khái niệm khác nhau:

| Khái niệm | Ý nghĩa | Output hop trước → input hop sau? |
|---|---|---|
| Graph multi-hop | 1 retrieval đi qua nhiều relationship trong Neo4j (REFERS_TO → CONTAINS) | Không bắt buộc — thuộc tầng GraphRAG |
| Multi-query decomposition | Tách 1 câu hỏi thành nhiều subquery độc lập | Không |
| Logical dependency | q2 "đi sau" q1 về reasoning nhưng vẫn self-contained | Không |
| True multi-hop execution | q2 cần dữ liệu cụ thể sinh từ q1 (article_id, clause_id, unit_id, graph anchor) | **Có** |

### Quyết định (MVP scope)

1. Canonical `ReferenceResolver` và `StandaloneQueryRewriter` luôn chạy trước;
   ambiguity ở tầng này phải clarification và không gọi Query Processor.
2. Query Processor chỉ decomposition canonical standalone query, không sở hữu
   conversation reference resolution và không nhận raw history.
3. Document filters đã resolve phải được giữ nguyên cho mọi subquery và trạng
   thái resolution ban đầu phải được persist cùng answer.
   Trường `standalone_query` dư thừa trong output processor không được thay
   canonical query; mọi subquery của resolved reference phải giữ đủ canonical
   anchors, nếu không fail closed trước retrieval.
4. Giữ **multi-query decomposition + graph multi-hop retrieval**; **chưa** làm
   cross-subquery output binding.
5. Mọi subquery phải **self-contained** theo generation/SFT contract, chạy
   **concurrently** dưới giới hạn concurrency của application retrieval runner,
   rồi `merge_contexts` trước khi generate.
6. `depends_on` được **preserve + validate** như *logical/reasoning metadata*.
   Nó **không điều khiển scheduling** trong MVP — bắt q2 chờ q1 khi q2 không nhận
   dữ liệu từ q1 chỉ tăng latency mà không tăng độ chính xác.
7. `plan_type=multi_hop` ở tầng Query Processing chỉ biểu diễn
   decomposition/reasoning plan, **chưa** đồng nghĩa với true hop-to-hop
   execution.
8. `QueryProcessor` là adapter provider-swappable: bản hiện tại dùng Gemini;
   Qwen/Ollama là dự phòng cho tương lai, không hardcode.

### Vì sao chỉ có `depends_on` là chưa đủ cho true multi-hop

`depends_on=["q1"]` mới nói "q2 phụ thuộc q1", nhưng runtime chưa biết: lấy dữ
liệu gì từ q1 (document/article/clause/unit id, entity, graph path?), dùng như
thế nào (hard filter, query hint, graph seed, temporal target, rewrite?), chọn
candidate nào khi q1 trả nhiều, và xử lý ra sao khi q1 rỗng/ambiguous. Contract
true multi-hop tương lai phải thêm **binding semantics** (ví dụ
`bindings: [{ from: "q1", select: "article_ids", use_as: "anchor_unit_ids" }]`).

### Điểm dừng đề xuất (ba mức)

- **Mức 0 — MVP hiện tại (baseline, ĐÃ XONG):** concurrent self-contained
  subqueries + merge; `depends_on` là metadata. Đúng và đủ về mặt kỹ thuật.
- **Mức 1 — Narrow true multi-hop demo (điểm dừng khuyến nghị nếu còn thời
  gian):** đúng **một** use case hai-hop, hard-code hình dạng — Hop 1 retrieval
  nội dung → lấy grounded `article_ids/clause_ids` → bind cứng một luật duy nhất
  (`article_ids → anchor_unit_ids`) → Hop 2 traverse `AMENDS/REPEALS/REPLACES`
  theo `query_date`. Policy ca biên chốt cứng: nhiều kết quả → top-k grounded;
  q1 rỗng/ambiguous → fail closed; temporal truyền y nguyên; depth ≤ 2, cấm hop
  3. Thể hiện rõ giá trị Graph + Temporal mà scope kiểm soát được.
- **Mức 2 — General `QueryPlanExecutor` (OUT OF SCOPE):** DAG tổng quát, typed
  anchor mọi node type, binding DSL, branching, provenance, error propagation,
  temporal policy cấu hình được. Ghi vào Future Work.

### Kiến trúc tương lai (nếu nhóm quyết định làm true multi-hop)

```text
QueryProcessor → QueryPlan (subqueries + dependencies + bindings)
   → QueryPlanExecutor:
        1. Validate dependency DAG
        2. Chạy root queries concurrently
        3. Materialize RetrievalContext từng subquery
        4. Extract typed anchors
        5. Bind outputs vào dependent queries
        6. Chạy next hops (giới hạn depth/branch/concurrency)
        7. Merge evidence + provenance
   → Answer Generator + Grounding
```

DTO output cho mỗi hop: `SubqueryExecutionResult { subquery_id,
retrieval_context, document_ids, article_ids, clause_ids, unit_ids, graph_paths,
temporal_context }`.

### Hệ quả

- Điểm cần thống nhất **không phải** "có field `depends_on` hay không", mà là
  runtime **có dùng output của dependency để đổi input của subquery phụ thuộc
  hay không**. Chưa có output binding → `depends_on` chỉ là logical metadata.
- MVP không phát sinh contract mới; true multi-hop cần một ADR/DTO riêng
  (`QueryPlan` + `bindings`) trước khi implement.
- ADR-26 (exact-linear plan với `AnchorMention` + `TargetMention`) là hướng
  tiếp cận cho Mức 1/2 khi làm true multi-hop, không áp dụng cho MVP fan-out.
- 7 câu hỏi cần cả nhóm chốt trước khi lên Mức 1/2: xem
  `Thao_luan_MultiHop_QueryProcessing_TemporalGraphRAG` (mục 12).

---

## ADR-28: Chapter cho phép direct preamble Article trước Section

**Ngày**: 2026-08-08
**Trạng thái**: ACCEPTED

### Bối cảnh

Một số văn bản có Điều mở đầu trực tiếp dưới Chương rồi mới chia thành các Mục.
Ví dụ Chương XXIII Bộ luật Hình sự 100/2015/QH13 chứa Điều 352 trực tiếp, sau đó
Mục 1 bắt đầu từ Điều 353 và Mục 2 bắt đầu từ Điều 360. Guard theo ADR-25 coi
mọi `Chapter -> Article` kết hợp `Chapter -> Section` là mixed mode không hợp lệ,
dù payload builder đã biểu diễn đúng hai loại cạnh cha-con này.

### Quyết định

Cho phép một Chapter có đồng thời direct Article và Section với điều kiện mọi
direct Article có canonical legal number đứng trước mọi Article nằm dưới các
Section của Chapter đó. Đây là preamble mode có điều kiện, không phải bỏ mixed
mode validation:

```text
max(direct Article numbers) < min(Section descendant Article numbers)
```

Parser model và whole-payload consistency validator phải cùng enforce rule bằng
natural legal-number ordering. Document vẫn không được mix Part, Chapter và
direct Article; Section vẫn không được mix Subsection và direct Article.

### Các phương án đã cân nhắc

**Bỏ hoàn toàn Chapter mixed-mode validation**

- Không chọn vì sẽ chấp nhận direct Article chen sau hoặc giữa các Section,
  làm mất invariant cấu trúc mà parser có thể kiểm tra chắc chắn.

**Giữ single-mode tuyệt đối theo ADR-25**

- Không chọn vì reject cấu trúc pháp lý có thật và ngăn parse corpus BLHS 2015.

### Hệ quả

- `Chapter -> Article` và `Chapter -> Section` có thể cùng tồn tại cho preamble.
- Payload builder không đổi: Article không có `section` vẫn gắn trực tiếp vào
  Chapter; Article có `section` vẫn gắn vào Section.
- Thiếu Article number hoặc direct Article không đứng trước Section Articles là
  validation failure trước write.
- Quyết định này thu hẹp và supersede phần cấm Chapter mixed mode trong ADR-25;
  các boundary Document và Section của ADR-25 vẫn giữ nguyên.

---

## ADR-29: Đồng bộ executable ontology contract và diagram provenance

**Ngày**: 2026-08-10
**Trạng thái**: ACCEPTED

### Bối cảnh

Các thay đổi đã merge vào executable contract mở rộng metadata node, đặt
`DIAGRAM` chung enum với `REFERS_TO`, mở `REGULATES -> Issuer`, và cho Point
mang temporal metadata tùy chọn. Canonical ontology chưa phê duyệt các endpoint
và provenance expansion đó; diagram runtime còn tự gắn validity trước validator.

### Quyết định

1. `plans/legal_ontology.md` tiếp tục là contract chuẩn tắc; module Python là
   executable mirror và phải dùng cùng version.
2. Bump ontology lên `1.9.0` vì đây là additive contract expansion, không chỉ
   sửa diễn đạt.
3. Đồng bộ optional metadata của Document, Article, Clause và Point theo
   executable contract. Point temporal fields chỉ là schema capability; parser
   và payload hiện tại vẫn kế thừa hiệu lực từ Clause.
4. Giữ `REGULATES` ở `LegalSubject|LegalAction`; `Issuer` bị loại vì prompt và
   evaluation chưa có semantic extraction contract tương ứng.
5. Tách `DIAGRAM` khỏi enum của `REFERS_TO`. Nó chỉ là deterministic source cho
   quan hệ Document-level
   `AMENDS`, `REPEALS`, `REPLACES`, `GUIDES` sau canonical registry resolution.
6. Diagram builder chỉ tạo validation-pending record. Orchestrator phải chạy
   schema, ontology và consistency validation trước decision gate. Temporal
   relation chỉ kế thừa `effective_from` khi acting head là current document;
   external head thiếu ngày phải vào blocking review.

### Hệ quả

- Artifact mang ontology version `1.8.x` không được tự nhận là tương thích với
  runtime `1.9.0`; phải re-normalize hoặc regenerate qua pipeline hiện hành.
- Diagram target unresolved tiếp tục đi review/fail closed, không tạo Document
  hoặc relation giả.
- `DIAGRAM` confidence không có quyền nới ontology validation.
- `DIAGRAM` không phải provenance hợp lệ của `REFERS_TO`.
- Test parity khóa version, Point capability, semantic endpoint và diagram gate.

---

## ADR-30: Statement-level grounding và deterministic answer rendering

**Ngày**: 2026-08-10
**Trạng thái**: ACCEPTED

### Bối cảnh

Contract `answer-generation-v1` dùng `claims[]` làm cả đơn vị grounding lẫn đơn
vị trình bày. Renderer nối từng claim với citation label nên câu trả lời đúng về
cấu trúc nhưng rời rạc, đồng thời backend làm mất reasoning paths và temporal
notes khi tạo snapshot/API response.

### Quyết định

1. Bump contract thành `answer-generation-v2`.
2. Paragraph là đơn vị trình bày; `GroundedStatement` là đơn vị grounding.
3. Mỗi statement pháp lý bắt buộc có allowlisted `citation_ids`. Path/temporal
   linkage là optional, nhưng nếu khai báo phải hard-validate ID và interval.
4. Model sinh `direct_answer`, `sections`, `caveats` và statements. Structural
   grounding không tuyên bố chứng minh semantic entailment; entailment thuộc eval.
5. Sau validation, chỉ `DeterministicAnswerRenderer` được chạm nội dung: join,
   heading, Markdown escaping và citation ordinal theo first occurrence. Không
   provider hay LLM nào được paraphrase hậu validation.
6. Persist immutable snapshot gồm Markdown, structured answer, citations,
   temporal notes và reasoning paths. Buffered SSE và history replay cùng đọc
   snapshot; không re-run renderer/generator.
7. Internal `insufficiency_reason` chỉ dùng logging/eval và snapshot diagnostics.
   Client chỉ nhận message do backend map deterministic.

### Hệ quả

- Citation trong prose dùng `[1]`, `[2]`; cùng citation ID giữ nguyên ordinal
  trên toàn answer và source card dùng cùng ordinal.
- Backend phát `explanation` SSE event riêng; frontend đặt XAI trong khối mở rộng,
  không nhét graph path kỹ thuật vào prose chính.
- Artifact answer-generation-v1 đã sinh trước quyết định này là historical và
  phải regenerate trước khi dùng làm evidence cho contract v2.
- Hard grounding gate giữ deterministic; semantic support, completeness,
  naturalness và exception coverage được đánh giá ở quality/eval layer riêng.
