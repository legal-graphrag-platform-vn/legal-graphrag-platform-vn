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
[Step 5] Confidence Scoring                       ← ADR-06: rule-based, không phải N=3
    │   Input : Validated JSON + graph context
    │   Output: confidence score ∈ [0, 1] (weighted multi-criteria)
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
        "type": {"enum": ["Document", "Article", "Clause", "Point", "Concept", "Entity"]},
        "label": {"type": "string", "minLength": 1},
        "properties": {"type": "object"}
    }
}

# NOTE: "Definition" đã được loại bỏ khỏi enum.
# Definition = attribute của Concept (Concept.definition), không phải node riêng.
# Quyết định: ADR session 2026-06-29.

RELATION_SCHEMA = {
    "type": "object",
    "required": ["head", "relation", "tail"],
    "properties": {
        "head": {"type": "string"},
        "relation": {"enum": [
            "CONTAINS", "AMENDED_BY", "REPLACED_BY", "REPEALED_BY",
            "IMPLEMENTED_BY",        # GUIDED_BY đã hợp nhất vào đây
            "REFERENCES", "DEFINES", "REGULATES", "REQUIRES"
            # Tổng: 9 relation types
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
    # ╔════════════════════════════════════════════
    # Phải đồng bộ với CONSTRAINTS trong 02_ontology_specification.md
    # Duy trì bằng unit test: tests/test_ontology_consistency.py
    # GUIDED_BY đã hợp nhất vào IMPLEMENTED_BY.
    # ╚════════════════════════════════════════════
    DOCUMENT_LEVELS = {
        "Law": 3, "Resolution": 3,
        "Decree": 2, "Decision": 2,
        "Circular": 1
    }

    RELATION_ENUM = {
        "CONTAINS", "AMENDED_BY", "REPLACED_BY", "REPEALED_BY",
        "IMPLEMENTED_BY",
        "REFERENCES", "DEFINES", "REGULATES", "REQUIRES"
        # Tổng: 9 — GUIDED_BY hợp nhất vào IMPLEMENTED_BY
    }

    CONSTRAINTS = {
        "CONTAINS": {
            "valid_pairs": [
                ("Document", "Article"),
                ("Article",  "Clause"),
                ("Clause",   "Point")
            ],
            "no_self_loop": True
        },
        "AMENDED_BY": {
            # Document→Document ĐÃ Bỏ: cấp Document dùng REPLACED_BY hoặc REPEALED_BY.
            # head_tail_same_type bị bỏ — quá strict cho cấu trúc luật sửa đổi VN.
            "valid_pairs": [
                ("Article",  "Article"),   # Điều→Điều
                ("Article",  "Clause"),    # Điều→Khoản ← phổ biến nhất VN
                ("Clause",   "Clause"),    # Khoản→Khoản
                ("Clause",   "Article"),   # Khoản→Điều (mở rộng)
            ],
            "no_self_loop": True,
            "required_properties": ["effective_from"]
        },
        "REPLACED_BY": {
            "head_tail_same_type": True,
            "valid_pairs": [
                ("Document", "Document"),
                ("Article",  "Article")
            ],
            "no_self_loop": True,
            "required_properties": ["effective_from"]
        },
        "REPEALED_BY": {
            "allowed_tail": ["Document"],   # Tail LUÔN là Document
            "head_tail_same_type": False,
            "required_properties": ["effective_from"]
        },
        "IMPLEMENTED_BY": {
            # Level-based rule: head.level > tail.level
            # GUIDED_BY đã hợp nhất vào đây.
            # Covers: Law→Decree, Law→Circular (direct),
            #         Resolution→Decree, Decree→Circular, Decision→Circular
            "rule": "head_doc_level > tail_doc_level",
            # doc_levels reference: DOCUMENT_LEVELS dict phía trên
        },
        "REFERENCES": {
            "valid_pairs": [
                ("Article", "Article"),
                ("Article", "Clause"),
                ("Article", "Document"),
                ("Clause",  "Article"),
                ("Clause",  "Clause"),
                ("Clause",  "Document")
            ]
        },
        "DEFINES": {
            "valid_pairs": [
                ("Article", "Concept"),
                ("Clause",  "Concept")
            ]
        },
        "REGULATES": {
            "valid_pairs": [
                ("Article", "Entity"),
                ("Article", "Concept"),
                ("Clause",  "Entity"),
                ("Clause",  "Concept")
            ]
        },
        "REQUIRES": {
            "valid_pairs": [
                ("Entity", "Concept"),
                ("Entity", "Entity"),   # ví dụ: công ty phải có người đại diện theo PL
            ]
        }
    }

    def validate_relation(self, head_type, relation, tail_type):
        constraint = self.CONSTRAINTS.get(relation)
        if not constraint:
            # Relation không có trong CONSTRAINTS → reject
            # Nếu gặp lỗi này: kiểm tra RELATION_ENUM và CONSTRAINTS có khớp nhau không
            return False, f"Unknown relation type: {relation}. Check RELATION_ENUM == set(CONSTRAINTS.keys())"

        valid_pairs = constraint.get("valid_pairs", [])
        if valid_pairs and (head_type, tail_type) not in valid_pairs:
            return False, f"Invalid pair: {head_type}-[{relation}]->{tail_type}"

        # Kiểm tra required_properties trên relation (runtime check)
        # Được gọi bởi pipeline với relation_data dict
        return True, None
```

---

## Unit Test Spec — Ontology Consistency

```python
# tests/test_ontology_consistency.py
# Chạy: pytest tests/test_ontology_consistency.py
# Tốc độ: < 1ms, không cần DB hay LLM

from pipeline.ontology_validator import OntologyValidator, RELATION_ENUM

RELATION_ENUM_EXPECTED = {
    "CONTAINS", "AMENDED_BY", "REPLACED_BY", "REPEALED_BY",
    "IMPLEMENTED_BY", "GUIDED_BY", "REFERENCES",
    "DEFINES", "REGULATES", "REQUIRES"
}

def test_all_relations_have_constraints():
    """
    Mọi relation trong enum phải có đúng 1 key trong CONSTRAINTS.
    Test này fail ngay nếu thêm relation mới mà quên thêm constraint.
    """
    missing = RELATION_ENUM_EXPECTED - set(OntologyValidator.CONSTRAINTS.keys())
    assert missing == set(), f"Relations thiếu constraint: {missing}"

def test_no_orphan_constraints():
    """
    Không có constraint nào cho relation không tồn tại trong enum.
    """
    orphans = set(OntologyValidator.CONSTRAINTS.keys()) - RELATION_ENUM_EXPECTED
    assert orphans == set(), f"Constraints thừa (không có trong enum): {orphans}"

def test_references_not_rejected():
    """REFERENCES là relation phổ biến nhất — phải pass validator."""
    validator = OntologyValidator()
    ok, err = validator.validate_relation("Article", "REFERENCES", "Article")
    assert ok, f"REFERENCES bị reject: {err}"

def test_requires_not_rejected():
    """REQUIRES quan trọng cho XAI reasoning path."""
    validator = OntologyValidator()
    ok, err = validator.validate_relation("Entity", "REQUIRES", "Concept")
    assert ok, f"REQUIRES bị reject: {err}"

def test_replaced_by_same_type_enforced():
    """REPLACED_BY phải cùng loại (Document→Document, Article→Article)."""
    validator = OntologyValidator()
    ok, _ = validator.validate_relation("Document", "REPLACED_BY", "Document")
    assert ok
    ok, _ = validator.validate_relation("Article", "REPLACED_BY", "Document")
    assert not ok, "Article→Document REPLACED_BY phải bị reject"

def test_repealed_by_tail_always_document():
    """REPEALED_BY: Clause có thể bị bãi bỏ bởi Document."""
    validator = OntologyValidator()
    ok, err = validator.validate_relation("Clause", "REPEALED_BY", "Document")
    assert ok, f"Clause→Document REPEALED_BY bị reject: {err}"
```

---

## Step 5: Confidence Scoring (Rule-based)

> [!IMPORTANT]
> **ADR-06**: Dùng rule-based multi-criteria, KHÔNG dùng self-consistency N=3.
> Lý do: Explainable, không tốn thêm API calls, threshold calibrate được trên validation set.

```python
class ConfidenceScorer:
    """Rule-based confidence scorer theo ADR-06."""

    WEIGHTS = {
        "schema_valid":       0.30,
        "ontology_valid":     0.30,
        "evidence_present":   0.20,
        "entities_resolvable":0.10,
        "direction_correct":  0.10,
    }

    def score(self, extraction: dict, validation_results: dict, graph_context: dict) -> tuple[float, dict]:
        """
        Args:
            extraction: LLM extraction result
            validation_results: kết quả từ JSON Schema + Ontology Validator
            graph_context: các IDs hiện có trong graph (dùng kiểm tra entity resolvable)
        Returns:
            (confidence_score, criteria_breakdown)
        """
        criteria = {
            # 1. JSON Schema pass?
            "schema_valid": 1.0 if validation_results.get("schema_ok") else 0.0,

            # 2. Ontology constraint pass?
            "ontology_valid": 1.0 if validation_results.get("ontology_ok") else 0.0,

            # 3. Có evidence trong text?
            "evidence_present": 1.0 if extraction.get("evidence", "").strip() else 0.0,

            # 4. Head + Tail IDs resolvable?
            "entities_resolvable": self._check_entities(
                extraction, graph_context
            ),

            # 5. Hướng relation đúng?
            "direction_correct": 1.0 if validation_results.get("direction_ok") else 0.0,
        }

        score = sum(
            self.WEIGHTS[k] * v for k, v in criteria.items()
        )
        return round(score, 3), criteria

    def _check_entities(self, extraction, graph_context) -> float:
        head_id = extraction.get("head", "")
        tail_id = extraction.get("tail", "")
        existing_ids = graph_context.get("existing_ids", set())
        resolved = sum([
            1 if head_id in existing_ids else 0,
            1 if tail_id in existing_ids else 0
        ])
        return resolved / 2.0
```

### Threshold Calibration (thực hiện sau khi có validation data)

```
Doạn calibration:
  1. Annotate thủ công 3 văn bản (gold standard triples)
  2. Chạy pipeline, tính confidence score cho mọi extraction
  3. Vẽ Precision-Recall curve theo threshold
  4. Chọn threshold tối ưu theo F1
  5. Report threshold + PR curve trong luận văn

Không viết số cụ thể trước khi chạy experiment.
```
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
