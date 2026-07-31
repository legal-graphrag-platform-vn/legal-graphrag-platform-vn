from __future__ import annotations

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
