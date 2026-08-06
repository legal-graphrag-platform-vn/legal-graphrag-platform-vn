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
| `owner_kind` | `enum` | NN, CHECK | **Phân loại chủ sở hữu hội thoại**: <br>• `ANONYMOUS`: Khách vãng lai chưa đăng nhập (định danh bằng UUID ngẫu nhiên lưu trong Signed Cookie). <br>• `USER`: Người dùng chính thức đã đăng ký & đăng nhập (định danh bằng ID trong bảng `USERS`). |
| `owner_principal_id` | `uuid` | NN | ID chủ sở hữu (UUID của khách ẩn danh hoặc ID của User) |
| `title` | `varchar(255)` | NN, DF='Cuộc trò chuyện mới' | Tiêu đề cuộc trò chuyện (tự động tạo từ câu hỏi đầu tiên) |
| `is_deleted` | `boolean` | NN, DF=false | Cờ đánh dấu xóa mềm cuộc trò chuyện (Soft Delete) |
| `next_user_turn_no` | `integer` | NN, DF=1, CHECK(>=1) | Số thứ tự lượt tương tác kế tiếp của người dùng |
| `created_at` | `timestamptz` | NN, DF=NOW() | Thời điểm khởi tạo cuộc trò chuyện |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm cập nhật tin nhắn cuối cùng |

---

### 4. Bảng `CONVERSATION_TURNS` (Chu trình lượt hỏi - đáp & Idempotency)
Bảng này điều phối và lưu trữ trạng thái xử lý tổng thể của 1 chu trình tương tác: `User gửi câu hỏi` ➔ `Viết lại câu hỏi` ➔ `AI truy vấn dữ liệu pháp lý & suy luận` ➔ `AI trả lời xong`.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh lượt tương tác |
| `conversation_id` | `uuid` | FK(conversations.id), NN | Khóa ngoại thuộc cuộc trò chuyện nào |
| `client_turn_id` | `uuid` | NN, UNIQUE(conv_id, client_turn_id) | **Mã chống trùng lặp request (Idempotency Key)** từ phía Client gửi lên. Tránh bị gọi AI dư thừa khi người dùng bấm gửi 2 lần do mạng chậm. |
| `user_turn_no` | `integer` | NN, UNIQUE(conv_id, user_turn_no) | Số thứ tự lượt tương tác của người dùng trong cuộc trò chuyện (1, 2, 3...) |
| `status` | `enum` | NN | **Trạng thái xử lý tổng thể lượt chat**: <br>• `PROCESSING`: Hệ thống đang trong quá trình nhận câu hỏi, phân tích ngữ cảnh và gọi AI suy luận. <br>• `COMPLETED`: AI đã truy vấn tri thức thành công và phát sinh câu trả lời hoàn chỉnh. <br>• `CANNOT_ANSWER`: Hệ thống không tìm thấy căn cứ pháp lý phù hợp để trả lời. <br>• `NEEDS_CLARIFICATION`: Câu hỏi bị nhập nhằng ngữ cảnh, tạm dừng chờ người dùng phản hồi làm rõ. <br>• `FAILED`: Gặp lỗi sự cố hệ thống hoặc timeout trong quá trình xử lý. |
| `resolution_status` | `enum` | | **Kết quả giải quyết tham chiếu ngữ cảnh câu hỏi**: <br>• `RESOLVED`: Đã xác định rõ 100% điều luật tham chiếu (người dùng nêu đích danh tên luật hoặc từ nói tắt chỉ trùng với đúng 1 điều luật vừa nhắc). <br>• `AMBIGUOUS`: Bị nhập nhằng ngữ cảnh (từ nói tắt trùng tới 2-3 điều luật khác nhau vừa đề cập ➔ Cần gửi câu hỏi làm rõ). <br>• `UNRESOLVED`: Chưa/Không xác định được ngữ cảnh (dùng từ nói tắt 'quy định đó' nhưng trước đó chưa từng đề cập tới điều luật nào). |
| `resolution_reason_code` | `varchar(64)` | | **Mã lý do giải quyết ngữ cảnh**: <br>• `EXPLICIT_FOUND`: Người dùng viết đích danh tên Điều/Luật trực tiếp trong câu hỏi. <br>• `ANAPHORA_RESOLVED`: Thuật toán đã giải quyết và thay thế thành công từ nói tắt ('hồ sơ trên' = Điều 21). <br>• `ANAPHORA_AMBIGUOUS`: Từ nói tắt bị trùng với 2-3 điều luật khác nhau trong bộ nhớ ➔ Tạo làm rõ. <br>• `NO_ANAPHORA`: Câu hỏi thông thường hoặc chào hỏi, không chứa từ nói tắt hay tên điều luật. |
| `standalone_query` | `text` | | **Câu hỏi đã được AI viết lại độc lập đầy đủ nghĩa**: Tự động thay thế các từ tắt 'hồ sơ trên', 'quy định đó' thành tên luật cụ thể để làm đầu vào tìm kiếm trên Đồ thị Neo4j. |
| `error_code` | `varchar(64)` | | Mã lỗi chuẩn hóa (nếu lượt tương tác bị `FAILED`) |
| `response_snapshot` | `jsonb` | | Snapshot dữ liệu câu trả lời chuẩn (JSONB) dùng để Replay lại luồng stream SSE nếu trình duyệt client bị rớt mạng giữa chừng mà không phải gọi lại AI. |
| `created_at` | `timestamptz` | NN, DF=NOW() | Thời điểm bắt đầu lượt tương tác |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm hoàn thành lượt tương tác |

