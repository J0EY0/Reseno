import os
from collections.abc import Callable

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_oauth_tab import TabFlow
from tests.e2e.test_oauth_tab import tab_flow as tab_flow

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)

RESULT_TYPE = "reseno:oauth:result"


def _expect_completion(flow: TabFlow, tab: Page) -> None:
    expect(flow.page.get_by_text("connected-owner", exact=True)).to_be_visible()
    expect(
        flow.page.get_by_role("button", name="Disconnect GitHub", exact=True)
    ).to_be_enabled()
    flow.assert_binding_toast(success=True)
    if not tab.is_closed():
        tab.wait_for_event("close")
    assert len(flow.context.pages) == 1


@pytest.mark.parametrize("mode", ["bind", "setup"])
@pytest.mark.parametrize("stage", ["starting", "provider"])
def test_cancelled_github_authorization_restores_parent_and_ignores_late_start(
    tab_flow: Callable[..., TabFlow], mode: str, stage: str
) -> None:
    flow = tab_flow(mode)
    flow.hold_start = stage == "starting"
    flow.open()
    label = flow.button().inner_text()
    opened_tabs: list[Page] = []
    flow.context.on("page", lambda page: opened_tabs.append(page))
    if stage == "starting":
        flow.begin()
        dialog = flow.page.get_by_role("dialog")
        expect(dialog).to_be_visible()
        expect(flow.button()).to_be_disabled()
        assert len(flow.starts) == 1
        assert not opened_tabs
        if mode == "setup":
            flow.page.keyboard.press("Escape")
        else:
            dialog.get_by_role("button", name="Cancel", exact=True).click()
        expect(dialog).to_have_count(0)
    else:
        tab = flow.start()
        expect(flow.button()).to_be_disabled()
        expect(
            tab.get_by_role("heading", name="Choose a GitHub account")
        ).to_be_visible()
        tab.close()
    expect(flow.button()).to_be_enabled()
    flow.assert_binding_toast()
    expect(flow.page.locator('[data-slot="field-error"]')).to_have_count(0)
    expect(flow.button()).to_have_text(label, use_inner_text=True)
    flow.assert_parent()
    assert len(flow.context.pages) == 1
    assert not flow.completions

    if stage == "starting":
        flow.begin()
        expect(flow.page.get_by_role("dialog")).to_be_visible()
        expect(flow.button()).to_be_disabled()
        assert len(flow.starts) == 2
        flow.release_start(flow.starts[0])
        flow.page.wait_for_timeout(100)
        assert not flow.provider_requests
        assert not opened_tabs
        assert len(flow.context.pages) == 1
        flow.assert_binding_toast()
        retry = flow.release_tab(1)
    else:
        retry = flow.start()
    expect(flow.button()).to_be_disabled()
    assert len(flow.starts) == 2
    flow.confirm(retry)
    assert len(flow.completions) == 1
    flow.finish()
    _expect_completion(flow, retry)


def test_blocked_github_tab_reopens_prepared_authorization_without_another_post(
    tab_flow: Callable[..., TabFlow],
) -> None:
    flow = tab_flow("bind")
    flow.open()
    flow.page.evaluate(
        "() => { window.__nativeOpen = window.open; window.open = () => null; }"
    )
    flow.begin()
    dialog = flow.page.get_by_role("dialog")
    expect(
        dialog.get_by_text(
            "The browser didn't open the authorization tab automatically. "
            "Open it below to continue.",
            exact=True,
        )
    ).to_be_visible()
    expect(flow.button()).to_be_disabled()
    flow.assert_parent()
    assert len(flow.starts) == 1
    assert len(flow.context.pages) == 1
    flow.page.evaluate("() => { window.open = window.__nativeOpen; }")
    with flow.page.expect_popup() as tab_event:
        dialog.get_by_role(
            "button", name="Open GitHub authorization page", exact=True
        ).click()
    tab = tab_event.value
    expect(tab).to_have_url(flow.provider_url)
    assert len(flow.starts) == 1
    flow.confirm(tab)
    flow.finish()
    _expect_completion(flow, tab)


def test_github_tab_ignores_untrusted_and_malformed_messages(
    tab_flow: Callable[..., TabFlow],
) -> None:
    flow = tab_flow("bind")
    flow.open()
    tab = flow.start()
    expect(
        tab.get_by_role("heading", name="Choose a GitHub account")
    ).to_be_visible()
    flow.page.evaluate(
        "window.__receivedMessages = []; addEventListener('message', "
        "event => window.__receivedMessages.push(event.data))"
    )
    result = {"type": RESULT_TYPE, "code": "untrusted", "intent": flow.intent}
    tab.evaluate(
        "([payload, origin]) => opener.postMessage(payload, origin)",
        [result, flow.url],
    )
    probe_url = f"{flow.url}/oauth-message-probe"
    flow.context.route(
        probe_url,
        lambda route: route.fulfill(content_type="text/html", body="Message probe"),
    )
    with flow.page.expect_popup() as sibling_event:
        flow.page.evaluate("url => window.open(url)", probe_url)
    sibling = sibling_event.value
    sibling.wait_for_url(probe_url)
    sibling.evaluate(
        "([payload, origin]) => opener.postMessage(payload, origin)",
        [result, flow.url],
    )
    sibling.close()
    tab.evaluate("url => { location.assign(url); }", probe_url)
    tab.wait_for_url(probe_url)
    invalid_messages = [
        None,
        "invalid-result",
        {**result, "type": "unrelated-message"},
        {**result, "intent": "login"},
        {**result, "code": 42},
        {**result, "code": ""},
        {**result, "code": "x" * 129},
    ]
    tab.evaluate(
        "([payloads, origin]) => payloads.forEach(payload => "
        "opener.postMessage(payload, origin))",
        [invalid_messages, flow.url],
    )
    flow.page.wait_for_function(
        "count => window.__receivedMessages.length === count",
        arg=len(invalid_messages) + 2,
    )
    assert not flow.completions
    assert len(flow.starts) == 1
    expect(flow.button()).to_be_disabled()
    flow.assert_parent()
    tab.evaluate("url => { location.assign(url); }", flow.provider_url)
    tab.wait_for_url(flow.provider_url)
    flow.confirm(tab)
    assert len(flow.completions) == 1
    assert flow.completions[0].request.post_data_json == {"code": "tab-code"}
    flow.finish()
    _expect_completion(flow, tab)


