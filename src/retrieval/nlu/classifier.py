from src.infrastructure.llm.base import LLMClient
from src.retrieval.models import IntentType
from src.retrieval.nlu.prompts import INTENT_CLASSIFICATION_SYSTEM_PROMPT


class LLMIntentClassifier:
    """
    Sử dụng LLMClient để phân loại Intent khi Rule-based không đủ độ tin cậy.
    """
    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client

    def classify(self, query: str) -> IntentType:
        try:
            response = self.llm_client.generate_text(
                system_prompt=INTENT_CLASSIFICATION_SYSTEM_PROMPT,
                user_prompt=query,
                temperature=0.0
            )
            raw_intent = response.strip().lower()
            
            # Map back to Enum
            for intent in IntentType:
                if intent.value in raw_intent:
                    return intent
            
            # Default fallback
            return IntentType.FACTUAL
        except Exception:
            return IntentType.FACTUAL
