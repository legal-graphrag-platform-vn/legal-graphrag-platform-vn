"""LLM-backed classification for the canonical retrieval intent taxonomy."""

from src.retrieval.errors import IntentAnalysisError
from src.retrieval.models import IntentType
from src.retrieval.nlu.prompts import INTENT_CLASSIFICATION_SYSTEM_PROMPT
from src.retrieval.ports import TextGenerationPort


class LLMIntentClassifier:
    def __init__(self, llm_client: TextGenerationPort) -> None:
        self._llm_client = llm_client

    def classify(self, query: str) -> IntentType:
        response = self._llm_client.generate_text(
            system_prompt=INTENT_CLASSIFICATION_SYSTEM_PROMPT,
            user_prompt=query,
            temperature=0.0,
        )
        normalized = response.strip().lower()
        for intent in IntentType:
            if normalized == intent.value:
                return intent
        raise IntentAnalysisError(f"Unsupported intent response: {response!r}")
