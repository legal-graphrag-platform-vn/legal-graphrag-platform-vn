"""Resolve LuatVietnam provider IDs to existing canonical corpus identities."""

from __future__ import annotations

import json
import re
from pathlib import Path

from experiments.luatvietnam_crawler.errors import ParseError
from experiments.luatvietnam_crawler.parser import parse_provider_item_spans

from src.pipeline.extraction.provider_references import ProviderReferenceMentionV1
from src.pipeline.extraction.provider_relation_candidates import (
    ProviderDocumentIndex,
    ProviderDocumentNumberIndex,
    ProviderFailureIndex,
    ProviderUnitIndex,
)
from src.pipeline.extraction.structural_context import StructuralRegistry
from src.pipeline.parser.models import ParsedDocument
from src.shared.ontology.hierarchy import (
    normalize_part_number,
    normalize_subsection_number,
)


def build_luatvietnam_identity_indexes(
    raw_root: Path,
    processed_root: Path,
    current_parsed: ParsedDocument,
    references: tuple[ProviderReferenceMentionV1, ...],
) -> tuple[
    ProviderDocumentIndex,
    ProviderDocumentNumberIndex,
    ProviderUnitIndex,
    ProviderFailureIndex,
]:
    """Build indexes only from corpus documents and hierarchy artifacts that exist.

    No target node is synthesized from an href. A raw document can resolve at
    Document level, while provider item resolution additionally requires its
    parsed ``hierarchy.json`` and HTML-to-source alignment.
    """

    provider_document_ids = {
        value
        for reference in references
        for value in (
            reference.provider_source_document_id,
            reference.provider_target_document_id,
        )
        if value
    }
    requested_items: dict[str, set[str]] = {}
    for reference in references:
        if reference.provider_target_document_id:
            requested_items.setdefault(
                reference.provider_target_document_id, set()
            ).update(reference.provider_target_item_ids)

    document_index: dict[tuple[str, str], str] = {}
    document_number_index: dict[tuple[str, str], str] = {}
    unit_index: dict[tuple[str, str, str], tuple[str, str]] = {}
    failure_index: dict[tuple[str, str, str | None], str] = {}
    current_provider_id = (
        references[0].provider_source_document_id if references else None
    )

    for provider_document_id in sorted(provider_document_ids):
        raw_dir = raw_root / f"LTV_{provider_document_id}"
        metadata_path = raw_dir / "metadata.json"
        if not metadata_path.is_file():
            continue
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if str(metadata.get("external_id") or "") != provider_document_id:
            continue

        parsed = _load_parsed_document(
            processed_root,
            provider_document_id,
            current_parsed if provider_document_id == current_provider_id else None,
        )
        graph_id = (
            parsed.document.id
            if parsed is not None
            else metadata.get("graph_id") or metadata.get("candidate_graph_id")
        )
        if not graph_id:
            continue
        document_index[("luatvietnam", provider_document_id)] = str(graph_id)
        document_number = str(
            (parsed.document.number if parsed is not None else None)
            or metadata.get("number")
            or ""
        ).strip()
        if document_number:
            document_number_index[("luatvietnam", provider_document_id)] = (
                document_number
            )

        item_ids = tuple(sorted(requested_items.get(provider_document_id, ())))
        if not item_ids:
            continue
        if parsed is None:
            _record_item_failures(
                failure_index,
                provider_document_id,
                item_ids,
                "target_hierarchy_not_available",
            )
            continue
        html_path = raw_dir / "source.html"
        source_path = raw_dir / "source.txt"
        if not html_path.is_file() or not source_path.is_file():
            _record_item_failures(
                failure_index,
                provider_document_id,
                item_ids,
                "target_provider_source_unavailable",
            )
            continue
        target_source_text = source_path.read_text(encoding="utf-8")
        try:
            spans = parse_provider_item_spans(
                html_path.read_text(encoding="utf-8"),
                target_source_text,
                item_ids,
            )
        except ParseError:
            _record_item_failures(
                failure_index,
                provider_document_id,
                item_ids,
                "target_provider_source_mismatch",
            )
            continue
        registry = StructuralRegistry.from_parsed_document(
            parsed, f"LTV_{provider_document_id}"
        )
        for span in spans:
            endpoint = _smallest_structural_endpoint(
                parsed,
                registry,
                span.source_char_start,
                span.source_char_end,
                source_text=target_source_text,
            )
            if endpoint is not None:
                unit_index[
                    ("luatvietnam", provider_document_id, span.provider_item_id)
                ] = endpoint
        resolved_item_ids = {
            item_id
            for item_id in item_ids
            if ("luatvietnam", provider_document_id, item_id) in unit_index
        }
        _record_item_failures(
            failure_index,
            provider_document_id,
            tuple(item for item in item_ids if item not in resolved_item_ids),
            "target_provider_item_not_found_or_ambiguous",
        )

    return document_index, document_number_index, unit_index, failure_index


