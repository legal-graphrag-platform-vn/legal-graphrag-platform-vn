# Quy Trình Hoạt Động (Workflow) của Hierarchy Parser

Tài liệu này mô tả chi tiết luồng xử lý và kiến trúc của module **Parser** trong việc cấu trúc hóa văn bản pháp luật Việt Nam. Quy trình đã được tách biệt thành **2 luồng xử lý riêng biệt** (không sử dụng cơ chế tự động fallback dự phòng để đảm bảo độ chính xác tuyệt đối theo chỉ định của người dùng).

---

## 1. Sơ đồ Luồng Hoạt Động (Workflow Diagram)

```text
[ Lệnh parse từ CLI ]
        │
        ├──► [--ocr] (PDF Scan/Ảnh chụp)
        │         │
        │         ▼
        │   extract_lines_via_ocr()
        │   (Tiền xử lý ảnh: xám + tương phản ──► Tesseract OCR)
        │         │
        │         ▼
        │   parse_lines(..., lenient_article=True)
        │   (Sử dụng regex nới lỏng ARTICLE_RE_LENIENT chống lỗi OCR)
        │
        └──► [--no-ocr] (Mặc định - PDF sạch từ Word/HTML)
                  │
                  ├──► [backend == "pypdf"] ──► extract_lines_via_pypdf()
                  │
                  └──► [backend == "auto"]  ──► extract_lines_with_font() (PyMuPDF)
                  │
                  ▼
            parse_lines(..., lenient_article=False)
            (Sử dụng regex nghiêm ngặt ARTICLE_RE chặn trích dẫn lồng)
```

---

## 2. Chi Tiết 2 Luồng Xử Lý Riêng Biệt

### Luồng 1: Trích xuất bằng OCR (`--ocr`)
Dành riêng cho các file PDF scan, ảnh chụp, tài liệu bản cứng ký số `.signed.pdf` (không có lớp text layer để bôi đen/copy).

1. **OCR Tesseract**: Hàm [extract_lines_via_ocr](file:///D:/Workspace/Project/legal-graphrag/pipline/src/parser/hierarchy_parser.py#L225) sẽ render các trang PDF thành ảnh độ phân giải cao ($400$ DPI), áp dụng bộ tiền xử lý ảnh (`grayscale` + `autocontrast`), sau đó gọi Tesseract OCR với gói ngôn ngữ tiếng Việt (`lang="vie"`).
2. **Regex mềm dẻo (`lenient_article=True`)**: Khi chạy luồng OCR, hàm [parse_lines](file:///D:/Workspace/Project/legal-graphrag/pipline/src/parser/hierarchy_parser.py#L58) sử dụng biểu thức chính quy `ARTICLE_RE_LENIENT` từ [patterns.py](file:///D:/Workspace/Project/legal-graphrag/pipline/src/parser/patterns.py). Regex này cho phép tối đa 2 ký tự rác đứng trước từ khóa `"Điều"` (nhằm khắc phục các lỗi bẩn/vết scan nhòe thường gặp).

---

### Luồng 2: Trích xuất bằng Text Layer (`--no-ocr` - Mặc định)
Dành cho các file PDF sạch được export trực tiếp từ Microsoft Word, trang web HTML hoặc tài liệu có text layer chuẩn.

1. **Lựa chọn Backend trích xuất**:
   * **PyMuPDF (`backend="auto"`)**: Sử dụng [extract_lines_with_font](file:///D:/Workspace/Project/legal-graphrag/pipline/src/parser/hierarchy_parser.py#L198) để lấy toàn bộ text dòng kèm thông tin kích thước cỡ chữ (`font_size`) và định dạng `bold` giúp nhận diện chính xác các tiêu đề.
   * **pypdf (`backend="pypdf"`)**: Sử dụng [extract_lines_via_pypdf](file:///D:/Workspace/Project/legal-graphrag/pipline/src/parser/hierarchy_parser.py#L269) để trích xuất text thuần với tốc độ tối đa, bỏ qua kiểm tra font.
2. **Regex nghiêm ngặt (`lenient_article=False`)**: Sử dụng biểu thức chính quy `ARTICLE_RE` chặt chẽ từ [patterns.py](file:///D:/Workspace/Project/legal-graphrag/pipline/src/parser/patterns.py). Yêu cầu khớp chính xác tuyệt đối chữ `"Điều"`. Việc này giúp ngăn chặn triệt để tình trạng nhận diện nhầm các dòng trích dẫn lồng trong ngoặc kép thành Điều cấp cao mới.

---

## 3. Máy Trạng Thế Cốt Lõi (`parse_lines`)

Sau khi trích xuất danh sách các dòng văn bản từ một trong hai luồng trên, máy trạng thái (State Machine) sẽ duyệt qua từng dòng để xây dựng cấu trúc cây phân cấp:

```text
Dòng văn bản ──► [Kiểm tra quote_depth] ──(nếu > 0)──► Nối tiếp nội dung cha (Continuation)
                      │
                  (nếu == 0)
                      │
                      ├──► Khớp Chương (CHAPTER_RE) ──► Chờ Tiêu Đề Chương (looks_like_title)
                      ├──► Khớp Điều (ARTICLE_RE / ARTICLE_RE_LENIENT) ──► Tạo Điều Mới
                      ├──► Khớp Khoản (CLAUSE_RE) ──► Tạo Khoản Mới thuộc Điều hiện tại
                      ├──► Khớp Điểm (POINT_RE) ──► Tạo Điểm Mới thuộc Khoản hiện tại
                      └──► Không khớp gì ──► Nối tiếp nội dung (Điểm ➔ Khoản ➔ Điều)
```

### Xử lý khối trích dẫn sửa đổi luật (`quote_depth`)
> [!IMPORTANT]
> Đây là giải pháp mấu chốt để xử lý các văn bản có dạng "Sửa đổi, bổ sung".
* **Thách thức**: Văn bản sửa đổi thường trích dẫn nguyên văn một đoạn luật cũ/mới trong cặp ngoặc kép `“...”`, trong đó tự bản thân nó lại chứa các phân cấp riêng của nó như `Điều X`, `1. Khoản 1`, `a) Điểm a`. Nếu parse bình thường sẽ làm gãy hoàn toàn cấu trúc cây của văn bản gốc.
* **Giải pháp**: Parser đếm số lượng ngoặc kép `“` (tăng độ sâu) và `”` (giảm độ sâu) tích lũy qua từng dòng. Khi đang ở trong khối trích dẫn (`quote_depth > 0`), parser **bỏ qua toàn bộ việc so khớp regex cấu trúc**, chỉ coi dòng đó là nội dung tiếp nối văn bản thường của phần tử cha đang mở.

---

## 4. Đóng Gói & Xuất Kết Quả (Serialization)
* Sau khi duyệt hết dòng cuối cùng, các builders sẽ dọn dẹp khoảng trắng dư thừa ở đầu và cuối mỗi phần tử.
* Dữ liệu phân cấp được cấu trúc hóa chặt chẽ theo Pydantic model [ParsedDocument](file:///D:/Workspace/Project/legal-graphrag/pipline/src/parser/models.py).
* Ghi dữ liệu ra tệp JSON cấu trúc tại `data/processed/<doc_id>/hierarchy.json`.
