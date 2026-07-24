"""Step 3: JSON Schema Validation — wrapper qua Pydantic.

Lớp an toàn thứ 2 sau `response_schema` của Gemini (extraction/llm_extractor.py):
`response_schema` ép Gemini trả đúng shape tại API level, nhưng module này vẫn
re-validate vì pipeline cũng nhận input từ review queue / file JSON thủ công
(không đi qua Gemini), nơi `response_schema` không bảo vệ được.
"""

from __future__ import annotations

from pydantic import ValidationError

from src.pipeline.extraction.models import ExtractedEntity, ExtractedRelation


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


def score_relation_schema(raw: dict) -> float:
    """Tính điểm khớp schema cho relation bằng DeepDiff.
    Trả về điểm số float từ 0.0 đến 1.0.
    """
    if not isinstance(raw, dict):
        return 0.0

    from deepdiff import DeepDiff
    
    # 1. Định nghĩa template lý tưởng dựa trên ExtractedRelation
    ideal_template = {
        "head": str(raw.get("head", "")),
        "relation": str(raw.get("relation", "REFERS_TO")),
        "tail": str(raw.get("tail", "")),
        "evidence": str(raw.get("evidence", "")),
        "confidence": float(raw.get("confidence", 0.5)) if isinstance(raw.get("confidence"), (int, float)) else 0.5
    }
    
    # Chỉ giữ lại các trường có trong template để so khớp sâu
    cleaned_raw = {}
    for k in ideal_template:
        if k in raw:
            val = raw[k]
            if k == "confidence" and isinstance(val, (int, float)):
                cleaned_raw[k] = float(val)
            elif k != "confidence" and isinstance(val, str):
                cleaned_raw[k] = val
            else:
                cleaned_raw[k] = val
                
    diff = DeepDiff(ideal_template, cleaned_raw, ignore_order=True)
    
    penalty = 0.0
    
    # Lỗi 1: Thiếu trường bắt buộc (mỗi trường -0.3)
    if "dictionary_item_removed" in diff:
        penalty += len(diff["dictionary_item_removed"]) * 0.3
        
    # Lỗi 2: Sai kiểu dữ liệu (mỗi trường -0.2)
    if "type_changes" in diff:
        penalty += len(diff["type_changes"]) * 0.2
        
    # Lỗi 3: Thừa trường không mong muốn (mỗi trường -0.05)
    extra_keys = [k for k in raw.keys() if k not in ideal_template]
    penalty += len(extra_keys) * 0.05
    
    # Lỗi 4: Giá trị của relation không hợp lệ (không thuộc RelationType)
    valid_relations = {
        "CONTAINS", "AMENDS", "REPEALS", "REPLACES", 
        "GUIDES", "REFERS_TO", "DEFINES", "REGULATES", "REQUIRES"
    }
    if raw.get("relation") not in valid_relations:
        penalty += 0.2
        
    # Lỗi 5: Giá trị confidence ngoài khoảng 0.0 - 1.0
    conf = raw.get("confidence")
    if isinstance(conf, (int, float)) and (conf < 0.0 or conf > 1.0):
        penalty += 0.2

    return max(0.0, 1.0 - penalty)
