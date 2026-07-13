Bạn đang tiếp quản implementation cho dự án:

`legal-graphrag-platform-vn`

Đây là đồ án xây dựng nền tảng AI khai thác tri thức pháp luật doanh nghiệp Việt Nam dựa trên Knowledge Graph và Temporal GraphRAG.

Hai execution plan cần thực hiện tuần tự:

1. `plans/agent-plan-feats/10_phase2_backend_retrieval_integration_plan.md`
2. `plans/agent-plan-feats/11_phase2_answer_generation_plan.md`

Không bắt đầu sửa code ngay. Trước tiên phải đọc repository, đối chiếu plan với code hiện tại và lập implementation map.

## 1. Trạng thái hiện tại

Retrieval runtime đã được triển khai và kiểm thử trên pilot `L59_2020`.

Các thành phần đã tồn tại gồm:

* retrieval public contracts;
* intent router;
* seed retrieval;
* vector/full-text retrieval;
* graph expansion;
* RRF fusion;
* temporal filtering;
* reranking;
* evidence/context construction;
* retrieval factory và runtime lifecycle;
* evaluation framework;
* artifact verification.

Retrieval runtime hiện là source of truth duy nhất cho retrieval orchestration.

Không được viết lại retrieval orchestration trong backend hoặc generation layer.

Pilot hiện dùng:

* embedding model: `BAAI/bge-m3`;
* embedding dimension: 1024;
* reranker model: `BAAI/bge-reranker-v2-m3`;
* reranker adapter đã chốt: `FlagEmbedding.FlagReranker`;
* Neo4j 5.x;
* FastAPI;
* Python 3.11–3.12;
* Pydantic v2;
* uv dependency management.

Không tự ý đổi:

* model checkpoint;
* reranker adapter;
* ranking logic;
* intent routing;
* graph expansion behavior;
* temporal semantics;
* retrieval evaluation gold;
* dependency versions đã pin.

## 2. Kiến trúc bắt buộc

Dependency direction phải giữ:

```text
API / Backend
    ↓
Application services
    ↓
Retrieval public contracts/runtime
    ↓
Domain ports
    ↓
Infrastructure adapters
```

Backend không được import trực tiếp:

* Neo4j driver;
* concrete embedding provider;
* concrete reranker;
* concrete full-text/vector adapters;
* internal graph query implementation.

Answer generation không được gọi HTTP retrieval endpoint.

Luồng đúng:

```text
/api/v1/ask
→ application generation service
→ RetrievalRuntime trực tiếp qua application boundary
→ RetrievalContext
→ Evidence Registry
→ Prompt Builder
→ LLM Provider
→ Citation/Grounding Validation
→ API response
```

Không tạo orchestration thứ hai bên cạnh `RetrievalRuntime`.

## 3. Thứ tự thực hiện bắt buộc

### Phase A — Repository reconnaissance

Đọc tối thiểu:

* Plan 10;
* Plan 11;
* `src/backend`;
* `src/application/retrieval_factory.py`;
* toàn bộ public contracts trong `src/retrieval`;
* retrieval typed errors;
* retrieval runtime;
* retrieval tests;
* backend tests hiện có;
* provider abstractions hiện có;
* `pyproject.toml`;
* cấu hình và dependency lockfile.

Sau đó báo cáo:

* kiến trúc thực tế;
* file nào sẽ thay đổi;
* file nào sẽ tạo mới;
* dependency direction;
* các điểm plan khác code hiện tại;
* blockers trước implementation.

Chỉ sửa plan khi plan thật sự không khớp repository. Không tự ý mở rộng scope.

### Phase B — Implement Plan 10

Hoàn thành Backend Retrieval Integration trước.

Bắt buộc có:

* FastAPI request/response DTO;
* retrieval endpoint;
* application service;
* dependency injection;
* application-scoped runtime lifecycle;
* startup/shutdown;
* thread offloading cho blocking retrieval;
* bounded concurrency;
* timeout;
* typed error mapping;
* request logging/tracing;
* OpenAPI validation;
* unit, API, lifecycle và integration tests.

Không triển khai answer generation trong Phase B.

Sau khi Plan 10 pass đầy đủ:

* chạy full tests;
* chạy Ruff;
* chạy format check;
* chạy `git diff --check`;
* báo acceptance matrix;
* không bắt đầu Plan 11 nếu còn blocker.

### Phase C — Implement Plan 11

Chỉ bắt đầu khi Backend Retrieval Integration đã ổn định.

Answer Generation phải:

* chỉ dùng evidence từ `RetrievalContext`;
* không cho LLM tự tạo trusted citation metadata;
* tạo evidence registry trước khi gọi model;
* dùng structured output hoặc schema validation;
* validate mọi citation ID;
* phát hiện Điều/Khoản/Điểm/văn bản không có trong evidence;
* xử lý riêng:

  * unsupported capability;
  * no results;
  * insufficient evidence;
  * provider timeout;
  * malformed model output;
  * hallucinated citation;
* không trả lời đoán khi evidence không đủ;
* không cho retrieved legal text điều khiển system instructions;
* giữ citation ordering và response deterministic sau post-processing.

## 4. Async và lifecycle contract

Retrieval hiện là blocking/synchronous.

Trong FastAPI:

