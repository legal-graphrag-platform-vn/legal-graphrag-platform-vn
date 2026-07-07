# Legal Ontology — Frozen Contract

> **Trạng thái**: FROZEN — không sửa mà không có ADR  
> **Phiên bản**: 1.2.0  
> **Ngày chốt**: 2026-07-06  
> **Phạm vi**: Pháp luật Việt Nam — tập trung Luật Doanh nghiệp + văn bản liên quan

---

> Đây là **hợp đồng (contract)** giữa tất cả các thành phần hệ thống.  
> Mọi thay đổi phải tạo ADR và tăng version.  
> Thứ tự phụ thuộc: `legal_ontology.md` → `schema_init.cypher` → Pydantic models → Prompt → Validator → Writer

---

## 1. Kiến trúc — Hai Tầng

```
┌──────────────────────────────────────────────────────────┐
│  STRUCTURAL LAYER — Tầng văn bản                         │
│  Document, Chapter, Article, Clause, Point, Issuer       │
│  Relations: ISSUED_BY, AMENDS, REPEALS, GUIDES, ...      │
└──────────────────────────────────────────────────────────┘
                         ↕  Article → DEFINES/REGULATES → ...
┌──────────────────────────────────────────────────────────┐
│  SEMANTIC LAYER — Tầng tri thức pháp lý                  │
│  LegalConcept, LegalSubject, LegalAction,                │
│  Obligation, Right, Condition, Exception                 │
│  Relations: DEFINES, REGULATES, REQUIRES,                │
│             HAS_CONDITION, HAS_EXCEPTION                 │
└──────────────────────────────────────────────────────────┘
```

---

## 2. Node Types

### 2.1 Structural Layer

#### Document

| Property | Type | Required | Ghi chú |
|---|---|---|---|
| `id` | string | ✅ | snake_case, unique. Vd: `ldn_2020` |
| `doc_type` | enum | ✅ | Constitution\|Law\|Ordinance\|Resolution\|Decree\|Decision\|Circular\|JointCircular |
| `number` | string | ✅ | Số hiệu chính thức. Vd: `"59/2020/QH14"` |
| `normative` | boolean | ✅ | `true` = văn bản quy phạm; `false` = không index |
| `legal_status` | enum | ✅ | ACTIVE\|NOT_YET_EFFECTIVE\|PARTIALLY_EFFECTIVE\|REPLACED\|REPEALED\|EXPIRED |
| `effective_from` | date | ✅ | Ngày có hiệu lực |
| `effective_to` | date | ❌ | Null nếu chưa hết hiệu lực |
| `jurisdiction` | string | ❌ | `"National"`, `"Ho Chi Minh City"`, ... |
| `source_url` | string | ❌ | URL trên vbpl.vn |
| `document_uri` | string | ❌ | URI local/S3 của file gốc |
| `issuer_name` | string | ✅ | Tên cơ quan ban hành — Writer dùng để MERGE Issuer node. Vd: `"National Assembly"` |
| `gazette_number` | string | ❌ | Số Công báo |

**Định nghĩa `legal_status`**:
- `PARTIALLY_EFFECTIVE`: Một phần văn bản còn hiệu lực — state, không mô tả nguyên nhân. Chi tiết → suy luận từ relation graph.
- `REPLACED`: Toàn bộ nội dung được thay thế bởi một văn bản mới (có văn bản kế nhiệm).
- `REPEALED`: Bị bãi bỏ hiệu lực mà không nhất thiết có văn bản kế nhiệm.

#### Issuer

Tự động tạo từ `Document.issuer_name` trong Writer (MERGE). LLM không extract riêng.

| Property | Type | Required | Ghi chú |
|---|---|---|---|
| `id` | string | ✅ | `slug(normalize(issuer_name))` — **MERGE key**. Vd: `"Quốc hội"` → `"quoc_hoi"` |
| `name` | string | ✅ | Tên canonical từ vbpl.vn controlled vocabulary (không chuẩn hóa hoa/thường) |
| `branch` | enum | ✅ | `LEGISLATIVE\|EXECUTIVE\|JUDICIAL\|OTHER` — map qua `ISSUER_BRANCH_MAP` |

