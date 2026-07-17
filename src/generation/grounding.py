"""Hard citation, path, and temporal validation with trusted rendering."""

from __future__ import annotations

from src.generation.errors import (
    CitationValidationError,
    GroundingValidationError,
    ReasoningPathValidationError,
    TemporalAnswerValidationError,
)
from src.generation.models import (
    AnswerCandidate,
    AnswerCitation,
    AnswerReasoningPath,
    AnswerResponse,
    EvidenceRegistry,
    ProjectedAnswerContext,
)


class GroundingValidator:
    def validate_and_render(
        self,
        *,
        candidate: AnswerCandidate,
        projected: ProjectedAnswerContext,
        registry: EvidenceRegistry,
        retrieval_contract_version: str,
        provider: str,
        model: str,
    ) -> AnswerResponse:
        if candidate.cannot_answer:
            return AnswerResponse(
                retrieval_contract_version=retrieval_contract_version,
                query=projected.query,
                answer_text="Không đủ căn cứ trong dữ liệu truy xuất để trả lời chắc chắn.",
                claims=(),
                citations=(),
                reasoning_paths=(),
                temporal_notes=(),
                cannot_answer=True,
                insufficiency_reason=candidate.insufficiency_reason,
                confidence=candidate.confidence,
                provider=provider,
                model=model,
                intent=projected.intent,
                strategy=projected.strategy,
            )

        evidence_by_id = {item.unit_id: item for item in registry.entries}
        citation_order: list[str] = []
        for claim in candidate.claims:
            if not claim.text.strip():
                raise GroundingValidationError("Answer claim text must not be blank")
            for citation_id in claim.citation_ids:
                if citation_id not in evidence_by_id:
                    raise CitationValidationError(
                        f"Citation is not allowlisted: {citation_id}"
                    )
                if citation_id not in citation_order:
                    citation_order.append(citation_id)

        paths_by_id = {
            path.path_id: path
            for path in projected.paths
            if path.path_id in registry.allowed_path_ids
        }
        selected_paths: list[AnswerReasoningPath] = []
        for path_id in candidate.reasoning_path_ids:
            path = paths_by_id.get(path_id)
            if path is None:
                raise ReasoningPathValidationError(
                    f"Reasoning path is not allowlisted: {path_id}"
                )
            selected_paths.append(
                AnswerReasoningPath(
                    path_id=path.path_id,
                    nodes=path.nodes,
                    edges=path.edges,
                    description=path.description,
                )
            )

        temporal_notes = tuple(
            self._validate_temporal(assertion, projected, evidence_by_id)
            for assertion in candidate.temporal_assertions
        )
        citations = tuple(
            AnswerCitation(
                unit_id=item.unit_id,
                citation_label=item.citation_label,
                document_id=item.document_id,
                article_id=item.article_id,
                clause_id=item.clause_id,
                deep_link=item.deep_link,
            )
            for item in (evidence_by_id[citation_id] for citation_id in citation_order)
        )
        answer_text = "\n\n".join(
            f"{claim.text.strip()} "
            f"[{'; '.join(evidence_by_id[cid].citation_label for cid in claim.citation_ids)}]"
            for claim in candidate.claims
        )
        return AnswerResponse(
            retrieval_contract_version=retrieval_contract_version,
            query=projected.query,
            answer_text=answer_text,
            claims=tuple(candidate.claims),
            citations=citations,
            reasoning_paths=tuple(selected_paths),
            temporal_notes=temporal_notes,
            cannot_answer=False,
            insufficiency_reason=None,
            confidence=candidate.confidence,
            provider=provider,
            model=model,
            intent=projected.intent,
            strategy=projected.strategy,
        )

    @staticmethod
    def _validate_temporal(assertion, projected, evidence_by_id) -> str:
        if (
            projected.resolved_from is None
            or projected.resolved_to != projected.resolved_from
        ):
            raise TemporalAnswerValidationError(
                "Temporal assertion requires one resolved query date"
            )
        if assertion.query_date != projected.resolved_from:
            raise TemporalAnswerValidationError("Temporal assertion date mismatch")
        evidence = evidence_by_id.get(assertion.subject_unit_id)
        if evidence is None:
            raise TemporalAnswerValidationError(
                "Temporal assertion subject is not allowlisted"
            )
        computed_valid = (
            evidence.effective_from is not None
            and evidence.effective_from <= assertion.query_date
            and (
                evidence.effective_to is None
                or assertion.query_date < evidence.effective_to
            )
        )
        if assertion.asserted_valid != computed_valid:
            raise TemporalAnswerValidationError(
                "Temporal assertion conflicts with retrieved interval"
            )
        state = "có hiệu lực" if computed_valid else "không có hiệu lực"
        return (
            f"Theo phạm vi dữ liệu truy xuất, {evidence.citation_label} {state} "
            f"tại ngày {assertion.query_date.isoformat()}."
        )
