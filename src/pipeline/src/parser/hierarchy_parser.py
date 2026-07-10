"""Hierarchy Parser — Phân tích và cấu trúc hóa văn bản pháp luật VN -> ParsedDocument phân cấp.

State machine thuần text (`parse_lines`) xử lý phân tách cấu trúc Chương/Điều/Khoản/Điểm.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from src.parser.models import Article, Clause, DocumentInfo, ParsedDocument, Point
from src.parser.patterns import (
    looks_like_title,
    match_article,
    match_chapter,
    match_clause,
    match_point,
)

logger = logging.getLogger(__name__)


def clean_vietnamese_spacing(text: str) -> str:
    """Khắc phục lỗi tự động tách chữ tiếng Việt (lỗi khoảng cách dấu thanh/font/khoảng trắng thừa)."""
    # 1. Loại bỏ các dòng tiêu đề/chân trang Công Báo (Gazette headers/footers)
    # Ví dụ: "4 CÔNG BÁO/Số 1175 + 1176/Ngày 30-12-2014" hoặc "CÔNG BÁO/Số 1175 + 1176/Ngày 30-12-2014 5"
    gazette_pattern = re.compile(
        r"\d*\s*CÔNG BÁO\s*/\s*Số\s+[0-9\s+]+/\s*Ngày\s+[0-9\s\-]+\d*",
        re.IGNORECASE
    )
    text = gazette_pattern.sub("", text)

    # 2. Ghép các cặp phụ âm ghép bị tách (vd: t heo -> theo, t rên -> trên, p háp -> pháp, n ghiệm -> nghiệm)
    digraphs_pattern = re.compile(
        r"\b(c|g|k|n|p|t)\s+([hrg][aăâeêuơoôưiàáạảãầấậẩẫằắặẳẵèéẹẻẽềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỴỷỹ][\w]*)\b", 
        re.IGNORECASE
    )
    old_text = ""
    while old_text != text:
        old_text = text
        text = digraphs_pattern.sub(r"\1\2", text)

    # 3. Ghép phụ âm đầu bị tách khỏi nguyên âm (vd: h ữu -> hữu, qu ản -> quản, d oanh -> doanh)
    consonants = r"\b(ch|gh|kh|ngh|ng|nh|ph|qu|th|tr|[bcdđghklmnpqrstvx])"
    vowels = r"([aăâeêuơoôưiàáạảãầấậẩẫằắặẳẵèéẹẻẽềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỴỷỹ][\w]*)\b"
    pattern1 = re.compile(consonants + r"\s+" + vowels, re.IGNORECASE)
    
    old_text = ""
    while old_text != text:
        old_text = text
        text = pattern1.sub(r"\1\2", text)
        
    # 4. Ghép phần đuôi bắt đầu bằng nguyên âm mang dấu thanh (vd: nhi ệm -> nhiệm, nghi ệp -> nghiệp)
    diacritic_vowels = r"([àáạảãầấậẩẫằắặẳẵèéẹẻẽềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỴỷỹ][\w]*)\b"
    pattern2 = re.compile(r"(\w+)\s+" + diacritic_vowels, re.IGNORECASE)
    
    old_text = ""
    while old_text != text:
        old_text = text
        text = pattern2.sub(r"\1\2", text)
        
    # 5. Xử lý khoảng trắng thừa
    text = re.sub(r"\s+", " ", text).strip()
    return text


def should_skip_line(line: str) -> bool:
    """Kiểm tra xem dòng hiện tại có phải là số trang, chữ ký số hoặc thông tin rác cần bỏ qua không."""
    line = line.strip()
    # 1. Số trang đứng riêng lẻ (vd: "4", "5", "6")
    if re.match(r"^\d+$", line):
        return True
    # 2. Các dòng thuộc khối chữ ký số của Cổng TTĐT CP
    if (line.startswith("Ký bởi:") or 
        (line.startswith("Email:") and "@" in line) or 
        line.startswith("Cơ quan:") or 
        re.match(r"^Thời gian\s*ký:", line, re.IGNORECASE)):
        return True
    # 3. Tiêu đề Công Báo đứng riêng dòng
    if "CÔNG BÁO/Số" in line or "CONG BAO/So" in line:
        return True
    return False


@dataclass
class LineRecord:
    text: str
    font_size: float = 0.0
    bold: bool = False


@dataclass
class _ArticleBuilder:
    number: int
    title: str | None
    chapter: str | None
    chapter_title: str | None
    content_lines: list[str] = field(default_factory=list)
    clauses: list[Clause] = field(default_factory=list)

    def to_article(self) -> Article:
        # Tái tạo content_raw sạch bằng cách nối các dòng tiếp nối bằng dấu cách,
        # và chỉ dùng dấu xuống dòng '\n' trước các Khoản/Điểm mới.
        joined_lines = []
        for line in self.content_lines:
            line_str = line.strip()
            if not line_str:
                continue
            
            from src.parser.patterns import match_clause, match_point
            
            is_new_element = (
                not joined_lines or 
                (self.title is not None and len(joined_lines) == 1) or 
                match_clause(line_str) is not None or 
                match_point(line_str) is not None
            )
            
            if is_new_element:
                joined_lines.append(line_str)
            else:
                joined_lines[-1] = f"{joined_lines[-1]} {line_str}".strip()
                
        content_raw = "\n".join(joined_lines)
        return Article(
            number=self.number,
            title=self.title,
            content_raw=content_raw,
            chapter=self.chapter,
            chapter_title=self.chapter_title,
            clauses=self.clauses,
        )


def parse_lines(lines: list[str]) -> list[Article]:
    """State machine cốt lõi: list các dòng text (đã strip blank thừa) -> list[Article].

    Chỉ dùng regex pattern + heuristic "dòng toàn chữ hoa" để bắt tiêu đề chương.

    Theo dõi trạng thái dấu ngoặc kép (“ ”, dùng trong văn bản "sửa đổi, bổ sung" để
    trích dẫn nguyên văn nội dung mới) bằng 1 counter `quote_depth`: khi đang ở trong
    trích dẫn (`quote_depth > 0`), KHÔNG nhận diện Điều/Khoản/Điểm mới trên dòng đó dù
    format có khớp regex — coi là nội dung tiếp nối của Khoản/Điểm cha. Lý do: nội dung
    trích dẫn thường tự có cấu trúc số/chữ cái riêng ("1.", "a)"...) của chính nó, nếu
    không tách biệt sẽ bị nhận nhầm thành Khoản/Điểm cấp cao mới (xem REPORT.md mục A7).
    """
    articles: list[Article] = []
    current_chapter: str | None = None
    current_chapter_title: str | None = None
    current_article: _ArticleBuilder | None = None
    current_clause: Clause | None = None
    current_point: Point | None = None

    def flush_article() -> None:
        nonlocal current_article, current_clause, current_point
        if current_article is not None:
            flush_clause()
            articles.append(current_article.to_article())
        current_article = None
        current_clause = None
        current_point = None

    def flush_clause() -> None:
        nonlocal current_clause, current_point
        if current_clause is not None and current_article is not None:
            flush_point()
            current_article.clauses.append(current_clause)
        current_clause = None
        current_point = None

    def flush_point() -> None:
        nonlocal current_point
        if current_point is not None and current_clause is not None:
            current_clause.points.append(current_point)
        current_point = None

    pending_chapter_title = False
    # Đếm độ sâu dấu ngoặc kép “ ” đang mở — > 0 nghĩa là dòng hiện tại nằm trong
    # khối trích dẫn nguyên văn (vd nội dung mới của khoản/điểm bị sửa đổi), nên
    # KHÔNG coi cấu trúc số/chữ cái bên trong nó là Khoản/Điểm thật của văn bản.
    quote_depth = 0

    for raw_line in lines:
        cleaned_line = clean_vietnamese_spacing(raw_line)
        line = cleaned_line.strip()
        if not line or should_skip_line(line):
            continue

        in_quote = quote_depth > 0
        quote_depth = max(0, quote_depth + line.count("“") - line.count("”"))

        if in_quote:
            # Đang trong trích dẫn -> chỉ coi là nội dung tiếp nối, không nhận diện
            # Chương/Điều/Khoản/Điểm mới trên dòng này.
            if current_article is not None:
                current_article.content_lines.append(line)
                if current_point is not None:
                    current_point.content = f"{current_point.content} {line}".strip()
                elif current_clause is not None:
                    current_clause.content = f"{current_clause.content} {line}".strip()
            continue

        chapter_num = match_chapter(line)
        if chapter_num is not None:
            current_chapter = chapter_num
            current_chapter_title = None
            pending_chapter_title = True
            continue

        if pending_chapter_title:
            pending_chapter_title = False
            if looks_like_title(line):
                current_chapter_title = line
                continue
            # Không phải tiêu đề chương (vd đi thẳng vào Điều) -> rơi qua xử lý bình thường

        article_match = match_article(line)
        if article_match is not None:
            flush_article()
            number, title = article_match
            current_article = _ArticleBuilder(
                number=number,
                title=title or None,
                chapter=current_chapter,
                chapter_title=current_chapter_title,
            )
            if title:
                current_article.content_lines.append(title)
            continue

        if current_article is None:
            # Dòng trước Điều đầu tiên (header văn bản, mục lục...) -> bỏ qua, log để debug
            logger.debug("Bỏ qua dòng ngoài cấu trúc Điều: %r", line)
            continue

        clause_match = match_clause(line)
        if clause_match is not None:
            flush_clause()
            number, content = clause_match
            current_clause = Clause(number=number, content=content)
            current_article.content_lines.append(line)
            continue

        point_match = match_point(line)
        if point_match is not None and current_clause is not None:
            flush_point()
            label, content = point_match
            current_point = Point(label=label, content=content)
            current_article.content_lines.append(line)
            continue

        # Dòng tiếp nối nội dung (continuation) của point/clause/article hiện tại
        current_article.content_lines.append(line)
        if current_point is not None:
            current_point.content = f"{current_point.content} {line}".strip()
        elif current_clause is not None:
            current_clause.content = f"{current_clause.content} {line}".strip()

    flush_article()
    return articles


def parse_text(text: str, document: DocumentInfo) -> ParsedDocument:
    """Parse từ văn bản text thuần."""
    lines = text.splitlines()
    articles = parse_lines(lines)
    return ParsedDocument(document=document, articles=articles)