> **Unique key = `id` (slug), không phải `name`** (ADR-14 Rev.1).  
> `MERGE (i:Issuer {id: $slug})` tránh duplicate khi `issuer_name` có biến thể hoa/thường.  
> `name` lưu giá trị gốc từ vbpl.vn để hiển thị; `id` dùng để lookup/merge.

> **Không có `level` property.** Level chỉ dùng trong Validator rule engine (xem §5).

#### Chapter / Article / Clause / Point

| Node | Property | Type | Required | Ghi chú |
|---|---|---|---|---|
| Chapter | `id` | string | ✅ | `{doc_id}_ch{N}`. Vd: `ldn2020_ch2` |
| Chapter | `number` | string | ✅ | `"II"` |
| Chapter | `title` | string | ✅ | `"Thành lập doanh nghiệp"` |
| Article | `id` | string | ✅ | `{doc_id}_art{N}`. Vd: `ldn2020_art17` |
| Article | `number` | string | ✅ | `"17"` |
| Article | `title` | string | ❌ | Tiêu đề điều (nếu có) |
| Article | `content_raw` | string | ✅ | Nội dung gốc |
| Article | `embedding` | float[768] | ❌ | **Nullable** — Embedding Generator fill sau Writer (M3 Tuần 2). 768-dim = schema contract (xem §7). |
| Clause | `id` | string | ✅ | `{doc_id}_art{N}_cl{K}` |
| Clause | `number` | string | ✅ | `"1"`, `"2"`, ... |
| Clause | `content_raw` | string | ✅ | Nội dung gốc |
| Clause | `embedding` | float[768] | ❌ | **Nullable** — đơn vị retrieval chính theo ADR-02 |
| Point | `id` | string | ✅ | `{doc_id}_art{N}_cl{K}_p{letter}` |
| Point | `label` | string | ✅ | `"a"`, `"b"`, `"c"` |
| Point | `content_raw` | string | ✅ | Nội dung gốc |

> **Point không có `embedding`** — Point là 1 câu rất ngắn, không đủ ngữ cảnh để tạo vector có ý nghĩa riêng (ADR-02). Đơn vị retrieval chính là Clause; Article dùng cho câu hỏi tổng quát.

---

### 2.2 Semantic Layer

| Node | Ý nghĩa | Ví dụ | Phase | Extraction status |
|---|---|---|---|---|
| `LegalConcept` | Khái niệm, thuật ngữ pháp lý trừu tượng | `vốn điều lệ`, `tư cách pháp nhân` | Phase 1 | ✅ LLM extract (`Concept` type) |
| `LegalSubject` | Chủ thể có tư cách pháp lý | `doanh nghiệp`, `cổ đông`, `cơ quan ĐKKD` | Phase 1 | ✅ LLM extract (`Entity` type) |
| `LegalAction` | Hành vi pháp lý (động từ) | `thành lập`, `góp vốn`, `giải thể` | Phase 1 | ✅ LLM extract (`Action` type) |
| `Obligation` | Nghĩa vụ pháp lý | `nộp thuế`, `đăng ký thay đổi vốn` | Future | ⏳ Chưa có extraction path — ngoài scope đánh giá |
| `Right` | Quyền pháp lý | `quyền biểu quyết`, `quyền yêu cầu họp` | Future | ⏳ Chưa có extraction path — ngoài scope đánh giá |
| `Condition` | Điều kiện áp dụng | `vốn ≥ X tỷ`, `ít nhất 3 thành viên` | Future | ⏳ Chưa có extraction path — ngoài scope đánh giá |
| `Exception` | Ngoại lệ | `trừ trường hợp điều lệ quy định khác` | Future | ⏳ Chưa có extraction path — ngoài scope đánh giá |

> **Scope note (S4)**: Ontology mô tả **toàn bộ không gian khái niệm** của domain (thiết kế đúng-đắn về mặt học thuật — Ontology Principle 1: "Node represents stable legal concepts"). Việc **node type nào có pipeline extract được ở giai đoạn nào** là quyết định về **implementation scope**, không phải về ontology design. Hai việc này tách bạch có chủ đích.

---

## 3. Relationship Types

### 3.1 Structural Relations

