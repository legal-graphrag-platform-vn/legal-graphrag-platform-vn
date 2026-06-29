# Ontology Specification — Legal Knowledge Graph

> **Trạng thái**: Draft — cần nhóm review và chốt  
> **Phiên bản**: 0.1  
> **Domain**: Pháp luật doanh nghiệp Việt Nam

---

## Tầng 1 — Conceptual Model

### Các Khái Niệm Trong Thế Giới Pháp Luật Doanh Nghiệp VN

```
                    ┌─────────────────────────┐
                    │       Hệ thống PL        │
                    └──────────┬──────────────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
         Văn bản          Chủ thể          Khái niệm
         pháp luật        pháp lý          pháp lý
              │
    ┌─────────┼──────────┐
    ▼         ▼          ▼
  Luật    Nghị định   Thông tư
              │
    ┌─────────┼──────────┐
    ▼         ▼          ▼
  Điều     Khoản       Điểm
```

### Phân Loại Văn Bản Pháp Luật (Document Types)

| Type | Tiếng Việt | Ví Dụ | Cấp |
|---|---|---|---|
| `Law` | Luật, Bộ luật | Luật Doanh nghiệp 2020 | Cao nhất |
| `Decree` | Nghị định | NĐ 01/2021/NĐ-CP | Dưới Luật |
| `Circular` | Thông tư | TT 01/2021/TT-BKHĐT | Dưới NĐ |
| `Resolution` | Nghị quyết | NQ 01/2021/QH | Ngang Luật |
| `Decision` | Quyết định | QĐ 01/2021/TTg | Khác |

---

## Tầng 2 — Formal Ontology

### Node Types

```
(:Document)
Properties:
  - id: string (unique) — e.g., "LDN2020"
  - number: string — e.g., "59/2020/QH14"
  - title: string — e.g., "Luật Doanh nghiệp"
  - type: enum [Law, Decree, Circular, Resolution, Decision]
  - issued_by: string — e.g., "Quốc hội"
  - issued_date: date — e.g., "2020-06-17"
  - effective_from: date
  - effective_to: date | null
  - status: enum [active, amended, repealed, suspended]

(:Article)
Properties:
  - id: string (unique) — e.g., "LDN2020_D17"
  - number: int — e.g., 17
  - title: string — e.g., "Điều kiện thành lập doanh nghiệp"
  - content: string — full text
  - effective_from: date
  - effective_to: date | null
  - status: enum [active, amended, repealed]

(:Clause)
Properties:
  - id: string (unique) — e.g., "LDN2020_D17_K1"
  - number: int — e.g., 1
  - content: string — full text
  - effective_from: date
  - effective_to: date | null

(:Point)
Properties:
  - id: string (unique) — e.g., "LDN2020_D17_K1_Da"
  - label: string — e.g., "a"
  - content: string — full text

(:Concept)
Properties:
  - id: string (unique)
  - name: string — e.g., "Vốn điều lệ"
  - definition: string (optional)
  - domain: string — e.g., "company_law"

(:Entity)
Properties:
  - id: string (unique)
  - name: string — e.g., "Công ty TNHH"
  - type: enum [company_type, authority, person_type]
```

### Relation Types

```
CONTAINS
  Head: Document | Article | Clause
  Tail: Article | Clause | Point
  Properties: order (int)
  Ý nghĩa: Quan hệ phân cấp cấu trúc

AMENDED_BY
  Head: Article | Clause | Document
  Tail: Article | Clause | Document (cùng loại)
  Properties:
    - effective_from: date
    - effective_to: date | null
    - amendment_type: enum [partial, full]
    - source_document: string (văn bản sửa đổi)
  Ý nghĩa: A bị sửa đổi bởi B kể từ ngày effective_from

REPLACED_BY
  Head: Document | Article
  Tail: Document | Article (cùng loại)
  Properties:
    - effective_from: date
  Ý nghĩa: A bị thay thế hoàn toàn bởi B

REPEALED_BY
  Head: Document | Article | Clause
  Tail: Document (văn bản hủy bỏ)
  Properties:
    - effective_from: date
  Ý nghĩa: A bị bãi bỏ bởi B

IMPLEMENTED_BY
  Head: Document (type=Law)
  Tail: Document (type=Decree)
  Properties:
    - scope: string (phạm vi hướng dẫn)
  Ý nghĩa: Luật được hướng dẫn bởi Nghị định

GUIDED_BY
  Head: Document (type=Decree)
  Tail: Document (type=Circular)
  Properties:
    - scope: string
  Ý nghĩa: Nghị định được hướng dẫn bởi Thông tư

REFERENCES
  Head: Article | Clause
  Tail: Article | Clause | Document
  Properties:
    - reference_type: enum [direct, conditional]
  Ý nghĩa: A viện dẫn B

DEFINES
  Head: Article | Clause
  Tail: Concept
  Ý nghĩa: Điều/Khoản định nghĩa một khái niệm pháp lý

REGULATES
  Head: Article | Clause
  Tail: Entity | Concept
  Ý nghĩa: Điều/Khoản điều chỉnh một chủ thể hoặc khái niệm

REQUIRES
  Head: Entity
  Tail: Concept
  Properties:
    - condition_type: enum [must, should, prohibited]
  Ý nghĩa: Chủ thể phải/nên/không được...
```

