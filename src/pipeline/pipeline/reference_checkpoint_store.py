"""Crash-safe reference checkpoint and materialization-attempt persistence."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from src.pipeline.extraction.structural_references import ResolvedReference


CHECKPOINT_CONTRACT_VERSION = "reference-checkpoint-v2"
ATTEMPT_CONTRACT_VERSION = "reference-materialization-attempt-v1"
EMPTY_CHECKPOINT_HASH = f"sha256:{hashlib.sha256(b'').hexdigest()}"


class ReferenceCheckpointError(ValueError):
    """Raised when checkpoint or attempt evidence is invalid or stale."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReferenceResolutionState(_StrictModel):
    status: Literal["UNRESOLVED", "RESOLVED", "AMBIGUOUS"]
    reference_scope: Literal["LOCAL", "EXTERNAL", "UNKNOWN"]
    is_self_reference: bool
    reason_code: str
    target_ids: tuple[str, ...] = ()
    build_id: str | None = None
    snapshot_hash: str | None = None
    provenance_hash: str | None = None
    resolved_at: datetime | None = None


class ReferenceMaterializationState(_StrictModel):
    status: Literal["NOT_APPLICABLE", "PENDING", "WRITTEN", "FAILED", "BLOCKED"]
    reason_code: str | None = None
    relation_ids: tuple[str, ...] = ()
    attempt_count: int = Field(default=0, ge=0)
    last_attempt_at: datetime | None = None
    written_at: datetime | None = None


class ReferenceCheckpointV2(_StrictModel):
    contract_version: Literal["reference-checkpoint-v2"] = CHECKPOINT_CONTRACT_VERSION
    reference_bundle_id: str
    mention_fingerprint: str
    resolver_name: str
    resolver_version: str
    detected_at: datetime
    reference: ResolvedReference
    resolution: ReferenceResolutionState
    materialization: ReferenceMaterializationState


class ReferenceMaterializationAttempt(_StrictModel):
    contract_version: Literal["reference-materialization-attempt-v1"] = (
        ATTEMPT_CONTRACT_VERSION
    )
    attempt_id: str
    reference_bundle_id: str
    build_id: str
    snapshot_hash: str
    provenance_hash: str
    expected_checkpoint_hash: str
    expected_target_ids: tuple[str, ...]
    observed_existing_target_ids: tuple[str, ...]
    graph_outcome: Literal["COMMITTED", "NOT_COMMITTED", "UNKNOWN"]
    relation_ids: tuple[str, ...] = ()
    started_at: datetime
    finished_at: datetime
    error_code: str | None = None
    record_hash: str = ""


