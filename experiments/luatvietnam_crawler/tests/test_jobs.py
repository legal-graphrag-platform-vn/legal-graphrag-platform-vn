from __future__ import annotations

import json
from pathlib import Path

from experiments.luatvietnam_crawler.jobs import (
    claim_next_job,
    create_job_bundle,
    migrate_content_unavailable_jobs,
    requeue_stale_content_jobs,
    summarize_job_bundle,
    update_job_status,
)
from experiments.luatvietnam_crawler.parser import CONTENT_SERIALIZER_VERSION


def _discovery() -> dict[str, object]:
    return {
        "schema_version": "luatvietnam-discovery-v3",
        "search_url": "https://luatvietnam.vn/van-ban/tim-van-ban.html?PageSize=100",
        "pages_visited": 2,
        "pages_planned": 2,
        "result_occurrence_count": 2,
        "pagination": {"total_results": 2, "page_size": 100},
        "duplicate_occurrences": [],
        "documents": [
            {
                "rank": 1,
                "page_index": 1,
                "external_id": "100001",
                "detail_variant": "d1",
                "source_kind": "issued_document",
                "title": "Văn bản thứ nhất",
                "url": "https://luatvietnam.vn/a/van-ban-thu-nhat-100001-d1.html",
            },
            {
                "rank": 2,
                "page_index": 2,
                "external_id": "100002",
                "detail_variant": "d5",
                "source_kind": "consolidated_document",
                "title": "Văn bản thứ hai",
                "url": "https://luatvietnam.vn/a/van-ban-thu-hai-100002-d5.html",
            },
        ],
    }


