# Ontology Specification — Legal Knowledge Graph

> **Trạng thái**: v0.2 — cập nhật sau review ADR  
> **Phiên bản**: 0.2  
> **Domain**: Pháp luật doanh nghiệp Việt Nam

> [!IMPORTANT]
> File này là **source of truth** cho toàn bộ Neo4j schema.  
> Mọi thay đổi phải được cả nhóm đồng ý và cập nhật vào đây trước khi code.

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

---

### ID Convention (CHỐT — không thay đổi)

> [!IMPORTANT]
> ID phải **unique, human-readable, stable**. Toàn bộ pipeline dùng convention này.

```
Document:  {doc_code}
           Ví dụ: LDN2020, ND01_2021, TT01_2021
           Rule: viết tắt tên văn bản + năm

Article:   {doc_code}_D{number}
           Ví dụ: LDN2020_D17

Clause:    {doc_code}_D{number}_K{number}
           Ví dụ: LDN2020_D17_K1

Point:     {doc_code}_D{number}_K{number}_P{label}
           Ví dụ: LDN2020_D17_K1_Pa  (điểm a)

Concept:   concept_{slug_viet_khong_dau}
           Ví dụ: concept_von_dieu_le

Entity:    entity_{slug_viet_khong_dau}
           Ví dụ: entity_cong_ty_tnhh
```

**Xử lý collision**: Khi Điều 17 NĐ47/2024 sửa Điều 17 LDN2020:
- `LDN2020_D17` = phiên bản gốc
- `ND47_2024_D17` = điều sửa đổi (node khác)
- Quan hệ: `(LDN2020_D17)-[:AMENDED_BY]->(ND47_2024_D17)`

---

### Node Labels — Multi-label Strategy (CHỐT)

> [!IMPORTANT]
> **Quyết định**: Dùng **multi-label** cho Document type thay vì property.
> Lý do: Ontology constraint `IMPLEMENTED_BY` chỉ từ `:Law` → `:Decree` enforce được ở DB level.

```
:Document:Law        — Luật, Bộ luật
:Document:Decree     — Nghị định
:Document:Circular   — Thông tư
:Document:Resolution — Nghị quyết
:Document:Decision   — Quyết định

:Entity:CompanyType  — Loại hình doanh nghiệp
:Entity:Authority    — Cơ quan nhà nước
:Entity:PersonType   — Loại chủ thể (cá nhân, tổ chức)
```

Query examples với multi-label:
```cypher
// Chỉ tìm Luật (không bao gồm Nghị định)
MATCH (d:Document:Law) RETURN d

// Enforce constraint: IMPLEMENTED_BY chỉ từ Law → Decree
MATCH (law:Document:Law)-[:IMPLEMENTED_BY]->(decree:Document:Decree)
```

---

### Node Types & Properties

```
(:Document:Law | :Document:Decree | :Document:Circular | ...)
Properties:
  - id: string (unique)          — e.g., "LDN2020"
  - number: string               — e.g., "59/2020/QH14"
  - title: string                — e.g., "Luật Doanh nghiệp"
  - issued_by: string            — e.g., "Quốc hội"
  - issued_date: date            — e.g., date("2020-06-17")
  - effective_from: date
  - effective_to: date | null    — null = còn hiệu lực
  - status: enum [active, amended, repealed, suspended]
  [KHÔNG có property 'type' — type được encode trong label]

(:Article)
Properties:
  - id: string (unique)          — e.g., "LDN2020_D17"
  - number: int                  — e.g., 17
  - title: string                — e.g., "Điều kiện thành lập..."
  - content: string              — full text của Điều
  - effective_from: date
  - effective_to: date | null
  - status: enum [active, amended, repealed]
  - embedding: float[]           — vector 768 dims ⭐ (dùng cho hybrid search)

(:Clause)
Properties:
  - id: string (unique)          — e.g., "LDN2020_D17_K1"
  - number: int                  — e.g., 1
  - content: string              — full text của Khoản
  - effective_from: date
  - effective_to: date | null
  - status: enum [active, amended, repealed, suspended]
  - embedding: float[]           — vector 768 dims ⭐ (unit chính cho retrieval)

(:Point)
Properties:
  - id: string (unique)          — e.g., "LDN2020_D17_K1_Pa"
  - label: string                — e.g., "a"
  - content: string              — full text của Điểm
  - effective_from: date         — ⭐ cần thiết cho RC4 temporal filter
  - effective_to: date | null    — null = còn hiệu lực
  - status: enum [active, amended, repealed]
  [KHÔNG có embedding — Point quá ngắn, embed ở Clause level]

(:Concept)
Properties:
  - id: string (unique)          — e.g., "concept_von_dieu_le"
  - name: string                 — e.g., "Vốn điều lệ"
  - definition: string | null    — định nghĩa chính thức (nếu có)
  - defined_in: string | null    — ID của Article/Clause định nghĩa (backref citation)
  - domain: string               — e.g., "company_law"

(:Entity:CompanyType | :Entity:Authority | :Entity:PersonType)
Properties:
  - id: string (unique)          — e.g., "entity_cong_ty_tnhh"
  - name: string                 — e.g., "Công ty TNHH"
```

