"""Validated answer-generation runtime configuration."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class GenerationConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_seconds: float = Field(default=45.0, gt=0, le=300)
    max_concurrency: int = Field(default=2, ge=1, le=16)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_output_tokens: int = Field(default=2048, ge=128, le=8192)
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    thinking_level: Literal["minimal", "low", "medium", "high"] = "minimal"
    context_max_chars: int = Field(default=24_000, ge=1000, le=200_000)
    context_safety_reserve_chars: int = Field(default=256, ge=0, le=20_000)
    history_max_messages: int = Field(default=6, ge=0, le=20)
    history_max_chars: int = Field(default=4000, ge=0, le=20_000)
    stream_chunk_chars: int = Field(default=160, ge=1, le=2000)