---

### 5. Bảng `CONVERSATION_MESSAGES` (Lịch sử nội dung tin nhắn)
Lưu trữ toàn bộ nội dung tin nhắn transcript chi tiết giữa người dùng và trợ lý AI.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh tin nhắn |
| `turn_id` | `uuid` | FK(conversation_turns.id), NN | Khóa ngoại thuộc lượt tương tác nào |
| `conversation_id` | `uuid` | FK(conversations.id), NN | Khóa ngoại thuộc cuộc trò chuyện nào |
| `role` | `enum` | NN | **Vai trò người gửi tin nhắn**: <br>• `user`: Tin nhắn chứa nội dung câu hỏi hoặc phản hồi của người dùng. <br>• `assistant`: Tin nhắn chứa câu trả lời tư vấn hoặc câu hỏi làm rõ do Trợ lý AI phát sinh. |
| `kind` | `enum` | NN | **Phân loại mục đích tin nhắn**: <br>• `USER_QUERY`: Câu hỏi tra cứu pháp lý nguyên bản do người dùng gửi lên. <br>• `ANSWER`: Câu trả lời tư vấn pháp lý hoàn chỉnh của AI kèm các trích dẫn luật. <br>• `CANNOT_ANSWER`: Thông báo của AI giải thích lý do không tìm thấy căn cứ pháp lý để trả lời. <br>• `CLARIFICATION`: Câu hỏi do AI phát sinh để yêu cầu người dùng chọn làm rõ tham chiếu nhập nhằng. <br>• `SMALL_TALK`: Tin nhắn giao tiếp thông thường, chào hỏi hoặc cảm ơn không chứa tra cứu luật. |
| `content` | `text` | NN | Nội dung chi tiết của tin nhắn văn bản |
| `ordinal` | `integer` | NN, UNIQUE(conv_id, ordinal) | Thứ tự tuyến tính hiển thị tin nhắn trong cuộc trò chuyện (1, 2, 3...) |
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
| `citation_label` | `text` | NN | Nhãn trích dẫn hiển thị (ví dụ: "Điều 21, Khoản 1, Luật Doanh nghiệp 2020") |
| `document_id` | `varchar(256)` | NN | Mã văn bản quy phạm pháp luật gốc (lấy từ Neo4j) |
| `article_id` | `varchar(256)` | | Mã Điều pháp luật liên quan (lấy từ Neo4j) |
| `clause_id` | `varchar(256)` | | Mã Khoản pháp luật liên quan (lấy từ Neo4j) |
| `deep_link` | `text` | NN | Đường dẫn liên kết sâu đến chi tiết văn bản pháp luật trên giao diện |
| `metadata_snapshot` | `jsonb` | | Snapshot thông tin bổ sung của căn cứ trích dẫn |

---

### 7. Bảng `GROUNDED_FOCUSES` (Cửa sổ ngữ cảnh tham chiếu pháp lý)
**Chức năng**: "Bộ nhớ tạm các Điều/Khoản luật vừa nhắc tới" trong vòng 5 câu hỏi gần nhất để AI giải quyết câu hỏi tắt.

**Ví dụ Kịch bản Update dữ liệu thực tế**:
- **Lượt 1 (`user_turn_no = 1`)**: AI trích dẫn Điều 21 (đứng đầu) và Điều 23 (đứng thứ hai).
  ➔ Ghi nhận Điều 21 có `citation_order = 1`, `last_grounded_user_turn_no = 1`.
  ➔ Ghi nhận Điều 23 có `citation_order = 2`, `last_grounded_user_turn_no = 1`.
- **Lượt 2 (`user_turn_no = 2`)**: User hỏi *"thời hạn của Điều đầu tiên?"* ➔ AI tra `citation_order = 1` để biết đó là Điều 21 và trả lời.
  ➔ Cập nhật `last_grounded_user_turn_no` của Điều 21 lên `= 2` (Reset đồng hồ 5 lượt).
