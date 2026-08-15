"""Hierarchy Parser — Phân tích và cấu trúc hóa văn bản pháp luật VN -> ParsedDocument phân cấp.

State machine thuần text (`parse_lines`) xử lý phân tách cấu trúc Chương/Điều/Khoản/Điểm.
"""

from __future__ import annotations

import logging
import re
import hashlib
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from src.pipeline.parser.models import (
    Appendix,
    Article,
    AttachedInstrument,
    Clause,
    DocumentInfo,
    ParseDiagnostics,
    ParseWarning,
    Part,
    ParsedDocument,
    Point,
    Section,
    Subsection,
    UnparsedSection,
)
from src.pipeline.parser.patterns import (
    MAX_STRUCTURAL_TITLE_LENGTH,
    looks_like_title,
    match_article,
    match_chapter,
    match_chapter_heading,
    match_clause,
    match_part,
    match_point,
    match_section,
    match_subsection,
)

logger = logging.getLogger(__name__)


def clean_vietnamese_spacing(text: str) -> str:
    """Khắc phục lỗi tự động tách chữ tiếng Việt (lỗi khoảng cách dấu thanh/font/khoảng trắng thừa)."""
    # 1. Loại bỏ các dòng tiêu đề/chân trang Công Báo (Gazette headers/footers)
    # Ví dụ: "4 CÔNG BÁO/Số 1175 + 1176/Ngày 30-12-2014" hoặc "CÔNG BÁO/Số 1175 + 1176/Ngày 30-12-2014 5"
    gazette_pattern = re.compile(
        r"\d*\s*CÔNG BÁO\s*/\s*Số\s+[0-9\s+]+/\s*Ngày\s+[0-9\s\-]+\d*", re.IGNORECASE
    )
    text = gazette_pattern.sub("", text)

    # 2. Ghép các cặp phụ âm ghép bị tách (vd: t heo -> theo, t rên -> trên, p háp -> pháp, n ghiệm -> nghiệm)
    digraphs_pattern = re.compile(
        r"\b(c|g|k|n|p|t)\s+([hrg][aăâeêuơoôưiàáạảãầấậẩẫằắặẳẵèéẹẻẽềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỴỷỹ][\w]*)\b",
        re.IGNORECASE,
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
    diacritic_vowels = (
        r"([àáạảãầấậẩẫằắặẳẵèéẹẻẽềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỴỷỹ][\w]*)\b"
    )
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
    if (
        line.startswith("Ký bởi:")
        or (line.startswith("Email:") and "@" in line)
        or line.startswith("Cơ quan:")
        or re.match(r"^Thời gian\s*ký:", line, re.IGNORECASE)
    ):
        return True
    # 3. Tiêu đề Công Báo đứng riêng dòng
    if "CÔNG BÁO/Số" in line or "CONG BAO/So" in line:
        return True
    if line in {"Điều khoản được sửa đổi, bổ sung", "Điều khoản được bổ sung"}:
        return True
    return False


@dataclass
class LineRecord:
    text: str
    font_size: float = 0.0
    bold: bool = False
    source_start_char: int = 0
    source_end_char: int = 0
    source_line: int = 1


@dataclass
class _ArticleBuilder:
    number: str
    title: str | None
    part: str | None
    chapter: str | None
    chapter_title: str | None
    section: str | None
    subsection: str | None
    content_lines: list[str] = field(default_factory=list)
    clauses: list[Clause] = field(default_factory=list)
    source_start_char: int = 0
    source_end_char: int = 0

    def to_article(self) -> Article:
        # Tái tạo content_raw sạch bằng cách nối các dòng tiếp nối bằng dấu cách,
        # và chỉ dùng dấu xuống dòng '\n' trước các Khoản/Điểm mới.
        joined_lines = []
        for line in self.content_lines:
            line_str = line.strip()
            if not line_str:
                continue

            from src.pipeline.parser.patterns import match_clause, match_point

            is_new_element = (
                not joined_lines
                or (self.title is not None and len(joined_lines) == 1)
                or match_clause(line_str) is not None
                or match_point(line_str) is not None
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
            part=self.part,
            chapter=self.chapter,
            chapter_title=self.chapter_title,
            section=self.section,
            subsection=self.subsection,
            clauses=self.clauses,
            source_start_char=self.source_start_char,
            source_end_char=self.source_end_char,
        )


def _ascii(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    return (
        "".join(char for char in decomposed if unicodedata.category(char) != "Mn")
        .replace("đ", "d")
        .replace("Đ", "D")
    )


CITATION_PREV_RE = re.compile(
    r"(?:quy\s+dinh\s+tai|sua\s+doi[,\s]+bo\s+sung|thong\s+nhat\s+voi|theo|tai|theo\s+quy\s+dinh|khoan\s+\d+|diem\s+[a-z]|vao|hoac|va|bai\s+bo|,)\s*$",
    re.IGNORECASE,
)
CITATION_NEXT_RE = re.compile(
    r"^(?:va|hoac|,|nhu\s+sau|cua|nghi\s+dinh|luat|phu\s+luc|\.)",
    re.IGNORECASE,
)
CLOSING_ARTICLE_TITLE_RE = re.compile(r"(?:thi\s+hanh|chuyen\s+tiep)", re.IGNORECASE)
REPLACEMENT_QUOTE_INTRO_RE = re.compile(
    r"(?:sua\s+doi|bo\s+sung|thay\s+the|bai\s+bo).{0,200}"
    r"(?:nhu\s+sau|sau\s+day)\s*:\s*(.*)$",
    re.IGNORECASE,
)


def is_citation_context(prev_line: str, line: str, next_line: str) -> bool:
    m = re.match(r"^Điều\s+\d+[a-z]?$", line.strip(), re.IGNORECASE)
    if not m:
        return False
    prev_asc = _ascii(prev_line).strip().lower() if prev_line else ""
    next_asc = _ascii(next_line).strip().lower() if next_line else ""
    if prev_asc and CITATION_PREV_RE.search(prev_asc):
        return True
    if next_asc and CITATION_NEXT_RE.search(next_asc):
        return True
    return False


@dataclass(frozen=True, slots=True)
class _ParsedHierarchy:
    articles: list[Article]
    parts: list[Part]
    sections: list[Section]
    subsections: list[Subsection]


@dataclass(frozen=True, slots=True)
class _SourcePartitions:
    main: list[LineRecord]
    appendices: list[list[LineRecord]]
    attached_instruments: list[list[LineRecord]]
    table_of_contents: list[LineRecord]


@dataclass(frozen=True, slots=True)
class _AppendixHeading:
    number: str | None
    title: str | None


@dataclass(frozen=True, slots=True)
class _AttachedInstrumentHeading:
    instrument_kind: str
    title: str | None
    adoption_text: str
    adoption_line_offset: int


def _replacement_quote_lines(
    lines: list[str] | list[LineRecord],
) -> tuple[set[int], list[ParseWarning]]:
    """Locate only explicit, closed amendment/replacement quotation blocks.

    Ordinary typographic quotes are content punctuation and must never disable
    structural heading recognition for the remainder of a document.
    """

    quoted_lines: set[int] = set()
    warnings: list[ParseWarning] = []
    pending_intro: LineRecord | None = None
    active_origin: LineRecord | None = None
    active_lines: list[int] = []
    quote_style: str | None = None
    quote_depth = 0

    def as_record(item: str | LineRecord, index: int) -> LineRecord:
        if isinstance(item, LineRecord):
            return item
        return LineRecord(text=str(item), source_line=index + 1)

    def start_scope(record: LineRecord, index: int, line: str) -> None:
        nonlocal active_origin, quote_style, quote_depth
        active_origin = pending_intro or record
        quote_style = "curly" if line.startswith("“") else "straight"
        quote_depth = (
            line.count("“") - line.count("”")
            if quote_style == "curly"
            else line.count('"') % 2
        )
        if (
            quote_style == "curly"
            and quote_depth > 0
            and re.search(r'"\s*[.,;:]?\s*$', line)
        ):
            quote_depth = 0
        active_lines.append(index)

    for index, item in enumerate(lines):
        record = as_record(item, index)
        line = clean_vietnamese_spacing(record.text).strip()
        if not line:
            continue

        if active_origin is not None:
            active_lines.append(index)
            if quote_style == "curly":
                quote_depth += line.count("“") - line.count("”")
                if quote_depth > 0 and re.search(r'"\s*[.,;:]?\s*$', line):
                    quote_depth = 0
            else:
                quote_depth ^= line.count('"') % 2
            if quote_depth <= 0:
                quoted_lines.update(active_lines)
                active_origin = None
                active_lines = []
                quote_style = None
                quote_depth = 0
            continue

        if pending_intro is not None:
            if line.startswith(("“", '"')):
                start_scope(record, index, line)
                pending_intro = None
                if quote_depth <= 0:
                    quoted_lines.update(active_lines)
                    active_origin = None
                    active_lines = []
                    quote_style = None
                continue
            pending_intro = None

        intro_match = REPLACEMENT_QUOTE_INTRO_RE.search(_ascii(line).lower())
        if intro_match is not None:
            suffix = intro_match.group(1).lstrip()
            if suffix.startswith(("“", '"')):
                start_scope(record, index, suffix)
                active_lines.clear()  # The intro itself remains normal host content.
                if quote_depth <= 0:
                    active_origin = None
                    quote_style = None
            else:
                pending_intro = record
            continue

        if line.count("“") != line.count("”"):
            warnings.append(
                ParseWarning(
                    code="UNSCOPED_QUOTE_IMBALANCE_IGNORED",
                    message=(
                        "Unbalanced ordinary quotation mark was treated as content; "
                        "structural heading detection remained active."
                    ),
                    source_line=record.source_line,
                    source_start_char=record.source_start_char,
                    source_end_char=record.source_end_char,
                )
            )

    if active_origin is not None:
        warnings.append(
            ParseWarning(
                code="UNCLOSED_REPLACEMENT_QUOTE_IGNORED",
                message=(
                    "An explicit replacement quotation was not closed; its internal "
                    "headings were parsed permissively instead of swallowing the "
                    "remainder of the document."
                ),
                source_line=active_origin.source_line,
                source_start_char=active_origin.source_start_char,
                source_end_char=active_origin.source_end_char,
            )
        )

    return quoted_lines, warnings


def parse_lines(lines: list[str] | list[LineRecord]) -> list[Article]:
    """Compatibility wrapper returning only parsed Articles."""
    return _parse_hierarchy(lines).articles


def _parse_hierarchy(
    lines: list[str] | list[LineRecord],
    *,
    warnings: list[ParseWarning] | None = None,
) -> _ParsedHierarchy:
    """Parse the canonical seven-path structural hierarchy deterministically."""
    articles: list[Article] = []
    parts: list[Part] = []
    sections: list[Section] = []
    subsections: list[Subsection] = []

    current_part: Part | None = None
    current_chapter: str | None = None
    current_chapter_title: str | None = None
    current_section: Section | None = None
    current_subsection: Subsection | None = None
    current_article: _ArticleBuilder | None = None
    current_clause: Clause | None = None
    current_point: Point | None = None
    part_article_count = 0
    chapter_article_count = 0
    section_article_count = 0
    subsection_article_count = 0
    document_mode: str | None = None
    chapter_modes: dict[tuple[str | None, str], str] = {}
    section_modes: dict[tuple[str | None, str, str], str] = {}

    def flush_point() -> None:
        nonlocal current_point
        if current_point is not None and current_clause is not None:
            duplicate = next(
                (
                    point
                    for point in current_clause.points
                    if point.label.strip().lower()
                    == current_point.label.strip().lower()
                ),
                None,
            )
            if duplicate is None:
                current_clause.points.append(current_point)
            elif duplicate.content.strip() == current_point.content.strip():
                duplicate.source_end_char = max(
                    duplicate.source_end_char, current_point.source_end_char
                )
            else:
                duplicate.content = (
                    f"{duplicate.content} {current_point.content}".strip()
                )
                duplicate.source_end_char = max(
                    duplicate.source_end_char, current_point.source_end_char
                )
        current_point = None

    def flush_clause() -> None:
        nonlocal current_clause, current_point
        if current_clause is not None and current_article is not None:
            flush_point()
            current_article.clauses.append(current_clause)
        current_clause = None
        current_point = None

    def flush_article() -> None:
        nonlocal current_article, current_clause, current_point
        if current_article is not None:
            flush_clause()
            articles.append(current_article.to_article())
        current_article = None
        current_clause = None
        current_point = None

    def require_mode(current: str | None, expected: str, *, owner: str) -> str:
        if current is not None and current != expected:
            logger.debug(f"{owner} transition from {current} to {expected} mode")
        return expected

    def require_current_subsection_has_article() -> None:
        nonlocal current_subsection
        if current_subsection is not None and subsection_article_count == 0:
            if subsections and subsections[-1] == current_subsection:
                subsections.pop()
            current_subsection = None

    def require_current_section_has_article() -> None:
        nonlocal current_section
        if current_section is not None and section_article_count == 0:
            if sections and sections[-1] == current_section:
                sections.pop()
            current_section = None

    def require_current_chapter_has_article() -> None:
        nonlocal current_chapter
        if current_chapter is not None and chapter_article_count == 0:
            current_chapter = None

    def require_current_part_has_article() -> None:
        nonlocal current_part
        if current_part is not None and part_article_count == 0:
            if parts and parts[-1] == current_part:
                parts.pop()
            current_part = None

    pending_chapter_title = False
    pending_article_title = False
    pending_heading: tuple[str, str, LineRecord] | None = None
    replacement_quote_lines, quote_warnings = _replacement_quote_lines(lines)
    if warnings is not None:
        warnings.extend(quote_warnings)
    raw_text_lines = [
        item.text if isinstance(item, LineRecord) else str(item) for item in lines
    ]

    for idx, item in enumerate(lines):
        record = item if isinstance(item, LineRecord) else LineRecord(text=item)
        line = clean_vietnamese_spacing(record.text).strip()
        if not line or should_skip_line(line):
            continue

        prev_line = raw_text_lines[idx - 1] if idx > 0 else ""
        next_line = raw_text_lines[idx + 1] if idx < len(raw_text_lines) - 1 else ""

        if idx in replacement_quote_lines:
            if current_article is not None:
                current_article.content_lines.append(line)
                current_article.source_end_char = record.source_end_char
                if current_point is not None:
                    current_point.content = f"{current_point.content} {line}".strip()
                    current_point.source_end_char = record.source_end_char
                elif current_clause is not None:
                    current_clause.content = f"{current_clause.content} {line}".strip()
                    current_clause.source_end_char = record.source_end_char
            continue

        if pending_heading is not None:
            kind, number, heading_record = pending_heading
            if not _looks_like_structural_title(record, line):
                default_title = f"{kind} {number}"
                if kind == "Part":
                    current_part = Part(
                        number=number,
                        title=default_title,
                        source_start_char=heading_record.source_start_char,
                        source_end_char=heading_record.source_end_char,
                    )
                    parts.append(current_part)
                elif kind == "Section":
                    current_section = Section(
                        number=number,
                        title=default_title,
                        part=current_part.number if current_part else None,
                        chapter=current_chapter,
                        source_start_char=heading_record.source_start_char,
                        source_end_char=heading_record.source_end_char,
                    )
                    sections.append(current_section)
                else:
                    current_subsection = Subsection(
                        number=number,
                        title=default_title,
                        part=current_part.number if current_part else None,
                        chapter=current_chapter,
                        section=current_section.number if current_section else "",
                        source_start_char=heading_record.source_start_char,
                        source_end_char=heading_record.source_end_char,
                    )
                    subsections.append(current_subsection)
                pending_heading = None
            else:
                if kind == "Part":
                    current_part = Part(
                        number=number,
                        title=line,
                        source_start_char=heading_record.source_start_char,
                        source_end_char=record.source_end_char,
                    )
                    parts.append(current_part)
                elif kind == "Section":
                    current_section = Section(
                        number=number,
                        title=line,
                        part=current_part.number if current_part else None,
                        chapter=current_chapter,
                        source_start_char=heading_record.source_start_char,
                        source_end_char=record.source_end_char,
                    )
                    sections.append(current_section)
                else:
                    current_subsection = Subsection(
                        number=number,
                        title=line,
                        part=current_part.number if current_part else None,
                        chapter=current_chapter,
                        section=current_section.number if current_section else "",
                        source_start_char=heading_record.source_start_char,
                        source_end_char=record.source_end_char,
                    )
                    subsections.append(current_subsection)
                pending_heading = None
                continue

        part_match = match_part(line)
        if part_match is not None:
            flush_article()
            require_current_subsection_has_article()
            require_current_section_has_article()
            if current_chapter is not None and chapter_article_count == 0:
                pass
            else:
                require_current_chapter_has_article()
            if current_part is not None and part_article_count == 0:
                if parts and parts[-1] == current_part:
                    parts.pop()
            else:
                require_current_part_has_article()
            document_mode = require_mode(document_mode, "Part", owner="Document")
            number, inline_title = part_match
            current_part = None
            current_chapter = None
            current_chapter_title = None
            current_section = None
            current_subsection = None
            part_article_count = 0
            chapter_article_count = 0
            section_article_count = 0
            subsection_article_count = 0
            if inline_title is None:
                pending_heading = ("Part", number, record)
            else:
                current_part = Part(
                    number=number,
                    title=_bounded_title("Part", number, inline_title),
                    source_start_char=record.source_start_char,
                    source_end_char=record.source_end_char,
                )
                parts.append(current_part)
            continue

        chapter_match = match_chapter_heading(line)
        if chapter_match is not None:
            flush_article()
            require_current_subsection_has_article()
            require_current_section_has_article()
            if current_chapter is not None and chapter_article_count == 0:
                pass
            else:
                require_current_chapter_has_article()
            expected_root_mode = "Part" if current_part is not None else "Chapter"
            document_mode = require_mode(
                document_mode, expected_root_mode, owner="Document"
            )
            chapter_num, inline_chapter_title = chapter_match
            current_chapter = chapter_num
            current_chapter_title = inline_chapter_title
            current_section = None
            current_subsection = None
            chapter_article_count = 0
            section_article_count = 0
            subsection_article_count = 0
            pending_chapter_title = inline_chapter_title is None
            continue

        if pending_chapter_title:
            pending_chapter_title = False
            if looks_like_title(line):
                current_chapter_title = line
                continue

        section_match = match_section(line)
        if section_match is not None:
            flush_article()
            require_current_subsection_has_article()
            require_current_section_has_article()
            if current_chapter is not None:
                chapter_key = (
                    current_part.number if current_part else None,
                    current_chapter,
                )
                chapter_modes[chapter_key] = require_mode(
                    chapter_modes.get(chapter_key),
                    "Section",
                    owner=f"Chapter {current_chapter}",
                )
            number, inline_title = section_match
            current_section = None
            current_subsection = None
            section_article_count = 0
            subsection_article_count = 0
            if inline_title is None:
                pending_heading = ("Section", number, record)
            else:
                current_section = Section(
                    number=number,
                    title=_bounded_title("Section", number, inline_title),
                    part=current_part.number if current_part else None,
                    chapter=current_chapter,
                    source_start_char=record.source_start_char,
                    source_end_char=record.source_end_char,
                )
                sections.append(current_section)
            continue

        subsection_match = match_subsection(line)
        if subsection_match is not None:
            if current_section is None:
                raise ValueError(
                    f"Subsection {subsection_match[0]} appears before any Section"
                )
            flush_article()
            require_current_subsection_has_article()
            section_key = (
                current_part.number if current_part else None,
                current_chapter or "",
                current_section.number,
            )
            section_modes[section_key] = require_mode(
                section_modes.get(section_key),
                "Subsection",
                owner=f"Section {current_section.number}",
            )
            number, inline_title = subsection_match
            current_subsection = None
            subsection_article_count = 0
            if inline_title is None:
                pending_heading = ("Subsection", number, record)
            else:
                current_subsection = Subsection(
                    number=number,
                    title=_bounded_title("Subsection", number, inline_title),
                    part=current_part.number if current_part else None,
                    chapter=current_chapter,
                    section=current_section.number,
                    source_start_char=record.source_start_char,
                    source_end_char=record.source_end_char,
                )
                subsections.append(current_subsection)
            continue

        article_match = match_article(line)
        if article_match is not None and not is_citation_context(
            prev_line, line, next_line
        ):
            flush_article()
            number, inline_title = article_match
            part_article_count += 1
            chapter_article_count += 1
            section_article_count += 1
            subsection_article_count += 1
            if current_chapter is not None and current_section is None:
                chapter_key = (
                    current_part.number if current_part else None,
                    current_chapter,
                )
                chapter_modes[chapter_key] = require_mode(
                    chapter_modes.get(chapter_key),
                    "Article",
                    owner=f"Chapter {current_chapter}",
                )
            if current_section is not None and current_subsection is None:
                section_key = (
                    current_part.number if current_part else None,
                    current_chapter or "",
                    current_section.number,
                )
                section_modes[section_key] = require_mode(
                    section_modes.get(section_key),
                    "Article",
                    owner=f"Section {current_section.number}",
                )

            current_article = _ArticleBuilder(
                number=number,
                title=inline_title,
                part=current_part.number if current_part else None,
                chapter=current_chapter,
                chapter_title=current_chapter_title,
                section=current_section.number if current_section else None,
                subsection=(current_subsection.number if current_subsection else None),
                source_start_char=record.source_start_char,
                source_end_char=record.source_end_char,
            )
            current_clause = None
            current_point = None
            pending_article_title = inline_title is None
            if not pending_article_title and inline_title:
                current_article.content_lines.append(inline_title)
            continue

        if pending_article_title:
            pending_article_title = False
            title = _bounded_title("Article", current_article.number, line)
            current_article.title = title
            current_article.content_lines.append(title)
            continue

        if current_article is None:
            logger.debug("Bỏ qua dòng ngoài cấu trúc Điều: %r", line)
            continue

        clause_match = match_clause(line)
        if clause_match is not None:
            number, content = clause_match
            existing_clauses = {c.number for c in current_article.clauses}
            if current_clause is not None and (
                number in existing_clauses or number == current_clause.number
            ):
                clause_match = None

        if clause_match is not None:
            flush_clause()
            number, content = clause_match
            current_clause = Clause(
                number=number,
                content=content,
                source_start_char=record.source_start_char,
                source_end_char=record.source_end_char,
            )
            current_article.content_lines.append(line)
            current_article.source_end_char = record.source_end_char
            continue

        point_match = match_point(line)
        if point_match is not None and current_clause is not None:
            label, content = point_match
            existing_points = {p.label.strip().lower() for p in current_clause.points}
            if current_point is not None and label.strip().lower() in existing_points:
                point_match = None

        if point_match is not None and current_clause is not None:
            flush_point()
            label, content = point_match
            current_point = Point(
                label=label,
                content=content,
                source_start_char=record.source_start_char,
                source_end_char=record.source_end_char,
            )
            current_article.content_lines.append(line)
            current_article.source_end_char = record.source_end_char
            current_clause.source_end_char = record.source_end_char
            continue

        current_article.content_lines.append(line)
        current_article.source_end_char = record.source_end_char
        if current_point is not None:
            current_point.content = f"{current_point.content} {line}".strip()
            current_point.source_end_char = record.source_end_char
            if current_clause is not None:
                current_clause.source_end_char = record.source_end_char
        elif current_clause is not None:
            current_clause.content = f"{current_clause.content} {line}".strip()
            current_clause.source_end_char = record.source_end_char

    flush_article()
    if pending_heading is not None:
        raise ValueError(
            f"{pending_heading[0]} {pending_heading[1]} is missing a valid title"
        )
    require_current_subsection_has_article()
    require_current_section_has_article()
    require_current_chapter_has_article()
    require_current_part_has_article()
    return _ParsedHierarchy(
        articles=articles,
        parts=parts,
        sections=sections,
        subsections=subsections,
    )


def parse_text(text: str, document: DocumentInfo) -> ParsedDocument:
    """Parse từ văn bản text thuần."""
    canonical_text = canonicalize_source_text(text)
    document = _with_source_effective_date(canonical_text, document)
    return _parse_canonical_text(canonical_text, document)


def parse_text_with_diagnostics(
    text: str, document: DocumentInfo
) -> tuple[ParsedDocument, ParseDiagnostics]:
    """Parse permissively while preserving uncertain source and audit warnings."""

    canonical_text = canonicalize_source_text(text)
    document = _with_source_effective_date(canonical_text, document)
    warnings: list[ParseWarning] = []
    records = source_line_records(canonical_text)
    partitions = partition_source_sections(records)
    main_records = partitions.main
    try:
        parsed = _parse_canonical_text(
            canonical_text,
            document,
            warnings=warnings,
            partitioned=partitions,
        )
    except ValueError as exc:
        warnings.append(
            ParseWarning(
                code="HIERARCHY_VALIDATION_FALLBACK",
                message=str(exc),
            )
        )
        parsed = _source_preserved_document(canonical_text, document)

    if not parsed.articles and _records_have_content(main_records):
        if not any(
            section.section_type == "UNPARSED_BODY"
            for section in parsed.unparsed_sections
        ):
            parsed = parsed.model_copy(
                update={
                    "unparsed_sections": [
                        _unparsed_body_section(
                            main_records, canonical_text, document.id
                        ),
                        *parsed.unparsed_sections,
                    ]
                }
            )
        if not any(
            warning.code == "HIERARCHY_VALIDATION_FALLBACK" for warning in warnings
        ):
            warnings.append(
                ParseWarning(
                    code="NO_ARTICLE_BOUNDARY",
                    message=(
                        "No supported Article boundary was found; the canonical "
                        "body was preserved without inventing legal structure."
                    ),
                    source_line=main_records[0].source_line,
                    source_start_char=main_records[0].source_start_char,
                    source_end_char=main_records[-1].source_end_char,
                )
            )

    status = (
        "SOURCE_PRESERVED"
        if any(
            section.section_type == "UNPARSED_BODY"
            for section in parsed.unparsed_sections
        )
        else "PARSED_WITH_WARNINGS"
        if warnings
        else "PARSED"
    )
    diagnostics = ParseDiagnostics(
        source_sha256=hashlib.sha256(canonical_text.encode("utf-8")).hexdigest(),
        status=status,
        article_count=len(parsed.articles)
        + sum(len(appendix.articles) for appendix in parsed.appendices)
        + sum(
            len(instrument.articles)
            + sum(len(appendix.articles) for appendix in instrument.appendices)
            for instrument in parsed.attached_instruments
        ),
        unparsed_section_count=len(parsed.unparsed_sections),
        warnings=warnings,
    )
    parsed = parsed.model_copy(update={"parser_metadata": diagnostics})
    return parsed, diagnostics


def _with_source_effective_date(
    canonical_text: str, document: DocumentInfo
) -> DocumentInfo:
    if document.effective_from is not None:
        return document
    source_effective_from = infer_source_effective_from(canonical_text)
    if source_effective_from is None:
        return document
    return document.model_copy(update={"effective_from": source_effective_from})


def _parse_canonical_text(
    canonical_text: str,
    document: DocumentInfo,
    *,
    warnings: list[ParseWarning] | None = None,
    partitioned: _SourcePartitions | None = None,
) -> ParsedDocument:
    records = source_line_records(canonical_text)
    partitions = partitioned or partition_source_sections(records)
    hierarchy = _parse_hierarchy(partitions.main, warnings=warnings)
    articles = hierarchy.articles
    _validate_unique_point_labels(articles)
    return ParsedDocument(
        document=document,
        articles=articles,
        parts=hierarchy.parts,
        sections=hierarchy.sections,
        subsections=hierarchy.subsections,
        appendices=[
            _appendix_from_records(
                group,
                canonical_text,
                document,
                source_order=source_order,
                parse_structure=True,
            )
            for source_order, group in enumerate(partitions.appendices, start=1)
        ],
        attached_instruments=[
            _attached_instrument_from_records(
                group,
                canonical_text,
                document,
                source_order=source_order,
            )
            for source_order, group in enumerate(
                partitions.attached_instruments, start=1
            )
        ],
        unparsed_sections=(
            [
                _table_of_contents_section(
                    partitions.table_of_contents, canonical_text, document.id
                )
            ]
            if partitions.table_of_contents
            else []
        ),
    )


def _source_preserved_document(
    canonical_text: str,
    document: DocumentInfo,
) -> ParsedDocument:
    records = source_line_records(canonical_text)
    return ParsedDocument(
        document=document,
        unparsed_sections=(
            [_unparsed_body_section(records, canonical_text, document.id)]
            if _records_have_content(records)
            else []
        ),
    )


def infer_source_effective_from(source_text: str) -> date | None:
    """Extract one explicit Vietnamese commencement date, failing on conflict."""

    matches = re.findall(
        r"có\s+hiệu\s+lực(?:\s+thi\s+hành)?\s+(?:kể\s+)?từ\s+ngày\s+"
        r"(\d{1,2})\s+tháng\s+(\d{1,2})\s+năm\s+(\d{4})",
        source_text,
        flags=re.IGNORECASE,
    )
    explicit_dates: set[date] = set()
    for day, month, year in matches:
        try:
            explicit_dates.add(date(int(year), int(month), int(day)))
        except ValueError as exc:
            raise ValueError(
                "Canonical source contains an invalid effective date"
            ) from exc
    if len(explicit_dates) > 1:
        raise ValueError("Canonical source contains conflicting effective dates")
    return next(iter(explicit_dates)) if explicit_dates else None


def _bounded_title(kind: str, number: str, title: str) -> str:
    normalized = title.strip()
    if not normalized:
        raise ValueError(f"{kind} {number} is missing a valid title")
    if len(normalized) > MAX_STRUCTURAL_TITLE_LENGTH:
        raise ValueError(
            f"{kind} {number} title exceeds {MAX_STRUCTURAL_TITLE_LENGTH} characters"
        )
    return normalized


def _looks_like_structural_title(record: LineRecord, line: str) -> bool:
    if len(line) > MAX_STRUCTURAL_TITLE_LENGTH:
        return False
    if any(
        matcher(line) is not None
        for matcher in (
            match_chapter,
            match_part,
            match_section,
            match_subsection,
            match_article,
            match_clause,
            match_point,
        )
    ):
        return False
    return record.bold or looks_like_title(line)


def canonicalize_source_text(text: str) -> str:
    """Canonical source coordinate space: NFC text with LF newlines."""
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def source_line_records(canonical_text: str) -> list[LineRecord]:
    records: list[LineRecord] = []
    cursor = 0
    for line_number, raw_line in enumerate(
        canonical_text.splitlines(keepends=True), start=1
    ):
        text = raw_line.rstrip("\n")
        records.append(
            LineRecord(
                text=text,
                source_start_char=cursor,
                source_end_char=cursor + len(text),
                source_line=line_number,
            )
        )
        cursor += len(raw_line)
    if canonical_text and not records:
        records.append(
            LineRecord(text=canonical_text, source_end_char=len(canonical_text))
        )
    return records


def partition_source_sections(records: list[LineRecord]) -> _SourcePartitions:
    """Split source into the host body, owned attachments, Appendices, and TOC."""

    main: list[LineRecord] = []
    appendices: list[list[LineRecord]] = []
    attached_instruments: list[list[LineRecord]] = []
    current_appendix: list[LineRecord] | None = None
    current_instrument: list[LineRecord] | None = None
    table_of_contents: list[LineRecord] = []
    seen_article = False
    midpoint = len(records) // 2

    for index, record in enumerate(records):
        if table_of_contents:
            table_of_contents.append(record)
            continue

        attached_heading = _match_attached_instrument_heading(records, index)
        if attached_heading is not None and current_appendix is None:
            current_instrument = [record]
            attached_instruments.append(current_instrument)
            continue

        if current_instrument is not None:
            current_instrument.append(record)
            continue

        appendix_heading = _match_appendix_heading(record.text)
        if appendix_heading is not None:
            current_appendix = [record]
            appendices.append(current_appendix)
            continue

        if current_appendix is not None:
            current_appendix.append(record)
            continue

        if (
            seen_article
            and index >= midpoint
            and _is_table_of_contents_heading(record.text)
        ):
            table_of_contents.append(record)
            continue

        main.append(record)
        seen_article = seen_article or match_article(record.text) is not None

    return _SourcePartitions(
        main=main,
        appendices=appendices,
        attached_instruments=attached_instruments,
        table_of_contents=table_of_contents,
    )


_ATTACHED_INSTRUMENT_PREFIXES: tuple[tuple[str, str], ...] = (
    ("QUY CHE", "REGULATION"),
    ("QUY DINH", "REGULATION"),
    ("DIEU LE", "CHARTER"),
    ("CHUAN MUC", "STANDARD"),
)
_ATTACHED_ADOPTION_RE = re.compile(
    r"(?i)\b(?:được\s+)?(?:ban\s+hành\s+)?kèm\s+theo\s+"
    r"(?:luật|nghị\s+định|thông\s+tư|quyết\s+định|nghị\s+quyết)\b"
)


def _match_attached_instrument_heading(
    records: list[LineRecord], index: int
) -> _AttachedInstrumentHeading | None:
    heading = re.sub(r"\s+", " ", records[index].text.strip())
    if not heading or heading != heading.upper():
        return None
    ascii_heading = _ascii(heading).upper()
    matched_kind: str | None = None
    matched_prefix: str | None = None
    for prefix, instrument_kind in _ATTACHED_INSTRUMENT_PREFIXES:
        if ascii_heading == prefix or ascii_heading.startswith(f"{prefix} "):
            matched_kind = instrument_kind
            matched_prefix = prefix
            break
    if matched_kind is None or matched_prefix is None:
        return None

    non_empty_seen = 0
    for lookahead in range(index + 1, min(index + 6, len(records))):
        candidate = records[lookahead].text.strip()
        if not candidate:
            continue
        non_empty_seen += 1
        if _ATTACHED_ADOPTION_RE.search(candidate):
            title = heading[len(matched_prefix) :].strip(" .:-–—") or None
            return _AttachedInstrumentHeading(
                instrument_kind=matched_kind,
                title=title,
                adoption_text=candidate,
                adoption_line_offset=lookahead - index,
            )
        if non_empty_seen >= 3 or match_article(candidate) is not None:
            break
    return None


def _match_appendix_heading(text: str) -> _AppendixHeading | None:
    stripped = re.sub(r"\s+", " ", text.strip())
    prefix = re.fullmatch(r"(?i)phụ\s+lục", stripped)
    if prefix:
        return _AppendixHeading(number=None, title=None)

    match = re.match(r"(?i)^phụ\s+lục(?:\s+số)?\s+(.+)$", stripped)
    if match is None:
        return None
    remainder = match.group(1).strip()
    first_token, _, trailing = remainder.partition(" ")
    token = first_token.rstrip(":.–—-")
    ascii_token = _ascii(token)
    if not re.fullmatch(
        r"(?i)(?:[IVXLCDM]+|\d+[A-Z]*|[A-Z])(?:[./-][A-Z0-9]+)*",
        ascii_token,
    ):
        if stripped != stripped.upper():
            return None
        return _AppendixHeading(number=None, title=remainder)

    has_delimiter = first_token != token
    if trailing and not has_delimiter and trailing != trailing.upper():
        return None
    title = trailing.strip().lstrip(":.–—- ").strip() or None
    return _AppendixHeading(number=token, title=title)


def _appendix_from_records(
    records: list[LineRecord],
    canonical_text: str,
    document: DocumentInfo,
    *,
    source_order: int,
    parse_structure: bool,
) -> Appendix:
    heading_text = records[0].text.strip()
    heading = _match_appendix_heading(heading_text)
    if heading is None:
        raise ValueError(f"Invalid Appendix heading: {heading_text}")
    start = records[0].source_start_char
    end = records[-1].source_end_char
    content_start = (
        records[1].source_start_char if len(records) > 1 else records[0].source_end_char
    )
    content_raw = canonical_text[content_start:end].strip("\n")
    if not content_raw.strip():
        content_raw = heading_text

    scope = _appendix_scope(heading.number, source_order)
    kind = _classify_appendix(heading_text, records[1:])
    hierarchy = _ParsedHierarchy([], [], [], [])
    if parse_structure and kind == "LEGAL_CONTENT":
        hierarchy = _parse_hierarchy(records[1:])
        _validate_unique_point_labels(hierarchy.articles)
        ParsedDocument(
            document=document,
            articles=hierarchy.articles,
            parts=hierarchy.parts,
            sections=hierarchy.sections,
            subsections=hierarchy.subsections,
        )

    hash_input = f"{heading_text}\n{content_raw}".encode("utf-8")
    return Appendix(
        scope=scope,
        number=heading.number,
        heading=heading_text,
        title=heading.title,
        appendix_kind=kind,
        content_raw=content_raw,
        parts=hierarchy.parts,
        sections=hierarchy.sections,
        subsections=hierarchy.subsections,
        articles=hierarchy.articles,
        source_start_char=start,
        source_end_char=end,
        source_start_line=records[0].source_line,
        source_end_line=records[-1].source_line,
        content_hash=hashlib.sha256(hash_input).hexdigest(),
    )


def _attached_instrument_from_records(
    records: list[LineRecord],
    canonical_text: str,
    document: DocumentInfo,
    *,
    source_order: int,
) -> AttachedInstrument:
    heading = _match_attached_instrument_heading(records, 0)
    if heading is None:
        raise ValueError(f"Invalid AttachedInstrument heading: {records[0].text}")

    start = records[0].source_start_char
    end = records[-1].source_end_char
    content_start = (
        records[1].source_start_char if len(records) > 1 else records[0].source_end_char
    )
    content_raw = canonical_text[content_start:end].strip("\n")
    if not content_raw.strip():
        raise ValueError("AttachedInstrument content must not be blank")

    inner_partitions = partition_source_sections(records[1:])
    if inner_partitions.attached_instruments:
        raise ValueError("Nested AttachedInstrument is not supported")
    hierarchy = _parse_hierarchy(inner_partitions.main)
    _validate_unique_point_labels(hierarchy.articles)
    ParsedDocument(
        document=document,
        articles=hierarchy.articles,
        parts=hierarchy.parts,
        sections=hierarchy.sections,
        subsections=hierarchy.subsections,
    )
    if not hierarchy.articles:
        raise ValueError(
            f"AttachedInstrument {records[0].text.strip()} has no Article boundary"
        )

    nested_appendices = [
        _appendix_from_records(
            group,
            canonical_text,
            document,
            source_order=appendix_order,
            parse_structure=True,
        )
        for appendix_order, group in enumerate(inner_partitions.appendices, start=1)
    ]
    scope = f"{heading.instrument_kind.lower()}_{source_order}"
    heading_text = records[0].text.strip()
    hash_input = f"{heading_text}\n{content_raw}".encode("utf-8")
    return AttachedInstrument(
        scope=scope,
        heading=heading_text,
        adoption_text=heading.adoption_text,
        title=heading.title,
        instrument_kind=heading.instrument_kind,
        content_raw=content_raw,
        parts=hierarchy.parts,
        sections=hierarchy.sections,
        subsections=hierarchy.subsections,
        articles=hierarchy.articles,
        appendices=nested_appendices,
        source_start_char=start,
        source_end_char=end,
        source_start_line=records[0].source_line,
        source_end_line=records[-1].source_line,
        content_hash=hashlib.sha256(hash_input).hexdigest(),
    )


def _appendix_scope(number: str | None, source_order: int) -> str:
    if number is None:
        return f"x{source_order}"
    normalized = _ascii(number).lower()
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def _classify_appendix(heading: str, body: list[LineRecord]) -> str:
    normalized = _ascii(heading).lower()
    if re.search(r"\b(?:mau|bieu mau)\b", normalized):
        return "FORM"
    if "danh muc" in normalized:
        return "LIST"
    if re.search(r"\bbang\b", normalized):
        return "TABLE"
    if any(match_article(record.text) is not None for record in body):
        return "LEGAL_CONTENT"
    return "UNCLASSIFIED"


def _is_table_of_contents_heading(text: str) -> bool:
    return bool(re.fullmatch(r"(?i)\s*mục\s+lục\s*", text))


def _table_of_contents_section(
    records: list[LineRecord], canonical_text: str, document_id: str
) -> UnparsedSection:
    heading = records[0].text.strip()
    start = records[0].source_start_char
    end = records[-1].source_end_char
    content_start = (
        records[1].source_start_char if len(records) > 1 else records[0].source_end_char
    )
    content_raw = canonical_text[content_start:end].strip("\n")
    hash_input = f"{heading}\n{content_raw}".encode("utf-8")
    return UnparsedSection(
        section_type="TABLE_OF_CONTENTS",
        heading=heading,
        content_raw=content_raw,
        source_document_id=document_id,
        source_start_char=start,
        source_end_char=end,
        source_start_line=records[0].source_line,
        source_end_line=records[-1].source_line,
        content_hash=hashlib.sha256(hash_input).hexdigest(),
    )


def _records_have_content(records: list[LineRecord]) -> bool:
    return any(record.text.strip() for record in records)


def _unparsed_body_section(
    records: list[LineRecord], canonical_text: str, document_id: str
) -> UnparsedSection:
    if not records:
        raise ValueError("Cannot preserve an empty unparsed body")
    start = records[0].source_start_char
    end = records[-1].source_end_char
    content_raw = canonical_text[start:end].strip("\n")
    return UnparsedSection(
        section_type="UNPARSED_BODY",
        heading=None,
        content_raw=content_raw,
        source_document_id=document_id,
        source_start_char=start,
        source_end_char=end,
        source_start_line=records[0].source_line,
        source_end_line=records[-1].source_line,
        content_hash=hashlib.sha256(content_raw.encode("utf-8")).hexdigest(),
    )


def _validate_unique_point_labels(articles: list[Article]) -> None:
    for article in articles:
        for clause in article.clauses:
            seen: set[str] = set()
            for point in clause.points:
                label = point.label.strip().lower()
                if label in seen:
                    raise ValueError(
                        f"Duplicate Point label {label!r} in Article {article.number}, Clause {clause.number}"
                    )
                seen.add(label)
