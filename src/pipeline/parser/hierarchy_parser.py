"""Hierarchy Parser — Phân tích và cấu trúc hóa văn bản pháp luật VN -> ParsedDocument phân cấp.

State machine thuần text (`parse_lines`) xử lý phân tách cấu trúc Chương/Điều/Khoản/Điểm.
"""

from __future__ import annotations

import logging
import re
import hashlib
import unicodedata
from dataclasses import dataclass, field

from src.pipeline.parser.models import (
    Article,
    Clause,
    DocumentInfo,
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
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn").replace("đ", "d").replace("Đ", "D")


CITATION_PREV_RE = re.compile(
    r"(?:quy\s+dinh\s+tai|sua\s+doi[,\s]+bo\s+sung|thong\s+nhat\s+voi|theo|tai|theo\s+quy\s+dinh|khoan\s+\d+|diem\s+[a-z]|vao|hoac|va|bai\s+bo|,)\s*$",
    re.IGNORECASE,
)
CITATION_NEXT_RE = re.compile(
    r"^(?:va|hoac|,|nhu\s+sau|cua|nghi\s+dinh|luat|phu\s+luc|\.)",
    re.IGNORECASE,
)
CLOSING_ARTICLE_TITLE_RE = re.compile(r"(?:thi\s+hanh|chuyen\s+tiep)", re.IGNORECASE)
APPENDIX_HEADING_RE = re.compile(
    r"^\s*(?:danh\s*muc|phu\s*luc|mau\s*so|bieu\s*mau)(?:\s+[ivxlcdm\d]+)?(?:\s*[:.\-].*)?$",
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


def parse_lines(lines: list[str] | list[LineRecord]) -> list[Article]:
    """Compatibility wrapper returning only parsed Articles."""
    return _parse_hierarchy(lines).articles


def _parse_hierarchy(lines: list[str] | list[LineRecord]) -> _ParsedHierarchy:
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
    seen_closing_article = False
    in_appendix = False

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
            elif duplicate.content.strip() != current_point.content.strip():
                raise ValueError(
                    f"Duplicate Point label {current_point.label!r} with different content "
                    f"in Clause {current_clause.number}"
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
        if current_subsection is not None and subsection_article_count == 0:
            raise ValueError(
                f"Subsection {current_subsection.number} in Section "
                f"{current_subsection.section} does not contain any Article"
            )

    def require_current_section_has_article() -> None:
        if current_section is not None and section_article_count == 0:
            raise ValueError(
                f"Section {current_section.number} in Chapter "
                f"{current_section.chapter} does not contain any Article"
            )

    def require_current_chapter_has_article() -> None:
        if current_chapter is not None and chapter_article_count == 0:
            raise ValueError(f"Chapter {current_chapter} does not contain any Article")

    def require_current_part_has_article() -> None:
        if current_part is not None and part_article_count == 0:
            raise ValueError(f"Part {current_part.number} does not contain any Article")

    pending_chapter_title = False
    pending_heading: tuple[str, str, LineRecord] | None = None
    quote_depth = 0
    raw_text_lines = [
        item.text if isinstance(item, LineRecord) else str(item) for item in lines
    ]

    for idx, item in enumerate(lines):
        record = item if isinstance(item, LineRecord) else LineRecord(text=item)
        line = clean_vietnamese_spacing(record.text).strip()
        if not line or should_skip_line(line):
            continue

        asc_line = _ascii(line).strip().lower()
        if seen_closing_article and APPENDIX_HEADING_RE.match(asc_line):
            in_appendix = True
        prev_line = raw_text_lines[idx - 1] if idx > 0 else ""
        next_line = raw_text_lines[idx + 1] if idx < len(raw_text_lines) - 1 else ""

        in_quote = quote_depth > 0 or line.startswith("“")
        quote_depth = max(0, quote_depth + line.count("“") - line.count("”"))

        if in_quote:
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
                raise ValueError(f"{kind} {number} is missing a valid title")
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
                    chapter=current_chapter or "",
                    source_start_char=heading_record.source_start_char,
                    source_end_char=record.source_end_char,
                )
                sections.append(current_section)
            else:
                current_subsection = Subsection(
                    number=number,
                    title=line,
                    part=current_part.number if current_part else None,
                    chapter=current_chapter or "",
                    section=current_section.number if current_section else "",
                    source_start_char=heading_record.source_start_char,
                    source_end_char=record.source_end_char,
                )
                subsections.append(current_subsection)
            pending_heading = None
            continue

        part_match = match_part(line)
        if part_match is not None and not in_appendix:
            flush_article()
            seen_closing_article = False
            require_current_subsection_has_article()
            require_current_section_has_article()
            if current_chapter is not None and chapter_article_count == 0:
                # 1. Bỏ qua Chương rỗng khi chuyển Phần do Mục lục
                pass
            else:
                require_current_chapter_has_article()
            if current_part is not None and part_article_count == 0:
                # 1. Bỏ qua Phần rỗng (do Mục lục hoặc tiêu đề trùng) thay vì văng lỗi
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

        chapter_num = match_chapter(line)
        if chapter_num is not None and not in_appendix:
            flush_article()
            seen_closing_article = False
            require_current_subsection_has_article()
            require_current_section_has_article()
            if current_chapter is not None and chapter_article_count == 0:
                # 1. Bỏ qua Chương rỗng do Mục lục hoặc tiêu đề trùng
                pass
            else:
                require_current_chapter_has_article()
            expected_root_mode = "Part" if current_part is not None else "Chapter"
            document_mode = require_mode(
                document_mode, expected_root_mode, owner="Document"
            )
            current_chapter = chapter_num
            current_chapter_title = None
            current_section = None
            current_subsection = None
            chapter_article_count = 0
            section_article_count = 0
            subsection_article_count = 0
            pending_chapter_title = True
            continue

        if pending_chapter_title:
            pending_chapter_title = False
            if looks_like_title(line):
                current_chapter_title = line
                continue

        section_match = match_section(line)
        if section_match is not None and not in_appendix:
            if current_chapter is None:
                # 1. Báo lỗi nếu Mục xuất hiện khi chưa khai báo Chương nào
                raise ValueError(
                    f"Section {section_match[0]} appears before any Chapter"
                )
            flush_article()
            require_current_subsection_has_article()
            require_current_section_has_article()
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
        if subsection_match is not None and not in_appendix:
            if current_section is None or current_chapter is None:
                raise ValueError(
                    f"Subsection {subsection_match[0]} appears before any Section"
                )
            flush_article()
            require_current_subsection_has_article()
            section_key = (
                current_part.number if current_part else None,
                current_chapter,
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
        if (
            article_match is not None
            and not in_appendix
            and not is_citation_context(prev_line, line, next_line)
        ):
            flush_article()
            if article_match[1] and CLOSING_ARTICLE_TITLE_RE.search(
                _ascii(article_match[1])
            ):
                seen_closing_article = True
            if current_chapter is None:
                if current_part is not None:
                    # 1. Tự động tạo Chapter ngầm '0' nếu Phần chứa Điều trực tiếp không qua Chương
                    current_chapter = "0"
                    current_chapter_title = ""
                else:
                    document_mode = require_mode(document_mode, "Article", owner="Document")
            elif current_section is None:
                chapter_key = (
                    current_part.number if current_part else None,
                    current_chapter,
                )
                chapter_modes[chapter_key] = require_mode(
                    chapter_modes.get(chapter_key),
                    "Article",
                    owner=f"Chapter {current_chapter}",
                )
            else:
                section_key = (
                    current_part.number if current_part else None,
                    current_chapter,
                    current_section.number,
                )
                mode = "Subsection" if current_subsection is not None else "Article"
                section_modes[section_key] = require_mode(
                    section_modes.get(section_key),
                    mode,
                    owner=f"Section {current_section.number}",
                )

            number, title = article_match
            current_article = _ArticleBuilder(
                number=number,
                title=title or None,
                part=current_part.number if current_part else None,
                chapter=current_chapter,
                chapter_title=current_chapter_title,
                section=current_section.number if current_section else None,
                subsection=(current_subsection.number if current_subsection else None),
                source_start_char=record.source_start_char,
                source_end_char=record.source_end_char,
            )
            if current_part is not None:
                part_article_count += 1
            if current_chapter is not None:
                chapter_article_count += 1
            if current_section is not None:
                section_article_count += 1
            if current_subsection is not None:
                subsection_article_count += 1
            if title:
                current_article.content_lines.append(title)
            continue

        if current_article is None:
            logger.debug("Bỏ qua dòng ngoài cấu trúc Điều: %r", line)
            continue

        clause_match = match_clause(line)
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
    records = source_line_records(canonical_text)
    main_records, appendix_groups = partition_appendices(records)
    hierarchy = _parse_hierarchy(main_records)
    articles = hierarchy.articles
    _validate_unique_point_labels(articles)
    return ParsedDocument(
        document=document,
        articles=articles,
        parts=hierarchy.parts,
        sections=hierarchy.sections,
        subsections=hierarchy.subsections,
        unparsed_sections=[
            _appendix_section(group, canonical_text, document.id)
            for group in appendix_groups
        ],
    )


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


def partition_appendices(
    records: list[LineRecord],
) -> tuple[list[LineRecord], list[list[LineRecord]]]:
    main: list[LineRecord] = []
    appendices: list[list[LineRecord]] = []
    current: list[LineRecord] | None = None
    for record in records:
        if _is_appendix_heading(record.text):
            current = [record]
            appendices.append(current)
        elif current is None:
            main.append(record)
        else:
            current.append(record)
    return main, appendices


def _is_appendix_heading(text: str) -> bool:
    stripped = re.sub(r"\s+", " ", text.strip())
    if not re.match(r"(?i)^phụ lục(?:\s+.*)?$", stripped):
        return False
    return stripped.upper() == stripped or bool(
        re.fullmatch(
            r"(?i)phụ lục(?:\s+(?:số\s+)?(?:[IVXLCDM]+|\d+[A-Z]?|[A-Z]))?", stripped
        )
    )


def _appendix_section(
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
        section_type="APPENDIX",
        heading=heading,
        content_raw=content_raw,
        source_document_id=document_id,
        source_start_char=start,
        source_end_char=end,
        source_start_line=records[0].source_line,
        source_end_line=records[-1].source_line,
        content_hash=hashlib.sha256(hash_input).hexdigest(),
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
