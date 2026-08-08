"""Tests cho document_relation_resolver — resolve candidates + build records."""

from __future__ import annotations

import pytest

from src.pipeline.extraction.diagram_parser import (
    DiagramRelationCandidate,
    parse_diagram,
)
from src.pipeline.extraction.document_relation_resolver import (
    DIAGRAM_RESOLVER_NAME,
    DIAGRAM_RESOLVER_VERSION,
    ResolvedDiagramRelation,
    UnresolvedDiagramRelation,
    build_diagram_records,
    resolve_diagram_relations,
)
from src.pipeline.extraction.structural_context import DocumentRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _registry(*aliases: tuple[str, str, str]) -> DocumentRegistry:
    """Build a minimal DocumentRegistry from (raw_key, graph_id, doc_type) tuples."""
    alias_map: dict[str, tuple[str, str]] = {}
    import re
    for raw_key, graph_id, doc_type in aliases:
        normalized = re.sub(r"[^a-z0-9]+", "", raw_key.lower().replace("đ", "d"))
        alias_map[normalized] = (graph_id, doc_type)
    return DocumentRegistry(alias_map)


def _candidate(
    source_category: str,
    relation_type: str,
    direction: str,
    raw_target: str,
) -> DiagramRelationCandidate:
    return DiagramRelationCandidate(
        source_category=source_category,
        relation_type=relation_type,  # type: ignore[arg-type]
        direction=direction,           # type: ignore[arg-type]
        raw_target=raw_target,
    )


# ---------------------------------------------------------------------------
# resolve_diagram_relations
# ---------------------------------------------------------------------------

class TestResolveDiagramRelations:
    def test_resolved_current_to_target(self):
        registry = _registry(("ldn_2014", "ldn_2014", "Law"))
        candidates = [
            _candidate("Văn bản được thay thế", "REPLACES", "CURRENT_TO_TARGET", "ldn_2014"),
        ]
        resolved, unresolved = resolve_diagram_relations(candidates, "ldn_2020", registry)

        assert len(resolved) == 1
        assert len(unresolved) == 0
        r = resolved[0]
        assert r.head_id == "ldn_2020"
        assert r.tail_id == "ldn_2014"
        assert r.relation_type == "REPLACES"
        assert r.resolved is True

    def test_resolved_target_to_current(self):
        registry = _registry(("ldn_2025", "ldn_2025", "Law"))
        candidates = [
            _candidate("Văn bản sửa đổi bổ sung", "AMENDS", "TARGET_TO_CURRENT", "ldn_2025"),
        ]
        resolved, unresolved = resolve_diagram_relations(candidates, "ldn_2020", registry)

        assert len(resolved) == 1
        r = resolved[0]
        assert r.head_id == "ldn_2025"   # target là head vì nó thực hiện AMENDS
        assert r.tail_id == "ldn_2020"   # current là tail bị tác động
        assert r.relation_type == "AMENDS"

    def test_unresolved_target_goes_to_unresolved(self):
        registry = DocumentRegistry({})  # empty
        candidates = [
            _candidate("Văn bản được thay thế", "REPLACES", "CURRENT_TO_TARGET", "Luật chưa biết"),
        ]
        resolved, unresolved = resolve_diagram_relations(candidates, "ldn_2020", registry)

        assert len(resolved) == 0
        assert len(unresolved) == 1
        u = unresolved[0]
        assert u.raw_target == "Luật chưa biết"
        assert u.relation_type == "REPLACES"
        assert u.current_document_id == "ldn_2020"

    def test_self_loop_skipped(self):
        """Nếu registry trả về chính current document → bỏ qua."""
        registry = _registry(("ldn_2020", "ldn_2020", "Law"))
        candidates = [
            _candidate("Văn bản được thay thế", "REPLACES", "CURRENT_TO_TARGET", "ldn_2020"),
        ]
        resolved, unresolved = resolve_diagram_relations(candidates, "ldn_2020", registry)

        assert len(resolved) == 0
        assert len(unresolved) == 0

    def test_mixed_resolved_and_unresolved(self):
        registry = _registry(("ldn_2014", "ldn_2014", "Law"))
        candidates = [
            _candidate("Văn bản được thay thế", "REPLACES", "CURRENT_TO_TARGET", "ldn_2014"),
            _candidate("Văn bản sửa đổi bổ sung", "AMENDS", "TARGET_TO_CURRENT", "Luật chưa biết"),
        ]
        resolved, unresolved = resolve_diagram_relations(candidates, "ldn_2020", registry)

        assert len(resolved) == 1
        assert len(unresolved) == 1

    def test_empty_candidates(self):
        registry = DocumentRegistry({})
        resolved, unresolved = resolve_diagram_relations([], "ldn_2020", registry)
        assert resolved == []
        assert unresolved == []

    def test_accepts_tuple_candidates(self):
        """resolver signature nhận cả tuple lẫn list."""
        registry = DocumentRegistry({})
        result = parse_diagram({"Văn bản được thay thế (0)": []})
        resolved, unresolved = resolve_diagram_relations(result.candidates, "ldn_2020", registry)
        assert resolved == []
        assert unresolved == []


