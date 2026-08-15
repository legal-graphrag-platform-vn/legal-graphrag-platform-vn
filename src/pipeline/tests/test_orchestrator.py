from __future__ import annotations

from unittest.mock import patch
from datetime import date

import json

import pytest

from src.pipeline.config import settings
from src.pipeline.parser.models import Article, Clause, DocumentInfo, ParsedDocument
from src.pipeline.extraction.models import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
)
from src.pipeline.extraction.providers.base import FatalExtractionProviderError
from src.pipeline.pipeline.orchestrator import process_article, run_pipeline
from src.pipeline.extraction.structural_context import StructuralRegistry
from src.pipeline.extraction.provider_references import ProviderReferenceMentionV1
from src.pipeline.extraction.provider_relation_candidates import (
    ProviderRelationCandidateV1,
    write_provider_relation_candidates,
)
from src.pipeline.parser.hierarchy_parser import parse_text


def test_process_article_temporal_relations_properties() -> None:
    # 1.   Prepare mock data for the Article and DocumentInfo
    article = Article(
        number=17,
        title="Điều kiện thành lập doanh nghiệp",
        content_raw="Khoản 1. Không được thành lập doanh nghiệp...",
    )
    document = DocumentInfo(
        id="ldn_2020",
        title="Luật Doanh nghiệp",
        number="59/2020/QH14",
        doc_type="Law",
        effective_from=date(2021, 1, 1),
    )

    # 2.   Prepare mock extraction result containing a temporal relation and other relations
    mock_entities = [
        ExtractedEntity(id="dieu_17", type="Article", label="Điều 17"),
        ExtractedEntity(id="dieu_18", type="Article", label="Điều 18"),
        ExtractedEntity(id="entity_cong_ty", type="Entity", label="Công ty"),
        ExtractedEntity(id="concept_von", type="Concept", label="Vốn"),
    ]
    mock_relations = [
        ExtractedRelation(
            head="dieu_17",
            relation="AMENDS",
            tail="dieu_18",
            evidence="Điều 18 sửa đổi Điều 17",
            confidence=0.9,
        ),
        ExtractedRelation(
            head="entity_cong_ty",
            relation="REQUIRES",
            tail="concept_von",
            evidence="Công ty phải có vốn",
            confidence=0.8,
        ),
        ExtractedRelation(
            head="dieu_17",
            relation="REFERS_TO",
            tail="dieu_18",
            evidence="Theo Điều 18 của Luật này",
            confidence=0.7,
        ),
    ]
    mock_result = ExtractionResult(
        article_number=17,
        provider="gemini",
        configured_model="gemini:configured-alias",
        resolved_model="gemini-3.1-flash-lite",
        completed_at="2026-07-12T02:00:00+07:00",
        entities=mock_entities,
        relations=mock_relations,
    )

    # 3.   Execute process_article with extract_article mocked
    with patch(
        "src.pipeline.pipeline.orchestrator.extract_article", return_value=mock_result
    ):
        all_records = []
        registry = StructuralRegistry.from_parsed_document(
            ParsedDocument(
                document=document,
                articles=[article, Article(number=18, content_raw="Điều 18")],
            ),
            "L59_2020",
        )
        process_article(article, document, all_records, registry=registry)

        # 4.   Verify that all relations were processed and logged correctly
        assert len(all_records) == 3

        # 5.   Check AMENDS relation properties and validation state
        amended_record = next(
            r for r in all_records if r["relation"]["relation"] == "AMENDS"
        )
        assert amended_record["schema_valid"] is True
        assert amended_record["ontology_valid"] is True
        assert (
            amended_record["relation"]["properties"]["effective_from"] == "2021-01-01"
        )
        assert amended_record["relation"]["properties"]["source_doc_id"] == "ldn_2020"

        # 6.   Check REQUIRES relation properties
        requires_record = next(
            r for r in all_records if r["relation"]["relation"] == "REQUIRES"
        )
        assert (
            requires_record["relation"]["properties"]["source_article"]
            == "ldn_2020_art17"
        )
        assert requires_record["relation"]["properties"]["confidence"] == 0.8
        assert (
            requires_record["relation"]["properties"]["llm_model"]
            == "gemini:gemini-3.1-flash-lite"
        )
        assert (
            requires_record["relation"]["properties"]["created_at"]
            == "2026-07-11T19:00:00Z"
        )

        # 7.   Check REFERS_TO citation properties
        refers_record = next(
            r for r in all_records if r["relation"]["relation"] == "REFERS_TO"
        )
        assert refers_record["ontology_valid"] is True
        assert (
            refers_record["relation"]["properties"]["citation_text"]
            == "Theo Điều 18 của Luật này"
        )
        assert refers_record["relation"]["properties"]["citation_type"] == "DIRECT"
        assert refers_record["relation"]["properties"]["confidence"] == 0.7
        assert (
            refers_record["relation"]["properties"]["llm_model"]
            == "gemini:gemini-3.1-flash-lite"
        )
        assert (
            refers_record["relation"]["properties"]["created_at"]
            == "2026-07-11T19:00:00Z"
        )


