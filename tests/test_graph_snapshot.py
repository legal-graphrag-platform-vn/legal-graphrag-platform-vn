from __future__ import annotations

import pytest
from datetime import date

from src.infrastructure.neo4j.graph_snapshot import (
    _normalize,
    graph_projection,
    payload_projection,
    projection_sha256,
    write_snapshot,
)


class ProjectionSession:
    def run(self, cypher: str, **parameters):
        if "RETURN n.id AS id" in cypher:
            return [
                {
                    "id": "doc",
                    "labels": ["Document"],
                    "properties": {"id": "doc", "number": "1", "effective_from": date(2026, 1, 1)},
                },
                {
                    "id": "doc_art1",
                    "labels": ["Article"],
                    "properties": {"id": "doc_art1", "content_raw": "A"},
                },
            ]
        return [
            {
                "relation_id": "r1",
                "type": "CONTAINS",
                "source_id": "doc",
                "target_id": "doc_art1",
                "properties": {"relation_id": "r1"},
            }
        ]


def test_payload_projection_is_order_independent_and_excludes_embedding_state() -> None:
    first = {
        "nodes": [
            {"type": "Article", "id": "doc_art1", "content_raw": "A", "embedding": [1.0]},
            {"type": "Document", "id": "doc", "number": "1"},
        ],
        "relations": [
            {
                "head_id": "doc",
                "type": "CONTAINS",
                "tail_id": "doc_art1",
                "properties": {"relation_id": "r1", "updated_at": "new"},
            }
        ],
    }
    second = {"nodes": list(reversed(first["nodes"])), "relations": first["relations"]}
    second["nodes"][0] = {**second["nodes"][0], "embedding": [9.0]}

    assert projection_sha256(payload_projection(first)) == projection_sha256(payload_projection(second))


def test_snapshot_output_rejects_path_traversal(tmp_path) -> None:
    with pytest.raises(ValueError, match="file name"):
        write_snapshot({}, tmp_path, "../write_1.json")

    path = write_snapshot({"graph_id": "doc"}, tmp_path, "write_1.json")
    assert path.name == "write_1.json"


def test_payload_and_graph_projection_share_temporal_and_null_contract() -> None:
    payload = {
        "nodes": [
            {"type": "Document", "id": "doc", "number": "1", "effective_from": "2026-01-01", "effective_to": None},
            {"type": "Article", "id": "doc_art1", "content_raw": "A"},
        ],
        "relations": [
            {"head_id": "doc", "type": "CONTAINS", "tail_id": "doc_art1", "properties": {"relation_id": "r1"}}
        ],
    }

    local = payload_projection(payload)
    written = graph_projection(ProjectionSession(), ["doc", "doc_art1"])

    assert projection_sha256(local) == projection_sha256(written)


def test_neo4j_temporal_style_values_are_json_serializable() -> None:
    class NeoDate:
        def iso_format(self) -> str:
            return "2026-01-01"

    session = ProjectionSession()
    rows = session.run("RETURN n.id AS id")
    rows[0]["properties"]["effective_from"] = NeoDate()
    session.run = lambda cypher, **parameters: rows if "RETURN n.id AS id" in cypher else []

    projection = graph_projection(session, ["doc"])

    assert projection["nodes"][0]["properties"]["effective_from"] == "2026-01-01"


def test_datetime_precision_normalizes_between_payload_and_neo4j() -> None:
    class NeoDateTime:
        def iso_format(self) -> str:
            return "2026-07-12T06:52:25.517500000+00:00"

    payload = {
        "nodes": [],
        "relations": [
            {
                "head_id": "a",
                "type": "DEFINES",
                "tail_id": "b",
                "properties": {"relation_id": "r", "created_at": "2026-07-12T06:52:25.517500Z"},
            }
        ],
    }
    local = payload_projection(payload)
    assert local["relations"][0]["properties"]["created_at"] == _normalize(NeoDateTime())
