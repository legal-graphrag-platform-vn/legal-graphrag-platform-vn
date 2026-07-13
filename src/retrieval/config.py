"""Retrieval-owned settings independent from pipeline configuration."""

from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class RetrievalConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RETRIEVAL_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    contract_version: Literal["retrieval-runtime-v1"] = "retrieval-runtime-v1"
    candidate_k: int = Field(default=20, ge=1, le=200)
    final_k: int = Field(default=10, ge=1, le=200)
    graph_entry_k: int = Field(default=5, ge=1, le=200)
    rrf_k: int = Field(default=60, ge=1)
    vector_enabled: bool = True
    fulltext_enabled: bool = True
    graph_enabled: bool = True
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_fp16: bool = False
    hierarchy_vector_enabled: bool = False
    query_max_length: int = Field(default=4000, ge=1, le=10000)

    @model_validator(mode="after")
    def validate_limits_and_channels(self) -> "RetrievalConfig":
        if self.final_k > self.candidate_k:
            raise ValueError("RETRIEVAL_FINAL_K must not exceed RETRIEVAL_CANDIDATE_K")
        if not self.vector_enabled and not self.fulltext_enabled:
            raise ValueError("At least one seed retrieval channel must be enabled")
        if not self.reranker_model.strip():
            raise ValueError("RETRIEVAL_RERANKER_MODEL must not be blank")
        return self
