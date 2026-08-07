import pytest

from src.retrieval.errors import IntentAnalysisError
from src.retrieval.models import IntentType
from src.retrieval.nlu.classifier import LLMIntentClassifier
from src.shared.llm_errors import TextGenerationError


class FakeTextGenerator:
    def __init__(self, output: str | None = None, error: Exception | None = None):
        self._output = output
        self._error = error
        self.calls: list[tuple[str, str, float]] = []

    def generate_text(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        response_format: str | None = None,
    ) -> str:
        self.calls.append((system_prompt, user_prompt, temperature))
        if self._error is not None:
            raise self._error
        assert self._output is not None
        return self._output


def test_valid_intent_is_parsed() -> None:
    classifier = LLMIntentClassifier(FakeTextGenerator(output=" DEFINITION "))
    assert classifier.classify("Vốn điều lệ là gì?") is IntentType.DEFINITION


def test_unknown_intent_string_raises() -> None:
    classifier = LLMIntentClassifier(FakeTextGenerator(output="không_rõ"))
    with pytest.raises(IntentAnalysisError):
        classifier.classify("...")


def test_textgeneration_error_translated_to_intent_error() -> None:
    classifier = LLMIntentClassifier(
        FakeTextGenerator(error=TextGenerationError("network down"))
    )
    with pytest.raises(IntentAnalysisError):
        classifier.classify("...")


def test_unexpected_error_is_not_swallowed() -> None:
    classifier = LLMIntentClassifier(FakeTextGenerator(error=ValueError("bug")))
    with pytest.raises(ValueError):
        classifier.classify("...")
