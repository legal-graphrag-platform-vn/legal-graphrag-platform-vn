"""Deterministic Vietnamese temporal parsing with an optional structural fallback."""

from __future__ import annotations

import json
import logging
import calendar
import re
from datetime import date, datetime

from src.retrieval.models import TemporalQuery
from src.retrieval.ports import TextGenerationPort


logger = logging.getLogger(__name__)

_CURRENT_VALIDITY = re.compile(
    r"(hiện hành|hiện nay|đang có hiệu lực|còn hiệu lực(?:\s+không)?)",
    re.IGNORECASE,
)
_EXPLICIT_DURATION_EXPRESSIONS = re.compile(
    r"(?:bao nhiêu|mấy|số)\s+(?:ngày|tháng|năm)|"
    r"(?:hơn|trên|khoảng|sau|trong|quá)\s+\d+\s+(?:ngày|tháng|năm)|"
    r"(?:hàng|hằng|mỗi|mọi|vài|các)\s+(?:ngày|tháng|năm)|"
    r"\d+\s+(?:ngày|tháng)\b|"
    r"(?<!năm\s)\b\d{1,3}\s+năm\b|"
    r"ngày\s+(?:làm việc|nghỉ|lễ|tết)|"
    r"sau\s+thuế|"
    r"thời hạn\s+(?:bao nhiêu|mấy|\d+)",
    re.IGNORECASE,
)
_EXPLICIT_TEMPORAL_WORDS = re.compile(
    r"(?:\bngày\s+\d{1,2}\b|\bnăm\s+\d{4}\b|\bthời điểm\s+\d|\bhiệu lực\b|\báp dụng\b|"
    r"\b(?:trước|sau)\s+(?:ngày|tháng|năm|thời điểm|\d))",
    re.IGNORECASE,
)


class TemporalParser:
    def __init__(self, llm_client: TextGenerationPort | None = None) -> None:
        self._llm_client = llm_client
        self._year_pattern = re.compile(r"(?:năm|trong năm)\s*(\d{4})", re.IGNORECASE)
        self._month_year_pattern = re.compile(
            r"tháng\s*(\d{1,2})\s*(?:năm|\/)\s*(\d{4})",
            re.IGNORECASE,
        )
        self._date_pattern = re.compile(
            r"(?:ngày\s*)?(\d{1,2})[\/\-](\d{1,2})[\/\-](\d{4})|"
            r"ngày\s*(\d{1,2})\s*tháng\s*(\d{1,2})\s*năm\s*(\d{4})",
            re.IGNORECASE,
        )
        self._iso_pattern = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")

    def parse(self, query: str) -> TemporalQuery:
        current_match = _CURRENT_VALIDITY.search(query)
        explicit_match = self._date_pattern.search(query) or self._iso_pattern.search(
            query
        )
        if explicit_match:
            parsed = self._parse_day(explicit_match)
            if parsed is not None:
                return TemporalQuery(
                    has_temporal=True,
                    expression=explicit_match.group(0),
                    resolved_from=parsed,
                    resolved_to=parsed,
                    granularity="day",
                    requests_current_validity=bool(current_match),
                )

        month_match = self._month_year_pattern.search(query)
        if month_match:
            month, year = int(month_match.group(1)), int(month_match.group(2))
            if 1 <= month <= 12:
                last_day = calendar.monthrange(year, month)[1]
                return TemporalQuery(
                    has_temporal=True,
                    expression=month_match.group(0),
                    resolved_from=date(year, month, 1),
                    resolved_to=date(year, month, last_day),
                    granularity="month",
                    requests_current_validity=bool(current_match),
                )

        year_match = self._year_pattern.search(query)
        if year_match:
            year = int(year_match.group(1))
            return TemporalQuery(
                has_temporal=True,
                expression=year_match.group(0),
                resolved_from=date(year, 1, 1),
                resolved_to=date(year, 12, 31),
                granularity="year",
                requests_current_validity=bool(current_match),
            )

        if current_match:
            return TemporalQuery(
                has_temporal=True,
                expression=current_match.group(0),
                requests_current_validity=True,
            )

        if _EXPLICIT_DURATION_EXPRESSIONS.search(query):
            return TemporalQuery(has_temporal=False)

        if _EXPLICIT_TEMPORAL_WORDS.search(query):
            if self._llm_client is None:
                # Option 1 Graceful Fallback: Proceed with standard non-temporal retrieval
                return TemporalQuery(has_temporal=False)
            return self._parse_with_fallback(query)

        return TemporalQuery(has_temporal=False)

    def _parse_day(self, match: re.Match[str]) -> date | None:
        groups = [g for g in match.groups() if g is not None]
        try:
            if "-" in match.group(0) and len(groups) == 3 and len(groups[0]) == 4:
                year, month, day = groups
            else:
                day, month, year = groups[:3]
            return date(int(year), int(month), int(day))
        except ValueError:
            return None

    def _parse_with_fallback(self, query: str) -> TemporalQuery:
        system_prompt = (
            "Extract a Vietnamese legal temporal condition. Return JSON with "
            "has_temporal, expression, resolved_from, resolved_to and granularity."
        )
        try:
            response = self._llm_client.generate_text(
                system_prompt=system_prompt,
                user_prompt=query,
                temperature=0.0,
                response_format="json_object",
            )
            data = json.loads(response)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning(
                "Invalid temporal parser response",
                extra={"error_type": type(exc).__name__},
            )
            return TemporalQuery(has_temporal=False)

        resolved_from = _parse_iso_date(data.get("resolved_from"))
        resolved_to = _parse_iso_date(data.get("resolved_to"))
        if data.get("has_temporal") and resolved_from is None:
            return TemporalQuery(has_temporal=False)

        return TemporalQuery(
            has_temporal=bool(data.get("has_temporal")),
            expression=data.get("expression"),
            resolved_from=resolved_from,
            resolved_to=resolved_to,
            granularity=data.get("granularity"),
        )


def _parse_iso_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None
