"""Batch orchestration for a LuatVietnam search URL."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .errors import ContentUnavailableError, PageBlockedError
from .jobs import claim_next_job, summarize_job_bundle, update_job_status
from .models import SearchDocument, SearchPageMetadata
from .parser import (
    page_url,
    is_not_approved_status,
    parse_detail_metadata,
    parse_document,
    parse_search_page_metadata,
    parse_search_results,
)
from .storage import save_document, save_metadata_only, write_report


class HtmlFetcher(Protocol):
    def get_html(self, url: str) -> str: ...


@dataclass(frozen=True, slots=True)
class CrawlProgress:
    event: str
    job_count: int
    job_id: str | None = None
    rank: int | None = None
    page_index: int | None = None
    attempts: int | None = None
    content_character_count: int | None = None
    article_count: int | None = None
    reference_marker_count: int | None = None
    reason: str | None = None
    counts: dict[str, int] | None = None
    next_rank: int | None = None


ProgressCallback = Callable[[CrawlProgress], None]


def crawl_job_bundle(
    *,
    fetcher: HtmlFetcher,
    bundle_dir: Path,
    output_root: Path,
    metadata_only_root: Path | None = None,
    max_jobs: int = 20,
    max_attempts: int = 3,
    max_failures: int = 3,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, object]:
    """Consume resumable detail jobs without loading search pages again."""
    if max_jobs < 1 or max_attempts < 1 or max_failures < 1:
        raise ValueError("Job and failure limits must be at least 1")

    completed: list[str] = []
    content_unavailable: list[dict[str, str]] = []
    retryable: list[dict[str, str]] = []
    failed: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    attempted_job_ids: set[str] = set()
    stopped_early = False
    initial_state = summarize_job_bundle(bundle_dir)
    job_count = int(initial_state["job_count"])
    _emit_progress(
        progress_callback,
        CrawlProgress(
            event="worker_started",
            job_count=job_count,
            counts=_integer_counts(initial_state.get("counts")),
        ),
    )
    for _ in range(max_jobs):
        job = claim_next_job(bundle_dir, exclude_job_ids=attempted_job_ids)
        if job is None:
            break
        job_id = str(job["job_id"])
        attempted_job_ids.add(job_id)
        source = job.get("source")
        state = job.get("state")
        if not isinstance(source, dict) or not isinstance(state, dict):
            raise ValueError(f"Malformed claimed job: {job_id}")
        url = str(source["url"])
        rank = int(job["rank"])
        page_index = int(job["page_index"])
        attempts = int(state.get("attempts", 1))
        _emit_progress(
            progress_callback,
            CrawlProgress(
                event="job_started",
                job_count=job_count,
                job_id=job_id,
                rank=rank,
                page_index=page_index,
                attempts=attempts,
            ),
        )
        try:
            html = fetcher.get_html(url)
            metadata = parse_detail_metadata(html, url)
            if is_not_approved_status(metadata.status_raw):
                metadata_dir = save_metadata_only(
                    metadata,
                    metadata_only_root or output_root.parent / "metadata-only",
                    skip_reason="not_approved",
                )
                update_job_status(
                    bundle_dir,
                    job_id,
                    "skipped",
                    error="not_approved",
                    metadata_only_directory=str(metadata_dir),
                )
                skipped.append(
                    {
                        "job_id": job_id,
                        "url": url,
                        "metadata_directory": str(metadata_dir),
                        "reason": "not_approved",
                    }
                )
                _emit_progress(
                    progress_callback,
                    CrawlProgress(
                        event="job_skipped",
                        job_count=job_count,
                        job_id=job_id,
                        rank=rank,
                        page_index=page_index,
                        attempts=attempts,
                        reason="not_approved",
                    ),
                )
                continue
            document = parse_document(html, url, metadata=metadata)
            document_dir = save_document(document, output_root, source_html=html)
            update_job_status(
                bundle_dir,
                job_id,
                "completed",
                output_directory=str(document_dir),
                content_serializer_version=document.content_serializer_version,
                content_character_count=len(document.source_text),
                article_count=document.article_count,
                reference_marker_count=document.reference_marker_count,
                raw_html_saved=True,
            )
            completed.append(job_id)
            _emit_progress(
                progress_callback,
                CrawlProgress(
                    event="job_completed",
                    job_count=job_count,
                    job_id=job_id,
                    rank=rank,
                    page_index=page_index,
                    attempts=attempts,
                    content_character_count=len(document.source_text),
                    article_count=document.article_count,
                    reference_marker_count=document.reference_marker_count,
                ),
            )
        except ContentUnavailableError as exc:
            metadata = parse_detail_metadata(html, url)
            metadata_dir = save_metadata_only(
                metadata,
                metadata_only_root or output_root.parent / "metadata-only",
                source_html=html,
            )
            error = f"{type(exc).__name__}: {exc}"
            update_job_status(
                bundle_dir,
                job_id,
                "content_unavailable",
                error=error,
                metadata_only_directory=str(metadata_dir),
            )
            content_unavailable.append(
                {
                    "job_id": job_id,
                    "url": url,
                    "metadata_directory": str(metadata_dir),
                    "reason": error,
                }
            )
            _emit_progress(
                progress_callback,
                CrawlProgress(
                    event="content_unavailable",
                    job_count=job_count,
                    job_id=job_id,
                    rank=rank,
                    page_index=page_index,
                    attempts=attempts,
                    reason=error,
                ),
            )
        except PageBlockedError as exc:
            update_job_status(bundle_dir, job_id, "retryable", error=str(exc))
            _emit_progress(
                progress_callback,
                CrawlProgress(
                    event="job_retryable",
                    job_count=job_count,
                    job_id=job_id,
                    rank=rank,
                    page_index=page_index,
                    attempts=attempts,
                    reason=type(exc).__name__,
                ),
            )
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            attempts = int(state.get("attempts", 1))
            if attempts >= max_attempts:
                update_job_status(bundle_dir, job_id, "failed", error=error)
                failed.append({"job_id": job_id, "url": url, "error": error})
                event = "job_failed"
            else:
                update_job_status(bundle_dir, job_id, "retryable", error=error)
                retryable.append({"job_id": job_id, "url": url, "error": error})
                event = "job_retryable"
            _emit_progress(
                progress_callback,
                CrawlProgress(
                    event=event,
                    job_count=job_count,
                    job_id=job_id,
                    rank=rank,
                    page_index=page_index,
                    attempts=attempts,
                    reason=type(exc).__name__,
                ),
            )
            if len(retryable) + len(failed) >= max_failures:
                stopped_early = True
                break

    report = {
        "bundle_dir": str(bundle_dir.resolve()),
        "completed": completed,
        "content_unavailable": content_unavailable,
        "skipped": skipped,
        "retryable": retryable,
        "failed": failed,
        "stopped_early": stopped_early,
        "state": summarize_job_bundle(bundle_dir),
    }
    write_report(report, bundle_dir / "last_worker_run.json")
    state = report["state"]
    assert isinstance(state, dict)
    next_job = state.get("next_job")
    _emit_progress(
        progress_callback,
        CrawlProgress(
            event="worker_finished",
            job_count=job_count,
            counts=_integer_counts(state.get("counts")),
            next_rank=(
                int(next_job["rank"])
                if isinstance(next_job, dict) and next_job.get("rank") is not None
                else None
            ),
        ),
    )
    return report


def _emit_progress(callback: ProgressCallback | None, event: CrawlProgress) -> None:
    if callback is not None:
        callback(event)


def _integer_counts(value: object) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    return {str(key): int(count) for key, count in value.items()}


def discover_search_results(
    search_url: str,
    *,
    fetcher: HtmlFetcher,
    max_pages: int | None = None,
    max_documents: int | None = None,
    delay_seconds: float = 1.0,
) -> dict[str, object]:
    """Return a stable JSON-ready manifest without opening detail pages."""
    (
        entries,
        pages_visited,
        page_metadata,
        pages_planned,
        duplicate_occurrences,
    ) = _collect_search_results(
        search_url,
        fetcher=fetcher,
        max_pages=max_pages,
        max_documents=max_documents,
        delay_seconds=delay_seconds,
    )
    documents = [
        {
            "rank": rank,
            "page_index": page_index,
            "external_id": entry.external_id,
            "detail_variant": entry.detail_variant,
            "source_kind": entry.source_kind,
            "title": entry.title,
            "url": entry.url,
        }
        for rank, (entry, page_index) in enumerate(entries, start=1)
    ]
    return {
        "schema_version": "luatvietnam-discovery-v3",
        "source_provider": "luatvietnam.vn",
        "search_url": search_url,
        "pages_visited": pages_visited,
        "pages_planned": pages_planned,
        "pagination": page_metadata.as_dict() if page_metadata else None,
        "truncated_by_document_limit": (
            max_documents is not None
            and page_metadata is not None
            and max_documents < page_metadata.total_results
        ),
        "document_count": len(documents),
        "result_occurrence_count": len(documents) + len(duplicate_occurrences),
        "duplicate_occurrence_count": len(duplicate_occurrences),
        "duplicate_occurrences": duplicate_occurrences,
        "matches_site_total": (
            page_metadata is not None
            and pages_visited == pages_planned
            and len(documents) + len(duplicate_occurrences)
            == page_metadata.total_results
        ),
        "documents": documents,
    }


def build_metadata_list(
    search_url: str,
    *,
    fetcher: HtmlFetcher,
    max_pages: int | None = None,
    max_documents: int = 20,
    delay_seconds: float = 1.0,
    max_failures: int = 3,
) -> dict[str, object]:
    """Discover documents and attach metadata parsed from each detail page."""
    if max_failures < 1:
        raise ValueError("max_failures must be at least 1")
    manifest = discover_search_results(
        search_url,
        fetcher=fetcher,
        max_pages=max_pages,
        max_documents=max_documents,
        delay_seconds=delay_seconds,
    )
    documents = manifest["documents"]
    assert isinstance(documents, list)
    failures: list[dict[str, str]] = []
    enriched = 0
    stopped_early = False
    for index, item in enumerate(documents):
        assert isinstance(item, dict)
        url = item["url"]
        assert isinstance(url, str)
        try:
            if delay_seconds:
                time.sleep(delay_seconds)
            metadata = parse_detail_metadata(fetcher.get_html(url), url)
            item["metadata_status"] = "ok"
            item["detail_metadata"] = metadata.as_dict()
            enriched += 1
        except PageBlockedError:
            raise
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            item["metadata_status"] = "error"
            item["metadata_error"] = error
            failures.append({"url": url, "error": error})
            if len(failures) >= max_failures:
                stopped_early = True
                for pending in documents[index + 1 :]:
                    pending["metadata_status"] = "pending"
                break

    manifest.update(
        {
            "schema_version": "luatvietnam-metadata-list-v3",
            "metadata_enriched_count": enriched,
            "metadata_failure_count": len(failures),
            "metadata_failures": failures,
            "stopped_early": stopped_early,
        }
    )
    return manifest


def crawl_search(
    search_url: str,
    *,
    fetcher: HtmlFetcher,
    output_root: Path,
    max_pages: int | None = None,
    max_documents: int = 100,
    delay_seconds: float = 1.0,
    overwrite: bool = False,
    fail_fast: bool = False,
    max_failures: int = 3,
) -> dict[str, object]:
    if max_failures < 1:
        raise ValueError("max_failures must be at least 1")

    (
        discovered_entries,
        pages_visited,
        page_metadata,
        pages_planned,
        duplicate_occurrences,
    ) = _collect_search_results(
        search_url,
        fetcher=fetcher,
        max_pages=max_pages,
        max_documents=max_documents,
        delay_seconds=delay_seconds,
    )
    discovered = {entry.url: entry for entry, _page_index in discovered_entries}

    saved: list[str] = []
    skipped: list[str] = []
    failures: list[dict[str, str]] = []
    stopped_early = False
    for url, entry in list(discovered.items())[:max_documents]:
        external_id = entry.external_id
        expected_dir = output_root / f"LTV_{external_id}"
        if external_id and not overwrite and (expected_dir / "metadata.json").exists():
            skipped.append(url)
            continue
        try:
            if delay_seconds:
                time.sleep(delay_seconds)
            html = fetcher.get_html(url)
            metadata = parse_detail_metadata(html, url)
            if is_not_approved_status(metadata.status_raw):
                save_metadata_only(
                    metadata,
                    output_root.parent / "metadata-only",
                    skip_reason="not_approved",
                )
                skipped.append(url)
                continue
            document = parse_document(html, url, metadata=metadata)
            save_document(document, output_root, source_html=html)
            saved.append(document.raw_doc_code)
        except PageBlockedError:
            raise
        except Exception as exc:
            failures.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})
            if fail_fast:
                raise
            if len(failures) >= max_failures:
                stopped_early = True
                break

    report: dict[str, object] = {
        "search_url": search_url,
        "pages_visited": pages_visited,
        "pages_planned": pages_planned,
        "pagination": page_metadata.as_dict() if page_metadata else None,
        "discovered": len(discovered),
        "result_occurrence_count": len(discovered) + len(duplicate_occurrences),
        "duplicate_occurrence_count": len(duplicate_occurrences),
        "duplicate_occurrences": duplicate_occurrences,
        "saved": saved,
        "skipped": skipped,
        "failures": failures,
        "stopped_early": stopped_early,
    }
    write_report(report, output_root.parent / "last_run.json")
    return report


def _collect_search_results(
    search_url: str,
    *,
    fetcher: HtmlFetcher,
    max_pages: int | None,
    max_documents: int | None,
    delay_seconds: float,
) -> tuple[
    list[tuple[SearchDocument, int]],
    int,
    SearchPageMetadata | None,
    int,
    list[dict[str, object]],
]:
    if max_pages is not None and max_pages < 1:
        raise ValueError("max_pages must be at least 1")
    if max_documents is not None and max_documents < 1:
        raise ValueError("max_documents must be at least 1")
    if delay_seconds < 0:
        raise ValueError("delay_seconds cannot be negative")

    discovered: list[tuple[SearchDocument, int]] = []
    seen: set[str] = set()
    first_seen_page: dict[str, int] = {}
    duplicate_occurrences: list[dict[str, object]] = []
    pages_visited = 0
    first_html = fetcher.get_html(page_url(search_url, 1))
    first_page_metadata = parse_search_page_metadata(first_html)
    pages_planned = (
        first_page_metadata.total_pages
        if first_page_metadata
        else (max_pages if max_pages is not None else 1)
    )
    if max_pages is not None:
        pages_planned = min(pages_planned, max_pages)
    if max_documents is not None and first_page_metadata is not None:
        document_pages = (
            max_documents + first_page_metadata.page_size - 1
        ) // first_page_metadata.page_size
        pages_planned = min(pages_planned, document_pages)

    for index in range(1, pages_planned + 1):
        if index == 1:
            html = first_html
        else:
            page_size = first_page_metadata.page_size if first_page_metadata else None
            html = fetcher.get_html(page_url(search_url, index, page_size=page_size))
        current_metadata = parse_search_page_metadata(html)
        if current_metadata is not None and current_metadata.current_page != index:
            raise ValueError(
                f"Expected search page {index}, got {current_metadata.current_page}"
            )
        entries = parse_search_results(html, search_url)
        pages_visited += 1
        new_count = 0
        for entry in entries:
            if entry.url not in seen:
                seen.add(entry.url)
                first_seen_page[entry.url] = index
                discovered.append((entry, index))
                new_count += 1
            else:
                duplicate_occurrences.append(
                    {
                        "external_id": entry.external_id,
                        "url": entry.url,
                        "title": entry.title,
                        "first_page_index": first_seen_page[entry.url],
                        "duplicate_page_index": index,
                    }
                )
            if max_documents is not None and len(discovered) >= max_documents:
                break
        reached_document_limit = (
            max_documents is not None and len(discovered) >= max_documents
        )
        if reached_document_limit or not entries or new_count == 0:
            break
        if delay_seconds and index < pages_planned:
            time.sleep(delay_seconds)
    return (
        discovered,
        pages_visited,
        first_page_metadata,
        pages_planned,
        duplicate_occurrences,
    )
