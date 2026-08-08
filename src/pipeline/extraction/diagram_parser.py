"""Diagram-based document relation parser.

Nhận raw diagram JSON từ trang web nguồn (vbpl.vn) — danh mục các văn bản
liên quan đến một văn bản pháp luật — và trả về DiagramRelationCandidate.

Trách nhiệm của module này:
  - Parse từng category trong diagram JSON.
  - Tra bảng DOCUMENT_RELATION_MAP để xác định relation_type và direction.
  - Trả DiagramRelationCandidate với raw_target còn nguyên, chưa resolve.

Trách nhiệm KHÔNG thuộc module này:
  - Resolve raw_target thành canonical Document ID (→ document_relation_resolver).
  - Ghi accepted.jsonl hay bất kỳ artifact nào.
  - Gọi LLM hay bất kỳ external service nào.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


# Explicit direction map — không dùng heuristic chuỗi ("được" in category).
# CURRENT_TO_TARGET: current document là head, target là tail.
# TARGET_TO_CURRENT: target document là head, current document là tail.
DOCUMENT_RELATION_MAP: dict[
    str,
    dict[str, str],
] = {
    # AMENDS: văn bản mới → sửa đổi → văn bản cũ
    "Văn bản sửa đổi bổ sung": {
        "relation": "AMENDS",
        "direction": "CURRENT_TO_TARGET",
    },
    # AMENDS inverse: văn bản cũ đã bị văn bản mới sửa
    "Văn bản được sửa đổi bổ sung": {
        "relation": "AMENDS",
        "direction": "TARGET_TO_CURRENT",
    },
    # REPLACES: văn bản mới → thay thế → văn bản cũ
    "Văn bản thay thế": {
        "relation": "REPLACES",
        "direction": "CURRENT_TO_TARGET",
    },
    # REPLACES inverse: văn bản cũ đã bị thay thế
    "Văn bản được thay thế": {
        "relation": "REPLACES",
        "direction": "TARGET_TO_CURRENT",
    },
    # REPEALS: văn bản mới → bãi bỏ → văn bản cũ
    "Văn bản bãi bỏ": {
        "relation": "REPEALS",
        "direction": "CURRENT_TO_TARGET",
    },
    # REPEALS inverse: văn bản cũ đã bị bãi bỏ
    "Văn bản bị bãi bỏ": {
        "relation": "REPEALS",
        "direction": "TARGET_TO_CURRENT",
    },
    # GUIDES: văn bản cấp cao → hướng dẫn → văn bản cấp thấp
    "Văn bản hướng dẫn áp dụng": {
        "relation": "GUIDES",
        "direction": "CURRENT_TO_TARGET",
    },
    # GUIDES inverse: văn bản cấp thấp đã được hướng dẫn bởi văn bản cấp cao
    "Văn bản được hướng dẫn áp dụng": {
        "relation": "GUIDES",
        "direction": "TARGET_TO_CURRENT",
    },
    "Văn bản quy định chi tiết, hướng dẫn thi hành": {
        "relation": "GUIDES",
        "direction": "CURRENT_TO_TARGET",
    },
    "Văn bản được quy định chi tiết, hướng dẫn thi hành": {
        "relation": "GUIDES",
        "direction": "TARGET_TO_CURRENT",
    },
    # Căn cứ ban hành: target là văn bản nền tảng mà current dựa vào.
    # Không có relation tương đương trong Phase 1 ontology — bỏ qua.
    # "Căn cứ ban hành": None
}

# Các category không có trong Phase 1 ontology — log để theo dõi, không extract.
UNSUPPORTED_CATEGORIES: set[str] = {
    "Căn cứ ban hành",
    "Văn bản được hợp nhất",
    "Văn bản hợp nhất",
    "Văn bản được đính chính",
    "Văn bản đính chính",
    "Văn bản được giải thích",
    "Văn bản được công bố",
    "Văn bản bị đình chỉ thi hành",
    "Văn bản bị tạm ngưng hiệu lực",
    "Văn bản dẫn chiếu",
    "Văn bản được dẫn chiếu",
    "Văn bản áp dụng",
}


@dataclass(frozen=True)
class DiagramRelationCandidate:
    """Một quan hệ thô được parse từ diagram, chưa resolve canonical ID.

    Attributes:
        source_category: Category gốc từ diagram (ví dụ "Văn bản được thay thế").
        relation_type: Loại relation theo ontology contract (REPLACES, AMENDS...).
        direction: CURRENT_TO_TARGET hoặc TARGET_TO_CURRENT.
        raw_target: Tên văn bản nguyên bản từ diagram, chưa map sang canonical ID.
    """

    source_category: str
    relation_type: str
    direction: Literal["CURRENT_TO_TARGET", "TARGET_TO_CURRENT"]
    raw_target: str


def parse_diagram(
    diagram: dict[str, list[str]],
) -> list[DiagramRelationCandidate]:
    """Parse diagram JSON thành danh sách DiagramRelationCandidate.

    Args:
        diagram: Dict với key là category label (ví dụ "Văn bản thay thế (1)")
                 và value là list tên văn bản. Số lượng trong ngoặc được bỏ qua.

    Returns:
        Danh sách candidates chỉ cho các category được hỗ trợ trong Phase 1.
        Các category không có trong DOCUMENT_RELATION_MAP bị bỏ qua hoàn toàn.
    """
    candidates: list[DiagramRelationCandidate] = []

    for raw_category, targets in diagram.items():
        if not targets:
            continue

        # Strip số lượng trong ngoặc: "Văn bản thay thế (1)" → "Văn bản thay thế"
        category = _strip_count(raw_category)

        if category in UNSUPPORTED_CATEGORIES:
            continue

        mapping = DOCUMENT_RELATION_MAP.get(category)
        if mapping is None:
            # Category không nhận ra — bỏ qua, caller có thể log nếu cần.
            continue

        for raw_target in targets:
            raw_target = raw_target.strip()
            if not raw_target:
                continue
            candidates.append(
                DiagramRelationCandidate(
                    source_category=category,
                    relation_type=mapping["relation"],
                    direction=mapping["direction"],  # type: ignore[arg-type]
                    raw_target=raw_target,
                )
            )

    return candidates


def _strip_count(category_label: str) -> str:
    """'Văn bản thay thế (1)' → 'Văn bản thay thế'."""
    bracket = category_label.rfind("(")
    if bracket > 0:
        return category_label[:bracket].strip()
    return category_label.strip()
