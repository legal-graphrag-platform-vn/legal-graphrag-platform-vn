from abc import ABC, abstractmethod
from typing import Optional


class LLMClient(ABC):
    """
    Giao diện chuẩn cho tất cả các LLM provider.
    Dùng để gọi LLM sinh response (cho intent classification, temporal parsing, QA generation).
    """

    @abstractmethod
    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: Optional[str] = None,
    ) -> str:
        """
        Gửi request đến LLM và trả về chuỗi text kết quả.
        
        Args:
            system_prompt: Câu lệnh hệ thống.
            user_prompt: Nội dung truy vấn của user.
            temperature: Độ ngẫu nhiên.
            response_format: Hỗ trợ "json_object" nếu LLM hỗ trợ, hoặc None.
            
        Returns:
            Chuỗi text (hoặc JSON text) trả về từ LLM.
        """
        pass
