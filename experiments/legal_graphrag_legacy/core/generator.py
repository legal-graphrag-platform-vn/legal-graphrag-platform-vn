from clients.llm_client import LLMClient
from prompts.templates import SYSTEM_GENERATION_PROMPT

class AnswerGenerator:
    def __init__(self):
        self.llm = LLMClient()
        
    def generate(self, query, context, chat_history=None):
        print("⏳ [Generator] Đang sinh câu trả lời (LLM Generation)...")
        user_prompt = f"---\n{context}\n---\nCâu hỏi hiện tại: {query}"
        return self.llm.generate(
            prompt=user_prompt,
            system_prompt=SYSTEM_GENERATION_PROMPT,
            temperature=0.3,
            model="deepseek-v4-flash",
            chat_history=chat_history
        )
