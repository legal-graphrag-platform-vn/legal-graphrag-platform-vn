"""Regex patterns nhận dạng ranh giới Phần/Chương/Điều/Khoản/Điểm.

Nguồn: plans/04_graph_construction_pipeline.md mục "Pattern Nhận Dạng".
Giữ patterns tách riêng khỏi hierarchy_parser.py để dễ điều chỉnh khi gặp
edge case thực tế trên văn bản thật (ghi log vào REPORT.md mục A).
"""

import re


# Pattern nhận diện dòng bắt đầu một Điều luật có chứa tối đa 2 ký tự nhiễu ở đầu (dành cho OCR).
ARTICLE_RE_LENIENT = re.compile(r"^[^\wĐ]{0,2}Điều\s+(\d+)(?:\.|\s*$)\s*(.*)$")

#===================================================================================================

# Pattern nhận diện dòng in hoa toàn bộ có dấu tiếng Việt (dùng làm heuristic cho tên Chương).
UPPERCASE_TITLE_RE = re.compile(
    r"^[A-ZĐÀÁẠẢÃÂẦẤẬẨẪĂẰẮẶẲẴÈÉẸẺẼÊỀẾỆỂỄÌÍỊỈĨÒÓỌỎÕÔỒỐỘỔỖƠỜỚỢỞỠÙÚỤỦŨƯỪỨỰỬỮỲÝỴỶỸ0-9 ,.\-]+$"
)

# Pattern nhận diện dòng bắt đầu một Điều luật chính xác (không chứa ký tự nhiễu).
ARTICLE_RE = re.compile(r"^Điều\s+(\d+)(?:\.|\s*$)\s*(.*)$")

# Pattern nhận diện dòng bắt đầu một Khoản luật (ví dụ: "1. ", "2. ").
CLAUSE_RE = re.compile(r"^(\d+)\.\s*(.*)$")

# Pattern nhận diện dòng bắt đầu một Điểm luật (ví dụ: "a) ", "b) ").
POINT_RE = re.compile(r"^([a-zđ])\)\s*(.*)$")

# Pattern nhận diện dòng tiêu đề Chương dạng số La Mã (ví dụ: "Chương II").
CHAPTER_RE = re.compile(r"^Chương\s+([IVXLCDM]+)\s*$", re.IGNORECASE)



# Thực hiện khớp và bóc tách thông tin Điều luật (số thứ tự và nội dung).
def match_article(line: str, lenient: bool = False) -> tuple[int, str] | None:
    pattern = ARTICLE_RE_LENIENT if lenient else ARTICLE_RE
    m = pattern.match(line.strip())
    if not m:
        return None
    return int(m.group(1)), m.group(2).strip()


# Thực hiện khớp và bóc tách thông tin Khoản luật (số thứ tự và nội dung).
def match_clause(line: str) -> tuple[int, str] | None:
    m = CLAUSE_RE.match(line.strip())
    if not m:
        return None
    return int(m.group(1)), m.group(2).strip()


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


# Kiểm tra dòng văn bản có thỏa mãn điều kiện là tiêu đề Chương hay không.
def looks_like_title(line: str) -> bool:
    """Heuristic: dòng toàn chữ hoa, đủ ngắn để là tiêu đề chứ không phải đoạn văn."""
    stripped = line.strip()
    if not stripped or len(stripped) > 120:
        return False
    return bool(UPPERCASE_TITLE_RE.match(stripped))
