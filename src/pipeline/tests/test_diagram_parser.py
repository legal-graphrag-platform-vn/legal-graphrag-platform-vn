"""Tests cho diagram_parser — dùng fixture L59_2020 từ dữ liệu thực."""

from __future__ import annotations

import pytest

from src.pipeline.extraction.diagram_parser import (
    DOCUMENT_RELATION_MAP,
    UNSUPPORTED_CATEGORIES,
    DiagramParseResult,
    DiagramRelationCandidate,
    _strip_count,
    parse_diagram,
)

# Fixture L59_2020 (Luật Doanh nghiệp 2020) — subset đủ để kiểm tra direction
L59_2020_DIAGRAM: dict[str, list[str]] = {
    "Văn bản được sửa đổi bổ sung (9)": [
        "Luật Sửa đổi, bổ sung một số điều của 37 luật có liên quan đến quy hoạch số 35/2018/QH14",
        "Luật Tố cáo số 25/2018/QH14",
        "Bộ Luật lao động số 45/2019/QH14",
    ],
    "Văn bản được thay thế (1)": [
        "Luật Doanh nghiệp số 68/2014/QH13",
    ],
    "Văn bản bị bãi bỏ (0)": [],
    "Văn bản quy định chi tiết, hướng dẫn thi hành (1)": [
        "Nghị định số 23/2022/NĐ-CP Về thành lập, sắp xếp lại, chuyển đổi sở hữu",
    ],
    "Văn bản sửa đổi bổ sung (5)": [
        "Luật Sửa đổi, bổ sung một số điều của Luật Doanh nghiệp số 76/2025/QH15",
        "Luật sửa đổi, bổ sung một số điều của Luật Chứng khoán số 56/2024/QH15",
    ],
    "Văn bản thay thế (0)": [],
    "Văn bản bãi bỏ (0)": [],
    # Unsupported
    "Căn cứ ban hành (1)": ["Hiến pháp năm 2013"],
    "Văn bản áp dụng (431)": ["Nghị quyết số X"],
    "Văn bản được hướng dẫn áp dụng (0)": [],
    "Văn bản hướng dẫn áp dụng (0)": [],
}


# ---------------------------------------------------------------------------
# _strip_count
# ---------------------------------------------------------------------------

class TestStripCount:
    def test_strips_trailing_number(self):
        assert _strip_count("Văn bản thay thế (1)") == "Văn bản thay thế"

    def test_strips_zero(self):
        assert _strip_count("Văn bản bị bãi bỏ (0)") == "Văn bản bị bãi bỏ"

    def test_strips_large_number(self):
        assert _strip_count("Văn bản áp dụng (431)") == "Văn bản áp dụng"

    def test_no_suffix(self):
        assert _strip_count("Văn bản thay thế") == "Văn bản thay thế"

    def test_does_not_strip_mid_parens(self):
        # Parens không ở cuối không bị strip
        assert _strip_count("Văn bản (thí điểm) áp dụng") == "Văn bản (thí điểm) áp dụng"

    def test_strips_only_trailing_digit_parens(self):
        # Parens ở cuối nhưng chứa text không bị strip
        result = _strip_count("Văn bản (thí điểm)")
        assert result == "Văn bản (thí điểm)"


# ---------------------------------------------------------------------------
# Direction correctness — core test
# ---------------------------------------------------------------------------

class TestDirectionCorrectness:
    """Current document = Luật Doanh nghiệp 2020 (ldn_2020)."""

    def test_current_replaces_old_document(self):
        """'Văn bản được thay thế' → ldn_2020 REPLACES ldn_2014."""
        result = parse_diagram({"Văn bản được thay thế (1)": ["Luật DN 2014"]})
        assert len(result.candidates) == 1
        c = result.candidates[0]
        assert c.relation_type == "REPLACES"
        assert c.direction == "CURRENT_TO_TARGET"

    def test_new_documents_amend_current(self):
        """'Văn bản sửa đổi bổ sung' → target (2025) AMENDS current (2020)."""
        result = parse_diagram({"Văn bản sửa đổi bổ sung (5)": ["Luật 76/2025/QH15"]})
        assert len(result.candidates) == 1
        c = result.candidates[0]
        assert c.relation_type == "AMENDS"
        assert c.direction == "TARGET_TO_CURRENT"

    def test_current_amends_other_documents(self):
        """'Văn bản được sửa đổi bổ sung' → ldn_2020 AMENDS target (luật cũ)."""
        result = parse_diagram({"Văn bản được sửa đổi bổ sung (9)": ["Bộ luật Lao động 2019"]})
        assert len(result.candidates) == 1
        c = result.candidates[0]
        assert c.relation_type == "AMENDS"
        assert c.direction == "CURRENT_TO_TARGET"

    def test_implementing_document(self):
        """'Văn bản quy định chi tiết' → current GUIDES target (Nghị định)."""
        result = parse_diagram({
            "Văn bản quy định chi tiết, hướng dẫn thi hành (1)": [
                "Nghị định số 23/2022/NĐ-CP"
            ]
        })
        assert len(result.candidates) == 1
        c = result.candidates[0]
        assert c.relation_type == "GUIDES"
        assert c.direction == "CURRENT_TO_TARGET"

    def test_current_being_guided(self):
        """'Văn bản được quy định chi tiết' → target GUIDES current."""
        result = parse_diagram({
            "Văn bản được quy định chi tiết, hướng dẫn thi hành (1)": [
                "Luật cấp trên 2015"
            ]
        })
        assert len(result.candidates) == 1
        c = result.candidates[0]
        assert c.relation_type == "GUIDES"
        assert c.direction == "TARGET_TO_CURRENT"

    def test_current_repeals_target(self):
        result = parse_diagram({"Văn bản bị bãi bỏ (1)": ["Luật cũ"]})
        c = result.candidates[0]
        assert c.relation_type == "REPEALS"
        assert c.direction == "CURRENT_TO_TARGET"

    def test_target_repeals_current(self):
        result = parse_diagram({"Văn bản bãi bỏ (1)": ["Luật mới"]})
        c = result.candidates[0]
        assert c.relation_type == "REPEALS"
        assert c.direction == "TARGET_TO_CURRENT"


