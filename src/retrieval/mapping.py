"""Map repository records into validated retrieval DTOs."""

from datetime import date
from typing import Any, Mapping

from src.retrieval.citation import build_citation_label, build_deep_link
from src.retrieval.models import RetrievedUnit


class RetrievalRecordError(ValueError):
    """Raised when a repository row cannot satisfy the retrieval DTO contract."""


def map_retrieved_unit(
    record: Mapping[str, Any],
    *,
    score_field: str | None = None,
) -> RetrievedUnit:
    unit_id = _required_text(record, "id")
    document_id = _required_text(record, "document_id")
    label = _required_text(record, "label")
    if label not in {"Article", "Clause", "Point"}:
        raise RetrievalRecordError(f"Unsupported retrieved label: {label!r}")

    article_number = _optional_text(record.get("article_number"))
    clause_number = _optional_text(record.get("clause_number"))
    article_id = _required_text(record, "article_id")
    clause_id = _optional_text(record.get("clause_id"))
    if label == "Clause" and not clause_id:
        raise RetrievalRecordError("Clause retrieval row requires clause_id")
    document_number = _optional_text(record.get("document_number"))
    score = float(record.get("score", 0.0)) if score_field else None
    scores = {score_field: score} if score_field else {}

    return RetrievedUnit(
        id=unit_id,
        label=label,
        content_raw=str(record.get("content_raw") or ""),
        title=_optional_text(record.get("title")),
        document_id=document_id,
        document_number=document_number,
        document_title=_optional_text(record.get("document_title")),
        source_url=_optional_text(record.get("source_url")),
        article_id=article_id,
        clause_id=clause_id,
        article_number=article_number,
        clause_number=clause_number,
        version_family_id=_optional_text(record.get("version_family_id")),
        effective_from=_native_date(record.get("effective_from")),
        effective_to=_native_date(record.get("effective_to")),
        legal_status=_optional_text(record.get("legal_status")),
        citation_label=build_citation_label(
            label=label,
            document_number=document_number,
            article_number=article_number,
            clause_number=clause_number,
        ),
        deep_link=build_deep_link(document_id, unit_id),
        retrieval_sources=[_retrieval_source(score_field)] if score_field else [],
        **scores,
    )


def _required_text(record: Mapping[str, Any], field: str) -> str:
    value = _optional_text(record.get(field))
    if not value:
        raise RetrievalRecordError(f"Missing required repository field: {field}")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _native_date(value: object) -> date | None:
    if value is None:
        return None
    native = value.to_native() if hasattr(value, "to_native") else value
    if isinstance(native, date):
        return native
    raise RetrievalRecordError(
        f"Expected date-compatible value, got {type(value).__name__}"
    )


def _retrieval_source(score_field: str) -> str:
    return (
        "fulltext"
        if score_field == "bm25_score"
        else score_field.removesuffix("_score")
    )
