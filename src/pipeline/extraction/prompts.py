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

Trích xuất tất cả entities được đề cập:

1. Documents bên ngoài được viện dẫn rõ ràng

2. Concept / LegalConcept:
   Khái niệm, thuật ngữ, đối tượng hoặc chế định pháp lý được quy định,
   định nghĩa hoặc sử dụng trong điều luật.
   Ví dụ: "vốn điều lệ", "cổ phần phổ thông", "điều kiện kinh doanh".

3. Entity / LegalSubject:
   Cá nhân, tổ chức, cơ quan nhà nước, loại hình doanh nghiệp hoặc
   chủ thể trực tiếp chịu sự điều chỉnh của quy định.
   Ví dụ: "công ty cổ phần", "cổ đông sáng lập", "cơ quan đăng ký kinh doanh".

4. Action / LegalAction:
   Hành vi hoặc hoạt động pháp lý do chủ thể thực hiện, được phép thực hiện,
   bị cấm hoặc được quy định trong điều luật.
   Ví dụ: "thành lập công ty", "góp vốn", "chuyển nhượng cổ phần", "giải thể".

QUY TẮC ĐẶT ID (BẮT BUỘC):
- Đối với Concept/Entity/Action/Document khác: Đặt tên tiếng Việt không dấu, viết thường, cách nhau bằng gạch dưới (Ví dụ: "cong_ty_co_phan", "co_quan_dang_ky_kinh_doanh").
- KHÔNG trích xuất Phần/Chương/Mục/Tiểu mục/Điều/Khoản/Điểm hiện tại thành entity. Chúng thuộc structural parser/resolver.

Chỉ trích xuất entity thực sự được nhắc tới trong văn bản, không suy diễn thêm."""

RELATION_EXTRACTION_PROMPT = """Cho điều luật sau và danh sách entities đã xác định:
---
Article: {article_text}
Entities: {entities_json}
Structural context: {structural_context}
---

Xác định các quan hệ giữa entities. Chỉ sử dụng các loại quan hệ và tuân thủ chặt chẽ ràng buộc sau:

- DEFINES: Đi từ Article/Clause -> LegalConcept.
  Dùng khi điều khoản định nghĩa hoặc giải thích một khái niệm pháp lý.

- REGULATES: Đi từ Article/Clause -> LegalSubject hoặc LegalAction.
  Dùng khi điều khoản điều chỉnh trực tiếp một chủ thể hoặc một hành vi.

- REQUIRES: Đi từ LegalSubject -> LegalConcept.
  Dùng khi một chủ thể phải có, đáp ứng hoặc gắn với một khái niệm/điều kiện pháp lý.
  KHÔNG dùng REQUIRES để biểu diễn điều kiện của một LegalAction. Điều kiện của
  hành vi thuộc lớp runtime (HAS_CONDITION) và không được trích xuất ở Phase 1.

- REFERS_TO: Đi từ Article/Clause/Point -> Document/Part/Chapter/Section/Subsection/Article/Clause/Point khác.
- AMENDS / REPLACES / REPEALS: Quan hệ chủ động từ văn bản hoặc đơn vị mới sang văn bản hoặc đơn vị bị tác động.
- GUIDES: Đi từ văn bản cấp cao hơn sang văn bản cấp thấp hơn trong whitelist ontology.

Với mỗi relation, bắt buộc có "evidence" là câu văn nguyên gốc làm cơ sở, và "confidence" thể hiện mức tự tin của bạn (0.0-1.0).
Không được trả về CONTAINS. Chỉ dùng canonical structural ID có trong structural context; không tự tạo ID Phần/Chương/Mục/Tiểu mục/Điều/Khoản/Điểm.
Không trích xuất lại dẫn chiếu cấu trúc tương đối có thể xác định bằng quy tắc, ví dụ
"khoản này", "Điều này" hoặc "các điểm a và b khoản này". Các dẫn chiếu này được
structural resolver xử lý trước. Chỉ đề xuất REFERS_TO khi dẫn chiếu cần liên kết
văn bản bên ngoài hoặc diễn giải ngữ nghĩa/mơ hồ.
Chỉ trả về quan hệ có evidence rõ ràng trong văn bản, không suy diễn."""
