# Supplemental crawl artifacts

> **Status:** Proposed experiment-local sidecars; not implemented yet.

## Scope

`properties.json` và `diagram.json` là hai file phụ trợ cho crawler tại
`experiments/luatvietnam_crawler`. Mục tiêu là giữ thêm dữ liệu đã có trên trang
LuatVietnam để có thể xử lý lại sau này mà không phải crawl lại.

Hai file này:

- không thay đổi `metadata.json` hiện tại;
- không phải contract của `src/pipeline`;
- không định nghĩa node, edge hoặc schema Neo4j;
- không được copy tự động sang `data/raw`;
- chỉ nằm trong output của experiment cho đến khi có bước promotion riêng.

Output của một văn bản sau khi bổ sung sidecar:

```text
experiments/luatvietnam_crawler/output/raw/LTV_<external_id>/
├── metadata.json       # giữ nguyên
├── source.txt          # giữ nguyên
├── source.html         # giữ nguyên DOM để parse lại
├── properties.json     # thuộc tính chi tiết phụ trợ
└── diagram.json        # các nhóm văn bản liên quan trên tab Lược đồ
```

Các hồ sơ mới nhất trong `output/raw` là nguồn tham chiếu cho experiment. Cấu
trúc cũ trong `src/pipeline` không được dùng để ép schema cho hai sidecar này.

## `properties.json`

```json
{
  "number": "09/2026/TT-BTP",
  "document_type": "Thông tư",
  "sector": "Tư pháp",
  "issued_date": "15/06/2026",
  "field": "Kiểm soát thủ tục hành chính",
  "effective_date": "01/08/2026",
  "status": "Chưa có hiệu lực",
  "expiry_date": null,
  "issuing_authority": "Bộ Tư pháp",
  "signer_title": "Bộ trưởng",
  "signer_name": "Hoàng Thanh Tùng"
}
```

Mapping cố định:

| Nhãn nguồn | JSON field |
|---|---|
| Số hiệu | `number` |
| Loại văn bản | `document_type` |
| Ngành | `sector` |
| Ngày ban hành | `issued_date` |
| Lĩnh vực | `field` |
| Ngày có hiệu lực | `effective_date` |
| Tình trạng hiệu lực | `status` |
| Ngày hết hiệu lực | `expiry_date` |
| Cơ quan ban hành | `issuing_authority` |
| Chức danh | `signer_title` |
| Người ký | `signer_name` |

Không thêm field khác vào `properties.json`. Không đổi format ngày hoặc enum.
Nếu nguồn là `--`, chuỗi rỗng hoặc không có giá trị thì lưu JSON `null`.
`metadata.json` không thay đổi.

## `diagram.json`

`diagram.json` chỉ phản ánh những gì trang LuatVietnam hiển thị trong tab
**Lược đồ**. Không đổi nhãn website thành relation kỹ thuật và không suy luận
chiều graph ở bước crawl.

Ví dụ:

```json
{
  "schema_version": "luatvietnam-diagram-v1",
  "external_id": "441828",
  "source_url": "https://luatvietnam.vn/doanh-nghiep/thong-tu-108-2026-tt-btc-huong-dan-ke-toan-co-phan-hoa-doanh-nghiep-nha-nuoc-441828-d1.html",
  "fetched_at": "2026-07-29T22:30:00+07:00",
  "groups": [
    {
      "label": "Căn cứ ban hành",
      "declared_count": 2,
      "items": [
        {
          "title": "Nghị định số 06/2026/NĐ-CP quy định về tổ chức và hoạt động của Ngân hàng Chính sách xã hội",
          "number": "06/2026/NĐ-CP",
          "url": "https://luatvietnam.vn/...-426422-d1.html",
          "external_id": "426422"
        },
        {
          "title": "Nghị định số 29/2025/NĐ-CP quy định chức năng, nhiệm vụ, quyền hạn và cơ cấu tổ chức của Bộ Tài chính",
          "number": "29/2025/NĐ-CP",
          "url": "https://luatvietnam.vn/...-391470-d1.html",
          "external_id": "391470"
        }
      ]
    },
    {
      "label": "Văn bản sửa đổi bổ sung",
      "declared_count": 0,
      "items": []
    }
  ]
}
```

### Quy tắc

- Giữ nguyên `label` hiển thị trên website, chỉ bỏ phần số lượng như `(2)`.
- Tách số lượng sang `declared_count` và kiểm tra nó khớp `items.length`.
- Giữ thứ tự group và item như trên trang để dễ audit.
- Với item có link, giữ cả `title`, canonical `url` và `external_id`.
- `number` được parse khi nhận diện chắc chắn; nếu không thì để `null`.
- Group rỗng có thể được giữ với `declared_count: 0` để phản ánh snapshot trang.
- Không thêm `graph_id`, tên relation chuẩn hóa, direction hoặc trạng thái resolve.
- Không tạo thêm request chỉ để điền field thiếu của item. Việc crawl các URL
  liên quan phải là một job riêng, tuân thủ request budget hiện tại.
- Ghi file atomically và không làm hỏng ba artifact đang có nếu parse Lược đồ
  thất bại. Khi thất bại, job chính vẫn có thể hoàn tất và report lỗi sidecar.

## Lý do cấu trúc này thuận lợi cho tích hợp sau

Không cần thiết kế theo pipeline hiện tại, nhưng crawler nên giữ các khóa nguồn
ổn định để một adapter tương lai có đủ dữ liệu làm việc:

- `external_id` để nhận diện hồ sơ LuatVietnam;
- `number` để đối chiếu số hiệu văn bản;
- `source_url` để truy vết và crawl lại;
- raw value để không mất thông tin khi parser hiện tại chưa hiểu;
- `schema_version` để migrate artifact khi format thay đổi.

Mọi mapping sang contract chính thức thuộc về bước promotion/adapter riêng,
không thuộc crawler và không nằm trong phạm vi tài liệu này.

## Gợi ý triển khai sau này

1. Cho `save_document()` ghi `properties.json` bằng mapping cố định 11 field ở
   trên, không thêm field phụ.
2. Viết parser riêng cho tab/container Lược đồ, trả về `groups` và `items` đúng
   cấu trúc nguồn.
3. Thêm unit test bằng HTML fixture đã lưu, không gọi website thật.
4. Khi sidecar lỗi, giữ nguyên `metadata.json`, `source.txt`, `source.html` và ghi
   lỗi vào report thay vì làm hỏng crawl chính.
