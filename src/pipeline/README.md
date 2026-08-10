# Legal GraphRAG VN — Graph Construction Pipeline (Milestone 1 + 2)

Crawler (vbpl.vn) → Hierarchy Parser (Chương/Mục/Điều/Khoản/Điểm) → LLM Extraction
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

`Mục` is persisted as `Section` under its `Chapter` when the canonical source
contains a verified heading and legal title. Existing processed artifacts do
not migrate automatically: re-run `parse`, normalization, payload validation,
and `write` for curated ready documents. The write command verifies each new
`Chapter -> Section -> Article` chain before removing its exact legacy direct
`Chapter -> Article` edge.

A `Chapter` may also retain direct preamble Articles before its first `Section`.
The parser and payload consistency validator reject the mixed structure if any
direct Article number is at or after the first Article contained by a Section.

## Dẫn chiếu cấu trúc liên văn bản

Sau khi toàn bộ văn bản nguồn và đích đã chạy `validate-payload` rồi `write`, tạo
registry bất biến từ đúng các payload đã qua root validation:

```bash
uv run python -m src.pipeline.main build-reference-registry \
  --build-id registry-v17-20260731-001 \
  --raw-doc-code L59_2020 \
  --raw-doc-code L68_2014 \
  --raw-doc-code TT01_2021
```

Có thể thay danh sách lặp bằng `--manifest configs/corpus/curated_v1.json`, nhưng
không dùng đồng thời hai kiểu chọn. Build thất bại toàn bộ nếu một document thiếu
source hoặc payload chưa hợp lệ. Output gồm `build_id`, `snapshot_hash` và
`provenance_hash`; registry không được xây từ manifest/crawl metadata đơn thuần.

Resolve trước ở dry-run (không mở Neo4j, không gọi LLM):

```bash
uv run python -m src.pipeline.main reconcile-external-references \
  --build-id registry-v17-20260731-001 \
  --raw-doc-code TT01_2021

uv run python -m src.pipeline.main reference-status \
  --raw-doc-code TT01_2021
```

Khi checkpoint đã đúng, materialize các bundle đã xác minh:

```bash
uv run python -m src.pipeline.main reconcile-external-references \
  --build-id registry-v17-20260731-001 \
  --raw-doc-code TT01_2021 \
  --apply
```

Writer chỉ `MATCH` source/target đã tồn tại và chỉ `MERGE` cạnh `REFERS_TO`.
Mỗi bundle chạy trong một Neo4j transaction; sau commit, attempt ledger được
append + fsync trước khi checkpoint được CAS sang `WRITTEN`. Target thiếu, sai
ownership, mơ hồ hoặc xung đột target cũ không tạo node/cạnh giả.

Ontology v1.9.0 còn nhận `DIAGRAM` như nguồn deterministic cho quan hệ
Document-level `AMENDS`, `REPEALS`, `REPLACES`, và `GUIDES`. Diagram category
phải map bằng bảng explicit, target phải resolve qua canonical registry, và
relation vẫn phải qua required-property, temporal, whitelist và consistency
validation trước decision gate. Builder không tự gắn validity. Temporal relation
chỉ dùng ngày của current document khi document đó là acting head; external head
thiếu ngày hoặc target chưa resolve đi blocking review và không được materialize.
`DIAGRAM` không phải extraction method hợp lệ của `REFERS_TO`.

## Parse từ raw text

Luồng hiện tại không parse PDF trực tiếp. `parse` đọc raw text đã crawl ở
`data/raw/<doc_id>/source.txt` và metadata đi kèm ở `metadata.json`.
Crawler giữ nguyên toàn bộ chính văn, gồm phần mở đầu, lời dẫn, chữ ký và nơi
nhận; chỉ loại phần điều hướng của website và mục lục được nối sau toàn văn.

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
