# Bug Report & Contract Decision — Query Processing Fan-out

Review commit `075cf8e`. Phát hiện 1 bug thật và 1 contract gap cần khóa semantics.

---

## BUG 1 — Fan-out Tuần tự (Sequential)

**Severity:** High / Performance

### Ngữ cảnh

Sau khi `QueryProcessor` trả về danh sách `subqueries`, hệ thống phải gửi từng subquery đi retrieval rồi merge context lại. Các subquery là self-contained và không cần output của nhau để thực hiện retrieval, nên không có lý do gì phải chờ q1 xong mới chạy q2.

### Code lỗi

**`apps/backend/conversation/service.py` — dòng 382–386**

```python
# HIỆN TẠI: sequential, await từng cái một
        try:
            contexts = [
                await self._retrieval.retrieve_context(subquery_request)
                for subquery_request in subquery_requests
            ]
            merged_context = merge_contexts(contexts, query=standalone_query)
```

Python list comprehension với `await` bên trong là sequential loop. Nếu có N subquery, mỗi cái mất T giây, tổng thời gian là `N × T`.

### Fix

```python
import asyncio  # thêm ở đầu file

        try:
            # Concurrent subject to the application-scoped retrieval concurrency bound.
            contexts = list(
                await asyncio.gather(*[
                    self._retrieval.retrieve_context(subquery_request)
                    for subquery_request in subquery_requests
                ])
            )
            merged_context = merge_contexts(contexts, query=standalone_query)
```

**Về concurrency bound:**  
`BoundedRetrievalRunner` đã giới hạn concurrency ở tầng executor chung. `gather()` không bypass bound này vì mọi `retrieve_context()` đi qua cùng runner. Điều kiện này cần được xác minh bằng integration test nếu sau này có thêm adapter mới, để đảm bảo không có path nào bypass runner và làm `gather()` bắn không giới hạn.

Ví dụ N=5, max_concurrency=2: sẽ có ~3 wave thay vì 1 lần T. Vẫn tốt hơn 5T.

**Hành vi khi một retrieval fail:**  
`asyncio.gather()` raise exception ngay khi bất kỳ coroutine nào fail (`return_exceptions=False`). Các sibling task đã submit vào thread pool có thể vẫn hoàn thành, nhưng kết quả bị bỏ vì exception được bắt ở `except (RetrievalError, ...)`. Partial context không bao giờ được merge.

---

## CONTRACT GAP 2 — `depends_on` Chưa Được Runtime Sử dụng

**Loại:** Contract gap / semantics cần khóa

### Code hiện tại

**`apps/backend/query_processing/fanout.py` — dòng 20–42**

```python
# HIỆN TẠI: depends_on bị bỏ qua hoàn toàn
def build_subquery_requests(
    result: QueryProcessingResult,
    *,
    document_ids: list[str],
    query_date: date | None,
    enable_reranker: bool | None,
) -> list[RetrievalRequest]:
    filters = RetrievalFilters(document_ids=document_ids, query_date=query_date)
    return [
        RetrievalRequest(
            query=subquery.query,
            filters=filters,
            force_intent=IntentType(subquery.intent.value),
            enable_reranker=enable_reranker,
        )
        for subquery in result.subqueries   # ← depends_on không được đọc
    ]
```

### Phân tích

**Tại sao không implement scheduling dependency (Level-based execution):**  
Nếu subquery đã self-contained, đợi q1 xong trước khi chạy q2 **không làm q2 chính xác hơn và không truyền bất kỳ dữ liệu nào sang q2**. Kết quả là chỉ tăng latency mà không có lợi ích. Cách tiếp cận `resolve_execution_levels()` sẽ chỉ đúng khi có data binding thực sự từ output q1 sang input q2, tức là True multi-hop (xem phần Future bên dưới).

**Tại sao không implement data dependency (True multi-hop) trong MVP:**  
Cần `QueryPlanExecutor` với output binding, structural filter contract mới (anchor `article_id`/`unit_id`, không phải `document_id`), và cần thay đổi đáng kể `RetrievalFilters`. Chưa làm trong phiên bản hiện tại.

### Về `plan_type = multi_hop` trong MVP

> **Quan trọng:** Trong MVP, `plan_type=multi_hop` biểu diễn cấu trúc reasoning/decomposition mà QueryProcessor nhận diện được. Runtime **chưa** thực hiện data-dependent hop-to-hop binding. Tất cả subquery — kể cả khi `plan_type=multi_hop` — vẫn được retrieve concurrently như nhau. True multi-hop execution thuộc `QueryPlanExecutor` tương lai.

Đây là điểm cần làm rõ trong báo cáo đồ án để tránh câu hỏi: *"Multi-hop mà sao q2 không nhận output q1?"*

### Về invariant self-contained subquery

> **Lưu ý:** Tính self-contained của subquery được yêu cầu trong system prompt của model SFT và kiểm tra trong dataset audit/evaluation. Đây là **model/data invariant**, không phải deterministic runtime guarantee. Runtime hiện không có validator chứng minh tính self-contained một cách xác định. Nếu model sinh ra subquery mơ hồ (ví dụ: "Nghị định nào sửa đổi các điều khoản đó?"), retrieval sẽ trả về kết quả kém chất lượng mà không có lỗi runtime.

### MVP Decision

```
✅ Mọi subquery phải self-contained (model/data invariant, không phải runtime guarantee)
✅ Tất cả subquery retrieval chạy concurrently — Bug 1 fix covers this
✅ depends_on giữ trong QueryProcessingResult làm logical/reasoning metadata
✅ depends_on không ảnh hưởng scheduling — không implement execution levels
✅ depends_on không output binding — không implement data dependency
❌ resolve_execution_levels() không được merge trong phiên bản này
```

**`depends_on` vẫn hữu ích trong MVP cho:**
- Audit query decomposition plan
- Evaluation độ chính xác của model SFT
- `QueryPlanExecutor` tương lai biết dependency graph
- Generator reasoning theo thứ tự plan

### Future: True Multi-hop (QueryPlanExecutor)

```text
Level 0 → retrieve() → materialize RetrievalContext
        ↓
extract dependency anchors (article_ids, unit_ids — không phải document_ids)
        ↓
bind anchors vào RetrievalRequest của Level 1 qua structural filter contract mới
        ↓
Level 1 → retrieve() với narrowed filter
        ↓
merge_contexts(level0 + level1)
```

`resolve_execution_levels()` là một phần của `QueryPlanExecutor` này, không phải standalone function ở MVP.

---

## Tóm tắt Contract Đã Chốt

| Hạng mục | Quyết định |
|---|---|
| Sequential fan-out | ✅ Bug thật — **fix ngay** với `asyncio.gather()` |
| Semaphore thêm | ❌ Không cần — application runner đã bound toàn bộ retrieval path |
| `depends_on` | ✅ Giữ trong contract làm logical metadata |
| `depends_on` → scheduling | ❌ Không làm — không có lợi nếu subquery self-contained |
| `depends_on` → output binding | ❌ Không làm — plan sau |
| `plan_type=multi_hop` runtime | ⚠️ Nhận diện được, chưa phải true hop-to-hop execution |
| Subquery self-contained | ✅ Yêu cầu qua SFT contract/audit, **không phải** deterministic runtime guarantee |
| `resolve_execution_levels()` | ❌ Không merge — thuộc `QueryPlanExecutor` tương lai |