def test_run_pipeline_accepts_resolved_provider_amendment_through_existing_gates(
    tmp_path,
) -> None:
    source = (
        "Điều 1. Sửa đổi\n"
        "1. Sửa đổi quy định sau:\n"
        "a) Sửa đổi [điểm a khoản 2] như sau.\n"
        "Điều 2. Hiệu lực\n"
        "Nghị định này có hiệu lực thi hành từ ngày 15 tháng 11 năm 2024."
    )
    document = DocumentInfo(
        id="nd_117_2024",
        title="Nghị định 117",
        number="117/2024/NĐ-CP",
        doc_type="Decree",
        issuer_name="Chính phủ",
    )
    parsed = parse_text(source, document)
    marker_start = source.index("[điểm a khoản 2]")
    reference = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="366692",
        provider_source_item_id="2732412",
        provider_target_document_id="186730",
        provider_target_item_ids=("1399134",),
        provider_relation_id="158258",
        provider_link_type="CHANGE_CONTENT",
        citation_text="điểm a khoản 2",
        source_char_start=marker_start,
        source_char_end=marker_start + len("[điểm a khoản 2]"),
    )
    candidate = ProviderRelationCandidateV1(
        candidate_id="provider-rel-test",
        provider_relation_id="158258",
        relation_candidate="AMENDS",
        source_ownership="HOST",
        host_source_id="nd_117_2024_art1_cl1_pa",
        canonical_source_id="nd_117_2024_art1_cl1_pa",
        canonical_source_type="Point",
        canonical_target_ids=("nd_82_2020_art2_cl2_pa",),
        canonical_target_types=("Point",),
        status="RESOLVED",
        reason_code="provider_endpoints_resolved",
        evidence="a) Sửa đổi [điểm a khoản 2] như sau.",
        reference=reference,
    )
    unresolved = candidate.model_copy(
        update={
            "candidate_id": "provider-rel-unresolved",
            "canonical_target_ids": (),
            "canonical_target_types": (),
            "status": "UNRESOLVED",
            "reason_code": "target_document_not_in_corpus",
        }
    )
    out_dir = tmp_path / "LTV_366692"
    write_provider_relation_candidates(
        out_dir / "provider_relation_candidates.jsonl", (candidate, unresolved)
    )

    with (
        patch.object(settings, "extraction_max_workers", 1),
        patch(
            "src.pipeline.pipeline.orchestrator.extract_article",
            return_value=ExtractionResult(
                article_number="1", entities=[], relations=[]
            ),
        ),
    ):
        run_pipeline(
            parsed,
            tmp_path,
            raw_doc_code="LTV_366692",
            source_text=source,
            article_numbers={"1"},
        )

    accepted = [
        json.loads(line)
        for line in (out_dir / "accepted.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    relation = next(
        record
        for record in accepted
        if record["relation"]["properties"].get("provider_relation_id") == "158258"
    )
    assert relation["relation"]["head"] == "nd_117_2024_art1_cl1_pa"
    assert relation["relation"]["tail"] == "nd_82_2020_art2_cl2_pa"
    assert relation["relation"]["relation"] == "AMENDS"
    assert relation["relation"]["properties"]["effective_from"] == "2024-11-15"
    assert relation["relation"]["properties"]["extraction_method"] == "PROVIDER_HTML"
    assert relation["schema_valid"] is True
    assert relation["ontology_valid"] is True
    assert relation["consistency_valid"] is True
    extraction_run = json.loads(
        (out_dir / "extraction_run.json").read_text(encoding="utf-8")
    )
    assert extraction_run["provider_candidate_count"] == 2
    assert extraction_run["provider_relation_record_count"] == 1


def test_run_pipeline_materializes_local_provider_reference_without_rule_duplicate(
    tmp_path,
) -> None:
    source = "Điều 1. Dẫn chiếu\n1. Thực hiện theo [Điều 2].\nĐiều 2. Quy định\n"
    parsed = parse_text(
        source,
        DocumentInfo(
            id="ldn_2020",
            title="Luật Doanh nghiệp",
            number="59/2020/QH14",
            doc_type="Law",
        ),
    )
    marker_start = source.index("[Điều 2]")
    reference = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="100",
        provider_target_document_id="100",
        provider_target_item_ids=("2",),
        provider_link_type="REFERENCE",
        citation_text="Điều 2",
        source_char_start=marker_start,
        source_char_end=marker_start + len("[Điều 2]"),
    )
    candidate = ProviderRelationCandidateV1(
        candidate_id="provider-ref-local",
        provider_relation_id=None,
        relation_candidate="REFERS_TO",
        source_ownership="HOST",
        host_source_id="ldn_2020_art1_cl1",
        canonical_source_id="ldn_2020_art1_cl1",
        canonical_source_type="Clause",
        canonical_target_ids=("ldn_2020_art2",),
        canonical_target_types=("Article",),
        status="RESOLVED",
        reason_code="provider_endpoints_resolved",
        evidence="1. Thực hiện theo [Điều 2].",
        reference=reference,
    )
    out_dir = tmp_path / "LTV_100"
    write_provider_relation_candidates(
        out_dir / "provider_relation_candidates.jsonl", (candidate,)
    )

    with (
        patch.object(settings, "extraction_max_workers", 1),
        patch(
            "src.pipeline.pipeline.orchestrator.extract_article",
            side_effect=lambda article_number, *_args, **_kwargs: ExtractionResult(
                article_number=str(article_number), entities=[], relations=[]
            ),
        ),
    ):
        run_pipeline(
            parsed,
            tmp_path,
            raw_doc_code="LTV_100",
            source_text=source,
        )

    accepted = [
        json.loads(line)
        for line in (out_dir / "accepted.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    references = [row for row in accepted if row["relation"]["relation"] == "REFERS_TO"]
    assert len(references) == 1
    relation = references[0]
    assert relation["relation"]["head"] == "ldn_2020_art1_cl1"
    assert relation["relation"]["tail"] == "ldn_2020_art2"
    assert relation["relation"]["properties"]["extraction_method"] == "ENTITY_LINKING"
    assert relation["materialization_route"] is None


def test_process_article_rejects_llm_contains_and_normalizes_clause() -> None:
    article = Article(
        number=5,
        content_raw="Khoản 1 quy định về doanh nghiệp",
        clauses=[Clause(number=1, content="Khoản 1 quy định về doanh nghiệp")],
    )
    document = DocumentInfo(
        id="ldn_2020", title="Luật Doanh nghiệp", number="59/2020/QH14", doc_type="Law"
    )
    result = ExtractionResult(
        article_number=5,
        provider="gemini",
        resolved_model="gemini-3.1-flash-lite",
        completed_at="2026-07-12T00:00:00Z",
        entities=[
            ExtractedEntity(id="khoan_1_1", type="Clause", label="Khoản 1"),
            ExtractedEntity(id="doanh_nghiep", type="Entity", label="Doanh nghiệp"),
        ],
        relations=[
            ExtractedRelation(
                head="khoan_1_1",
                relation="REGULATES",
                tail="doanh_nghiep",
                evidence="doanh nghiệp",
                confidence=1,
            ),
            ExtractedRelation(
                head="dieu_5",
                relation="CONTAINS",
                tail="khoan_1_1",
                evidence="Khoản 1",
                confidence=1,
            ),
        ],
    )
    records: list[dict] = []
    registry = StructuralRegistry.from_parsed_document(
        ParsedDocument(document=document, articles=[article]), "L59_2020"
    )
    process_article(
        article, document, records, registry=registry, extraction_result=result
    )

    regulates = next(
        record for record in records if record["relation"]["relation"] == "REGULATES"
    )
    contains = next(
        record for record in records if record["relation"]["relation"] == "CONTAINS"
    )
    assert regulates["relation"]["head"] == "ldn_2020_art5_cl1"
    assert regulates["endpoint_resolution"]["head"]["method"] == "structural_label"
    assert contains["ontology_valid"] is False
    assert contains["ontology_error"] == "llm_structural_relation_forbidden"


def test_orchestrator_aborts_and_writes_blocked_artifact_on_fatal_provider_error(
    tmp_path,
) -> None:
    parsed = ParsedDocument(
        document=DocumentInfo(
            id="ldn_2020",
            title="Luật Doanh nghiệp",
            number="59/2020/QH14",
            doc_type="Law",
            issuer_name="Quốc hội",
        ),
        articles=[
            Article(number=1, content_raw="Điều 1"),
            Article(number=2, content_raw="Điều 2"),
        ],
    )
    error = FatalExtractionProviderError("404 NOT_FOUND: model unavailable")

    with (
        patch.object(settings, "extraction_max_workers", 1),
        patch(
            "src.pipeline.pipeline.orchestrator._process_article_worker",
            side_effect=error,
        ) as worker,
    ):
        with pytest.raises(FatalExtractionProviderError):
            run_pipeline(parsed, tmp_path, raw_doc_code="L59_2020")

    assert worker.call_count == 1
    blocked = json.loads(
        (tmp_path / "L59_2020" / "extraction_blocked.json").read_text(encoding="utf-8")
    )
    assert blocked["blocked"] is True
    assert blocked["accepted_semantic_relation_count"] == 0
    assert "404 NOT_FOUND" in blocked["reason"]


def test_run_pipeline_reuses_matching_article_checkpoint(tmp_path) -> None:
    parsed = ParsedDocument(
        document=DocumentInfo(
            id="ldn_2020",
            title="Luật Doanh nghiệp",
            number="59/2020/QH14",
            doc_type="Law",
            issuer_name="Quốc hội",
        ),
        articles=[Article(number=5, content_raw="Điều 5")],
    )
    result = ExtractionResult(
        article_number=5,
        entities=[
            ExtractedEntity(id="doanh_nghiep", type="Entity", label="Doanh nghiệp")
        ],
        relations=[],
    )

    with (
        patch.object(settings, "extraction_max_workers", 1),
        patch(
            "src.pipeline.pipeline.orchestrator.extract_article", return_value=result
        ) as extractor,
    ):
        run_pipeline(parsed, tmp_path, raw_doc_code="L59_2020")
        run_pipeline(parsed, tmp_path, raw_doc_code="L59_2020")

    assert extractor.call_count == 1
    checkpoint = tmp_path / "L59_2020" / "article_extractions.jsonl"
    assert len(checkpoint.read_text(encoding="utf-8").splitlines()) == 1


def test_normalize_only_rejects_missing_checkpoint(tmp_path) -> None:
    parsed = ParsedDocument(
        document=DocumentInfo(
            id="ldn_2020",
            title="Luật Doanh nghiệp",
            number="59/2020/QH14",
            doc_type="Law",
        ),
        articles=[Article(number=5, content_raw="Điều 5")],
    )
    with pytest.raises(
        ValueError, match="Missing valid Article extraction checkpoints"
    ):
        run_pipeline(
            parsed,
            tmp_path,
            raw_doc_code="L59_2020",
            provider_calls_allowed=False,
        )


def test_run_pipeline_does_not_reuse_checkpoint_after_article_text_changes(
    tmp_path,
) -> None:
    document = DocumentInfo(
        id="ldn_2020", title="Luật Doanh nghiệp", number="59/2020/QH14", doc_type="Law"
    )
    first = ParsedDocument(
        document=document, articles=[Article(number=5, content_raw="Nội dung cũ")]
    )
    changed = ParsedDocument(
        document=document, articles=[Article(number=5, content_raw="Nội dung mới")]
    )
    result = ExtractionResult(article_number=5, entities=[], relations=[])

    with (
        patch.object(settings, "extraction_max_workers", 1),
        patch(
            "src.pipeline.pipeline.orchestrator.extract_article", return_value=result
        ) as extractor,
    ):
        run_pipeline(first, tmp_path, raw_doc_code="L59_2020")
        run_pipeline(changed, tmp_path, raw_doc_code="L59_2020")

    assert extractor.call_count == 2


def test_duplicate_article_checkpoint_is_rejected(tmp_path) -> None:
    parsed = ParsedDocument(
        document=DocumentInfo(
            id="ldn_2020",
            title="Luật Doanh nghiệp",
            number="59/2020/QH14",
            doc_type="Law",
        ),
        articles=[Article(number="5", content_raw="Điều 5")],
    )
    result = ExtractionResult(article_number="5", entities=[], relations=[])
    with (
        patch.object(settings, "extraction_max_workers", 1),
        patch(
            "src.pipeline.pipeline.orchestrator.extract_article", return_value=result
        ),
    ):
        run_pipeline(parsed, tmp_path, raw_doc_code="L59_2020")

    checkpoint = tmp_path / "L59_2020" / "article_extractions.jsonl"
    row = checkpoint.read_text(encoding="utf-8")
    checkpoint.write_text(row + row, encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate Article checkpoint: 5"):
        run_pipeline(
            parsed, tmp_path, raw_doc_code="L59_2020", provider_calls_allowed=False
        )


def test_resolved_model_change_blocks_mixed_checkpoints(tmp_path) -> None:
    document = DocumentInfo(
        id="ldn_2020", title="Luật Doanh nghiệp", number="59/2020/QH14", doc_type="Law"
    )
    first = ParsedDocument(
        document=document, articles=[Article(number="1", content_raw="Điều 1")]
    )
    expanded = ParsedDocument(
        document=document,
        articles=[
            Article(number="1", content_raw="Điều 1"),
            Article(number="2", content_raw="Điều 2"),
        ],
    )
    version_one = ExtractionResult(
        article_number="1", entities=[], relations=[], resolved_model="model-001"
    )
    version_two = ExtractionResult(
        article_number="2", entities=[], relations=[], resolved_model="model-002"
    )
    with (
        patch.object(settings, "extraction_max_workers", 1),
        patch(
            "src.pipeline.pipeline.orchestrator.extract_article",
            return_value=version_one,
        ),
    ):
        run_pipeline(first, tmp_path, raw_doc_code="L59_2020")
    with (
        patch.object(settings, "extraction_max_workers", 1),
        patch(
            "src.pipeline.pipeline.orchestrator.extract_article",
            return_value=version_two,
        ),
    ):
        with pytest.raises(RuntimeError, match="Resolved model changed"):
            run_pipeline(expanded, tmp_path, raw_doc_code="L59_2020")


def test_global_semantic_type_conflict_moves_relations_to_review(tmp_path) -> None:
    parsed = ParsedDocument(
        document=DocumentInfo(
            id="ldn_2020",
            title="Luật Doanh nghiệp",
            number="59/2020/QH14",
            doc_type="Law",
        ),
        articles=[
            Article(number="1", content_raw="Điều 1"),
            Article(number="2", content_raw="Điều 2"),
        ],
    )
    results = [
        ExtractionResult(
            article_number="1",
            resolved_model="gemini-3.1-flash-lite",
            entities=[
                ExtractedEntity(id="doanh_nghiep", type="Entity", label="Doanh nghiệp")
            ],
            relations=[
                ExtractedRelation(
                    head="ldn_2020_art1",
                    relation="REGULATES",
                    tail="doanh_nghiep",
                    evidence="Doanh nghiệp",
                    confidence=1,
                )
            ],
        ),
        ExtractionResult(
            article_number="2",
            resolved_model="gemini-3.1-flash-lite",
            entities=[
                ExtractedEntity(id="doanh_nghiep", type="Concept", label="Doanh nghiệp")
            ],
            relations=[
                ExtractedRelation(
                    head="ldn_2020_art2",
                    relation="DEFINES",
                    tail="doanh_nghiep",
                    evidence="Doanh nghiệp",
                    confidence=1,
                )
            ],
        ),
    ]
    with (
        patch.object(settings, "extraction_max_workers", 1),
        patch(
            "src.pipeline.pipeline.orchestrator.extract_article", side_effect=results
        ),
    ):
        run_pipeline(parsed, tmp_path, raw_doc_code="L59_2020")

    out = tmp_path / "L59_2020"
    review = [
        json.loads(line)
        for line in (out / "review.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    entity_index = json.loads((out / "entity_index.json").read_text(encoding="utf-8"))
    assert len(review) == 2
    assert {record["review_reason"] for record in review} == {"semantic_type_conflict"}
    assert "doanh_nghiep" not in entity_index