| Relation | From | To | Properties |
|---|---|---|---|
| `ISSUED_BY` | Document | Issuer | — |
| `CONTAINS` | Doc/Chapter/Article/Clause | Chapter/Article/Clause/Point | — |
| `AMENDS` | Doc/Article/Clause | Doc/Article/Clause | `effective_from`, `effective_to` |
| `REPEALS` | Document | Document/Article/Clause | `effective_from` |
| `REPLACES` | Document | Document | `effective_from` |
| `GUIDES` | Document | Document | — |
| `REFERS_TO` | Article/Clause/Point | Article/Clause/Point/Document | `citation_text`, `citation_type` |

`citation_type`: `DIRECT | INDIRECT | RANGE`

### 3.2 Semantic Relations

Tất cả semantic relations có provenance:

| Property | Type | Mô tả |
|---|---|---|
| `confidence` | float | Scorer confidence (0.0–1.0) |
| `llm_model` | string | Model đã extract |
| `created_at` | datetime | Thời điểm extract |

| Relation | From | To |
|---|---|---|
| `DEFINES` | Article/Clause | LegalConcept |
| `REGULATES` | Article/Clause | LegalSubject/LegalAction |
| `REQUIRES` | LegalSubject | LegalConcept/Obligation |
| `HAS_CONDITION` | LegalAction/Obligation/Right | Condition |
| `HAS_EXCEPTION` | Article/Clause/LegalAction | Exception |

---

## 4. Extraction Schema → Ontology Mapping

LLM extract theo schema đơn giản. Writer thực hiện mapping:

LLM extraction dùng 3 semantic type:

| Extraction type | Mô tả | Ví dụ |
|---|---|---|
| `Entity` | Chủ thể có tư cách pháp lý | `doanh nghiệp`, `cổ đông` |
| `Concept` | Khái niệm/thuật ngữ pháp lý | `vốn điều lệ`, `tư cách pháp nhân` |
| `Action` | Hành vi pháp lý (động từ) | `thành lập`, `góp vốn`, `giải thể` |

Writer map sang Ontology nodes:

| Extraction type | Neo4j node |
|---|---|
| `Entity` | `LegalSubject` |
| `Concept` | `LegalConcept` |
| `Action` | `LegalAction` |
| `Document` | `Document` |
| `Article/Clause/Point` | `Article/Clause/Point` |

> LLM extract 3 type đơn giản. Writer normalize → Ontology node. Không để Writer suy luận từ Entity → LegalAction bằng POS tagging.

---

## 5. Validator Rule Engine

`level` chỉ tồn tại ở đây, không phải trong Neo4j.

### GUIDES — Whitelist Matrix

Dùng whitelist thay vì chỉ so sánh số nguyên. `Law-GUIDES-Law` sẽ bị chặn đúng (cùng level = không hướng dẫn nhau).

```python
# (from_doc_type, to_doc_type) → valid
GUIDES_WHITELIST: set[tuple[str, str]] = {
    ("Constitution",  "Law"),
    ("Constitution",  "Ordinance"),
    ("Law",           "Decree"),
    ("Law",           "Decision"),      # PM Decision
    ("Law",           "Circular"),
    ("Ordinance",     "Decree"),
    ("Resolution",    "Decree"),
    ("Decree",        "Circular"),
    ("Decree",        "Decision"),      # Minister Decision
    ("Decree",        "JointCircular"),
    ("Decision",      "Circular"),      # PM Decision → Circular
}

def validate_guides(from_type: str, to_type: str) -> bool:
    return (from_type, to_type) in GUIDES_WHITELIST
```

### Precedence (dự phòng cho các relation khác)

```python
VALIDATOR_PRECEDENCE: dict[str, int] = {
    "Constitution":                    5,
    "Law":                             4,
    "Ordinance":                       4,
    "Resolution_NationalAssembly":     4,
    "Resolution_Government":           3,
    "Decree":                          3,
    "PrimeMinisterDecision":           3,
    "Resolution_Provincial":           2,
    "MinisterDecision":                2,
    "Circular":                        2,
    "JointCircular":                   2,
    "LocalDecision":                   1,
}
```

### Semantic Relation Guidelines

Annotator và LLM phải tuân theo:

