from __future__ import annotations

import pytest

from src.pipeline.extraction.corpus_structural_registry import build_corpus_registry
from src.pipeline.extraction.structural_context import StructuralRegistry
from src.pipeline.extraction.structural_references import (
    RESOLVER_NAME,
    RESOLVER_VERSION,
    StructuralReferenceResolver,
)
from src.pipeline.extraction.provider_references import ProviderReferenceMentionV1
from src.pipeline.extraction.provider_relation_candidates import (
    ProviderRelationCandidateV1,
)
from src.pipeline.parser.hierarchy_parser import parse_text
from src.pipeline.parser.models import DocumentInfo
from src.pipeline.pipeline.reference_checkpoint_store import checkpoint_from_reference
from src.pipeline.pipeline.external_reference_reconciliation import (
    _provider_external_references,
)
from src.pipeline.validation.external_reference_validator import (
    ExternalReferenceValidationError,
    validate_external_reference_bundle,
)
from src.shared.ontology.validators import validate_graph_payload


def _payload(document_id: str, number: str, article: str):
    return validate_graph_payload(
        {
            "nodes": [
                {
                    "type": "Document",
                    "id": document_id,
                    "number": number,
                    "doc_type": "Law",
                    "normative": True,
                    "legal_status": "ACTIVE",
                    "effective_from": "2021-01-01",
                    "issuer_name": "Quốc hội",
                },
                {
                    "type": "Article",
                    "id": f"{document_id}_art{article}",
                    "number": article,
                    "content_raw": "Điều",
                    "effective_from": "2021-01-01",
                    "legal_status": "ACTIVE",
                },
            ],
            "relations": [
                {
                    "head_id": document_id,
                    "type": "CONTAINS",
                    "tail_id": f"{document_id}_art{article}",
                    "properties": {},
                }
            ],
        }
    )


def _payload_many(document_id: str, number: str, articles: tuple[str, ...]):
    payload = {
        "nodes": [
            {
                "type": "Document",
                "id": document_id,
                "number": number,
                "doc_type": "Law",
                "normative": True,
                "legal_status": "ACTIVE",
                "effective_from": "2021-01-01",
                "issuer_name": "Quốc hội",
            }
        ],
        "relations": [],
    }
    for article in articles:
        payload["nodes"].append(
            {
                "type": "Article",
                "id": f"{document_id}_art{article}",
                "number": article,
                "content_raw": "Điều",
                "effective_from": "2021-01-01",
                "legal_status": "ACTIVE",
            }
        )
        payload["relations"].append(
            {
                "head_id": document_id,
                "type": "CONTAINS",
                "tail_id": f"{document_id}_art{article}",
                "properties": {},
            }
        )
    return validate_graph_payload(payload)


def _checkpoint_and_build():
    text = "Điều 1. Áp dụng Điều 35 Luật số 68/2014/QH13."
    document = DocumentInfo(
        id="ldn_2020", title="Luật", number="59/2020/QH14", doc_type="Law"
    )
    parsed = parse_text(text, document)
    build = build_corpus_registry(
        {
            "source": _payload("ldn_2020", "59/2020/QH14", "1"),
            "target": _payload("ldn_2014", "68/2014/QH13", "35"),
        },
        {"source": text, "target": "Điều 35. Nội dung."},
        build_id="registry-test",
    )
    local = StructuralRegistry.from_parsed_document(parsed, "L59")
    reference = StructuralReferenceResolver(
        local,
        text,
        corpus_registry=build.registry,
        registry_receipt=build.receipt,
    ).resolve_article(parsed.articles[0])[0]
    checkpoint = checkpoint_from_reference(
        reference,
        resolver_name=RESOLVER_NAME,
        resolver_version=RESOLVER_VERSION,
    )
    return checkpoint, build


def test_external_validator_builds_root_tokened_relation_batch() -> None:
    checkpoint, build = _checkpoint_and_build()

    batch = validate_external_reference_bundle([checkpoint], build)

    assert batch.registry_build_id == "registry-test"
    assert len(batch.references) == 1
    wrapped = batch.references[0]
    assert wrapped.source_document_id == "ldn_2020"
    assert wrapped.target_document_id == "ldn_2014"
    assert wrapped.relation.relation_type == "REFERS_TO"
    assert wrapped.relation.properties["extraction_method"] == "ENTITY_LINKING"
    assert wrapped.relation.properties["relation_id"]


def test_external_validator_rejects_mixed_snapshot_evidence() -> None:
    checkpoint, build = _checkpoint_and_build()
    bad_resolution = checkpoint.resolution.model_copy(
        update={"snapshot_hash": "sha256:" + "0" * 64}
    )
    tampered = checkpoint.model_copy(update={"resolution": bad_resolution})

    try:
        validate_external_reference_bundle([tampered], build)
    except ExternalReferenceValidationError as exc:
        assert "registry build evidence mismatch" in str(exc)
    else:
        raise AssertionError("tampered snapshot evidence was accepted")


