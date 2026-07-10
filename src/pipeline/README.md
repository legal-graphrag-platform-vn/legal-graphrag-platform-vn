# Legal GraphRAG VN — Graph Construction Pipeline (Milestone 1 + 2)

Crawler (vbpl.vn) → Hierarchy Parser (Chương/Điều/Khoản/Điểm) → LLM Extraction
(Gemini, two-pass) → Schema/Ontology Validation → Confidence Scoring → Decision
Gate. Xem [`REPORT.md`](REPORT.md) cho thiết kế chi tiết, lý do kỹ thuật, và
data flow đầy đủ.

## Quick start

```bash
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env   # điền GEMINI_API_KEY — xem hướng dẫn lấy key bên dưới

python main.py crawl --url "https://vbpl.vn/van-ban/chi-tiet/luat-doanh-nghiep-so-59-2020-qh14--142881" \
    --doc-id LDN2020 --number "59/2020/QH14"
python main.py parse --doc-id LDN2020
python main.py extract --doc-id LDN2020   # cần GEMINI_API_KEY

python -m pytest tests/ -v
```

## Parse từ raw text

Luồng hiện tại không parse PDF trực tiếp. `parse` đọc raw text đã crawl ở
`data/raw/<doc_id>/source.txt` và metadata đi kèm ở `metadata.json`.

```bash
python main.py crawl --url "https://vbpl.vn/van-ban/chi-tiet/luat-doanh-nghiep-so-59-2020-qh14--142881" \
    --doc-id LDN2020 --number "59/2020/QH14"
python main.py parse --doc-id LDN2020
```

Nếu muốn parse một file `.txt` riêng, dùng `--txt` cùng `--doc-id`:

```bash
python main.py parse --doc-id LDN2020 --txt data/custom/source.txt \
    --number "59/2020/QH14" --title "Luật Doanh nghiệp 2020"
```

Không có `--pdf`, `--backend pypdf`, hay OCR fallback trong CLI hiện tại.

## Lấy Gemini API key

1. Vào https://aistudio.google.com/apikey
2. Đăng nhập Google, bấm "Create API key"
3. Dán vào `.env`: `GEMINI_API_KEY=<key của bạn>`

Không có key vẫn chạy được `crawl`/`parse`; `extract`/`ingest` sẽ báo lỗi rõ ràng
ngay lập tức nếu thiếu key.

Chi tiết đầy đủ (thách thức thực tế, quyết định kỹ thuật, code walkthrough): xem
[`REPORT.md`](REPORT.md).
