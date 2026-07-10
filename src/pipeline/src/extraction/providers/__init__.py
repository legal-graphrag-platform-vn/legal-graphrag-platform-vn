from __future__ import annotations

from src.config import settings
from src.extraction.providers.base import BaseProvider
from src.extraction.providers.gemini_provider import GeminiProvider
from src.extraction.providers.openai_provider import OpenAICompatibleProvider


def get_provider() -> BaseProvider:
    """Factory function trả về provider trích xuất LLM tương ứng với settings."""
    provider_name = settings.llm_provider.lower()
    if provider_name == "gemini":
        return GeminiProvider()
    elif provider_name in ("minimax", "qwen", "openai", "ollama"):
        return OpenAICompatibleProvider(provider_type=provider_name)
    else:
        raise ValueError(
            f"LLM Provider '{settings.llm_provider}' không được hỗ trợ. "
            "Các giá trị hợp lệ: gemini, minimax, qwen, openai, ollama."
        )
