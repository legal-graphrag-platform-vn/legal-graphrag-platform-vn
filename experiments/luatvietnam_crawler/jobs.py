"""Durable file-backed detail crawl jobs built from a discovery manifest."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from .parser import CONTENT_SERIALIZER_VERSION
from .safety import RunLock
from .storage import write_report

JobStatus = Literal[
    "pending",
    "in_progress",
    "completed",
    "content_unavailable",
    "skipped",
    "retryable",
    "failed",
]
JOB_STATUSES = frozenset(
    {
        "pending",
        "in_progress",
        "completed",
        "content_unavailable",
        "skipped",
        "retryable",
        "failed",
    }
)
CLAIMABLE_STATUSES = ("pending", "retryable")
TERMINAL_SUCCESS_STATUSES = frozenset({"completed", "content_unavailable", "skipped"})
JOB_ID_RE = re.compile(r"LTV_[0-9]+-d(?:1|5|10)")


def create_job_bundle(
    discovery: dict[str, object], output_root: Path
) -> dict[str, object]:
    """Materialize one resumable job file per unique discovery document."""
    search_url = _required_string(discovery, "search_url")
    documents = discovery.get("documents")
    if not isinstance(documents, list):
        raise ValueError("Discovery manifest must contain a documents list")

    bundle_id = f"search-{hashlib.sha256(search_url.encode()).hexdigest()[:16]}"
    bundle_dir = output_root.resolve() / bundle_id
    jobs_dir = bundle_dir / "jobs"
    pages_dir = bundle_dir / "pages"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    pages_dir.mkdir(parents=True, exist_ok=True)

    created_at = _utc_now()
    job_refs: list[dict[str, object]] = []
    page_jobs: dict[int, list[dict[str, object]]] = defaultdict(list)
    seen_job_ids: set[str] = set()

    for item in documents:
        if not isinstance(item, dict):
            raise ValueError("Every discovery document must be an object")
        job_id = _job_id(item)
        if job_id in seen_job_ids:
            raise ValueError(f"Duplicate job identity in discovery manifest: {job_id}")
        seen_job_ids.add(job_id)
        rank = _required_positive_int(item, "rank")
        page_index = _required_positive_int(item, "page_index")
        relative_path = Path("jobs") / f"{job_id}.json"
        job_path = bundle_dir / relative_path
        state, artifacts = _initial_or_existing_job_data(job_path, item, created_at)
        job = {
            "schema_version": "luatvietnam-detail-job-v2",
            "bundle_id": bundle_id,
            "job_id": job_id,
            "rank": rank,
            "page_index": page_index,
            "source": {
                "external_id": _required_string(item, "external_id"),
                "detail_variant": _required_string(item, "detail_variant"),
                "source_kind": _required_string(item, "source_kind"),
                "title": _required_string(item, "title"),
                "url": _required_string(item, "url"),
            },
            "state": state,
            "artifacts": artifacts,
        }
        write_report(job, job_path)
        reference = {
            "job_id": job_id,
            "rank": rank,
            "page_index": page_index,
            "job_file": relative_path.as_posix(),
        }
        job_refs.append(reference)
        page_jobs[page_index].append(
            {
                **reference,
                "external_id": item["external_id"],
                "title": item["title"],
                "url": item["url"],
            }
        )

    job_refs.sort(key=lambda value: int(value["rank"]))
    page_refs: list[dict[str, object]] = []
    for page_index in sorted(page_jobs):
        page_file = Path("pages") / f"page-{page_index:04d}.json"
        page_payload = {
            "schema_version": "luatvietnam-job-page-v1",
            "bundle_id": bundle_id,
            "page_index": page_index,
            "job_count": len(page_jobs[page_index]),
            "jobs": sorted(page_jobs[page_index], key=lambda value: int(value["rank"])),
        }
        write_report(page_payload, bundle_dir / page_file)
        page_refs.append(
            {
                "page_index": page_index,
                "page_file": page_file.as_posix(),
                "job_count": len(page_jobs[page_index]),
            }
        )

    manifest = {
        "schema_version": "luatvietnam-job-bundle-v1",
        "bundle_id": bundle_id,
        "source_provider": "luatvietnam.vn",
        "search_url": search_url,
        "created_at": created_at,
        "discovery_schema_version": discovery.get("schema_version"),
        "pagination": discovery.get("pagination"),
        "pages_visited": discovery.get("pages_visited"),
        "pages_planned": discovery.get("pages_planned"),
        "site_result_occurrence_count": discovery.get("result_occurrence_count"),
        "duplicate_occurrences": discovery.get("duplicate_occurrences", []),
        "page_count": len(page_refs),
        "job_count": len(job_refs),
        "pages": page_refs,
        "jobs": job_refs,
    }
    write_report(manifest, bundle_dir / "manifest.json")
    state = summarize_job_bundle(bundle_dir)
    return {"bundle_dir": str(bundle_dir), "manifest": manifest, "state": state}


def load_discovery(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read discovery manifest {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("Discovery manifest root must be an object")
    return payload


def summarize_job_bundle(bundle_dir: Path) -> dict[str, object]:
    """Rebuild the aggregate state from the authoritative per-job files."""
    manifest = _load_object(bundle_dir / "manifest.json")
    refs = manifest.get("jobs")
    if not isinstance(refs, list):
        raise ValueError("Job bundle manifest must contain a jobs list")

    counts: Counter[str] = Counter()
    next_by_status: dict[str, dict[str, object]] = {}
    for reference in sorted(refs, key=lambda value: int(value["rank"])):
        job = _load_job_from_reference(bundle_dir, reference)
        state = job.get("state")
        if not isinstance(state, dict) or state.get("status") not in JOB_STATUSES:
            raise ValueError(f"Invalid state for job {job.get('job_id')}")
        status = str(state["status"])
        counts[status] += 1
        next_by_status.setdefault(status, _job_pointer(reference, job))

    next_job = next(
        (
            next_by_status[status]
            for status in CLAIMABLE_STATUSES
            if status in next_by_status
        ),
        None,
    )
    first_unfinished_job = next(
        (
            next_by_status[status]
            for status in ("in_progress", "pending", "retryable", "failed")
            if status in next_by_status
        ),
        None,
    )
    state_payload = {
        "schema_version": "luatvietnam-job-state-v2",
        "bundle_id": manifest.get("bundle_id"),
        "updated_at": _utc_now(),
        "job_count": len(refs),
        "counts": {status: counts.get(status, 0) for status in sorted(JOB_STATUSES)},
        "next_job": next_job,
        "first_unfinished_job": first_unfinished_job,
        "first_in_progress_job": next_by_status.get("in_progress"),
        "complete": (
            sum(counts.get(status, 0) for status in TERMINAL_SUCCESS_STATUSES)
            == len(refs)
        ),
    }
    write_report(state_payload, bundle_dir / "state.json")
    return state_payload


def claim_next_job(
    bundle_dir: Path, *, exclude_job_ids: set[str] | None = None
) -> dict[str, object] | None:
    """Claim the first pending job, falling back to a retryable job."""
    with RunLock(bundle_dir / ".job-state.lock"):
        return _claim_next_job_unlocked(bundle_dir, exclude_job_ids or set())


def _claim_next_job_unlocked(
    bundle_dir: Path, exclude_job_ids: set[str]
) -> dict[str, object] | None:
    manifest = _load_object(bundle_dir / "manifest.json")
    refs = manifest.get("jobs")
    if not isinstance(refs, list):
        raise ValueError("Job bundle manifest must contain a jobs list")
    sorted_refs = sorted(refs, key=lambda value: int(value["rank"]))
    for wanted_status in CLAIMABLE_STATUSES:
        for reference in sorted_refs:
            if reference.get("job_id") in exclude_job_ids:
                continue
            job_path = _job_path_from_reference(bundle_dir, reference)
            job = _load_object(job_path)
            state = job.get("state")
            if not isinstance(state, dict) or state.get("status") != wanted_status:
                continue
            now = _utc_now()
            state.update(
                {
                    "status": "in_progress",
                    "attempts": int(state.get("attempts", 0)) + 1,
                    "started_at": now,
                    "completed_at": None,
                    "updated_at": now,
                    "last_error": None,
                }
            )
            write_report(job, job_path)
            summarize_job_bundle(bundle_dir)
            return job
    summarize_job_bundle(bundle_dir)
    return None


def update_job_status(
    bundle_dir: Path,
    job_id: str,
    status: JobStatus,
    *,
    error: str | None = None,
    output_directory: str | None = None,
    metadata_only_directory: str | None = None,
    content_serializer_version: str | None = None,
    content_character_count: int | None = None,
    article_count: int | None = None,
    reference_marker_count: int | None = None,
    raw_html_saved: bool | None = None,
) -> dict[str, object]:
    with RunLock(bundle_dir / ".job-state.lock"):
        return _update_job_status_unlocked(
            bundle_dir,
            job_id,
            status,
            error=error,
            output_directory=output_directory,
            metadata_only_directory=metadata_only_directory,
            content_serializer_version=content_serializer_version,
            content_character_count=content_character_count,
            article_count=article_count,
            reference_marker_count=reference_marker_count,
            raw_html_saved=raw_html_saved,
        )


def _update_job_status_unlocked(
    bundle_dir: Path,
    job_id: str,
    status: JobStatus,
    *,
    error: str | None,
    output_directory: str | None,
    metadata_only_directory: str | None,
    content_serializer_version: str | None,
    content_character_count: int | None,
    article_count: int | None,
    reference_marker_count: int | None,
    raw_html_saved: bool | None,
) -> dict[str, object]:
    if status not in JOB_STATUSES:
        raise ValueError(f"Unsupported job status: {status}")
    if JOB_ID_RE.fullmatch(job_id) is None:
        raise ValueError(f"Unsafe job ID: {job_id}")
    job_path = bundle_dir / "jobs" / f"{job_id}.json"
    job = _load_object(job_path)
    state = job.get("state")
    if not isinstance(state, dict):
        raise ValueError(f"Job {job_id} has no valid state")
    now = _utc_now()
    state.update(
        {
            "status": status,
            "updated_at": now,
            "completed_at": (now if status in TERMINAL_SUCCESS_STATUSES else None),
            "last_error": error,
        }
    )
    if status == "in_progress" and state.get("started_at") is None:
        state["started_at"] = now
        state["attempts"] = int(state.get("attempts", 0)) + 1
    artifacts = job.get("artifacts")
    if output_directory is not None and isinstance(artifacts, dict):
        artifacts["output_directory"] = output_directory
    if metadata_only_directory is not None and isinstance(artifacts, dict):
        artifacts["metadata_only_directory"] = metadata_only_directory
    if isinstance(artifacts, dict):
        artifact_updates = {
            "content_serializer_version": content_serializer_version,
            "content_character_count": content_character_count,
            "article_count": article_count,
            "reference_marker_count": reference_marker_count,
            "raw_html_saved": raw_html_saved,
        }
        for key, value in artifact_updates.items():
            if value is not None:
                artifacts[key] = value
    job["schema_version"] = "luatvietnam-detail-job-v2"
    write_report(job, job_path)
    summarize_job_bundle(bundle_dir)
    return job


def _initial_or_existing_job_data(
    job_path: Path, item: dict[str, object], created_at: str
) -> tuple[dict[str, object], dict[str, object]]:
    if job_path.exists():
        existing = _load_object(job_path)
        source = existing.get("source")
        state = existing.get("state")
        artifacts = existing.get("artifacts")
        if not isinstance(source, dict) or source.get("url") != item.get("url"):
            raise ValueError(f"Existing job identity conflicts with {job_path}")
        if not isinstance(state, dict) or state.get("status") not in JOB_STATUSES:
            raise ValueError(f"Existing job has invalid state: {job_path}")
        if not isinstance(artifacts, dict):
            raise ValueError(f"Existing job has invalid artifacts: {job_path}")
        artifacts.setdefault("output_directory", None)
        artifacts.setdefault("metadata_only_directory", None)
        artifacts.setdefault("content_serializer_version", None)
        artifacts.setdefault("content_character_count", None)
        artifacts.setdefault("article_count", None)
        artifacts.setdefault("reference_marker_count", None)
        artifacts.setdefault("raw_html_saved", None)
        return state, artifacts
    external_id = _required_string(item, "external_id")
    return (
        {
            "status": "pending",
            "attempts": 0,
            "created_at": created_at,
            "updated_at": created_at,
            "started_at": None,
            "completed_at": None,
            "last_error": None,
        },
        {
            "raw_doc_code": f"LTV_{external_id}",
            "output_directory": None,
            "metadata_only_directory": None,
            "content_serializer_version": None,
            "content_character_count": None,
            "article_count": None,
            "reference_marker_count": None,
            "raw_html_saved": None,
        },
    )


def requeue_stale_content_jobs(
    bundle_dir: Path,
    *,
    apply: bool = False,
    target_serializer_version: str = CONTENT_SERIALIZER_VERSION,
) -> dict[str, object]:
    """Find or requeue completed jobs written by an older content serializer."""
    if not target_serializer_version.strip():
        raise ValueError("target_serializer_version must not be empty")

    def inspect() -> tuple[list[str], list[tuple[Path, dict[str, object]]]]:
        manifest = _load_object(bundle_dir / "manifest.json")
        references = manifest.get("jobs")
        if not isinstance(references, list):
            raise ValueError("Job bundle manifest must contain a jobs list")
        candidate_ids: list[str] = []
        candidate_jobs: list[tuple[Path, dict[str, object]]] = []
        for reference in sorted(references, key=lambda value: int(value["rank"])):
            job_path = _job_path_from_reference(bundle_dir, reference)
            job = _load_object(job_path)
            state = job.get("state")
            artifacts = job.get("artifacts")
            if not isinstance(state, dict) or not isinstance(artifacts, dict):
                raise ValueError(f"Malformed job: {job.get('job_id')}")
            if state.get("status") != "completed":
                continue
            if (
                artifacts.get("content_serializer_version") == target_serializer_version
                and artifacts.get("raw_html_saved") is True
            ):
                continue
            candidate_ids.append(str(job["job_id"]))
            candidate_jobs.append((job_path, job))
        return candidate_ids, candidate_jobs

    if not apply:
        candidate_ids, _ = inspect()
        return {
            "bundle_dir": str(bundle_dir.resolve()),
            "apply": False,
            "target_serializer_version": target_serializer_version,
            "candidate_count": len(candidate_ids),
            "candidate_job_ids": candidate_ids,
            "requeued_count": 0,
            "requeued_job_ids": [],
        }

    with RunLock(bundle_dir / ".job-state.lock"):
        candidate_ids, candidate_jobs = inspect()
        now = _utc_now()
        for job_path, job in candidate_jobs:
            state = job["state"]
            artifacts = job["artifacts"]
            assert isinstance(state, dict) and isinstance(artifacts, dict)
            state.update(
                {
                    "status": "pending",
                    "updated_at": now,
                    "started_at": None,
                    "completed_at": None,
                    "last_error": None,
                }
            )
            for key in (
                "output_directory",
                "content_serializer_version",
                "content_character_count",
                "article_count",
                "reference_marker_count",
                "raw_html_saved",
            ):
                artifacts[key] = None
            write_report(job, job_path)
        state_payload = summarize_job_bundle(bundle_dir)
    return {
        "bundle_dir": str(bundle_dir.resolve()),
        "apply": True,
        "target_serializer_version": target_serializer_version,
        "candidate_count": len(candidate_ids),
        "candidate_job_ids": candidate_ids,
        "requeued_count": len(candidate_ids),
        "requeued_job_ids": candidate_ids,
        "state": state_payload,
    }


def migrate_content_unavailable_jobs(bundle_dir: Path) -> dict[str, object]:
    """Reclassify legacy ContentUnavailable failures without fetching the site."""
    migrated: list[str] = []
    normalized: list[str] = []
    with RunLock(bundle_dir / ".job-state.lock"):
        manifest = _load_object(bundle_dir / "manifest.json")
        references = manifest.get("jobs")
        if not isinstance(references, list):
            raise ValueError("Job bundle manifest must contain a jobs list")
        now = _utc_now()
        for reference in references:
            job_path = _job_path_from_reference(bundle_dir, reference)
            job = _load_object(job_path)
            state = job.get("state")
            if not isinstance(state, dict):
                raise ValueError(f"Job {job.get('job_id')} has no valid state")
            last_error = str(state.get("last_error") or "")
            is_legacy_failure = state.get("status") in {
                "retryable",
                "failed",
            } and last_error.startswith("ContentUnavailableError:")
            is_existing_terminal = state.get("status") == "content_unavailable"
            if not is_legacy_failure and not is_existing_terminal:
                continue
            changed = False
            if is_legacy_failure:
                state.update(
                    {
                        "status": "content_unavailable",
                        "updated_at": now,
                        "completed_at": now,
                    }
                )
                migrated.append(str(job["job_id"]))
                changed = True
            artifacts = job.get("artifacts")
            if not isinstance(artifacts, dict):
                raise ValueError(f"Job {job.get('job_id')} has invalid artifacts")
            for key in ("output_directory", "metadata_only_directory"):
                if key not in artifacts:
                    artifacts[key] = None
                    changed = True
            if job.get("schema_version") != "luatvietnam-detail-job-v2":
                job["schema_version"] = "luatvietnam-detail-job-v2"
                changed = True
            if changed:
                write_report(job, job_path)
                normalized.append(str(job["job_id"]))
        state_payload = summarize_job_bundle(bundle_dir)
    return {
        "bundle_dir": str(bundle_dir.resolve()),
        "migrated_count": len(migrated),
        "migrated_job_ids": migrated,
        "normalized_count": len(normalized),
        "normalized_job_ids": normalized,
        "state": state_payload,
    }


def _load_job_from_reference(bundle_dir: Path, reference: object) -> dict[str, object]:
    return _load_object(_job_path_from_reference(bundle_dir, reference))


def _job_path_from_reference(bundle_dir: Path, reference: object) -> Path:
    if not isinstance(reference, dict) or not isinstance(
        reference.get("job_file"), str
    ):
        raise ValueError("Invalid job reference in bundle manifest")
    bundle_root = bundle_dir.resolve()
    job_path = (bundle_root / reference["job_file"]).resolve()
    if bundle_root not in job_path.parents:
        raise ValueError("Job reference points outside its bundle")
    return job_path


def _load_object(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read JSON file {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _job_id(item: dict[str, object]) -> str:
    external_id = _required_string(item, "external_id")
    variant = _required_string(item, "detail_variant")
    job_id = f"LTV_{external_id}-{variant}"
    if JOB_ID_RE.fullmatch(job_id) is None:
        raise ValueError("Unsafe external_id or detail_variant in discovery document")
    return job_id


def _job_pointer(
    reference: dict[str, object], job: dict[str, object]
) -> dict[str, object]:
    source = job.get("source")
    return {
        "job_id": reference.get("job_id"),
        "rank": reference.get("rank"),
        "page_index": reference.get("page_index"),
        "job_file": reference.get("job_file"),
        "url": source.get("url") if isinstance(source, dict) else None,
    }


def _required_string(value: dict[str, object], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"Missing non-empty string: {key}")
    return result


def _required_positive_int(value: dict[str, object], key: str) -> int:
    result = value.get(key)
    if not isinstance(result, int) or isinstance(result, bool) or result < 1:
        raise ValueError(f"Missing positive integer: {key}")
    return result


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
