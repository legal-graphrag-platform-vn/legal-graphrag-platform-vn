# Nguyên Tắc Phát Triển Giao Diện (Frontend Developer & Agent Guidelines)

Tài liệu này định nghĩa cấu trúc thư mục, quy tắc viết code và hướng dẫn dành cho AI Agents khi tham gia phát triển repo `chat-client`.

---

## 1. Cấu Trúc Thư Mục (Client Structure)

```text
chat-client/
├── AGENTS.md                  # Hướng dẫn lập trình Client (nằm trong repo này)
├── package.json               # Các thư viện dependencies (lucide-react, react-markdown, remark-gfm)
├── tsconfig.json              # Cấu hình TypeScript
├── src/
│   ├── app/                   # App Router pages & layouts
│   │   ├── layout.tsx         # Bọc HTML, CSS toàn cục
│   │   └── page.tsx           # Giao diện chính của Chat (Welcome Screen, chat form)
│   ├── components/            # UI Components dùng chung
│   │   ├── chat/              # Các component liên quan đến cuộc hội thoại
│   │   │   ├── MessageItem.tsx# Hiển thị tin nhắn người dùng và AI
│   │   │   ├── SourceCard.tsx # Hiển thị các thẻ nguồn trích dẫn tài liệu RAG
│   │   │   └── SourceDetailModal.tsx # Modal hiển thị chi tiết nội dung tài liệu trích dẫn
│   │   ├── layout/            # Các component khung sườn bố cục (Layout)
│   │   │   └── Sidebar.tsx    # Thanh bên quản lý lịch sử hội thoại & Settings
│   │   └── shared/            # Các component nguyên tử dùng chung (Button, Input, Modal...)
│   ├── hooks/                 # Custom React Hooks
│   │   └── useChatStream.ts   # Hook xử lý kết nối SSE & đọc stream chunk
│   └── types/                 # Kiểu dữ liệu TypeScript
│       └── chat.ts            # Định nghĩa Message, Source, ChatSession
```

---

## 2. Quy Tắc Lập Trình (Client Coding Rules)

### 2.1. React 19 & Next.js 16 (App Router)
* Chú ý tính tương thích giữa **React Server Components (RSC)** và **Client Components**.
* Luôn khai báo `"use client"` ở đầu các tệp tin quản lý trạng thái (`useState`, `useEffect`, `useRef`).
* Giữ cấu trúc thư mục phẳng, sạch sẽ, không tạo các subfolder lồng nhau quá sâu.

### 2.2. TypeScript & Type Safety
* Khai báo kiểu dữ liệu rõ ràng cho tất cả các props và states. Tránh sử dụng kiểu `any`.
* Để vượt qua kiểm tra kiểu TypeScript của môi trường mà không để lộ thông tin nhạy cảm, luôn sử dụng giá trị fallback rỗng `|| ''` thay vì hardcode giá trị mặc định.

### 2.3. Quy định về Design Tokens & Styling (Tailwind CSS v4)
* **Bắt buộc sử dụng các Design Tokens** đã được định nghĩa sẵn trong hệ thống tại [globals.css](file:///D:/Workspace/Project/legal-graphrag/gpt/chat-client/src/app/globals.css) (ví dụ: `bg-background`, `text-foreground`, `border-border`, `bg-sidebar`, `bg-brand`, `rounded-standard`...).
* **Tuyệt đối không hardcode** các mã màu tùy tiện (như `bg-zinc-100`, `text-black`, `bg-[#121212]`), các giá trị bo góc tự chọn (như `rounded-xl`, `rounded-[14px]`) hoặc các giá trị shadow khác biệt. Mọi styling phải tham chiếu qua các class token tiện ích đã được ánh xạ sẵn.
* Không cài đặt thêm các thư viện UI cồng kềnh (như Shadcn/ui) để tránh làm nặng mã nguồn và phá vỡ giao diện tối giản thuần túy của ChatGPT Clone.
* Sử dụng modifier `dark:` để cấu hình giao diện tối đồng bộ với hệ thống.

### 2.4. Kết Nối Streaming SSE (Server-Sent Events)
* Client sử dụng fetch API để gửi request dạng POST. Sử dụng `response.body.getReader()` để đọc dữ liệu stream tuần tự.
* Định dạng dữ liệu mong đợi từ API Server:
  * Chunk metadata chứa nguồn tài liệu (gửi đầu tiên): `data: {"type": "metadata", "sources": [...]}\n\n`
  * Chunk nội dung chữ (gửi liên tiếp): `data: {"type": "content", "content": "..."}\n\n`
  * Chunk kết thúc stream (gửi cuối cùng): `data: [DONE]\n\n`

### 2.5. Tư Duy Chia Nhỏ Component & Tách Biệt Logic (Modularization & Custom Hooks)
* **Quy tắc Single Responsibility (Đơn nhiệm)**: Không gộp quá nhiều code hoặc nhiều tính năng khác nhau vào một component duy nhất. Cố gắng giữ kích thước file dưới 150-200 dòng.
* **Tách biệt UI và Logic (Separation of Concerns)**:
  * **Tuyệt đối không viết code call API trực tiếp** hoặc xử lý các logic phức tạp (như SSE stream reader, đồng bộ hóa state, quản lý luồng dữ liệu) ngay bên trong component giao diện.
  * Mọi tác vụ gọi API hoặc xử lý luồng dữ liệu bắt buộc phải được tách thành các **Custom Hook riêng** (như `useChatStream.ts`) nằm ở thư mục `src/hooks/`. Component giao diện chỉ chịu trách nhiệm gọi Hook, nhận dữ liệu/trạng thái và render UI.
* **Tách nhỏ các thành phần giao diện phụ**: Khi một component chứa các khối giao diện phụ như Modals, Drawers, Dropdowns hay Popovers, hãy tách các thành phần này ra các file riêng biệt (ví dụ: tách `SourceDetailModal.tsx` khỏi `SourceCard.tsx`).
* **Sử dụng thư mục `components/shared/`**: Các phần tử giao diện cơ bản có tần suất sử dụng lại cao (như các nút bấm chung, khung input tùy chỉnh, loading spinners, dialogs...) phải được lưu trữ trong thư mục `src/components/shared/` để tối ưu hóa tái sử dụng.
