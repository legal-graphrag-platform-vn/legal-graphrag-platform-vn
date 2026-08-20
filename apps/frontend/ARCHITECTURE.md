# Component: Frontend (`apps/frontend/`)

> Tài liệu kiến trúc/thiết kế. Để chạy dev server hoặc lệnh kiểm thử/build — xem [README.md](README.md) trong thư mục này. Quy tắc coding chi tiết (React/Next.js, styling, tách hook/component) xem [AGENTS.md](AGENTS.md).

> Next.js 16 App Router — giao diện Chat (hỏi-đáp grounded, streaming) và Explorer (duyệt văn bản pháp luật dạng cây + đồ thị quan hệ).

## Cấu trúc `src/`

| Thư mục | Nội dung |
|---|---|
| `app/` | Route App Router: `page.tsx` (trang chủ), `chat/` (trang chat), `explorer/` (trang explorer), `layout.tsx` (HTML gốc/CSS toàn cục), `api/[...path]/route.ts` (catch-all proxy sang backend, mọi HTTP verb). |
| `components/chat/` | `MessageItem`, `SourceCard`, `SourceDetailModal`, `ExplanationPanel`. |
| `components/explorer/` | `DocumentDetail`, `DocumentList`, `FilterBar`, `GraphViewer`. |
| `components/layout/` | `Sidebar`, `ThemeProvider`, `ThemeToggle`. |
| `components/auth/` | `AuthModal`. |
| `components/ui/` | Primitives kiểu shadcn (badge, button, card, input, scroll-area, select, separator, sheet, skeleton, tabs, tooltip). |
| `hooks/` | `useChatStream` (SSE stream + state, ~292 dòng), `useDocumentDetail`, `useDocumentGraph`, `useDocuments`. |
| `lib/` | `api/client.ts` (fetch wrapper), `api/documents.ts`, `api/sse.ts` (SSE parser), `source-link.ts` (resolve deep-link), `utils.ts`. |
| `types/` | `chat.ts`, `documents.ts` — mirror 1-1 với Pydantic model backend. |

## Tính năng chính

**Chat**: UI hỏi-đáp streaming. `MessageItem` render markdown (`react-markdown`/`remark-gfm`). `SourceCard` render chip trích dẫn theo từng message — badge label (Appendix/Article/Clause/Point), trích văn bản, khoảng hiệu lực, thanh điểm relevance; click → `sourceHref()` điều hướng deep-link sang `/explorer`, hoặc mở `SourceDetailModal` khi nguồn là Appendix hoặc thiếu ID điều hướng được. `ExplanationPanel` (`<details>` thu gọn) hiển thị ghi chú temporal + reasoning path phục vụ "giải thích căn cứ".

**Explorer**: `DocumentList` + `FilterBar` để duyệt/lọc văn bản. `DocumentDetail` render toàn bộ cây pháp lý (Part → Chapter → Section/Subsection → Article → Clause → Point) dạng block thu gọn được, tự động hyperlink số hiệu văn bản được nhắc tới (`renderContentWithLinks`), và **`AppendixBlock`** render riêng Part/Chapter/Article-không-nhóm thuộc Phụ lục, tách biệt khỏi thân văn bản chính. Có tab Content / Relations (AMENDS/REPLACES/REPEALS...) / `GraphViewer` (dynamic import `ssr:false`, dùng `useDocumentGraph`).

## Kết nối backend

`lib/api/client.ts` — `getBaseUrl()`:
- Server-side (SSR/Node): `INTERNAL_API_URL` → `NEXT_PUBLIC_API_URL` → fallback `http://backend:8000`.
- Client-side (browser): chỉ dùng `NEXT_PUBLIC_API_URL` (rỗng nếu chưa set → gọi tương đối, dễ 404 âm thầm — đây từng là nguyên nhân UI "bung bét" trước khi tạo `.env.local`).
- Mọi request kèm `credentials: 'include'`.

`apps/frontend/.env.local` (dev local): `NEXT_PUBLIC_API_URL=http://localhost:8000`.

Ngoài ra có proxy catch-all `app/api/[...path]/route.ts` forward sang `INTERNAL_API_URL || NEXT_PUBLIC_API_URL || http://127.0.0.1:8000`, giữ nguyên cookie và stream response body.

## Type contract (mirror backend)

- `types/chat.ts`: `Source` (mirror `RetrievedUnitDTO`, giữ field cũ để backward-compat), `ReasoningPath`, `ResolvedReference`, `Message` (có `client_turn_id`, `kind`, `cannot_answer`, `temporal_notes`, `reasoning_paths`), `ChatSession`.
- `types/documents.ts`: comment rõ là mirror của `apps/backend/api/models.py` — `PointDetail`, `ClauseDetail`, `ArticleDetail`, `SubsectionDetail`, `SectionDetail`, `ChapterDetail`, `PartDetail`, `AppendixDetail`, `DocumentRelation`, `DocumentSummary`/`DocumentDetail`, `GraphNode`/`GraphEdge`/`GraphData`, `RetrievedUnitDTO`, `FilterState`.

## Test (Vitest, `npm test`)

- `lib/source-link.test.ts` — `sourceHref()`: ưu tiên deep-link tin cậy, fallback từ document/article/clause ID, map route backend không hỗ trợ qua explorer param, trả `null` khi thiếu định danh hoặc label là Appendix.
- `lib/api/client.test.ts` — `apiGet`/`apiPost`/`apiStream` gửi credentials/cookie đúng.
- `lib/api/sse.test.ts` — `SseParser`: event unicode bị phân mảnh, payload metadata/citation, event clarification, event explanation có cấu trúc, từ chối JSON hỏng.

## Kiểm chứng (test evidence)

```
npx vitest run   (trong apps/frontend/)
→ 3 test files, 13 passed
```

Phạm vi test hiện tại chỉ ở tầng `lib/` (resolve link, SSE parser, API client) — **chưa có test cho component React** (`SourceCard`, `DocumentDetail`, `AppendixBlock`...), đây là khoảng trống kiểm thử cần lưu ý khi trình bày.

## Liên quan

- [Backend API](../backend/ARCHITECTURE.md) — nguồn của mọi endpoint `/chat`, `/documents`, `/conversations` mà frontend gọi.
- [Generation](../../src/generation/README.md) — nguồn `StatementCitation`/`AnswerCitation` mà `SourceCard` hiển thị.
- [../../README.md](../../README.md) — tổng quan toàn bộ dự án.
