import os
from collections.abc import Callable

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from tests.e2e.test_oauth_tab import TabFlow
from tests.e2e.test_oauth_tab import tab_flow as tab_flow

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


@pytest.mark.parametrize(
    ("mode", "locale", "width", "cancel_method", "stage"),
    [
        ("bind", "en", 1440, "button", "preparing"),
        ("bind", "zh", 375, "escape", "waiting"),
        ("setup", "en", 375, "close", "waiting"),
    ],
)
def test_github_authorization_dialog_blocks_parent_and_can_cancel(
    tab_flow: Callable[..., TabFlow],
    mode: str,
    locale: str,
    width: int,
    cancel_method: str,
    stage: str,
) -> None:
    flow = tab_flow(
        mode,
        viewport={"width": width, "height": 900},
        reduced_motion="reduce" if width == 375 else "no-preference",
    )
    flow.hold_start = True
    flow.open()
    if locale == "zh":
        flow.context.route(
            "**/api/workspace/user-settings**",
            lambda route: flow.respond(route, {"locale": "zh"}),
        )
        flow.page.get_by_role("combobox", name="Language", exact=True).click()
        flow.page.get_by_role("option", name="中文", exact=True).click()
        expect(flow.page.get_by_text("偏好设置", exact=True)).to_be_visible()
    button = (
        flow.page.get_by_role(
            "button", name="绑定 GitHub", exact=True, include_hidden=True
        )
        if locale == "zh"
        else flow.button()
    )
    initial_rect = button.bounding_box()
    assert initial_rect is not None
    button.click()
    dialog = flow.page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    assert len(flow.context.pages) == 1
    assert len(flow.starts) == 1
    tab = flow.release_tab() if stage == "waiting" else None
    expect(dialog.locator("svg.animate-spin")).to_be_visible()
    cancel_label = "取消" if locale == "zh" else "Cancel"
    title = (
        "Connecting to GitHub"
        if stage == "preparing"
        else "等待 GitHub 授权"
        if locale == "zh"
        else "Waiting for GitHub authorization"
    )
    expect(dialog).to_have_accessible_name(title)
    expect(dialog.get_by_role("button", name=cancel_label, exact=True)).to_be_enabled()
    expect(button).to_be_disabled()
    flow.assert_parent()
    flow.page.bring_to_front()
    blocked_control = flow.page.get_by_role("combobox", include_hidden=True).first
    with pytest.raises(PlaywrightTimeoutError):
        blocked_control.click(trial=True, timeout=250)
    flow.assert_parent()
    assert len(flow.starts) == 1
    assert not flow.completions
    bounds = dialog.bounding_box()
    assert bounds is not None
    assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
    flow.page.screenshot(
        path=f"/private/tmp/reseno-oauth-dialog-{mode}-{locale}-{width}.png"
    )
    if cancel_method == "button":
        dialog.get_by_role("button", name=cancel_label, exact=True).click()
    elif cancel_method == "escape":
        flow.page.keyboard.press("Escape")
    else:
        dialog.get_by_role("button", name="Close", exact=True).click()
    expect(dialog).to_have_count(0)
    expect(button).to_be_enabled()
    if tab is not None and not tab.is_closed():
        tab.wait_for_event("close")
    if tab is None:
        flow.release_start(flow.starts[0])
        flow.page.wait_for_timeout(100)
    assert len(flow.context.pages) == 1
    current_rect = button.bounding_box()
    assert current_rect is not None
    assert (current_rect["width"], current_rect["height"]) == (
        initial_rect["width"],
        initial_rect["height"],
    )
    flow.assert_parent()
    assert not flow.completions
    flow.assert_binding_toast(locale=locale)
    expect(flow.page.locator('[data-slot="field-error"]')).to_have_count(0)
    flow.page.screenshot(
        path=f"/private/tmp/reseno-github-binding-cancel-{locale}.png"
    )
