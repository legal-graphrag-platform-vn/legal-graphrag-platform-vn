import json
import httpx
from typing import Generator, List, Dict
from providers.base import BaseLLMProvider
from config import Config

class OpenAIProvider(BaseLLMProvider):
    # 1.   Khởi tạo nhà cung cấp OpenAI với cấu hình bảo mật
    def __init__(self):
        self.api_key = Config.OPENAI_API_KEY
        self.model = Config.OPENAI_MODEL

    # 2.   Thực hiện việc stream câu trả lời từ OpenAI Chat Completions API
    def stream_chat(
        self, 
        prompt: str, 
        context: str, 
        history: List[Dict[str, str]]
    ) -> Generator[str, None, None]:
        # 1.   Chuẩn bị headers xác thực và payload dữ liệu gửi đi
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        messages = []
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True
        }

        url = "https://api.openai.com/v1/chat/completions"

        try:
            # 3.   Gửi request dạng POST Stream tới OpenAI API
            with httpx.stream("POST", url, headers=headers, json=payload, timeout=60.0) as r:
                r.raise_for_status()
                # 4.   Đọc từng dòng từ SSE stream trả về bởi OpenAI
                for line in r.iter_lines():
                    trimmed = line.strip()
                    if not trimmed:
                        continue
                    if trimmed.startswith("data: "):
                        data_str = trimmed[6:]
                        if data_str == "[DONE]":
                            break
                        chunk = json.loads(data_str)
                        content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            yield content
        except Exception as e:
            # 5.   Xử lý lỗi kết nối hoặc xác thực API
            yield f"\n\n**[Lỗi kết nối OpenAI API]**: Không thể hoàn thành yêu cầu. Chi tiết lỗi: `{str(e)}`"
