# Hướng Dẫn Sử Dụng Pipeline CLI (Legal GraphRAG VN)

> **Cập nhật:** 2026-08-16  
> **Phạm vi:** Tài liệu hướng dẫn toàn diện các lệnh CLI trong module `src.pipeline.main` phục vụ việc cào dữ liệu, phân tách cấu trúc, nạp đồ thị 2 pha (Structural & Semantic), nhúng vector embeddings và xử lý hàng loạt.

---

## 1. Tổng Quan Kiến Trúc Nạp Dữ Liệu (2-Phase Ingestion)

Hệ thống hỗ trợ nạp dữ liệu theo 2 pha độc lập để tối ưu tốc độ và chi phí:

```text
[PHASE 1: NẠP KHUNG CẤU TRÚC & VECTOR (Vài giây / văn bản - Không tốn LLM quota)]
  parse ──► write-structural ──► embed
  (Sẵn sàng phục vụ Hybrid Search: BM25 + Vector Search + Cypher traversal)

[PHASE 2: LÀM GIÀU TRI THỨC NGỮ NGHĨA (Chạy bất đồng bộ / Theo lô)]
  extract ──► normalize-extraction ──► sync-semantics (hoặc sync-concepts)
  (Đồng bộ LegalConcept, LegalSubject, LegalAction và các quan hệ DEFINES, MENTIONS, APPLIES_TO, REQUIRES vào đồ thị)
```

---

## 2. Bảng Tra Cứu 6 Lệnh CLI Cốt Lõi (Core 6 Commands)

| Nhóm | # | Tên lệnh CLI | Mô tả chức năng | Cú pháp mẫu |
|---|---|---|---|---|
| **Từng raw doc code** | 1 | `add-node` | Ghi cấu trúc cây Điều/Khoản/Điểm của 1 văn bản vào Neo4j | `uv run python -m src.pipeline.main add-node --raw-doc-code LTV_101180` |
| | 2 | `embed-node` | Sinh vector embedding BGE-M3 (1024 dims) cho 1 văn bản | `uv run python -m src.pipeline.main embed-node --raw-doc-code LTV_101180` |
| | 3 | `sync-concept` | Đồng bộ thực thể ngữ nghĩa & quan hệ của 1 văn bản vào Neo4j | `uv run python -m src.pipeline.main sync-concept --raw-doc-code LTV_101180` |
| **Hàng loạt (Batch)** | 4 | `batch-add-nodes` | Quét toàn bộ folder `data/processed` và ghi cấu trúc vào Neo4j | `uv run python -m src.pipeline.main batch-add-nodes` |
| | 5 | `batch-embed-nodes`| Sinh vector embedding hàng loạt cho toàn bộ folder processed | `uv run python -m src.pipeline.main batch-embed-nodes --batch-size 32` |
| | 6 | `batch-sync-concepts`| Đồng bộ hàng loạt Concept/Subject/Action & Quan hệ vào Neo4j | `uv run python -m src.pipeline.main batch-sync-concepts` |

---

## 3. Chi Tiết Từng Lệnh & Tham Số

### 3.1 Nhóm lệnh theo Từng Raw Doc Code (Single Document)

```bash
# 1. Ghi cấu trúc cây phân cấp Điều/Khoản/Điểm (Phase 1)
uv run python -m src.pipeline.main add-node --raw-doc-code LTV_101180

# 2. Sinh vector embeddings cho Article/Clause vào Neo4j
uv run python -m src.pipeline.main embed-node --raw-doc-code LTV_101180

# 3. Đồng bộ các thực thể (LegalConcept, LegalSubject, LegalAction) & quan hệ (Phase 2)
uv run python -m src.pipeline.main sync-concept --raw-doc-code LTV_101180
```

---

### 3.2 Nhóm lệnh Hàng Loạt (Batch All Folder Processed)

```bash
# 4. Ghi toàn bộ các folder đã parse trong data/processed/ vào Neo4j
uv run python -m src.pipeline.main batch-add-nodes

# 5. Sinh vector embeddings cho toàn bộ các văn bản đã parse
uv run python -m src.pipeline.main batch-embed-nodes --batch-size 32

# 6. Đồng bộ toàn bộ khái niệm & tri thức ngữ nghĩa của các văn bản đã extract
uv run python -m src.pipeline.main batch-sync-concepts
```

