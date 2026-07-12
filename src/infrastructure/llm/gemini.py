import os
from typing import Optional

from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from src.infrastructure.llm.base import LLMClient


class GeminiLLMClient(LLMClient):
    """
    Client gọi Google Gemini API thông qua google-genai SDK.
    """

    def __init__(self, model_name: str = "gemini-2.5-flash", api_key: Optional[str] = None):
        self.model_name = model_name
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is not set.")
        self.client = genai.Client(api_key=self.api_key)

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
        
        config_kwargs = {
            "temperature": temperature,
            "system_instruction": system_prompt,
        }
        
        if response_format == "json_object":
            config_kwargs["response_mime_type"] = "application/json"
            
        config = types.GenerateContentConfig(**config_kwargs)

        response = self.client.models.generate_content(
            model=self.model_name,
            contents=user_prompt,
            config=config,
        )
        return response.text
