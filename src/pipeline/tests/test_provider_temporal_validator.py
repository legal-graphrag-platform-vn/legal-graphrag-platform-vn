from __future__ import annotations

import pytest

from src.pipeline.extraction.corpus_structural_registry import build_corpus_registry
from src.pipeline.extraction.provider_references import ProviderReferenceMentionV1
from src.pipeline.extraction.provider_relation_candidates import (
    ProviderRelationCandidateV1,
)
from src.pipeline.tests.test_external_reference_validator import _payload
from src.pipeline.validation.provider_temporal_validator import (
    validate_provider_temporal_candidates,
)
from src.shared.ontology.validators import GraphValidationError


def _candidate(*, ownership: str = "HOST") -> ProviderRelationCandidateV1:
    mention = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="100",
        provider_target_document_id="200",
        provider_target_item_ids=("35",),
        provider_relation_id="101",
        provider_link_type="CHANGE_CONTENT",
        citation_text="Điều 35",
        source_char_start=20,
        source_char_end=30,
    )
    return ProviderRelationCandidateV1(
        candidate_id="provider-temporal-1",
        provider_relation_id="101",
        relation_candidate="AMENDS",
        source_ownership=ownership,
        host_source_id="source_doc_art1",
        canonical_source_id=(
            "projected_doc_art2" if ownership == "PROJECTED" else "source_doc_art1"
        ),
        canonical_source_type="Article",
        canonical_target_ids=("target_doc_art35",),
        canonical_target_types=("Article",),
        projection_basis_candidate_id=(
            "governing-provider-candidate" if ownership == "PROJECTED" else None
        ),
        status="RESOLVED",
        reason_code="provider_endpoints_resolved",
        evidence="Sửa đổi Điều 35",
        reference=mention,
    )


def _accepted_record(*, ownership: str = "HOST") -> dict:
    source_id = (
        "projected_doc_art2" if ownership == "PROJECTED" else "source_doc_art1"
    )
    properties = {
        "effective_from": "2024-01-01",
        "extraction_method": "PROVIDER_HTML",
        "provider_candidate_id": "provider-temporal-1",
        "provider_relation_id": "101",
        "materialization_route": "CORPUS_RELATION_RECONCILIATION",
        "source_ownership": ownership,
    }
    if ownership == "PROJECTED":
        properties.update(
            {
                "host_evidence_document_id": "source_doc",
                "host_evidence_source_unit_id": "source_doc_art1",
                "host_evidence_char_start": 20,
                "host_evidence_char_end": 30,
                "projection_basis_candidate_id": "governing-provider-candidate",
            }
        )
    return {
        "decision": "accepted",
        "provider_bundle_id": "provider-temporal-1",
        "relation": {
            "head": source_id,
            "relation": "AMENDS",
            "tail": "target_doc_art35",
            "properties": properties,
        },
    }


def _build():
    return build_corpus_registry(
        {
            "source": _payload("source_doc", "1/2024/QH15", "1"),
            "projected": _payload("projected_doc", "3/2022/QH15", "2"),
            "target": _payload("target_doc", "2/2020/QH14", "35"),
        },
        {
            "source": "Điều 1. Sửa đổi.",
            "projected": "Điều 2. Nội dung được sửa đổi.",
            "target": "Điều 35. Nội dung.",
        },
        build_id="provider-temporal-registry",
    )


def test_provider_temporal_candidate_requires_accepted_record_and_registry() -> None:
    result = validate_provider_temporal_candidates(
        (_candidate(),), (_accepted_record(),), _build()
    )

    assert result.ready_count == 1
    assert result.not_accepted_count == 0
    assert result.batch is not None
    wrapped = result.batch.relations[0]
    assert wrapped.source_document_id == "source_doc"
    assert wrapped.target_document_id == "target_doc"
    assert wrapped.relation.relation_type == "AMENDS"
    assert wrapped.relation.properties["relation_id"]
    assert "materialization_route" not in wrapped.relation.properties


def test_projected_temporal_candidate_uses_dual_provenance() -> None:
    result = validate_provider_temporal_candidates(
        (_candidate(ownership="PROJECTED"),),
        (_accepted_record(ownership="PROJECTED"),),
        _build(),
    )

    assert result.projected_blocked_count == 0
    assert result.ready_count == 1
    assert result.batch is not None
    properties = result.batch.relations[0].relation.properties
    assert properties["source_ownership"] == "PROJECTED"
    assert properties["host_evidence_source_unit_id"] == "source_doc_art1"


def test_temporal_candidate_without_decision_gate_record_is_not_ready() -> None:
    result = validate_provider_temporal_candidates((_candidate(),), (), _build())

    assert result.not_accepted_count == 1
    assert result.ready_count == 0
    assert result.batch is None


def test_stale_temporal_candidate_conflicting_with_registry_number_is_blocked() -> None:
    candidate = _candidate()
    conflicting_reference = candidate.reference.model_copy(
        update={"citation_text": "Điều 35 Luật số 99/2019/QH14"}
    )
    candidate = candidate.model_copy(update={"reference": conflicting_reference})

    with pytest.raises(GraphValidationError, match="provider_text_target_conflict"):
        validate_provider_temporal_candidates(
            (candidate,), (_accepted_record(),), _build()
        )
