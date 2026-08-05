# Hướng Dẫn Vận Hành Pipeline: Dataset LuatVietnam & Batch Processing Engine

> **Mục đích**: Hướng dẫn chi tiết cách chạy pipeline cho tập dữ liệu LuatVietnam (gồm 1,850 văn bản trong `data/raw`), cơ chế Hybrid Crawl tự động kết hợp VBPL, và cách quản lý tiến độ batch với checkpoint 2 cấp độ.

---

## 1. Tiền Đề & Cấu Hình Môi Trường

### 1.1 Kiểm Tra Môi Trường
Đảm bảo đã cài đặt Python 3.12+ và `uv` làm trình quản lý dependency:

```bash
# Cài đặt môi trường từ repo root
uv sync --group dev
```

### 1.2 File Cấu Hình `.env`
Sao chép `.env.example` tạo file `.env` tại root dự án nếu chưa có:

```bash
cp src/pipeline/.env.example .env
```

Cấu hình các biến môi trường quan trọng:
```env
# Provider LLM (gemini | minimax | qwen | openai | ollama)
LLM_PROVIDER=gemini
GEMINI_API_KEY=your_gemini_api_key_here
GEMINI_MODEL=gemini-flash-lite-latest

# Số luồng gọi LLM song song
EXTRACTION_MAX_WORKERS=2

# Neo4j Database (để ingest đồ thị)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
```

---

## 2. Quy Trình Vận Hành 4 Bước (Execution Workflow)

```text
[1. Build Manifest] --> [2. Batch Parse] --> [3. Batch Extract] --> [4. Batch Ingest]
```

### Bước 1: Sinh File Manifest & Chuẩn Hóa Metadata (`build-manifest`)

Lệnh này quét toàn bộ 1,850 thư mục văn bản thô tại `data/raw`, tự động chuẩn hóa `doc_type`, `legal_status`, `graph_id` và xuất file danh mục manifest tập trung tại `data/luatvietnam_v1.json`:

```bash
uv run python -m src.pipeline.main build-manifest
```

- **Đầu ra**: `data/luatvietnam_v1.json`
- **Tùy chọn nâng cao**:
  - `--raw-dir`: Chỉ định thư mục chứa dữ liệu thô khác.
  - `--output`: Thay đổi đường dẫn file manifest xuất ra.

---

### Bước 2: Phân Tách Cấu Trúc Cây Hàng Loạt (`batch-parse`)

Parse file văn bản thô `source.txt` thành cây cấu trúc luật (`Chương` -> `Mục` -> `Điều` -> `Khoản` -> `Điểm`) cho toàn bộ 1,850 văn bản trong `data/raw`:

```bash
uv run python -m src.pipeline.main batch-parse --workers 4
```

- **Đầu ra**: Lưu file cấu trúc tại `data/processed/<id>/hierarchy.json`.
- **Cơ chế Checkpoint**: Lệnh ghi nhận trạng thái tại `data/processed/batch_progress.json`. Nếu bị gián đoạn giữa chừng, chạy lại lệnh trên hệ thống sẽ tự động bỏ qua các văn bản đã thành công.
- **Chạy lại các văn bản từng lỗi**:
  ```bash
  uv run python -m src.pipeline.main batch-parse --retry-failed
  ```

---

### Bước 3: Trích Xuất Tri Thức LLM Hàng Loạt (`batch-extract`)

Gọi LLM trích xuất các thực thể pháp lý, định nghĩa, điều kiện áp dụng và các mốc dẫn chiếu giữa các văn bản:

```bash
uv run python -m src.pipeline.main batch-extract
```

- **Cơ chế Checkpoint cấp Điều (Article Checkpoint)**:
  Kết quả trích xuất từng Điều được ghi nối tiếp vào file `article_extractions.jsonl`. Nếu đứt mạng hoặc hết quota API, khi chạy lại hệ thống sẽ nhảy qua các Điều đã xong, bảo vệ chi phí API.

---

### Bước 4: Nạp Đồ Thị Neo4j & Vector Embedding (`batch-ingest`)

Nạp toàn bộ dữ liệu đã qua xác thực vào Neo4j Graph DB và sinh Vector Embedding `bge-m3` cho tìm kiếm ngữ nghĩa:

```bash
uv run python -m src.pipeline.main batch-ingest
```

---

## 3. Cơ Chế Crawl Trực Tiếp (Hybrid Crawler)

Khi cào một văn bản mới từ `luatvietnam.vn`, hệ thống **mặc định tự động kết hợp với VBPL** để đảm bảo đầy đủ thông tin nhất:

1. Tải chính văn chuẩn (`source.txt`) và metadata từ `luatvietnam.vn`.
2. Dùng Số hiệu văn bản (`number`) tìm kiếm trên `vbpl.vn`.
3. Bóc tách tab **Lược đồ** -> lưu file `diagram.json`.
4. Bóc tách tab **Thuộc tính** -> lưu file `properties.json`.

```bash
# Crawl 1 văn bản trực tiếp (Tự động lấy chính văn LuatVietnam + diagram & properties từ VBPL)
uv run python -m src.pipeline.main crawl \
  --url "https://luatvietnam.vn/doanh-nghiep/luat-doanh-nghiep-2020-so-59-2020-qh14-186272-d1.html" \
  --raw-doc-code LTV_186272 \
  --number "59/2020/QH14"
```

---

## 4. Theo Dõi Tiến Độ & Báo Cáo Sự Cố

### 4.1 Kiểm Tra File Trạng Thái Progress
File `data/processed/batch_progress.json` lưu giữ chi tiết trạng thái từng văn bản:

```json
{
  "LTV_101180": {
    "status": "SUCCESS",
    "last_step": "parse",
    "history": {
      "parse": {
        "status": "SUCCESS",
        "updated_at": "2026-08-06T00:22:01Z",
        "error": null
      }
    }
  }
}
```

### 4.2 Lọc Danh Sách Văn Bản Lỗi
Dùng lệnh Python nhanh để kiểm tra các văn bản bị lỗi parse/extract:

```bash
uv run python -c "
import json
with open('data/processed/batch_progress.json', 'r', encoding='utf-8') as f:
    data = json.load(f)
failed = [k for k, v in data.items() if v.get('status') == 'FAILED']
print(f'Tổng số văn bản bị lỗi: {len(failed)}')
print('Mẫu văn bản lỗi:', failed[:5])
"
```

---

## 5. Quản Lý Git & Ignore Dữ Liệu

Toàn bộ dữ liệu thô, kết quả phân tách, file manifest và registry sinh ra đều được cấu hình tự động trong `.gitignore` để không bị push nhầm lên Git repository:

```gitignore
# Runtime data (generated, not committed)
data/raw/
data/processed/
data/reports/
data/registry/
data/*.json
```