# ---------------------------------------------------------------------------
# Unsupported / Unknown category handling
# ---------------------------------------------------------------------------

class TestCategoryClassification:
    def test_empty_items_skipped(self):
        result = parse_diagram({"Văn bản bị bãi bỏ (0)": []})
        assert len(result.candidates) == 0
        assert len(result.unsupported_categories) == 0
        assert len(result.unknown_categories) == 0

    def test_can_ban_hanh_is_unsupported(self):
        result = parse_diagram({"Căn cứ ban hành (1)": ["Hiến pháp 2013"]})
        assert len(result.candidates) == 0
        assert "Căn cứ ban hành" in result.unsupported_categories

    def test_van_ban_ap_dung_is_unsupported(self):
        result = parse_diagram({"Văn bản áp dụng (431)": ["Nghị quyết X"]})
        assert "Văn bản áp dụng" in result.unsupported_categories

    def test_huong_dan_ap_dung_is_unsupported_pending_fixture(self):
        """Category này defer đến khi có fixture data thật."""
        result = parse_diagram({"Văn bản hướng dẫn áp dụng (1)": ["Thông tư X"]})
        assert "Văn bản hướng dẫn áp dụng" in result.unsupported_categories
        assert len(result.candidates) == 0

    def test_unknown_category_captured(self):
        result = parse_diagram({"Văn bản chấm dứt hiệu lực (1)": ["Luật X"]})
        assert "Văn bản chấm dứt hiệu lực" in result.unknown_categories
        assert len(result.candidates) == 0

    def test_unsupported_not_in_unknown(self):
        result = parse_diagram({"Căn cứ ban hành (1)": ["Hiến pháp 2013"]})
        assert len(result.unknown_categories) == 0

    def test_unknown_not_in_unsupported(self):
        result = parse_diagram({"Văn bản chấm dứt hiệu lực (1)": ["Luật X"]})
        assert len(result.unsupported_categories) == 0

    def test_unknown_categories_deduped(self):
        result = parse_diagram({
            "Văn bản X (1)": ["A"],
            "Văn bản X (2)": ["B"],  # same category after strip
        })
        assert result.unknown_categories.count("Văn bản X") == 1


# ---------------------------------------------------------------------------
# Full L59_2020 fixture integration
# ---------------------------------------------------------------------------

class TestL592020Fixture:
    def setup_method(self):
        self.result = parse_diagram(L59_2020_DIAGRAM)

    def test_candidate_count(self):
        # 3 (được sửa đổi) + 1 (được thay thế) + 1 (quy định chi tiết) + 2 (sửa đổi) = 7
        assert len(self.result.candidates) == 7

    def test_no_candidates_from_empty_categories(self):
        empty_cats = {"Văn bản bị bãi bỏ", "Văn bản thay thế", "Văn bản bãi bỏ"}
        candidate_cats = {c.source_category for c in self.result.candidates}
        assert not empty_cats.intersection(candidate_cats)

    def test_replaces_direction(self):
        replaces = [c for c in self.result.candidates if c.relation_type == "REPLACES"]
        assert len(replaces) == 1
        assert replaces[0].direction == "CURRENT_TO_TARGET"
        assert "68/2014" in replaces[0].raw_target

    def test_amends_directions(self):
        amends = [c for c in self.result.candidates if c.relation_type == "AMENDS"]
        current_to = [c for c in amends if c.direction == "CURRENT_TO_TARGET"]
        target_to = [c for c in amends if c.direction == "TARGET_TO_CURRENT"]
        assert len(current_to) == 3  # Văn bản được sửa đổi bổ sung
        assert len(target_to) == 2   # Văn bản sửa đổi bổ sung

    def test_guides_direction(self):
        guides = [c for c in self.result.candidates if c.relation_type == "GUIDES"]
        assert len(guides) == 1
        assert guides[0].direction == "CURRENT_TO_TARGET"
        assert "23/2022" in guides[0].raw_target

    def test_unsupported_captured(self):
        assert "Căn cứ ban hành" in self.result.unsupported_categories
        assert "Văn bản áp dụng" in self.result.unsupported_categories
        # Lưu ý: "Văn bản hướng dẫn áp dụng (0)" có danh sách rỗng
        # → bị skip trước khi check category, không xuất hiện trong unsupported_categories.
        # Hành vi này là đúng — test riêng trong TestCategoryClassification.

    def test_no_unknown_categories(self):
        assert len(self.result.unknown_categories) == 0
