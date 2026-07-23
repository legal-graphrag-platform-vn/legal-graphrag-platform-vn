"""Runtime configuration owned by the query-planning provider."""

from pydantic import BaseModel, ConfigDict, Field


class QueryPlannerConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    max_concurrency: int = Field(default=2, ge=1, le=16)
    max_retries: int = Field(default=2, ge=0, le=5)
    max_output_tokens: int = Field(default=1024, ge=128, le=4096)
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