- **Lượt 7 (`user_turn_no = 7`)**: Quá 5 lượt không nhắc lại Điều 23 (7 - 1 = 6 > 5) ➔ Tự động XÓA (DELETE) Điều 23 khỏi bảng.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh bản ghi bộ nhớ |
| `conversation_id` | `uuid` | FK(conversations.id), NN | Thuộc cuộc trò chuyện nào |
| `node_id` | `varchar(256)` | NN, UNIQUE(conv_id, node_id) | Mã Đỉnh đại diện điều luật trong Đồ thị Neo4j (ví dụ: `ldn_2020_art21` đại diện cho Điều 21 Luật Doanh nghiệp 2020) |
| `node_type` | `varchar(64)` | NN | **Cấp độ điều luật được ghi nhớ**: <br>• `Document`: Toàn bộ Văn bản. <br>• `Article`: Một Điều luật cụ thể. <br>• `Clause`: Một Khoản luật cụ thể. |
| `document_type` | `varchar(64)` | | Loại văn bản luật ('Luật', 'Nghị định', 'Thông tư'...) |
| `canonical_label` | `text` | NN | Tên hiển thị dễ đọc của điều luật (Ví dụ: "Điều 21, Luật Doanh nghiệp 2020") |
| `document_id` | `varchar(256)` | NN | Mã văn bản gốc từ Neo4j |
| `article_id` | `varchar(256)` | | Mã Điều gốc từ Neo4j |
| `clause_id` | `varchar(256)` | | Mã Khoản gốc từ Neo4j |
| `document_metadata` | `jsonb` | | Thông tin bổ sung phụ trợ của văn bản (dạng JSON) |
| `last_grounded_user_turn_no` | `integer` | NN | **Số lượt câu hỏi gần nhất mà điều luật này được trích dẫn**: Dùng để tính TTL của bộ nhớ tạm. Tự động UPDATE số lượt mới khi được nhắc lại, và tự động DELETE bản ghi nếu `Lượt_Hiện_Tại - last_grounded_user_turn_no > 5`. |
| `citation_order` | `integer` | NN | **Thứ tự xuất hiện của điều luật trong câu trả lời của AI (1, 2, 3...)**: Ghi nhận vị trí xuất hiện đầu tiên, thứ hai... để giúp AI hiểu khi người dùng hỏi các câu hỏi thứ tự như *"nội dung đầu tiên"*, *"điều luật thứ hai"*. |
| `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm cập nhật bộ nhớ tạm mới nhất |

---

### 8. Bảng `PENDING_CLARIFICATIONS` (Yêu cầu làm rõ tham chiếu nhập nhằng)
Tạm giữ trạng thái khi câu hỏi người dùng có tham chiếu bị nhập nhằng (`resolution_status = 'AMBIGUOUS'`), chờ người dùng phản hồi lựa chọn.

| Tên cột | Kiểu dữ liệu | Ràng buộc | Giải thích |
|---|---|---|---|
| `id` | `uuid` | PK, NN | Khóa chính định danh yêu cầu làm rõ |
| `conversation_id` | `uuid` | FK(conversations.id), NN, UNIQUE | Khóa ngoại liên kết 1-1 với cuộc trò chuyện đang chờ phản hồi |
| `source_turn_id` | `uuid` | FK(conversation_turns.id), NN | Khóa ngoại đến lượt tương tác gốc phát sinh nhập nhằng |
| `mode` | `enum` | NN | **Chế độ làm rõ tham chiếu**: <br>• `SELECT`: Hiển thị danh sách các lựa chọn (`candidates`) để người dùng chọn điều luật đúng. <br>• `RESTATE`: Yêu cầu người dùng diễn đạt lại câu hỏi bằng cách nhập từ khóa đầy đủ hơn (khi không thể tạo danh sách ứng viên). |
| `question` | `text` | NN | Câu hỏi làm rõ gửi tới người dùng (ví dụ: *"Bạn đang muốn hỏi về vốn điều lệ theo Luật Doanh nghiệp 2020 hay Nghị định 01/2021/NĐ-CP?"*) |
| `candidates` | `jsonb` | NN | Danh sách ứng viên pháp lý dạng JSONB để hiển thị trên UI. |
| `created_at` | `timestamptz` | NN, DF=NOW() | Thời điểm tạo câu hỏi làm rõ |
<!-- | `updated_at` | `timestamptz` | NN, DF=NOW() | Thời điểm cập nhật câu hỏi làm rõ | -->

---

### Ký hiệu viết tắt trong cột Ràng buộc:
* **PK**: Primary Key (Khóa chính).
* **FK**: Foreign Key (Khóa ngoại).
* **NN**: Not Null (Không được rỗng).
* **DF**: Default Value (Giá trị mặc định).
* **UNIQUE**: Giá trị duy nhất không trùng lặp.
* **CHECK**: Điều kiện kiểm tra hợp lệ dữ liệu.
