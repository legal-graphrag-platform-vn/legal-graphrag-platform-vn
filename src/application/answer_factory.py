"""The only concrete assembly point for answer generation."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.generation.config import GenerationConfig
from src.generation.context_projection import ContextProjector
from src.generation.errors import AnswerProviderDependencyError
from src.generation.grounding import GroundingValidator
from src.generation.service import AnswerGenerator
from src.generation.sufficiency import EvidenceSufficiencyPolicy
from src.infrastructure.llm.gemini_answer_provider import GeminiAnswerProvider


class AnswerApplicationSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    answer_provider: str = Field(default="gemini", validation_alias="ANSWER_PROVIDER")
    answer_model: str = Field(
        default="gemini-3.5-flash",
        validation_alias="ANSWER_MODEL",
    )
    gemini_api_key: str | None = Field(
        default=None,
        validation_alias="GEMINI_API_KEY",
    )


def create_answer_generator(
    config: GenerationConfig | None = None,
    settings: AnswerApplicationSettings | None = None,
) -> AnswerGenerator:
    runtime_config = config or GenerationConfig()
    application_settings = settings or AnswerApplicationSettings()
    if application_settings.answer_provider != "gemini":
        raise AnswerProviderDependencyError(
            f"Unsupported answer provider: {application_settings.answer_provider}"
        )
    provider = GeminiAnswerProvider(
        api_key=application_settings.gemini_api_key or "",
        model=application_settings.answer_model,
        config=runtime_config,
    )
    return AnswerGenerator(
        provider=provider,
        projector=ContextProjector(runtime_config),
        sufficiency=EvidenceSufficiencyPolicy(),
        grounding=GroundingValidator(),
    )
