"""Prompt templates cho 2-pass LLM extraction.

Nguồn: plans/04_graph_construction_pipeline.md mục "Step 2: LLM Information
Extraction". Giữ nguyên nội dung tiếng Việt + relation type list đúng spec gốc,
chỉ bổ sung hướng dẫn format JSON chặt hơn (Gemini structured output qua
`response_schema` đã ép schema, nhưng prompt rõ ràng vẫn giúp giảm nhiễu).
"""

from __future__ import annotations


ENTITY_EXTRACTION_PROMPT = """Cho điều luật sau:

---
{article_text}
---

Structural context canonical:
{structural_context}

Trích xuất các đối tượng pháp lý thực sự được đề cập trong văn bản:

1. Document:
   Văn bản pháp luật bên ngoài được viện dẫn rõ ràng.
   ID do LLM tạo ở bước này là raw extraction ID (BẮT BUỘC phải có, không được
   bỏ trống) — canonical Document ID chính thức sẽ do document
   registry/resolver xác định sau, raw ID chỉ cần đủ để nhận diện văn bản
   được viện dẫn.

2. Concept / LegalConcept:
   Khái niệm, thuật ngữ, đối tượng hoặc chế định pháp lý được quy định,
   định nghĩa hoặc sử dụng trong điều luật.
   Ví dụ: "vốn điều lệ", "cổ phần phổ thông", "điều kiện kinh doanh".

3. Entity / LegalSubject:
   Cá nhân, tổ chức, cơ quan nhà nước, loại hình doanh nghiệp hoặc
   chủ thể trực tiếp chịu sự điều chỉnh của quy định.
   Ví dụ: "công ty cổ phần", "cổ đông sáng lập",
   "cơ quan đăng ký kinh doanh".

4. Action / LegalAction:
   Hành vi hoặc hoạt động pháp lý do chủ thể thực hiện, được phép thực hiện,
   bị cấm hoặc được quy định trong điều luật.
   Ví dụ: "thành lập công ty", "góp vốn",
   "chuyển nhượng cổ phần", "giải thể".

QUY TẮC ĐẶT ID (áp dụng cho MỌI entity, kể cả Document — trường "id" là
BẮT BUỘC trên từng entity, không được bỏ trống hay bỏ qua field này):

- Mọi entity — Document, Concept, Entity, Action — đều phải có "id" dạng
  snake_case, không dấu tiếng Việt, viết thường, các từ cách nhau bằng dấu
  gạch dưới. Ví dụ: "vốn điều lệ" -> "von_dieu_le",
  "Nghị định số 78/2015/NĐ-CP" -> "nd_78_2015".
- Với Document, đặt id ngắn gọn dựa trên loại văn bản + số hiệu + năm ban
  hành nếu có trong văn bản (vd Nghị định 78/2015 -> "nd_78_2015"); nếu
  không đủ thông tin số hiệu/năm, dùng slug rút gọn từ tên văn bản.
- Không trích xuất Phụ lục/Phần/Chương/Mục/Tiểu mục/Điều/Khoản/Điểm hiện tại
  thành semantic entity. Các đơn vị này thuộc structural parser/resolver.
- Không suy diễn thêm đối tượng không được nhắc đến trong văn bản.

Chỉ trích xuất đối tượng có căn cứ trực tiếp trong điều luật."""


RELATION_EXTRACTION_PROMPT = """Cho điều luật sau và danh sách entities
đã xác định:

Điều luật:
---
{article_text}
---

Semantic entities:
{entities_json}

Structural context canonical:
{structural_context}

Xác định các quan hệ có căn cứ trực tiếp trong văn bản.

Chỉ sử dụng các loại quan hệ sau:

- DEFINES: Article/Clause -> LegalConcept.
  Dùng khi điều khoản định nghĩa hoặc giải thích một khái niệm pháp lý.

- REGULATES: Article/Clause -> LegalSubject hoặc LegalAction.
  Dùng khi điều khoản trực tiếp điều chỉnh một chủ thể hoặc hành vi.

- REQUIRES: LegalSubject -> LegalConcept.
  Dùng khi một chủ thể phải có, đáp ứng hoặc gắn với một khái niệm
  hoặc điều kiện pháp lý.
  Không dùng REQUIRES cho điều kiện của LegalAction.
  Các điều kiện hành vi thuộc runtime reasoning và không được persist
  trong Phase 1.

- REFERS_TO:
  Article/Clause/Point -> Document/Appendix/Part/Chapter/Section/Subsection/Article/Clause/Point
  khác được viện dẫn.

- AMENDS / REPLACES / REPEALS:
  Quan hệ chủ động từ văn bản hoặc đơn vị mới sang văn bản hoặc đơn vị
  bị tác động.

- GUIDES:
  Quan hệ từ văn bản cấp cao hơn sang văn bản cấp thấp hơn,
  theo whitelist ontology.

QUY TẮC ENDPOINT:

- Với Article/Clause/Point thuộc văn bản hiện tại, chỉ sử dụng canonical ID
  có trong structural_context. Không tự tạo structural ID mới.

- Với LegalSubject, LegalConcept và LegalAction, chỉ sử dụng đúng ID
  đã có trong entities_json. Không tạo semantic entity mới trong bước
  relation extraction.

- Với Document bên ngoài, chỉ sử dụng đúng raw Document ID đã được trích xuất
  trong entities_json. Không tự tạo canonical Document ID; document
  registry/resolver sẽ chuẩn hóa endpoint sau extraction.

- Không trả về CONTAINS.

QUY TẮC REFERS_TO:

- Không trích xuất lại các dẫn chiếu cấu trúc tương đối có thể được
  structural resolver xác định bằng quy tắc, ví dụ:
  "khoản này", "Điều này", "các điểm a và b khoản này".
- Chỉ đề xuất REFERS_TO khi dẫn chiếu cần xử lý bên ngoài hoặc không thể
  giải quyết hoàn toàn bằng structural resolver.

Với mỗi relation:
- evidence phải là câu hoặc đoạn nguyên văn làm căn cứ;
- confidence nằm trong khoảng 0.0-1.0.

Chỉ trả về quan hệ có evidence rõ ràng trong văn bản.
Không suy diễn."""

