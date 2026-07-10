from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from src.config import settings
from src.extraction.models import ExtractedEntity, ExtractedRelation
from src.extraction.providers import get_provider
from src.extraction.providers.gemini_provider import GeminiProvider
from src.extraction.providers.openai_provider import OpenAICompatibleProvider


def test_provider_factory() -> None:
    # Test default provider (gemini)
    with patch.object(settings, "llm_provider", "gemini"):
        provider = get_provider()
        assert isinstance(provider, GeminiProvider)

    # Test minimax provider
    with patch.object(settings, "llm_provider", "minimax"):
        provider = get_provider()
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.provider_type == "minimax"

    # Test qwen provider
    with patch.object(settings, "llm_provider", "qwen"):
        provider = get_provider()
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.provider_type == "qwen"

    # Test ollama provider
    with patch.object(settings, "llm_provider", "ollama"):
        provider = get_provider()
        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.provider_type == "ollama"

    # Test invalid provider
    with patch.object(settings, "llm_provider", "unknown"):
        with pytest.raises(ValueError, match="LLM Provider 'unknown' không được hỗ trợ"):
            get_provider()


@patch("src.extraction.providers.openai_provider.OpenAI")
def test_openai_provider_minimax_config(mock_openai_class: MagicMock) -> None:
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    with patch.object(settings, "llm_provider", "minimax"), \
         patch.object(settings, "minimax_api_key", "test-key-minimax"), \
         patch.object(settings, "minimax_model", "test-model-minimax"), \
         patch.object(settings, "minimax_base_url", "https://api.test-minimax.chat"):
         
        provider = get_provider()
        assert isinstance(provider, OpenAICompatibleProvider)
        
        client, model = provider._get_client_and_model()
        mock_openai_class.assert_called_once_with(api_key="test-key-minimax", base_url="https://api.test-minimax.chat")
        assert model == "test-model-minimax"


@patch("src.extraction.providers.openai_provider.OpenAI")
def test_openai_provider_ollama_config(mock_openai_class: MagicMock) -> None:
    mock_client = MagicMock()
    mock_openai_class.return_value = mock_client

    with patch.object(settings, "llm_provider", "ollama"), \
         patch.object(settings, "ollama_model", "qwen3:8b"), \
         patch.object(settings, "ollama_base_url", "http://localhost:11434/v1"):
         
        provider = get_provider()
        assert isinstance(provider, OpenAICompatibleProvider)
        
        client, model = provider._get_client_and_model()
        mock_openai_class.assert_called_once_with(api_key="ollama", base_url="http://localhost:11434/v1")
        assert model == "qwen3:8b"


def test_clean_json_text() -> None:
    provider = OpenAICompatibleProvider(provider_type="openai")
    
    # Test case 1: simple json with markdown wrapper and thinking block
    raw_content = "<think>I should output JSON</think>\n```json\n{\n  \"entities\": []\n}\n```"
    cleaned = provider._clean_json_text(raw_content)
    assert cleaned == '{\n  "entities": []\n}'

    # Test case 2: raw json only
    raw_content_2 = '{"entities": []}'
    cleaned_2 = provider._clean_json_text(raw_content_2)
    assert cleaned_2 == '{"entities": []}'


def test_normalize_id() -> None:
    provider = OpenAICompatibleProvider(provider_type="openai")
    
    assert provider._normalize_id("luat_phá_san") == "luat_pha_san"
    assert provider._normalize_id("nhung_nhiễu") == "nhung_nhieu"
    assert provider._normalize_id("doanh_nghiep_moi_gioi_bao_hiểm") == "doanh_nghiep_moi_gioi_bao_hiem"
    assert provider._normalize_id("  Luật  doanh   nghiệp ") == "luat_doanh_nghiep"
    assert provider._normalize_id("a-b-c!123") == "a_b_c_123"