> [!NOTE]
> **Embedding chỉ có ở Article và Clause** — đây là hai đơn vị retrieval chính.
> Point quá ngắn để embed độc lập; Concept/Entity được retrieve qua graph, không qua vector.

### Relation Types

> [!IMPORTANT]
> **Temporal consistency rule**: Tất cả relation có ngữ nghĩa thời gian (AMENDED_BY, REPLACED_BY, REPEALED_BY) **bắt buộc** có property `effective_from`. Thiếu là lỗi ontology.

```
CONTAINS
  Head: Document | Article | Clause
  Tail: Article | Clause | Point
  Head-Tail pairs hợp lệ:
    Document → Article
    Article  → Clause
    Clause   → Point
  Properties:
    - order: int (thứ tự xuất hiện trong văn bản)
  Temporal: KHÔNG (quan hệ cấu trúc, không thay đổi)

AMENDED_BY
  Head: Document | Article | Clause
  Tail: Document | Article | Clause (phải cùng loại với Head)
  Properties:
    - effective_from: date         ← BẮT BUỘC
    - effective_to: date | null    ← null = vẫn còn hiệu lực sửa đổi
    - amendment_type: enum [partial, full]
    - source_doc_id: string        ← ID của văn bản chứa nội dung sửa đổi
  Ý nghĩa: A bị sửa đổi bởi B, có hiệu lực từ effective_from
  Lưu ý: B là node chứa NỘI DUNG SỬA ĐỔI, không phải văn bản sửa đổi

REPLACED_BY
  Head: Document | Article
  Tail: Document | Article (phải cùng loại với Head)
  Properties:
    - effective_from: date         ← BẮT BUỘC
    - effective_to: date | null
  Ý nghĩa: A bị thay thế TOÀN BỘ bởi B kể từ effective_from. Có văn bản kế thừa.
  Phân biệt với AMENDED_BY: REPLACED_BY = hết toàn bộ hiệu lực
  Phân biệt với REPEALED_BY: REPLACED_BY = có văn bản mới kế tiếp

  Ví dụ phân biệt:
  ✅ REPLACED_BY: NĐ 78/2015 → [REPLACED_BY] → NĐ 01/2021
     (cùng lĩnh vực đăng ký DN, Nđ01 kế thừa toàn bộ Nđ78)

REPEALED_BY
  Head: Document | Article | Clause
  Tail: Document (văn bản ra quyết định hủy bỏ)
  Properties:
    - effective_from: date         ← BẮT BUỘC
  Ý nghĩa: A bị bãi bỏ hoàn toàn bởi văn bản B. KHÔNG có văn bản kế thừa.
  Sau effective_from: A.status = "repealed"

  Ví dụ phân biệt:
  ✅ REPEALED_BY: Điều 12 LDN2014 → [REPEALED_BY] → LDN2020
     (điều này bị bãi bỏ hoàn toàn, LDN2020 không có điều tương đương kế thừa)

  Heuristic cho LLM:
  "Có văn bản mới cùng lĩnh vực kế tiếp" → REPLACED_BY
  "Bị loại bỏ, không có văn bản tương đương" → REPEALED_BY

IMPLEMENTED_BY
  Head: :Document (bất kỳ loại)
  Tail: :Document (bất kỳ loại)
  Rule: **head.level > tail.level** (văn bản cấp cao hướng dẫn văn bản cấp thấp)
  Properties:
    - scope: string | null         ← phạm vi hướng dẫn (optional)
  Ý nghĩa: Văn bản cấp cao giao cho văn bản cấp thấp hướng dẫn thi hành
  Temporal: KHÔNG

  Cấp bậc văn bản:
  ```
  DOCUMENT_LEVELS = {
      "Law": 3, "Resolution": 3,     # Cấp Quốc hội
      "Decree": 2, "Decision": 2,    # Cấp Chính phủ / Thủ tướng
      "Circular": 1                   # Cấp Bộ
  }
  ```

  Các cặp hợp lệ (head.level > tail.level):
    Law (3) → Decree (2)      ✓ trường hợp thông thường
    Law (3) → Circular (1)    ✓ Luật giao thẳng cho Bộ trưởng
    Resolution (3) → Decree (2) ✓
    Decree (2) → Circular (1)  ✓ (trước đây là GUIDED_BY)
    Decision (2) → Circular (1) ✓

  Lưu ý: GUIDED_BY đã được hợp nhất vào IMPLEMENTED_BY.

REFERENCES
  Head: Article | Clause
  Tail: Article | Clause | Document
  Properties:
    - reference_type: enum [direct, conditional]
  Ý nghĩa: A viện dẫn B ("căn cứ theo Điều X...")
  Temporal: KHÔNG

DEFINES
  Head: Article | Clause
  Tail: Concept
  Properties: (không có)
  Ý nghĩa: Điều/Khoản đưa ra định nghĩa chính thức cho Concept
  Temporal: KHÔNG

REGULATES
  Head: Article | Clause
  Tail: Entity | Concept
  Properties: (không có)
  Ý nghĩa: Điều/Khoản điều chỉnh hành vi/nghĩa vụ của chủ thể
  Temporal: KHÔNG (temporal của Article/Clause đã bao phủ)

REQUIRES
  Head: Entity
  Tail: Concept
  Properties:
    - condition_type: enum [must, should, prohibited]
    - source_article: string       ← ID của Article/Clause áp đặt yêu cầu
      (tránh mất citation khi LLM bỏ sót REGULATES tương ứng)
  Ý nghĩa: Chủ thể phải/nên/không được có/làm Concept, theo quy định tại source_article
  Temporal: KHÔNG

  Ví dụ:
  (entity_cong_ty_tnhh)-[:REQUIRES {
    condition_type: "must",
    source_article: "LDN2020_D46_K1"   ← XAI có thể cite trực tiếp
  }]->(concept_so_thanh_vien_toi_thieu)
```

