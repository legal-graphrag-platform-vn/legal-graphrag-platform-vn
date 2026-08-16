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
    StructuralReadinessError,
    validate_extraction_readiness,
    validate_structural_readiness,
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


def load_validated_payload(
    processed_dir: Path,
    *,
    mode: str = "full",
) -> LoadedValidatedPayload:
    # 1.   Validate readiness and build raw graph payload based on mode
    try:
        if mode == "structural":
            validate_structural_readiness(processed_dir)
            raw_payload = build_payload_from_paths(processed_dir, mode="structural")
        else:
            validate_extraction_readiness(processed_dir)
            raw_payload = build_payload_from_paths(processed_dir, mode="full")
    except (
        ExtractionReadinessError,
        StructuralReadinessError,
        PayloadBuildError,
    ) as exc:
        raise ValidatedPayloadLoadError(str(exc)) from exc

    # 2.   Validate graph payload consistency and ontology conformance
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


def load_validated_structural_payload(processed_dir: Path) -> LoadedValidatedPayload:
    # 1.   Helper to load structural-only validated payload
    return load_validated_payload(processed_dir, mode="structural")

