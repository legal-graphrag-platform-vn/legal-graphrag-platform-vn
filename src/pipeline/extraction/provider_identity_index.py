"""Resolve LuatVietnam provider IDs to existing canonical corpus identities."""

from __future__ import annotations

import json
from pathlib import Path

from experiments.luatvietnam_crawler.errors import ParseError
from experiments.luatvietnam_crawler.parser import parse_provider_item_spans

from src.pipeline.extraction.provider_references import ProviderReferenceMentionV1
from src.pipeline.extraction.provider_relation_candidates import (
    ProviderDocumentIndex,
    ProviderFailureIndex,
    ProviderUnitIndex,
)
from src.pipeline.extraction.structural_context import StructuralRegistry
from src.pipeline.parser.models import ParsedDocument


def build_luatvietnam_identity_indexes(
    raw_root: Path,
    processed_root: Path,
    current_parsed: ParsedDocument,
    references: tuple[ProviderReferenceMentionV1, ...],
) -> tuple[ProviderDocumentIndex, ProviderUnitIndex, ProviderFailureIndex]:
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
        try:
            spans = parse_provider_item_spans(
                html_path.read_text(encoding="utf-8"),
                source_path.read_text(encoding="utf-8"),
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
                parsed, registry, span.source_char_start, span.source_char_end
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

    return document_index, unit_index, failure_index


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
) -> tuple[str, str] | None:
    for article in parsed.articles:
        for clause in article.clauses:
            for point in clause.points:
                if point.source_start_char <= start and end <= point.source_end_char:
                    node_id = registry.points.get(
                        (article.number, clause.number, point.label.strip().lower())
                    )
                    return (node_id, "Point") if node_id else None
            if clause.source_start_char <= start and end <= clause.source_end_char:
                node_id = registry.clauses.get((article.number, clause.number))
                return (node_id, "Clause") if node_id else None
        if article.source_start_char <= start and end <= article.source_end_char:
            node_id = registry.articles.get(article.number)
            return (node_id, "Article") if node_id else None
    return None