**Tổng kết temporal policy:**

| Relation | Có Temporal? | Lý do |
|---|---|---|
| `CONTAINS` | ❌ | Cấu trúc văn bản không đổi |
| `AMENDED_BY` | ✅ | Sửa đổi có ngày hiệu lực |
| `REPLACED_BY` | ✅ | Thay thế có ngày hiệu lực |
| `REPEALED_BY` | ✅ | Hủy bỏ có ngày hiệu lực |
| `IMPLEMENTED_BY` | ❌ | Quan hệ hành chính tĩnh |
| `REFERENCES` | ❌ | Temporal của node đã bao phủ |
| `DEFINES` | ❌ | Temporal của node đã bao phủ |
| `REGULATES` | ❌ | Temporal của node đã bao phủ |
| `REQUIRES` | ❌ | Temporal của node đã bao phủ |

### Ontology Constraints (Rules)

```python
# ╔══════════════════════════════════════════════════════
# QUAN TRỌNG: Mọi relation trong RELATION_ENUM phải có
# đúng 1 entry trong CONSTRAINTS. Duy trì bằng unit test.
# GUIDED_BY đã được hợp nhất vào IMPLEMENTED_BY.
# ╚══════════════════════════════════════════════════════
DOCUMENT_LEVELS = {
    "Law": 3, "Resolution": 3,     # Cấp Quốc hội
    "Decree": 2, "Decision": 2,    # Cấp Chính phủ
    "Circular": 1                   # Cấp Bộ
}

RELATION_ENUM = {
    "CONTAINS", "AMENDED_BY", "REPLACED_BY", "REPEALED_BY",
    "IMPLEMENTED_BY",              # GUIDED_BY đã hợp nhất vào đây
    "REFERENCES", "DEFINES", "REGULATES", "REQUIRES"
    # Tổng: 9 relation types
}

CONSTRAINTS = {
    # --- Cấu trúc phân cấp ---
    "CONTAINS": {
        "allowed_head": ["Document", "Article", "Clause"],
        "allowed_tail": ["Article", "Clause", "Point"],
        "no_self_loop": True,
        "head_tail_type_pairs": [
            ("Document", "Article"),
            ("Article",  "Clause"),
            ("Clause",   "Point")
        ]
    },

    # --- Temporal relations ---
    "AMENDED_BY": {
        # Bỏ head_tail_same_type — quá strict cho pháp luật VN.
        # Bỏ Document→Document — ở cấp Document, dùng REPLACED_BY/REPEALED_BY.
        # Văn bản sửa đổi VN thường có cấu trúc:
        #   "Điều 1: Khoản 1: Điều 17 LDN2020 được sửa đổi như sau..."
        # → head=Article (LDN2020_D17), tail=Clause (LuatSD_D1_K1) là hợp lệ.
        "valid_pairs": [
            # Document→Document ĐÃ Bỏ: cấp Document dùng REPLACED_BY hoặc REPEALED_BY
            ("Article",  "Article"),   # Điều→Điều (cùng cấp)
            ("Article",  "Clause"),    # Điều→Khoản ← phổ biến nhất trong luật sửa đổi VN
            ("Clause",   "Clause"),    # Khoản→Khoản (cùng cấp)
            ("Clause",   "Article"),   # Khoản→Điều (khoản nhỏ mở rộng thành điều)
        ],
        "no_self_loop": True,
        "required_properties": ["effective_from"],
        # Heuristic phân biệt AMENDED_BY vs REPLACED_BY:
        # Đối tượng sửa đổi là Article hoặc Clause → AMENDED_BY
        # Đối tượng là toàn bộ Document → REPLACED_BY (có kế thừa) hoặc REPEALED_BY (không)
    },
    "REPLACED_BY": {
        "allowed_head": ["Document", "Article"],
        "allowed_tail": ["Document", "Article"],
        "head_tail_same_type": True,  # Document→Document, Article→Article
        "no_self_loop": True,
        "required_properties": ["effective_from"]
    },
    "REPEALED_BY": {
        "allowed_head": ["Document", "Article", "Clause"],
        "allowed_tail": ["Document"],  # Tail LUÔN là Document
        "head_tail_same_type": False,  # Clause→Document là hợp lệ
        "no_self_loop": True,
        "required_properties": ["effective_from"]
    },

    # --- Hành chính phân cấp ---
    "IMPLEMENTED_BY": {
        # Level-based rule: head.level > tail.level
        # GUIDED_BY đã hợp nhất vào đây.
        # Covers: Law→Decree, Law→Circular (direct),
        #         Resolution→Decree, Decree→Circular, Decision→Circular
        "rule": "head_doc_level > tail_doc_level",
        "doc_levels": {"Law": 3, "Resolution": 3,
                       "Decree": 2, "Decision": 2,
                       "Circular": 1},
        # valid_pairs được tính động từ rule, không hard-code
    },

    # --- Ngữ nghĩa ---
    "REFERENCES": {
        "allowed_head": ["Article", "Clause"],
        "allowed_tail": ["Article", "Clause", "Document"],
        "no_self_loop": False  # Article có thể viện dẫn Article khác
    },
    "DEFINES": {
        "allowed_head": ["Article", "Clause"],
        "allowed_tail": ["Concept"]
    },
    "REGULATES": {
        "allowed_head": ["Article", "Clause"],
        "allowed_tail": ["Entity", "Concept"]
    },
    "REQUIRES": {
        "allowed_head": ["Entity"],
        "allowed_tail": ["Concept", "Entity"],  # Entity: ví dụ "công ty phải có người đại diện theo PL"
        "no_self_loop": True
    }
}

# Invariant: RELATION_ENUM == set(CONSTRAINTS.keys())
# Được kiểm tra bằng unit test (xem tests/test_ontology_consistency.py)
```

