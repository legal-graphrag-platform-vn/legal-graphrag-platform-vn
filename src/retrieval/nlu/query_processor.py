"""LLM-backed query processor producing the five-field processing contract.

The processor is provider-agnostic: it depends only on the ``TextGenerationPort``
Protocol and the shared DTOs. Concrete Gemini/Ollama adapters live in
``src/infrastructure`` and conform to the port structurally.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from pydantic import ValidationError

from src.retrieval.errors import (
    QueryProcessingContractError,
    QueryProcessingError,
    QueryProcessingParseError,
)
from src.retrieval.nlu.prompts import QUERY_PROCESSING_SYSTEM_PROMPT
from src.retrieval.ports import TextGenerationPort
from src.shared.retrieval_contract import QueryProcessingResult

_HISTORY_HEADER = "Lịch sử hội thoại:"
_QUERY_HEADER = "Câu hỏi mới nhất:"


class QueryProcessor:
    """Resolve context, rewrite, and decompose a query via a text generator."""

    def __init__(
        self,
        text_generator: TextGenerationPort,
        *,
        temperature: float = 0.0,
        system_prompt: str = QUERY_PROCESSING_SYSTEM_PROMPT,
    ) -> None:
        self._text_generator = text_generator
        self._temperature = temperature
        self._system_prompt = system_prompt

    def process(
        self,
        current_query: str,
        conversation_history: Sequence[Mapping[str, str]] = (),
    ) -> QueryProcessingResult:
        query = current_query.strip()
        if not query:
            raise QueryProcessingError("current_query must not be blank")

        raw_output = self._text_generator.generate_text(
            system_prompt=self._system_prompt,
            user_prompt=build_user_prompt(conversation_history, query),
            temperature=self._temperature,
            response_format="json",
        )
        payload = extract_json_object(raw_output)
        try:
            return QueryProcessingResult.model_validate(payload)
        except ValidationError as exc:
            raise QueryProcessingContractError(
                f"LLM output violated the query-processing contract: {exc}"
            ) from exc


def build_user_prompt(
    conversation_history: Sequence[Mapping[str, str]],
    current_query: str,
) -> str:
    """Serialize bounded history + the current query into one user turn."""
    lines: list[str] = []
    if conversation_history:
        lines.append(_HISTORY_HEADER)
        for turn in conversation_history:
            role = str(turn.get("role", "")).strip() or "user"
            content = str(turn.get("content", "")).strip()
            lines.append(f"[{role}] {content}")
        lines.append("")
    lines.append(_QUERY_HEADER)
    lines.append(current_query.strip())
    return "\n".join(lines)


def extract_json_object(raw_output: str) -> dict[str, Any]:
    """Recover a JSON object from a possibly noisy LLM string.

    Tolerant of Markdown code fences and surrounding prose. Raises
    ``QueryProcessingParseError`` (never swallowed) when no object is found.
    """
    if raw_output is None:
        raise QueryProcessingParseError("LLM returned no output", raw_output="")
    text = _strip_code_fences(raw_output.strip())

    parsed = _try_load(text)
    if parsed is None:
        parsed = _try_load(_slice_first_object(text))
    if parsed is None:
        raise QueryProcessingParseError(
            "LLM output did not contain a valid JSON object",
            raw_output=raw_output,
        )
    if not isinstance(parsed, dict):
        raise QueryProcessingParseError(
            "LLM output JSON was not an object",
            raw_output=raw_output,
        )
    return parsed


def _try_load(text: str | None) -> Any | None:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _strip_code_fences(text: str) -> str:
    if not text.startswith("```"):
        return text
    without_open = text[3:]
    if without_open[:4].lower() == "json":
        without_open = without_open[4:]
    closing = without_open.rfind("```")
    if closing != -1:
        without_open = without_open[:closing]
    return without_open.strip()


def _slice_first_object(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    return text[start : end + 1]
