# Architecture Plan — Hybrid Grounded Structured Memory

> **Loại tài liệu**: Architecture Plan
> **Trạng thái**: PROPOSED — context contracts chính đã khóa; chưa triển khai
> **Trọng tâm**: lưu trữ và xử lý context hội thoại
> **Không bao gồm**: code, execution roadmap, task breakdown hoặc timeline
> **Ràng buộc hiện hành**: retrieval-runtime-v2, answer-generation-v1, ontology v1.6.0

## 1. Mục tiêu kiến trúc

Kiến trúc này giúp Legal GraphRAG hiểu các câu hỏi nối tiếp như:

> “Còn khoản 2 thì sao?”
> “Quy định đó hiện còn hiệu lực không?”
> “Ý tôi là công ty cổ phần, không phải công ty TNHH.”
> “Tại sao câu trước bạn kết luận như vậy?”

Hệ thống cần nhớ người dùng đang nói đến document, article, clause hoặc subject
nào, nhưng không được dùng memory như một nguồn pháp luật.

Mục tiêu cốt lõi:

- lưu đủ context để resolve câu hỏi nối tiếp;
- tạo một standalone query rõ nghĩa trước retrieval;
- mỗi legal query vẫn retrieval evidence mới;
- chỉ grounded citations mới cập nhật legal focus;
- lưu đầy đủ transcript cho trải nghiệm giống ChatGPT;
- lưu provenance có cấu trúc để audit câu trả lời pháp lý;
- chống stale context, lost update và cross-session leakage;
- không thay đổi trách nhiệm của retrieval, planner và grounding hiện tại.

## 2. Nguyên tắc thiết kế

### 2.1. Memory không phải legal evidence

Memory trả lời câu hỏi “người dùng đang nói đến cái gì?”. Retrieval trả lời câu
hỏi “căn cứ pháp luật nào hỗ trợ cho câu trả lời hiện tại?”. Hai loại dữ liệu
không được thay thế cho nhau.

### 2.2. Tách dữ liệu trình bày khỏi dữ liệu quyết định

Full transcript phục vụ UI. Control state phục vụ clarification. Legal-focus
state phục vụ context pháp lý. Grounded ledger phục vụ audit. Các lớp này không
được dùng thay trách nhiệm của nhau.

### 2.3. Resolve trước, retrieve sau

Câu hỏi phụ thuộc hội thoại phải được resolve thành standalone query trước khi
đưa vào Intent Router, Temporal Parser và Retrieval Runtime.

### 2.4. Commit sau grounding

Legal focus chỉ thay đổi từ một `GroundedAnswerResult` hợp lệ sau citation, path
và temporal validation. Interpreter, transcript và retrieved-but-unused evidence
không có quyền tạo memory commit.

### 2.5. PostgreSQL là nguồn sự thật duy nhất

PostgreSQL quyết định conversation có tồn tại không, thuộc về ai, version hiện
tại là bao nhiêu và state nào đã được commit. Redis chỉ tăng tốc truy cập.

### 2.6. Khi mơ hồ thì hỏi lại

Nếu một reference có nhiều cách hiểu hợp lệ, hệ thống trả clarification thay vì
chọn document hoặc Điều gần nhất.

## 3. Kiến trúc dữ liệu tổng thể

```text
PostgreSQL — source of truth
    conversation metadata + transcript + control state + legal-focus state
    + grounded ledger + citation provenance
                    │
                    ├── versioned state cache ──► Redis
                    │
                    └── canonical legal IDs ────► Neo4j

Redis
    chỉ cache control/legal-focus state đã commit; có thể mất mà không mất dữ liệu

Neo4j
    chỉ chứa tri thức và evidence pháp luật; không chứa session memory
```

Việc tách ba storage boundary tránh hai lỗi kiến trúc:

- biến Redis thành một nguồn sự thật thứ hai cạnh PostgreSQL;
- trộn session-specific memory vào Legal Knowledge Graph.

## 4. Các lớp dữ liệu cần lưu

