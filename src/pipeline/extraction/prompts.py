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
2. Concepts pháp lý (khái niệm, thuật ngữ chuyên ngành)
3. Entities (loại hình doanh nghiệp, cơ quan, chủ thể)
4. Actions (hành vi pháp lý như thành lập, góp vốn, giải thể)

QUY TẮC ĐẶT ID (BẮT BUỘC):
- Đối với Concept/Entity/Document khác: Đặt tên tiếng Việt không dấu, viết thường, cách nhau bằng gạch dưới (Ví dụ: "cong_ty_co_phan", "co_quan_dang_ky_kinh_doanh").
- KHÔNG trích xuất Điều/Khoản/Điểm hiện tại thành entity. Chúng đã có trong structural context.

Chỉ trích xuất entity thực sự được nhắc tới trong văn bản, không suy diễn thêm."""

RELATION_EXTRACTION_PROMPT = """Cho điều luật sau và danh sách entities đã xác định:
---
Article: {article_text}
Entities: {entities_json}
Structural context: {structural_context}
---

Xác định các quan hệ giữa entities. Chỉ sử dụng các loại quan hệ và tuân thủ chặt chẽ ràng buộc sau:
- DEFINES: Đi từ Article/Clause -> Concept.
- REGULATES: Đi từ Article/Clause -> Entity hoặc Action.
- REQUIRES: Đi từ Entity -> Concept.
- REFERS_TO: Đi từ Article/Clause/Point -> Article/Clause/Point/Document khác.
- AMENDS / REPLACES / REPEALS: Quan hệ chủ động từ văn bản hoặc đơn vị mới sang văn bản hoặc đơn vị bị tác động.
- GUIDES: Đi từ văn bản cấp cao hơn sang văn bản cấp thấp hơn trong whitelist ontology.

Với mỗi relation, bắt buộc có "evidence" là câu văn nguyên gốc làm cơ sở, và "confidence" thể hiện mức tự tin của bạn (0.0-1.0).
Không được trả về CONTAINS. Chỉ dùng canonical structural ID có trong structural context; không tự tạo ID Điều/Khoản/Điểm.
Chỉ trả về quan hệ có evidence rõ ràng trong văn bản, không suy diễn."""
