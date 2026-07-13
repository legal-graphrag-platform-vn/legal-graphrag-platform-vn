"""Compatibility query analysis facade without concrete provider dependencies."""

from src.retrieval.models import IntentType, TemporalQuery
from src.retrieval.ports import IntentClassifierPort
from src.retrieval.query.temporal_parser import TemporalParser
from src.retrieval.routing.router import classify_intent_by_rule


class QueryAnalyzer:
    def __init__(
        self,
        classifier: IntentClassifierPort | None = None,
        temporal_parser: TemporalParser | None = None,
    ) -> None:
        self._classifier = classifier
        self._temporal_parser = temporal_parser or TemporalParser()

    def analyze(self, query: str) -> tuple[IntentType, TemporalQuery]:
        intent, _ = classify_intent_by_rule(query)
        if intent is None:
            intent = (
                self._classifier.classify(query)
                if self._classifier is not None
                else IntentType.FACTUAL
            )
        return intent, self._temporal_parser.parse(query)
