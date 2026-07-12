from typing import Optional

from src.infrastructure.llm.base import LLMClient


class FakeLLMClient(LLMClient):
    """
    Fake LLM Client dùng trong Unit Test.
    """

    def __init__(self, predefined_response: str = '{"intent": "factual"}'):
        self.predefined_response = predefined_response
        self.last_system_prompt = ""
        self.last_user_prompt = ""

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: Optional[str] = None,
    ) -> str:
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt
        return self.predefined_response
