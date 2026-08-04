from __future__ import annotations

from datetime import date

import pytest

from src.retrieval.models import (
    GraphCitationEvidence,
    GraphEdge,
    GraphNodeRef,
    GraphPath,
)
from src.retrieval.path_identity import build_topology_path_fingerprint


def _path() -> GraphPath:
    return GraphPath(
        nodes=(
            GraphNodeRef(
                node_id="doc_art1",
                labels=("Article",),
                effective_from=date(2021, 1, 1),
                legal_status="ACTIVE",
                citable_unit_id="doc_art1",
            ),
            GraphNodeRef(
                node_id="doc_art2",
                labels=("Article",),
                effective_from=date(2021, 1, 1),
                legal_status="ACTIVE",
                citable_unit_id="doc_art2",
            ),
        ),
        edges=(
            GraphEdge(
                relation_id="citation-a",
                relation_type="REFERS_TO",
                source_id="doc_art1",
                target_id="doc_art2",
                citation_evidence=(
                    GraphCitationEvidence(
                        relation_id="citation-a",
                        citation_text="Điều 2",
                        citation_type="DIRECT",
                        extraction_method="RULE",
                    ),
                ),
            ),
        ),
        path_description="Điều 1 dẫn chiếu Điều 2",
    )


def test_topology_fingerprint_is_deterministic() -> None:
    path = _path()

    first = build_topology_path_fingerprint(path)
    second = build_topology_path_fingerprint(path)

    assert first == second
    assert first.startswith("path_")


def test_mutable_metadata_and_parallel_citation_identity_do_not_change_fingerprint() -> (
    None
):
    path = _path()
    changed = path.model_copy(
        update={
            "nodes": (
                path.nodes[0].model_copy(
                    update={
                        "labels": ("Article", "ExtraLabel"),
                        "effective_from": date(2022, 1, 1),
                        "legal_status": "AMENDED",
                        "citable_unit_id": None,
                    }
                ),
                path.nodes[1],
            ),
            "edges": (
                path.edges[0].model_copy(
                    update={
                        "relation_id": "citation-b",
                        "effective_from": date(2022, 1, 1),
                        "citation_evidence": (
                            GraphCitationEvidence(
                                relation_id="citation-b",
                                citation_text="khoản 1 Điều 2",
                                citation_type="INDIRECT",
                                extraction_method="LLM",
                            ),
                        ),
                    }
                ),
            ),
            "path_description": "Presentation text changed",
        }
    )

    assert build_topology_path_fingerprint(changed) == (
        build_topology_path_fingerprint(path)
    )


@pytest.mark.parametrize(
    "changed_path",
    [
        _path().model_copy(
            update={
                "nodes": (
                    _path().nodes[0],
                    _path().nodes[1].model_copy(update={"node_id": "doc_art3"}),
                ),
                "edges": (
                    _path().edges[0].model_copy(update={"target_id": "doc_art3"}),
                ),
            }
        ),
        _path().model_copy(
            update={
                "edges": (
                    _path().edges[0].model_copy(update={"relation_type": "AMENDS"}),
                )
            }
        ),
        _path().model_copy(
            update={
                "edges": (
                    _path()
                    .edges[0]
                    .model_copy(
                        update={"source_id": "doc_art2", "target_id": "doc_art1"}
                    ),
                )
            }
        ),
        _path().model_copy(update={"nodes": tuple(reversed(_path().nodes))}),
    ],
)
def test_topology_changes_produce_different_fingerprints(
    changed_path: GraphPath,
) -> None:
    assert build_topology_path_fingerprint(changed_path) != (
        build_topology_path_fingerprint(_path())
    )


def test_fingerprint_rejects_malformed_path_shape() -> None:
    malformed = _path().model_copy(update={"nodes": (_path().nodes[0],)})

    with pytest.raises(ValueError, match="cardinality"):
        build_topology_path_fingerprint(malformed)
