# Từ Điển Dữ Liệu Hợp Nhất (Database Schema Dictionary)
## Hệ Thống Quản Lý Ngữ Cảnh Hội Thoại & Xác Thực Người Dùng (Plan 19 & Plan 20)

Tài liệu mô tả chi tiết các bảng dữ liệu trong hệ thống PostgreSQL của **Legal GraphRAG Platform VN**.

---

### 1. Bảng `USERS` (Hồ sơ người dùng)
Lưu trữ thông tin hồ sơ (profile) của người dùng hệ thống.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN, DF=gen_random_uuid() | Khóa chính định danh người dùng |
| `full_name` | `varchar(128)` | | Tên hiển thị đầy đủ của người dùng |
| `avatar_url` | `text` | | Đường dẫn ảnh đại diện của người dùng |
| `is_active` | `boolean` | NN, DF=true | Trạng thái hoạt động của tài khoản (true: đang hoạt động, false: bị khóa) |
| `created_at` | `timestamptz` | NN, DF=NOW() | Thời điểm tạo hồ sơ người dùng |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm cập nhật thông tin người dùng mới nhất |

---

### 2. Bảng `ACCOUNTS` (Tài khoản đăng nhập)
Lưu trữ thông tin xác thực đăng nhập (Username / Password) của người dùng, liên kết 1-1 với bảng `USERS`.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN, DF=gen_random_uuid() | Khóa chính định danh tài khoản đăng nhập |
| `user_id` | `uuid` | FK(users.id), NN, UNIQUE | Khóa ngoại liên kết 1-1 với hồ sơ người dùng trong bảng USERS |
| `username` | `varchar(64)` | NN, UNIQUE | Tên đăng nhập duy nhất của người dùng |
| `password_hash` | `varchar(255)` | NN | Chuỗi băm mật khẩu bảo mật (PBKDF2 / Argon2id) |
| `created_at` | `timestamptz` | NN, DF=NOW() | Thời điểm đăng ký tài khoản |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm thay đổi thông tin đăng nhập gần nhất |

---

### 3. Bảng `CONVERSATIONS` (Phiên hội thoại)
Quản lý các cuộc trò chuyện của người dùng ẩn danh (Anonymous) và người dùng chính thức (User).

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh phiên hội thoại |
| `owner_kind` | `enum('ANONYMOUS','USER')` | NN, CHECK | Phân loại chủ sở hữu hội thoại ('ANONYMOUS' hoặc 'USER') |
| `owner_principal_id` | `uuid` | NN | ID chủ sở hữu (UUID của khách ẩn danh hoặc ID của User) |
| `title` | `varchar(255)` | NN, DF='Cuộc trò chuyện mới' | Tiêu đề cuộc trò chuyện (tự động tạo từ câu hỏi đầu tiên) |
| `is_deleted` | `boolean` | NN, DF=false | Cờ đánh dấu xóa mềm cuộc trò chuyện (Soft Delete) |
| `next_user_turn_no` | `integer` | NN, DF=1, CHECK(>=1) | Số thứ tự lượt tương tác kế tiếp của người dùng |
| `created_at` | `timestamptz` | NN, DF=NOW() | Thời điểm khởi tạo cuộc trò chuyện |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm cập nhật tin nhắn cuối cùng |

---

### 4. Bảng `CONVERSATION_TURNS` (Lượt tương tác & Idempotency)
Quản lý trạng thái xử lý, chống trùng lặp request (Idempotency) và lưu snapshot kết quả replay.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh lượt tương tác |
| `conversation_id` | `uuid` | FK(conversations.id), NN | Khóa ngoại thuộc cuộc trò chuyện nào |
| `client_turn_id` | `uuid` | NN, UNIQUE(conv_id, client_turn_id) | Mã lượt câu hỏi cố định phía client để chống duplicate request (Idempotency) |
| `user_turn_no` | `integer` | NN, UNIQUE(conv_id, user_turn_no) | Số thứ tự lượt câu hỏi của người dùng trong cuộc trò chuyện |
| `status` | `enum('PROCESSING','COMPLETED','CANNOT_ANSWER','NEEDS_CLARIFICATION','FAILED')` | NN | Trạng thái xử lý của lượt chat hiện tại |
| `resolution_status` | `enum('RESOLVED','AMBIGUOUS','UNRESOLVED')` | | Trạng thái giải quyết ngữ cảnh tham chiếu pháp lý |
| `resolution_reason_code` | `varchar(64)` | | Mã lý do giải quyết tham chiếu (ví dụ: EXPLICIT_FOUND, ANAPHORA_AMBIGUOUS) |
| `standalone_query` | `text` | | Câu hỏi đã được viết lại độc lập đầy đủ nghĩa (Rewrite Standalone Query) |
| `error_code` | `varchar(64)` | | Mã lỗi chuẩn hóa (nếu lượt tương tác bị FAILED) |
| `response_snapshot` | `jsonb` | | Snapshot nội dung câu trả lời chuẩn để Replay lại SSE stream mà không gọi lại AI |
| `created_at` | `timestamptz` | NN, DF=NOW() | Thời điểm bắt đầu lượt tương tác |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm hoàn thành lượt tương tác |

---