| Lớp dữ liệu | Nội dung | Mục đích và ranh giới |
|---|---|---|
| Conversation metadata | ID, owner, title, active/archive, timestamps | Quản lý chat thread, sidebar và ownership |
| Full transcript | Mọi user/assistant message, greeting, clarification, cannot-answer, lỗi hiển thị, citations, thứ tự | Khôi phục UI; không dùng trực tiếp làm evidence, canonical ID, query date hoặc hard filter |
| Turn execution | Request ID, lifecycle state, lease/fencing token, expiry, attempts, error | Idempotency và crash recovery |
| Control state | Pending clarification, candidate set, user-turn expiry, `control_version` | Điều phối hội thoại; không chứa legal focus |
| Legal-focus state | Scope anchor, nhiều focus anchors, semantic anchors, grounded counter, `legal_focus_version` | Memory pháp lý; chỉ GroundedAnswerResult được thay đổi |
| Scope anchor | Document roots, primary document và scope kind | Phạm vi hội thoại; không tự trở thành hard filter |
| Focus anchors | Danh sách StructuralAnchor đang được nói đến | Giữ nhiều focus cùng lúc, không collapse thành một scope node |
| Grounded ledger | Standalone query, turn kind, resolved anchors, temporal/routing data, outcome, contract versions và commit status | Audit quyết định hệ thống, không thay thế transcript |
| Citation provenance | Used unit IDs, hierarchy, citation order, content fingerprint và deep link | Reproduce grounded answer và kiểm tra output-meta |

Conversation được tạo khi user gửi message đầu tiên. Frontend nhận ID, cập nhật
URL và dùng lại ID cho các lượt sau. Full transcript và ledger liên kết bằng
conversation, message, turn và request IDs nhưng không thay thế trách nhiệm của
nhau.

## 5. Vai trò của PostgreSQL

PostgreSQL chịu trách nhiệm:

- lưu conversation bền vững;
- kiểm tra ownership;
- lưu full transcript;
- quản lý turn lifecycle, lease và recovery metadata;
- lưu control state và legal-focus state độc lập;
- lưu grounded ledger và citation provenance;
- quản lý idempotency theo request ID;
- thực hiện optimistic compare-and-set;
- đảm bảo transcript, ledger và state không lệch nhau;
- cascade delete toàn bộ dữ liệu khi user xóa conversation.

### Transaction boundary và CAS contract

1. `Begin-turn transaction`: kiểm tra conversation/ownership, ghi user message
   idempotent và tạo turn ở `RECEIVED`.
2. `Claim-turn transaction` CAS turn sang `PROCESSING` và cấp lease token.
3. Retrieval và answer generation chạy ngoài database transaction.
4. `Finalize-turn transaction`: ghi assistant message, outcome ledger, citations
   và thực hiện các commit command đủ điều kiện.
5. `ControlStateCommit` dùng `expected_control_version`, chỉ set/clear pending
   clarification và chỉ tăng `control_version`.
6. `LegalFocusCommit` chỉ nhận `GroundedAnswerResult`, dùng
   `expected_legal_focus_version`, tăng `legal_focus_version` và grounded counter.

Hai commit dùng row/version riêng. Chúng có thể nằm trong cùng PostgreSQL
transaction nhưng CAS conflict của một commit không được rollback hoặc làm stale
commit còn lại; ledger ghi riêng status của từng commit.

Ngoại lệ là turn resolve pending clarification: control clear và legal-focus
update mang dependency `ALL_OR_NOTHING`. Finalizer lock control rồi legal row,
kiểm tra cả hai expected versions trước mọi update; nếu một CAS stale thì cả hai
state giữ nguyên, commit kia nhận `DEPENDENCY_ABORTED`. Turn control-only hoặc
legal-only dùng `INDEPENDENT`. `FinalizeCommitBundle` phải khai báo mode từ
Interpreter/Grounded outputs; repository không suy đoán.

Redis chỉ được populate sau khi `Finalize-turn transaction` đã commit. Không có
transaction phân tán giữa PostgreSQL và Redis.

### Idempotency

Mỗi message gửi lên có request ID. Retry cùng request ID không được tạo message,
ledger, citation hoặc memory commit thứ hai.

## 6. Vai trò của Redis

Redis chỉ cache control state và legal-focus state đã được PostgreSQL commit.
Nó không giữ transcript, legal answer, ledger, citation provenance hoặc ownership
như nguồn duy nhất.

### Versioned cache

Hai cache entry gắn lần lượt với `control_version` và `legal_focus_version`.
Backend kiểm tra existence, ownership và current version từ PostgreSQL; stale
entry không thể override state mới hoặc khôi phục conversation đã xóa. Cache
populate lỗi không rollback PostgreSQL.

### Cache lifecycle

Entry mặc định hết hạn sau 24 giờ không hoạt động; đây là eviction, không phải
xóa conversation. Redis unavailable thì đọc PostgreSQL, chậm hơn nhưng không đổi
behavior.

