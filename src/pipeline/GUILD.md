# Hướng Dẫn Chạy Pipeline

- **Bước 1: Cào dữ liệu từ vbpl.vn (Crawl)**
  - **Cào từ 1 link cụ thể (Crawl Link)**:
    - Lệnh chạy: `python main.py crawl --url "<url>" --doc-id <doc_id> --number "<so_hieu>"`
    - Ví dụ: `python main.py crawl --url "https://vbpl.vn/van-ban/chi-tiet/nghi-dinh-so-01-2021-nd-cp--142881" --doc-id ND01_2021 --number "01/2021/NĐ-CP"`
    - Đầu ra: Lưu tại `data/raw/<doc_id>/source.txt` và `metadata.json`
  
  - **Cào hàng loạt dựa trên tìm kiếm (Crawl All)**:
    - Lệnh chạy: `python main.py crawl-search --query "<từ_khóa>" [--limit <số_lượng>]`
    - Ví dụ: `python main.py crawl-search --query "Luật Doanh nghiệp" --limit 5`
    - *Tính năng tự động*: Tìm kiếm trong **Tiêu đề**, bật chế độ khớp **Chính xác cụm từ trên**, tự động phân trang nếu kết quả vượt quá trang đầu, tự sinh `doc_id` và cào hàng loạt lưu về `data/raw/<doc_id>/`.

- **Bước 2: Phân tích cấu trúc luật (Parse)**
  - **Parse 1 thư mục cụ thể (Parse 1)**:
    - Lệnh chạy: `python main.py parse --doc-id <doc_id>`
    - Ví dụ: `python main.py parse --doc-id LDN2020`
    - *Đặc điểm*: Tự động đọc dữ liệu từ `data/raw/<doc_id>/source.txt` và `metadata.json` để phân tích (không cần điền số hiệu hay tiêu đề).
  
  - **Parse hàng loạt tất cả thư mục (Parse All)**:
    - Lệnh chạy: `python main.py parse` (không truyền `--doc-id` và `--txt`)
    - *Đặc điểm*: Tự động quét toàn bộ thư mục con trong `data/raw/` (yêu cầu thư mục có đủ file `source.txt` và `metadata.json`), chạy song song đa luồng (multi-threaded) cực nhanh, tự động ghi đè dữ liệu cũ nếu trùng tên.

  - **Parse từ file text (.txt) tự chọn**:
    - Lệnh chạy: `python main.py parse --doc-id <doc_id> --txt <path> --number "<so_hieu>" --title "<tieu_de>"`
    - Đầu ra cấu trúc lưu tại: `data/processed/<doc_id>/hierarchy.json`

- **Bước 3: Trích xuất AI (LLM Extraction)**
  - Cấu hình file `.env`: Chọn `LLM_PROVIDER` là `gemini`, `minimax`, `qwen`, hoặc `openai` và điền API key.
  - Lệnh chạy: `python main.py extract --doc-id <doc_id>`
  - Kết quả lưu tại: `data/processed/<doc_id>/{accepted,review_queue,rejected}.jsonl`

- **Chạy tự động toàn bộ luồng đơn lẻ (Crawl -> Parse -> AI):**
  - Lệnh chạy: `python main.py ingest --url "<url>" --doc-id <doc_id> --number "<so_hieu>"`

