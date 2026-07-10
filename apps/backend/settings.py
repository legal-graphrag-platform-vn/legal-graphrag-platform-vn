import os
from dotenv import load_dotenv

load_dotenv()

class ConfigurationError(Exception):
    """Exception raised when a critical configuration is missing."""
    pass

class Config:
    # 1.   Load LLM Provider configuration (ollama, openai, gemini)
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama").lower()
    
    # 2.   Load Ollama specific configuration
    OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3") # Default model
    
    # 3.   Load OpenAI specific configuration (Throw exception if selected but missing key)
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    # 4.   Load Gemini specific configuration (Throw exception if selected but missing key)
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    @classmethod
    def validate(cls):
        # 1.   Validate OpenAI configuration if selected
        if cls.LLM_PROVIDER == "openai":
            if not cls.OPENAI_API_KEY:
                raise ConfigurationError(
                    "Cấu hình thiếu: Biến môi trường 'OPENAI_API_KEY' bắt buộc phải có khi sử dụng LLM_PROVIDER='openai'."
                )
        # 2.   Validate Ollama configuration if selected
        elif cls.LLM_PROVIDER == "ollama":
            if not cls.OLLAMA_BASE_URL:
                raise ConfigurationError(
                    "Cấu hình thiếu: Biến môi trường 'OLLAMA_BASE_URL' không được để trống khi sử dụng LLM_PROVIDER='ollama'."
                )
        # 3.   Validate Gemini configuration if selected
        elif cls.LLM_PROVIDER == "gemini":
            if not cls.GEMINI_API_KEY:
                raise ConfigurationError(
                    "Cấu hình thiếu: Biến môi trường 'GEMINI_API_KEY' bắt buộc phải có khi sử dụng LLM_PROVIDER='gemini'."
                )
