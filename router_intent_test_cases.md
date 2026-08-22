# Bộ Câu Hỏi Kiểm Thử Phân Loại Ý Định (Intent Router Test Cases - Lĩnh vực Doanh Nghiệp)

Dưới đây là bộ dữ liệu các câu hỏi mẫu được thiết kế đặc biệt để quét qua toàn bộ 6 loại Intent của hệ thống `Router`, **được giới hạn hoàn toàn trong domain Luật Doanh nghiệp**. Bạn có thể sử dụng bộ câu hỏi này để kiểm thử nhằm chứng minh khả năng phân loại tự động bằng Rule/Regex.

## 1. DEFINITION (Hỏi định nghĩa)

_Dấu hiệu nhận biết: "là gì", "định nghĩa", "được hiểu thế nào", "khái niệm"_

| Câu hỏi                                                 | Ý định kỳ vọng | Lý giải                                           |
| ------------------------------------------------------- | -------------- | ------------------------------------------------- |
| Thế nào là công ty trách nhiệm hữu hạn một thành viên?  | `definition`   | Bắt được từ khóa "Thế nào là"                     |
| Định nghĩa về vốn điều lệ theo quy định hiện hành.      | `definition`   | Bắt được từ khóa "Định nghĩa"                     |
| Khái niệm người quản lý doanh nghiệp được hiểu thế nào? | `definition`   | Bắt được từ khóa "Khái niệm", "được hiểu thế nào" |

## 2. HIERARCHY (Hỏi cấu trúc thứ bậc / Văn bản hướng dẫn)

_Dấu hiệu nhận biết: "thuộc chương", "thuộc điều", "nằm ở chương", "văn bản...hướng dẫn"_

| Câu hỏi                                                       | Ý định kỳ vọng | Lý giải                         |
| ------------------------------------------------------------- | -------------- | ------------------------------- |
| Quy định về tổ chức quản lý công ty cổ phần nằm ở chương mấy? | `hierarchy`    | Bắt được từ khóa "nằm ở chương" |
| Điều 15 có thuộc chương II của Luật Doanh nghiệp 2020 không?  | `hierarchy`    | Bắt được từ khóa "thuộc chương" |

## 3. VALIDITY (Hỏi hiệu lực thời gian / Văn bản thay thế)

_Dấu hiệu nhận biết: "sửa đổi", "bãi bỏ", "thay thế", "hết hiệu lực", "còn hiệu lực"_

| Câu hỏi                                                     | Ý định kỳ vọng | Lý giải                          |
| ----------------------------------------------------------- | -------------- | -------------------------------- |
| Nghị định 47/2021 về doanh nghiệp xã hội đã bị bãi bỏ chưa? | `validity`     | Bắt được từ khóa "bãi bỏ"        |
<!-- | Văn bản nào sửa đổi, thay thế Luật Doanh nghiệp 2014?       | `validity`     | Bắt được cụm "sửa đổi, thay thế" | -->

## 4. COMPARISON (Hỏi so sánh / Thay đổi trước sau)

_Dấu hiệu nhận biết: "so sánh", "khác nhau", "giống nhau", "trước và sau"_

| Câu hỏi                                                                       | Ý định kỳ vọng | Lý giải                                    |
| ----------------------------------------------------------------------------- | -------------- | ------------------------------------------ |
| So sánh sự khác nhau giữa cổ phần phổ thông và cổ phần ưu đãi biểu quyết.     | `comparison`   | Bắt được từ khóa "So sánh", "khác nhau"    |
| Sự giống nhau và khác nhau giữa công ty cổ phần và công ty TNHH.              | `comparison`   | Bắt được từ khóa "giống nhau", "khác nhau" |
| Quyền của cổ đông thay đổi thế nào trước và sau khi có Luật Doanh nghiệp mới? | `comparison`   | Bắt được từ khóa "trước và sau"            |

## 5. MULTI-HOP (Câu hỏi phức tạp / Đòi hỏi suy luận nhiều bước)

_Dấu hiệu nhận biết: "nhiều bước", "dẫn chiếu", "thủ tục...hướng dẫn"_

| Câu hỏi                                                                     | Ý định kỳ vọng | Lý giải                       |
| --------------------------------------------------------------------------- | -------------- | ----------------------------- |
| Thủ tục đăng ký thành lập công ty cổ phần phải qua nhiều bước như thế nào?  | `multi_hop`    | Bắt được từ khóa "nhiều bước" |
| Cơ quan nào có thẩm quyền xử lý, có dẫn chiếu từ điều 16 Luật Doanh nghiệp? | `multi_hop`    | Bắt được từ khóa "dẫn chiếu"  |

## 6. FACTUAL (Câu hỏi nghiệp vụ / Tình huống)

_Trường hợp mặc định: Không chứa từ khóa của 5 loại trên._

| Câu hỏi                                                                        | Ý định kỳ vọng | Lý giải                                                |
| ------------------------------------------------------------------------------ | -------------- | ------------------------------------------------------ |
| Chủ doanh nghiệp tư nhân có được quyền cho thuê doanh nghiệp của mình không?   | `factual`      | Không chứa keyword đặc thù. Rơi vào Fallback mặc định. |
| Công ty TNHH 1 thành viên có được phép phát hành cổ phần không?                | `factual`      | Không chứa keyword đặc thù. Rơi vào Fallback mặc định. |
| Giám đốc công ty cổ phần có thể đồng thời làm Giám đốc của công ty khác không? | `factual`      | Không chứa keyword đặc thù. Rơi vào Fallback mặc định. |

---

> [!TIP]
> **Nhóm 6 (Factual)** là nhóm mặc định (Fallback). Khi hệ thống không tìm thấy các từ khóa đặc thù (như "là gì", "bãi bỏ", "so sánh"...), nó sẽ tự động coi đây là một câu hỏi tra cứu nghiệp vụ thông thường (Factual) và áp dụng chiến thuật tìm kiếm tiêu chuẩn (Hybrid Search).
