import json
import httpx
from typing import Generator, List, Dict
from providers.base import BaseLLMProvider
from config import Config

class GeminiProvider(BaseLLMProvider):
    # 1.   Khởi tạo Gemini provider với API Key và Model được cấu hình
    def __init__(self):
        self.api_key = Config.GEMINI_API_KEY
        self.model = Config.GEMINI_MODEL

    # 2.   Thực hiện việc stream câu trả lời từ Gemini API bằng HTTP POST (SSE)
    def stream_chat(
        self, 
        prompt: str, 
        context: str, 
        history: List[Dict[str, str]]
    ) -> Generator[str, None, None]:
        # 1.   Chuẩn bị danh sách contents cho Gemini (Gemini yêu cầu vai trò là 'user' hoặc 'model')
        contents = []
        for msg in history:
            role = "user" if msg["role"] == "user" else "model"
            contents.append({
                "role": role,
                "parts": [{"text": msg["content"]}]
            })
            
        # Thêm tin nhắn hiện tại của người dùng vào cuối danh sách
        contents.append({
            "role": "user",
            "parts": [{"text": prompt}]
        })

        # 2.   Thiết lập cấu trúc Payload theo chuẩn API của Google Gemini (không dùng system instruction)
        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": 0.3
            }
        }

        # 4.   Xác định URL endpoint stream hỗ trợ định dạng SSE (alt=sse)
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:streamGenerateContent"
            f"?alt=sse&key={self.api_key}"
        )

        headers = {
            "Content-Type": "application/json"
        }

        try:
            # 5.   Thực hiện kết nối HTTP POST Stream sử dụng httpx
            with httpx.stream("POST", url, headers=headers, json=payload, timeout=60.0) as r:
                r.raise_for_status()
                # 6.   Đọc dữ liệu trả về từ Google SSE stream
                for line in r.iter_lines():
                    trimmed = line.strip()
                    if not trimmed:
                        continue
                    if trimmed.startswith("data: "):
                        data_str = trimmed[6:]
                        chunk = json.loads(data_str)
                        
                        # Trích xuất đoạn text sinh ra trong chunk hiện tại
                        text = (
                            chunk.get("candidates", [{}])[0]
                            .get("content", {})
                            .get("parts", [{}])[0]
                            .get("text", "")
                        )
                        if text:
                            yield text
        except Exception as e:
            # 7.   Xử lý ngoại lệ lỗi gọi API
            yield f"\n\n**[Lỗi kết nối Gemini API]**: Không thể kết nối tới Google Generative Language API. Chi tiết: `{str(e)}`"
