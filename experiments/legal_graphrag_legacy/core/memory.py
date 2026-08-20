from clients.llm_client import LLMClient
from prompts.templates import QUERY_REWRITE_PROMPT

class MemoryManager:
    def __init__(self, max_turns=3):
        self.history = []  # Danh sách dict {"role": "user"/"assistant", "content": "..."}
        self.max_turns = max_turns
        self.llm = LLMClient()
        
    def add_interaction(self, user_query, assistant_answer):
        self.history.append({"role": "user", "content": user_query})
        self.history.append({"role": "assistant", "content": assistant_answer})
        
        # Nếu dài quá thì chặt bớt để khỏi tràn token (chỉ giữ lại max_turns * 2 tin nhắn)
        if len(self.history) > self.max_turns * 2:
            self.history = self.history[-(self.max_turns * 2):]
            
    def get_history_messages(self):
        return self.history
        
    def get_history_text(self):
        if not self.history:
            return "Không có."
        text = ""
        for msg in self.history:
            role = "Người dùng" if msg["role"] == "user" else "Trợ lý AI"
            text += f"{role}: {msg['content']}\n"
        return text

    def contextualize_query(self, current_query):
        # Nếu chưa có lịch sử gì thì khỏi viết lại
        if not self.history:
            return current_query
            
        print("⏳ [Memory] Đang đánh giá bối cảnh và viết lại câu hỏi (Contextualization)...")
        prompt = QUERY_REWRITE_PROMPT.format(
            chat_history=self.get_history_text(),
            query=current_query
        )
        
        # Dùng v4-flash để chốt hạ câu hỏi cực nhanh
        standalone_query = self.llm.generate(prompt, temperature=0.1)
        return standalone_query.strip()