def _record_item_failures(
    failures: dict[tuple[str, str, str | None], str],
    provider_document_id: str,
    item_ids: tuple[str, ...],
    reason: str,
) -> None:
    for item_id in item_ids:
        failures[("luatvietnam", provider_document_id, item_id)] = reason


def _load_parsed_document(
    processed_root: Path,
    provider_document_id: str,
    current_parsed: ParsedDocument | None,
) -> ParsedDocument | None:
    if current_parsed is not None:
        return current_parsed
    path = processed_root / f"LTV_{provider_document_id}" / "hierarchy.json"
    if not path.is_file():
        return None
    try:
        return ParsedDocument.model_validate_json(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _smallest_structural_endpoint(
    parsed: ParsedDocument,
    registry: StructuralRegistry,
    start: int,
    end: int,
    *,
    source_text: str | None = None,
) -> tuple[str, str] | None:
    candidates: list[tuple[int, int, str, str]] = []

    def add_candidate(
        source_start: int,
        source_end: int,
        node_id: str | None,
        node_type: str,
        depth: int,
    ) -> None:
        if (
            node_id
            and source_start <= start
            and end <= source_end
            and source_end > source_start
        ):
            candidates.append((source_end - source_start, -depth, node_id, node_type))

    for part in parsed.parts:
        add_candidate(
            part.source_start_char,
            part.source_end_char,
            registry.parts.get(normalize_part_number(part.number)),
            "Part",
            1,
        )
    if source_text is not None:
        chapter_match = re.match(
            r"(?i)\s*chương\s+([IVXLCDM]+|\d+[a-z]?)\b", source_text[start:end]
        )
        if chapter_match:
            chapter_number = chapter_match.group(1).strip().upper()
            add_candidate(
                start,
                end,
                registry.chapters.get(chapter_number),
                "Chapter",
                2,
            )
    for section in parsed.sections:
        chapter = section.chapter.strip().upper() if section.chapter else None
        add_candidate(
            section.source_start_char,
            section.source_end_char,
            registry.sections.get((chapter, section.number.strip().lower())),
            "Section",
            3,
        )
    for subsection in parsed.subsections:
        chapter = subsection.chapter.strip().upper() if subsection.chapter else None
        add_candidate(
            subsection.source_start_char,
            subsection.source_end_char,
            registry.subsections.get(
                (
                    chapter,
                    subsection.section.strip().lower(),
                    normalize_subsection_number(subsection.number),
                )
            ),
            "Subsection",
            4,
        )
    for article in parsed.articles:
        article_key = (
            f"p{normalize_part_number(article.part)}_{article.number}"
            if article.part
            else article.number
        )
        for clause in article.clauses:
            for point in clause.points:
                add_candidate(
                    point.source_start_char,
                    point.source_end_char,
                    registry.points.get(
                        (article_key, clause.number, point.label.strip().lower())
                    ),
                    "Point",
                    7,
                )
            add_candidate(
                clause.source_start_char,
                clause.source_end_char,
                registry.clauses.get((article_key, clause.number)),
                "Clause",
                6,
            )
        add_candidate(
            article.source_start_char,
            article.source_end_char,
            registry.articles.get(article_key),
            "Article",
            5,
        )
    if not candidates:
        return None
    _, _, node_id, node_type = min(candidates)
    return node_id, node_type
