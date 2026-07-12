from __future__ import annotations

from unittest.mock import MagicMock, patch
import pytest

from src.pipeline.config import settings
from src.pipeline.extraction.models import ExtractedEntity
from src.pipeline.extraction.providers import get_provider
from src.pipeline.extraction.providers.gemini_provider import GeminiProvider
from src.pipeline.extraction.providers.gemini_provider import _raise_classified_provider_error
from src.pipeline.extraction.providers.base import FatalExtractionProviderError
from src.pipeline.extraction.providers.openai_provider import OpenAICompatibleProvider
from src.pipeline.extraction.llm_extractor import extract_article, normalize_entities_for_relations
from src.pipeline.extraction.structural_context import ArticleExtractionContext


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


@patch("src.pipeline.extraction.providers.openai_provider.OpenAI")
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


@patch("src.pipeline.extraction.providers.openai_provider.OpenAI")
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


@pytest.mark.parametrize(
    ("message", "reason"),
    [
        ("404 NOT_FOUND: model not found", "model_unavailable"),
        ("429 RESOURCE_EXHAUSTED: GenerateRequestsPerDay limit: 20", "quota_exhausted"),
    ],
)
def test_gemini_fatal_errors_are_not_retryable(message: str, reason: str) -> None:
    with pytest.raises(FatalExtractionProviderError, match=reason):
        _raise_classified_provider_error(RuntimeError(message), "gemini-test")


def test_gemini_transient_rate_limit_is_retryable() -> None:
    from src.pipeline.extraction.providers.base import RetryableExtractionProviderError

    with pytest.raises(RetryableExtractionProviderError, match="rate_limited"):
        _raise_classified_provider_error(
            RuntimeError("429 RESOURCE_EXHAUSTED: per-minute request limit; retry in 5s"),
            "gemini-test",
        )


def test_gemini_requests_use_global_minimum_interval(monkeypatch) -> None:
    import src.pipeline.extraction.providers.gemini_provider as module

    clock = MagicMock(side_effect=[10.0, 12.0])
    sleeper = MagicMock()
    monkeypatch.setattr(settings, "gemini_min_request_interval_seconds", 2.0)
    monkeypatch.setattr(module, "_last_request_at", 9.0)
    monkeypatch.setattr(module.time, "monotonic", clock)
    monkeypatch.setattr(module.time, "sleep", sleeper)

    module._wait_for_request_slot()

    sleeper.assert_called_once_with(1.0)
    assert module._last_request_at == 12.0


def test_semantic_entities_are_canonical_before_relation_pass() -> None:
    raw_entities = [
        ExtractedEntity(id="raw_1", type="Concept", label="Bình đẳng trước pháp luật"),
        ExtractedEntity(id="khoan_1", type="Clause", label="Khoản 1"),
    ]
    assert normalize_entities_for_relations(raw_entities) == [
        ExtractedEntity(
            id="binh_dang_truoc_phap_luat",
            type="Concept",
            label="Bình đẳng trước pháp luật",
        )
    ]


def test_extract_article_passes_canonical_entities_to_relation_provider() -> None:
    provider = MagicMock()
    provider.resolved_model = "gemini-flash-lite-001"
    provider.extract_entities.return_value = [
        ExtractedEntity(id="raw_concept", type="Concept", label="Vốn điều lệ")
    ]
    provider.extract_relations.return_value = []
    context = ArticleExtractionContext(
        raw_doc_code="L59_2020",
        graph_id="ldn_2020",
        article_number="5",
        article_id="ldn_2020_art5",
        clause_ids={},
        point_ids={},
    )
    with patch("src.pipeline.extraction.llm_extractor.get_provider", return_value=provider):
        result = extract_article("5", "Điều 5", context=context)

    relation_entities = provider.extract_relations.call_args.args[1]
    assert relation_entities[0].id == "von_dieu_le"
    assert result.raw_entities[0].id == "raw_concept"
    assert result.entities[0].id == "von_dieu_le"
    assert result.resolved_model == "gemini-flash-lite-001"
