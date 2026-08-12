# Hướng Dẫn Vận Hành Pipeline: Dataset LuatVietnam & Batch Processing Engine

> **Mục đích**: Hướng dẫn chi tiết cách vận hành Pipeline đơn lẻ (Single Ingest) và hàng loạt (Batch Ingest) cho tập dữ liệu văn bản pháp luật, cơ chế cào dữ liệu Luật Việt Nam kết hợp VBPL, tự động quy ước mã tên 26 hình thức văn bản, và cơ chế nạp Đồ thị Neo4j + BGE-M3 Vector Embeddings.

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

### 1.3 Vị Trí & Cấu Trúc Dữ Liệu Thô (Raw Data Location)

Để chạy luồng **Batch Ingest** (`batch-ingest-all`), toàn bộ các thư mục văn bản thô phải nằm tại thư mục:

📁 **`data/raw/`** *(tính từ gốc thư mục dự án `legal-graphrag-platform-vn`)*

Cấu trúc tổ chức thư mục dữ liệu thô bên trong `data/raw/`:
```text
<project_root>/data/raw/
├── TT94_2026/
├── L59_2020/
├── ND01_2021/
├── LTV_101180/
│   ├── source.txt        # [BẮT BUỘC] Nội dung chính văn bản
│   ├── metadata.json     # [BẮT BUỘC] Thông tin siêu dữ liệu (tiêu đề, số hiệu, ngày ban hành)
│   ├── source.html       # [TÙY CHỌN] HTML thô cào từ LuatVietnam
│   ├── diagram.json      # [TÙY CHỌN] Sơ đồ quan hệ cào bổ sung từ VBPL
│   └── properties.json   # [TÙY CHỌN] Thuộc tính cào bổ sung từ VBPL
└── ... (tổng cộng 1,850+ thư mục văn bản)
```

> **Lưu ý**: Mỗi thư mục văn bản chỉ cần có 2 file bắt buộc là `source.txt` và `metadata.json` là engine Batch đã đủ điều kiện tự động quét và xử lý thành công!

---

## 2. Luồng Chạy 1 Lệnh Duy Nhất (Single Command Execution)

Hệ thống hỗ trợ 2 lệnh chạy tổng hợp tự động từ A $\rightarrow$ Z mà không cần thực hiện nhiều câu lệnh lẻ:

### 2.1 Chạy 1 Văn bản Đơn lẻ từ URL (`ingest`)

Dùng khi bạn có 1 URL văn bản mới (trên `luatvietnam.vn` hoặc `vbpl.vn`) và muốn cào về nạp thẳng vào Neo4j:

```bash
uv run python -m src.pipeline.main ingest --url "https://luatvietnam.vn/thue/thong-tu-94-2026-tt-btc-quan-ly-tuan-thu-va-rui-ro-trong-quan-ly-thue-hieu-qua-439781-d1.html"
```

- **Tự động hóa hoàn toàn**:
  - Không bắt buộc truyền `--raw-doc-code` hay `--number` (hệ thống tự động bóc tách số hiệu và tự sinh mã thư mục chuẩn theo 26 loại hình thức văn bản như `TT94_2026`, `L59_2020`, `DT_...`).
  - Tự động cào chính văn `source.txt` và `metadata.json` từ Luật Việt Nam.
  - Tự động tìm kiếm số hiệu trên VBPL để cào bổ sung `diagram.json` / `properties.json` (nếu trên VBPL chưa có sẽ tự động bỏ qua an toàn).
  - Tự động chạy tuần tự: **Crawl $\rightarrow$ Parse $\rightarrow$ Extract LLM $\rightarrow$ Write Neo4j $\rightarrow$ Generate Embeddings**.

---

### 2.2 Chạy Hàng loạt cho Bộ Dữ liệu Có sẵn (`batch-ingest-all`)

Dùng khi bạn đã có sẵn tập hợp các thư mục văn bản trong `data/raw` và muốn xử lý toàn bộ tập dữ liệu vào Neo4j trong 1 lệnh:

```bash
# Chạy toàn bộ dataset
uv run python -m src.pipeline.main batch-ingest-all

# Thử nghiệm nhanh với 3 văn bản đầu tiên
uv run python -m src.pipeline.main batch-ingest-all --limit 3
```

- **Tự động chạy 6 bước liên hoàn**:
  1. **Tạo Manifest**: Quét `data/raw` và xuất file danh mục `luatvietnam_v1.json`.
  2. **Batch Parse**: Tách cây cấu trúc phân cấp đa luồng (`hierarchy.json`).
  3. **Batch Extract**: Gọi Gemini LLM trích xuất tri thức song song (có Checkpoint Resume).
  4. **Corpus Registry & Reconcile**: Đăng ký chỉ mục và đối soát các dẫn chiếu chéo liên văn bản.
  5. **Batch Write Neo4j**: Nạp tất cả Nút & Quan hệ vào Neo4j Graph DB.
  6. **Batch Generate Embeddings**: Sinh Vector BGE-M3 (1024 dims) inject vào Neo4j.

---

### 2.3 Chạy FULL PIPELINE Cho Một Thư Mục Tùy Chỉnh (`ingest-folder`)

Dùng khi bạn muốn chỉ định trực tiếp một thư mục chứa dữ liệu thô (ví dụ: `data/raw/LTV_366692` hoặc một thư mục bất kỳ bên ngoài) để chạy toàn bộ luồng Pipeline end-to-end:

