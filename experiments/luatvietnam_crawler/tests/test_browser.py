from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from experiments.luatvietnam_crawler.browser import BrowserSession
from experiments.luatvietnam_crawler.errors import PageBlockedError, SafetyPolicyError
from experiments.luatvietnam_crawler.safety import RequestSafetyPolicy


def _safety_policy(tmp_path: Path) -> RequestSafetyPolicy:
    return RequestSafetyPolicy(
        state_path=tmp_path / "safety-state.json",
        min_delay_seconds=0,
        max_delay_seconds=0,
    )


@patch("experiments.luatvietnam_crawler.browser.sync_playwright")
def test_browser_reuses_profile_and_closes_context(
    sync_playwright: MagicMock, tmp_path: Path
) -> None:
    playwright = sync_playwright.return_value.start.return_value
    context = playwright.chromium.launch_persistent_context.return_value
    context.pages = []

    with BrowserSession(
        profile_dir=tmp_path / "profile",
        safety_policy=_safety_policy(tmp_path),
    ):
        pass

    playwright.chromium.launch_persistent_context.assert_called_once()
    launch = playwright.chromium.launch_persistent_context.call_args
    assert launch.args[0] == str(tmp_path / "profile")
    assert launch.kwargs["channel"] == "chrome"
    assert launch.kwargs["headless"] is False
    assert launch.kwargs["no_viewport"] is True
    assert launch.kwargs["args"] == ["--start-maximized"]
    context.new_page.assert_called_once_with()
    context.close.assert_called_once_with()
    playwright.stop.assert_called_once_with()


@patch("experiments.luatvietnam_crawler.browser.sync_playwright")
def test_browser_cleans_playwright_after_profile_startup_failure(
    sync_playwright: MagicMock, tmp_path: Path
) -> None:
    playwright = sync_playwright.return_value.start.return_value
    playwright.chromium.launch_persistent_context.side_effect = RuntimeError(
        "profile locked"
    )

    with pytest.raises(RuntimeError, match="profile locked"):
        with BrowserSession(
            profile_dir=tmp_path / "profile",
            safety_policy=_safety_policy(tmp_path),
        ):
            pass

    playwright.stop.assert_called_once_with()


@patch("experiments.luatvietnam_crawler.browser.sync_playwright")
def test_browser_reuses_one_tab_across_requests(
    sync_playwright: MagicMock, tmp_path: Path
) -> None:
    playwright = sync_playwright.return_value.start.return_value
    context = playwright.chromium.launch_persistent_context.return_value
    page = MagicMock()
    context.pages = [page]
    page.goto.return_value.status = 200
    page.locator.return_value.inner_text.return_value = "Document page"
    page.title.return_value = "Document"
    page.content.return_value = "<html>Document</html>"

    with BrowserSession(
        profile_dir=tmp_path / "profile",
        safety_policy=_safety_policy(tmp_path),
    ) as browser:
        browser.get_html("https://luatvietnam.vn/van-ban/tim-van-ban.html")
        browser.get_html("https://luatvietnam.vn/document-12345-d1.html")

    assert page.goto.call_count == 2
    page.close.assert_not_called()
    context.new_page.assert_not_called()


@patch("experiments.luatvietnam_crawler.browser.sync_playwright")
def test_browser_closes_page_and_stops_on_rate_limit(
    sync_playwright: MagicMock, tmp_path: Path
) -> None:
    playwright = sync_playwright.return_value.start.return_value
    context = playwright.chromium.launch_persistent_context.return_value
    context.pages = []
    page = context.new_page.return_value
    page.goto.return_value.status = 429
    page.goto.return_value.headers = {"retry-after": "120"}

    with BrowserSession(
        profile_dir=tmp_path / "profile",
        safety_policy=_safety_policy(tmp_path),
    ) as browser:
        with pytest.raises(PageBlockedError, match="429"):
            browser.get_html("https://luatvietnam.vn/van-ban/tim-van-ban.html")

    page.close.assert_not_called()
    context.close.assert_called_once_with()


@patch("experiments.luatvietnam_crawler.browser.sync_playwright")
def test_browser_stops_on_visible_challenge_and_persists_cooldown(
    sync_playwright: MagicMock, tmp_path: Path
) -> None:
    playwright = sync_playwright.return_value.start.return_value
    context = playwright.chromium.launch_persistent_context.return_value
    context.pages = []
    page = context.new_page.return_value
    page.goto.return_value.status = 200
    page.locator.return_value.inner_text.return_value = "Verify you are human"
    page.title.return_value = "Just a moment"
    policy = _safety_policy(tmp_path)

    with BrowserSession(
        profile_dir=tmp_path / "profile", safety_policy=policy
    ) as browser:
        with pytest.raises(PageBlockedError, match="challenged"):
            browser.get_html("https://luatvietnam.vn/van-ban/tim-van-ban.html")

    with pytest.raises(SafetyPolicyError, match="cooldown is active"):
        _safety_policy(tmp_path).before_request()
