# Legal GraphRAG VN — Graph Construction Pipeline (Milestone 1 + 2)

Crawler (vbpl.vn) → Hierarchy Parser (Chương/Mục/Điều/Khoản/Điểm) → LLM Extraction
(Gemini, two-pass) → Schema/Ontology Validation → Confidence Scoring → Decision
Gate. Xem [`REPORT.md`](REPORT.md) cho thiết kế chi tiết, lý do kỹ thuật, và
data flow đầy đủ; xem [`ARCHITECTURE.md`](ARCHITECTURE.md) cho tổng quan
kiến trúc component (module, CLI, kiểm chứng test).

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
uv run python -m src.pipeline.main embed --raw-doc-code L59_2020 --dry-run
uv run python -m src.pipeline.main embed --raw-doc-code L59_2020
uv run python -m src.pipeline.main graph-quality --raw-doc-code L59_2020

uv run python -m pytest src/pipeline/tests/ -v
```

`Mục` is persisted as `Section` under its direct canonical parent: `Document`,
`Part`, or `Chapter`, when the canonical source contains a verified heading and
legal title. Existing processed artifacts do
not migrate automatically: re-run `parse`, normalization, payload validation,
and `write` for curated ready documents. The write command verifies each new
`Chapter -> Section -> Article` chain before removing its exact legacy direct
`Chapter -> Article` edge.

Ontology 1.13.0 persists an explicit full-line `Phụ lục` as `Appendix` under its
Document. Supported designators include Roman/Arabic/letter codes and compound
forms such as `I-1` or `01/TĐG`; any Article/Clause parsed inside uses the
Appendix ID as its canonical prefix. Inline references to a Phụ lục do not open
a new scope. Form/list/table content remains on the Appendix node unless source
structure proves citable Articles. A trailing `MỤC LỤC` is retained only as a
`TABLE_OF_CONTENTS` parser artifact and never creates Neo4j data.

Ontology 1.14.0 persists an evidenced `Quy chế`, `Quy định`, `Điều lệ`, or
`Chuẩn mực` ban hành kèm as `AttachedInstrument`. The parser requires a full-line
controlled heading plus a nearby `ban hành kèm theo` line; its Articles use an
AttachedInstrument-scoped canonical ID and no longer collide with host Articles.
The ownership node itself is not embedded in Phase 1; Article/Clause descendants
remain the retrieval and citation units.

A `Chapter` may also retain direct preamble Articles before its first `Section`.
The parser and payload consistency validator reject the mixed structure if any
direct Article number is at or after the first Article contained by a Section.

Trước một đợt nạp hoặc cập nhật corpus lớn, chạy `embed --dry-run` cho từng
document đã write. Lệnh này kiểm tra ba vector index đang `ONLINE`, dimension
khớp BGE-M3/1024, và báo số Appendix/Article/Clause stale theo content hash + provenance;
nó không tải embedding model và không ghi Neo4j. Chỉ chạy `embed` không có
`--dry-run` sau khi readiness report đúng với phạm vi dữ liệu dự kiến.

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

Ontology v1.14.0 còn nhận `DIAGRAM` như nguồn deterministic cho quan hệ
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

Không truyền `--raw-doc-code` thì lệnh `parse` xử lý mọi thư mục con trong
`data/raw/` có đủ `source.txt` và `metadata.json`; curated manifest không giới
hạn batch parse. Mỗi `hierarchy.json` chứa `parser_metadata` với parser version,
SHA-256 của canonical source, trạng thái, số lượng đơn vị và các warning có tọa độ nguồn. Parser chỉ coi heading nằm
trong dấu ngoặc kép là nội
dung nhúng khi đó là một block sửa đổi/bổ sung tường minh và block đã đóng.
Dấu ngoặc lỗi không được phép nuốt các heading `Điều` còn lại. Nếu không nhận
diện được `Điều`, hoặc hierarchy không qua validation, canonical body được giữ
trong `unparsed_sections` với loại `UNPARSED_BODY`; phần này không trở thành node
ontology và phải được xử lý lại trước extraction/write.

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

Với raw bundle LuatVietnam, `parse` còn tạo
`provider_relation_candidates.jsonl`. Sau batch parse, candidate được rebuild
một lần từ toàn bộ hierarchy đã tồn tại để kết quả không phụ thuộc thứ tự worker.
Khi `extract` hoặc `normalize-extraction` chạy, candidate `RESOLVED` thuộc
`AMENDS`/`REPEALS`/`REFERS_TO` được chuyển thành deterministic record rồi đi qua
schema, ontology, consistency và decision gate hiện có. `REFERS_TO` dùng
`ENTITY_LINKING`; span dấu ngoặc vuông thuộc provider và bị loại khỏi generic
structural resolver, kể cả khi provider candidate chưa resolve. Ngày
`effective_from` ưu tiên
metadata đã xác thực; khi metadata thiếu mới lấy câu hiệu lực rõ ràng trong
canonical `source.txt`; không dùng ngày ban hành thay ngày hiệu lực. Candidate unresolved, ambiguous và
positional anchor vẫn chỉ nằm trong sidecar. Relation liên-document accepted có
`materialization_route=CORPUS_RELATION_RECONCILIATION`; payload builder một
document defer relation này để không tạo dangling endpoint hoặc node giả. Batch
write toàn bộ endpoint trước rồi mới chạy corpus reconciliation. Reconciliation
materialize provider `REFERS_TO` theo một checkpoint cho toàn bundle; mọi target
được kiểm chứng và commit trong cùng transaction.

Provider target còn phải khớp số hiệu văn bản xuất hiện tường minh trong
`citation_text`. Nếu HTML trỏ sang một văn bản nhưng phần chữ hiển thị ghi số
hiệu khác, candidate chuyển thành `UNRESOLVED` với
`provider_text_target_conflict`; pipeline không tin ngầm provider ID và cũng
không cho generic resolver tìm lại bằng text.

Sau decision gate, reconciliation materialize các candidate
`AMENDS`/`REPEALS` có đúng một target bằng relation-only writer: endpoint được
đối chiếu lại với registry và graph trước khi `MERGE`, còn `relation_id` giữ ổn
định để rerun idempotent. Candidate thiếu record `accepted` không được ghi.
Candidate `PROJECTED` dùng dual provenance: canonical source thuộc amended
document, còn host document/unit/span và governing candidate được lưu riêng.
Sidecar v1 thiếu `projection_basis_candidate_id` vẫn fail closed và phải rebuild.
Nội dung được bổ sung sau/trước một positional anchor chỉ được mở lại khi đơn vị
mới đã có canonical node trong corpus; anchor cũ không bao giờ được dùng thay
legal source của nội dung mới.

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
Lệnh này cũng yêu cầu hierarchy có canonical source spans hợp lệ cho mọi Article
được chọn. Artifact cũ thiếu spans sẽ bị chặn và phải chạy lại `parse` trước;
normalizer không được giữ lại LLM structural reference chỉ vì deterministic
resolver không có tọa độ nguồn để chạy.
Nếu resolver xác định cùng source unit và citation mention, relation deterministic
sẽ thay thế proposal `REFERS_TO` của LLM kể cả khi LLM chọn target rộng hơn như
Article thay vì Clause.

Trước khi thay một extraction run không hợp lệ, archive bằng:

```bash
uv run python -m src.pipeline.main archive-extraction --raw-doc-code L59_2020
```
ngay lập tức nếu thiếu key.

Chi tiết đầy đủ (thách thức thực tế, quyết định kỹ thuật, code walkthrough): xem
[`REPORT.md`](REPORT.md).
