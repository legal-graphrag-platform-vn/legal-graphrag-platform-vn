from __future__ import annotations

import pytest

from src.infrastructure.neo4j.reference_writer import (
    ExternalReferenceWriteError,
    Neo4jProviderTemporalWriter,
)
from src.shared.ontology.validators import (
    ValidatedProviderTemporalRelation,
    ValidatedRelation,
    validate_provider_temporal_relation_batch,
)


def _batch():
    relation = ValidatedRelation(
        head_id="source_art1",
        relation_type="AMENDS",
        tail_id="target_art35",
        head_type="Article",
        tail_type="Article",
        properties={
            "relation_id": "temporal-rel-1",
            "effective_from": "2024-01-01",
            "provider_candidate_id": "provider-temporal-1",
            "extraction_method": "PROVIDER_HTML",
        },
    )
    wrapped = ValidatedProviderTemporalRelation(
        relation=relation,
        source_document_id="source_doc",
        target_document_id="target_doc",
        provider_candidate_id="provider-temporal-1",
    )
    return validate_provider_temporal_relation_batch(
        (wrapped,),
        registry_build_id="build-1",
        registry_snapshot_hash="sha256:" + "1" * 64,
        registry_provenance_hash="sha256:" + "2" * 64,
    )


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def data(self):
        return self._rows


class _Transaction:
    def __init__(self, existing=()):
        self.existing = existing
        self.queries = []

    def run(self, query, **parameters):
        self.queries.append((query, parameters))
        if "ownership_path_count" in query:
            endpoint = parameters["endpoint_id"]
            owner = "source_doc" if endpoint == "source_art1" else "target_doc"
            return _Result(
                [
                    {
                        "endpoint_count": 1,
                        "owner_ids": [owner],
                        "ownership_path_count": 1,
                    }
                ]
            )
        if "existing_relations" in query:
            return _Result([{"existing_relations": list(self.existing)}])
        if "MERGE (source)-[relation:AMENDS" in query:
            return _Result(
                [
                    {
                        "relation_id": parameters["relation_id"],
                        "target_id": parameters["target_id"],
                    }
                ]
            )
        raise AssertionError(query)


class _Session:
    def __init__(self, existing=()):
        self.tx = _Transaction(existing)

    def execute_write(self, callback, *args):
        return callback(self.tx, *args)


def test_provider_temporal_writer_verifies_endpoints_and_merges_only_relation() -> None:
    session = _Session()

    result = Neo4jProviderTemporalWriter(session).write(_batch())[0]

    assert result.target_id == "target_art35"
    merge_queries = [query for query, _ in session.tx.queries if "MERGE" in query]
    assert len(merge_queries) == 1
    assert "MERGE (source)-[relation:AMENDS" in merge_queries[0]
    assert "date($relation_effective_from)" in merge_queries[0]


def test_provider_temporal_writer_rejects_candidate_target_drift() -> None:
    session = _Session(
        existing=({"relation_type": "AMENDS", "target_id": "old_target"},)
    )

    with pytest.raises(
        ExternalReferenceWriteError,
        match="provider_temporal_target_conflict_in_graph",
    ):
        Neo4jProviderTemporalWriter(session).write(_batch())

    assert not any("MERGE" in query for query, _ in session.tx.queries)


def test_provider_temporal_writer_rejects_raw_input() -> None:
    with pytest.raises(TypeError, match="ValidatedProviderTemporalBatch"):
        Neo4jProviderTemporalWriter(_Session()).write({"relations": []})
