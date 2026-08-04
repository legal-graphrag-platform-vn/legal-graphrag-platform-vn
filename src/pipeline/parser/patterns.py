"""Regex patterns nhận dạng ranh giới Phần/Chương/Mục/Tiểu mục/Điều/Khoản/Điểm.

Nguồn: plans/04_graph_construction_pipeline.md mục "Pattern Nhận Dạng".
Giữ patterns tách riêng khỏi hierarchy_parser.py để dễ điều chỉnh khi gặp
edge case thực tế trên văn bản thật (ghi log vào REPORT.md mục A).
"""

import re


MAX_STRUCTURAL_TITLE_LENGTH = 240

# Pattern nhận diện dòng bắt đầu một Điều luật có chứa tối đa 2 ký tự nhiễu ở đầu (dành cho OCR).
ARTICLE_RE_LENIENT = re.compile(
    r"^[^\wĐ]{0,2}Điều\s+(\d+[a-z]?)(?:\[\d+\])?\s*(?::|\.|\s*$)\s*(.*)$", re.IGNORECASE
)

# ===================================================================================================

# Pattern nhận diện dòng in hoa toàn bộ có dấu tiếng Việt (dùng làm heuristic cho tên Chương).
UPPERCASE_TITLE_RE = re.compile(
    r"^[A-ZĐÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸ0-9 ,.\-]+$"
)

# Pattern nhận diện dòng bắt đầu một Điều luật chính xác (không chứa ký tự nhiễu).
ARTICLE_RE = re.compile(
    r"^Điều\s+(\d+[a-z]?)(?:\[\d+\])?\s*(?::|\.|\s*$)\s*(.*)$", re.IGNORECASE
)

# Pattern nhận diện dòng bắt đầu một Khoản luật (ví dụ: "1. ", "2. ").
CLAUSE_RE = re.compile(r"^(\d+[a-z]?)\.(?:\s+|$)(.*)$", re.IGNORECASE)

# Pattern nhận diện dòng bắt đầu một Điểm luật (ví dụ: "a) ", "b) ").
POINT_RE = re.compile(r"^([a-zđ])\)\s*(.*)$")

# Pattern nhận diện dòng tiêu đề Chương dạng số La Mã (ví dụ: "Chương II").
CHAPTER_RE = re.compile(r"^Chương\s+([IVXLCDM]+)\s*$", re.IGNORECASE)

_PART_NUMBER = (
    r"(?:[IVXLCDM]+|\d+[a-z]?|"
    r"(?:thứ\s+)?(?:nhất|một|hai|ba|tư|năm|sáu|bảy|tám|chín|mười))"
)

# Full-line only so inline citations such as "theo Phần II của Luật này" are not headings.
PART_RE = re.compile(
    rf"^Phần\s+({_PART_NUMBER})(?:(?:\.|:)\s*(.*))?$",
    re.IGNORECASE,
)

# Pattern nhận diện heading Mục toàn dòng. Citation như "Mục 1 Chương III"
# không full-match và vì vậy không thể trở thành structural heading.
SECTION_RE = re.compile(
    r"^Mục\s+(\d+[a-z]?)(?:(?:\.|:)\s*(.*))?$",
    re.IGNORECASE,
)

SUBSECTION_RE = re.compile(
    r"^Tiểu\s+Mục\s+(\d+[a-z]?)(?:(?:\.|:)\s*(.*))?$",
    re.IGNORECASE,
)


# Thực hiện khớp và bóc tách thông tin Điều luật (số thứ tự và nội dung).
def match_article(line: str, lenient: bool = False) -> tuple[str, str] | None:
    pattern = ARTICLE_RE_LENIENT if lenient else ARTICLE_RE
    m = pattern.match(line.strip())
    if not m:
        return None
    return m.group(1).lower(), m.group(2).strip()


# Thực hiện khớp và bóc tách thông tin Khoản luật (số thứ tự và nội dung).
def match_clause(line: str) -> tuple[str, str] | None:
    m = CLAUSE_RE.match(line.strip())
    if not m:
        return None
    return m.group(1).lower(), m.group(2).strip()


# Thực hiện khớp và bóc tách thông tin Điểm luật (ký hiệu chữ cái và nội dung).
def match_point(line: str) -> tuple[str, str] | None:
    m = POINT_RE.match(line.strip())
    if not m:
        return None
    return m.group(1), m.group(2).strip()


# Thực hiện khớp và bóc tách thông tin Chương (số thứ tự La Mã).
def match_chapter(line: str) -> str | None:
    m = CHAPTER_RE.match(line.strip())
    if not m:
        return None
    return m.group(1)


def match_part(line: str) -> tuple[str, str | None] | None:
    m = PART_RE.fullmatch(line.strip())
    if not m:
        return None
    title = (m.group(2) or "").strip()
    return m.group(1).lower(), title or None


def match_section(line: str) -> tuple[str, str | None] | None:
    m = SECTION_RE.fullmatch(line.strip())
    if not m:
        return None
    title = (m.group(2) or "").strip()
    return m.group(1).lower(), title or None


def match_subsection(line: str) -> tuple[str, str | None] | None:
    m = SUBSECTION_RE.fullmatch(line.strip())
    if not m:
        return None
    title = (m.group(2) or "").strip()
    return m.group(1).lower(), title or None


# Kiểm tra dòng văn bản có thỏa mãn điều kiện là tiêu đề Chương hay không.
def looks_like_title(line: str) -> bool:
    """Heuristic: dòng toàn chữ hoa, đủ ngắn để là tiêu đề chứ không phải đoạn văn."""
    stripped = line.strip()
    if not stripped or len(stripped) > MAX_STRUCTURAL_TITLE_LENGTH:
        return False
    # ``str.isupper`` handles Vietnamese uppercase letters and legal-title
    # punctuation such as ``;`` and ``%`` without maintaining a fragile
    # hand-written character class. It still requires at least one cased
    # character, so punctuation-only lines cannot become headings.
    return stripped.isupper()