* không gọi blocking retrieval trực tiếp trên event loop;
* phải dùng thread boundary phù hợp;
* timeout ở API/application layer;
* bounded concurrency để tránh tạo vô hạn worker jobs;
* runtime được tạo một lần trong lifespan;
* runtime đóng đúng một lần;
* partial startup failure phải cleanup resource đã tạo;
* request state không được dùng mutable global state;
* concurrent requests không được ghi đè context của nhau.

Phải có test cho:

* thread boundary;
* timeout;
* cancellation behavior;
* concurrent requests;
* startup failure;
* shutdown;
* double close safety;
* resource cleanup.

## 5. Error semantics

Không gộp các trạng thái sau thành một:

```text
unsupported
no_results
insufficient_evidence
dependency_unavailable
timeout
invalid_request
internal_error
```

Không đổi exception thành empty result để né lỗi.

Không trả stack trace, credentials, Neo4j URI hoặc provider secrets trong API response.

HTTP mapping phải tập trung ở backend boundary, không để domain phụ thuộc HTTP.

## 6. Test contract bắt buộc

Trước mỗi implementation unit:

1. xác định behavior;
2. lập test cases;
3. viết hoặc cập nhật test;
4. implement;
5. chạy targeted tests;
6. chạy full suite.

Test tối thiểu gồm:

### Happy paths

* request hợp lệ;
* đúng DTO/schema;
* đúng intent, status, evidence và citations;
* ordering ổn định;
* runtime được gọi đúng một lần.

### Boundary cases

* empty query;
* whitespace query;
* min/max top-k;
* optional fields;
* duplicate citations;
* empty retrieval context;
* một evidence item;
* score ties;
* temporal boundary dates.

### Invalid inputs

* enum không hợp lệ;
* malformed dates;
* limit ngoài range;
* unsupported configuration;
* missing required fields;
* malformed model output.

### Failure paths

* Neo4j unavailable;
* embedding/reranker unavailable;
* retrieval timeout;
* provider timeout;
* provider returns empty content;
* provider returns invalid structured output;
* citation không tồn tại;
* hallucinated Article/Clause;
* insufficient evidence;
* startup partial failure.

### Security/integrity

* không nối user input trực tiếp vào Cypher;
* không log secrets;
* prompt injection trong legal text không được điều khiển system behavior;
* model không được tự quyết định trusted URLs/IDs;
* response không lộ internal exception;
* read-only integration test không được mutate pilot graph.

### Architecture tests

* backend không import concrete retrieval infrastructure;
* generation không import Neo4j adapter;
* answer endpoint không gọi retrieval HTTP endpoint;
* retrieval runtime vẫn là orchestration owner duy nhất.

Không được:

* thêm `skip` hoặc `xfail` để che lỗi;
* nới assertion để test pass;
* mock function đang được kiểm tra;
* chỉ kiểm tra `result is not None`;
* viết mock-only integration test;
* thay đổi production behavior chỉ để dễ test;
* sửa evaluation gold để phù hợp implementation.

## 7. Model và dependency contract

Giữ nguyên:

```text
Embedding: BAAI/bge-m3
Reranker: BAAI/bge-reranker-v2-m3
Adapter: FlagEmbedding.FlagReranker
FlagEmbedding: 1.4.0
Transformers: 4.57.6
```

Không đổi sang `sentence_transformers.CrossEncoder` nếu không có quyết định kiến trúc mới.

Dependency group `embedding` phải được sync rõ ràng:

```bash
uv sync --group embedding
```

Phải kiểm tra runtime thực tế:

```bash
uv run python -c "
import transformers
import FlagEmbedding
print(transformers.__version__)
print(transformers.__file__)
print(FlagEmbedding.__file__)
"
```

Không kết luận dependency đúng chỉ dựa vào `pyproject.toml`.

## 8. Scope exclusions

Không thực hiện trong hai plan này:

* thay đổi ontology;
* viết lại graph construction;
* mở rộng corpus;
* thay đổi retrieval ranking;
* train model;
* fine-tune embedding/reranker;
* frontend;
* deployment production;
* thay đổi Gate 7;
* đóng M3-B13;
* đánh dấu Milestone A passed.

Giữ nguyên:

```text
Gate 7: OPEN
M3-B13: OPEN
Milestone A: NOT PASSED
```

## 9. Verification commands

Sau mỗi plan phải chạy ít nhất:

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
git diff --check
```

Nếu integration tests có marker riêng, chạy thêm đúng command và ghi rõ môi trường được sử dụng.

Không tuyên bố hoàn thành nếu còn:

* test failure;
* lint failure;
* unexplained warning;
* untested acceptance requirement;
* architecture violation;
* dirty workaround không được báo cáo.

## 10. Output sau mỗi plan

Báo cáo theo format:

```text
Plan implemented
Files changed
Architecture decisions
Public contracts added/changed
Acceptance matrix
Tests added/updated
Targeted test results
Full suite result
Integration evidence
Ruff/format/diff results
Remaining untested risks
Deferred items
Unexpected repository issues
Verdict
```

Verdict chỉ được là:

```text
READY FOR NEXT PLAN
```

hoặc:

```text
BLOCKED — NEEDS FIX
```

Không bắt đầu Plan 11 khi verdict Plan 10 chưa phải `READY FOR NEXT PLAN`.

Trước khi sửa code, hãy bắt đầu bằng repository reconnaissance và trả lại implementation map.
