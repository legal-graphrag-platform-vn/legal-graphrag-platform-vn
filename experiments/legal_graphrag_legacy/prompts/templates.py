QUERY_REWRITE_PROMPT = """
Dưới đây là lịch sử cuộc trò chuyện và câu hỏi mới nhất của người dùng.
Nhiệm vụ của bạn là viết lại câu hỏi mới nhất thành một câu hỏi độc lập (standalone query), sao cho nó bao hàm đầy đủ ý nghĩa từ lịch sử cuộc trò chuyện, mà không cần phải đọc lại lịch sử để hiểu.

Lưu ý:
- Nếu câu hỏi mới nhất vốn đã rõ ràng và độc lập, hãy giữ nguyên nó.
- Chỉ trả về đúng 1 câu hỏi được viết lại, KHÔNG giải thích gì thêm.

Lịch sử trò chuyện:
{chat_history}

Câu hỏi mới nhất: {query}
Câu hỏi độc lập:
"""

INTENT_CLASSIFICATION_PROMPT = """
Phân loại intent của câu hỏi pháp lý sau:

Classes:
- factual: Hỏi về quy định, điều kiện cụ thể
- validity: Hỏi về tình trạng hiệu lực của văn bản/điều luật
- hierarchy: Hỏi về văn bản hướng dẫn/thực thi
- comparison: So sánh quy định giữa các thời điểm
- definition: Hỏi định nghĩa khái niệm pháp lý
- multi_hop: Câu hỏi cần nhiều bước suy luận, chạm từ 2 nhãn trên trở lên

Ví dụ:
Q: "Điều kiện thành lập công ty TNHH là gì?" → factual
Q: "NĐ 78/2015 còn hiệu lực không?" → validity
Q: "Nghị định nào hướng dẫn Luật DN 2020?" → hierarchy
Q: "Quy định vốn điều lệ năm 2019 khác bây giờ như thế nào?" → comparison
Q: "Vốn điều lệ là gì?" → definition
Q: "Thủ tục mà nghị định hướng dẫn điều X quy định ra sao?" → multi_hop
Q: "Điều kiện thành lập công ty TNHH theo quy định hiện hành (còn hiệu lực) là gì?" → multi_hop

Câu hỏi: "{query}"
Intent (Trả về đúng 1 từ khóa, không giải thích):
"""

TEMPORAL_EXTRACTION_PROMPT = """
Trích xuất thông tin thời gian từ câu hỏi pháp lý sau.
Câu hỏi: "{query}"
Ngày hiện tại: {today}

Lưu ý:
- Nếu câu hỏi nhắc mốc thời gian gắn với 1 văn bản cụ thể (vd "trước khi Nghị định X có hiệu lực"),
  KHÔNG tự suy ra ngày cụ thể — chỉ trích xuất tên văn bản vào "anchor_event".
- Nếu câu hỏi không đề cập thời gian, coi như hỏi luật hiện hành (has_temporal: false).
- Ví dụ 1: "Năm 2018 quy định thế nào?" -> has_temporal: true, temporal_type: "event_context", expression: "Năm 2018", resolved_from: "2018-01-01"
- Ví dụ 2: "So sánh luật cũ và luật mới" -> has_temporal: true, temporal_type: "comparison"
- Ví dụ 3: "Trước khi có Luật DN 2020" -> has_temporal: true, temporal_type: "comparison", anchor_event: "Luật DN 2020"
- Ví dụ 4: "Quy định này còn hiệu lực không?" -> has_temporal: true, temporal_type: "validity_check"
Trả về JSON:
{{
  "has_temporal": boolean,
  "temporal_type": "validity_check" | "event_context" | "comparison" | null,
  "expression": string | null,
  "resolved_from": "YYYY-MM-DD" | null,
  "resolved_to": "YYYY-MM-DD" | null,
  "granularity": "year" | "month" | "day" | "current" | "relative_to_event" | null,
  "anchor_event": string | null
}}
"""

SYSTEM_GENERATION_PROMPT = """
Bạn là một trợ lý pháp lý AI xuất sắc tại Việt Nam.
Nhiệm vụ của bạn là trả lời câu hỏi của người dùng DỰA HOÀN TOÀN VÀO NGỮ CẢNH (Context) được cung cấp.

Quy tắc bắt buộc:
1. Tuyệt đối KHÔNG sử dụng kiến thức bên ngoài. Nếu ngữ cảnh không chứa đủ thông tin, hãy trả lời: "Tôi không có đủ dữ kiện pháp lý để trả lời câu hỏi này."
2. LUÔN LUÔN trích dẫn rõ ràng Tên Điều, Tên Luật (ví dụ: "Theo Điều 17 của Luật Doanh nghiệp 2020...").
3. Nếu ngữ cảnh có xuất hiện các mối liên hệ như [AMENDS] (Sửa đổi), [REPLACES] (Thay thế), hãy chú ý cảnh báo cho người dùng biết đâu là quy định cũ, đâu là quy định hiện hành.
4. Trình bày câu trả lời ngắn gọn, súc tích, chia gạch đầu dòng rõ ràng.
5. TRỰC TIẾP VÀO THẲNG VẤN ĐỀ. Tuyệt đối KHÔNG sử dụng các câu mào đầu thừa thãi như "Theo ngữ cảnh được cung cấp...", "Dựa vào thông tin trên...", hay "Câu trả lời là...".
"""
