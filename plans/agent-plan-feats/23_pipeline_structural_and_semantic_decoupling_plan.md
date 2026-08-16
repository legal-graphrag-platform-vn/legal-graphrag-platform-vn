# Pipeline Structural and Semantic Decoupling Plan

> **Status:** Draft / Planned  
> **Date:** 2026-08-16  
> **Scope:** Phân tách luồng Ingestion thành 2 pha độc lập: Phase 1 (Deterministic Structural Backbone + Vector Embedding) và Phase 2 (Asynchronous Semantic Enrichment & LegalConcept Synchronization).  
> **Authority:** `src/shared/ontology/contract.py` và `plans/legal_ontology.md` giữ vai trò single source of truth.

---

## 1. Problem Statement & Motivation

Hiện tại, quy trình `write` và `ingest` trong `src/pipeline/` bị gắn chặt (tightly coupled) giữa cấu trúc pháp lý (`hierarchy.json`) và trích xuất ngữ nghĩa LLM (`extract.jsonl`, `accepted.jsonl`, `entity_index.json`):

1. **Nghẽn luồng nạp dữ liệu (Ingestion Bottleneck):** Quá trình nạp cây phân cấp văn bản và tạo Vector Index bị phụ thuộc 100% vào tốc độ gọi LLM, quota API và độ trễ trích xuất.
2. **Khó chịu lỗi (Lack of Fault Tolerance):** Nếu bước LLM extraction gặp lỗi (rate-limit, timeout, schema validation error), toàn bộ văn bản bị dừng và không thể nạp vào Neo4j dù cấu trúc phân cấp đã parse thành công.
3. **Cản trở tiến hóa tri thức (Impedes Knowledge Evolution):** Khi cần tinh chỉnh Prompt, đổi model SFT trích xuất, hoặc bổ sung relation mới, hệ thống hiện tại phải chạy lại toàn bộ pipeline thay vì chỉ cập nhật đồ thị ngữ nghĩa.

**Giải pháp:** Phân rã Ingestion thành **2 pha độc lập (2-Phase Ingestion Pattern)**:
* **Phase 1 (Structural Ingestion):** Parse cây cấu trúc văn bản $\rightarrow$ Ghi Neo4j $\rightarrow$ Tạo Vector Embeddings. Chạy xác định (deterministic), tốc độ cao (vài giây/văn bản), sẵn sàng cho Hybrid Search.
* **Phase 2 (Semantic Enrichment):** Trích xuất `LegalConcept`, `LegalSubject`, `LegalAction` qua LLM $\rightarrow$ Đồng bộ Cypher `MERGE` vào các `Article`/`Clause` đã có trên Neo4j.

---

## 2. Invariants & Architectural Rules

