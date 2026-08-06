# Từ Điển Dữ Liệu Hợp Nhất (Database Schema Dictionary)
## Hệ Thống Quản Lý Ngữ Cảnh Hội Thoại & Xác Thực Người Dùng (Plan 19 & Plan 20)

Tài liệu mô tả chi tiết 8 bảng dữ liệu cơ sở dữ liệu PostgreSQL của **Legal GraphRAG Platform VN**.

---

> **KỸ THUẬT CONTEXT MEMORY (BỘ NHỚ NGỮ CẢNH HỘI THOẠI) DÙNG ĐỂ LÀM GÌ?**
> 1. **Ghi nhớ điều luật vừa nhắc**: Ghi nhớ các Điều/Khoản luật trích dẫn trong 5 câu hỏi gần nhất để hiểu đúng khi người dùng hỏi tắt (*"nói rõ hơn về điều luật đó"*, *"quy định trên bị phạt thế nào?"*).
> 2. **Viết lại câu hỏi đầy đủ (`standalone_query`)**: Tự động thay thế đại từ mơ hồ (*"hồ sơ trên"*, *"quy định đó"*) thành câu hỏi hoàn chỉnh nghĩa để mang đi tìm kiếm trên Đồ thị tri thức Neo4j (GraphRAG Search).
> 3. **Xử lý tham chiếu nhập nhằng (`AMBIGUOUS`)**: Phát hiện câu hỏi có thể hiểu theo nhiều văn bản luật khác nhau để chủ động hỏi lại người dùng thay vì đoán mò.

---

### 1. Bảng `USERS` (Hồ sơ người dùng)
Lưu trữ thông tin hồ sơ (profile) của người dùng hệ thống. Giữ khóa ngoại `account_id` liên kết 1-1 tới tài khoản đăng nhập trong bảng `ACCOUNTS`.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN, DF=gen_random_uuid() | Khóa chính định danh người dùng |
| `account_id` | `uuid` | FK(accounts.id) ON DELETE CASCADE, UNIQUE, INDEX | Khóa ngoại liên kết 1-1 tới tài khoản đăng nhập trong bảng ACCOUNTS (nullable) |
| `full_name` | `varchar(128)` | | Tên hiển thị đầy đủ của người dùng |
| `avatar_url` | `text` | | Đường dẫn ảnh đại diện của người dùng |
| `created_at` | `timestamptz` | NN, DF=NOW() | Thời điểm tạo hồ sơ người dùng |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm cập nhật thông tin người dùng mới nhất |

---

### 2. Bảng `ACCOUNTS` (Tài khoản đăng nhập)
Lưu trữ thông tin xác thực đăng nhập (Username / Password). Liên kết 1-1 với bảng `USERS` được thiết lập từ phía `users.account_id`.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN, DF=gen_random_uuid() | Khóa chính định danh tài khoản đăng nhập |
| `username` | `varchar(64)` | NN, UNIQUE, INDEX | Tên đăng nhập duy nhất của người dùng (lưu chữ thường) |
| `password_hash` | `varchar(255)` | NN | Chuỗi băm mật khẩu bảo mật (PBKDF2-HMAC-SHA256) |
| `created_at` | `timestamptz` | NN, DF=NOW() | Thời điểm đăng ký tài khoản |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm thay đổi thông tin đăng nhập gần nhất |

---

### 3. Bảng `CONVERSATIONS` (Phiên hội thoại)
Quản lý các cuộc trò chuyện của người dùng ẩn danh (Anonymous) và người dùng chính thức (User).

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh phiên hội thoại |
| `owner_kind` | `enum('ANONYMOUS','USER')` | NN, CHECK | Phân loại chủ sở hữu hội thoại (`ANONYMOUS`: Khách ẩn danh, `USER`: Người dùng đã đăng nhập) |
| `owner_principal_id` | `uuid` | NN | ID chủ sở hữu (UUID của khách ẩn danh hoặc ID của User) |
| `title` | `varchar(255)` | NN, DF='Cuộc trò chuyện mới' | Tiêu đề cuộc trò chuyện (tự động tạo từ câu hỏi đầu tiên) |
| `is_deleted` | `boolean` | NN, DF=false | Cờ đánh dấu xóa mềm cuộc trò chuyện (Soft Delete) |
| `next_user_turn_no` | `integer` | NN, DF=1, CHECK(>=1) | Số thứ tự lượt tương tác kế tiếp của người dùng |
| `created_at` | `timestamptz` | NN, DF=NOW() | Thời điểm khởi tạo cuộc trò chuyện |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm cập nhật tin nhắn cuối cùng |

---

