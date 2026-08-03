from __future__ import annotations

import pytest

from src.infrastructure.neo4j.reference_writer import (
    ExternalReferenceWriteError,
    Neo4jExternalReferenceWriter,
)
from src.shared.ontology.validators import (
    ValidatedExternalReference,
    ValidatedRelation,
    validate_external_relation_batch,
)


def _batch(*, target_type: str = "Article", target_id: str = "target_art35"):
    properties = {
        "relation_id": "rel-1",
        "citation_text": "Điều 35 Luật số 68/2014/QH13",
        "citation_type": "DIRECT",
        "extraction_method": "ENTITY_LINKING",
        "created_at": "2026-07-31T00:00:00+00:00",
        "reference_bundle_id": "bundle-1",
        "reference_target_count": 1,
        "source_unit_id": "source_art1",
        "source_char_start": 10,
        "source_char_end": 42,
        "linker_name": "corpus-structural-registry",
        "linker_version": "1.0.0",
    }
    relation = ValidatedRelation(
        head_id="source_art1",
        relation_type="REFERS_TO",
        tail_id=target_id,
        head_type="Article",
        tail_type=target_type,
        properties=properties,
    )
    wrapped = ValidatedExternalReference(
        relation=relation,
        source_id="source_art1",
        source_type="Article",
        source_document_id="source_doc",
        source_ancestor_ids=("source_doc",),
        target_id=target_id,
        target_type=target_type,
        target_document_id="target_doc",
        target_ancestor_ids=("target_doc",),
        reference_bundle_id="bundle-1",
    )
    return validate_external_relation_batch(
        [wrapped],
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
        self.existing = tuple(existing)
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
        if "target_ids" in query:
            return _Result([{"target_ids": list(self.existing)}])
        if "MERGE (source)-[relation:REFERS_TO" in query:
            return _Result(
                [
                    {
                        "target_id": row["target_id"],
                        "relation_id": row["relation_id"],
                    }
                    for row in parameters["rows"]
                ]
            )
        raise AssertionError(query)


class _Session:
    def __init__(self, existing=()):
        self.tx = _Transaction(existing)

    def execute_write(self, callback, *args):
        return callback(self.tx, *args)


def test_external_writer_matches_endpoints_and_only_merges_relation() -> None:
    session = _Session()

    result = Neo4jExternalReferenceWriter(session).write(_batch())[0]

    assert result.final_target_ids == ("target_art35",)
    merge_queries = [query for query, _ in session.tx.queries if "MERGE" in query]
    assert len(merge_queries) == 1
    assert "MERGE (source)-[relation:REFERS_TO" in merge_queries[0]
    assert "MERGE (source {" not in merge_queries[0]
    assert "MERGE (target {" not in merge_queries[0]


def test_external_writer_blocks_conflicting_old_target_before_merge() -> None:
    session = _Session(existing=("old_target",))

    with pytest.raises(
        ExternalReferenceWriteError, match="bundle_target_conflict_in_graph"
    ):
        Neo4jExternalReferenceWriter(session).write(_batch())

    assert not any("MERGE" in query for query, _ in session.tx.queries)


def test_external_writer_rejects_raw_input() -> None:
    with pytest.raises(TypeError, match="ValidatedRelationBatch"):
        Neo4jExternalReferenceWriter(_Session()).write({"references": []})


@pytest.mark.parametrize(
    ("target_type", "target_id"),
    [("Part", "target_part2"), ("Subsection", "target_ch5_sec3_subsec1")],
)
def test_external_writer_accepts_verified_new_structural_targets(
    target_type: str, target_id: str
) -> None:
    session = _Session()

    result = Neo4jExternalReferenceWriter(session).write(
        _batch(target_type=target_type, target_id=target_id)
    )[0]

    assert result.final_target_ids == (target_id,)
    assert any(
        f"MATCH (target:{target_type}" in query for query, _ in session.tx.queries
    )
    assert any("CONTAINS*1..7" in query for query, _ in session.tx.queries)