```bash
# Chạy cho một thư mục văn bản tùy chỉnh
uv run python -m src.pipeline.main ingest-folder --folder "D:/path/to/your/folder"

# Hoặc dùng alias pipeline-folder
uv run python -m src.pipeline.main pipeline-folder --folder "data/raw/LTV_366692"

# Chạy thử nghiệm N văn bản đầu tiên trong thư mục
uv run python -m src.pipeline.main ingest-folder --folder data/raw --limit 5

# Bắt buộc chạy lại các văn bản từng lỗi / chưa xong
uv run python -m src.pipeline.main ingest-folder --folder data/raw/LTV_186730 --retry-failed
```

- **Đặc điểm nổi bật**:
  - Hỗ trợ linh hoạt cả **thư mục cha chứa nhiều văn bản** (như `data/raw`) lẫn **thư mục của 1 văn bản đơn lẻ** (như `data/raw/LTV_366692`).
  - Tự động tạo file `manifest.json` trong thư mục được chỉ định.
  - Tự động thực hiện 6 bước liên hoàn: **Manifest $\rightarrow$ Parse $\rightarrow$ LLM Extract $\rightarrow$ Reconcile $\rightarrow$ Write Neo4j $\rightarrow$ BGE-M3 Embeddings**.

---

## 3. Bảng Quy Ước Tiền Tố (Prefix) Cho Đầy Đủ 26 Hình Thức Văn Bản VBPL

Hệ thống tự động bóc tách loại văn bản từ số hiệu hoặc tiêu đề và quy ước tiền tố chuẩn hóa tên thư mục (`raw_doc_code`) cho toàn bộ 26 loại hình thức văn bản của CSDL Quốc gia VBPL:

| STT | Hình thức văn bản (VBPL) | Tiền tố (Prefix) | Ví dụ mã tự sinh |
| :--- | :--- | :--- | :--- |
| 1 | **Hiến pháp** | `HP` | `HP01_2013` |
| 2 | **Bộ luật** | `BL` | `BL45_2019` |
| 3 | **Luật** | `L` | `L59_2020` |
| 4 | **Pháp lệnh** | `PL` | `PL02_2022` |
| 5 | **Nghị định** | `ND` | `ND01_2021` |
| 6 | **Nghị quyết** | `NQ` | `NQ01_2021` |
| 7 | **Nghị quyết liên tịch** | `NQLT` | `NQLT01_2021` |
| 8 | **Quyết định** | `QD` | `QD01_2021` |
| 9 | **Thông tư** | `TT` | `TT01_2021` |
| 10 | **Thông tư liên tịch** | `TTLT` | `TTLT01_2021` |
| 11 | **Lệnh** | `LENH` | `LENH01_2021` |
| 12 | **Chỉ thị** | `CT` | `CT01_2021` |
| 13 | **Quy chế** | `QC` | `QC01_2021` |
| 14 | **Quy định** | `QDINH` | `QDINH01_2021` |
| 15 | **Công văn** | `CV` | `CV123_2022` |
| 16 | **Công điện** | `CD` | `CD05_2023` |
| 17 | **Tờ trình** | `TTR` | `TTR10_2022` |
| 18 | **Thông báo** | `TB` | `TB50_2023` |
| 19 | **Hướng dẫn** | `HD` | `HD02_2022` |
| 20 | **Văn bản hợp nhất** | `VBHN` | `VBHN01_2023` |
| 21 | **Văn bản hệ thống hóa** | `HTH` | `HTH01_2023` |
| 22 | **Văn bản hành chính liên quan** | `HCKL` | `HCKL01_2023` |
| 23 | **Bản dịch văn bản** | `BD` | `BD01_2023` |
| 24 | **Dự thảo** | `DT` | `DT_du_thao_luat_dat_dai_1723315200` |
| 25 | **Kế hoạch / Đề án** | `KH` | `KH01_2023` |
| 26 | **Báo cáo / Biên bản** | `BC` | `BC01_2023` |

---

## 4. Cơ Chế Crawl Hybrid & Xử Lý An Toàn

Khi chạy cào một văn bản từ Luật Việt Nam:
1. **Dữ liệu bắt buộc**: Tải chính văn `source.txt` và `metadata.json` từ Luật Việt Nam.
2. **Dữ liệu bổ sung từ VBPL**: Dùng Số hiệu văn bản tra cứu sang `vbpl.vn` để bóc tách `diagram.json` (sơ đồ quan hệ) và `properties.json` (bảng thuộc tính).
3. **Cơ chế Graceful Fallback**: Nếu tìm kiếm số hiệu trên `vbpl.vn` không thấy (hoặc văn bản mới chưa cập nhật lên VBPL) $\rightarrow$ Hệ thống tự động log warning và bỏ qua VBPL, bảo toàn dữ liệu `source.txt` + `metadata.json` để tiếp tục xử lý các bước downstream.

---

## 5. Bảng Tra Cứu Câu Lệnh CLI Nhanh

| Mục đích | Câu lệnh CLI |
| :--- | :--- |
| **Ingest đơn lẻ 1 URL** | `uv run python -m src.pipeline.main ingest --url "<URL>"` |
| **Batch Ingest toàn bộ `data/raw`** | `uv run python -m src.pipeline.main batch-ingest-all` |
| **Ingest FULL PIPELINE cho 1 thư mục bất kỳ** | `uv run python -m src.pipeline.main ingest-folder --folder "<PATH>"` |
| **Ingest FULL PIPELINE test N bài** | `uv run python -m src.pipeline.main ingest-folder --folder "<PATH>" --limit 5` |
| **Chạy lại các bài bị lỗi / ép chạy lại LLM** | `uv run python -m src.pipeline.main ingest-folder --folder "<PATH>" --retry-failed` |
| **Kiểm tra trợ giúp** | `uv run python -m src.pipeline.main --help` |