### 5. Bảng `CONVERSATION_MESSAGES` (Lịch sử nội dung tin nhắn)
Lưu trữ toàn bộ nội dung tin nhắn transcript của người dùng và trợ lý AI.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh tin nhắn |
| `turn_id` | `uuid` | FK(conversation_turns.id), NN | Khóa ngoại thuộc lượt tương tác nào |
| `conversation_id` | `uuid` | FK(conversations.id), NN | Khóa ngoại thuộc cuộc trò chuyện nào |
| `role` | `enum('user','assistant')` | NN | Vai trò người gửi ('user': người dùng, 'assistant': trợ lý AI) |
| `kind` | `enum('USER_QUERY','ANSWER','CANNOT_ANSWER','CLARIFICATION','SMALL_TALK')` | NN | Phân loại mục đích tin nhắn phía server |
| `content` | `text` | NN | Nội dung chi tiết của tin nhắn văn bản |
| `ordinal` | `integer` | NN, UNIQUE(conv_id, ordinal) | Thứ tự tuyến tính hiển thị tin nhắn trong cuộc trò chuyện |
| `created_at` | `timestamptz` | NN, DF=NOW() | Thời điểm phát sinh tin nhắn |

---

### 6. Bảng `MESSAGE_CITATIONS` (Căn cứ & Trích dẫn pháp lý)
Lưu trữ chi tiết các trích dẫn pháp lý kèm theo tin nhắn trả lời của trợ lý AI.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh trích dẫn |
| `message_id` | `uuid` | FK(conversation_messages.id), NN | Khóa ngoại thuộc tin nhắn trả lời nào của assistant |
| `conversation_id` | `uuid` | FK(conversations.id), NN | Khóa ngoại thuộc cuộc trò chuyện nào |
| `unit_id` | `varchar(256)` | NN, UNIQUE(msg_id, unit_id) | Mã định danh đơn vị pháp lý gốc (Khoản/Điều/Văn bản) |
| `citation_ordinal` | `integer` | NN | Thứ tự xuất hiện của trích dẫn trong câu trả lời |
| `citation_label` | `text` | NN | Nhãn trích dẫn hiển thị (ví dụ: "Điều 3, Khoản 1, 01/2021/NĐ-CP") |
| `document_id` | `varchar(256)` | NN | Mã văn bản quy phạm pháp luật gốc |
| `article_id` | `varchar(256)` | | Mã Điều pháp luật liên quan |
| `clause_id` | `varchar(256)` | | Mã Khoản pháp luật liên quan |
| `deep_link` | `text` | NN | Đường dẫn liên kết sâu đến chi tiết văn bản pháp luật |
| `metadata_snapshot` | `jsonb` | | Snapshot thông tin bổ sung của căn cứ trích dẫn |

---

### 7. Bảng `GROUNDED_FOCUSES` (Cửa sổ ngữ cảnh tham chiếu pháp lý)
Lưu giữ danh sách các đối tượng pháp lý đã trích dẫn gần đây làm tiêu điểm giải quyết đại từ thay thế (Anaphora Resolution).

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh ngữ cảnh trọng tâm |
| `conversation_id` | `uuid` | FK(conversations.id), NN | Khóa ngoại thuộc cuộc trò chuyện nào |
| `node_id` | `varchar(256)` | NN, UNIQUE(conv_id, node_id) | Mã node đối tượng pháp lý trong đồ thị tri thức (Graph Node ID) |
| `node_type` | `varchar(64)` | NN | Loại node pháp lý ('Document', 'Article', 'Clause') |
| `document_type` | `varchar(64)` | | Loại văn bản pháp luật ('Luật', 'Nghị định', 'Thông tư',...) |
| `canonical_label` | `text` | NN | Tên nhãn chuẩn hóa của đối tượng pháp lý |
| `document_id` | `varchar(256)` | NN | Mã văn bản gốc |
| `article_id` | `varchar(256)` | | Mã Điều |
| `clause_id` | `varchar(256)` | | Mã Khoản |
| `document_metadata` | `jsonb` | | Metadata bổ sung của node pháp lý |
| `last_grounded_user_turn_no` | `integer` | NN | Số lượt tương tác gần nhất đối tượng này được trích dẫn (Hết hạn sau 5 lượt) |
| `citation_order` | `integer` | NN | Thứ tự trích dẫn trong câu trả lời |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm cập nhật tiêu điểm ngữ cảnh |

---

### 8. Bảng `PENDING_CLARIFICATIONS` (Yêu cầu làm rõ tham chiếu nhập nhằng)
Tạm giữ trạng thái khi câu hỏi người dùng có tham chiếu bị nhập nhằng, chờ người dùng phản hồi lựa chọn.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh yêu cầu làm rõ |
| `conversation_id` | `uuid` | FK(conversations.id), NN, UNIQUE | Khóa ngoại liên kết 1-1 với cuộc trò chuyện đang chờ phản hồi |
| `source_turn_id` | `uuid` | FK(conversation_turns.id), NN | Khóa ngoại đến lượt tương tác gốc phát sinh nhập nhằng |
| `mode` | `enum('SELECT','RESTATE')` | NN | Chế độ làm rõ ('SELECT': Chọn từ danh sách, 'RESTATE': Yêu cầu nhập lại) |
| `question` | `text` | NN | Câu hỏi làm rõ gửi tới người dùng |
| `candidates` | `jsonb` | NN | Danh sách tối đa 5 ứng viên pháp lý để người dùng chọn |
| `created_at` | `timestamptz` | NN, DF=NOW() | Thời điểm tạo câu hỏi làm rõ |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm cập nhật câu hỏi làm rõ |

---

### Ký hiệu viết tắt trong cột Ràng buộc:
* **PK**: Primary Key (Khóa chính).
* **FK**: Foreign Key (Khóa ngoại).
* **NN**: Not Null (Không được rỗng).
* **DF**: Default Value (Giá trị mặc định).
* **UNIQUE**: Giá trị duy nhất không trùng lặp.
* **CHECK**: Điều kiện kiểm tra hợp lệ dữ liệu.