def test_duplicate_github_tab_messages_complete_only_once(
    tab_flow: Callable[..., TabFlow],
) -> None:
    flow = tab_flow("bind")
    flow.open()
    tab = flow.start()
    flow.confirm(tab)
    expect(tab).to_have_url(f"{flow.url}/api/auth/oauth/github/callback")
    tab.evaluate(
        "([payload, origin]) => { for (let i = 0; i < 4; i++) "
        "opener.postMessage(payload, origin); }",
        [{"type": RESULT_TYPE, "code": "tab-code", "intent": flow.intent}, flow.url],
    )
    flow.page.wait_for_timeout(100)
    assert len(flow.completions) == 1
    expect(flow.button()).to_be_disabled()
    flow.finish()
    _expect_completion(flow, tab)
    assert len(flow.completions) == 1


def test_closing_github_tab_cancels_pending_completion(
    tab_flow: Callable[..., TabFlow],
) -> None:
    flow = tab_flow("bind")
    flow.open()
    original_session = flow.page.evaluate(
        "localStorage.getItem('reseno-auth-session')"
    )
    tab = flow.start()
    flow.confirm(tab)
    tab.close()
    expect(flow.button()).to_be_enabled()
    flow.assert_binding_toast()
    expect(flow.page.locator('[data-slot="field-error"]')).to_have_count(0)
    flow.assert_parent()
    flow.finish()
    flow.page.wait_for_timeout(100)
    flow.assert_parent()
    assert flow.page.evaluate(
        "localStorage.getItem('reseno-auth-session')"
    ) == original_session
    flow.assert_binding_toast()
    expect(flow.page.get_by_text("connected-owner", exact=True)).to_have_count(0)
    retry = flow.start()
    flow.confirm(retry)
    assert len(flow.completions) == 2
    flow.finish()
    _expect_completion(flow, retry)


def test_dialog_cancel_closes_github_tab_and_ignores_late_completion(
    tab_flow: Callable[..., TabFlow],
) -> None:
    flow = tab_flow("bind")
    flow.open()
    original_session = flow.page.evaluate(
        "localStorage.getItem('reseno-auth-session')"
    )
    tab = flow.start()
    flow.confirm(tab)
    dialog = flow.page.get_by_role("dialog")
    dialog.get_by_role("button", name="Cancel", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(flow.button()).to_be_enabled()
    flow.assert_binding_toast()
    expect(flow.page.locator('[data-slot="field-error"]')).to_have_count(0)
    assert tab.is_closed()
    flow.assert_parent()
    flow.finish()
    flow.page.wait_for_timeout(100)
    flow.assert_parent()
    assert flow.page.evaluate(
        "localStorage.getItem('reseno-auth-session')"
    ) == original_session
    flow.assert_binding_toast()
    expect(flow.page.get_by_text("connected-owner", exact=True)).to_have_count(0)
    assert len(flow.completions) == 1
    retry = flow.start()
    flow.confirm(retry)
    assert len(flow.completions) == 2
    flow.finish()
    _expect_completion(flow, retry)


def test_leaving_binding_settings_aborts_authorization_without_a_toast(
    tab_flow: Callable[..., TabFlow],
) -> None:
    flow = tab_flow("bind", viewport={"width": 1440, "height": 900})
    flow.open()
    flow.page.locator('a[href="/resume"]').click()
    expect(flow.page.locator('input[name="resume-search"]')).to_be_visible()
    flow.page.locator('a[href="/settings"]').click()
    expect(flow.button()).to_be_enabled()
    original_session = flow.page.evaluate(
        "localStorage.getItem('reseno-auth-session')"
    )
    tab = flow.start()
    flow.confirm(tab)
    flow.page.go_back()
    flow.page.wait_for_url(f"{flow.url}/resume")
    expect(flow.page.locator('input[name="resume-search"]')).to_be_visible()
    flow.assert_parent(retained=False)
    if not tab.is_closed():
        tab.wait_for_event("close")
    expect(flow.page.locator("[data-sonner-toast]")).to_have_count(0)
    flow.finish()
    flow.page.wait_for_timeout(100)
    assert flow.page.url == f"{flow.url}/resume"
    expect(flow.page.locator("[data-sonner-toast]")).to_have_count(0)
    assert flow.page.evaluate(
        "localStorage.getItem('reseno-auth-session')"
    ) == original_session
