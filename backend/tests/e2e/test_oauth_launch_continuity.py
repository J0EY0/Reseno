import os
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect

from tests.e2e.test_oauth_tab import TabFlow
from tests.e2e.test_oauth_tab import tab_flow as tab_flow

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


@pytest.mark.browser_smoke
@pytest.mark.parametrize("start_delay_ms", [0, 500])
def test_github_launch_does_not_paint_callback_before_authorization(
    tab_flow: Callable[..., TabFlow],
    tmp_path: Path,
    start_delay_ms: int,
) -> None:
    flow = tab_flow("bind")
    flow.hold_start = bool(start_delay_ms)
    callback_documents: list[str] = []
    flow.context.on(
        "request",
        lambda request: callback_documents.append(request.url)
        if request.is_navigation_request()
        and urlsplit(request.url).path == "/auth/callback"
        else None,
    )
    flow.open()
    button = flow.button()
    label = button.inner_text()
    rect = button.bounding_box()
    flow.page.evaluate("""() => {
      const open = window.open;
      window.__authorizationOpenCalls = [];
      window.open = function(url, ...args) {
        window.__authorizationOpenCalls.push({
          url,
          dialogTitle: document.querySelector('[role="dialog"] h2')?.textContent,
        });
        return open.call(this, url, ...args);
      };
    }""")

    if start_delay_ms:
        flow.begin()
        flow.page.wait_for_timeout(start_delay_ms)
        assert len(flow.context.pages) == 1
        assert not flow.provider_requests
        assert flow.page.evaluate("window.__authorizationOpenCalls") == []
        expect(flow.page.get_by_role("dialog")).to_have_accessible_name(
            "Connecting to GitHub"
        )
        flow.page.screenshot(path=str(tmp_path / "authorization-preparing.png"))
        assert button.inner_text() == label
        assert button.bounding_box() == rect
        assert len(flow.starts) == 1
        tab = flow.release_tab()
    else:
        tab = flow.start()

    expect(tab.get_by_role("heading", name="Choose a GitHub account")).to_be_visible()
    flow.assert_parent()
    expect(flow.page.get_by_role("dialog")).to_be_visible()
    assert not flow.completions
    assert not callback_documents
    calls = flow.page.evaluate("window.__authorizationOpenCalls")
    assert len(calls) == 1
    assert calls[0]["url"] == flow.provider_url
    if not start_delay_ms:
        assert calls[0]["dialogTitle"] is None
