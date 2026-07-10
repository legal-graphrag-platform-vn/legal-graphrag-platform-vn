"""Step 3: JSON Schema Validation — wrapper qua Pydantic.

Lớp an toàn thứ 2 sau `response_schema` của Gemini (extraction/llm_extractor.py):
`response_schema` ép Gemini trả đúng shape tại API level, nhưng module này vẫn
re-validate vì pipeline cũng nhận input từ review queue / file JSON thủ công
(không đi qua Gemini), nơi `response_schema` không bảo vệ được.
"""

from __future__ import annotations

from pydantic import ValidationError

from src.extraction.models import ExtractedEntity, ExtractedRelation


def validate_entity(raw: dict) -> tuple[ExtractedEntity | None, str | None]:
    try:
        return ExtractedEntity.model_validate(raw), None
    except ValidationError as e:
        return None, str(e)


def validate_relation(raw: dict) -> tuple[ExtractedRelation | None, str | None]:
    try:
        return ExtractedRelation.model_validate(raw), None
    except ValidationError as e:
        return None, str(e)
