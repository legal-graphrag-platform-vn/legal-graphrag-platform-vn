"""Playwright adapter kept outside the pure parser."""

from __future__ import annotations

import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from types import TracebackType

from playwright.sync_api import BrowserContext, Page, Playwright, sync_playwright

from .errors import PageBlockedError
from .safety import RequestSafetyPolicy

BLOCK_MARKERS = (
    "just a moment",
    "web page blocked",
    "access denied",
    "verify you are human",
)


class BrowserSession:
    def __init__(
        self,
        *,
        profile_dir: Path,
        safety_policy: RequestSafetyPolicy,
        timeout_ms: int = 30_000,
        headless: bool = False,
        browser_channel: str = "chrome",
    ) -> None:
        self.profile_dir = profile_dir
        self.safety_policy = safety_policy
        self.timeout_ms = timeout_ms
        self.headless = headless
        self.browser_channel = browser_channel
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    def __enter__(self) -> BrowserSession:
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                headless=self.headless,
                channel=self.browser_channel,
                args=["--start-maximized"],
                no_viewport=True,
                locale="vi-VN",
            )
            existing_pages = self._context.pages
            self._page = (
                existing_pages[0] if existing_pages else self._context.new_page()
            )
        except BaseException:
            self._playwright.stop()
            self._playwright = None
            raise
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._context is not None:
            self._context.close()
        if self._playwright is not None:
            self._playwright.stop()

    def get_html(self, url: str) -> str:
        if self._context is None:
            raise RuntimeError("BrowserSession must be used as a context manager")
        self.safety_policy.before_request()
        if self._page is None:
            self._page = self._context.new_page()
        response = self._page.goto(
            url, wait_until="domcontentloaded", timeout=self.timeout_ms
        )
        if response is not None and response.status in {403, 429}:
            retry_after = _retry_after_seconds(response.headers.get("retry-after"))
            self.safety_policy.block(
                f"HTTP {response.status}", retry_after_seconds=retry_after
            )
            raise PageBlockedError(
                f"LuatVietnam returned HTTP {response.status}; stopping crawl: {url}"
            )
        self._page.wait_for_timeout(1_500)
        html = self._page.content()
        visible_text = self._page.locator("body").inner_text().lower()
        title = self._page.title().lower()
        if any(marker in f"{title}\n{visible_text}" for marker in BLOCK_MARKERS):
            self.safety_policy.block("visible anti-bot challenge")
            raise PageBlockedError(f"LuatVietnam blocked or challenged request: {url}")
        return html


def _retry_after_seconds(value: str | None) -> int | None:
    if not value:
        return None
    if value.isdigit():
        return int(value)
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if retry_at.tzinfo is None:
        return None
    return max(0, int(retry_at.timestamp() - time.time()))
