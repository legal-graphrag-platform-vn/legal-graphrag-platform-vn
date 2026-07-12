# Legal GraphRAG VN — Graph Construction Pipeline (Milestone 1 + 2)

Crawler (vbpl.vn) → Hierarchy Parser (Chương/Điều/Khoản/Điểm) → LLM Extraction
(Gemini, two-pass) → Schema/Ontology Validation → Confidence Scoring → Decision
Gate. Xem [`REPORT.md`](REPORT.md) cho thiết kế chi tiết, lý do kỹ thuật, và
data flow đầy đủ.

## Quick start

Chạy các lệnh dưới đây từ **repo root** để Python resolve package `src` đúng
sau khi pipeline được merge vào monorepo.

```bash
uv sync --group dev
python -m playwright install chromium
cp src/pipeline/.env.example .env   # điền GEMINI_API_KEY — xem hướng dẫn lấy key bên dưới

uv run python -m src.pipeline.main crawl --url "https://vbpl.vn/van-ban/chi-tiet/luat-doanh-nghiep-so-59-2020-qh14--142881" \
    --raw-doc-code L59_2020 --number "59/2020/QH14"
uv run python -m src.pipeline.main validate-data --raw-doc-code L59_2020
uv run python -m src.pipeline.main parse --raw-doc-code L59_2020
uv run python -m src.pipeline.main extract --raw-doc-code L59_2020   # cần GEMINI_API_KEY
uv run python -m src.pipeline.main normalize-extraction --raw-doc-code L59_2020
uv run python -m src.pipeline.main validate-payload --raw-doc-code L59_2020
uv run python -m src.pipeline.main write --raw-doc-code L59_2020
uv run python -m src.pipeline.main embed --raw-doc-code L59_2020
uv run python -m src.pipeline.main graph-quality --raw-doc-code L59_2020

uv run python -m pytest src/pipeline/tests/ -v
```

## Parse từ raw text

Luồng hiện tại không parse PDF trực tiếp. `parse` đọc raw text đã crawl ở
`data/raw/<doc_id>/source.txt` và metadata đi kèm ở `metadata.json`.

```bash
uv run python -m src.pipeline.main crawl --url "https://vbpl.vn/van-ban/chi-tiet/luat-doanh-nghiep-so-59-2020-qh14--142881" \
    --raw-doc-code L59_2020 --number "59/2020/QH14"
uv run python -m src.pipeline.main parse --raw-doc-code L59_2020
```

Nếu muốn parse một file `.txt` riêng, thư mục raw tương ứng vẫn phải có
`metadata.json` hợp lệ và pass `validate-data`:

```bash
uv run python -m src.pipeline.main parse --raw-doc-code L59_2020 --txt data/custom/source.txt
```

Không có `--pdf`, `--backend pypdf`, hay OCR fallback trong CLI hiện tại.

## Lấy Gemini API key

1. Vào https://aistudio.google.com/apikey
2. Đăng nhập Google, bấm "Create API key"
3. Dán vào `.env`: `GEMINI_API_KEY=<key của bạn>`

Không có key vẫn chạy được `crawl`/`parse`; `extract`/`ingest` sẽ báo lỗi rõ ràng

Với Gemini free tier, giữ `GEMINI_MIN_REQUEST_INTERVAL_SECONDS=7.0` và
`EXTRACTION_MAX_WORKERS=1`. Lỗi 429 tạm thời được retry với exponential backoff;
429 sau khi hết retry vẫn chặn Gate 2 thay vì tạo extraction artifacts hợp lệ giả.

Extraction lưu raw output theo từng Điều trong `article_extractions.jsonl`.
Checkpoint hợp lệ được reuse theo graph/context/provider/model/prompt fingerprint,
vì vậy lỗi provider giữa chừng không bắt chạy lại các Điều đã hoàn tất.

Trước full run, chạy smoke 3-5 Điều bằng full hierarchy registry:

```bash
uv run python -m src.pipeline.main extract \
  --raw-doc-code L59_2020 \
  --articles 5,13,53,171,215
```

Smoke artifacts có `extraction_run.complete_document=false` và bị Gate 2/write
reject. Full run sau đó reuse các Article checkpoints đã hoàn tất.

`normalize-extraction` chạy lại endpoint normalization, validation, scoring và
decision artifacts từ checkpoint mà không gọi LLM. Structural IDs trong accepted
records phải là canonical IDs từ `hierarchy.json`; LLM `CONTAINS` luôn bị reject.

Trước khi thay một extraction run không hợp lệ, archive bằng:

```bash
uv run python -m src.pipeline.main archive-extraction --raw-doc-code L59_2020
```
ngay lập tức nếu thiếu key.

Chi tiết đầy đủ (thách thức thực tế, quyết định kỹ thuật, code walkthrough): xem
[`REPORT.md`](REPORT.md).