def _read(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_create_job_bundle_splits_manifest_pages_and_individual_jobs(
    tmp_path: Path,
) -> None:
    result = create_job_bundle(_discovery(), tmp_path / "jobs")
    bundle = Path(str(result["bundle_dir"]))

    manifest = _read(bundle / "manifest.json")
    state = _read(bundle / "state.json")
    first_page = _read(bundle / "pages" / "page-0001.json")
    first_job = _read(bundle / "jobs" / "LTV_100001-d1.json")

    assert manifest["job_count"] == 2
    assert manifest["page_count"] == 2
    assert manifest["jobs"][0]["job_file"] == "jobs/LTV_100001-d1.json"
    assert first_page["jobs"][0]["job_id"] == "LTV_100001-d1"
    assert first_job["source"]["title"] == "Văn bản thứ nhất"
    assert first_job["state"]["status"] == "pending"
    assert state["counts"]["pending"] == 2
    assert state["next_job"]["job_id"] == "LTV_100001-d1"
    assert state["first_unfinished_job"]["job_id"] == "LTV_100001-d1"


def test_job_claim_update_and_resume_preserve_completed_state(tmp_path: Path) -> None:
    result = create_job_bundle(_discovery(), tmp_path / "jobs")
    bundle = Path(str(result["bundle_dir"]))

    claimed = claim_next_job(bundle)
    assert claimed is not None
    assert claimed["job_id"] == "LTV_100001-d1"
    assert claimed["state"]["status"] == "in_progress"
    assert claimed["state"]["attempts"] == 1

    update_job_status(
        bundle,
        "LTV_100001-d1",
        "completed",
        output_directory="output/raw/LTV_100001",
    )
    state = summarize_job_bundle(bundle)
    assert state["counts"]["completed"] == 1
    assert state["next_job"]["job_id"] == "LTV_100002-d5"

    create_job_bundle(_discovery(), tmp_path / "jobs")
    completed = _read(bundle / "jobs" / "LTV_100001-d1.json")
    assert completed["state"]["status"] == "completed"
    assert completed["artifacts"]["output_directory"] == "output/raw/LTV_100001"


def test_retryable_job_is_resumed_after_pending_jobs(tmp_path: Path) -> None:
    result = create_job_bundle(_discovery(), tmp_path / "jobs")
    bundle = Path(str(result["bundle_dir"]))
    update_job_status(bundle, "LTV_100001-d1", "retryable", error="temporary")

    claimed = claim_next_job(bundle)

    assert claimed is not None
    assert claimed["job_id"] == "LTV_100002-d5"


def test_content_unavailable_is_terminal_and_completes_bundle(tmp_path: Path) -> None:
    result = create_job_bundle(_discovery(), tmp_path / "jobs")
    bundle = Path(str(result["bundle_dir"]))
    update_job_status(bundle, "LTV_100001-d1", "content_unavailable")
    update_job_status(bundle, "LTV_100002-d5", "completed")

    state = summarize_job_bundle(bundle)

    assert state["counts"]["content_unavailable"] == 1
    assert state["next_job"] is None
    assert state["first_unfinished_job"] is None
    assert state["complete"] is True


def test_skipped_is_terminal_and_completes_bundle(tmp_path: Path) -> None:
    result = create_job_bundle(_discovery(), tmp_path / "jobs")
    bundle = Path(str(result["bundle_dir"]))
    update_job_status(bundle, "LTV_100001-d1", "skipped", error="not_approved")
    update_job_status(bundle, "LTV_100002-d5", "completed")

    state = summarize_job_bundle(bundle)

    assert state["counts"]["skipped"] == 1
    assert state["next_job"] is None
    assert state["complete"] is True


def test_content_unavailable_state_migration_is_idempotent(tmp_path: Path) -> None:
    result = create_job_bundle(_discovery(), tmp_path / "jobs")
    bundle = Path(str(result["bundle_dir"]))
    claimed = claim_next_job(bundle)
    assert claimed is not None
    update_job_status(
        bundle,
        "LTV_100001-d1",
        "retryable",
        error="ContentUnavailableError: HTML full text is unavailable",
    )

    first = migrate_content_unavailable_jobs(bundle)
    second = migrate_content_unavailable_jobs(bundle)
    migrated = _read(bundle / "jobs" / "LTV_100001-d1.json")

    assert first["migrated_count"] == 1
    assert second["migrated_count"] == 0
    assert migrated["state"]["status"] == "content_unavailable"
    assert migrated["state"]["attempts"] == 1
    assert migrated["artifacts"]["metadata_only_directory"] is None


def test_requeue_stale_content_is_dry_run_then_idempotent_apply(
    tmp_path: Path,
) -> None:
    result = create_job_bundle(_discovery(), tmp_path / "jobs")
    bundle = Path(str(result["bundle_dir"]))
    update_job_status(
        bundle,
        "LTV_100001-d1",
        "completed",
        output_directory="output/raw/LTV_100001",
        content_serializer_version=CONTENT_SERIALIZER_VERSION,
        content_character_count=100,
        article_count=1,
        reference_marker_count=0,
        raw_html_saved=False,
    )
    update_job_status(bundle, "LTV_100002-d5", "content_unavailable")

    dry_run = requeue_stale_content_jobs(bundle, apply=False)
    unchanged = _read(bundle / "jobs" / "LTV_100001-d1.json")
    applied = requeue_stale_content_jobs(bundle, apply=True)
    repeated = requeue_stale_content_jobs(bundle, apply=True)
    migrated = _read(bundle / "jobs" / "LTV_100001-d1.json")
    unavailable = _read(bundle / "jobs" / "LTV_100002-d5.json")

    assert dry_run["candidate_job_ids"] == ["LTV_100001-d1"]
    assert unchanged["state"]["status"] == "completed"
    assert applied["requeued_job_ids"] == ["LTV_100001-d1"]
    assert repeated["requeued_count"] == 0
    assert migrated["state"]["status"] == "pending"
    assert migrated["artifacts"]["content_serializer_version"] is None
    assert migrated["artifacts"]["raw_html_saved"] is None
    assert migrated["artifacts"]["output_directory"] is None
    assert unavailable["state"]["status"] == "content_unavailable"
    assert applied["target_serializer_version"] == CONTENT_SERIALIZER_VERSION