### 4. Bảng `CONVERSATION_TURNS` (Chu trình lượt hỏi - đáp & Idempotency)
**Giải thích bản chất**: Bảng này điều phối và lưu trữ trạng thái xử lý tổng thể của 1 chu trình tương tác khép kín: `User gửi câu hỏi` ➔ `Viết lại câu hỏi` ➔ `AI truy vấn dữ liệu pháp lý & suy luận` ➔ `AI trả lời xong`. Bảng không lưu nội dung văn bản tin nhắn (nội dung chữ lưu ở `CONVERSATION_MESSAGES`), mà đóng vai trò là "Bộ não quản lý trạng thái xử lý" của lượt chat.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh lượt tương tác |
| `conversation_id` | `uuid` | FK(conversations.id), NN | Khóa ngoại thuộc cuộc trò chuyện nào |
| `client_turn_id` | `uuid` | NN, UNIQUE(conv_id, client_turn_id) | **Mã chống trùng lặp request (Idempotency Key)** từ phía Client gửi lên. Tránh bị gọi AI dư thừa khi người dùng bấm gửi 2 lần do mạng chậm. |
| `user_turn_no` | `integer` | NN, UNIQUE(conv_id, user_turn_no) | Số thứ tự lượt tương tác của người dùng trong cuộc trò chuyện (1, 2, 3...) |
| `status` | `enum` | NN | **Trạng thái xử lý tổng thể lượt chat**: <br>• `PROCESSING`: Đang trong quá trình suy luận / gọi AI. <br>• `COMPLETED`: Đã trả lời thành công. <br>• `CANNOT_ANSWER`: Không tìm thấy căn cứ pháp lý phù hợp. <br>• `NEEDS_CLARIFICATION`: Câu hỏi bị nhập nhằng, chờ người dùng làm rõ. <br>• `FAILED`: Gặp lỗi hệ thống trong quá trình xử lý. |
| `resolution_status` | `enum` | Trạng thái giải quyết ngữ cảnh tham chiếu pháp lý (`RESOLVED`: Đã xác định rõ, `AMBIGUOUS`: Bị nhập nhằng tham chiếu, `UNRESOLVED`: Chưa xác định) |
| `resolution_reason_code` | `varchar(64)` | | Mã lý do giải quyết tham chiếu (`EXPLICIT_FOUND`: Chỉ đích danh tên điều luật, `ANAPHORA_RESOLVED`: Giải quyết thành công từ thay thế, `ANAPHORA_AMBIGUOUS`: Từ thay thế bị nhập nhằng, `NO_ANAPHORA`: Câu hỏi thông thường) |
| `standalone_query` | `text` | | **Câu hỏi đã được AI viết lại độc lập đầy đủ nghĩa**: Tự động thay thế các từ tắt 'hồ sơ trên', 'quy định đó' thành tên luật cụ thể để làm đầu vào tìm kiếm trên Đồ thị Neo4j. |
| `error_code` | `varchar(64)` | | Mã lỗi chuẩn hóa (nếu lượt tương tác bị `FAILED`) |
| `response_snapshot` | `jsonb` | | Snapshot dữ liệu câu trả lời chuẩn (JSONB) dùng để Replay lại luồng stream SSE nếu trình duyệt client bị rớt mạng giữa chừng mà không phải gọi lại AI. |
| `created_at` | `timestamptz` | NN, DF=NOW() | Thời điểm bắt đầu lượt tương tác |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm hoàn thành lượt tương tác |

---

### 5. Bảng `CONVERSATION_MESSAGES` (Lịch sử nội dung tin nhắn)
Lưu trữ toàn bộ nội dung tin nhắn transcript chi tiết giữa người dùng và trợ lý AI. Trong mỗi 1 Turn của `CONVERSATION_TURNS`, sẽ có tin nhắn của `user` (câu hỏi) và tin nhắn của `assistant` (câu trả lời).

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh tin nhắn |
| `turn_id` | `uuid` | FK(conversation_turns.id), NN | Khóa ngoại thuộc lượt tương tác nào |
| `conversation_id` | `uuid` | FK(conversations.id), NN | Khóa ngoại thuộc cuộc trò chuyện nào |
| `role` | `enum` | NN | Vai trò người gửi tin nhắn (`user`: Người dùng, `assistant`: Trợ lý AI) |
| `kind` | `enum` | NN | Phân loại mục đích tin nhắn (`USER_QUERY`: Câu hỏi người dùng, `ANSWER`: Câu trả lời AI, `CANNOT_ANSWER`: Thông báo không trả lời được, `CLARIFICATION`: Câu hỏi làm rõ, `SMALL_TALK`: Giao tiếp thông thường) |
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
| `unit_id` | `varchar(256)` | NN, UNIQUE(msg_id, unit_id) | Mã định danh duy nhất của đơn vị pháp lý được trích dẫn (đồng bộ từ Đồ thị Neo4j, ví dụ: `ldn_2020_art21_cl1` đại diện cho Khoản 1 Điều 21 Luật Doanh nghiệp 2020) |
| `citation_ordinal` | `integer` | NN | Thứ tự xuất hiện của trích dẫn trong câu trả lời (1, 2, 3...) |
| `citation_label` | `text` | NN | Nhãn trích dẫn hiển thị (ví dụ: "Điều 3, Khoản 1, 01/2021/NĐ-CP") |
| `document_id` | `varchar(256)` | NN | Mã văn bản quy phạm pháp luật gốc (lấy từ Neo4j) |
| `article_id` | `varchar(256)` | | Mã Điều pháp luật liên quan (lấy từ Neo4j) |
| `clause_id` | `varchar(256)` | | Mã Khoản pháp luật liên quan (lấy từ Neo4j) |
| `deep_link` | `text` | NN | Đường dẫn liên kết sâu đến chi tiết văn bản pháp luật trên giao diện |
| `metadata_snapshot` | `jsonb` | | Snapshot thông tin bổ sung của căn cứ trích dẫn |

