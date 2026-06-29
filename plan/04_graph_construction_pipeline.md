# Graph Construction Pipeline — Chi Tiết Kỹ Thuật

> **Phiên bản**: 0.1  
> **Liên quan đến**: RC2

---

## Tổng Quan Pipeline

```
Raw PDF
    │
    ▼
[Step 1] Hierarchy Parser
    │   Input : PDF binary
    │   Output: Structured document tree (JSON)
    │
    ▼
[Step 2] LLM Information Extraction
    │   Input : Text chunks (Article/Clause level)
    │   Output: Entities + Relations (JSON)
    │
    ▼
[Step 3] JSON Schema Validation
    │   Input : LLM JSON output
    │   Output: Validated JSON | ValidationError
    │
    ▼
[Step 4] Ontology Validation
    │   Input : Validated JSON
    │   Output: Ontology-compliant triples | OntologyError
    │
    ▼
[Step 5] Confidence Scoring
    │   Input : LLM outputs (N=3 runs)
    │   Output: confidence score ∈ [0, 1]
    │
    ▼
[Decision Gate]
    ├── confidence ≥ 0.7 → Auto-accept → Neo4j Writer
    ├── 0.3 ≤ confidence < 0.7 → Human Review Queue
    └── confidence < 0.3 → Rejection Log
```

---

## Step 1: Hierarchy Parser

### Cấu Trúc Văn Bản Pháp Luật VN

```
Document
├── Phần (Part)          [optional]
│   └── Chương (Chapter)
│       └── Mục (Section) [optional]
│           └── Điều (Article)
│               └── Khoản (Clause)
│                   └── Điểm (Point)
│                       └── [text content]
```

### Pattern Nhận Dạng

```python
PATTERNS = {
    "article": r"^Điều\s+(\d+)\.\s*(.+)",
    # "Điều 17. Điều kiện thành lập..."
    
    "clause": r"^(\d+)\.\s+",
    # "1. Doanh nghiệp được thành lập..."
    
    "point": r"^([a-zđ])\)\s+",
    # "a) Có vốn điều lệ..."
    
    "chapter": r"^Chương\s+([IVXLCDM]+)\s*$",
    # "Chương II"
    
    "chapter_title": r"^([A-ZĐÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸ ]+)$"
    # Dòng toàn chữ hoa = tiêu đề chương
}
```

### Output Format

```json
{
  "document": {
    "id": "LDN2020",
    "title": "Luật Doanh nghiệp",
    "number": "59/2020/QH14",
    "issued_date": "2020-06-17",
    "effective_from": "2021-01-01"
  },
  "articles": [
    {
      "number": 17,
      "title": "Điều kiện thành lập, quản lý doanh nghiệp",
      "content_raw": "1. Tổ chức, cá nhân sau đây...",
      "clauses": [
        {
          "number": 1,
          "content": "Tổ chức, cá nhân sau đây có quyền...",
          "points": [
            {
              "label": "a",
              "content": "Cơ quan nhà nước, đơn vị vũ trang nhân dân..."
            }
          ]
        }
      ]
    }
  ]
}
```

---

## Step 2: LLM Information Extraction

### Two-Pass Strategy

**Pass 1 — Entity Extraction** (per Article):

```python
ENTITY_EXTRACTION_PROMPT = """
Cho điều luật sau:
---
{article_text}
---

Trích xuất tất cả entities được đề cập:

1. Documents được viện dẫn (số hiệu văn bản)
2. Concepts pháp lý (khái niệm, thuật ngữ chuyên ngành)
3. Entities (loại hình doanh nghiệp, cơ quan, chủ thể)

Trả về JSON:
{
  "entities": [
    {
      "id": "string (unique, snake_case)",
      "type": "Document|Concept|Entity|Article",
      "label": "string (tên hiển thị)",
      "properties": {}
    }
  ]
}
"""

**Pass 2 — Relation Extraction** (per Article, using entities from Pass 1):

```python
RELATION_EXTRACTION_PROMPT = """
Cho điều luật sau và danh sách entities đã xác định:
---
Article: {article_text}
Entities: {entities_json}
---

Xác định các quan hệ giữa entities.
Chỉ sử dụng các relation types sau:
- AMENDED_BY: A bị sửa đổi bởi B
- REPLACED_BY: A bị thay thế bởi B
- REFERENCES: A viện dẫn B
- DEFINES: Article/Clause định nghĩa Concept
- REGULATES: Article/Clause điều chỉnh Entity
- REQUIRES: Entity yêu cầu/phải có Concept
- IMPLEMENTED_BY: Law được hướng dẫn bởi Decree
- GUIDED_BY: Decree được hướng dẫn bởi Circular

Trả về JSON:
{
  "relations": [
    {
      "head": "entity_id",
      "relation": "RELATION_TYPE",
      "tail": "entity_id",
      "evidence": "câu văn làm cơ sở",
      "confidence": 0.0-1.0
    }
  ]
}
"""
```

---

## Step 3: JSON Schema Validation

```python
ENTITY_SCHEMA = {
    "type": "object",
    "required": ["id", "type", "label"],
    "properties": {
        "id": {"type": "string", "pattern": "^[a-z0-9_]+$"},
        "type": {"enum": ["Document", "Article", "Clause", "Point", "Concept", "Entity", "Definition"]},
        "label": {"type": "string", "minLength": 1},
        "properties": {"type": "object"}
    }
}

