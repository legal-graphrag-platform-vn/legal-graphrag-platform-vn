from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.pipeline.extraction.structural_references import (
    ReferenceMention,
    ResolvedReference,
    SourceContext,
)
from src.pipeline.pipeline.reference_checkpoint_store import (
    EMPTY_CHECKPOINT_HASH,
    ReferenceCheckpointError,
    ReferenceCheckpointStore,
    ReferenceMaterializationAttempt,
    checkpoint_from_reference,
    committed_target_history,
)


NOW = datetime(2026, 7, 31, tzinfo=timezone.utc)


def _reference(target: str, *, scope: str = "EXTERNAL") -> ResolvedReference:
    mention = ReferenceMention(
        source_context=SourceContext(
            document_id="source_doc",
            article_id="source_doc_art1",
            clause_id="source_doc_art1_cl1",
            source_unit_id="source_doc_art1_cl1",
            source_start_char=0,
            source_end_char=20,
        ),
        raw_text="Điều 8 Nghị định 57/2026/NĐ-CP",
        reference_kind="EXPLICIT",
        source_char_start=2,
        source_char_end=20,
        reference_bundle_id="bundle-1",
    )
    return ResolvedReference(
        mention=mention,
        target_unit_ids=(target,),
        status="RESOLVED",
        reference_scope=scope,
        is_self_reference=(scope == "LOCAL" and target == "source_doc_art1_cl1"),
        resolution_method="ENTITY_LINKING" if scope == "EXTERNAL" else "RULE",
        reason_code="resolved",
    )


def _attempt(*, outcome: str = "COMMITTED") -> ReferenceMaterializationAttempt:
    return ReferenceMaterializationAttempt(
        attempt_id="attempt-1",
        reference_bundle_id="bundle-1",
        build_id="build-1",
        snapshot_hash="sha256:" + "a" * 64,
        provenance_hash="sha256:" + "b" * 64,
        expected_checkpoint_hash="sha256:" + "c" * 64,
        expected_target_ids=("target-1",),
        observed_existing_target_ids=(),
        graph_outcome=outcome,
        relation_ids=("relation-1",),
        started_at=NOW,
        finished_at=NOW,
    )


def test_checkpoint_cas_requires_lock_and_rejects_stale_hash(tmp_path) -> None:
    store = ReferenceCheckpointStore(tmp_path)
    checkpoint = checkpoint_from_reference(
        _reference("target-1"),
        resolver_name="resolver",
        resolver_version="1",
        detected_at=NOW,
    )

    with pytest.raises(ReferenceCheckpointError, match="requires advisory lock"):
        store.compare_and_swap(
            {"bundle-1": checkpoint}, expected_hash=EMPTY_CHECKPOINT_HASH
        )

    with store.locked():
        written_hash = store.compare_and_swap(
            {"bundle-1": checkpoint}, expected_hash=EMPTY_CHECKPOINT_HASH
        )
        with pytest.raises(ReferenceCheckpointError, match="stale_checkpoint"):
            store.compare_and_swap(
                {"bundle-1": checkpoint}, expected_hash=EMPTY_CHECKPOINT_HASH
            )

    assert store.checkpoint_hash() == written_hash
    assert store.read_checkpoints()["bundle-1"] == checkpoint


def test_attempt_is_hashed_appended_and_reloaded(tmp_path) -> None:
    store = ReferenceCheckpointStore(tmp_path)
    with store.locked():
        durable = store.append_attempt(_attempt())

    assert durable.record_hash.startswith("sha256:")
    assert store.read_attempts() == (durable,)
    assert committed_target_history(store.read_attempts(), "bundle-1") == {
        ("target-1",)
    }


def test_truncated_attempt_row_never_proves_commit(tmp_path) -> None:
    store = ReferenceCheckpointStore(tmp_path)
    store.attempt_path.write_text('{"graph_outcome":"COMMITTED"}', encoding="utf-8")

    with pytest.raises(ReferenceCheckpointError, match="Truncated JSONL"):
        store.read_attempts()


def test_target_change_after_written_becomes_blocked() -> None:
    old = checkpoint_from_reference(
        _reference("old-target"),
        resolver_name="resolver",
        resolver_version="1",
        detected_at=NOW,
    )
    old = old.model_copy(
        update={
            "materialization": old.materialization.model_copy(
                update={"status": "WRITTEN", "relation_ids": ("old-relation",)}
            )
        }
    )

    changed = checkpoint_from_reference(
        _reference("new-target"),
        resolver_name="resolver",
        resolver_version="1",
        detected_at=NOW,
        prior=old,
    )

    assert changed.materialization.status == "BLOCKED"
    assert (
        changed.materialization.reason_code
        == "resolved_target_changed_after_materialization"
    )


def test_target_change_before_write_remains_pending() -> None:
    old = checkpoint_from_reference(
        _reference("old-target"),
        resolver_name="resolver",
        resolver_version="1",
        detected_at=NOW,
    )

    changed = checkpoint_from_reference(
        _reference("new-target"),
        resolver_name="resolver",
        resolver_version="1",
        detected_at=NOW,
        prior=old,
    )

    assert changed.materialization.status == "PENDING"


def test_local_self_reference_is_resolved_but_not_applicable() -> None:
    validated = _reference("source_doc_art1_cl1", scope="LOCAL")

    checkpoint = checkpoint_from_reference(
        validated,
        resolver_name="resolver",
        resolver_version="1",
        detected_at=NOW,
    )

    assert checkpoint.resolution.status == "RESOLVED"
    assert checkpoint.resolution.is_self_reference is True
    assert checkpoint.materialization.status == "NOT_APPLICABLE"
