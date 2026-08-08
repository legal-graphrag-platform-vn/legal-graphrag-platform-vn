"""Diagram-based document relation parser.

Nhận raw diagram JSON từ trang web nguồn (vbpl.vn) — danh mục các văn bản
liên quan đến một văn bản pháp luật — và trả về DiagramParseResult.

Trách nhiệm của module này:
  - Parse từng category trong diagram JSON.
  - Tra bảng DOCUMENT_RELATION_MAP để xác định relation_type và direction.
  - Trả DiagramParseResult phân biệt rõ: candidates / unsupported / unknown.
  - raw_target chỉ trim whitespace, chưa normalize hay resolve canonical ID.

Trách nhiệm KHÔNG thuộc module này:
  - Resolve raw_target thành canonical Document ID (→ document_relation_resolver).
  - Ghi accepted.jsonl hay bất kỳ artifact nào.
  - Gọi LLM hay bất kỳ external service nào.

## Quy tắc direction

  "Văn bản được/bị X (n)" → current document thực hiện hành động lên target
                           → direction = CURRENT_TO_TARGET

  "Văn bản X (n)"         → target thực hiện hành động lên current document
                           → direction = TARGET_TO_CURRENT

Map sử dụng explicit lookup, không heuristic chuỗi ("được"/"bị" in label).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


RelationType = Literal[
    "AMENDS",
    "REPLACES",
    "REPEALS",
    "GUIDES",
]

Direction = Literal[
    "CURRENT_TO_TARGET",
    "TARGET_TO_CURRENT",
]


@dataclass(frozen=True)
class DocumentRelationMapping:
    """Ánh xạ từ category label sang relation_type và direction."""

    relation_type: RelationType
    direction: Direction


# Explicit map. Không dùng heuristic "được"/"bị" in string.
# Các category GUIDES "hướng dẫn áp dụng" chưa có fixture data thật
# → tạm chưa map, nằm trong UNSUPPORTED cho đến khi xác nhận direction.
DOCUMENT_RELATION_MAP: dict[str, DocumentRelationMapping] = {
    # Current document sửa đổi target
    "Văn bản được sửa đổi bổ sung": DocumentRelationMapping(
        relation_type="AMENDS",
        direction="CURRENT_TO_TARGET",
    ),
    # Target (văn bản mới hơn) sửa đổi current document
    "Văn bản sửa đổi bổ sung": DocumentRelationMapping(
        relation_type="AMENDS",
        direction="TARGET_TO_CURRENT",
    ),
    # Current document thay thế target (văn bản cũ)
    "Văn bản được thay thế": DocumentRelationMapping(
        relation_type="REPLACES",
        direction="CURRENT_TO_TARGET",
    ),
    # Target (văn bản mới hơn) thay thế current document
    "Văn bản thay thế": DocumentRelationMapping(
        relation_type="REPLACES",
        direction="TARGET_TO_CURRENT",
    ),
    # Current document bãi bỏ target
    "Văn bản bị bãi bỏ": DocumentRelationMapping(
        relation_type="REPEALS",
        direction="CURRENT_TO_TARGET",
    ),
    # Target bãi bỏ current document
    "Văn bản bãi bỏ": DocumentRelationMapping(
        relation_type="REPEALS",
        direction="TARGET_TO_CURRENT",
    ),
    # Current document (cấp cao hơn) hướng dẫn target (cấp thấp hơn)
    "Văn bản quy định chi tiết, hướng dẫn thi hành": DocumentRelationMapping(
        relation_type="GUIDES",
        direction="CURRENT_TO_TARGET",
    ),
    # Target hướng dẫn current document
    "Văn bản được quy định chi tiết, hướng dẫn thi hành": DocumentRelationMapping(
        relation_type="GUIDES",
        direction="TARGET_TO_CURRENT",
    ),
}

# Category biết rõ nhưng Phase 1 ontology cố ý chưa hỗ trợ.
# Phân biệt với UNKNOWN (parser chưa gặp).
UNSUPPORTED_CATEGORIES: frozenset[str] = frozenset({
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
    # Direction chưa xác nhận bằng fixture thật — defer
    "Văn bản hướng dẫn áp dụng",
    "Văn bản được hướng dẫn áp dụng",
})

_COUNT_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")


@dataclass(frozen=True)
class DiagramRelationCandidate:
    """Một quan hệ thô được parse từ diagram, chưa resolve canonical ID.

    Attributes:
        source_category: Category đã strip count (ví dụ "Văn bản được thay thế").
        relation_type: Loại relation theo ontology contract.
        direction: CURRENT_TO_TARGET hoặc TARGET_TO_CURRENT.
        raw_target: Tên văn bản trim whitespace, chưa normalize hay resolve.
    """

    source_category: str
    relation_type: RelationType
    direction: Direction
    raw_target: str


@dataclass(frozen=True)
class DiagramParseResult:
    """Kết quả parse diagram, phân loại rõ 3 nhóm category.

    Attributes:
        candidates: Các quan hệ được parse thành công từ supported categories.
        unsupported_categories: Category biết rõ nhưng Phase 1 chưa hỗ trợ.
        unknown_categories: Category chưa từng thấy — cần điều tra.
    """

    candidates: tuple[DiagramRelationCandidate, ...]
    unsupported_categories: tuple[str, ...]
    unknown_categories: tuple[str, ...]


def parse_diagram(diagram: dict[str, list[str]]) -> DiagramParseResult:
    """Parse diagram JSON thành DiagramParseResult.

    Args:
        diagram: Dict với key là category label (có hoặc không có count trong ngoặc)
                 và value là list tên văn bản. Count trong ngoặc "(n)" được strip.

    Returns:
        DiagramParseResult phân biệt: candidates / unsupported / unknown.
        Category không có item (danh sách rỗng) được bỏ qua hoàn toàn.
    """
    candidates: list[DiagramRelationCandidate] = []
    unsupported: list[str] = []
    unknown: list[str] = []

    for raw_category, targets in diagram.items():
        if not targets:
            continue

        category = _strip_count(raw_category)

        if category in UNSUPPORTED_CATEGORIES:
            unsupported.append(category)
            continue

        mapping = DOCUMENT_RELATION_MAP.get(category)
        if mapping is None:
            unknown.append(category)
            continue

        for raw_target in targets:
            stripped = raw_target.strip()
            if not stripped:
                continue
            candidates.append(
                DiagramRelationCandidate(
                    source_category=category,
                    relation_type=mapping.relation_type,
                    direction=mapping.direction,
                    raw_target=stripped,
                )
            )

    return DiagramParseResult(
        candidates=tuple(candidates),
        unsupported_categories=tuple(dict.fromkeys(unsupported)),  # dedupe, preserve order
        unknown_categories=tuple(dict.fromkeys(unknown)),
    )


def _strip_count(category_label: str) -> str:
    """Strip trailing count suffix: 'Văn bản thay thế (1)' → 'Văn bản thay thế'."""
    return _COUNT_SUFFIX.sub("", category_label).strip()
