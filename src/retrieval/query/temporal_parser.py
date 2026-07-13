"""Deterministic Vietnamese temporal parsing with an optional structural fallback."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from src.retrieval.models import TemporalQuery
from src.retrieval.ports import TextGenerationPort


logger = logging.getLogger(__name__)

_CURRENT_VALIDITY = re.compile(
    r"(hiện hành|hiện nay|đang có hiệu lực|còn hiệu lực(?:\s+không)?)",
    re.IGNORECASE,
)
_EXPLICIT_TEMPORAL_WORDS = re.compile(
    r"(?:\b(?:ngày|năm|thời điểm|hiệu lực|áp dụng)\b|"
    r"\b(?:trước|sau)\s+(?:ngày|tháng|năm|thời điểm|\d))",
    re.IGNORECASE,
)


class TemporalParser:
    def __init__(self, llm_client: TextGenerationPort | None = None) -> None:
        self._llm_client = llm_client
        self._year_pattern = re.compile(r"(?:năm|trong năm)\s*(\d{4})", re.IGNORECASE)
        self._date_pattern = re.compile(
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
            if parsed is None:
                return TemporalQuery(
                    has_temporal=True,
                    expression=explicit_match.group(0),
                    parse_error="Invalid explicit calendar date",
                    requests_current_validity=bool(current_match),
                )
            return TemporalQuery(
                has_temporal=True,
                expression=explicit_match.group(0),
                resolved_from=parsed,
                resolved_to=parsed,
                granularity="day",
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

        if _EXPLICIT_TEMPORAL_WORDS.search(query):
            if self._llm_client is None:
                return TemporalQuery(
                    has_temporal=True,
                    expression=query,
                    parse_error="Explicit temporal expression could not be resolved",
                )
            return self._parse_with_fallback(query)

        return TemporalQuery(has_temporal=False)

    def _parse_day(self, match: re.Match[str]) -> date | None:
        groups = match.groups()
        try:
            if "-" in match.group(0):
                year, month, day = groups
            else:
                day, month, year = groups
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
            return TemporalQuery(
                has_temporal=True,
                expression=query,
                parse_error="Temporal provider returned an invalid response",
            )

        resolved_from = _parse_iso_date(data.get("resolved_from"))
        resolved_to = _parse_iso_date(data.get("resolved_to"))
        if data.get("has_temporal") and resolved_from is None:
            return TemporalQuery(
                has_temporal=True,
                expression=str(data.get("expression") or query),
                parse_error="Temporal provider did not resolve a temporal point",
            )
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
