from __future__ import annotations

from src.pipeline.extraction.corpus_structural_registry import build_corpus_registry
from src.pipeline.extraction.structural_context import StructuralRegistry
from src.pipeline.extraction.structural_references import (
    RESOLVER_NAME,
    RESOLVER_VERSION,
    StructuralReferenceResolver,
)
from src.pipeline.parser.hierarchy_parser import parse_text
from src.pipeline.parser.models import DocumentInfo
from src.pipeline.pipeline.reference_checkpoint_store import checkpoint_from_reference
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
