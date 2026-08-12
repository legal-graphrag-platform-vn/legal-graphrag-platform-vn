"""Pure HTML and identity parsing for luatvietnam.vn."""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, NavigableString, Tag

from .errors import ContentUnavailableError, ParseError, UnsupportedUrlError
from .models import (
    CrawledDocument,
    DetailMetadata,
    ProviderItemSpan,
    ProviderReferenceMention,
    SearchDocument,
    SearchPageMetadata,
)

ALLOWED_HOSTS = {"luatvietnam.vn", "www.luatvietnam.vn"}
DETAIL_PATH_RE = re.compile(r"-([0-9]{4,})-d(1|5|10)\.html$", re.IGNORECASE)
SOURCE_KIND_BY_DETAIL_VARIANT = {
    "1": "issued_document",
    "5": "consolidated_document",
    "10": "draft_document",
}
NUMBER_RE = re.compile(
    r"\b\d{1,4}(?:/\d{4})?/[A-ZĐƠƯ0-9-]+(?:/[A-ZĐƠƯ0-9-]+)*\b",
    re.IGNORECASE,
)
ARTICLE_RE = re.compile(r"(?im)^\s*Điều\s+\d+[a-zđ]?\b")
CONTENT_NOISE_LINES = {"Đang theo dõi", "Theo dõi văn bản"}
CONTENT_SERIALIZER_VERSION = "luatvietnam-detail-v3"
REFERENCE_SPAN_SELECTOR = "span.noi-dung-tham-chieu"
CONTENT_NOISE_SELECTORS = (
    "script",
    "style",
    "svg",
    "noscript",
    ".tooltip-button",
    ".tooltip-content-1",
    "[data-role='customer-doc-item-follow-button']",
    "[data-role='customer-doc-item-note-button']",
)
BLOCK_TAGS = frozenset(
    {
        "address",
        "article",
        "blockquote",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "header",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "tbody",
        "tfoot",
        "thead",
        "tr",
        "ul",
    }
)
INLINE_TEXT_PARENTS = frozenset(
    {"a", "b", "em", "i", "label", "p", "small", "span", "strong", "td", "th"}
)
CONTENT_UNAVAILABLE_MARKERS = (
    "văn bản này đang cập nhật nội dung",
    "nội dung tóm tắt đang được cập nhật",
    "vui lòng xem nội dung văn bản dưới dạng file pdf",
)

CONTENT_SELECTORS = (
    "#tab-noi-dung",
    "#noi-dung",
    ".the-document-body",
    ".content-document",
    ".law-content",
    ".content1",
    "[data-tab='noi-dung']",
)

LABEL_ALIASES = {
    "so hieu": "number",
    "co quan ban hanh": "issuer_name",
    "so cong bao": "gazette_number",
    "ngay dang cong bao": "gazette_date",
    "loai van ban": "document_type_raw",
    "nguoi ky": "signer",
    "trich yeu": "abstract",
    "ngay ban hanh": "issued_date",
    "ngay co hieu luc": "effective_from",
    "ap dung": "application_raw",
    "ngay het hieu luc": "effective_to",
    "tinh trang hieu luc": "status",
    "trang thai": "status",
    "linh vuc": "fields",
}

MISSING_VALUE_MARKERS = {"", "-", "--", "dang cap nhat"}

DOC_TYPES = (
    ("hiến pháp", "Constitution"),
    ("pháp lệnh", "Ordinance"),
    ("nghị quyết", "Resolution"),
    ("nghị định", "Decree"),
    ("quyết định", "Decision"),
    ("thông tư liên tịch", "JointCircular"),
    ("thông tư", "Circular"),
    ("luật", "Law"),
)


@dataclass(frozen=True, slots=True)
class _SerializedBody:
    text: str
    reference_marker_count: int
    references: tuple["_SerializedReference", ...] = ()


@dataclass(frozen=True, slots=True)
class _SerializedReference:
    citation_text: str
    source_char_start: int
    source_char_end: int
    provider_source_document_id: str | None
    provider_source_item_id: str | None
    provider_target_document_id: str | None
    provider_target_item_ids: tuple[str, ...]
    provider_relation_id: str | None
    provider_link_type: str
    provider_href: str | None