---

## Tầng 3 — Neo4j Schema (Cypher)

### 3.1 Constraints (chạy khi init DB)

```cypher
// Uniqueness — bắt buộc có
CREATE CONSTRAINT doc_id_unique   FOR (d:Document) REQUIRE d.id IS UNIQUE;
CREATE CONSTRAINT art_id_unique   FOR (a:Article)  REQUIRE a.id IS UNIQUE;
CREATE CONSTRAINT cls_id_unique   FOR (c:Clause)   REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT pnt_id_unique   FOR (p:Point)    REQUIRE p.id IS UNIQUE;
CREATE CONSTRAINT con_id_unique   FOR (c:Concept)  REQUIRE c.id IS UNIQUE;
CREATE CONSTRAINT ent_id_unique   FOR (e:Entity)   REQUIRE e.id IS UNIQUE;
```

### 3.2 Indexes (chạy khi init DB)

```cypher
// --- Lookup indexes ---
CREATE INDEX doc_number  FOR (d:Document) ON (d.number);   // tìm theo số hiệu
CREATE INDEX art_number  FOR (a:Article)  ON (a.number);   // tìm theo số điều

// --- Temporal indexes ---
CREATE INDEX art_temporal FOR (a:Article) ON (a.effective_from, a.effective_to);
CREATE INDEX cls_temporal FOR (c:Clause)  ON (c.effective_from, c.effective_to);
CREATE INDEX doc_temporal FOR (d:Document) ON (d.effective_from, d.effective_to);
// Index trên relationship property (Neo4j 5.x)
CREATE INDEX amended_from FOR ()-[r:AMENDED_BY]-()   ON (r.effective_from);
CREATE INDEX replaced_from FOR ()-[r:REPLACED_BY]-() ON (r.effective_from);
CREATE INDEX repealed_from FOR ()-[r:REPEALED_BY]-() ON (r.effective_from);

// --- Full-text search ---
CREATE FULLTEXT INDEX legal_fulltext
FOR (n:Article|Clause|Point)
ON EACH [n.content, n.title];

// --- Vector index (Neo4j 5.x native) ---
CREATE VECTOR INDEX article_embedding
FOR (a:Article) ON (a.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 768,
  `vector.similarity_function`: 'cosine'
}};

CREATE VECTOR INDEX clause_embedding
FOR (c:Clause) ON (c.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 768,
  `vector.similarity_function`: 'cosine'
}};
```

