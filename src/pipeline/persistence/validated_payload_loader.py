"""Pure root-validation loader shared by CLI and registry workflows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.pipeline.persistence.payload_builder import (
    PayloadBuildError,
    build_payload_from_paths,
)
from src.pipeline.validation.extraction_readiness import (
    ExtractionReadinessError,
    validate_extraction_readiness,
)
from src.shared.ontology.payload_consistency_validator import (
    validate_payload_consistency,
)
from src.shared.ontology.validators import (
    GraphValidationError,
    ValidatedGraphPayload,
    validate_graph_payload,
)


class ValidatedPayloadLoadError(ValueError):
    """Raised when processed artifacts cannot pass the root write gate."""


@dataclass(frozen=True, slots=True)
class LoadedValidatedPayload:
    raw_payload: dict
    validated_payload: ValidatedGraphPayload


def load_validated_payload(processed_dir: Path) -> LoadedValidatedPayload:
    try:
        validate_extraction_readiness(processed_dir)
        raw_payload = build_payload_from_paths(processed_dir)
    except (ExtractionReadinessError, PayloadBuildError) as exc:
        raise ValidatedPayloadLoadError(str(exc)) from exc

    consistency = validate_payload_consistency(raw_payload)
    if not consistency.valid:
        raise ValidatedPayloadLoadError("; ".join(consistency.errors))
    try:
        validated = validate_graph_payload(raw_payload)
    except GraphValidationError as exc:
        raise ValidatedPayloadLoadError("; ".join(exc.errors)) from exc
    return LoadedValidatedPayload(
        raw_payload=raw_payload,
        validated_payload=validated,
    )
