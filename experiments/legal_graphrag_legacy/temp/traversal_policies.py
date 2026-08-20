
INTENT_CLASSIFICATION_PROMPT = """
Phân loại intent của câu hỏi pháp lý sau:

Classes:
- factual: Hỏi về quy định, điều kiện cụ thể
- validity: Hỏi về tình trạng hiệu lực của văn bản/điều luật
- hierarchy: Hỏi về văn bản hướng dẫn/thực thi
- comparison: So sánh quy định giữa các thời điểm
- definition: Hỏi định nghĩa khái niệm pháp lý
- multi_hop: Câu hỏi cần nhiều bước suy luận, chạm từ 2 nhãn trên trở lên

Ví dụ:
Q: "Điều kiện thành lập công ty TNHH là gì?" → factual
Q: "NĐ 78/2015 còn hiệu lực không?" → validity
Q: "Nghị định nào hướng dẫn Luật DN 2020?" → hierarchy
Q: "Quy định vốn điều lệ năm 2019 khác bây giờ như thế nào?" → comparison
Q: "Vốn điều lệ là gì?" → definition
Q: "Thủ tục mà nghị định hướng dẫn điều X quy định ra sao?" → multi_hop
Q: "Điều kiện thành lập công ty TNHH theo quy định hiện hành (còn hiệu lực) là gì?" → multi_hop

Câu hỏi: "{query}"
Intent:
"""



TEMPORAL_EXTRACTION_PROMPT = """
Trích xuất thông tin thời gian từ câu hỏi pháp lý sau.
Câu hỏi: "{query}"
Ngày hiện tại: {today}

Lưu ý:
- Nếu câu hỏi nhắc mốc thời gian gắn với 1 văn bản cụ thể (vd "trước khi Nghị định X có hiệu lực"),
  KHÔNG tự suy ra ngày cụ thể — chỉ trích xuất tên văn bản vào "anchor_event".
- Nếu câu hỏi không đề cập thời gian, coi như hỏi luật hiện hành (has_temporal: false).

Trả về JSON:
{{
  "has_temporal": boolean,
  "temporal_type": "validity_check" | "event_context" | "comparison" | null,
  "expression": string | null,
  "resolved_from": "YYYY-MM-DD" | null,
  "resolved_to": "YYYY-MM-DD" | null,
  "granularity": "year" | "month" | "day" | "current" | "relative_to_event" | null,
  "anchor_event": string | null
}}
"""

TRAVERSAL_POLICIES = {
    "factual": {
        "relations": ["REGULATES", "DEFINES", "REQUIRES", "REFERS_TO"],
        "max_depth": 2,
        "follow_temporal": False,
    },
    "validity": {
        "relations": ["AMENDS", "REPLACES", "REPEALS"],
        "max_depth": 10,              # safety cap, không phải target depth
        "follow_temporal": True,
        "priority": "latest",
        "stop_condition": "no_outgoing_temporal_edge",
    },
    "hierarchy": {
        "relations": ["GUIDES"],      # FIX: bỏ CONTAINS ra khỏi đây
        "max_depth": 3,
        "direction": "both",
        "priority": "legal_rank",     # Luật > Nghị định > Thông tư khi có nhiều path
    },
    "comparison": {
        "relations": ["AMENDS", "REPLACES"],
        "max_depth": 10,              # safety cap
        "follow_temporal": True,
        "return_all_versions": True,
        "stop_condition": "no_outgoing_temporal_edge",
    },
    "definition": {
        "relations": ["DEFINES"],
        "max_depth": 1,
        "follow_temporal": False,
    },
}

# FIX: policy riêng cho containment, chạy song song mọi truy vấn để lấy context vị trí
# (Document chứa Article nào), không gắn cứng vào 1 intent.
STRUCTURAL_CONTEXT_POLICY = {
    "relations": ["CONTAINS"],
    "max_depth": 1,
    "direction": "up",
}

# FIX: luôn traverse các relation này bất kể intent gì, để không bỏ sót việc
# 1 Điều đã bị AMENDS/REPLACES/REPEALS khi trả lời các intent khác (vd factual, definition).
#
# CHIỀU DỮ LIỆU (giữ theo bản gốc): cũ -[AMENDS/REPLACES/REPEALS]-> mới
# => Để tìm "bản mới nhất áp dụng cho 1 node": traverse chiều OUT.
# => Để tìm "node này có bị thay bởi bản nào không (ngược lại)": traverse chiều IN.
MANDATORY_RELATIONS = ["AMENDS", "REPLACES", "REPEALS"]


def find_latest_version(traverse_fn, entry_node: str):
    """
    Đi chiều OUT theo MANDATORY_RELATIONS để tìm bản mới nhất áp dụng cho entry_node.
    traverse_fn(node, relations, direction, max_depth) -> list[(node_id, relation)]
    """
    chain = traverse_fn(entry_node, MANDATORY_RELATIONS, direction="out", max_depth=10)
    if not chain:
        return entry_node  # không có bản nào sửa nó -> chính nó là bản mới nhất
    return chain[-1][0]  # node cuối cùng trong chain = bản mới nhất

CONFIDENCE_THRESHOLD = 0.6


def resolve_policy(intents_with_scores: list[tuple[str, float]]) -> dict:
    """
    intents_with_scores: [("factual", 0.8), ("hierarchy", 0.65), ...]
    Trả về policy đã union, hoặc fallback "ALL" nếu không đủ confidence.
    Đây là chỗ thay thế cho "multi_hop": {"relations": ["ALL"]} ở bản gốc.
    """
    valid = [i for i, score in intents_with_scores if score >= CONFIDENCE_THRESHOLD]

    if not valid:
        return {
            "relations": "ALL",   # fallback thật sự cuối cùng, không phải default cho multi_hop
            "max_depth": 3,
            "follow_temporal": True,
            "mode": "fallback_low_confidence",
        }

    if len(valid) == 1:
        return {**TRAVERSAL_POLICIES[valid[0]], "mode": "single_intent"}

    # multi-intent (bao gồm cả trường hợp classifier trả "multi_hop" rồi được decompose
    # thành các intent con ở bước trước đó) -> union, chạy tuần tự từng intent rồi merge
    merged_relations = set()
    for i in valid:
        merged_relations |= set(TRAVERSAL_POLICIES[i]["relations"])

    return {
        "relations": list(merged_relations),
        "max_depth": max(TRAVERSAL_POLICIES[i]["max_depth"] for i in valid),
        "follow_temporal": any(TRAVERSAL_POLICIES[i].get("follow_temporal") for i in valid),
        "mode": "sequential_multi_intent",
        "sub_intents": valid,
    }