| Relation | Khi nào dùng | Ví dụ |
|---|---|---|
| `DEFINES` | Article đưa ra **định nghĩa** của một Concept | `Điều 4. Giải thích từ ngữ — "vốn điều lệ" là...` |
| `REGULATES` | Article **điều chỉnh hành vi** của Subject/Action | `Điều 13 quy định về việc thành lập doanh nghiệp` |
| `REQUIRES` | Subject/Action có **nghĩa vụ** phải đáp ứng | `Doanh nghiệp phải đăng ký thay đổi vốn` |
| `HAS_CONDITION` | Áp dụng **có điều kiện** | `Chỉ áp dụng khi vốn ≥ 10 tỷ` |
| `HAS_EXCEPTION` | Có **ngoại lệ** | `Trừ trường hợp điều lệ quy định khác` |

---

## 6. Naming Conventions

| Element | Convention | Ví dụ |
|---|---|---|
| Document ID | slug | `ldn_2020` |
| Article ID | `{doc_id}_art{N}` | `ldn2020_art17` |
| Clause ID | `{doc_id}_art{N}_cl{K}` | `ldn2020_art17_cl1` |
| Point ID | `{doc_id}_art{N}_cl{K}_p{letter}` | `ldn2020_art17_cl1_pa` |
| Concept/Subject ID | snake_case không dấu | `von_dieu_le` |
| Issuer ID | snake_case | `national_assembly` |
| Relation | SCREAMING_SNAKE_CASE, active voice | `AMENDS`, `DEFINES` |

---

## 7. Constraints & Cardinality

| Constraint | Mô tả |
|---|---|
| `Document.id` UNIQUE | 1 document = 1 node |
| `Article.id` UNIQUE | — |
| No self-loop trên CONTAINS | — |
| No cycle trên AMENDS | DAG enforcement |
| `normative=false` → không có GUIDES | Quyết định cá biệt không hướng dẫn |
| `AMENDS.effective_from` required | Temporal relation bắt buộc |
| `Article.embedding` dim = 768 | **Schema contract** — đổi model → phải ADR + DROP INDEX + re-embed |
| `Clause.embedding` dim = 768 | Idem — 768 = vietnamese-bi-encoder dimension |
| `Point` không có `embedding` | ADR-02: Point quá ngắn, không embed |


---

## 8. Out of Scope — v1.0

- `Procedure` node (quy trình nhiều bước) → Future Work
- `LegalSubject` subtypes (Person/Organization/Enterprise/StateAgency) → Future Work
- `OfficialDispatch` → không đưa vào normative KG
- Cross-jurisdiction mapping → Future Work

---

## 9. Ontology Principles

> Dành cho hội đồng luận văn — thể hiện thiết kế có chủ đích, không để code dẫn dắt kiến trúc.

1. **Node represents stable legal concepts** — không phải implementation artifact.
2. **Relationship represents legal semantics** — mỗi relation type có ý nghĩa pháp lý rõ ràng.
3. **Validator logic is NOT ontology** — precedence/whitelist sống trong rule engine, không trong graph.
4. **Metadata không duplicate graph semantics** trừ khi vì lý do hiệu năng (vd: `legal_status` denormalized để filter nhanh).
5. **Every semantic edge must have provenance** — confidence, llm_model, created_at là bắt buộc.
6. **Extraction schema ≠ Ontology** — LLM extract theo schema đơn giản (Entity/Concept/Action); Writer normalize sang ontology đầy đủ.
7. **Structural Layer ổn định trước, Semantic Layer phát triển iterative** — không block nhau.

---

## 10. ADR Log

| Version | Ngày | Thay đổi | Lý do |
|---|---|---|---|
| 1.0.0 | 2026-07-03 | Initial frozen schema | 4 rounds debate, consensus đạt được |
| 1.1.0 | 2026-07-03 | +`issuer_name` vào Document; GUIDES dùng whitelist thay precedence; thêm `Action` extraction type; định nghĩa REPLACED/REPEALED; semantic relation guidelines; Ontology Principles | Reviewer feedback 5 điểm |
| 1.2.0 | 2026-07-06 | +`embedding: float[768]` (nullable) vào Article và Clause; explicit note Point không có embedding; expand Chapter/Article/Clause/Point property table; Chapter ID naming convention | F2: gap giữa schema (VECTOR INDEX đã tạo) và ontology (chưa khai báo field) — RC3 Hybrid Retrieval phụ thuộc vào field này |