## 7. Context processing pipeline

```text
User Message
→ Idempotent Begin-turn → lease-fenced Claim-turn
→ Load conversation, hai versions và hai cached state snapshots
→ State Resolver tạo effective state, không đọc raw message
→ Conversation Query Interpreter hiểu lượt, phân loại và rewrite trong một quyết định
→ Canonical Reference Linker được Interpreter gọi khi cần
    ├─ direct/clarification/output-meta → handler tương ứng
    └─ legal query → retrieval + grounding → GroundedAnswerResult hoặc failure outcome
→ ControlStateCommit từ Interpreter outcome, nếu có
→ LegalFocusCommit chỉ từ GroundedAnswerResult, nếu có
→ PostgreSQL CAS độc lập → populate cache entry đã commit
```

## 8. Một owner cho classification và standalone-query rewrite

`Conversation Query Interpreter` là owner duy nhất của cả hai quyết định:

- message thuộc greeting, legal query, output-meta hay clarification;
- nếu là legal query, standalone query cuối cùng là gì.

Không tồn tại `Turn Classifier` và `Follow-up Rewriter` như hai service có quyền
ra quyết định độc lập. Điều này ngăn trường hợp classifier coi message là
standalone nhưng rewriter lại ngầm dùng memory, hoặc classifier coi là follow-up
trong khi query cuối không chứa referent đã resolve.

Interpreter nhận raw message và hai effective state views từ State Resolver.
Nó dùng deterministic rules cho trường hợp rõ ràng, gọi Canonical Reference
Linker để resolve identity, rồi chỉ dùng LLM để diễn đạt lại khi cần. Kết quả là
một quyết định nguyên tử thuộc một trong bốn dạng:

- greeting/direct response;
- clarification required;
- output-meta;
- legal query có standalone query bắt buộc.

Nếu không thể đồng thời khóa loại turn và standalone query nhất quán, kết quả bắt
buộc là clarification. Interpreter không chọn legal retrieval intent; Intent
Router vẫn xác định factual, validity, hierarchy, comparison, definition hoặc
multi-hop sau bước này.

Mọi hiểu biết về lượt hiện tại thuộc Interpreter: explicit-input precedence,
anaphora, correction, topic switch, query hint/hard filter và yêu cầu
`REPLACE`/`MERGE`. Interpreter có thể phát `ControlStateCommit` nhưng không được
phát `LegalFocusCommit`.

## 9. State resolution không hiểu ngữ nghĩa lượt

`State Resolver` chỉ nhận persisted state, counters, versions và clock; không nhận
raw message, standalone query hoặc model output. Nó tạo immutable effective view
mà không mutate state đã load.

Nhiệm vụ:

- loại các anchor đã hết semantic TTL;
- validate schema và canonical ancestor path của structural anchors;
- loại anchor orphan hoặc vi phạm hierarchy;
- áp dụng cascade thuần cấu trúc và pending-clarification expiry;
- trả effective control state và legal-focus state kèm hai version.

Resolver không classify, rewrite, resolve anaphora, phát hiện correction/topic
switch, chọn query hint/hard filter hoặc tạo state patch. Các quyết định đó cần
raw message nên thuộc duy nhất Conversation Query Interpreter.

### Semantic precedence tại Interpreter

```text
Thông tin user nói rõ trong message hiện tại
    > canonical reference resolve từ message hiện tại
    > structured anchor còn hiệu lực
    > unresolved
```

Memory không được override structural scope, subject hoặc query date user đã nói
rõ trong lượt hiện tại.

### Query hint và hard filter

Một anchor được nhớ từ citation trước thường chỉ là query hint. Nó giúp Interpreter
làm câu hỏi rõ nghĩa nhưng không tự động giới hạn corpus.

Hard filter chỉ được tạo khi:

- user/API nêu scope rõ ràng;
- hoặc message có restrictive anaphora đã resolve chắc chắn, ví dụ “trong luật
  đó”.

Phân biệt này tránh memory làm mất evidence liên quan từ document khác.

## 10. Canonical linking và structural anchor tổng quát

Reference Linker biến mention thành canonical graph identity. Structural mention
được biểu diễn bằng `StructuralAnchor`, không dùng các field song song theo từng
level hierarchy.