> [!NOTE]
> **Tại sao dùng Neo4j Vector Index thay vì Qdrant riêng?**  
> Cho phép viết 1 Cypher query duy nhất: vector search → graph traversal → temporal filter.  
> Không cần 2 round trips (Qdrant → IDs → Neo4j).

### 3.3 Ví Dụ Dữ Liệu Thực (Cypher)

```cypher
// --- Tạo Documents (multi-label) ---
CREATE (:Document:Law {
  id: "LDN2020",
  number: "59/2020/QH14",
  title: "Luật Doanh nghiệp",
  issued_by: "Quốc hội",
  issued_date: date("2020-06-17"),
  effective_from: date("2021-01-01"),
  effective_to: null,
  status: "active"
});

CREATE (:Document:Decree {
  id: "ND01_2021",
  number: "01/2021/NĐ-CP",
  title: "Nghị định về đăng ký doanh nghiệp",
  issued_by: "Chính phủ",
  issued_date: date("2021-01-04"),
  effective_from: date("2021-01-04"),
  effective_to: null,
  status: "active"
});

// --- Quan hệ giữa Documents ---
MATCH (law:Document:Law {id: "LDN2020"}),
      (dec:Document:Decree {id: "ND01_2021"})
CREATE (law)-[:IMPLEMENTED_BY {scope: "đăng ký doanh nghiệp"}]->(dec);

// --- Tạo Article ---
CREATE (:Article {
  id: "LDN2020_D17",
  number: 17,
  title: "Điều kiện thành lập, quản lý doanh nghiệp",
  content: "1. Tổ chức, cá nhân sau đây có quyền...",
  effective_from: date("2021-01-01"),
  effective_to: null,
  status: "active",
  embedding: null   // được fill sau khi embed
});

MATCH (doc:Document:Law {id: "LDN2020"}),
      (art:Article {id: "LDN2020_D17"})
CREATE (doc)-[:CONTAINS {order: 17}]->(art);

// --- Tạo Clause ---
CREATE (:Clause {
  id: "LDN2020_D17_K1",
  number: 1,
  content: "Tổ chức, cá nhân sau đây có quyền thành lập...",
  effective_from: date("2021-01-01"),
  effective_to: null,
  status: "active",
  embedding: null   // được fill sau khi embed
});

MATCH (art:Article {id: "LDN2020_D17"}),
      (cls:Clause {id: "LDN2020_D17_K1"})
CREATE (art)-[:CONTAINS {order: 1}]->(cls);

// --- Temporal relation (AMENDED_BY) ---
// Giả sử NĐ 47/2021 sửa đổi Khoản 1 Điều 17 từ 2021-09-15
CREATE (:Clause {
  id: "ND47_2021_D1_K1",   // nội dung sửa đổi nằm trong NĐ47
  number: 1,
  content: "Nội dung sửa đổi Khoản 1 Điều 17 LDN2020...",
  effective_from: date("2021-09-15"),
  effective_to: null,
  status: "active",
  embedding: null
});

MATCH (original:Clause {id: "LDN2020_D17_K1"}),
      (amended:Clause  {id: "ND47_2021_D1_K1"})
CREATE (original)-[:AMENDED_BY {
  effective_from: date("2021-09-15"),
  effective_to: null,
  amendment_type: "partial",
  source_doc_id: "ND47_2021"
}]->(amended);

// Update status của node gốc
MATCH (c:Clause {id: "LDN2020_D17_K1"})
SET c.status = "amended", c.effective_to = date("2021-09-14");
```

