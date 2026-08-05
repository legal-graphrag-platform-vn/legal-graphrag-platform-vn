"""Unit tests for the query processor, DTO contract, adapters, and factory."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.infrastructure.llm.errors import (
    TextGenerationDependencyError,
    TextGenerationOutputError,
)
from src.infrastructure.llm.gemini_text_provider import GeminiTextProvider
from src.infrastructure.llm.ollama_text_provider import OllamaTextProvider
from src.infrastructure.llm.text_generation_factory import build_text_generator
from src.retrieval.errors import (
    QueryProcessingContractError,
    QueryProcessingError,
    QueryProcessingParseError,
)
from src.retrieval.nlu.prompts import QUERY_PROCESSING_SYSTEM_PROMPT
from src.retrieval.nlu.query_processor import (
    QueryProcessor,
    build_user_prompt,
    extract_json_object,
)
from src.shared.retrieval_contract import (
    IntentType,
    PlanType,
    ProcessingStatus,
    QueryProcessingResult,
    SubqueryDTO,
    SubqueryIntent,
)


# --------------------------------------------------------------------------- #
# Fixtures / fakes
# --------------------------------------------------------------------------- #


class FakeTextGenerator:
    """Records prompts and returns a canned string."""

    def __init__(self, output: str) -> None:
        self.output = output
        self.calls: list[dict[str, Any]] = []

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: str | None = None,
    ) -> str:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "temperature": temperature,
                "response_format": response_format,
            }
        )
        return self.output


def _ready_single_payload() -> str:
    return json.dumps(
        {
            "status": "ready",
            "standalone_query": "Điều kiện thành lập công ty cổ phần là gì?",
            "plan_type": "single",
            "subqueries": [
                {
                    "id": "q1",
                    "query": "Điều kiện thành lập công ty cổ phần là gì?",
                    "intent": "factual",
                    "depends_on": [],
                }
            ],
            "clarification_question": None,
        },
        ensure_ascii=False,
    )


# --------------------------------------------------------------------------- #
# DTO contract
# --------------------------------------------------------------------------- #


def test_ready_result_requires_subqueries() -> None:
    with pytest.raises(ValueError):
        QueryProcessingResult(
            status=ProcessingStatus.READY,
            standalone_query="x",
            plan_type=PlanType.SINGLE,
            subqueries=[],
            clarification_question=None,
        )


def test_needs_clarification_requires_question() -> None:
    with pytest.raises(ValueError):
        QueryProcessingResult(
            status=ProcessingStatus.NEEDS_CLARIFICATION,
            clarification_question=None,
        )


def test_needs_clarification_forbids_query_and_plan() -> None:
    with pytest.raises(ValueError):
        QueryProcessingResult(
            status=ProcessingStatus.NEEDS_CLARIFICATION,
            standalone_query="not allowed",
            clarification_question="Bạn hỏi văn bản nào?",
        )


def test_depends_on_must_reference_preceding_subquery() -> None:
    with pytest.raises(ValueError):
        QueryProcessingResult(
            status=ProcessingStatus.READY,
            standalone_query="x",
            plan_type=PlanType.MULTI_HOP,
            subqueries=[
                SubqueryDTO(
                    id="q1", query="a", intent=SubqueryIntent.FACTUAL, depends_on=["q2"]
                ),
                SubqueryDTO(id="q2", query="b", intent=SubqueryIntent.FACTUAL),
            ],
            clarification_question=None,
        )


def test_duplicate_subquery_ids_rejected() -> None:
    with pytest.raises(ValueError):
        QueryProcessingResult(
            status=ProcessingStatus.READY,
            standalone_query="x",
            plan_type=PlanType.PARALLEL,
            subqueries=[
                SubqueryDTO(id="q1", query="a", intent=SubqueryIntent.FACTUAL),
                SubqueryDTO(id="q1", query="b", intent=SubqueryIntent.DEFINITION),
            ],
            clarification_question=None,
        )


def test_primary_intent_maps_comparison_and_multi_hop() -> None:
    comparison = QueryProcessingResult(
        status=ProcessingStatus.READY,
        standalone_query="so sánh",
        plan_type=PlanType.COMPARISON,
        subqueries=[SubqueryDTO(id="q1", query="a", intent=SubqueryIntent.FACTUAL)],
    )
    multi_hop = QueryProcessingResult(
        status=ProcessingStatus.READY,
        standalone_query="đa bước",
        plan_type=PlanType.MULTI_HOP,
        subqueries=[
            SubqueryDTO(id="q1", query="a", intent=SubqueryIntent.FACTUAL),
            SubqueryDTO(
                id="q2", query="b", intent=SubqueryIntent.HIERARCHY, depends_on=["q1"]
            ),
        ],
    )
    assert comparison.primary_intent() is IntentType.COMPARISON
    assert multi_hop.primary_intent() is IntentType.MULTI_HOP


def test_primary_intent_falls_back_to_first_subquery_intent() -> None:
    result = QueryProcessingResult(
        status=ProcessingStatus.READY,
        standalone_query="x",
        plan_type=PlanType.PARALLEL,
        subqueries=[
            SubqueryDTO(id="q1", query="a", intent=SubqueryIntent.DEFINITION),
            SubqueryDTO(id="q2", query="b", intent=SubqueryIntent.VALIDITY),
        ],
    )
    assert result.primary_intent() is IntentType.DEFINITION


def test_primary_intent_undefined_for_clarification() -> None:
    result = QueryProcessingResult(
        status=ProcessingStatus.NEEDS_CLARIFICATION,
        clarification_question="Bạn hỏi văn bản nào?",
    )
    with pytest.raises(ValueError):
        result.primary_intent()


# --------------------------------------------------------------------------- #
# JSON extraction
# --------------------------------------------------------------------------- #


def test_extract_json_plain() -> None:
    assert extract_json_object('{"a": 1}') == {"a": 1}


def test_extract_json_strips_markdown_fence() -> None:
    raw = '```json\n{"status": "ready"}\n```'
    assert extract_json_object(raw) == {"status": "ready"}


def test_extract_json_from_surrounding_prose() -> None:
    raw = 'Đây là kết quả:\n{"status": "ready"}\nHết.'
    assert extract_json_object(raw) == {"status": "ready"}


def test_extract_json_raises_on_garbage() -> None:
    with pytest.raises(QueryProcessingParseError) as exc_info:
        extract_json_object("không có json ở đây")
    assert exc_info.value.raw_output == "không có json ở đây"


# --------------------------------------------------------------------------- #
# QueryProcessor
# --------------------------------------------------------------------------- #


def test_process_ready_single() -> None:
    processor = QueryProcessor(FakeTextGenerator(_ready_single_payload()))
    result = processor.process("Điều kiện thành lập công ty cổ phần?")
    assert result.status is ProcessingStatus.READY
    assert result.plan_type is PlanType.SINGLE
    assert result.primary_intent() is IntentType.FACTUAL


def test_process_needs_clarification() -> None:
    payload = json.dumps(
        {
            "status": "needs_clarification",
            "standalone_query": None,
            "plan_type": None,
            "subqueries": [],
            "clarification_question": "Bạn muốn hỏi về văn bản nào?",
        },
        ensure_ascii=False,
    )
    result = QueryProcessor(FakeTextGenerator(payload)).process("điều 1 của nó")
    assert result.status is ProcessingStatus.NEEDS_CLARIFICATION
    assert result.clarification_question


def test_process_multi_hop_with_dependency() -> None:
    payload = json.dumps(
        {
            "status": "ready",
            "standalone_query": "Công ty nước ngoài đầu tư áp dụng luật nào?",
            "plan_type": "multi_hop",
            "subqueries": [
                {
                    "id": "q1",
                    "query": "Luật điều chỉnh đầu tư nước ngoài?",
                    "intent": "factual",
                    "depends_on": [],
                },
                {
                    "id": "q2",
                    "query": "Nội dung luật đó quy định gì?",
                    "intent": "factual",
                    "depends_on": ["q1"],
                },
            ],
            "clarification_question": None,
        },
        ensure_ascii=False,
    )
    result = QueryProcessor(FakeTextGenerator(payload)).process("hỏi đa bước")
    assert result.primary_intent() is IntentType.MULTI_HOP
    assert result.subqueries[1].depends_on == ["q1"]


def test_process_passes_system_prompt_and_history() -> None:
    generator = FakeTextGenerator(_ready_single_payload())
    processor = QueryProcessor(generator)
    processor.process(
        "Điều 1 của nó?",
        conversation_history=[
            {"role": "user", "content": "Luật Doanh nghiệp 2020"},
            {"role": "assistant", "content": "Vâng"},
        ],
    )
    call = generator.calls[0]
    assert call["system_prompt"] == QUERY_PROCESSING_SYSTEM_PROMPT
    assert call["response_format"] == "json"
    assert "Luật Doanh nghiệp 2020" in call["user_prompt"]
    assert "Điều 1 của nó?" in call["user_prompt"]


def test_process_blank_query_rejected() -> None:
    with pytest.raises(QueryProcessingError):
        QueryProcessor(FakeTextGenerator("{}")).process("   ")


def test_process_invalid_json_raises_parse_error() -> None:
    with pytest.raises(QueryProcessingParseError):
        QueryProcessor(FakeTextGenerator("xin chào, không phải json")).process("hỏi")


def test_process_schema_violation_raises_contract_error() -> None:
    payload = json.dumps({"status": "ready", "subqueries": []})
    with pytest.raises(QueryProcessingContractError):
        QueryProcessor(FakeTextGenerator(payload)).process("hỏi")


def test_process_invalid_subquery_intent_raises_contract_error() -> None:
    payload = json.dumps(
        {
            "status": "ready",
            "standalone_query": "x",
            "plan_type": "single",
            "subqueries": [
                {"id": "q1", "query": "a", "intent": "comparison", "depends_on": []}
            ],
            "clarification_question": None,
        }
    )
    with pytest.raises(QueryProcessingContractError):
        QueryProcessor(FakeTextGenerator(payload)).process("hỏi")


def test_build_user_prompt_without_history() -> None:
    prompt = build_user_prompt((), "Câu hỏi X")
    assert "Câu hỏi X" in prompt
    assert "Lịch sử hội thoại:" not in prompt


# --------------------------------------------------------------------------- #
# Adapters
# --------------------------------------------------------------------------- #


def test_gemini_provider_generates_text() -> None:
    class _Response:
        text = _ready_single_payload()

    class _Models:
        def __init__(self) -> None:
            self.kwargs: dict[str, Any] = {}

        def generate_content(self, **kwargs: Any) -> _Response:
            self.kwargs = kwargs
            return _Response()

    class _Client:
        def __init__(self) -> None:
            self.models = _Models()

    client = _Client()
    provider = GeminiTextProvider(
        api_key="k",
        model="gemini-2.5-flash",
        client_factory=lambda _key: client,
        config_factory=lambda **kwargs: kwargs,
    )
    text = provider.generate_text("sys", "usr", response_format="json")
    assert text == _ready_single_payload()
    assert client.models.kwargs["model"] == "gemini-2.5-flash"
    assert client.models.kwargs["config"]["response_mime_type"] == "application/json"
    assert provider.provider_name == "gemini"


def test_gemini_provider_requires_api_key() -> None:
    with pytest.raises(TextGenerationDependencyError):
        GeminiTextProvider(api_key="", model="m")


def test_gemini_provider_rejects_empty_output() -> None:
    class _EmptyResponse:
        text = ""

    class _Client:
        class models:  # noqa: N801 - mimic SDK attribute access
            @staticmethod
            def generate_content(**_kwargs: Any) -> _EmptyResponse:
                return _EmptyResponse()

    provider = GeminiTextProvider(
        api_key="k",
        model="m",
        client_factory=lambda _key: _Client(),
        config_factory=lambda **kwargs: kwargs,
    )
    with pytest.raises(TextGenerationOutputError):
        provider.generate_text("sys", "usr")


def test_ollama_provider_generates_text() -> None:
    captured: dict[str, Any] = {}

    def transport(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        captured["url"] = url
        captured["payload"] = payload
        return {"message": {"content": _ready_single_payload()}}

    provider = OllamaTextProvider(model="qwen3:4b", transport=transport)
    text = provider.generate_text("sys", "usr", temperature=0.2, response_format="json")
    assert text == _ready_single_payload()
    assert captured["url"] == "http://localhost:11434/api/chat"
    assert captured["payload"]["format"] == "json"
    assert captured["payload"]["options"]["temperature"] == 0.2
    assert captured["payload"]["messages"][0]["role"] == "system"
    assert provider.provider_name == "ollama"


def test_ollama_provider_rejects_empty_content() -> None:
    provider = OllamaTextProvider(
        model="qwen3:4b",
        transport=lambda _u, _p, _t: {"message": {"content": ""}},
    )
    with pytest.raises(TextGenerationOutputError):
        provider.generate_text("sys", "usr")


# --------------------------------------------------------------------------- #
# Factory
# --------------------------------------------------------------------------- #


def test_factory_selects_ollama() -> None:
    generator = build_text_generator(
        provider="ollama", env={"OLLAMA_MODEL": "qwen3:7b"}
    )
    assert isinstance(generator, OllamaTextProvider)
    assert generator.model_name == "qwen3:7b"


def test_factory_gemini_branch_requires_key() -> None:
    with pytest.raises(TextGenerationDependencyError):
        build_text_generator(provider="gemini", env={})


def test_factory_defaults_to_gemini() -> None:
    # No LLM_PROVIDER and no key -> gemini branch selected, fails on missing key.
    with pytest.raises(TextGenerationDependencyError):
        build_text_generator(env={})


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(TextGenerationDependencyError):
        build_text_generator(provider="anthropic", env={})
