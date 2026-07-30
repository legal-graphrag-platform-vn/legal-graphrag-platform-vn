"""Standalone CLI for the isolated LuatVietnam experiment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, cast

import typer

from .browser import BrowserSession
from .crawler import (
    CrawlProgress,
    build_metadata_list,
    crawl_job_bundle,
    crawl_search,
    discover_search_results,
)
from .jobs import (
    JOB_STATUSES,
    JobStatus,
    claim_next_job,
    create_job_bundle,
    load_discovery,
    migrate_content_unavailable_jobs,
    requeue_stale_content_jobs,
    summarize_job_bundle,
    update_job_status,
)
from .safety import RequestSafetyPolicy, RunLock
from .storage import write_report

APP_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT = APP_DIR / "output" / "raw"
DEFAULT_LIST_OUTPUT = APP_DIR / "output" / "lists" / "discovery.json"
DEFAULT_METADATA_LIST_OUTPUT = APP_DIR / "output" / "lists" / "metadata-list.json"
DEFAULT_METADATA_ONLY_OUTPUT = APP_DIR / "output" / "metadata-only"
DEFAULT_JOB_OUTPUT = APP_DIR / "output" / "jobs"
DEFAULT_PROFILE = APP_DIR / "runtime" / "chromium-profile"
DEFAULT_STATE = APP_DIR / "runtime" / "safety-state.json"
DEFAULT_LOCK = APP_DIR / "runtime" / "crawler.lock"
DEFAULT_MIN_REQUEST_DELAY = 7.0
DEFAULT_MAX_REQUEST_DELAY = 12.0
app = typer.Typer(help="Experimental LuatVietnam search-results crawler")


@app.callback()
def main() -> None:
    """Keep every command explicitly namespaced under this experiment."""


@app.command("list")
def list_documents(
    url: Annotated[str, typer.Option(help="Full LuatVietnam search-results URL")],
    max_pages: Annotated[
        int | None,
        typer.Option(min=1, help="Optional page cap; default uses site pagination"),
    ] = None,
    max_documents: Annotated[
        int | None,
        typer.Option(min=1, help="Optional document cap; default lists all matches"),
    ] = None,
    output: Annotated[
        Path, typer.Option(help="Destination JSON discovery manifest")
    ] = DEFAULT_LIST_OUTPUT,
    min_request_delay: Annotated[
        float, typer.Option(min=0)
    ] = DEFAULT_MIN_REQUEST_DELAY,
    max_request_delay: Annotated[
        float, typer.Option(min=0)
    ] = DEFAULT_MAX_REQUEST_DELAY,
    request_budget: Annotated[int, typer.Option(min=1)] = 40,
    daily_request_budget: Annotated[int, typer.Option(min=1)] = 100,
    block_cooldown_hours: Annotated[int, typer.Option(min=1)] = 24,
    profile: Annotated[
        Path, typer.Option(help="Persistent system Chrome profile and cookies")
    ] = DEFAULT_PROFILE,
    headless: Annotated[
        bool, typer.Option(help="Run without the visible system Chrome window")
    ] = False,
) -> None:
    """Save search-result document URLs without opening their detail pages."""
    safety_policy = RequestSafetyPolicy(
        state_path=DEFAULT_STATE,
        min_delay_seconds=min_request_delay,
        max_delay_seconds=max_request_delay,
        per_run_budget=request_budget,
        daily_budget=daily_request_budget,
        block_cooldown_seconds=block_cooldown_hours * 3600,
    )
    with RunLock(DEFAULT_LOCK):
        with BrowserSession(
            profile_dir=profile,
            safety_policy=safety_policy,
            headless=headless,
            browser_channel="chrome",
        ) as browser:
            manifest = discover_search_results(
                url,
                fetcher=browser,
                max_pages=max_pages,
                max_documents=max_documents,
                delay_seconds=0,
            )
    write_report(manifest, output)
    typer.echo(
        json.dumps(
            {
                "output": str(output.resolve()),
                "pages_visited": manifest["pages_visited"],
                "document_count": manifest["document_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("prepare-jobs")
def prepare_jobs(
    discovery: Annotated[
        Path, typer.Option(exists=True, dir_okay=False, help="Completed discovery JSON")
    ],
    output_root: Annotated[
        Path, typer.Option(help="Root directory for deterministic job bundles")
    ] = DEFAULT_JOB_OUTPUT,
) -> None:
    """Split a completed discovery manifest into resumable detail jobs."""
    result = create_job_bundle(load_discovery(discovery), output_root)
    manifest = result["manifest"]
    state = result["state"]
    assert isinstance(manifest, dict) and isinstance(state, dict)
    typer.echo(
        json.dumps(
            {
                "bundle_dir": result["bundle_dir"],
                "page_count": manifest["page_count"],
                "job_count": manifest["job_count"],
                "state": state,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("job-status")
def job_status(
    bundle: Annotated[Path, typer.Option(exists=True, file_okay=False)],
) -> None:
    """Rebuild and print aggregate progress from individual job states."""
    typer.echo(json.dumps(summarize_job_bundle(bundle), ensure_ascii=False, indent=2))


@app.command("job-next")
def job_next(
    bundle: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    claim: Annotated[
        bool, typer.Option(help="Atomically mark the returned job in_progress")
    ] = False,
) -> None:
    """Print the next pending/retryable job, optionally claiming it."""
    if claim:
        job = claim_next_job(bundle)
    else:
        job = summarize_job_bundle(bundle)["next_job"]
    typer.echo(json.dumps(job, ensure_ascii=False, indent=2))


@app.command("job-update")
def job_update(
    bundle: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    job_id: Annotated[str, typer.Option()],
    status: Annotated[
        str,
        typer.Option(
            help=(
                "pending/in_progress/completed/content_unavailable/skipped/"
                "retryable/failed"
            )
        ),
    ],
    error: Annotated[str | None, typer.Option()] = None,
    output_directory: Annotated[str | None, typer.Option()] = None,
) -> None:
    """Persist a job result and refresh the aggregate resume state."""
    if status not in JOB_STATUSES:
        choices = ", ".join(sorted(JOB_STATUSES))
        raise typer.BadParameter(f"status must be one of: {choices}")
    job = update_job_status(
        bundle,
        job_id,
        cast(JobStatus, status),
        error=error,
        output_directory=output_directory,
    )
    typer.echo(json.dumps(job, ensure_ascii=False, indent=2))


@app.command("crawl-jobs")
def crawl_jobs(
    bundle: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    max_jobs: Annotated[int, typer.Option(min=1)] = 20,
    max_attempts: Annotated[int, typer.Option(min=1)] = 3,
    max_failures: Annotated[int, typer.Option(min=1)] = 3,
    output: Annotated[Path, typer.Option()] = DEFAULT_OUTPUT,
    metadata_only_output: Annotated[
        Path, typer.Option(help="Output for detail metadata without HTML full text")
    ] = DEFAULT_METADATA_ONLY_OUTPUT,
    min_request_delay: Annotated[
        float, typer.Option(min=0)
    ] = DEFAULT_MIN_REQUEST_DELAY,
    max_request_delay: Annotated[
        float, typer.Option(min=0)
    ] = DEFAULT_MAX_REQUEST_DELAY,
    request_budget: Annotated[int, typer.Option(min=1)] = 25,
    daily_request_budget: Annotated[int, typer.Option(min=1)] = 100,
    block_cooldown_hours: Annotated[int, typer.Option(min=1)] = 24,
    profile: Annotated[Path, typer.Option()] = DEFAULT_PROFILE,
    headless: Annotated[bool, typer.Option()] = False,
    quiet: Annotated[
        bool,
        typer.Option(help="Suppress per-job progress logs; keep final JSON report"),
    ] = False,
) -> None:
    """Resume detail crawling from a prepared job bundle."""
    safety_policy = RequestSafetyPolicy(
        state_path=DEFAULT_STATE,
        min_delay_seconds=min_request_delay,
        max_delay_seconds=max_request_delay,
        per_run_budget=request_budget,
        daily_budget=daily_request_budget,
        block_cooldown_seconds=block_cooldown_hours * 3600,
    )
    with RunLock(DEFAULT_LOCK):
        with BrowserSession(
            profile_dir=profile,
            safety_policy=safety_policy,
            headless=headless,
            browser_channel="chrome",
        ) as browser:
            report = crawl_job_bundle(
                fetcher=browser,
                bundle_dir=bundle,
                output_root=output,
                metadata_only_root=metadata_only_output,
                max_jobs=max_jobs,
                max_attempts=max_attempts,
                max_failures=max_failures,
                progress_callback=None if quiet else _render_crawl_progress,
            )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failed"] or report["retryable"]:
        raise typer.Exit(code=2)


@app.command("migrate-job-states")
def migrate_job_states(
    bundle: Annotated[Path, typer.Option(exists=True, file_okay=False)],
) -> None:
    """Idempotently reclassify legacy ContentUnavailable job failures."""
    result = migrate_content_unavailable_jobs(bundle)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("requeue-stale-content")
def requeue_stale_content(
    bundle: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    apply: Annotated[
        bool,
        typer.Option(help="Apply requeue; default only reports stale completed jobs"),
    ] = False,
) -> None:
    """Requeue completed jobs written by an older content serializer."""
    result = requeue_stale_content_jobs(bundle, apply=apply)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


def _render_crawl_progress(progress: CrawlProgress) -> None:
    if progress.event == "worker_started":
        counts = progress.counts or {}
        typer.echo(
            "[START] "
            f"jobs={progress.job_count} pending={counts.get('pending', 0)} "
            f"retryable={counts.get('retryable', 0)}"
        )
        return
    if progress.event == "worker_finished":
        counts = progress.counts or {}
        next_rank = progress.next_rank if progress.next_rank is not None else "none"
        typer.echo(
            "[DONE] "
            f"completed={counts.get('completed', 0)} "
            f"unavailable={counts.get('content_unavailable', 0)} "
            f"skipped={counts.get('skipped', 0)} "
            f"retryable={counts.get('retryable', 0)} "
            f"failed={counts.get('failed', 0)} next_rank={next_rank}"
        )
        return

    prefix = f"[{progress.rank}/{progress.job_count}] {progress.job_id}"
    if progress.event == "job_started":
        typer.echo(f"{prefix} fetching page={progress.page_index}")
    elif progress.event == "job_completed":
        typer.echo(
            f"{prefix} completed chars={progress.content_character_count} "
            f"articles={progress.article_count} "
            f"references={progress.reference_marker_count}"
        )
    elif progress.event == "content_unavailable":
        typer.echo(f"{prefix} content_unavailable metadata-only")
    elif progress.event == "job_skipped":
        typer.echo(f"{prefix} skipped reason={progress.reason} metadata-only")
    elif progress.event in {"job_retryable", "job_failed"}:
        status = progress.event.removeprefix("job_")
        typer.echo(
            f"{prefix} {status} attempt={progress.attempts} error={progress.reason}"
        )


@app.command("metadata-list")
def metadata_list(
    url: Annotated[str, typer.Option(help="Full LuatVietnam search-results URL")],
    max_pages: Annotated[
        int | None,
        typer.Option(min=1, help="Optional page cap; default uses site pagination"),
    ] = None,
    max_documents: Annotated[int, typer.Option(min=1)] = 5,
    output: Annotated[
        Path, typer.Option(help="Destination enriched JSON manifest")
    ] = DEFAULT_METADATA_LIST_OUTPUT,
    min_request_delay: Annotated[
        float, typer.Option(min=0)
    ] = DEFAULT_MIN_REQUEST_DELAY,
    max_request_delay: Annotated[
        float, typer.Option(min=0)
    ] = DEFAULT_MAX_REQUEST_DELAY,
    request_budget: Annotated[int, typer.Option(min=1)] = 6,
    daily_request_budget: Annotated[int, typer.Option(min=1)] = 100,
    block_cooldown_hours: Annotated[int, typer.Option(min=1)] = 24,
    max_failures: Annotated[int, typer.Option(min=1)] = 3,
    profile: Annotated[
        Path, typer.Option(help="Persistent system Chrome profile and cookies")
    ] = DEFAULT_PROFILE,
    headless: Annotated[
        bool, typer.Option(help="Run without the visible system Chrome window")
    ] = False,
) -> None:
    """Save discovery rows enriched with metadata from detail pages."""
    safety_policy = RequestSafetyPolicy(
        state_path=DEFAULT_STATE,
        min_delay_seconds=min_request_delay,
        max_delay_seconds=max_request_delay,
        per_run_budget=request_budget,
        daily_budget=daily_request_budget,
        block_cooldown_seconds=block_cooldown_hours * 3600,
    )
    with RunLock(DEFAULT_LOCK):
        with BrowserSession(
            profile_dir=profile,
            safety_policy=safety_policy,
            headless=headless,
            browser_channel="chrome",
        ) as browser:
            manifest = build_metadata_list(
                url,
                fetcher=browser,
                max_pages=max_pages,
                max_documents=max_documents,
                delay_seconds=0,
                max_failures=max_failures,
            )
    write_report(manifest, output)
    typer.echo(
        json.dumps(
            {
                "output": str(output.resolve()),
                "document_count": manifest["document_count"],
                "metadata_enriched_count": manifest["metadata_enriched_count"],
                "metadata_failure_count": manifest["metadata_failure_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if manifest["metadata_failure_count"]:
        raise typer.Exit(code=2)


@app.command()
def crawl(
    url: Annotated[str, typer.Option(help="Full LuatVietnam search-results URL")],
    max_pages: Annotated[
        int | None,
        typer.Option(min=1, help="Optional page cap; default uses site pagination"),
    ] = None,
    max_documents: Annotated[int, typer.Option(min=1)] = 20,
    min_request_delay: Annotated[
        float, typer.Option(min=0)
    ] = DEFAULT_MIN_REQUEST_DELAY,
    max_request_delay: Annotated[
        float, typer.Option(min=0)
    ] = DEFAULT_MAX_REQUEST_DELAY,
    request_budget: Annotated[int, typer.Option(min=1)] = 25,
    daily_request_budget: Annotated[int, typer.Option(min=1)] = 100,
    block_cooldown_hours: Annotated[int, typer.Option(min=1)] = 24,
    max_failures: Annotated[int, typer.Option(min=1)] = 3,
    output: Annotated[
        Path, typer.Option(help="Isolated raw output directory")
    ] = DEFAULT_OUTPUT,
    profile: Annotated[
        Path, typer.Option(help="Persistent system Chrome profile and cookies")
    ] = DEFAULT_PROFILE,
    overwrite: Annotated[
        bool, typer.Option(help="Replace already crawled documents")
    ] = False,
    fail_fast: Annotated[
        bool, typer.Option(help="Stop on the first failed detail page")
    ] = False,
    headless: Annotated[
        bool, typer.Option(help="Run without the visible system Chrome window")
    ] = False,
) -> None:
    """Enumerate the search pages and save each legal document."""
    safety_policy = RequestSafetyPolicy(
        state_path=DEFAULT_STATE,
        min_delay_seconds=min_request_delay,
        max_delay_seconds=max_request_delay,
        per_run_budget=request_budget,
        daily_budget=daily_request_budget,
        block_cooldown_seconds=block_cooldown_hours * 3600,
    )
    with RunLock(DEFAULT_LOCK):
        with BrowserSession(
            profile_dir=profile,
            safety_policy=safety_policy,
            headless=headless,
            browser_channel="chrome",
        ) as browser:
            report = crawl_search(
                url,
                fetcher=browser,
                output_root=output,
                max_pages=max_pages,
                max_documents=max_documents,
                delay_seconds=0,
                overwrite=overwrite,
                fail_fast=fail_fast,
                max_failures=max_failures,
            )
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))
    if report["failures"]:
        raise typer.Exit(code=2)


@app.command("enrich-vbpl")
def enrich_vbpl(
    raw_dir: Annotated[
        Path, typer.Option(help="Path to raw documents output directory")
    ] = DEFAULT_OUTPUT,
    skip_existing: Annotated[
        bool, typer.Option(help="Skip documents that already have properties.json and diagram.json")
    ] = True,
    max_documents: Annotated[
        int | None, typer.Option(help="Limit max documents to enrich")
    ] = None,
    delay: Annotated[
        float, typer.Option(min=0.0, help="Delay in seconds between document requests per worker")
    ] = 0.0,
    concurrency: Annotated[
        int, typer.Option(min=1, max=16, help="Number of parallel worker threads")
    ] = 4,
    batch_size: Annotated[
        int, typer.Option(min=1, help="Number of documents per batch across workers")
    ] = 50,
    batch_delay: Annotated[
        float, typer.Option(min=0.0, help="Delay in seconds between batches")
    ] = 10.0,
) -> None:
    """Enrich LuatVietnam raw document folders with properties.json and diagram.json from VBPL by querying document number in multithreading & batch mode."""
    from .vbpl_enricher import enrich_documents

    stats = enrich_documents(
        raw_dir,
        skip_existing=skip_existing,
        max_documents=max_documents,
        delay_seconds=delay,
        concurrency=concurrency,
        batch_size=batch_size,
        batch_delay_seconds=batch_delay,
    )
    typer.echo(json.dumps(stats, ensure_ascii=False, indent=2))


@app.command("resolve-diagram-items")
def resolve_diagram_items_cli(
    raw_dir: Annotated[
        Path, typer.Option(help="Path to raw documents output directory")
    ] = DEFAULT_OUTPUT,
    skip_existing: Annotated[
        bool, typer.Option(help="Skip document folders that have already been resolved")
    ] = True,
    max_documents: Annotated[
        int | None, typer.Option(help="Limit max diagram files to resolve")
    ] = None,
    delay: Annotated[
        float, typer.Option(min=0.0, help="Delay in seconds between title resolution requests")
    ] = 0.0,
    concurrency: Annotated[
        int, typer.Option(min=1, max=16, help="Number of parallel worker threads")
    ] = 4,
    batch_size: Annotated[
        int, typer.Option(min=1, help="Number of diagram files per batch across workers")
    ] = 50,
    batch_delay: Annotated[
        float, typer.Option(min=0.0, help="Delay in seconds between batches")
    ] = 10.0,
) -> None:
    """Resolve missing URL and number for items in diagram.json by querying Title on VBPL with Checkpoint & Cache."""
    from .diagram_item_resolver import resolve_diagram_items

    stats = resolve_diagram_items(
        raw_dir,
        skip_existing=skip_existing,
        max_documents=max_documents,
        delay_seconds=delay,
        concurrency=concurrency,
        batch_size=batch_size,
        batch_delay_seconds=batch_delay,
    )
    typer.echo(json.dumps(stats, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    app()