| Thành phần anchor | Ý nghĩa |
|---|---|
| `node_id`, `node_type` | Canonical node thuộc Document/Chapter/Article/Clause/Point |
| `ancestor_path` | Canonical containment path từ Document đến node |
| provenance | Grounded turn, used citation IDs và fingerprint nguồn |
| expiry | `set_at_grounded_turn` và TTL theo node type |

Legal-focus state dùng hai cấu trúc độc lập:

- `ScopeAnchor`: tập canonical Document roots, `primary_document_id` có thể null
  và `scope_kind` (`single`, `multi-primary`, `multi-balanced`);
- `FocusAnchor[]`: zero-to-many StructuralAnchor tại bất kỳ structural level nào.

Primary thuộc ScopeAnchor, không thuộc FocusAnchor. Mỗi focus phải có Document tổ
tiên nằm trong scope nếu scope không rỗng; thay focus không tự thay scope và ngược
lại. Subject là semantic anchor riêng. Linker ưu tiên deterministic lookup;
ambiguity tạo control-state clarification và Linker không ghi state.

## 11. Replace/merge và primary trong multi-document scope

Grounding tạo ScopeAnchor từ các Document roots của used citations, đồng thời giữ
mọi canonical structural unit được dùng thành FocusAnchor riêng. Chỉ exact ID bị
deduplicate; không collapse nhiều focus về lowest common ancestor. Ledger vẫn giữ
từng citation chi tiết.

Primary được đặt khi scope chỉ có một document, hoặc Interpreter đã resolve một
primary rõ ràng và GroundedAnswerResult có citation thuộc primary đó. Không suy
primary từ rank, citation count/order hoặc hierarchy level. Multi-document không
đủ điều kiện trên là `multi-balanced`; đại từ số ít phải tạo clarification.

`scope_operation` và `focus_operation` được đánh giá độc lập:

- `REPLACE` là mặc định cho từng collection; `MERGE` cần additive/comparison rõ
  tại đúng level, nên có thể scope MERGE nhưng focus REPLACE;
- scope root/focus mới luôn phải đến từ used citations của GroundedAnswerResult;
- giá trị cũ chỉ được retain khi còn effective và nằm trong result fields riêng
  `retained_scope_document_ids` hoặc `retained_focus_anchor_ids`;
  retained anchor giữ nguyên provenance và TTL, không được refresh ngầm;
- MERGE union Document roots và FocusAnchor IDs; focus mới cùng ID thay metadata
  cũ, còn nhiều focus khác ID trong cùng document vẫn cùng tồn tại;
- document bị loại khỏi scope phải cascade bỏ mọi focus nằm dưới document đó;
- primary mới do explicit resolved scope quyết định; nếu không có, giữ primary cũ
  khi nó còn trong merged scope, ngược lại đặt null.

Grounding phải hạ `MERGE` không đủ điều kiện thành `REPLACE`; result không hợp lệ
thì không tạo LegalFocusCommit. Legal Focus Committer không tự suy đoán. Scope chỉ là query
hint; hard filter cần current message/API scope rõ ràng. Gemini Query Planner vẫn
chỉ dành cho `MULTI_HOP` theo contract hiện tại.

## 12. Legal-focus commit chỉ từ GroundedAnswerResult

Grounding là component duy nhất được tạo `GroundedAnswerResult`. Contract này gồm
supported answer, used citations, canonical structural paths, fingerprints,
temporal result, normalized scope/focus operations, dependency mode và expected
versions. `LegalFocusCommitter` chỉ nhận contract này.

Trong quy tắc này, “memory” là legal-focus memory. Control state là namespace
điều phối riêng và chỉ đi qua ControlStateCommit.

Không commit legal focus từ Interpreter output, resolver output, transcript,
retrieval top-k, planner candidate, answer chưa validate hoặc citation không được
dùng. Cannot-answer, empty citations, hierarchy/temporal mismatch, grounding lỗi
và fail-closed outcome không tạo `LegalFocusCommit`.

CAS thành công cập nhật ScopeAnchor, FocusAnchor[], grounded semantic anchors,
last-grounded-turn ID và grounded counter. CAS stale chỉ ghi commit status; không
mutate legal focus. Transcript và ledger vẫn lưu outcome để UI và audit phản ánh
đúng những gì đã xảy ra.

## 13. Semantic expiration và data retention

Hai khái niệm phải tách biệt:

### Semantic expiration

Một `grounded legal turn` chỉ được tính khi `LegalFocusCommit` từ
GroundedAnswerResult thắng CAS. Greeting, clarification, output-meta,
cannot-answer, error và stale CAS không tăng bộ đếm.

