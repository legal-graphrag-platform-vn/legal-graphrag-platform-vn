from datetime import date

import pytest

from src.retrieval.errors import RetrievalOutputError
from src.retrieval.models import IntentType, RetrievalFilters
from src.retrieval.retriever.graph import GraphRetriever


class Repo:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def graph_expansion(self, *args, **kwargs):
        return self.rows


def _row(
    *,
    source_id: str = "newer",
    target_id: str = "older",
    traversal_nodes: tuple[str, str] = ("older", "newer"),
    relation_type: str = "AMENDS",
    effective_from: date | None = date(2024, 1, 1),
    effective_to: date | None = None,
) -> dict:
    return {
        "path_node_refs": [
            {
                "node_id": node_id,
                "labels": ["Article"],
                "effective_from": date(2021, 1, 1),
                "effective_to": None,
                "legal_status": "ACTIVE",
                "citable_unit_id": node_id,
            }
            for node_id in traversal_nodes
        ],
        "path_edge_refs": [
            {
                "relation_id": "rel-amends",
                "relation_type": relation_type,
                "source_id": source_id,
                "target_id": target_id,
                "effective_from": effective_from,
                "effective_to": effective_to,
            }
        ],
    }


def test_incoming_traversal_preserves_canonical_edge_direction() -> None:
    expansion = GraphRetriever(Repo([_row()])).expand(
        ["older"],
        IntentType.COMPARISON,
        filters=RetrievalFilters(query_date=date(2025, 1, 1)),
    )

    edge = expansion.paths[0].edges[0]
    assert (edge.source_id, edge.target_id) == ("newer", "older")
    assert expansion.paths[0].path_description == "older <-[AMENDS]- newer"


@pytest.mark.parametrize(
    ("effective_from", "effective_to"),
    [
        (date(2026, 1, 1), None),
        (date(2024, 1, 1), date(2025, 1, 1)),
    ],
)
def test_temporal_invalid_relationship_is_rejected_before_context(
    effective_from: date,
    effective_to: date | None,
) -> None:
    expansion = GraphRetriever(
        Repo([_row(effective_from=effective_from, effective_to=effective_to)])
    ).expand(
        ["older"],
        IntentType.COMPARISON,
        filters=RetrievalFilters(query_date=date(2025, 1, 1)),
    )

    assert expansion.paths == []
    assert expansion.diagnostics.temporal_rejected_path_count == 1


def test_temporal_relation_without_effective_from_is_malformed() -> None:
    with pytest.raises(RetrievalOutputError, match="requires effective_from"):
        GraphRetriever(Repo([_row(effective_from=None)])).expand(
            ["older"],
            IntentType.COMPARISON,
            filters=RetrievalFilters(),
        )


def test_edge_must_connect_adjacent_traversal_nodes() -> None:
    with pytest.raises(RetrievalOutputError, match="adjacent path nodes"):
        GraphRetriever(Repo([_row(source_id="unrelated")])).expand(
            ["older"],
            IntentType.COMPARISON,
            filters=RetrievalFilters(),
        )


def test_malformed_temporal_value_is_not_treated_as_unbounded() -> None:
    row = _row(relation_type="REFERS_TO", effective_from=None)
    row["path_edge_refs"][0]["effective_from"] = "not-a-date"

    with pytest.raises(RetrievalOutputError, match="date-compatible"):
        GraphRetriever(Repo([row])).expand(
            ["older"],
            IntentType.FACTUAL,
            filters=RetrievalFilters(),
        )