def test_provider_external_reference_uses_provider_identity_not_text_rediscovery() -> (
    None
):
    source_text = "Điều 1. Thực hiện theo [Điều 35]."
    start = source_text.index("[Điều 35]")
    build = build_corpus_registry(
        {
            "source": _payload("ldn_2020", "59/2020/QH14", "1"),
            "target": _payload("ldn_2014", "68/2014/QH13", "35"),
        },
        {"source": source_text, "target": "Điều 35. Nội dung."},
        build_id="provider-registry-test",
    )
    mention = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="100",
        provider_target_document_id="200",
        provider_target_item_ids=("35",),
        provider_link_type="REFERENCE",
        citation_text="Điều 35",
        source_char_start=start,
        source_char_end=start + len("[Điều 35]"),
    )
    candidate = ProviderRelationCandidateV1(
        candidate_id="provider-external-ref",
        provider_relation_id=None,
        relation_candidate="REFERS_TO",
        source_ownership="HOST",
        host_source_id="ldn_2020_art1",
        canonical_source_id="ldn_2020_art1",
        canonical_source_type="Article",
        canonical_target_ids=("ldn_2014_art35",),
        canonical_target_types=("Article",),
        status="RESOLVED",
        reason_code="provider_endpoints_resolved",
        evidence=source_text,
        reference=mention,
    )

    references = _provider_external_references(
        (candidate,), source_text=source_text, build=build
    )
    checkpoint = checkpoint_from_reference(
        references[0], resolver_name=RESOLVER_NAME, resolver_version=RESOLVER_VERSION
    )
    batch = validate_external_reference_bundle([checkpoint], build)

    assert references[0].target_unit_ids == ("ldn_2014_art35",)
    assert references[0].mention.raw_text == "[Điều 35]"
    assert batch.references[0].relation.properties["citation_text"] == "[Điều 35]"


def test_projected_provider_reference_uses_dual_provenance() -> None:
    source_text = "Điều 1. Sửa đổi: “Áp dụng [Điều 35].”"
    start = source_text.index("[Điều 35]")
    build = build_corpus_registry(
        {
            "host": _payload("amending_doc", "1/2024/QH15", "1"),
            "source": _payload("ldn_2020", "59/2020/QH14", "1"),
            "target": _payload("ldn_2014", "68/2014/QH13", "35"),
        },
        {
            "host": source_text,
            "source": "Điều 1. Nội dung được sửa đổi.",
            "target": "Điều 35. Nội dung.",
        },
        build_id="projected-provider-registry-test",
    )
    mention = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="100",
        provider_target_document_id="200",
        provider_target_item_ids=("35",),
        provider_link_type="REFERENCE",
        citation_text="Điều 35",
        source_char_start=start,
        source_char_end=start + len("[Điều 35]"),
    )
    candidate = ProviderRelationCandidateV1(
        candidate_id="projected-provider-ref",
        provider_relation_id=None,
        relation_candidate="REFERS_TO",
        source_ownership="PROJECTED",
        host_source_id="amending_doc_art1",
        canonical_source_id="ldn_2020_art1",
        canonical_source_type="Article",
        canonical_target_ids=("ldn_2014_art35",),
        canonical_target_types=("Article",),
        projection_basis_candidate_id="governing-provider-candidate",
        status="RESOLVED",
        reason_code="provider_endpoints_resolved",
        evidence=source_text,
        reference=mention,
    )

    references = _provider_external_references(
        (candidate,), source_text=source_text, build=build
    )

    checkpoint = checkpoint_from_reference(
        references[0], resolver_name=RESOLVER_NAME, resolver_version=RESOLVER_VERSION
    )
    batch = validate_external_reference_bundle([checkpoint], build)

    properties = batch.references[0].relation.properties
    assert properties["source_ownership"] == "PROJECTED"
    assert properties["source_unit_id"] == "ldn_2020_art1"
    assert properties["host_evidence_source_unit_id"] == "amending_doc_art1"
    assert properties["projection_basis_candidate_id"] == (
        "governing-provider-candidate"
    )
    assert "source_char_start" not in properties


