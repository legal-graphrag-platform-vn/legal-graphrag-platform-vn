import json
import urllib.request
from config import DEEPSEEK_API_KEY

class LLMClient:
    def __init__(self):
        self.api_key = DEEPSEEK_API_KEY
        self.url = "https://api.deepseek.com/chat/completions"
        self.headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {self.api_key}'
        }

    def generate(self, prompt, system_prompt=None, temperature=0.1, model="deepseek-v4-flash", chat_history=None):
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
            
        # Chèn lịch sử chat vào luồng tin nhắn
        if chat_history:
            for msg in chat_history:
                messages.append(msg)
                
        messages.append({"role": "user", "content": prompt})
        
        data = {
            "model": model,
            "messages": messages,
            "temperature": temperature
        }
        
        req = urllib.request.Request(self.url, data=json.dumps(data).encode('utf-8'), headers=self.headers, method='POST')
        try:
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result['choices'][0]['message']['content']
        except Exception as e:
            if hasattr(e, 'read'):
                return f"LỖI: {e}\nChi tiết: {e.read().decode('utf-8')}"
            return f"LỖI: {e}"
