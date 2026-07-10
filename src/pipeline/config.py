"""Cấu hình tập trung cho pipeline, đọc từ biến môi trường / .env (pydantic-settings).

Lý do dùng pydantic-settings thay vì os.getenv rải rác: type-checking tại
thời điểm khởi động, lỗi thiếu config rõ ràng ngay (fail-fast) thay vì lỗi
mơ hồ giữa chừng khi gọi Gemini API.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_provider: str = Field(default="gemini", description="LLM provider: gemini|minimax|qwen|openai")

    # Gemini
    gemini_api_key: str = Field(default="", description="API key cho Gemini, lấy tại aistudio.google.com/apikey")
    gemini_model: str = Field(default="gemini-2.5-flash")

    # MiniMax
    minimax_api_key: str = Field(default="")
    minimax_model: str = Field(default="MiniMax-Text-01")
    minimax_base_url: str = Field(default="https://api.minimax.io/v1")

    # Qwen
    qwen_api_key: str = Field(default="")
    qwen_model: str = Field(default="qwen-plus")
    qwen_base_url: str = Field(default="https://dashscope.aliyuncs.com/compatible-mode/v1")

    # Generic OpenAI
    openai_api_key: str = Field(default="")
    openai_model: str = Field(default="")
    openai_base_url: str = Field(default="")

    # Ollama (Local)
    ollama_model: str = Field(default="qwen3:8b")
    ollama_base_url: str = Field(default="http://localhost:11434/v1")

    data_raw_dir: Path = Field(default=Path(__file__).resolve().parents[2] / "data" / "raw")
    data_processed_dir: Path = Field(default=Path(__file__).resolve().parents[2] / "data" / "processed")
    data_reports_dir: Path = Field(default=Path(__file__).resolve().parents[2] / "data" / "reports")
    extraction_max_workers: int = Field(default=10, ge=1, le=50, description="Số lượng luồng gọi LLM API song song")

    confidence_threshold_auto: float = Field(default=0.8, ge=0.0, le=1.0)
    confidence_threshold_review: float = Field(default=0.55, ge=0.0, le=1.0)

    neo4j_uri: str = Field(default="bolt://localhost:7687")
    neo4j_user: str = Field(default="neo4j")
    neo4j_password: str = Field(default="")

    embedding_model: str = Field(default="bkai-foundation-models/vietnamese-bi-encoder")
    embedding_dimension: int = Field(default=768, ge=1)

    tesseract_cmd: str = Field(
        default="", description="Đường dẫn tesseract.exe nếu không nằm trong PATH (vd Windows)."
    )
    tessdata_dir: str = Field(
        default="",
        description="Thư mục chứa *.traineddata (vd gói ngôn ngữ vie.traineddata tải riêng, "
        "không ghi được vào thư mục cài đặt Tesseract mặc định do thiếu quyền admin).",
    )

    def require_gemini_api_key(self) -> str:
        """Trả về API key hoặc raise lỗi rõ ràng nếu thiếu (dành cho backward compatibility)."""
        if not self.gemini_api_key:
            raise RuntimeError(
                "Thiếu GEMINI_API_KEY. Lấy key tại https://aistudio.google.com/apikey "
                "rồi đặt vào file .env (xem .env.example)."
            )
        return self.gemini_api_key

    def require_api_key(self) -> str:
        """Trả về API key tương ứng với provider hiện tại."""
        provider = self.llm_provider.lower()
        if provider == "gemini":
            return self.require_gemini_api_key()
        elif provider == "minimax":
            if not self.minimax_api_key:
                raise RuntimeError("Thiếu MINIMAX_API_KEY trong file .env.")
            return self.minimax_api_key
        elif provider == "qwen":
            if not self.qwen_api_key:
                raise RuntimeError("Thiếu QWEN_API_KEY trong file .env.")
            return self.qwen_api_key
        elif provider == "openai":
            if not self.openai_api_key:
                raise RuntimeError("Thiếu OPENAI_API_KEY trong file .env.")
            return self.openai_api_key
        elif provider == "ollama":
            return "ollama"  # Ollama không bắt buộc API key thực tế
        else:
            raise ValueError(f"LLM provider '{self.llm_provider}' không hợp lệ.")


settings = Settings()