### 3.4 Temporal Query Examples

```cypher
// Query 1: "Điều 17 áp dụng tại ngày 2022-01-01"
// → Tìm phiên bản Điều 17 còn hiệu lực tại 2022
MATCH (a:Article)
WHERE a.id STARTS WITH 'LDN2020_D17'
  AND a.effective_from <= date('2022-01-01')
  AND (a.effective_to IS NULL OR a.effective_to > date('2022-01-01'))
RETURN a;

// Query 2: Time-travel với AMENDED_BY chain
// → Tìm nội dung Khoản 1 Điều 17 tại ngày 2020-06-01
MATCH (base:Clause {id: 'LDN2020_D17_K1'})
OPTIONAL MATCH (base)-[r:AMENDED_BY*1..5]->(latest)
WHERE ALL(rel IN r WHERE
  rel.effective_from <= date('2020-06-01')
)
RETURN CASE WHEN latest IS NULL THEN base ELSE latest END AS valid_clause;

// Query 3: Hybrid vector + graph (Neo4j 5.x)
// → Tìm các Clause gần nhất về ngữ nghĩa, sau đó mở rộng graph
CALL db.index.vector.queryNodes('clause_embedding', 5, $query_embedding)
YIELD node AS clause, score
WHERE clause.effective_from <= date($query_date)
  AND (clause.effective_to IS NULL OR clause.effective_to > date($query_date))
MATCH (clause)<-[:CONTAINS]-(article:Article)
MATCH (article)<-[:CONTAINS]-(doc:Document)
RETURN clause, article, doc, score
ORDER BY score DESC;
```

---

## Câu Hỏi Mở — Còn Lại (Sau v0.2)

| # | Câu Hỏi | Gợi Ý | Ảnh Hưởng |
|---|---|---|---|
| 1 | `Definition` là node riêng hay attribute của `Concept`? | Attribute — đơn giản hơn, đủ dùng | Schema RC1 |
| 2 | Phụ lục (Annex) xử lý như thế nào? | Bỏ qua — scope creep | Pipeline RC2 |
| 3 | `Procedure` có phải node riêng? | Để Future Work | Scope |
| 4 | Embedding dimension: 768 (PhoBERT) hay 1536 (OpenAI)? | 768 — dùng Vietnamese model | Vector Index config |
| 5 | Neo4j version: 5.x Community có hỗ trợ Vector Index không? | Cần verify — nếu không thì dùng Qdrant | Architecture |