RELATION_SCHEMA = {
    "type": "object",
    "required": ["head", "relation", "tail"],
    "properties": {
        "head": {"type": "string"},
        "relation": {"enum": [
            "CONTAINS", "AMENDED_BY", "REPLACED_BY", "REPEALED_BY",
            "IMPLEMENTED_BY", "GUIDED_BY", "REFERENCES",
            "DEFINES", "REGULATES", "REQUIRES"
        ]},
        "tail": {"type": "string"},
        "evidence": {"type": "string"},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1}
    }
}
```

---

## Step 4: Ontology Validation

```python
class OntologyValidator:
    CONSTRAINTS = {
        "CONTAINS": {
            "valid_pairs": [
                ("Document", "Article"),
                ("Article", "Clause"),
                ("Clause", "Point")
            ],
            "no_self_loop": True
        },
        "AMENDED_BY": {
            "head_tail_same_type": True,
            "no_self_loop": True
        },
        "IMPLEMENTED_BY": {
            "valid_pairs": [("Document", "Document")],
            "head_doc_type": "Law",
            "tail_doc_type": "Decree"
        },
        "DEFINES": {
            "valid_pairs": [
                ("Article", "Concept"),
                ("Clause", "Concept"),
                ("Article", "Definition")
            ]
        }
    }
    
    def validate_relation(self, head_type, relation, tail_type):
        constraint = self.CONSTRAINTS.get(relation)
        if not constraint:
            return False, f"Unknown relation type: {relation}"
        
        valid_pairs = constraint.get("valid_pairs", [])
        if valid_pairs and (head_type, tail_type) not in valid_pairs:
            return False, f"Invalid pair: {head_type}-[{relation}]->{tail_type}"
        
        return True, None
```

---

## Step 5: Confidence Scoring (Self-Consistency)

```python
class ConfidenceScorer:
    def __init__(self, n_runs: int = 3):
        self.n_runs = n_runs
    
    def score(self, chunk: str, extraction_fn) -> tuple[dict, float]:
        """
        Chạy extraction N lần, tính agreement score
        """
        results = [extraction_fn(chunk) for _ in range(self.n_runs)]
        
        # Aggregate relations
        relation_counts = defaultdict(int)
        for result in results:
            for rel in result.get("relations", []):
                key = (rel["head"], rel["relation"], rel["tail"])
                relation_counts[key] += 1
        
        # Agreement score = fraction of runs that agree
        agreed_relations = [
            rel for rel, count in relation_counts.items()
            if count >= ceil(self.n_runs / 2)  # Majority vote
        ]
        
        total_possible = max(
            len(set(k for result in results for k in 
                   [(r["head"], r["relation"], r["tail"]) 
                    for r in result.get("relations", [])]))
            , 1
        )
        
        confidence = len(agreed_relations) / total_possible
        
        return agreed_relations, confidence
```

---

## Human Review Queue

```python
class HumanReviewQueue:
    """
    Đơn giản nhất: lưu vào file JSON, reviewer mở và check
    Có thể upgrade lên web UI sau
    """
    
    def push(self, item: dict, confidence: float, reason: str):
        entry = {
            "id": uuid4().hex,
            "timestamp": datetime.now().isoformat(),
            "confidence": confidence,
            "reason": reason,
            "extraction": item,
            "status": "pending",  # pending | approved | rejected | modified
            "reviewer_comment": None
        }
        # Append to JSONL file
        with open("human_review_queue.jsonl", "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
```

---

## Evaluation — Level 1 (Graph Construction Quality)

```python
def evaluate_graph_construction(gold_graph: dict, predicted_graph: dict):
    """
    So sánh predicted graph với gold standard annotation
    """
    # Entity metrics
    gold_entities = set(e["id"] for e in gold_graph["entities"])
    pred_entities = set(e["id"] for e in predicted_graph["entities"])
    
    entity_tp = len(gold_entities & pred_entities)
    entity_precision = entity_tp / len(pred_entities) if pred_entities else 0
    entity_recall = entity_tp / len(gold_entities) if gold_entities else 0
    
    # Relation metrics (head, relation, tail) tuple matching
    gold_rels = set(
        (r["head"], r["relation"], r["tail"]) 
        for r in gold_graph["relations"]
    )
    pred_rels = set(
        (r["head"], r["relation"], r["tail"]) 
        for r in predicted_graph["relations"]
    )
    
    rel_tp = len(gold_rels & pred_rels)
    rel_precision = rel_tp / len(pred_rels) if pred_rels else 0
    rel_recall = rel_tp / len(gold_rels) if gold_rels else 0
    
    return {
        "entity_precision": entity_precision,
        "entity_recall": entity_recall,
        "entity_f1": 2 * entity_precision * entity_recall / (entity_precision + entity_recall + 1e-9),
        "relation_precision": rel_precision,
        "relation_recall": rel_recall,
        "relation_f1": 2 * rel_precision * rel_recall / (rel_precision + rel_recall + 1e-9)
    }
```
