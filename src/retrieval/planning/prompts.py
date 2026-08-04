"""Allowlisted prompt contract for exact-linear query planning."""

from __future__ import annotations

import json
from dataclasses import dataclass

from src.retrieval.planning.patterns import (
    QUERY_ANCHOR_LABELS,
    QUERY_PLANNABLE_RELATIONS,
    QUERY_TARGET_LABELS,
    QUERY_TRAVERSAL_LABELS,
)


@dataclass(frozen=True)
class QueryPlannerRequest:
    system_instruction: str
    prompt: str


def build_query_planner_request(query: str) -> QueryPlannerRequest:
    normalized = " ".join(query.split())
    if not normalized:
        raise ValueError("Query must not be blank")
    allowlist = {
        "anchor_labels": sorted(QUERY_ANCHOR_LABELS),
        "target_labels": sorted(QUERY_TARGET_LABELS),
        "traversal_labels": sorted(QUERY_TRAVERSAL_LABELS),
        "relations": sorted(QUERY_PLANNABLE_RELATIONS),
        "directions": ["incoming", "outgoing"],
        "depth": {"minimum": 2, "maximum": 3},
    }
    return QueryPlannerRequest(
        system_instruction=(
            "Bạn lập query plan graph tuyến tính từ câu hỏi pháp luật Việt Nam. "
            "Chỉ trả structured JSON theo schema. Không sinh node_id, canonical ID, "
            "Cypher, query database hoặc trường ngoài schema. Target chỉ chứa mention "
            "text; target label được suy ra từ next_label của bước cuối. Target text "
            "phải là cụm tìm kiếm tự đủ nghĩa và giữ các chi tiết phân biệt có trong câu hỏi: "
            "chủ thể, hành vi, điều kiện và số liệu. "
            "Khi câu hỏi có đề cập đến Điều/Khoản liên quan, target text phải bao gồm "
            "tên hoặc số của Điều đó (ví dụ: 'Khoản 2 Điều 41', 'khoản quy định trình tự chào bán phần vốn góp tại Điều 52'). "
            "Tuyệt đối không dùng target chung chung như 'khoản', 'điều', 'quy định' đứng một mình."
        ),
        prompt=(
            "ALLOWLIST="
            + json.dumps(allowlist, ensure_ascii=False, sort_keys=True)
            + "\nQUESTION="
            + json.dumps(normalized, ensure_ascii=False)
        ),
    )