---

### 7. Bảng `GROUNDED_FOCUSES` (Cửa sổ ngữ cảnh tham chiếu pháp lý)
Chức năng: "Sổ tay bộ nhớ tạm các Điều/Khoản luật vừa nhắc tới" trong vòng 5 câu hỏi gần nhất để AI giải quyết câu hỏi tắt.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh bản ghi bộ nhớ |
| `conversation_id` | `uuid` | FK(conversations.id), NN | Thuộc cuộc trò chuyện nào |
| `node_id` | `varchar(256)` | NN, UNIQUE(conv_id, node_id) | Mã Đỉnh đại diện điều luật trong Đồ thị Neo4j (ví dụ: `ldn_2020_art21` đại diện cho Điều 21 Luật Doanh nghiệp 2020) |
| `node_type` | `varchar(64)` | NN | Cấp độ điều luật được ghi nhớ (`Document`: Văn bản quy phạm pháp luật, `Article`: Điều luật, `Clause`: Khoản luật) |
| `document_type` | `varchar(64)` | | Loại văn bản luật ('Luật', 'Nghị định', 'Thông tư'...) |
| `canonical_label` | `text` | NN | Tên hiển thị dễ đọc của điều luật (Ví dụ: "Điều 21, Luật Doanh nghiệp 2020") |
| `document_id` | `varchar(256)` | NN | Mã văn bản gốc từ Neo4j |
| `article_id` | `varchar(256)` | | Mã Điều gốc từ Neo4j |
| `clause_id` | `varchar(256)` | | Mã Khoản gốc từ Neo4j |
| `document_metadata` | `jsonb` | | Thông tin bổ sung của văn bản |
| `last_grounded_user_turn_no` | `integer` | NN | Lượt câu hỏi gần nhất mà điều luật này được nhắc tới (Hết hạn ghi nhớ nếu trải qua 5 câu hỏi mà không nhắc lại) |
| `citation_order` | `integer` | NN | Thứ tự xuất hiện của điều luật trong câu trả lời (1: Điều luật nhắc đầu tiên, 2: Điều luật nhắc thứ hai... giúp AI hiểu khi người dùng hỏi "Điều luật đầu tiên là gì") |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm cập nhật bộ nhớ tạm mới nhất |

---

### 8. Bảng `PENDING_CLARIFICATIONS` (Yêu cầu làm rõ tham chiếu nhập nhằng)
Tạm giữ trạng thái khi câu hỏi người dùng có tham chiếu bị nhập nhằng (`resolution_status = 'AMBIGUOUS'`), chờ người dùng phản hồi lựa chọn trắc nghiệm.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh yêu cầu làm rõ |
| `conversation_id` | `uuid` | FK(conversations.id), NN, UNIQUE | Khóa ngoại liên kết 1-1 với cuộc trò chuyện đang chờ phản hồi |
| `source_turn_id` | `uuid` | FK(conversation_turns.id), NN | Khóa ngoại đến lượt tương tác gốc phát sinh nhập nhằng |
| `mode` | `enum` | NN | Chế độ làm rõ tham chiếu (`SELECT`: Chọn từ danh sách ứng viên, `RESTATE`: Yêu cầu người dùng diễn đạt lại) |
| `question` | `text` | NN | Câu hỏi làm rõ gửi tới người dùng |
| `candidates` | `jsonb` | NN | Danh sách tối đa 5 ứng viên pháp lý để người dùng chọn trên UI |
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
