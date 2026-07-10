"""Confidence Scorer — Step 5, theo ADR-06 (plans/00_architecture_decisions.md).

Rule-based weighted multi-criteria, KHÔNG self-consistency (N=3 LLM runs) — lý do
đã chốt trong ADR-06: explainable + không tốn thêm API cost.

LƯU Ý 1 mâu thuẫn nhỏ trong spec gốc: tiêu chí "Evidence in text" ghi chú
"(LLM: Does this evidence sentence support this relation?)" — nhưng rationale #2
của chính ADR-06 lại khẳng định "Không tốn thêm API calls: Toàn bộ criteria đều
compute-local". Module này ưu tiên rationale #2 (compute-local) và tính evidence
bằng so khớp chuỗi/token-overlap với văn bản gốc thay vì gọi thêm LLM — xem
REPORT.md mục B.

Weights (đã chốt, không tự ý đổi): schema_valid=0.3, ontology_valid=0.3,
evidence_present=0.2, entities_resolvable=0.1, direction_correct=0.1.
"""

from __future__ import annotations

from dataclasses import dataclass

WEIGHTS: dict[str, float] = {
    "schema_valid": 0.3,
    "ontology_valid": 0.3,
    "evidence_present": 0.2,
    "entities_resolvable": 0.1,
    "direction_correct": 0.1,
}


@dataclass
class ConfidenceBreakdown:
    schema_valid: float
    ontology_valid: float
    evidence_present: float
    entities_resolvable: float
    direction_correct: float

    @property
    def total(self) -> float:
        return (
            self.schema_valid * WEIGHTS["schema_valid"]
            + self.ontology_valid * WEIGHTS["ontology_valid"]
            + self.evidence_present * WEIGHTS["evidence_present"]
            + self.entities_resolvable * WEIGHTS["entities_resolvable"]
            + self.direction_correct * WEIGHTS["direction_correct"]
        )


def score_evidence_presence(evidence: str, article_text: str) -> float:
    """Đo evidence có thực sự xuất hiện trong văn bản gốc không (compute-local,
    không gọi LLM — xem ghi chú đầu file). Exact substring -> 1.0; nếu không khớp
    nguyên văn (LLM có thể rút gọn/diễn đạt lại nhẹ), fallback token-overlap ratio.
    """
    if not evidence or not article_text:
        return 0.0
    evidence_norm = evidence.strip()
    if evidence_norm and evidence_norm in article_text:
        return 1.0
    evidence_tokens = set(evidence_norm.split())
    if not evidence_tokens:
        return 0.0
    article_tokens = set(article_text.split())
    return len(evidence_tokens & article_tokens) / len(evidence_tokens)


def score_entities_resolvable(entity_ids: list[str], known_entity_ids: set[str]) -> float:
    """Fraction các id (head/tail) thực sự tồn tại trong document/graph hiện tại."""
    if not entity_ids:
        return 0.0
    resolved = sum(1 for eid in entity_ids if eid in known_entity_ids)
    return resolved / len(entity_ids)


def score(
    *,
    schema_valid: bool,
    ontology_valid: bool,
    evidence: str,
    article_text: str,
    head_id: str,
    tail_id: str,
    known_entity_ids: set[str],
) -> ConfidenceBreakdown:
    """Tính confidence score đầy đủ cho 1 relation đã qua Step 3 + Step 4.

    `direction_correct` dùng lại kết quả `ontology_valid`: valid_pairs trong
    `validation/ontology_validator.py` đã mã hoá đúng thứ tự head->tail kỳ vọng
    cho từng relation type, nên ontology hợp lệ tức là chiều quan hệ đúng.
    """
    return ConfidenceBreakdown(
        schema_valid=1.0 if schema_valid else 0.0,
        ontology_valid=1.0 if ontology_valid else 0.0,
        evidence_present=score_evidence_presence(evidence, article_text),
        entities_resolvable=score_entities_resolvable([head_id, tail_id], known_entity_ids),
        direction_correct=1.0 if ontology_valid else 0.0,
    )