### Ontology Constraints (Rules)

```python
CONSTRAINTS = {
    "CONTAINS": {
        "allowed_head": ["Document", "Article", "Clause"],
        "allowed_tail": ["Article", "Clause", "Point"],
        "no_self_loop": True,
        "head_tail_type_pairs": [
            ("Document", "Article"),
            ("Article", "Clause"),
            ("Clause", "Point")
        ]
    },
    "AMENDED_BY": {
        "allowed_head": ["Document", "Article", "Clause"],
        "allowed_tail": ["Document", "Article", "Clause"],
        "head_tail_same_type": True,  # Document→Document, Article→Article
        "no_self_loop": True
    },
    "IMPLEMENTED_BY": {
        "allowed_head": ["Document"],
        "allowed_tail": ["Document"],
        "head_type_constraint": "Law",
        "tail_type_constraint": "Decree"
    },
    "GUIDED_BY": {
        "allowed_head": ["Document"],
        "allowed_tail": ["Document"],
        "head_type_constraint": "Decree",
        "tail_type_constraint": "Circular"
    },
    "DEFINES": {
        "allowed_head": ["Article", "Clause"],
        "allowed_tail": ["Concept"]
    },
    "REGULATES": {
        "allowed_head": ["Article", "Clause"],
        "allowed_tail": ["Entity", "Concept"]
    }
}
```

---

## Tầng 3 — Neo4j Schema

### Cypher Schema

```cypher
// Indexes
CREATE INDEX document_id FOR (d:Document) ON (d.id);
CREATE INDEX article_id FOR (a:Article) ON (a.id);
CREATE INDEX concept_name FOR (c:Concept) ON (c.name);

// Full-text search
CALL db.index.fulltext.createNodeIndex(
  "articleFullText", ["Article", "Clause", "Point"], ["content", "title"]
);

// Temporal indexes
CREATE INDEX article_effective FOR (a:Article) ON (a.effective_from, a.effective_to);
CREATE INDEX rel_amended_temporal FOR ()-[r:AMENDED_BY]-() ON (r.effective_from);
```

### Ví Dụ Dữ Liệu Thực

```cypher
// Luật Doanh nghiệp 2020
CREATE (:Document {
  id: "LDN2020",
  number: "59/2020/QH14",
  title: "Luật Doanh nghiệp",
  type: "Law",
  issued_by: "Quốc hội",
  issued_date: date("2020-06-17"),
  effective_from: date("2021-01-01"),
  effective_to: null,
  status: "active"
});

// Nghị định 01/2021
CREATE (:Document {
  id: "ND01_2021",
  number: "01/2021/NĐ-CP",
  title: "Nghị định về đăng ký doanh nghiệp",
  type: "Decree",
  issued_by: "Chính phủ",
  issued_date: date("2021-01-04"),
  effective_from: date("2021-01-04"),
  effective_to: null,
  status: "active"
});

// Quan hệ
MATCH (l:Document {id: "LDN2020"}), (d:Document {id: "ND01_2021"})
CREATE (l)-[:IMPLEMENTED_BY {scope: "đăng ký doanh nghiệp"}]->(d);

// Điều 17
CREATE (:Article {
  id: "LDN2020_D17",
  number: 17,
  title: "Điều kiện thành lập, quản lý doanh nghiệp",
  content: "...",
  effective_from: date("2021-01-01"),
  effective_to: null,
  status: "active"
});

// CONTAINS
MATCH (l:Document {id: "LDN2020"}), (a:Article {id: "LDN2020_D17"})
CREATE (l)-[:CONTAINS {order: 17}]->(a);
```

---

## Câu Hỏi Mở — Cần Nhóm Thảo Luận

| # | Câu Hỏi | Ảnh Hưởng |
|---|---|---|
| 1 | `Definition` là node riêng hay attribute của `Concept`? | Schema của RC1 |
| 2 | Phụ lục (Annex) xử lý như node `Annex` hay bỏ qua? | Pipeline RC2 |
| 3 | `Procedure` (thủ tục hành chính) có phải node riêng? | Scope |
| 4 | Có cần node `Authority` (cơ quan ban hành)? | Graph complexity |
| 5 | Cách generate `id` cho Article: `{doc_id}_D{number}` — có ổn không? | Data consistency |
