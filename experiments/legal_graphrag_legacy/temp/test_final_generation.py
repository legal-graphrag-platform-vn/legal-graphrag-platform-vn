import json
import urllib.request
import sys
from test_graph_traversal import build_context_from_graph

sys.stdout.reconfigure(encoding='utf-8')

# API KEY của DeepSeek
API_KEY = "[ENCRYPTION_KEY]"

# =====================================================================
# HÀM GỌI DEEPSEEK ĐỂ SINH CÂU TRẢ LỜI (GENERATION NODE)
# =====================================================================
def generate_final_answer(query, context):
    print("\n⏳ Đang gửi Context và Câu hỏi cho LLM (DeepSeek) để tổng hợp câu trả lời...")
    
    # Prompt System chặt chẽ để chống Ảo giác (Anti-Hallucination)
    system_prompt = """
    Bạn là một trợ lý pháp lý AI xuất sắc tại Việt Nam.
    Nhiệm vụ của bạn là trả lời câu hỏi của người dùng DỰA HOÀN TOÀN VÀO NGỮ CẢNH (Context) được cung cấp.
    
    Quy tắc bắt buộc:
    1. Tuyệt đối KHÔNG sử dụng kiến thức bên ngoài. Nếu ngữ cảnh không chứa đủ thông tin, hãy trả lời: "Tôi không có đủ dữ kiện pháp lý để trả lời câu hỏi này."
    2. LUÔN LUÔN trích dẫn rõ ràng Tên Điều, Tên Luật (ví dụ: "Theo Điều 17 của Luật Doanh nghiệp 2020...").
    3. Nếu ngữ cảnh có xuất hiện các mối liên hệ như [AMENDS] (Sửa đổi), [REPLACES] (Thay thế), hãy chú ý cảnh báo cho người dùng biết đâu là quy định cũ, đâu là quy định hiện hành.
    4. Trình bày câu trả lời ngắn gọn, súc tích, chia gạch đầu dòng rõ ràng.
    """
    
    user_prompt = f"""
    --- NGỮ CẢNH TỪ KNOWLEDGE GRAPH ---
    {context}
    --- HẾT NGỮ CẢNH ---
    
    Câu hỏi của người dùng: {query}
    """

    url = "https://api.deepseek.com/chat/completions"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {API_KEY}'
    }
    
    # Dùng model deepseek-v4-pro (nếu bạn muốn suy luận sâu) hoặc v4-flash để trả lời nhanh.
    # Ở đây dùng v4-flash để đồng bộ với phần trước và tiết kiệm chi phí.
    # Nhiệt độ (temperature) đẩy lên 0.3 để câu văn tự nhiên hơn một chút so với lúc Router (0.1)
    data = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result['choices'][0]['message']['content']
    except Exception as e:
        if hasattr(e, 'read'):
            error_body = e.read().decode('utf-8')
            return f"LỖI: {e}\nChi tiết: {error_body}"
        return f"LỖI: {e}"

# =====================================================================
# CHẠY THỬ NGHIỆM END-TO-END (GRAPH -> CONTEXT -> LLM)
# =====================================================================
if __name__ == "__main__":
    print("="*70)
    print("🚀 BẮT ĐẦU CHẠY THỬ NGHIỆM SINH CÂU TRẢ LỜI (FINAL GENERATION)")
    print("="*70)
    
    query = "Cơ quan nhà nước có được phép góp vốn bằng quyền sử dụng đất theo Luật DN 2020 không?"
    print(f"[CÂU HỎI NGƯỜI DÙNG]: {query}\n")
    
    # 1. Giả lập kết quả từ Router & Vector Search (Bước 1 & 2)
    mock_anchor_ids = ["CT_CoQuanNhaNuoc", "TN_TaiSanGopVon"]
    
    # 2. Gom ngữ cảnh (Bước 3 & 4)
    graph_context = build_context_from_graph(mock_anchor_ids, intent="factual")
    
    # 3. Chạy LLM để sinh câu trả lời (Bước 5)
    final_answer = generate_final_answer(query, graph_context)
    
    print("\n" + "="*70)
    print("🎓 CÂU TRẢ LỜI CỦA TRỢ LÝ PHÁP LÝ AI:")
    print("="*70)
    print(final_answer)
