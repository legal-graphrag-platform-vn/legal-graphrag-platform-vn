"""Canonical topology identity shared by retrieval and generation."""

from __future__ import annotations

import hashlib
import json

from src.retrieval.models import GraphPath


def build_topology_path_fingerprint(path: GraphPath) -> str:
    """Hash traversal order and canonical edge topology, excluding provenance."""

    if not path.edges or len(path.nodes) != len(path.edges) + 1:
        raise ValueError("Graph path node/edge cardinality is invalid")

    edge_topology = []
    for left, edge, right in zip(
        path.nodes[:-1], path.edges, path.nodes[1:], strict=True
    ):
        if {edge.source_id, edge.target_id} != {left.node_id, right.node_id}:
            raise ValueError(
                f"Graph edge does not connect adjacent nodes: {edge.relation_id}"
            )
        edge_topology.append(
            {
                "relation_type": edge.relation_type,
                "source_id": edge.source_id,
                "target_id": edge.target_id,
            }
        )

    canonical = json.dumps(
        {
            "node_ids": [node.node_id for node in path.nodes],
            "edges": edge_topology,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "path_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]
