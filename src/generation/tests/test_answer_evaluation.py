from __future__ import annotations

import asyncio
import json

import pytest

from src.generation.eval.models import AnswerEvaluationDataset
from src.generation.eval.runner import AnswerEvaluationRunner, EvaluationMetadata
from src.generation.eval.cli import _write_atomic
from src.generation.models import (
    AnswerCitation,
    AnswerClaim,
    AnswerGenerationRequest,
    AnswerResponse,
)
from src.generation.tests.factories import retrieval_context
from src.retrieval.errors import RetrievalCapabilityError


class FakeRetrieval:
    def __init__(self, *, unsupported: bool = False) -> None:
        self.unsupported = unsupported

    def retrieve(self, request):
        if self.unsupported:
            raise RetrievalCapabilityError(
                "missing capability",
                required_capability="multiple_versions",
                available_capability="none",
            )
        context = retrieval_context(intent=request.force_intent)
        return context.model_copy(update={"query": request.query})


class FakeGeneration:
    def __init__(self, citation_id: str = "doc_art1") -> None:
        self.citation_id = citation_id

    async def generate(self, request: AnswerGenerationRequest) -> AnswerResponse:
        unit = request.retrieval_context.retrieved_units[0]
        claim = AnswerClaim(
            claim_id="claim-1",
            text="Câu trả lời có căn cứ.",
            citation_ids=[self.citation_id],
        )
        return AnswerResponse(
            retrieval_contract_version=request.retrieval_context.contract_version,
            query=request.query,
            answer_text="Câu trả lời có căn cứ. [Điều 1]",
            claims=(claim,),
            citations=(
                AnswerCitation(
                    unit_id=self.citation_id,
                    citation_label=unit.citation_label,
                    document_id=unit.document_id,
                    article_id=unit.article_id,
                    clause_id=unit.clause_id,
                    deep_link=unit.deep_link,
                ),
            ),
            reasoning_paths=(),
            temporal_notes=(),
            cannot_answer=False,
            insufficiency_reason=None,
            confidence=0.8,
            provider="fake",
            model="fake-model",
            intent=request.retrieval_context.intent.value,
            strategy=request.retrieval_context.strategy.value,
        )


def test_answer_evaluation_passes_hard_citation_check() -> None:
    report = asyncio.run(
        AnswerEvaluationRunner(FakeRetrieval(), FakeGeneration()).run(
            _dataset(), _metadata()
        )
    )

    assert report["summary"]["technical_checks_status"] == "PASS"
    assert report["summary"]["human_legal_review_status"] == "PENDING"
    assert report["summary"]["official_evidence_eligible"] is False


def test_answer_evaluation_reports_missing_required_citation() -> None:
    report = asyncio.run(
        AnswerEvaluationRunner(
            FakeRetrieval(), FakeGeneration("doc_art_unrelated")
        ).run(_dataset(), _metadata())
    )

    assert report["summary"]["technical_checks_status"] == "FAIL"
    assert report["cases"][0]["hard_failures"] == ["MISSING_CITATION_GROUP_1"]


def test_expected_unsupported_capability_is_not_an_empty_result() -> None:
    dataset = _dataset(expected_outcome="unsupported_capability")
    report = asyncio.run(
        AnswerEvaluationRunner(FakeRetrieval(unsupported=True), FakeGeneration()).run(
            dataset, _metadata()
        )
    )

    assert report["cases"][0]["actual_outcome"] == "unsupported_capability"
    assert report["cases"][0]["hard_status"] == "pass"


def test_atomic_report_write_cleans_temp_file_on_failure(tmp_path, monkeypatch) -> None:
    output = tmp_path / "report.json"

    def fail_dump(*args, **kwargs):
        raise TypeError("not serializable")

    monkeypatch.setattr(json, "dump", fail_dump)
    with pytest.raises(TypeError, match="not serializable"):
        _write_atomic(output, {"status": "PASS"})

    assert not output.exists()
    assert list(tmp_path.iterdir()) == []


def _dataset(*, expected_outcome: str = "answered") -> AnswerEvaluationDataset:
    case = {
        "query_id": "factual_01",
        "query": "Ai có quyền thành lập doanh nghiệp?",
        "intent": "factual",
        "expected_outcome": expected_outcome,
        "required_capability": (
            "multiple_versions"
            if expected_outcome == "unsupported_capability"
            else None
        ),
        "required_citation_groups": (
            [] if expected_outcome == "unsupported_capability" else [["doc_art1"]]
        ),
        "gold_key_claims": (
            [] if expected_outcome == "unsupported_capability" else ["Có quyền."]
        ),
        "review": {"status": "pending"},
    }
    return AnswerEvaluationDataset.model_validate(
        {
            "schema_version": "answer-evaluation-dataset-v1",
            "evaluation_scope": "pilot_development",
            "name": "test",
            "source_retrieval_dataset": "retrieval.json",
            "document_ids": ["doc"],
            "review": {"status": "pending"},
            "cases": [case],
        }
    )


def _metadata() -> EvaluationMetadata:
    return EvaluationMetadata(
        source_commit="abc123",
        working_tree_state="dirty",
        dataset_sha256="dataset",
        graph_snapshot_hash="graph",
        retrieval_contract_version="retrieval-runtime-v2",
        answer_contract_version="answer-generation-v1",
        prompt_sha256="prompt",
        generation_config_sha256="config",
        provider="fake",
        model="fake-model",
    )
