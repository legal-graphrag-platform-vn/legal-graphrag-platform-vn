from __future__ import annotations

import json

from src.pipeline.extraction.provider_references import ProviderReferenceMentionV1
from src.pipeline.extraction.provider_relation_candidates import (
    ProviderRelationCandidateV1,
)
from src.pipeline.pipeline import external_reference_reconciliation as service
from src.pipeline.pipeline.reference_checkpoint_store import ReferenceCheckpointStore
from src.pipeline.tests.test_external_reference_validator import _checkpoint_and_build


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def data(self):
        return self._rows


class _Transaction:
    def run(self, query, **parameters):
        if "ownership_path_count" in query:
            endpoint = parameters["endpoint_id"]
            owner = "ldn_2020" if endpoint == "ldn_2020_art1" else "ldn_2014"
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
            return _Result([{"target_ids": []}])
        if "existing_relations" in query:
            return _Result([{"existing_relations": []}])
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
        if "MERGE (source)-[relation:AMENDS" in query:
            return _Result(
                [
                    {
                        "target_id": parameters["target_id"],
                        "relation_id": parameters["relation_id"],
                    }
                ]
            )
        raise AssertionError(query)


class _Session:
    def __init__(self, events):
        self.events = events

    def execute_write(self, callback, *args):
        self.events.append("graph")
        return callback(_Transaction(), *args)


def test_reconciliation_durability_order_is_graph_ledger_checkpoint(
    tmp_path, monkeypatch
) -> None:
    checkpoint, build = _checkpoint_and_build()
    events = []
    original_append = ReferenceCheckpointStore.append_attempt
    original_cas = ReferenceCheckpointStore.compare_and_swap

    def append_attempt(self, attempt):
        events.append("ledger")
        return original_append(self, attempt)

    def compare_and_swap(self, checkpoints, *, expected_hash):
        events.append("checkpoint")
        return original_cas(self, checkpoints, expected_hash=expected_hash)

    monkeypatch.setattr(
        service, "detect_references", lambda *args, **kwargs: [checkpoint.reference]
    )
    monkeypatch.setattr(ReferenceCheckpointStore, "append_attempt", append_attempt)
    monkeypatch.setattr(ReferenceCheckpointStore, "compare_and_swap", compare_and_swap)

    report = service.reconcile_external_references(
        raw_doc_code="source",
        processed_dir=tmp_path,
        parsed=object(),
        source_text="source",
        build=build,
        apply=True,
        session=_Session(events),
    )

    assert report.written_count == 1
    graph_index = events.index("graph")
    assert events[graph_index : graph_index + 3] == [
        "graph",
        "ledger",
        "checkpoint",
    ]
    stored = ReferenceCheckpointStore(tmp_path).read_checkpoints()
    assert next(iter(stored.values())).materialization.status == "WRITTEN"


def test_reconciliation_materializes_accepted_provider_temporal_relation(
    tmp_path, monkeypatch
) -> None:
    _, build = _checkpoint_and_build()
    mention = ProviderReferenceMentionV1(
        contract_version="provider-reference-mention-v1",
        provider="luatvietnam",
        provider_source_document_id="100",
        provider_target_document_id="200",
        provider_target_item_ids=("35",),
        provider_relation_id="101",
        provider_link_type="CHANGE_CONTENT",
        citation_text="Điều 35",
        source_char_start=10,
        source_char_end=20,
    )
    candidate = ProviderRelationCandidateV1(
        candidate_id="provider-temporal-1",
        provider_relation_id="101",
        relation_candidate="AMENDS",
        source_ownership="HOST",
        host_source_id="ldn_2020_art1",
        canonical_source_id="ldn_2020_art1",
        canonical_source_type="Article",
        canonical_target_ids=("ldn_2014_art35",),
        canonical_target_types=("Article",),
        status="RESOLVED",
        reason_code="provider_endpoints_resolved",
        evidence="Sửa đổi Điều 35",
        reference=mention,
    )
    (tmp_path / "provider_relation_candidates.jsonl").write_text(
        candidate.model_dump_json() + "\n", encoding="utf-8"
    )
    accepted = {
        "decision": "accepted",
        "provider_bundle_id": candidate.candidate_id,
        "relation": {
            "head": "ldn_2020_art1",
            "relation": "AMENDS",
            "tail": "ldn_2014_art35",
            "properties": {
                "effective_from": "2024-01-01",
                "extraction_method": "PROVIDER_HTML",
                "provider_candidate_id": candidate.candidate_id,
                "materialization_route": "CORPUS_RELATION_RECONCILIATION",
            },
        },
    }
    (tmp_path / "accepted.jsonl").write_text(
        json.dumps(accepted) + "\n", encoding="utf-8"
    )
    monkeypatch.setattr(service, "detect_references", lambda *args, **kwargs: [])

    report = service.reconcile_external_references(
        raw_doc_code="source",
        processed_dir=tmp_path,
        parsed=object(),
        source_text="source",
        build=build,
        apply=True,
        session=_Session([]),
    )

    assert report.provider_temporal_candidate_count == 1
    assert report.provider_temporal_ready_count == 1
    assert report.provider_temporal_written_count == 1