class ReferenceCheckpointStore:
    """Per-document store. Mutations require the advisory lock context."""

    def __init__(self, processed_dir: Path) -> None:
        self.processed_dir = processed_dir
        self.checkpoint_path = processed_dir / "reference_resolutions.jsonl"
        self.attempt_path = processed_dir / "reference_materialization_attempts.jsonl"
        self.lock_path = processed_dir / ".reference_reconciliation.lock"
        self._lock_depth = 0

    @contextmanager
    def locked(self) -> Iterator["ReferenceCheckpointStore"]:
        self.processed_dir.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self._lock_depth += 1
            yield self
        finally:
            self._lock_depth -= 1
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def read_checkpoints(self) -> dict[str, ReferenceCheckpointV2]:
        rows = _read_jsonl(self.checkpoint_path, allow_missing=True)
        checkpoints: dict[str, ReferenceCheckpointV2] = {}
        for line_number, row in rows:
            try:
                checkpoint = ReferenceCheckpointV2.model_validate(row)
            except Exception as exc:
                raise ReferenceCheckpointError(
                    f"Unsupported or malformed reference checkpoint at "
                    f"{self.checkpoint_path}:{line_number}"
                ) from exc
            if checkpoint.reference_bundle_id in checkpoints:
                raise ReferenceCheckpointError(
                    f"Duplicate reference checkpoint: {checkpoint.reference_bundle_id}"
                )
            checkpoints[checkpoint.reference_bundle_id] = checkpoint
        return checkpoints

    def read_attempts(self) -> tuple[ReferenceMaterializationAttempt, ...]:
        attempts: list[ReferenceMaterializationAttempt] = []
        for line_number, row in _read_jsonl(self.attempt_path, allow_missing=True):
            try:
                attempt = ReferenceMaterializationAttempt.model_validate(row)
            except Exception as exc:
                raise ReferenceCheckpointError(
                    f"Malformed attempt ledger row at {self.attempt_path}:{line_number}"
                ) from exc
            expected_hash = attempt_record_hash(attempt)
            if attempt.record_hash != expected_hash:
                raise ReferenceCheckpointError(
                    f"Attempt ledger record hash mismatch at {self.attempt_path}:{line_number}"
                )
            attempts.append(attempt)
        return tuple(attempts)

    def checkpoint_hash(self) -> str:
        if not self.checkpoint_path.exists():
            return EMPTY_CHECKPOINT_HASH
        if self.checkpoint_path.is_symlink():
            raise ReferenceCheckpointError("Checkpoint path must not be a symlink")
        return _hash_bytes(self.checkpoint_path.read_bytes())

    def compare_and_swap(
        self,
        checkpoints: Mapping[str, ReferenceCheckpointV2],
        *,
        expected_hash: str,
    ) -> str:
        self._require_lock()
        actual_hash = self.checkpoint_hash()
        if actual_hash != expected_hash:
            raise ReferenceCheckpointError(
                "stale_checkpoint_compare_and_swap: "
                f"expected {expected_hash}, found {actual_hash}"
            )
        content = "".join(
            f"{_canonical_json(checkpoints[bundle_id].model_dump(mode='json'))}\n"
            for bundle_id in sorted(checkpoints)
        ).encode("utf-8")
        temporary = self.checkpoint_path.with_name(
            f".{self.checkpoint_path.name}.{uuid.uuid4().hex}.tmp"
        )
        _write_new_file_durable(temporary, content)
        os.replace(temporary, self.checkpoint_path)
        _fsync_directory(self.processed_dir)
        return _hash_bytes(content)

    def append_attempt(
        self, attempt: ReferenceMaterializationAttempt
    ) -> ReferenceMaterializationAttempt:
        self._require_lock()
        if attempt.record_hash:
            raise ReferenceCheckpointError(
                "Attempt record_hash must be assigned by store"
            )
        durable = attempt.model_copy(
            update={"record_hash": attempt_record_hash(attempt)}
        )
        content = f"{_canonical_json(durable.model_dump(mode='json'))}\n".encode(
            "utf-8"
        )
        created = not self.attempt_path.exists()
        descriptor = os.open(
            self.attempt_path,
            os.O_WRONLY | os.O_APPEND | os.O_CREAT,
            0o600,
        )
        try:
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("Attempt ledger append made no progress")
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if created:
            _fsync_directory(self.processed_dir)
        return durable

    def _require_lock(self) -> None:
        if self._lock_depth < 1:
            raise ReferenceCheckpointError("Checkpoint mutation requires advisory lock")


