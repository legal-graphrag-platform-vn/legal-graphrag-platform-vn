import json
import httpx
from typing import Generator, List, Dict
from providers.base import BaseLLMProvider
from config import Config

class OllamaProvider(BaseLLMProvider):
    # 1.   Khởi tạo nhà cung cấp Ollama với cấu hình từ Config
    def __init__(self):
        self.base_url = Config.OLLAMA_BASE_URL
        self.model = Config.OLLAMA_MODEL

    # 2.   Thực hiện việc stream câu trả lời từ Ollama cục bộ
    def stream_chat(
        self, 
        prompt: str, 
        context: str, 
        history: List[Dict[str, str]]
    ) -> Generator[str, None, None]:
        # 1.   Chuẩn bị danh sách tin nhắn gửi sang Ollama (gồm cả lịch sử hội thoại)
        messages = []
        for msg in history:
            messages.append({"role": msg["role"], "content": msg["content"]})
        messages.append({"role": "user", "content": prompt})

        # 2.   Gửi request dạng POST Stream tới API của Ollama
        url = f"{self.base_url}/api/chat"
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True
        }

        try:
            # 4.   Thực hiện streaming HTTP request
            with httpx.stream("POST", url, json=payload, timeout=60.0) as r:
                r.raise_for_status()
                # 5.   Đọc từng dòng từ stream kết quả của Ollama
                for line in r.iter_lines():
                    if line:
                        chunk = json.loads(line)
                        content = chunk.get("message", {}).get("content", "")
                        if content:
                            yield content
        except Exception as e:
            # 6.   Bắt lỗi kết nối và trả về thông báo chi tiết
            yield (
                f"\n\n**[Lỗi kết nối Ollama local]**: Không thể kết nối tới Ollama tại địa chỉ `{self.base_url}`.\n"
                f"* Chi tiết lỗi: `{str(e)}`\n"
                f"* Vui lòng chạy lệnh: `ollama run {self.model}` trong Command Prompt hoặc Terminal của bạn trước khi thử lại."
            )