1. **Idempotent Multi-Pass Writes:** Mọi thao tác ghi node và relation đều sử dụng Cypher `MERGE` qua [`Neo4jWriter`](file:///D:/Workspace/Project/legal-graphrag/legal-graphrag-platform-vn/src/infrastructure/neo4j/writer.py) với `id` và `relation_id` tiền định (deterministic SHA-1).
2. **Global Entity vs. Local Edge Invariant:**
   * Node `LegalConcept` là Global Entity (dùng chung trên toàn đồ thị, `id` là canonical slug như `von_dieu_le`, `doanh_nghiep`).
   * Cạnh `(:Article)-[:DEFINES]->(:LegalConcept)` là Local Edge (thuộc về `Article` cụ thể của văn bản).
   * Đồng bộ `LegalConcept` của văn bản này không gây xung đột dữ liệu với văn bản khác.
3. **Embedding Independence:** Quá trình sinh Vector Embedding trên `Article`, `Clause`, `Appendix` (BGE-M3) chỉ dựa vào nội dung văn bản cấu trúc, hoàn toàn độc lập với `LegalConcept`.
4. **Guarded Writer Compliance:** Mọi payload (structural hoặc semantic) đều phải đi qua `payload_consistency_validator` và `validate_graph_payload` trước khi tới `Neo4jWriter`.

---

## 3. Data Flow Architecture

```text
[PHASE 1: DETERMINISTIC STRUCTURAL BACKBONE]
Raw Document (HTML / Text / PDF)
    │
    ▼
[parse] ──► hierarchy.json (Document, Chapter, Section, Article, Clause, Point, Appendix)
    │
    ▼
[validate-structural] (Gate 1 Check: hierarchy schema & legal metadata)
    │
    ▼
[write-structural] (Idempotent MERGE: Structural Nodes + Structural Relations)
    │
    ▼
[embed] (Dense Vector Embeddings cho Article & Clause -> Neo4j Vector Indexes)
    │
    └─► Hệ thống phục vụ ngay Hybrid Search (BM25 + Vector + Graph Traversal)

─────────────────────────────────────────────────────────────────────────────

[PHASE 2: ASYNCHRONOUS SEMANTIC ENRICHMENT]
hierarchy.json
    │
    ▼
[extract] ──► extract.jsonl ──► accepted.jsonl + entity_index.json (Gate 2 Check)
    │
    ▼
[validate-semantic] (Validate Semantic Payload)
    │
    ▼
[sync-concepts] (Cypher MERGE: LegalConcept, LegalSubject, LegalAction, DEFINES, MENTIONS)
    │
    └─► Làm giàu đồ thị phục vụ Concept Expansion & Multi-hop Reasoning
```

---

## 4. Detailed Implementation Tasks

### Task 1: Tách Gate Validation Readiness
* **Target File:** [`src/pipeline/validation/extraction_readiness.py`](file:///D:/Workspace/Project/legal-graphrag/legal-graphrag-platform-vn/src/pipeline/validation/extraction_readiness.py)
* **Yêu cầu:**
  1. Thêm `validate_structural_readiness(processed_dir: Path) -> None`:
     * Kiểm tra sự tồn tại và tính hợp lệ của `hierarchy.json`.
     * Kiểm tra metadata văn bản tối thiểu (`doc_type`, `number`, `effective_from`, `legal_status`).
  2. Giữ nguyên `validate_extraction_readiness(processed_dir: Path)` làm Gate 2 kiểm tra các file artifact của LLM (`accepted.jsonl`, `entity_index.json`).

### Task 2: Refactor Payload Builder & Loader
* **Target Files:**
  * [`src/pipeline/persistence/payload_builder.py`](file:///D:/Workspace/Project/legal-graphrag/legal-graphrag-platform-vn/src/pipeline/persistence/payload_builder.py)
  * [`src/pipeline/persistence/validated_payload_loader.py`](file:///D:/Workspace/Project/legal-graphrag/legal-graphrag-platform-vn/src/pipeline/persistence/validated_payload_loader.py)
* **Yêu cầu:**
  1. Cập nhật `build_graph_payload()`: Cho phép `accepted_records` và `entity_index` là rỗng (`None` hoặc `[]`/`{}`). Khi đó chỉ tạo các node và relation cấu trúc.
  2. Thêm hàm chuyên biệt:
     * `build_structural_payload(parsed: ParsedDocument, *, raw_doc_code: str) -> dict[str, Any]`
     * `build_semantic_payload(accepted_records: list[Mapping], entity_index: Mapping, *, raw_doc_code: str) -> dict[str, Any]`
  3. Cập nhật `load_validated_payload(processed_dir: Path, mode: Literal["structural", "semantic", "full"] = "full")`:
     * Mode `"structural"`: Chạy qua Gate 1 $\rightarrow$ `build_structural_payload` $\rightarrow$ Validate payload.
     * Mode `"semantic"`: Chạy qua Gate 2 $\rightarrow$ `build_semantic_payload` $\rightarrow$ Validate payload.
     * Mode `"full"`: Giữ hành vi hiện tại (tương thích ngược).

### Task 3: Cập nhật Neo4j Writer & Ingestion Service
* **Target File:** [`src/infrastructure/neo4j/writer.py`](file:///D:/Workspace/Project/legal-graphrag/legal-graphrag-platform-vn/src/infrastructure/neo4j/writer.py)
* **Yêu cầu:**
  1. `Neo4jWriter` ghi các node `LegalConcept` bằng `MERGE (n:LegalConcept {id: $id})`.
  2. Khi ghi quan hệ ngữ nghĩa `MATCH (head {id: $head_id}) MATCH (tail {id: $tail_id})`: Nếu `head` (Article) chưa có trong Neo4j (do chưa chạy Phase 1), ghi nhận log cảnh báo hoặc raise exception rõ ràng để yêu cầu nạp Phase 1 trước.

### Task 4: Mở rộng CLI Entrypoints
* **Target File:** [`src/pipeline/main.py`](file:///D:/Workspace/Project/legal-graphrag/legal-graphrag-platform-vn/src/pipeline/main.py)
* **Yêu cầu:**
  1. Thêm command `write-structural`:
     ```bash
     python -m src.pipeline.main write-structural --raw-doc-code <raw_doc_code>
     ```
  2. Thêm command `sync-concepts`:
     ```bash
     python -m src.pipeline.main sync-concepts --raw-doc-code <raw_doc_code>
     ```
  3. Cập nhật command `write`: Thêm flag `--mode [full|structural|semantic]` (mặc định `full`).
  4. Cập nhật command `ingest`: Thêm flag `--structural-only` hoặc `--skip-extract` để cho phép nạp nhanh văn bản mà không gọi LLM.

### Task 5: Testing & Verification
* **Target Directory:** `src/pipeline/tests/`
* **Test cases:**
  1. `test_structural_payload_builder`: Kiểm tra payload chỉ chứa `Document`, `Chapter`, `Section`, `Article`, `Clause`, `Point`, `Appendix`.
  2. `test_semantic_payload_builder`: Kiểm tra payload chỉ chứa `LegalConcept`, `LegalSubject`, `LegalAction` và các relation `DEFINES`, `MENTIONS`.
  3. `test_idempotent_two_phase_write`:
     * Bước 1: Ghi structural payload vào test Neo4j container.
     * Bước 2: Kiểm tra số lượng node cấu trúc và quan hệ `CONTAINS`.
     * Bước 3: Ghi semantic payload vào cùng database.
     * Bước 4: Kiểm tra `LegalConcept` được gắn đúng vào `Article` tương ứng mà không làm thay đổi các node cấu trúc.

---

## 5. Target CLI Workflow

```bash
# ==============================================================================
# LUỒNG 1: NẠP NHANH VĂN BẢN VÀO HỆ THỐNG (Phase 1 - Vài giây, không tốn LLM)
# ==============================================================================
# 1. Crawl & Parse
uv run python -m src.pipeline.main crawl --url "https://vbpl.vn/..." --raw-doc-code L59_2020 --number "59/2020/QH14"
uv run python -m src.pipeline.main parse --raw-doc-code L59_2020

# 2. Ghi khung cấu trúc vào Neo4j & Sinh Embeddings
uv run python -m src.pipeline.main write-structural --raw-doc-code L59_2020
uv run python -m src.pipeline.main embed --raw-doc-code L59_2020

# -> Lúc này hệ thống ĐÃ SẴN SÀNG trả lời câu hỏi qua Vector Search + Graph Traversal.

# ==============================================================================
# LUỒNG 2: LÀM GIÀU TRI THỨC NGỮ NGHĨA (Phase 2 - Chạy nền / Batch)
# ==============================================================================
# 1. Trích xuất LLM & Chuẩn hóa
uv run python -m src.pipeline.main extract --raw-doc-code L59_2020
uv run python -m src.pipeline.main normalize-extraction --raw-doc-code L59_2020

# 2. Đồng bộ LegalConcept vào Neo4j
uv run python -m src.pipeline.main sync-concepts --raw-doc-code L59_2020
```