> **Tùy chọn bổ sung cho các lệnh Batch:**
> * `--processed-dir <path>`: Chỉ định thư mục processed khác (mặc định: `data/processed`).
> * `--limit <N>`: Giới hạn số lượng $N$ văn bản đầu tiên để chạy thử nghiệm.
> * `--manifest <path>`: Dùng danh sách từ file manifest JSON.

---

### 3.3 Lệnh nạp trọn gói nhanh (All-in-One Shortcut)

```bash
# Nạp nhanh toàn bộ văn bản đã parse (gồm batch-add-nodes + batch-embed-nodes trong 1 lệnh)
uv run python -m src.pipeline.main batch-load-parsed
```

---

### 3.4 Nhóm lệnh Đối soát & Kết nối Quan hệ Liên văn bản (Cross-document References - Plan 17 & Plan 22)

Các quan hệ **Dẫn chiếu (`REFERS_TO`)**, **Sửa đổi (`AMENDS`)**, **Bãi bỏ (`REPEALS`)** giữa các văn bản khác nhau được tự động đối soát và kết nối bằng 1 lệnh duy nhất:

```bash
# Tự động quét toàn bộ kho dữ liệu, tạo snapshot và ghi tất cả cạnh liên văn bản vào Neo4j:
uv run python -m src.pipeline.main batch-reconcile-references --apply
```

---

### 3.5 Nhóm lệnh xử lý hàng loạt từ nguồn thô (Raw Batch)

| Lệnh | Ý nghĩa | Tùy chọn nổi bật |
|---|---|---|
| `build-manifest` | Quét thư mục raw và tạo file manifest JSON | `--raw-dir`, `--output` |
| `batch-parse` | Parse cấu trúc cây cho toàn bộ dataset trong manifest | `--workers 4`, `--retry-failed`, `--limit` |
| `batch-extract` | Gọi LLM trích xuất tri thức song song (hỗ trợ checkpoint per-Article) | `--limit`, `--retry-failed` |
| `batch-reconcile-references` | Tự động kết nối toàn bộ quan hệ liên văn bản vào Neo4j | `--apply` |
| `batch-ingest-all` | Chạy tuần tự toàn bộ các bước Batch trong 1 lệnh | `--skip-extract`, `--workers 4`, `--limit` |
| `ingest-folder` / `pipeline-folder` | Chạy Full Pipeline cho một thư mục bất kỳ | `--folder`, `--skip-extract`, `--doc-by-doc`, `--workers 4` |

**Ví dụ:**
```bash
# Chạy toàn bộ thư mục data/raw bỏ qua trích xuất LLM
uv run python -m src.pipeline.main batch-ingest-all --skip-extract

# Chạy lần lượt từng văn bản (Parse -> Write Neo4j -> Embed)
uv run python -m src.pipeline.main ingest-folder --folder data/raw --doc-by-doc --skip-extract
```

---

### 3.4 Nhóm lệnh hòa giải tham chiếu & Quản trị Schema

| Lệnh | Ý nghĩa | Ví dụ |
|---|---|---|
| `init-schema` | Khởi tạo toàn bộ Constraints & Vector Indexes trên Neo4j | `uv run python -m src.pipeline.main init-schema` |
| `verify-schema` | Kiểm tra trạng thái ONLINE của các Indexes và Constraints | `uv run python -m src.pipeline.main verify-schema` |
| `clear-database` | Xóa sạch toàn bộ node & relationship trên Neo4j Server | `uv run python -m src.pipeline.main clear-database --force` |
| `validate-payload` | Kiểm tra payload trước khi nạp đồ thị (không mở Neo4j) | `uv run python -m src.pipeline.main validate-payload --raw-doc-code L59_2020 --mode structural` |
| `build-reference-registry` | Tạo registry liên văn bản bất biến từ các payload đã qua kiểm duyệt | `uv run python -m src.pipeline.main build-reference-registry --build-id registry-001 --manifest configs/corpus/curated_v1.json` |
| `reconcile-external-references` | Điều hòa và nối các cạnh dẫn chiếu liên văn bản (`AMENDS`, `REFERS_TO`) | `uv run python -m src.pipeline.main reconcile-external-references --build-id registry-001 --apply` |
