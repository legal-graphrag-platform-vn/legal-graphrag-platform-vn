from __future__ import annotations

import json
from pathlib import Path

import pytest

from experiments.luatvietnam_crawler.crawler import (
    CrawlProgress,
    build_metadata_list,
    crawl_job_bundle,
    crawl_search,
    discover_search_results,
)
from experiments.luatvietnam_crawler.errors import PageBlockedError
from experiments.luatvietnam_crawler.jobs import create_job_bundle
from experiments.luatvietnam_crawler.parser import page_url


SEARCH_URL = "https://luatvietnam.vn/van-ban/tim-van-ban.html?PageSize=100&PageIndex=1"
DETAIL_URL = "https://luatvietnam.vn/doanh-nghiep/luat-doanh-nghiep-2020-186270-d1.html"


def _card(url: str, title: str) -> str:
    return f'<article class="art-search"><h2 class="doc-title"><a href="{url}">{title}</a></h2></article>'


class FakeFetcher:
    def __init__(self, responses: dict[str, str]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def get_html(self, url: str) -> str:
        self.calls.append(url)
        return self.responses[url]


def _detail_html() -> str:
    return """
    <h1>Luật Doanh nghiệp số 59/2020/QH14</h1>
    <table>
      <tr><th>Số hiệu:</th><td>59/2020/QH14</td></tr>
      <tr><th>Cơ quan ban hành:</th><td>Quốc hội</td></tr>
      <tr><th>Ngày có hiệu lực:</th><td>01/01/2021</td></tr>
    </table>
    <div class="the-document-body">Điều 1. Phạm vi\nNội dung.</div>
    """


def _unavailable_detail_html() -> str:
    return """
    <h1>Quyết định 1995/QĐ-BTC năm 2026</h1>
    <table>
      <tr><th>Số hiệu:</th><td>1995/QĐ-BTC</td></tr>
      <tr><th>Cơ quan ban hành:</th><td>Bộ Tài chính</td></tr>
      <tr><th>Ngày ban hành:</th><td>01/07/2026</td></tr>
    </table>
    <div class="the-document-body">
      Văn bản này đang cập nhật nội dung.
      Mời quý khách xem nội dung văn bản dưới dạng file PDF.
    </div>
    """


def _not_approved_detail_html() -> str:
    return """
    <h1>Dự thảo Nghị định số 10/2026/NĐ-CP</h1>
    <table>
      <tr><th>Số hiệu:</th><td>10/2026/NĐ-CP</td></tr>
      <tr><th>Trạng thái:</th><td>Chưa thông qua</td></tr>
    </table>
    <div class="the-document-body">Điều 1. Nội dung dự thảo.</div>
    """


def _search_page(
    cards: str, *, total_results: int, current_page: int, page_size: int = 100
) -> str:
    return f"""
    <div id="search_results">
      <div class="block-text-resut"><div class="s-text1">
        Có <strong>{total_results:,}</strong> văn bản;
        loại văn bản: Luật; cơ quan ban hành: Quốc hội;
        lĩnh vực: Doanh nghiệp; ngôn ngữ: Tiếng Việt
      </div></div>
      {cards}
    </div>
    <div class="pagination padding">
      <div class="pag-select"><select>
        <option selected="active">{page_size} kết quả</option>
      </select></div>
      <span class="page-numbers active" title="Trang {current_page}">{current_page}</span>
    </div>
    """


def test_discovery_manifest_lists_results_without_opening_details() -> None:
    second_url = DETAIL_URL.replace("186270", "186271")
    fetcher = FakeFetcher(
        {
            SEARCH_URL: (
                _card(DETAIL_URL, "Luật doanh nghiệp")
                + _card(second_url, "Nghị định hướng dẫn")
            )
        }
    )

    manifest = discover_search_results(
        SEARCH_URL,
        fetcher=fetcher,
        max_documents=100,
        delay_seconds=0,
    )

    assert manifest["schema_version"] == "luatvietnam-discovery-v3"
    assert manifest["document_count"] == 2
    assert manifest["documents"] == [
        {
            "rank": 1,
            "page_index": 1,
            "external_id": "186270",
            "detail_variant": "d1",
            "source_kind": "issued_document",
            "title": "Luật doanh nghiệp",
            "url": DETAIL_URL,
        },
        {
            "rank": 2,
            "page_index": 1,
            "external_id": "186271",
            "detail_variant": "d1",
            "source_kind": "issued_document",
            "title": "Nghị định hướng dẫn",
            "url": second_url,
        },
    ]
    assert fetcher.calls == [SEARCH_URL]


def test_discovery_manifest_deduplicates_across_pages() -> None:
    page_two = SEARCH_URL.replace("PageIndex=1", "PageIndex=2")
    listing = _card(DETAIL_URL, "Luật doanh nghiệp")
    fetcher = FakeFetcher({SEARCH_URL: listing, page_two: listing})

    manifest = discover_search_results(
        SEARCH_URL,
        fetcher=fetcher,
        max_pages=5,
        delay_seconds=0,
    )

    assert manifest["pages_visited"] == 2
    assert manifest["document_count"] == 1
    assert manifest["result_occurrence_count"] == 2
    assert manifest["duplicate_occurrence_count"] == 1
    assert manifest["duplicate_occurrences"] == [
        {
            "external_id": "186270",
            "url": DETAIL_URL,
            "title": "Luật doanh nghiệp",
            "first_page_index": 1,
            "duplicate_page_index": 2,
        }
    ]


def test_discovery_automatically_crawls_pages_from_total_results() -> None:
    urls = [DETAIL_URL.replace("186270", str(186270 + index)) for index in range(3)]
    page_two = page_url(SEARCH_URL, 2, page_size=100)
    page_three = page_url(SEARCH_URL, 3, page_size=100)
    fetcher = FakeFetcher(
        {
            SEARCH_URL: _search_page(
                _card(urls[0], "First"), total_results=201, current_page=1
            ),
            page_two: _search_page(
                _card(urls[1], "Second"), total_results=201, current_page=2
            ),
            page_three: _search_page(
                _card(urls[2], "Third"), total_results=201, current_page=3
            ),
        }
    )

    manifest = discover_search_results(SEARCH_URL, fetcher=fetcher, delay_seconds=0)

    assert manifest["pages_planned"] == 3
    assert manifest["pages_visited"] == 3
    assert manifest["pagination"]["total_results"] == 201
    assert manifest["pagination"]["page_size"] == 100
    assert manifest["pagination"]["total_pages"] == 3
    assert manifest["document_count"] == 3
    assert fetcher.calls == [SEARCH_URL, page_two, page_three]


def test_discovery_document_limit_reduces_automatically_planned_pages() -> None:
    first_cards = "".join(
        _card(DETAIL_URL.replace("186270", str(200000 + index)), f"Doc {index}")
        for index in range(100)
    )
    second_cards = "".join(
        _card(DETAIL_URL.replace("186270", str(300000 + index)), f"Doc {index}")
        for index in range(100)
    )
    page_two = page_url(SEARCH_URL, 2, page_size=100)
    fetcher = FakeFetcher(
        {
            SEARCH_URL: _search_page(first_cards, total_results=3353, current_page=1),
            page_two: _search_page(second_cards, total_results=3353, current_page=2),
        }
    )

    manifest = discover_search_results(
        SEARCH_URL, fetcher=fetcher, max_documents=150, delay_seconds=0
    )

    assert manifest["pages_planned"] == 2
    assert manifest["pages_visited"] == 2
    assert manifest["document_count"] == 150
    assert manifest["truncated_by_document_limit"] is True


def test_metadata_list_attaches_detail_metadata() -> None:
    fetcher = FakeFetcher(
        {
            SEARCH_URL: _card(DETAIL_URL, "Luật doanh nghiệp"),
            DETAIL_URL: _detail_html(),
        }
    )

    manifest = build_metadata_list(
        SEARCH_URL,
        fetcher=fetcher,
        max_documents=1,
        delay_seconds=0,
    )

    assert manifest["schema_version"] == "luatvietnam-metadata-list-v3"
    assert manifest["metadata_enriched_count"] == 1
    assert manifest["metadata_failure_count"] == 0
    item = manifest["documents"][0]
    assert item["metadata_status"] == "ok"
    assert item["detail_metadata"]["number"] == "59/2020/QH14"
    assert item["detail_metadata"]["issuer_name"] == "Quốc hội"
    assert item["detail_metadata"]["content"]["html_full_text_available"] is True
    assert item["detail_metadata"]["content"]["article_count"] == 1
    assert item["detail_metadata"]["content"]["character_count"] > 20
    assert fetcher.calls == [SEARCH_URL, DETAIL_URL]


def test_crawl_search_saves_inside_isolated_output(tmp_path: Path) -> None:
    fetcher = FakeFetcher(
        {
            SEARCH_URL: _card(DETAIL_URL, "Luật doanh nghiệp"),
            DETAIL_URL: _detail_html(),
        }
    )

    report = crawl_search(
        SEARCH_URL,
        fetcher=fetcher,
        output_root=tmp_path / "output" / "raw",
        delay_seconds=0,
    )

    document_dir = tmp_path / "output" / "raw" / "LTV_186270"
    assert (
        (document_dir / "source.txt").read_text(encoding="utf-8").startswith("Điều 1")
    )
    assert (document_dir / "source.html").read_text(encoding="utf-8") == _detail_html()
    assert (document_dir / "references.jsonl").exists()
    metadata = json.loads((document_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["source_provider"] == "luatvietnam.vn"
    assert metadata["content"]["raw_html_saved"] is True
    assert report["saved"] == ["LTV_186270"]
    assert report["failures"] == []
    assert (tmp_path / "output" / "last_run.json").exists()


def test_crawl_search_skips_not_approved_body_and_saves_metadata(
    tmp_path: Path,
) -> None:
    draft_url = DETAIL_URL.replace("186270-d1", "100003-d10")
    fetcher = FakeFetcher(
        {
            SEARCH_URL: _card(draft_url, "Dự thảo nghị định"),
            draft_url: _not_approved_detail_html(),
        }
    )

    report = crawl_search(
        SEARCH_URL,
        fetcher=fetcher,
        output_root=tmp_path / "output" / "raw",
        delay_seconds=0,
    )

    metadata_dir = tmp_path / "output" / "metadata-only" / "LTV_100003"
    assert report["saved"] == []
    assert report["skipped"] == [draft_url]
    assert report["failures"] == []
    assert (metadata_dir / "metadata.json").exists()
    assert not (metadata_dir / "source.txt").exists()
    assert not (metadata_dir / "source.html").exists()


def test_crawl_search_reports_detail_failure_without_fake_output(
    tmp_path: Path,
) -> None:
    fetcher = FakeFetcher(
        {
            SEARCH_URL: _card(DETAIL_URL, "Luật doanh nghiệp"),
            DETAIL_URL: "<h1>Blocked detail without metadata or body</h1>",
        }
    )

    report = crawl_search(
        SEARCH_URL,
        fetcher=fetcher,
        output_root=tmp_path / "output" / "raw",
        delay_seconds=0,
    )

    assert report["saved"] == []
    assert len(report["failures"]) == 1
    assert not (tmp_path / "output" / "raw" / "LTV_186270").exists()


def test_crawl_search_stops_when_next_page_repeats_results(tmp_path: Path) -> None:
    page_two = SEARCH_URL.replace("PageIndex=1", "PageIndex=2")
    listing = _card(DETAIL_URL, "Luật doanh nghiệp")
    fetcher = FakeFetcher(
        {SEARCH_URL: listing, page_two: listing, DETAIL_URL: _detail_html()}
    )

    report = crawl_search(
        SEARCH_URL,
        fetcher=fetcher,
        output_root=tmp_path / "output" / "raw",
        max_pages=5,
        delay_seconds=0,
    )

    assert report["pages_visited"] == 2
    assert fetcher.calls.count(DETAIL_URL) == 1


def test_crawl_search_stops_immediately_on_detail_challenge(tmp_path: Path) -> None:
    class BlockingFetcher(FakeFetcher):
        def get_html(self, url: str) -> str:
            if url == DETAIL_URL:
                raise PageBlockedError("HTTP 429")
            return super().get_html(url)

    fetcher = BlockingFetcher({SEARCH_URL: _card(DETAIL_URL, "Luật doanh nghiệp")})

    with pytest.raises(PageBlockedError, match="429"):
        crawl_search(
            SEARCH_URL,
            fetcher=fetcher,
            output_root=tmp_path / "output" / "raw",
            delay_seconds=0,
        )


def test_crawl_search_stops_after_failure_budget(tmp_path: Path) -> None:
    second_url = DETAIL_URL.replace("186270", "186271")
    listing = _card(DETAIL_URL, "First") + _card(second_url, "Second")
    fetcher = FakeFetcher(
        {
            SEARCH_URL: listing,
            DETAIL_URL: "<h1>missing body</h1>",
            second_url: "<h1>must not be requested</h1>",
        }
    )

    report = crawl_search(
        SEARCH_URL,
        fetcher=fetcher,
        output_root=tmp_path / "output" / "raw",
        delay_seconds=0,
        max_failures=1,
    )

    assert report["stopped_early"] is True
    assert second_url not in fetcher.calls


def test_crawl_job_bundle_completes_and_resumes_at_next_job(tmp_path: Path) -> None:
    second_url = DETAIL_URL.replace("186270", "186271")
    discovery = {
        "search_url": SEARCH_URL,
        "documents": [
            {
                "rank": 1,
                "page_index": 1,
                "external_id": "186270",
                "detail_variant": "d1",
                "source_kind": "issued_document",
                "title": "First",
                "url": DETAIL_URL,
            },
            {
                "rank": 2,
                "page_index": 1,
                "external_id": "186271",
                "detail_variant": "d1",
                "source_kind": "issued_document",
                "title": "Second",
                "url": second_url,
            },
        ],
    }
    bundle_result = create_job_bundle(discovery, tmp_path / "jobs")
    bundle = Path(str(bundle_result["bundle_dir"]))
    fetcher = FakeFetcher({DETAIL_URL: _detail_html(), second_url: _detail_html()})
    progress: list[CrawlProgress] = []

    first = crawl_job_bundle(
        fetcher=fetcher,
        bundle_dir=bundle,
        output_root=tmp_path / "raw",
        max_jobs=1,
        progress_callback=progress.append,
    )
    second = crawl_job_bundle(
        fetcher=fetcher,
        bundle_dir=bundle,
        output_root=tmp_path / "raw",
        max_jobs=1,
    )

    assert first["completed"] == ["LTV_186270-d1"]
    assert first["state"]["next_job"]["job_id"] == "LTV_186271-d1"
    assert second["completed"] == ["LTV_186271-d1"]
    assert second["state"]["complete"] is True
    assert fetcher.calls == [DETAIL_URL, second_url]
    assert [event.event for event in progress] == [
        "worker_started",
        "job_started",
        "job_completed",
        "worker_finished",
    ]
    assert progress[1].rank == 1
    assert progress[1].page_index == 1
    assert progress[2].content_character_count > 0
    assert progress[2].article_count == 1
    job = json.loads(
        (bundle / "jobs" / "LTV_186270-d1.json").read_text(encoding="utf-8")
    )
    assert job["artifacts"]["content_serializer_version"] == "luatvietnam-detail-v2"
    assert job["artifacts"]["content_character_count"] > 0
    assert job["artifacts"]["raw_html_saved"] is True


def test_crawl_job_bundle_returns_parse_failure_to_retryable(tmp_path: Path) -> None:
    discovery = {
        "search_url": SEARCH_URL,
        "documents": [
            {
                "rank": 1,
                "page_index": 1,
                "external_id": "186270",
                "detail_variant": "d1",
                "source_kind": "issued_document",
                "title": "First",
                "url": DETAIL_URL,
            }
        ],
    }
    bundle_result = create_job_bundle(discovery, tmp_path / "jobs")
    bundle = Path(str(bundle_result["bundle_dir"]))
    fetcher = FakeFetcher({DETAIL_URL: "<h1>missing metadata</h1>"})

    report = crawl_job_bundle(
        fetcher=fetcher,
        bundle_dir=bundle,
        output_root=tmp_path / "raw",
        max_jobs=1,
    )

    assert report["completed"] == []
    assert report["retryable"][0]["job_id"] == "LTV_186270-d1"
    assert report["state"]["counts"]["retryable"] == 1


def test_crawl_job_bundle_saves_metadata_only_and_continues(
    tmp_path: Path,
) -> None:
    unavailable_url = DETAIL_URL.replace(
        "luat-doanh-nghiep-2020-186270",
        "quyet-dinh-1995-qd-btc-2026-441834",
    )
    second_url = DETAIL_URL.replace("186270", "186271")
    discovery = {
        "search_url": SEARCH_URL,
        "documents": [
            {
                "rank": 1,
                "page_index": 1,
                "external_id": "441834",
                "detail_variant": "d1",
                "source_kind": "issued_document",
                "title": "Quyết định 1995/QĐ-BTC",
                "url": unavailable_url,
            },
            {
                "rank": 2,
                "page_index": 1,
                "external_id": "186271",
                "detail_variant": "d1",
                "source_kind": "issued_document",
                "title": "Second",
                "url": second_url,
            },
        ],
    }
    bundle_result = create_job_bundle(discovery, tmp_path / "jobs")
    bundle = Path(str(bundle_result["bundle_dir"]))
    fetcher = FakeFetcher(
        {unavailable_url: _unavailable_detail_html(), second_url: _detail_html()}
    )

    report = crawl_job_bundle(
        fetcher=fetcher,
        bundle_dir=bundle,
        output_root=tmp_path / "raw",
        metadata_only_root=tmp_path / "metadata-only",
        max_jobs=2,
        max_failures=1,
    )

    metadata_dir = tmp_path / "metadata-only" / "LTV_441834"
    metadata = json.loads((metadata_dir / "metadata.json").read_text(encoding="utf-8"))
    assert report["completed"] == ["LTV_186271-d1"]
    assert report["content_unavailable"][0]["job_id"] == "LTV_441834-d1"
    assert report["retryable"] == []
    assert report["failed"] == []
    assert report["stopped_early"] is False
    assert report["state"]["counts"]["content_unavailable"] == 1
    assert report["state"]["complete"] is True
    assert metadata["metadata_only"] is True
    assert metadata["content"]["html_full_text_available"] is False
    assert metadata["content"]["raw_html_saved"] is True
    assert not (metadata_dir / "source.txt").exists()
    assert (metadata_dir / "source.html").read_text(encoding="utf-8") == (
        _unavailable_detail_html()
    )
    assert fetcher.calls == [unavailable_url, second_url]


def test_crawl_job_bundle_skips_not_approved_body_but_keeps_metadata(
    tmp_path: Path,
) -> None:
    draft_url = DETAIL_URL.replace("186270-d1", "100003-d10")
    discovery = {
        "search_url": SEARCH_URL,
        "documents": [
            {
                "rank": 1,
                "page_index": 1,
                "external_id": "100003",
                "detail_variant": "d10",
                "source_kind": "draft_document",
                "title": "Dự thảo",
                "url": draft_url,
            }
        ],
    }
    bundle_result = create_job_bundle(discovery, tmp_path / "jobs")
    bundle = Path(str(bundle_result["bundle_dir"]))
    progress: list[CrawlProgress] = []

    report = crawl_job_bundle(
        fetcher=FakeFetcher({draft_url: _not_approved_detail_html()}),
        bundle_dir=bundle,
        output_root=tmp_path / "raw",
        metadata_only_root=tmp_path / "metadata-only",
        max_jobs=1,
        progress_callback=progress.append,
    )

    metadata_dir = tmp_path / "metadata-only" / "LTV_100003"
    metadata = json.loads((metadata_dir / "metadata.json").read_text(encoding="utf-8"))
    assert report["skipped"][0]["reason"] == "not_approved"
    assert report["state"]["counts"]["skipped"] == 1
    assert report["state"]["complete"] is True
    assert metadata["status_raw"] == "Chưa thông qua"
    assert metadata["skip_reason"] == "not_approved"
    assert metadata["content"]["html_full_text_available"] is False
    assert metadata["content"]["raw_html_saved"] is False
    assert not (metadata_dir / "source.txt").exists()
    assert not (metadata_dir / "source.html").exists()
    assert [event.event for event in progress] == [
        "worker_started",
        "job_started",
        "job_skipped",
        "worker_finished",
    ]


def test_crawl_job_bundle_returns_blocked_job_to_retryable(tmp_path: Path) -> None:
    discovery = {
        "search_url": SEARCH_URL,
        "documents": [
            {
                "rank": 1,
                "page_index": 1,
                "external_id": "186270",
                "detail_variant": "d1",
                "source_kind": "issued_document",
                "title": "Blocked",
                "url": DETAIL_URL,
            }
        ],
    }
    bundle_result = create_job_bundle(discovery, tmp_path / "jobs")
    bundle = Path(str(bundle_result["bundle_dir"]))

    class BlockedFetcher(FakeFetcher):
        def get_html(self, url: str) -> str:
            raise PageBlockedError("HTTP 429")

    with pytest.raises(PageBlockedError, match="429"):
        crawl_job_bundle(
            fetcher=BlockedFetcher({}),
            bundle_dir=bundle,
            output_root=tmp_path / "raw",
            max_jobs=1,
        )

    job = json.loads(
        (bundle / "jobs" / "LTV_186270-d1.json").read_text(encoding="utf-8")
    )
    assert job["state"]["status"] == "retryable"