- ScopeAnchor document-root entry: TTL mặc định 5 grounded turns;
- FocusAnchor loại Document/Chapter: TTL mặc định 5 grounded turns;
- FocusAnchor loại Article/Clause/Point: TTL mặc định 3 grounded turns;
- semantic anchor: TTL mặc định 5 grounded turns;
- pending clarification: TTL 1 user turn trong control state.

Anchor mới hoặc được current used citation hỗ trợ nhận
`set_at_grounded_turn` mới. Retained anchor khi MERGE, user mention và output-meta
không refresh TTL. State Resolver loại anchor khi
`current_grounded_turn - set_at_grounded_turn >= TTL`. Scope root hết hạn cascade
bỏ focus bên dưới; primary hết hạn thì đặt null, không tự suy primary khác. Lịch
sử vẫn còn trong PostgreSQL.

### Data retention

Quyết định conversation còn được lưu không.

- PostgreSQL không tự động xóa conversation theo inactivity;
- conversation tồn tại đến khi user xóa;
- archive chỉ ẩn khỏi danh sách active;
- delete xóa transcript, control/legal-focus state, ledger, citations và cache;
- chỉ aggregate metrics không định danh được giữ lại.

## 14. Output-meta processing

Output-meta xử lý câu hỏi về answer trước, ví dụ “tại sao bạn kết luận vậy?”.

Luồng xử lý:

1. Đọc last grounded legal turn ID từ legal-focus state.
2. Đọc citation provenance từ PostgreSQL ledger.
3. Re-fetch các legal units tương ứng từ Neo4j.
4. So sánh evidence fingerprints.
5. Đưa evidence qua validation, projection và grounding hiện có.
6. Trả câu trả lời mới dựa trên evidence đã xác minh.

Answer text cũ chỉ là đối tượng cần giải thích, không phải căn cứ pháp luật.

Output-meta không thay đổi active legal focus hoặc last grounded legal turn ID.

### Stale-evidence policy

Fingerprint bao phủ nội dung có thể trích dẫn, canonical hierarchy, trạng thái
pháp lý và thời gian hiệu lực; không bao gồm retrieval score, rank hoặc deep link.
Nếu legal unit bắt buộc bị thiếu, fingerprint đổi hoặc hierarchy không còn khớp,
handler trả `STALE_PREVIOUS_EVIDENCE` và không dùng answer/transcript cũ làm
evidence, không âm thầm chạy lại câu hỏi cũ. Ledger lịch sử giữ nguyên; legal
focus, TTL và last grounded turn không đổi. User được đề nghị chạy một legal query
mới để nhận answer theo dữ liệu hiện hành.

Với legal follow-up thông thường, anchor lưu trong memory chỉ là query hint và
luôn phải qua linker/retrieval mới. Anchor không còn resolve được bị loại khỏi
effective context; nếu thiếu referent duy nhất thì hệ thống hỏi clarification.

Câu hỏi thêm một legal claim mới, như “quy định đó còn hiệu lực không?”, phải
được phân loại thành legal follow-up và chạy temporal retrieval mới.

## 15. Ambiguity và clarification

Khi có nhiều referent hợp lệ:

- không chạy retrieval;
- lưu pending clarification có thời hạn ngắn;
- trả candidate labels dễ hiểu cho user;
- không hiển thị internal scores hoặc technical IDs nếu không cần thiết;
- lượt trả lời tiếp theo resolve dựa trên candidate set;
- nếu user đổi chủ đề, pending clarification bị bỏ.

Clarification messages được lưu trong transcript nhưng không tạo grounded ledger
hoặc legal focus mới.

Pending clarification chỉ được set/clear bằng `ControlStateCommit` từ Interpreter
outcome. Commit này dùng control CAS và không đổi legal-focus version hoặc TTL.

## 16. Turn lifecycle, CAS dependency và crash recovery

| Turn state | Ý nghĩa |
|---|---|
| `RECEIVED` | User message đã được ghi idempotent |
| `PROCESSING` | Một worker giữ lease để xử lý |
| `COMPLETED` | Finalize đã commit; memory substatus có thể stale/aborted |
| `FAILED_RETRYABLE` | Lỗi tạm thời, có thể claim lại |
| `FAILED_TERMINAL` | Lỗi typed không retry hoặc đã hết attempt |

