# REPORT — Graph Construction Pipeline (Milestone 1 + 2)

**Phạm vi đã build**: Crawler → Hierarchy Parser → LLM Extraction → Schema/Ontology
Validation → Confidence Scoring → Decision Gate (accepted/review/rejected JSONL).
**Ngoài phạm vi**: Neo4j Writer, Embedding (Milestone 3).

Văn bản test: **Luật Doanh nghiệp 2020 (59/2020/QH14)**, crawl trực tiếp từ
[vbpl.vn](https://vbpl.vn/van-ban/chi-tiet/luat-doanh-nghiep-so-59-2020-qh14--142881).

---

## A. Bài toán & Thách thức thực tế

### A1. Crawler: vbpl.vn không phải trang server-rendered như giả định ban đầu

Giả định lúc lập kế hoạch: vbpl.vn là ASP.NET WebForms, server-rendered HTML, chỉ
cần `httpx` + `BeautifulSoup`. Thực tế khi `curl` trang thật: **vbpl.vn là Next.js
App Router SPA** (client/RSC-rendered) — response HTML thô chỉ là một shell rỗng,
nội dung thật được JS dựng sau khi load. `httpx.get()` trả về HTML không chứa nội
dung văn bản.

**Giải quyết**: chuyển sang Playwright (headless Chromium), `wait_until="networkidle"`
+ một khoảng `wait_timeout` ngắn để JS render xong rồi mới đọc `page.inner_text("body")`.

Vấn đề tiếp theo: request headless mặc định (`browser.new_page()`) bị WAF chặn,
trả về trang "Web Page Blocked! Attack ID: 20000051". **Giải quyết**: tạo
`browser.new_context()` với `user_agent` trình duyệt thật, `viewport`, và
`locale="vi-VN"` thay vì dùng context mặc định — WAF có vẻ chặn dựa trên
fingerprint thiếu các header/properties của trình duyệt thật, không phải chặn
headless tuyệt đối.

### A2. Nút "Tải về" (PDF) bị chặn sau reCAPTCHA — không có PDF tự động hoá được

Bắt network requests trong lúc Playwright load trang chỉ thấy các request liên
quan Google reCAPTCHA, không có endpoint PDF/API lộ ra. Nút "Tải về" trên vbpl.vn
được gate bởi reCAPTCHA vô hình — **không thử bypass captcha** (ngoài phạm vi đạo
đức/kỹ thuật cho phép của task này).

**Quyết định kiến trúc quan trọng**: thay vì tải PDF, crawler trích xuất trực
tiếp **toàn bộ text nội dung văn bản** đã có sẵn trong DOM ở tab "Nội dung" (tab
mặc định khi trang load xong) — nội dung đầy đủ, đúng cấu trúc Chương/Điều/Khoản/
Điểm, không cần OCR hay xử lý PDF gì thêm. Output của crawler là `source.txt`
thay vì `source.pdf`. Module `parser/hierarchy_parser.py` vẫn giữ nguyên 2 entry
point: `parse_text()` (dùng cho crawler output, đã test với fixture + dữ liệu
thật) và `parse_pdf()`/PyMuPDF (giữ nguyên cho trường hợp người dùng cung cấp PDF
thủ công — vẫn đúng yêu cầu M1 "lấy 1 file PDF thủ công").

### A3. Bóc tách ranh giới Chương/Điều/Khoản/Điểm trên dữ liệu thật

Chạy `parse_text()` trên toàn văn Luật Doanh nghiệp 2020 (6042 dòng text crawl
được) cho ra đúng **218 Điều** — khớp số lượng điều thật của luật này. Heuristic
"dòng toàn chữ hoa sau dòng `Chương X`" hoạt động tốt trên dữ liệu thật vì vbpl.vn
giữ định dạng gốc (chương title luôn đứng riêng dòng, in hoa).

Phát hiện thú vị (chưa xử lý, ghi nhận cho M3): vbpl.vn chèn marker
`"Điều khoản được sửa đổi, bổ sung"` làm dòng riêng ngay trước các khoản đã bị
sửa đổi bởi văn bản khác — đây là tín hiệu có sẵn, miễn phí, rất hữu ích để tự
động hoá việc dựng quan hệ `AMENDED_BY` ở Milestone 3, nhưng pipeline hiện tại
(M1+M2) chưa khai thác tín hiệu này — parser hiện coi đó là một dòng nội dung
bình thường (không match Điều/Khoản/Điểm nên bị nối vào content liền trước).

### A4. LLM JSON schema / hallucination

**Chưa đo được trên dữ liệu thật** — môi trường hiện tại chưa có `GEMINI_API_KEY`
(người dùng xác nhận chưa có key, sẽ tự lấy và set vào `.env` — xem mục C). Pipeline
extraction (`extract_entities`/`extract_relations`) đã được verify fail-fast đúng
cách khi thiếu key (raise `RuntimeError` rõ ràng ngay từ `config.py`, không để lỗi
mơ hồ rơi xuống tận lúc gọi API), và đã unit-test cấu trúc Pydantic model +
`response_schema` ép kiểu. Khi có key, tỉ lệ JSON parse fail / loại hallucination
phổ biến cần được đo và điền vào mục này.

### A5. `IMPLEMENTED_BY` rule `head.level > tail.level` — giới hạn đã biết

Rule cần biết `doc_type` (qua đó suy ra level) của CẢ HAI văn bản trong quan hệ —
nhưng ở M1+M2 không có document registry (đó là việc của Neo4j ở M3). Orchestrator
hiện tại (`pipeline/orchestrator.py`) chỉ suy ra level khi entity type là chính
document đang xử lý; còn lại level=`None` khiến `IMPLEMENTED_BY` luôn bị
`ontology_validator` reject và rơi vào review queue thay vì bị auto-accept sai —
đây là hành vi an toàn có chủ đích, không phải bug, nhưng có nghĩa hiện tại mọi
quan hệ `IMPLEMENTED_BY` sẽ không bao giờ auto-accept cho tới khi có document
registry ở M3.

### A6. PDF gốc tải tay từ vbpl.vn là bản scan — phải dùng OCR, độ chính xác chỉ ~43%

Giả định ban đầu trong B1 ("văn bản từ vbpl.vn có text layer, không phải bản scan")
**sai** khi kiểm tra trên PDF thật. Người dùng tải tay `VanBanGoc_59.signed.pdf`
(70 trang, link "Tải về" trên vbpl.vn — bị reCAPTCHA chặn tự động hoá, xem A2) và
kiểm tra bằng PyMuPDF: cả 70 trang chỉ có 1 ảnh/trang, 0 ký tự text thật (trừ
trang 1 có 147 ký tự — chỉ là metadata chữ ký số "Ký bởi: Cổng Thông tin điện tử
Chính phủ..."). `extract_lines_with_font()` (vốn dùng cho route PDF có text layer)
chỉ trả về 4 dòng — không dùng được.

Đã thêm `extract_lines_via_ocr()` (Tesseract qua `pytesseract`, `lang="vie"`) và
`parse_pdf()` tự phát hiện PDF scan (đo số ký tự trích được trung bình/trang, dưới
ngưỡng 50 thì tự fallback OCR) — không cần người dùng tự chọn route.

**Kết quả thực tế trên `VanBanGoc_59.signed.pdf`**: OCR chỉ nhận diện đúng
**93–98/218 Điều** (tuỳ tham số, ~43-45% recall) so với route crawler (HTML text từ
vbpl.vn, không qua OCR) cho ra **218/218 Điều chính xác tuyệt đối**. Nguyên nhân
gốc: Tesseract đôi khi đọc nhầm hẳn ký tự "Điều" thành chuỗi rác hoàn toàn không
liên quan (vd `Điều 3.` → `l)1eu 3.` — log thực tế khi debug), không phải lỗi
regex/parser — quan sát được bằng cách dump raw OCR text và đối chiếu thủ công.
Đã thử 2 cách cải thiện:
1. Tăng DPI render trang 300→400 + tiền xử lý ảnh (`ImageOps.grayscale` +
   `autocontrast`) trước khi OCR, đổi `--psm 6` (giả định block text đồng nhất).
2. Nới `ARTICLE_RE`/`patterns.py` chấp nhận tối đa 2 ký tự rác đứng trước "Điều"
   (OCR hay chèn dấu `'`/ký tự lạ ở đầu dòng tiêu đề).

Cả hai chỉ cải thiện biên độ nhỏ (98→93 Điều, đổi loại lỗi chứ không giảm hẳn) —
giới hạn nằm ở chất lượng nhận diện ký tự gốc của Tesseract trên bản scan nén/độ
phân giải thấp, không phải lỗi logic có thể sửa thêm trong scope hiện tại.
**Quyết định**: giữ cả 2 route song song — **crawler (HTML) là nguồn chính thức,
chính xác**, OCR chỉ dùng khi không có route HTML (PDF scan độc lập, không qua
vbpl.vn crawl). Không xoá/sửa crawler theo yêu cầu của người dùng.

### A7. Test với PDF text layer thật (`pypdf`) — phát hiện bug regex từ A6 gây false positive

Người dùng cung cấp `LDN762025QH15.pdf` (Luật sửa đổi, bổ sung một số điều của
Luật Doanh nghiệp, 76/2025/QH15) — PDF có text layer thật (bôi đen/copy được),
xác nhận bằng `pypdf.PdfReader.extract_text()`: 7 trang, text sạch ngay từ đầu,
không cần OCR. Thêm backend `extract_lines_via_pypdf()` + `parse_pdf(..., backend="pypdf")`.

Lần chạy đầu tiên cho ra **4 Điều** thay vì đúng **3 Điều** (văn bản sửa đổi chỉ có
Điều 1/Điều 2/Điều 3) — root cause: regex `ARTICLE_RE` đã bị nới lỏng ở A6 để chịu
rác OCR (`'Điều 7.` → chấp nhận 1-2 ký tự rác trước "Điều") vô tình khớp luôn dòng
trích dẫn nguyên văn lồng trong dấu ngoặc kép `"Điều 25. ..."` (Điều 1 khoản 11 trích
dẫn tên Điều mới của Điều 25 trong Luật gốc) → bị tách nhầm thành Điều cấp cao mới,
gãy cấu trúc. **Bug này lẽ ra sẽ không bị phát hiện nếu chỉ test trên văn bản gốc
LDN2020** (không có cấu trúc trích dẫn lồng) — chính nhờ test thêm loại văn bản
"sửa đổi, bổ sung" mới lộ ra.

**Fix**: tách riêng `ARTICLE_RE` (chặt, dùng cho text layer thật) và
`ARTICLE_RE_LENIENT` (lỏng, chỉ dùng cho dòng lấy từ OCR) trong `patterns.py`;
`parse_lines(lines, lenient_article=...)` chỉ bật lỏng khi `parse_pdf()` thực sự
chạy qua nhánh OCR. Sau fix: đúng 3/3 Điều, 28/28 khoản trong Điều 1.

**Giới hạn ban đầu (đã fix, xem dưới)**: lúc đầu 1/28 khoản (khoản 5, sửa đổi khoản
4+5 của Điều 16) bị tách thành 2 entry vì văn bản trích dẫn nguyên văn "4. ... 5. ..."
lồng bên trong cũng khớp `CLAUSE_RE`; tương tự khoản 1 bị đếm 6 điểm thay vì 4 vì
trích dẫn lồng "a)/b)..." (định nghĩa "giá giao dịch liên kết" của khoản 14 mới)
cũng khớp `POINT_RE`. Đây là ambiguity cố hữu của loại văn bản "sửa đổi, bổ sung"
(trích dẫn nguyên văn điều khoản mới, có cấu trúc phân cấp riêng của nó lồng trong
cấu trúc phân cấp ngoài).

**Fix (quote-depth tracking)**: thêm counter `quote_depth` trong `parse_lines()`
(`hierarchy_parser.py`), đếm số dấu ngoặc kép mở “ trừ số dấu đóng ” tích luỹ qua
từng dòng. Khi `quote_depth > 0` (đang ở trong khối trích dẫn), dòng đó KHÔNG được
đem qua `match_article`/`match_clause`/`match_point` — chỉ coi là nội dung tiếp nối
(continuation) của Khoản/Điểm cha đang mở, bất kể format có khớp regex hay không.
Quan sát thực tế trên văn bản này: dấu “ luôn đứng riêng đầu dòng hoặc cuối dòng
"header" (vd `b) Sửa đổi, bổ sung khoản 14 như sau: ` rồi dòng sau bắt đầu `"14. Giá
thị trường...`), không có trường hợp nội dung cấu trúc thật xuất hiện ngay sau dấu
đóng ” trên cùng dòng — nên không cần xử lý tách nửa dòng phức tạp hơn.

Kết quả sau fix: đúng 3/3 Điều, đúng 28/28 khoản trong Điều 1 (không trùng số),
đúng 4/4 điểm (a, b, c, d) trong khoản 1 — hết over-segmentation. 28/28 unit test
vẫn pass (không phá vỡ case nào khác).

### A8. Chạy thử Step 2 (LLM Extraction) lần đầu — 2 lỗi thực tế

**Lỗi 1 — `ValueError: additionalProperties is only supported in Gemini Enterprise
Agent Platform mode, not in Gemini Developer API mode`**: `ExtractedEntity` (
`extraction/models.py`) có field `properties: dict = Field(default_factory=dict)`
theo đúng spec `ENTITY_SCHEMA` trong `plans/04_graph_construction_pipeline.md`
(`"properties": {}` — object mở, không khai báo trước key). Khi dùng Pydantic
model này làm `response_schema` cho Gemini structured output, `google-genai` sinh
JSON Schema có `additionalProperties`, mà **Gemini Developer API (free tier) không
hỗ trợ object schema mở** (chỉ Enterprise/Vertex AI mới hỗ trợ) — lỗi ngay khi gọi
`generate_content()`, trước khi tới được model.

**Fix**: bỏ field `properties` khỏi `ExtractedEntity` — kiểm tra toàn bộ codebase
(`grep -rn "\.properties"`) xác nhận không có chỗ nào đọc field này (validator,
scorer, orchestrator đều không dùng), nên bỏ an toàn, không mất dữ liệu nào đang
thực sự được dùng. Lưu ý: đây là giới hạn kỹ thuật thật của Gemini Developer API,
không phải lỗi logic — nếu sau này cần entity properties tự do, phải đổi sang
dạng `list[KeyValue]` (object có schema cố định) thay vì `dict` mở.

**Lỗi 2 — `429 RESOURCE_EXHAUSTED` (quota free tier hết)**: sau khi fix lỗi 1, gọi
`extract` thật vài lần liên tiếp (mỗi lần 3 Điều × 2 pass = 6 request, cộng thêm
vài lần gọi chẩn đoán) gặp `503 UNAVAILABLE` rồi cuối cùng lộ lỗi thật:
`generate_content_free_tier_requests, limit: 20, model: gemini-2.5-flash` —
**free tier Gemini Developer API giới hạn 20 request/ngày cho mỗi project x
model**. Các lỗi `503` trước đó nhiều khả năng cũng do áp lực gần ngưỡng quota,
Google trả nhầm "high demand" thay vì quota rõ ràng. Xác nhận bằng cách gọi
`generate_content` đơn giản (không `response_schema`) thành công ngay — loại trừ
khả năng lỗi do key/model/kích thước input.

**Quyết định**: không sửa code (đây là giới hạn hạ tầng phía Google, không phải
bug) — dừng gọi thêm API trong ngày, đợi quota reset (chu kỳ 24h theo Google), thử
lại sau. Production thật sẽ cần plan trả phí hoặc batch/throttle request để tránh
chạm quota free tier.

---

## B. Quyết định kỹ thuật & Lý do

### B1. Thư viện parse PDF: PyMuPDF (`fitz`), giữ nguyên dù route chính không dùng PDF nữa

Chốt theo `plans/10_tech_stack.md`. So với `pdfplumber`: PyMuPDF nhanh hơn (C++
binding), expose trực tiếp font size/bold qua `page.get_text("dict")` — cần thiết
để phân biệt "Chương II" là tiêu đề (to/đậm, đứng riêng dòng) hay xuất hiện lẫn
trong câu văn thường. Dù route crawler thật sự (vbpl.vn) không cần PDF nữa (xem A2),
code path `parse_pdf()`/`extract_lines_with_font()` vẫn giữ nguyên và hoạt động —
phục vụ trường hợp người dùng cung cấp PDF thủ công (M1 exit criteria), hoặc nguồn
khác không phải vbpl.vn.

**Cập nhật sau khi test trên PDF thật (xem A6)**: giả định "PDF từ vbpl.vn có text
layer" sai — bản tải tay là scan/ảnh. `parse_pdf()` được sửa để tự phát hiện (đo
mật độ ký tự trích được/trang) và fallback sang `extract_lines_via_ocr()` (Tesseract
qua `pytesseract`, `lang="vie"`) khi cần — `extract_lines_with_font()` không bị sửa,
chỉ thêm route OCR song song. Với văn bản pháp luật VN scan, PyMuPDF *không* hoạt
động tốt hơn (không trích được gì) — phải cần OCR, và OCR free (Tesseract) chỉ đạt
~43-45% recall trên bản scan chất lượng thấp này (xem A6) — kết luận thực tế:
route HTML (crawler) đáng tin cậy hơn nhiều so với route PDF-OCR cho nguồn vbpl.vn.

### B2. LLM model & strategy: Gemini 2.5 Flash, two-pass

Cập nhật từ "Gemini 1.5 Flash" trong `plans/10_tech_stack.md` (dòng 1.5 đã ngừng
hỗ trợ) sang **Gemini 2.5 Flash** — giữ nguyên lý do gốc (cost-effective, tiếng
Việt tốt). Two-pass (entity trước, relation sau) đúng theo spec
`04_graph_construction_pipeline.md`: Pass 2 cần danh sách entity_id đã chốt ở
Pass 1 để tham chiếu `head`/`tail`, nếu gộp 1 pass thì LLM phải tự bịa ra
entity_id ngay trong lúc xác định relation — dễ sinh ID không khớp, khó validate
"entities resolvable" ở bước Confidence Scoring (tiêu chí #4, ADR-06).

SDK: `google-genai` (SDK hợp nhất hiện tại của Google), KHÔNG dùng
`google-generativeai` cũ đã deprecated. Lý do chính: `response_schema` nhận thẳng
Pydantic model (`EntityExtractionResult`, `RelationExtractionResult`) — Gemini bị
ép trả đúng JSON shape ở API level, giảm hẳn lỗi parse so với chỉ dựa vào prompt
engineering. Retry qua `tenacity`, chỉ bắt `google.genai.errors.APIError` (không
bắt mọi Exception) để không nuốt lỗi lập trình (vd `ValidationError` từ Pydantic
parse output) — phân biệt rõ lỗi "đáng retry" (timeout, rate limit, lỗi server
tạm thời) với lỗi logic.

### B3. Cấu trúc OntologyValidator: dict tra cứu (`CONSTRAINTS`)

Dùng dict `CONSTRAINTS: dict[str, dict]` thay vì 1 function riêng cho mỗi relation.
Lý do: cho phép viết invariant `RELATION_ENUM == set(CONSTRAINTS.keys())` bằng
đúng 1 dòng so sánh set (`tests/test_ontology_consistency.py::test_all_relations_have_constraints`
và `test_no_orphan_constraints`) — nếu thêm relation type mới mà quên thêm
constraint, test fail ngay lập tức thay vì lỗi runtime mơ hồ ở pipeline. Function-
based registry phải tự maintain danh sách riêng song song với enum, dễ lệch.
Mở rộng dict khi thêm relation type mới chỉ cần thêm 1 entry — không cần sửa
logic `validate_relation()`.

**Phát hiện không nhất quán trong spec gốc** (đã ghi chú trong code, xem
`src/validation/ontology_validator.py`): `plans/04_graph_construction_pipeline.md`
có 2 chỗ liệt kê `RELATION_ENUM` khác nhau — bản ở mục "Step 4" (9 relations,
`GUIDED_BY` đã hợp nhất vào `IMPLEMENTED_BY`, có ghi chú rõ "ADR session
2026-06-29") và bản `RELATION_ENUM_EXPECTED` ở mục "Unit Test Spec" cuối file
(10 relations, còn `GUIDED_BY` riêng — rõ ràng quên cập nhật theo ADR). Đã chọn
dùng bản 9-relation (có `CONSTRAINTS` đầy đủ đi kèm) làm nguồn sự thật, vì khớp
với `tasks/task-1.graph-construction-pipeline.md` dòng 60-65 xác nhận lại "9 loại
— không thêm, không bớt".

### B4. Confidence threshold: giữ nguyên 0.3 / 0.7 (chưa calibrate trên dữ liệu)

ADR-06 yêu cầu threshold được chọn dựa trên precision/recall trên tập validation
đã annotate (3 văn bản) — nhưng tập đó **chưa tồn tại** ở giai đoạn M1+M2 này
(thuộc phạm vi ADR-07 "ground truth dataset"). Giữ nguyên 0.3/0.7 làm giá trị mặc
định hợp lý ban đầu (đọc từ `.env` qua `pydantic-settings`, có thể chỉnh không cần
sửa code) — đây là placeholder cần calibrate lại khi có dữ liệu annotate thật.

Một mâu thuẫn nhỏ khác trong ADR-06 cũng được xử lý: tiêu chí "Evidence in text"
ghi chú gợi ý dùng LLM phụ ("LLM: Does this evidence sentence support this
relation?"), nhưng chính rationale #2 của ADR-06 lại khẳng định "không tốn thêm
API calls — toàn bộ criteria đều compute-local". Đã chọn ưu tiên rationale #2:
`score_evidence_presence()` tính bằng so khớp substring/token-overlap với
`article_text` gốc, không gọi thêm LLM — vừa rẻ, vừa nhất quán với toàn bộ
triết lý "rule-based, explainable" của ADR-06.

### B5. Crawler strategy: vbpl.vn, không phải thuvienphapluat.vn

Theo khuyến nghị đã có sẵn trong `plans/09_open_questions.md` Q12 ("Nguồn tin cậy
nhất để tải văn bản có text layer: vbpl.vn... Ưu tiên tải từ đây") — vbpl.vn là
trang chính phủ (Cổng Thông tin điện tử Chính phủ), metadata (ngày hiệu lực, tình
trạng) đáng tin hơn nguồn thương mại thứ 3. Anti-bot gặp phải: WAF chặn fingerprint
headless trần (giải quyết bằng browser context thật, xem A1) và reCAPTCHA gate
trên nút tải PDF (giải quyết bằng cách không dùng PDF nữa, xem A2) — không gặp
rate-limit hay block IP trong quá trình test.

### B6. Kiến trúc tổng thể: khác đề xuất ở 2 điểm

So với cấu trúc gợi ý trong task (`pipeline/src/...`), thực tế đặt `src/` ngay ở
repo root (không có thư mục `pipeline/` lồng ngoài) vì đây đã là 1 repo riêng cho
chính module này — thêm 1 cấp `pipeline/` là thừa.

`database/` (Neo4j writer) chưa tồn tại — đúng phạm vi M3, không tạo thư mục rỗng
trước. Thay vào đó M1+M2 dừng ở `pipeline/review_queue.py` (3 sink JSONL:
accepted/review/rejected) làm input sẵn sàng cho Neo4j Writer ở M3 sau này.

---

## C. Hướng dẫn chạy & Luồng dữ liệu

### C1. Cài đặt

```bash
pip install -r requirements.txt
python -m playwright install chromium   # 1 lần duy nhất, tải headless Chromium cho crawler
cp .env.example .env
```

**Lấy Gemini API key** (bắt buộc cho bước `extract`, không cần cho `crawl`/`parse`):
1. Vào https://aistudio.google.com/apikey
2. Đăng nhập Google, bấm "Create API key"
3. Copy key, dán vào `.env`: `GEMINI_API_KEY=<key của bạn>`

Không có key thì `crawl` và `parse` vẫn chạy bình thường; `extract`/`ingest` sẽ
báo lỗi rõ ràng ngay lập tức (`RuntimeError` từ `src/config.py`) thay vì lỗi mơ
hồ giữa chừng khi gọi API.

Neo4j: **chưa cần** ở phạm vi M1+M2 (không có bước ghi DB nào).

### C2. Lệnh chạy từng Milestone

```bash
# Milestone 1: Crawler + Parser
python main.py crawl --url "https://vbpl.vn/van-ban/chi-tiet/luat-doanh-nghiep-so-59-2020-qh14--142881" \
    --doc-id LDN2020 --number "59/2020/QH14"
python main.py parse --doc-id LDN2020

# Milestone 2: LLM Extraction + Validation + Scoring (cần GEMINI_API_KEY)
python main.py extract --doc-id LDN2020

# Hoặc full pipeline M1+M2 nối tiếp:
python main.py ingest --url "https://vbpl.vn/van-ban/chi-tiet/luat-doanh-nghiep-so-59-2020-qh14--142881" \
    --doc-id LDN2020 --number "59/2020/QH14"
```

### C3. Data flow

```
crawl_and_save() [src/crawler/vbpl_crawler.py]
  Playwright render trang vbpl.vn -> body_text (str)
  -> _extract_metadata() -> DocumentMetadata (Pydantic)
  -> _extract_body_lines() -> full_text (str, nội dung văn bản thuần)
  -> ghi data/raw/<doc_id>/source.txt + metadata.json

parse() [main.py] đọc lại source.txt + metadata.json
  -> DocumentInfo (Pydantic, src/parser/models.py)
  -> parse_text(text, DocumentInfo) [src/parser/hierarchy_parser.py]
       state machine theo regex patterns.py (Chương/Điều/Khoản/Điểm)
  -> ParsedDocument (Pydantic) -> ghi data/processed/<doc_id>/hierarchy.json

extract() [main.py] đọc lại hierarchy.json -> ParsedDocument
  -> run_pipeline() [src/pipeline/orchestrator.py], lặp qua từng Article:
       extract_article() [src/extraction/llm_extractor.py]
         Pass 1: extract_entities() -> list[ExtractedEntity] (Gemini, response_schema)
         Pass 2: extract_relations() -> list[ExtractedRelation] (Gemini, response_schema)
       với mỗi relation:
         validate_schema() [src/validation/schema_validator.py] -> schema_valid: bool
         validate_ontology() [src/validation/ontology_validator.py] -> ontology_valid: bool
         score() [src/scoring/confidence_scorer.py] -> ConfidenceBreakdown.total ∈ [0,1]
         Decision Gate (ngưỡng đọc từ settings, mặc định 0.3/0.7):
           >= 0.7  -> AcceptedLog (data/processed/<doc_id>/accepted.jsonl)
           0.3-0.7 -> ReviewQueue (data/processed/<doc_id>/review_queue.jsonl)
           < 0.3   -> RejectionLog (data/processed/<doc_id>/rejected.jsonl)
```

Không có bước nào ghi Neo4j hay tạo embedding — các file JSONL ở
`data/processed/<doc_id>/` là output cuối cùng của phạm vi M1+M2, sẵn sàng làm
input cho Neo4j Writer (M3).

### C4. Chạy unit tests

```bash
python -m pytest tests/ -v
```

28 test, chia theo module:
- `tests/test_parser.py` (6) — parse fixture text, kiểm tra ranh giới Chương/Điều/Khoản/Điểm.
- `tests/test_crawler.py` (3) — `_extract_metadata`/`_extract_body_lines`/`_infer_doc_type`
  trên fixture mô phỏng cấu trúc trang vbpl.vn thật (không gọi network thật, chạy nhanh + ổn định trong CI).
- `tests/test_ontology_consistency.py` (10) — **bắt buộc theo task**, gồm 2 invariant
  (`RELATION_ENUM == set(CONSTRAINTS.keys())` theo cả 2 chiều) + 8 test case cụ thể
  cho từng relation type/rule (vượt yêu cầu tối thiểu 6 case).
- `tests/test_confidence_scorer.py` (9) — weights sum = 1.0, evidence matching,
  entities resolvable, và 2 test case end-to-end (auto-accept threshold, reject threshold).

Tất cả pass độc lập, không cần `GEMINI_API_KEY` hay network — verify bằng
`python -m pytest tests/ -q` -> `28 passed`.

### C5. Đã verify trên dữ liệu thật (không phải chỉ fixture)

- `python main.py crawl ...` chạy thật trên vbpl.vn, output `data/raw/LDN2020/source.txt`
  (6042 dòng) + `metadata.json` (title, status="Hết hiệu lực một phần",
  effective_from=2021-01-01, issued_date=2020-07-01, issued_by="QUỐC HỘI" — tất cả
  trích đúng từ trang thật, không phải giá trị giả).
- `python main.py parse --doc-id LDN2020` chạy trên text crawl thật, ra đúng
  **218 Điều** (khớp số điều thật của Luật Doanh nghiệp 2020), kiểm tra thủ công
  Điều 1 ("Phạm vi điều chỉnh") và Điều 17 (4 khoản, khoản 2 có 7 điểm a-g) khớp
  văn bản gốc.
- `extract`/`ingest` **chưa chạy được trên dữ liệu thật** vì chưa có `GEMINI_API_KEY`
  trong môi trường hiện tại — đã verify fail-fast đúng cách (exit code 1, thông báo
  lỗi tiếng Việt rõ ràng kèm link lấy key) thay vì verify bằng LLM call thật.
