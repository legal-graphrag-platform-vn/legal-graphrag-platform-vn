import json
import urllib.request
import os
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

# Import trực tiếp các prompt từ file của bạn
from traversal_policies import INTENT_CLASSIFICATION_PROMPT, TEMPORAL_EXTRACTION_PROMPT

# Sử dụng DeepSeek API Key mới
API_KEY = "sk-..."

print("Đã nhận DeepSeek API Key. Đang kết nối với DeepSeek API (Direct HTTP)...")

def call_deepseek(prompt):
    url = "https://api.deepseek.com/chat/completions"
    headers = {
        'Content-Type': 'application/json',
        'Authorization': f'Bearer {API_KEY}'
    }
    data = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1
    }
    
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            # Chuẩn đầu ra của DeepSeek (giống OpenAI)
            return result['choices'][0]['message']['content']
    except Exception as e:
        if hasattr(e, 'read'):
            error_body = e.read().decode('utf-8')
            return f"LỖI: {e}\nChi tiết: {error_body}"
        return f"LỖI: {e}"

test_queries = [
    "Điều kiện thành lập công ty cổ phần là gì?",
    "Thủ tục đăng ký doanh nghiệp trước khi có Nghị định 01/2021 khác với bây giờ như thế nào?",
    "Cơ quan nhà nước có được phép góp vốn bằng quyền sử dụng đất theo Luật DN 2020 không?"
]

today = datetime.now().strftime("%Y-%m-%d")

for i, query in enumerate(test_queries, 1):
    print(f"\n{'='*60}\n📌 TEST CASE {i}:\nCâu hỏi: {query}\n{'-'*60}")
    
    # 1. Test Intent Classification
    intent_prompt = INTENT_CLASSIFICATION_PROMPT.format(query=query)
    print("⏳ Đang gọi API phân loại Intent...")
    res1 = call_deepseek(intent_prompt)
    print("✅ Kết quả Intent:\n" + res1.strip())
        
    # 2. Test Temporal Extraction
    temporal_prompt = TEMPORAL_EXTRACTION_PROMPT.format(query=query, today=today)
    print("\n⏳ Đang gọi API trích xuất mốc thời gian (Temporal)...")
    res2 = call_deepseek(temporal_prompt)
    print("✅ Kết quả Temporal:\n" + res2.strip())