def test_projected_same_document_reference_is_materialized() -> None:
    source_text = "Điều 1. Sửa đổi: “Áp dụng [Điều 35].”"
    start = source_text.index("[Điều 35]")
    build = build_corpus_registry(
        {
            "host": _payload("amending_doc", "1/2024/QH15", "1"),
            "projected": _payload_many(
                "projected_doc", "2/2020/QH14", ("1", "35")
            ),
        },
        {
            "host": source_text,
            "projected": "Điều 1. Nội dung.\nĐiều 35. Nội dung.",
        },
        build_id="projected-local-registry-test",
    )
    mention = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="100",
        provider_target_document_id="200",
        provider_target_item_ids=("35",),
        provider_link_type="REFERENCE",
        citation_text="Điều 35",
        source_char_start=start,
        source_char_end=start + len("[Điều 35]"),
    )
    candidate = ProviderRelationCandidateV1(
        candidate_id="projected-local-ref",
        provider_relation_id=None,
        relation_candidate="REFERS_TO",
        source_ownership="PROJECTED",
        host_source_id="amending_doc_art1",
        canonical_source_id="projected_doc_art1",
        canonical_source_type="Article",
        canonical_target_ids=("projected_doc_art35",),
        canonical_target_types=("Article",),
        projection_basis_candidate_id="governing-provider-candidate",
        status="RESOLVED",
        reason_code="provider_endpoints_resolved",
        evidence=source_text,
        reference=mention,
    )

    reference = _provider_external_references(
        (candidate,), source_text=source_text, build=build
    )[0]
    checkpoint = checkpoint_from_reference(
        reference, resolver_name=RESOLVER_NAME, resolver_version=RESOLVER_VERSION
    )
    batch = validate_external_reference_bundle([checkpoint], build)

    assert checkpoint.resolution.reference_scope == "LOCAL"
    assert checkpoint.materialization.status == "PENDING"
    assert len(batch.references) == 1


def test_provider_multi_target_reference_is_one_atomic_checkpoint() -> None:
    source_text = "Điều 1. Theo [Điều 35 và Điều 36]."
    start = source_text.index("[Điều 35")
    marker = "[Điều 35 và Điều 36]"
    build = build_corpus_registry(
        {
            "source": _payload("source_doc", "1/2024/QH15", "1"),
            "target": _payload_many("target_doc", "2/2020/QH14", ("35", "36")),
        },
        {
            "source": source_text,
            "target": "Điều 35. Nội dung.\nĐiều 36. Nội dung.",
        },
        build_id="provider-multi-target-test",
    )
    mention = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="100",
        provider_target_document_id="200",
        provider_target_item_ids=("35", "36"),
        provider_link_type="REFERENCE",
        citation_text="Điều 35 và Điều 36",
        source_char_start=start,
        source_char_end=start + len(marker),
    )
    candidate = ProviderRelationCandidateV1(
        candidate_id="provider-multi-target",
        provider_relation_id=None,
        relation_candidate="REFERS_TO",
        source_ownership="HOST",
        host_source_id="source_doc_art1",
        canonical_source_id="source_doc_art1",
        canonical_source_type="Article",
        canonical_target_ids=("target_doc_art35", "target_doc_art36"),
        canonical_target_types=("Article", "Article"),
        status="RESOLVED",
        reason_code="provider_endpoints_resolved",
        evidence=source_text,
        reference=mention,
    )

    reference = _provider_external_references(
        (candidate,), source_text=source_text, build=build
    )[0]
    checkpoint = checkpoint_from_reference(
        reference, resolver_name=RESOLVER_NAME, resolver_version=RESOLVER_VERSION
    )
    batch = validate_external_reference_bundle([checkpoint], build)

    assert checkpoint.resolution.target_ids == (
        "target_doc_art35",
        "target_doc_art36",
    )
    assert len(batch.references) == 2
    assert {
        item.relation.properties["reference_target_count"]
        for item in batch.references
    } == {2}


def test_stale_provider_candidate_conflicting_with_registry_number_is_blocked() -> None:
    source_text = "Điều 1. Thực hiện theo [Khoản 1 Điều 35 Luật số 59/2020/QH14]."
    start = source_text.index("[Khoản 1")
    build = build_corpus_registry(
        {
            "source": _payload("source_doc", "1/2024/QH15", "1"),
            "target": _payload("target_doc", "68/2014/QH13", "35"),
        },
        {"source": source_text, "target": "Điều 35. Nội dung."},
        build_id="provider-conflict-registry-test",
    )
    mention = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="100",
        provider_target_document_id="200",
        provider_target_item_ids=("35",),
        provider_link_type="REFERENCE",
        citation_text="Khoản 1 Điều 35 Luật số 59/2020/QH14",
        source_char_start=start,
        source_char_end=start + len("[Khoản 1 Điều 35 Luật số 59/2020/QH14]"),
    )
    stale_candidate = ProviderRelationCandidateV1(
        candidate_id="stale-provider-conflict",
        provider_relation_id=None,
        relation_candidate="REFERS_TO",
        source_ownership="HOST",
        host_source_id="source_doc_art1",
        canonical_source_id="source_doc_art1",
        canonical_source_type="Article",
        canonical_target_ids=("target_doc_art35",),
        canonical_target_types=("Article",),
        status="RESOLVED",
        reason_code="provider_endpoints_resolved",
        evidence=source_text,
        reference=mention,
    )

    with pytest.raises(ValueError, match="provider_text_target_conflict"):
        _provider_external_references(
            (stale_candidate,), source_text=source_text, build=build
        )
