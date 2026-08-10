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
    answer_context_safety_reserve_chars: int = Field(
        default=256,
        ge=0,
        le=20_000,
    )
    answer_history_max_messages: int = Field(default=6, ge=0, le=20)
    answer_history_max_chars: int = Field(default=4000, ge=0, le=20_000)
    answer_stream_chunk_chars: int = Field(default=160, ge=1, le=2000)

    # 5.   Query planning (multi-hop) is an explicit runtime profile
    query_planning_enabled: bool = False
    query_planner_provider: Literal["gemini"] = "gemini"
    query_planner_model: str = "gemini-3.1-flash-lite"
    query_planner_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    query_planner_max_concurrency: int = Field(default=2, ge=1, le=16)
    query_planner_max_retries: int = Field(default=2, ge=0, le=5)
    query_planner_max_output_tokens: int = Field(default=1024, ge=128, le=4096)
    query_planner_temperature: float = Field(default=0.0, ge=0.0, le=1.0)

    # 6.   LLM Providers
    llm_provider: Literal["gemini", "deepseek", "openai", "ollama"] = "ollama"
    llm_model: str = "llama3"
    ollama_base_url: str = "http://localhost:11434"
    gemini_api_key: str | None = None
    deepseek_api_key: str | None = None
    openai_api_key: str | None = None

    # 7.   CORS — không dùng ["*"] trong production
    cors_origins: list[str] = Field(default=["http://localhost:3000"])

    # 8.   Conversation context store (Plan 19) — PostgreSQL
    database_url: str | None = None
    db_pool_size: int = Field(default=6, ge=1, le=64)
    db_max_overflow: int = Field(default=0, ge=0, le=32)
    db_pool_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    # Session-level advisory lock acquisition deadline (Plan 19 §3).
    conversation_lock_timeout_seconds: float = Field(default=1.0, gt=0, le=30)
    conversation_lock_poll_interval_seconds: float = Field(
        default=0.05,
        gt=0,
        le=1.0,
    )

    # 9b. Query Processor (five-field contract). It decomposes the canonical
    # standalone query after deterministic reference resolution and rewriting.
    query_processor_enabled: bool = False
    query_processor_model: str = "gemini-flash-lite-latest"

    # 8b.  Observability / debug trace logging (Plan 21)
    log_level: str = "INFO"
    chat_trace_llm_io: Literal["off", "redacted", "full"] = "redacted"
    chat_trace_max_raw: int = Field(default=2000, ge=200, le=20_000)
    # Set to a file path (e.g. infra/data/logs/chat-trace.log) so Promtail can
    # tail it into Loki. None → stdout only.
    chat_trace_log_file: str | None = None
    # Durable per-turn trace in Postgres (turn_debug_trace): off | failed | all.
    chat_trace_persist: Literal["off", "failed", "all"] = "failed"

    # 9.   Signed anonymous principal (Plan 19 §2)
    anonymous_principal_signing_key: str | None = None
    anonymous_principal_cookie_ttl_days: int = Field(default=180, ge=1, le=730)
    # Set Secure cookie attribute in production deployments.
    anonymous_principal_cookie_secure: bool = False

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
            if self.answer_generation_enabled:
                self._validate_conversation_store()
            if (
                self.query_planning_enabled
                and self.query_planner_provider == "gemini"
                and not self.gemini_api_key
            ):
                raise RuntimeError("QUERY_PLANNING_ENABLED=true yêu cầu GEMINI_API_KEY")
            if (
                self.query_processor_enabled
                and self.llm_provider == "gemini"
                and not self.gemini_api_key
            ):
                raise RuntimeError(
                    "QUERY_PROCESSOR_ENABLED=true với LLM_PROVIDER=gemini yêu cầu "
                    "GEMINI_API_KEY"
                )

    def _validate_conversation_store(self) -> None:
        """Grounded chat persists context in PostgreSQL and signs principals."""
        if not self.database_url:
            raise RuntimeError("ANSWER_GENERATION_ENABLED=true yêu cầu DATABASE_URL")
        if not self.database_url.startswith("postgresql+asyncpg://"):
            raise RuntimeError("DATABASE_URL phải dùng driver postgresql+asyncpg://")
        key = self.anonymous_principal_signing_key
        if not key or len(key.encode("utf-8")) < 32:
            raise RuntimeError(
                "ANSWER_GENERATION_ENABLED=true yêu cầu "
                "ANONYMOUS_PRINCIPAL_SIGNING_KEY tối thiểu 32 bytes"
            )
        if self.db_pool_size < self.answer_max_concurrency:
            raise RuntimeError(
                "DB_POOL_SIZE không được nhỏ hơn ANSWER_MAX_CONCURRENCY "
                f"({self.db_pool_size} < {self.answer_max_concurrency})"
            )