def checkpoint_from_reference(
    reference: ResolvedReference,
    *,
    resolver_name: str,
    resolver_version: str,
    detected_at: datetime | None = None,
    prior: ReferenceCheckpointV2 | None = None,
    prior_written: bool = False,
) -> ReferenceCheckpointV2:
    now = detected_at or datetime.now(timezone.utc)
    evidence = reference.registry_evidence
    resolution = ReferenceResolutionState(
        status=reference.status,
        reference_scope=reference.reference_scope,
        is_self_reference=reference.is_self_reference,
        reason_code=reference.reason_code,
        target_ids=reference.target_unit_ids,
        build_id=evidence.build_id if evidence else None,
        snapshot_hash=evidence.snapshot_hash if evidence else None,
        provenance_hash=evidence.provenance_hash if evidence else None,
        resolved_at=now if reference.status == "RESOLVED" else None,
    )
    initial_status: Literal["NOT_APPLICABLE", "PENDING", "WRITTEN", "FAILED", "BLOCKED"]
    if reference.status == "RESOLVED" and reference.reference_scope == "EXTERNAL":
        initial_status = "PENDING"
    else:
        initial_status = "NOT_APPLICABLE"
    materialization_reason = None
    if reference.is_self_reference:
        materialization_reason = "self_reference_no_edge"
    elif reference.status == "RESOLVED" and reference.reference_scope == "LOCAL":
        materialization_reason = "local_reference_not_external"
    materialization = ReferenceMaterializationState(
        status=initial_status,
        reason_code=materialization_reason,
    )

    if prior is not None:
        old_targets = prior.resolution.target_ids
        new_targets = resolution.target_ids
        if old_targets == new_targets:
            materialization = prior.materialization
        elif prior_written or prior.materialization.status in {"WRITTEN", "BLOCKED"}:
            materialization = ReferenceMaterializationState(
                status="BLOCKED",
                reason_code="resolved_target_changed_after_materialization",
                relation_ids=prior.materialization.relation_ids,
                attempt_count=prior.materialization.attempt_count,
                last_attempt_at=prior.materialization.last_attempt_at,
                written_at=prior.materialization.written_at,
            )

    return ReferenceCheckpointV2(
        reference_bundle_id=reference.mention.reference_bundle_id,
        mention_fingerprint=reference_mention_fingerprint(reference),
        resolver_name=resolver_name,
        resolver_version=resolver_version,
        detected_at=(
            prior.detected_at
            if prior
            and prior.mention_fingerprint == reference_mention_fingerprint(reference)
            else now
        ),
        reference=reference,
        resolution=resolution,
        materialization=materialization,
    )


def reference_mention_fingerprint(reference: ResolvedReference) -> str:
    mention = reference.mention.model_dump(mode="json")
    return _hash_bytes(_canonical_json(mention).encode("utf-8"))


def attempt_record_hash(attempt: ReferenceMaterializationAttempt) -> str:
    payload = attempt.model_dump(mode="json")
    payload.pop("record_hash", None)
    return _hash_bytes(_canonical_json(payload).encode("utf-8"))


def committed_target_history(
    attempts: Sequence[ReferenceMaterializationAttempt], bundle_id: str
) -> set[tuple[str, ...]]:
    return {
        tuple(sorted(attempt.expected_target_ids))
        for attempt in attempts
        if attempt.reference_bundle_id == bundle_id
        and attempt.graph_outcome == "COMMITTED"
    }


def _read_jsonl(
    path: Path, *, allow_missing: bool
) -> list[tuple[int, dict[str, object]]]:
    if not path.exists():
        if allow_missing:
            return []
        raise ReferenceCheckpointError(f"Missing JSONL file: {path}")
    if path.is_symlink():
        raise ReferenceCheckpointError(f"JSONL path must not be a symlink: {path}")
    content = path.read_bytes()
    if content and not content.endswith(b"\n"):
        raise ReferenceCheckpointError(f"Truncated JSONL final row: {path}")
    rows: list[tuple[int, dict[str, object]]] = []
    for line_number, raw_line in enumerate(content.splitlines(), 1):
        if not raw_line:
            continue
        try:
            row = json.loads(raw_line)
        except json.JSONDecodeError as exc:
            raise ReferenceCheckpointError(
                f"Malformed JSONL row at {path}:{line_number}"
            ) from exc
        if not isinstance(row, dict):
            raise ReferenceCheckpointError(
                f"JSONL row must be an object at {path}:{line_number}"
            )
        rows.append((line_number, row))
    return rows


def _write_new_file_durable(path: Path, content: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("Checkpoint write made no progress")
            view = view[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _canonical_json(payload: object) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _hash_bytes(content: bytes) -> str:
    return f"sha256:{hashlib.sha256(content).hexdigest()}"