def validate_luatvietnam_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https" or (parts.hostname or "").lower() not in ALLOWED_HOSTS:
        raise UnsupportedUrlError(
            "Only HTTPS URLs on luatvietnam.vn are accepted by this experiment"
        )


def page_url(search_url: str, page_index: int, *, page_size: int | None = None) -> str:
    validate_luatvietnam_url(search_url)
    if page_index < 1:
        raise ValueError("page_index must be at least 1")
    parts = urlsplit(search_url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    if page_size is not None and page_size < 1:
        raise ValueError("page_size must be at least 1")
    output: list[tuple[str, str]] = []
    replaced = False
    for key, value in pairs:
        normalized_key = key.lower()
        if normalized_key == "pageindex":
            if not replaced:
                output.append((key, str(page_index)))
                replaced = True
            continue
        if page_size is not None and normalized_key in {"pagesize", "pagsize"}:
            continue
        output.append((key, value))
    if not replaced:
        output.append(("PageIndex", str(page_index)))
    if page_size is not None:
        output.extend((key, str(page_size)) for key in ("PageSize", "PagSize"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(output), ""))


def parse_search_page_metadata(html: str) -> SearchPageMetadata | None:
    soup = BeautifulSoup(html, "lxml")
    summary = soup.select_one("#search_results .block-text-resut .s-text1")
    selected = soup.select_one(".pagination .pag-select option[selected]")
    active = soup.select_one(".pagination .page-numbers.active")
    if not isinstance(summary, Tag) or not isinstance(selected, Tag):
        return None

    summary_raw = _clean_text(summary.get_text(" ", strip=True))
    total_match = re.search(r"\bCó\s+([\d.,]+)\s+văn bản\b", summary_raw)
    page_size_match = re.search(r"(\d+)\s+kết quả", selected.get_text(" ", strip=True))
    if not total_match or not page_size_match:
        return None
    total_results = int(re.sub(r"\D", "", total_match.group(1)))
    page_size = int(page_size_match.group(1))
    if page_size < 1:
        return None
    selected_url = str(selected.get("data-url") or selected.get("value") or "")
    if selected_url:
        selected_params = dict(
            parse_qsl(urlsplit(selected_url).query, keep_blank_values=True)
        )
        for key in ("PageSize", "PagSize"):
            if key in selected_params and selected_params[key] != str(page_size):
                raise ParseError(
                    f"Selected {key}={selected_params[key]!r} does not match "
                    f"page size {page_size}"
                )
    total_pages = max(1, (total_results + page_size - 1) // page_size)

    current_page = 1
    if isinstance(active, Tag):
        active_match = re.search(
            r"\d+", str(active.get("title") or active.get_text(" ", strip=True))
        )
        if active_match:
            current_page = int(active_match.group(0))

    visible_page_set: set[int] = set()
    for element in soup.select(".pagination .page-numbers[title]"):
        match = re.search(r"Trang\s+(\d+)", str(element.get("title") or ""))
        if not match:
            continue
        title_page = int(match.group(1))
        visible_page_set.add(title_page)
        href = str(element.get("href") or "")
        if not href:
            continue
        params = dict(parse_qsl(urlsplit(href).query, keep_blank_values=True))
        href_page = params.get("PageIndex")
        if href_page is not None and href_page != str(title_page):
            raise ParseError(
                f"Pagination title page {title_page} does not match "
                f"PageIndex={href_page!r}"
            )
        href_size = params.get("PageSize")
        if href_size is not None and href_size != str(page_size):
            raise ParseError(
                f"Pagination PageSize={href_size!r} does not match selected "
                f"page size {page_size}"
            )
    visible_pages = sorted(visible_page_set)
    next_page = current_page + 1 if current_page < total_pages else None
    return SearchPageMetadata(
        total_results=total_results,
        page_size=page_size,
        current_page=current_page,
        total_pages=total_pages,
        visible_page_indexes=tuple(visible_pages),
        next_page=next_page,
        document_types=_summary_values(summary_raw, "loại văn bản", "cơ quan ban hành"),
        issuers_raw=_summary_segment(summary_raw, "cơ quan ban hành", "lĩnh vực"),
        fields=_summary_values(summary_raw, "lĩnh vực", "ngôn ngữ"),
        language=_summary_scalar(summary_raw, "ngôn ngữ"),
        summary_raw=summary_raw,
    )


def parse_search_results(html: str, base_url: str) -> list[SearchDocument]:
    validate_luatvietnam_url(base_url)
    soup = BeautifulSoup(html, "lxml")
    results: list[SearchDocument] = []
    seen: set[str] = set()
    for card in soup.select("article.art-search"):
        anchor = card.select_one(".doc-title a[href]")
        if not isinstance(anchor, Tag):
            continue
        href = urljoin(base_url, str(anchor["href"]))
        parts = urlsplit(href)
        if (parts.hostname or "").lower() not in ALLOWED_HOSTS:
            continue
        match = DETAIL_PATH_RE.search(parts.path)
        if not match or "/van-ban/tim-van-ban" in parts.path:
            continue
        canonical_url = urlunsplit(("https", parts.netloc, parts.path, "", ""))
        if canonical_url in seen:
            continue
        title = _clean_text(anchor.get_text(" ", strip=True))
        if not title:
            title = _clean_text(str(anchor.get("title") or ""))
        if not title:
            continue
        seen.add(canonical_url)
        results.append(
            SearchDocument(
                title=title,
                url=canonical_url,
                external_id=match.group(1),
                detail_variant=f"d{match.group(2)}",
                source_kind=SOURCE_KIND_BY_DETAIL_VARIANT[match.group(2)],
            )
        )
    return results


def parse_document(
    html: str,
    source_url: str,
    *,
    metadata: DetailMetadata | None = None,
) -> CrawledDocument:
    validate_luatvietnam_url(source_url)
    metadata = metadata or parse_detail_metadata(html, source_url)
    soup = BeautifulSoup(html, "lxml")

    body = _document_body(soup)
    source_text = body.text
    if _body_is_unavailable(source_text):
        raise ContentUnavailableError(
            f"LuatVietnam has not published HTML full text for this document: {source_url}"
        )
    if not source_text:
        raise ParseError(f"Legal body not found: {source_url}")
    for reference in body.references:
        if (
            reference.provider_source_document_id is not None
            and reference.provider_source_document_id != metadata.external_id
        ):
            raise ParseError(
                "Provider reference source document conflicts with detail page"
            )

    raw_doc_code = f"LTV_{metadata.external_id}"
    return CrawledDocument(
        raw_doc_code=raw_doc_code,
        candidate_graph_id=_candidate_graph_id(
            metadata.doc_type, metadata.number, metadata.external_id
        ),
        external_id=metadata.external_id,
        title=metadata.title,
        number=metadata.number,
        doc_type=metadata.doc_type,
        normative=True,
        issuer_name=metadata.issuer_name,
        issuer_branch=metadata.issuer_branch,
        issued_date=metadata.issued_date,
        effective_from=metadata.effective_from,
        effective_to=metadata.effective_to,
        status=metadata.status_raw,
        legal_status=metadata.legal_status,
        source_url=source_url,
        source_text=source_text,
        article_count=len(ARTICLE_RE.findall(source_text)),
        reference_marker_count=body.reference_marker_count,
        content_serializer_version=CONTENT_SERIALIZER_VERSION,
        provider_references=tuple(
            ProviderReferenceMention(
                provider_source_document_id=metadata.external_id,
                provider_source_item_id=reference.provider_source_item_id,
                provider_target_document_id=reference.provider_target_document_id,
                provider_target_item_ids=reference.provider_target_item_ids,
                provider_relation_id=reference.provider_relation_id,
                provider_link_type=reference.provider_link_type,  # type: ignore[arg-type]
                citation_text=reference.citation_text,
                source_char_start=reference.source_char_start,
                source_char_end=reference.source_char_end,
                provider_href=reference.provider_href,
            )
            for reference in body.references
        ),
    )


def parse_detail_metadata(html: str, source_url: str) -> DetailMetadata:
    """Extract detail-page metadata without requiring a complete legal body."""
    validate_luatvietnam_url(source_url)
    external_id = _external_id(source_url)
    soup = BeautifulSoup(html, "lxml")
    title = _first_text(soup, (".the-document-title", "h1", ".law-title"))
    if not title:
        raise ParseError(f"Document title not found: {source_url}")

    fields = _metadata_fields(soup)
    number = _field_text(fields, "number") or _number_from_text(title)
    if not number:
        raise ParseError(f"Document number not found: {source_url}")
    doc_type = infer_doc_type(title, number)
    issuer_name = _present_value(_field_text(fields, "issuer_name"))
    application_raw = _field_text(fields, "application_raw")
    effective_raw = _field_text(fields, "effective_from") or application_raw
    effective_to_raw = _field_text(fields, "effective_to")
    status_raw = _field_text(fields, "status")
    gazette_number_raw = _field_text(fields, "gazette_number")
    gazette_date_raw = _field_text(fields, "gazette_date")
    body = (
        _SerializedBody(text="", reference_marker_count=0)
        if is_not_approved_status(status_raw)
        else _document_body(soup)
    )
    html_full_text_available = bool(body.text) and not _body_is_unavailable(body.text)

    return DetailMetadata(
        external_id=external_id,
        title=title,
        number=number,
        document_type_raw=_present_value(_field_text(fields, "document_type_raw")),
        doc_type=doc_type,
        issuer_name=issuer_name,
        issuer_branch=infer_issuer_branch(issuer_name),
        signer=_present_value(_field_text(fields, "signer")),
        abstract=_present_value(_field_text(fields, "abstract")),
        issued_date=_parse_date(_field_text(fields, "issued_date"), strict=False),
        application_raw=application_raw,
        effective_from=_parse_date(effective_raw, strict=False),
        effective_to_raw=effective_to_raw,
        effective_to=_parse_date(effective_to_raw, strict=False),
        status_raw=status_raw,
        legal_status=infer_legal_status(status_raw),
        gazette_number_raw=gazette_number_raw,
        gazette_number=_present_value(gazette_number_raw),
        gazette_date_raw=gazette_date_raw,
        gazette_date=_parse_date(gazette_date_raw, strict=False),
        fields=_field_tuple(fields, "fields_list"),
        page_updated_at=_page_updated_at(soup),
        og_url=_meta_content(soup, "og:url"),
        og_title=_meta_content(soup, "og:title"),
        og_description=_meta_content(soup, "og:description"),
        og_image=_meta_content(soup, "og:image"),
        html_full_text_available=html_full_text_available,
        article_count=(
            len(ARTICLE_RE.findall(body.text)) if html_full_text_available else 0
        ),
        content_character_count=len(body.text) if html_full_text_available else 0,
        reference_marker_count=body.reference_marker_count,
        content_serializer_version=CONTENT_SERIALIZER_VERSION,
        source_url=source_url,
    )


def infer_doc_type(title: str, number: str) -> str:
    normalized_title = title.lower()
    for label, doc_type in DOC_TYPES:
        if label in normalized_title:
            return doc_type
    suffix = _ascii(number).upper().split("/")[-1]
    if suffix.startswith("ND-"):
        return "Decree"
    if suffix.startswith("TTLT-"):
        return "JointCircular"
    if suffix.startswith("TT-"):
        return "Circular"
    if suffix.startswith("QD-"):
        return "Decision"
    if suffix.startswith("NQ-"):
        return "Resolution"
    if suffix.startswith("QH"):
        return "Law"
    raise ParseError(f"Unsupported document type for {title!r} ({number})")


def infer_issuer_branch(issuer_name: str | None) -> str:
    value = _ascii(issuer_name or "").lower()
    if "quoc hoi" in value or "uy ban thuong vu quoc hoi" in value:
        return "LEGISLATIVE"
    if "toa an" in value or "vien kiem sat" in value:
        return "JUDICIAL"
    executive_tokens = ("chinh phu", "thu tuong", "bo ", "uy ban nhan dan")
    if any(token in value for token in executive_tokens):
        return "EXECUTIVE"
    return "OTHER"


def infer_legal_status(status: str | None) -> str | None:
    value = _ascii(status or "").lower().strip()
    mappings = (
        ("het hieu luc mot phan", "PARTIALLY_EFFECTIVE"),
        ("het hieu luc", "EXPIRED"),
        ("chua co hieu luc", "NOT_YET_EFFECTIVE"),
        ("bi thay the", "REPLACED"),
        ("bi bai bo", "REPEALED"),
        ("con hieu luc", "ACTIVE"),
    )
    return next((mapped for token, mapped in mappings if token in value), None)


def is_not_approved_status(status: str | None) -> bool:
    """Return whether a draft is explicitly marked as not approved."""
    return "chua thong qua" in _ascii(status or "").lower()


def _metadata_fields(soup: BeautifulSoup) -> dict[str, object]:
    fields: dict[str, object] = {}
    for row in soup.select(".div-table table tr, table tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        for index in range(0, len(cells) - 1, 2):
            label = _metadata_label(cells[index])
            key = LABEL_ALIASES.get(label)
            if not key:
                continue
            value_cell = cells[index + 1]
            value = _cell_text(value_cell)
            if value:
                fields.setdefault(key, value)
            if key == "fields":
                tags = tuple(
                    text
                    for anchor in value_cell.select("a")
                    if (text := _clean_text(anchor.get_text(" ", strip=True)))
                )
                if tags:
                    fields.setdefault("fields_list", tags)

    # Compatibility with simpler list/div layouts used by older pages and tests.
    for row in soup.find_all(["li", "div"]):
        direct_children = [
            child for child in row.find_all(recursive=False) if isinstance(child, Tag)
        ]
        if len(direct_children) < 2:
            continue
        key = LABEL_ALIASES.get(_metadata_label(direct_children[0]))
        if key and (value := _cell_text(direct_children[1])):
            fields.setdefault(key, value)
    return fields


def _metadata_label(cell: Tag) -> str:
    label_node = cell.find("strong") or cell
    return _ascii(_cell_text(label_node)).lower().rstrip(":").strip()


def _cell_text(cell: Tag) -> str:
    fragment = BeautifulSoup(str(cell), "lxml")
    for noise in fragment.select(".tooltip-content-1, svg, script, style"):
        noise.decompose()
    return _clean_text(fragment.get_text(" ", strip=True))


def _document_text(soup: BeautifulSoup) -> str:
    """Compatibility wrapper for callers that only need canonical text."""
    return _document_body(soup).text


def parse_provider_item_spans(
    html: str, source_text: str, provider_item_ids: tuple[str, ...]
) -> tuple[ProviderItemSpan, ...]:
    """Map selected provider item IDs onto exact canonical source coordinates.

    Mapping is deliberately fail-closed: the complete HTML serialization must
    equal ``source_text`` and each selected item body must occur exactly once.
    Missing or ambiguous items are omitted for the caller to keep unresolved.
    """

    canonical_source = source_text.rstrip("\n")
    soup = BeautifulSoup(html, "lxml")
    if _document_body(soup).text != canonical_source:
        raise ParseError("Provider HTML does not match canonical source text")

    spans: list[ProviderItemSpan] = []
    for item_id in dict.fromkeys(provider_item_ids):
        if not item_id.isdigit():
            continue
        element = soup.find(id=re.compile(rf"^demuc{re.escape(item_id)}$", re.I))
        if not isinstance(element, Tag):
            continue
        item_text = _serialize_content_element(element).text
        if not item_text or canonical_source.count(item_text) != 1:
            continue
        start = canonical_source.index(item_text)
        spans.append(
            ProviderItemSpan(
                provider_item_id=item_id,
                source_char_start=start,
                source_char_end=start + len(item_text),
            )
        )
    return tuple(spans)


def _body_is_unavailable(text: str) -> bool:
    return (
        bool(text)
        and not ARTICLE_RE.search(text)
        and len(text) < 500
        and any(marker in text.lower() for marker in CONTENT_UNAVAILABLE_MARKERS)
    )


def _document_body(soup: BeautifulSoup) -> _SerializedBody:
    candidates: list[_SerializedBody] = []
    for selector in CONTENT_SELECTORS:
        for element in soup.select(selector):
            if "doc-summary" in (element.get("class") or []):
                continue
            serialized = _serialize_content_element(element)
            text = serialized.text
            if text:
                candidates.append(serialized)
    if not candidates:
        return _SerializedBody(text="", reference_marker_count=0)
    legal_candidates = [item for item in candidates if ARTICLE_RE.search(item.text)]
    return max(legal_candidates or candidates, key=lambda item: len(item.text))


def _serialize_content_element(element: Tag) -> _SerializedBody:
    fragment = BeautifulSoup(str(element), "lxml")
    root = fragment.body or fragment
    for noise in root.select(", ".join(CONTENT_NOISE_SELECTORS)):
        noise.decompose()

    pending_references: list[dict[str, object]] = []
    for index, reference in enumerate(root.select(REFERENCE_SPAN_SELECTOR)):
        text = _clean_text(reference.get_text(" ", strip=True))
        if not text:
            reference.decompose()
            continue
        marker = text if text.startswith("[") and text.endswith("]") else f"[{text}]"
        token = f"LTVREFTOKEN{index:08d}{uuid.uuid4().hex}"
        href = str(reference.get("data-href") or "") or None
        query = {
            key.lower(): value for key, value in parse_qsl(urlsplit(href or "").query)
        }
        source_container = reference.find_parent(
            id=re.compile(r"^demuc\d+$", re.IGNORECASE)
        )
        container_source_item_id = None
        if source_container is not None:
            container_source_item_id = re.sub(
                r"^demuc", "", str(source_container.get("id")), flags=re.IGNORECASE
            )
        href_source_item_id = query.get("docitemreferenceid")
        if (
            href_source_item_id
            and container_source_item_id
            and href_source_item_id != container_source_item_id
        ):
            raise ParseError(
                "Provider reference source item conflicts with containing demuc"
            )
        source_item_id = href_source_item_id or container_source_item_id
        raw_target_items = query.get("docitemids") or query.get("docitemid") or ""
        target_item_ids = tuple(
            item.strip() for item in raw_target_items.split(",") if item.strip()
        )
        if "docitemrelateid_select" in query:
            link_type = "CHANGE_CONTENT"
            relation_id = query["docitemrelateid_select"]
        elif "docitemrelateid" in query:
            link_type = "CHANGE_CONTENT"
            relation_id = query["docitemrelateid"]
        elif "docitemreferid" in query:
            link_type = "REFERENCE"
            relation_id = query["docitemreferid"]
        else:
            link_type = "UNKNOWN"
            relation_id = None
        pending_references.append(
            {
                "token": token,
                "marker": marker,
                "citation_text": text.strip("[]"),
                "provider_source_document_id": query.get("docreferenceid"),
                "provider_source_item_id": source_item_id,
                "provider_target_document_id": query.get("docid"),
                "provider_target_item_ids": target_item_ids,
                "provider_relation_id": relation_id,
                "provider_link_type": link_type,
                "provider_href": href,
            }
        )
        reference.replace_with(NavigableString(token))

    serialized_text = _clean_multiline(_render_content_node(root))
    resolved_references: list[_SerializedReference] = []
    for pending in pending_references:
        token = str(pending["token"])
        marker = str(pending["marker"])
        start = serialized_text.find(token)
        if start < 0:
            raise ParseError("Serialized reference token was lost during normalization")
        serialized_text = (
            serialized_text[:start] + marker + serialized_text[start + len(token) :]
        )
        resolved_references.append(
            _SerializedReference(
                citation_text=str(pending["citation_text"]),
                source_char_start=start,
                source_char_end=start + len(marker),
                provider_source_document_id=pending["provider_source_document_id"],  # type: ignore[arg-type]
                provider_source_item_id=pending["provider_source_item_id"],  # type: ignore[arg-type]
                provider_target_document_id=pending["provider_target_document_id"],  # type: ignore[arg-type]
                provider_target_item_ids=pending["provider_target_item_ids"],  # type: ignore[arg-type]
                provider_relation_id=pending["provider_relation_id"],  # type: ignore[arg-type]
                provider_link_type=str(pending["provider_link_type"]),
                provider_href=pending["provider_href"],  # type: ignore[arg-type]
            )
        )

    return _SerializedBody(
        text=serialized_text,
        reference_marker_count=len(resolved_references),
        references=tuple(resolved_references),
    )


def _render_content_node(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        value = str(node)
        parent_name = node.parent.name if isinstance(node.parent, Tag) else None
        if parent_name in INLINE_TEXT_PARENTS:
            leading_space = bool(value[:1].isspace())
            trailing_space = bool(value[-1:].isspace())
            value = re.sub(r"\s+", " ", value).strip()
            if not value:
                return " " if leading_space or trailing_space else ""
            return (
                (" " if leading_space else "") + value + (" " if trailing_space else "")
            )
        return value
    if node.name == "br":
        return "\n"
    rendered = "".join(_render_content_node(child) for child in node.children)
    if node.name in {"td", "th"}:
        return f"{rendered}\t"
    if node.name in BLOCK_TAGS:
        return f"\n{rendered}\n"
    return rendered


def _external_id(url: str) -> str:
    match = DETAIL_PATH_RE.search(urlsplit(url).path)
    if not match:
        raise ParseError(
            f"Cannot derive stable LuatVietnam document ID from URL: {url}"
        )
    return match.group(1)


def _number_from_text(text: str) -> str | None:
    match = NUMBER_RE.search(text)
    return match.group(0) if match else None


def _parse_date(value: str | None, *, strict: bool = True) -> date | None:
    if not value or _ascii(value).lower().strip() in MISSING_VALUE_MARKERS:
        return None
    match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", value)
    if not match:
        if not strict:
            return None
        raise ParseError(f"Unsupported Vietnamese date: {value!r}")
    day, month, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise ParseError(f"Invalid Vietnamese date: {value!r}") from exc


def _present_value(value: str | None) -> str | None:
    if value is None or _ascii(value).lower().strip() in MISSING_VALUE_MARKERS:
        return None
    return value


def _field_text(fields: dict[str, object], key: str) -> str | None:
    value = fields.get(key)
    return value if isinstance(value, str) else None


def _field_tuple(fields: dict[str, object], key: str) -> tuple[str, ...]:
    value = fields.get(key)
    if isinstance(value, tuple) and all(isinstance(item, str) for item in value):
        return value
    return ()


def _page_updated_at(soup: BeautifulSoup) -> datetime | None:
    note = _first_text(soup, (".note-download",))
    if not note:
        return None
    match = re.search(
        r"(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{1,2}):(\d{2})\s*\(GMT([+-]\d{1,2})\)",
        note,
        re.IGNORECASE,
    )
    if not match:
        return None
    day, month, year, hour, minute, offset = (int(part) for part in match.groups())
    try:
        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            tzinfo=timezone(timedelta(hours=offset)),
        )
    except ValueError:
        return None


def _meta_content(soup: BeautifulSoup, property_name: str) -> str | None:
    element = soup.find("meta", attrs={"property": property_name})
    if not isinstance(element, Tag):
        return None
    return _present_value(_clean_text(str(element.get("content") or "")))


def _summary_values(text: str, label: str, next_label: str) -> tuple[str, ...]:
    segment = _summary_segment(text, label, next_label)
    if not segment:
        return ()
    return tuple(value.strip() for value in segment.split(",") if value.strip())


def _summary_segment(text: str, label: str, next_label: str) -> str | None:
    match = re.search(
        rf";\s*{re.escape(label)}\s*:\s*(.*?)\s*;\s*{re.escape(next_label)}\s*:",
        text,
        re.IGNORECASE,
    )
    return _present_value(match.group(1).strip()) if match else None


def _summary_scalar(text: str, label: str) -> str | None:
    match = re.search(
        rf";\s*{re.escape(label)}\s*:\s*(.*?)(?:\s*;|$)", text, re.IGNORECASE
    )
    return _present_value(match.group(1).strip()) if match else None


def _candidate_graph_id(doc_type: str, number: str, external_id: str) -> str:
    prefix = {
        "Constitution": "hp",
        "Law": "l",
        "Ordinance": "pl",
        "Resolution": "nq",
        "Decree": "nd",
        "Decision": "qd",
        "Circular": "tt",
        "JointCircular": "ttlt",
    }[doc_type]
    numbers = re.findall(r"\d+", number)
    if len(numbers) >= 2:
        return f"{prefix}_{numbers[0]}_{numbers[1]}"
    return f"ltv_{external_id}"


def _first_text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str | None:
    for selector in selectors:
        if element := soup.select_one(selector):
            if text := _clean_text(element.get_text(" ", strip=True)):
                return text
    return None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_multiline(value: str) -> str:
    lines = [_clean_text(line) for line in value.splitlines()]
    return "\n".join(line for line in lines if line and line not in CONTENT_NOISE_LINES)


def _ascii(value: str) -> str:
    decomposed = unicodedata.normalize("NFD", value)
    no_marks = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return no_marks.replace("đ", "d").replace("Đ", "D")
