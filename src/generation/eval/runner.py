"""Deterministic hard checks for pilot answer-generation outputs."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from src.generation.eval.models import AnswerEvaluationCase, AnswerEvaluationDataset
from src.generation.models import AnswerGenerationRequest, AnswerResponse
from src.retrieval.errors import RetrievalCapabilityError
from src.retrieval.models import RetrievalContext
from src.shared.retrieval_contract import RetrievalFilters, RetrievalRequest


class RetrievalPort(Protocol):
    def retrieve(self, request: RetrievalRequest) -> RetrievalContext: ...


class GenerationPort(Protocol):
    async def generate(self, request: AnswerGenerationRequest) -> AnswerResponse: ...


@dataclass(frozen=True)
class EvaluationMetadata:
    source_commit: str
    working_tree_state: str
    dataset_sha256: str
    graph_snapshot_hash: str
    retrieval_contract_version: str
    answer_contract_version: str
    prompt_sha256: str
    generation_config_sha256: str
    provider: str
    model: str


class AnswerEvaluationRunner:
    def __init__(self, retrieval: RetrievalPort, generation: GenerationPort) -> None:
        self._retrieval = retrieval
        self._generation = generation

    async def run(
        self,
        dataset: AnswerEvaluationDataset,
        metadata: EvaluationMetadata,
    ) -> dict[str, object]:
        cases = [
            await self._run_case(case, dataset.document_ids) for case in dataset.cases
        ]
        hard_pass_count = sum(case["hard_status"] == "pass" for case in cases)
        human_pending_count = sum(
            case["human_review_status"] != "approved" for case in cases
        )
        return {
            "contract_version": "answer-evaluation-report-v1",
            "evaluation_scope": dataset.evaluation_scope,
            "metadata": {
                **metadata.__dict__,
                "dataset_review_status": dataset.review.status,
            },
            "summary": {
                "case_count": len(cases),
                "hard_pass_count": hard_pass_count,
                "hard_fail_count": len(cases) - hard_pass_count,
                "human_pending_count": human_pending_count,
                "technical_checks_status": (
                    "PASS" if hard_pass_count == len(cases) else "FAIL"
                ),
                "human_legal_review_status": (
                    "PASS" if human_pending_count == 0 else "PENDING"
                ),
                "official_evidence_eligible": (
                    hard_pass_count == len(cases)
                    and human_pending_count == 0
                    and metadata.working_tree_state == "clean"
                ),
            },
            "cases": cases,
            "status": {
                "Gate 7 / M3-B13": "OPEN",
                "Milestone A": "NOT PASSED",
                "Milestone B acceptance": "NOT STARTED",
            },
        }

    async def _run_case(
        self,
        case: AnswerEvaluationCase,
        document_ids: tuple[str, ...],
    ) -> dict[str, object]:
        started = time.perf_counter()
        request = RetrievalRequest(
            query=case.query,
            filters=RetrievalFilters(
                document_ids=list(document_ids),
                query_date=case.query_date,
            ),
            force_intent=case.intent,
        )
        try:
            context = self._retrieval.retrieve(request)
        except RetrievalCapabilityError as exc:
            matched = (
                case.expected_outcome == "unsupported_capability"
                and exc.required_capability == case.required_capability
            )
            return {
                "query_id": case.query_id,
                "expected_outcome": case.expected_outcome,
                "actual_outcome": "unsupported_capability",
                "required_capability": case.required_capability,
                "reported_capability": exc.required_capability,
                "hard_status": "pass" if matched else "fail",
                "hard_failures": ([] if matched else ["UNEXPECTED_CAPABILITY_ERROR"]),
                "human_review_status": case.review.status,
                "latency_ms": _elapsed_ms(started),
            }

        if case.expected_outcome == "unsupported_capability":
            return {
                "query_id": case.query_id,
                "expected_outcome": case.expected_outcome,
                "actual_outcome": "retrieval_supported",
                "required_capability": case.required_capability,
                "hard_status": "fail",
                "hard_failures": ["EXPECTED_CAPABILITY_ERROR_NOT_RAISED"],
                "human_review_status": case.review.status,
                "latency_ms": _elapsed_ms(started),
            }

        answer = await self._generation.generate(
            AnswerGenerationRequest(query=case.query, retrieval_context=context)
        )
        failures = _hard_failures(case, answer)
        return {
            "query_id": case.query_id,
            "expected_outcome": case.expected_outcome,
            "actual_outcome": "cannot_answer" if answer.cannot_answer else "answered",
            "hard_status": "pass" if not failures else "fail",
            "hard_failures": failures,
            "answer_text": answer.answer_text,
            "citation_ids": [item.unit_id for item in answer.citations],
            "temporal_notes": list(answer.temporal_notes),
            "gold_key_claims": list(case.gold_key_claims),
            "human_review_status": case.review.status,
            "provider": answer.provider,
            "model": answer.model,
            "latency_ms": _elapsed_ms(started),
        }


def _hard_failures(
    case: AnswerEvaluationCase,
    answer: AnswerResponse,
) -> list[str]:
    failures: list[str] = []
    if answer.cannot_answer:
        failures.append("UNEXPECTED_CANNOT_ANSWER")
        return failures
    cited = {item.unit_id for item in answer.citations}
    for index, group in enumerate(case.required_citation_groups):
        if cited.isdisjoint(group):
            failures.append(f"MISSING_CITATION_GROUP_{index + 1}")
    if case.expected_temporal_valid is not None and not answer.temporal_notes:
        failures.append("MISSING_TEMPORAL_DECISION")
    return failures


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
