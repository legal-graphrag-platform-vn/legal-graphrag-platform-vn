import json
import re
from datetime import datetime
from clients.llm_client import LLMClient
from prompts.templates import INTENT_CLASSIFICATION_PROMPT, TEMPORAL_EXTRACTION_PROMPT

class QueryRouter:
    def __init__(self):
        self.llm = LLMClient()
        
    def analyze(self, query):
        print("⏳ [Router] Đang phân loại Intent...")
        intent_res = self.llm.generate(INTENT_CLASSIFICATION_PROMPT.format(query=query), temperature=0.1)
        intent = intent_res.strip()
        # Clean intent string in case model returns bold or extra text
        match = re.search(r'(factual|validity|hierarchy|comparison|definition|multi_hop)', intent.lower())
        if match:
            intent = match.group(1)
        else:
            intent = "factual" # Default fallback
            
        print("⏳ [Router] Đang trích xuất Temporal...")
        today = datetime.now().strftime("%Y-%m-%d")
        temp_res = self.llm.generate(TEMPORAL_EXTRACTION_PROMPT.format(query=query, today=today), temperature=0.1)
        
        try:
            # Lấy đúng đoạn JSON nếu LLM sinh ra text rác
            start = temp_res.find('{')
            end = temp_res.rfind('}') + 1
            if start != -1 and end != 0:
                temporal = json.loads(temp_res[start:end])
            else:
                temporal = None
        except:
            temporal = None
            
        return intent, temporal
