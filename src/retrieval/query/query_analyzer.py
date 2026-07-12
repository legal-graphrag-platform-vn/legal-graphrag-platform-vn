import json
import re
from typing import Optional

from src.infrastructure.llm.base import LLMClient
from src.retrieval.models import IntentType
from src.retrieval.nlu.classifier import LLMIntentClassifier
from src.retrieval.query.temporal_parser import TemporalParser


class QueryAnalyzer:
    """
    Phân tích truy vấn để bóc tách Intent và Temporal.
    Quy trình: Rule-based (Fast path) -> Fallback LLM.
    """

    def __init__(self, llm_client: LLMClient):
        self.llm_client = llm_client
        self.temporal_parser = TemporalParser(llm_client=llm_client)
        self.llm_classifier = LLMIntentClassifier(llm_client=llm_client)
        
        # Rule-based heuristics
        self.rules = {
            # definition rules
            r"(là gì|định nghĩa|được hiểu thế nào)": IntentType.DEFINITION,
            r"(thế nào là|khái niệm)": IntentType.DEFINITION,
            
            # hierarchy/factual rules
            r"(điều \d+|khoản \d+|chương \d+)": IntentType.HIERARCHY, # Thường hỏi trực tiếp về 1 điều luật cụ thể
            
            # validity/multi-hop rules
            r"(sửa đổi|bãi bỏ|thay thế)": IntentType.VALIDITY,
            r"(còn hiệu lực|hết hiệu lực)": IntentType.VALIDITY,
            
            # comparison
            r"(khác nhau|giống nhau|so sánh)": IntentType.COMPARISON,
        }

    def analyze(self, query: str) -> tuple[IntentType, dict]:
        """
        Analyze query to get IntentType and TemporalQuery dict representation.
        Return: (IntentType, TemporalQuery)
        """
        query_lower = query.lower()
        
        # 1. Temporal Parsing
        temporal_query = self.temporal_parser.parse(query)
        
        # 2. Rule-based Intent Classification (fast path)
        matched_intent = None
        for pattern, intent in self.rules.items():
            if re.search(pattern, query_lower):
                # We could have conflicts, but first match wins for this heuristic
                matched_intent = intent
                break
                
        # 3. LLM Fallback (if rule confidence is low or no match)
        if not matched_intent:
            matched_intent = self.llm_classifier.classify(query)
            
        return matched_intent, temporal_query
