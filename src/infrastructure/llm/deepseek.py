import os
from typing import Optional

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from src.infrastructure.llm.base import LLMClient


class DeepSeekLLMClient(LLMClient):
    """
    Client gọi DeepSeek API thông qua OpenAI SDK (tương thích API chuẩn OpenAI).
    """

    def __init__(self, model_name: str = "deepseek-chat", api_key: Optional[str] = None):
        self.model_name = model_name
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError("DEEPSEEK_API_KEY is not set.")
        
        self.client = OpenAI(
            api_key=self.api_key,
            base_url="https://api.deepseek.com"
        )

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=10),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: Optional[str] = None,
    ) -> str:
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        
        kwargs = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        
        if response_format == "json_object":
            kwargs["response_format"] = {"type": "json_object"}

        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content
