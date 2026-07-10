from abc import ABC, abstractmethod
from typing import Generator, List, Dict

class BaseLLMProvider(ABC):
    """
    Lớp trừu tượng định nghĩa giao diện chung cho các LLM Provider.
    Tất cả các provider mới (Ollama, OpenAI, Gemini...) cần phải kế thừa lớp này.
    """

    @abstractmethod
    def stream_chat(
        self, 
        prompt: str, 
        context: str, 
        history: List[Dict[str, str]]
    ) -> Generator[str, None, None]:
        """
        Stream câu trả lời từ LLM dựa trên prompt, context từ RAG và lịch sử chat.
        Trả về một Python Generator sinh ra các text chunk.
        """
        # 1.   Phương thức này bắt buộc phải được triển khai ở lớp con
        pass