Begin-turn tạo `RECEIVED`, rồi claim `PROCESSING` với lease token, expiry và
attempt count. Worker renew lease trước hạn và không finalize nếu renewal fail.
Finalize còn yêu cầu đúng state/token nên zombie worker không thể overwrite.

PostgreSQL CAS `control_version` và `legal_focus_version` theo dependency mode ở
§5. Stale namespace trả status riêng; all-or-nothing dependency trả thêm
`DEPENDENCY_ABORTED`. Không tự động retry state CAS hoặc merge hai topic.

Crash recovery:

- retry của `COMPLETED` trả stored response, không chạy provider lần nữa;
- `PROCESSING` còn lease không được worker thứ hai claim;
- lease hết hạn hoặc `FAILED_RETRYABLE` được claim bằng CAS với token/attempt mới;
- recovery reload state/versions từ PostgreSQL, không tiếp tục từ Redis snapshot;
- crash trong Finalize là all-or-nothing; cache thiếu được populate ở lượt sau;
- quá attempt limit chuyển `FAILED_TERMINAL` với reason code có thể audit.

Hệ thống bảo đảm exactly-once cho database effects theo request ID/turn ID, nhưng
provider call có thể at-least-once nếu worker crash trước Finalize commit.

## 17. Failure và degraded behavior

| Failure | Policy |
|---|---|
| Redis lỗi | Đọc PostgreSQL; tăng latency nhưng không đổi behavior |
| PostgreSQL lỗi trước xử lý | Follow-up fail-closed; stateless mode cần policy rõ |
| Standalone rewrite lỗi | Chỉ raw message đã standalone được tiếp tục |
| Linker ambiguous/not found | Clarification; không chọn top semantic result |
| Grounding lỗi | Không emit unvalidated answer, không commit legal focus |
| Cache populate lỗi | Không rollback PostgreSQL; populate lại ở lượt sau |

## 18. Security và privacy boundary

- Conversation ID không tự tạo quyền truy cập.
- Backend kiểm tra owner trước mọi read/write/delete.
- Khi chưa có authentication, dùng signed anonymous browser principal.
- Redis cache không thay thế ownership check trong PostgreSQL.
- Transcript, prompt và evidence không được ghi đầy đủ vào operational logs.
- Log chỉ chứa request ID, reason code, version, status, counts và latency.
- Delete phải xóa mọi content có thể liên kết lại với conversation.
- Conversation state không được ghi vào Neo4j Legal Knowledge Graph.

## 19. Component responsibility summary

| Component | Nhiệm vụ | Lý do tồn tại |
|---|---|---|
| Conversation API | Tạo, mở, liệt kê, archive, delete và chat | Giữ lifecycle/API tách khỏi domain logic |
| Conversation Orchestrator | Điều phối flow và assemble FinalizeCommitBundle | Khai báo CAS dependency trước repository |
| Turn Lifecycle Manager | Idempotency, lease, fencing và recovery | Chống duplicate/zombie finalize sau crash |
| PostgreSQL Repositories | Transcript, hai state namespace, ledger, citations, CAS | Bảo đảm durability và transaction consistency |
| Redis State Cache | Cache control/legal-focus state theo version riêng | Giảm latency mà không tạo source of truth mới |
| Conversation Query Interpreter | Phân loại turn và tạo standalone query trong một quyết định | Loại split-brain giữa classification và rewrite |
| State Resolver | Schema, expiry, structural cascade, effective state | Không hiểu ngữ nghĩa của current turn |
| Reference Linker | Resolve mention thành canonical ID | Ngăn LLM phát minh legal identity |
| Output-meta Handler | Re-fetch evidence lượt trước | Không tin answer text cũ như nguồn luật |
| Existing Retrieval | Lấy legal evidence mới | Memory không thay thế retrieval |
| Existing Grounding | Tạo GroundedAnswerResult từ validated used citations | Là nguồn duy nhất của legal-focus commit |
| Control State Committer | CAS pending clarification | Tách hội thoại control khỏi legal memory |
| Legal Focus Committer | CAS scope/focus/counter từ GroundedAnswerResult | Chặn mọi ungrounded memory mutation |

## 20. Kết luận kiến trúc

Transcript, control state, legal-focus state và ledger có trách nhiệm độc lập.
PostgreSQL giữ sự thật bền vững, Redis chỉ cache, Neo4j chỉ giữ tri thức pháp luật.
Chỉ GroundedAnswerResult qua legal-focus CAS được thay đổi legal memory.
