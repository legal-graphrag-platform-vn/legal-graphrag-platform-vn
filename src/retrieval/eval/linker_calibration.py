"""Deterministic threshold calibration from pinned endpoint rankings."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Mapping


@dataclass(frozen=True)
class RoleCalibration:
    role: str
    min_score: float
    min_margin: float
    case_count: int
    resolved_count: int
    correct_count: int
    false_resolution_count: int

    @property
    def accuracy(self) -> float:
        return self.correct_count / self.case_count if self.case_count else 0.0

    @property
    def resolved_precision(self) -> float:
        return self.correct_count / self.resolved_count if self.resolved_count else 0.0


def calibrate_role(
    cases: Iterable[Mapping[str, object]],
    *,
    role: str,
) -> RoleCalibration:
    role_cases = tuple(case for case in cases if case["role"] == role)
    candidates: list[RoleCalibration] = []
    for score_step in range(1, 101):
        min_score = float(Decimal(score_step) / Decimal(1000))
        for margin_step in range(1, 21):
            min_margin = float(Decimal(margin_step) / Decimal(1000))
            candidates.append(
                _evaluate(
                    role_cases,
                    role=role,
                    min_score=min_score,
                    min_margin=min_margin,
                )
            )
    safe = [item for item in candidates if item.false_resolution_count == 0]
    if not safe:
        raise ValueError(f"No fail-closed calibration exists for role {role}")
    return min(
        safe,
        key=lambda item: (
            -item.correct_count,
            item.min_score,
            item.min_margin,
        ),
    )


def _evaluate(
    cases: tuple[Mapping[str, object], ...],
    *,
    role: str,
    min_score: float,
    min_margin: float,
) -> RoleCalibration:
    resolved = 0
    correct = 0
    false_resolutions = 0
    for case in cases:
        ranked = case["candidates"]
        if not isinstance(ranked, list) or not ranked:
            continue
        top = ranked[0]
        if not isinstance(top, dict):
            raise ValueError("Calibration candidate must be an object")
        top_score = float(top["score"])
        second_score = (
            float(ranked[1]["score"])
            if len(ranked) > 1 and isinstance(ranked[1], dict)
            else 0.0
        )
        if top_score < min_score or top_score - second_score < min_margin:
            continue
        resolved += 1
        if top["node_id"] == case["gold_node_id"]:
            correct += 1
        else:
            false_resolutions += 1
    return RoleCalibration(
        role=role,
        min_score=min_score,
        min_margin=min_margin,
        case_count=len(cases),
        resolved_count=resolved,
        correct_count=correct,
        false_resolution_count=false_resolutions,
    )
