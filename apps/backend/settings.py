"""
Settings — pydantic-settings cho toàn bộ backend config.
Không hardcode password default. Validate runtime trước khi serve.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 1.   App mode: "mock" không cần Neo4j, "graphrag" cần full config
    app_mode: Literal["mock", "graphrag"] = "mock"

    # 2.   Neo4j — chỉ required khi app_mode="graphrag"
    neo4j_uri: str | None = None
    neo4j_user: str | None = None
    neo4j_password: str | None = None  # Không có default — nếu thiếu phải fail rõ ràng

    # 3.   Sync retrieval runs in one bounded application-owned executor
    backend_retrieval_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    backend_retrieval_max_concurrency: int = Field(default=4, ge=1, le=32)
    backend_retrieval_shutdown_grace_seconds: float = Field(
        default=5.0,
        ge=0,
        le=60,
    )

    # 4.   Answer generation is an explicit runtime profile
    answer_generation_enabled: bool = False
    answer_provider: Literal["gemini"] = "gemini"
    answer_model: str = "gemini-3.1-flash-lite"
    answer_timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    answer_max_concurrency: int = Field(default=2, ge=1, le=16)
    answer_max_retries: int = Field(default=2, ge=0, le=5)
    answer_max_output_tokens: int = Field(default=2048, ge=128, le=8192)
    answer_temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    answer_thinking_level: Literal["minimal", "low", "medium", "high"] = "minimal"
    answer_context_max_chars: int = Field(default=24_000, ge=1000, le=200_000)
    answer_history_max_messages: int = Field(default=6, ge=0, le=20)
    answer_history_max_chars: int = Field(default=4000, ge=0, le=20_000)
    answer_stream_chunk_chars: int = Field(default=160, ge=1, le=2000)

    # 5.   LLM Providers
    llm_provider: Literal["gemini", "deepseek", "openai", "ollama"] = "ollama"
    llm_model: str = "llama3"
    ollama_base_url: str = "http://localhost:11434"
    gemini_api_key: str | None = None
    deepseek_api_key: str | None = None
    openai_api_key: str | None = None

    # 6.   CORS — không dùng ["*"] trong production
    cors_origins: list[str] = Field(default=["http://localhost:3000"])

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    def validate_runtime(self) -> None:
        """
        Raise RuntimeError sớm nếu config thiếu cho mode đang chạy.
        Gọi trong lifespan() trước khi build container.
        """
        if self.app_mode == "graphrag":
            missing = [
                name
                for name, val in {
                    "NEO4J_URI": self.neo4j_uri,
                    "NEO4J_USER": self.neo4j_user,
                    "NEO4J_PASSWORD": self.neo4j_password,
                }.items()
                if not val
            ]
            if missing:
                raise RuntimeError(
                    f"APP_MODE=graphrag yêu cầu phải set: {', '.join(missing)}"
                )
            if self.answer_generation_enabled and not self.gemini_api_key:
                raise RuntimeError(
                    "ANSWER_GENERATION_ENABLED=true yêu cầu GEMINI_API_KEY"
                )