# ---------------------------------------------------------------------------
# build_diagram_records
# ---------------------------------------------------------------------------

class TestBuildDiagramRecords:
    def _resolved(self, head: str, rel: str, tail: str) -> ResolvedDiagramRelation:
        return ResolvedDiagramRelation(
            head_id=head,
            relation_type=rel,
            tail_id=tail,
            source_category="Văn bản được thay thế",
            raw_target="Luật DN 2014",
            resolved=True,
        )

    def _unresolved(self) -> UnresolvedDiagramRelation:
        return UnresolvedDiagramRelation(
            raw_target="Luật chưa biết",
            source_category="Văn bản được thay thế",
            relation_type="REPLACES",
            direction="CURRENT_TO_TARGET",
            current_document_id="ldn_2020",
        )

    def test_resolved_record_schema(self):
        records = build_diagram_records(
            [self._resolved("ldn_2020", "REPLACES", "ldn_2014")],
            [],
            "ldn_2020",
        )
        assert len(records) == 1
        r = records[0]
        assert r["document_id"] == "ldn_2020"
        assert r["article_number"] is None
        assert r["extraction_method"] == "DIAGRAM"
        assert r["schema_valid"] is True
        assert r["ontology_valid"] is True
        assert r["consistency_valid"] is True
        assert r["confidence"] == 1.0
        assert r["review_reason"] is None
        assert r["blocking"] is False

    def test_resolved_relation_content(self):
        records = build_diagram_records(
            [self._resolved("ldn_2020", "REPLACES", "ldn_2014")],
            [],
            "ldn_2020",
        )
        rel = records[0]["relation"]
        assert rel["head"] == "ldn_2020"
        assert rel["relation"] == "REPLACES"
        assert rel["tail"] == "ldn_2014"
        props = rel["properties"]
        assert props["extraction_method"] == "DIAGRAM"
        assert props["confidence"] == 1.0
        assert props["resolver_name"] == DIAGRAM_RESOLVER_NAME
        assert props["resolver_version"] == DIAGRAM_RESOLVER_VERSION
        assert "created_at" in props
        assert "source_category" in props
        assert "source_text" in props

    def test_resolved_endpoint_resolution(self):
        records = build_diagram_records(
            [self._resolved("ldn_2020", "REPLACES", "ldn_2014")],
            [],
            "ldn_2020",
        )
        ep = records[0]["endpoint_resolution"]
        assert ep["head"]["status"] == "resolved"
        assert ep["tail"]["status"] == "resolved"
        assert ep["head"]["canonical_id"] == "ldn_2020"
        assert ep["tail"]["canonical_id"] == "ldn_2014"

    def test_unresolved_record_schema(self):
        records = build_diagram_records([], [self._unresolved()], "ldn_2020")
        assert len(records) == 1
        r = records[0]
        assert r["ontology_valid"] is False
        assert r["consistency_valid"] is False
        assert r["confidence"] == 0.0
        assert r["review_reason"] == "unresolved_diagram_target"
        assert r["blocking"] is False

    def test_unresolved_relation_head_tail(self):
        records = build_diagram_records([], [self._unresolved()], "ldn_2020")
        rel = records[0]["relation"]
        # CURRENT_TO_TARGET: current = head, unresolved = tail
        assert rel["head"] == "ldn_2020"
        assert "UNRESOLVED" in rel["tail"]
        assert "Luật chưa biết" in rel["tail"]

    def test_unresolved_target_to_current_head_tail(self):
        unres = UnresolvedDiagramRelation(
            raw_target="Luật chưa biết",
            source_category="Văn bản sửa đổi bổ sung",
            relation_type="AMENDS",
            direction="TARGET_TO_CURRENT",
            current_document_id="ldn_2020",
        )
        records = build_diagram_records([], [unres], "ldn_2020")
        rel = records[0]["relation"]
        # TARGET_TO_CURRENT: unresolved = head, current = tail
        assert "UNRESOLVED" in rel["head"]
        assert rel["tail"] == "ldn_2020"

    def test_empty_inputs(self):
        records = build_diagram_records([], [], "ldn_2020")
        assert records == []

    def test_mixed_resolved_and_unresolved(self):
        records = build_diagram_records(
            [self._resolved("ldn_2020", "REPLACES", "ldn_2014")],
            [self._unresolved()],
            "ldn_2020",
        )
        assert len(records) == 2
        accepted = [r for r in records if r["ontology_valid"]]
        review = [r for r in records if not r["ontology_valid"]]
        assert len(accepted) == 1
        assert len(review) == 1

    def test_created_at_iso_format(self):
        records = build_diagram_records(
            [self._resolved("ldn_2020", "REPLACES", "ldn_2014")],
            [],
            "ldn_2020",
        )
        created_at = records[0]["relation"]["properties"]["created_at"]
        assert created_at.endswith("Z")
        assert "T" in created_at
