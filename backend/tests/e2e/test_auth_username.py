"""Owner username changes preserve active browser sessions and editor state."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Locator, Page, Request, Route, expect

from tests.e2e.browser_support import browser_session
from tests.e2e.conftest import workspace_servers as _workspace_servers_fixture

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]

PASSWORD = "E2ePassword2026"
SESSION = "JSON.parse(localStorage.getItem('reseno-auth-session'))"


@pytest.fixture
def username_workspace(request: pytest.FixtureRequest) -> Iterator[tuple[str, str]]:
    previous_session = browser_session.copy()
    try:
        yield from _workspace_servers_fixture.__wrapped__(request)
    finally:
        browser_session.clear()
        browser_session.update(previous_session)


def _login(page: Page, base: str, username: str = "e2e-owner") -> None:
    page.goto(f"{base}/login", wait_until="networkidle")
    page.locator("#username").fill(username)
    page.locator("#password").fill(PASSWORD)
    page.locator('form button[type="submit"]').click()
    page.wait_for_url(f"{base}/resume")
    expect(page.locator('input[name="resume-search"]')).to_be_visible()


def _dialog(page: Page, label: str = "修改用户名") -> Locator:
    page.get_by_role("button", name=label, exact=True).click()
    dialog = page.get_by_role("dialog", name=label, exact=True)
    expect(dialog).to_be_visible()
    return dialog


def _session(page: Page) -> dict[str, Any]:
    return page.evaluate(SESSION)


def _screenshot(page: Page, path: Path) -> None:
    page.evaluate("""async () => {
      await Promise.allSettled(document.getAnimations()
        .filter(animation => animation.effect?.getComputedTiming().endTime !== Infinity)
        .map(animation => animation.finished));
    }""")
    page.screenshot(path=str(path))


def _expect_owner(page: Page, username: str) -> None:
    page.wait_for_function(
        f"username => ({SESSION})?.username === username", arg=username
    )
    assert _session(page)["username"] == username


def test_username_change_updates_open_tabs_and_login_credentials(
    browser: Browser, username_workspace: tuple[str, str], tmp_path: Path
) -> None:
    base, _ = username_workspace
    context = browser.new_context(
        locale="zh-CN", viewport={"width": 1440, "height": 1000}
    )
    context.route(
        "**/api/auth/oauth/identities",
        lambda route: route.fulfill(
            json={
                "code": 0,
                "message": "OK",
                "data": {
                    "identities": [
                        {
                            "provider": "github",
                            "label": "connected-github-owner",
                            "createdAt": "2026-09-09T00:00:00Z",
                        }
                    ],
                    "providers": [{"provider": "github", "configured": True}],
                },
            }
        ),
    )
    page = context.new_page()
    other = context.new_page()
    errors: list[str] = []
    for tab in (page, other):
        tab.on("pageerror", lambda error: errors.append(str(error)))
    try:
        _login(page, base)
        for tab in (page, other):
            tab.goto(f"{base}/settings", wait_until="networkidle")
            _expect_owner(tab, "e2e-owner")
            expect(
                tab.get_by_text("connected-github-owner", exact=True)
            ).to_be_visible()
        old_session = _session(page)
        controls = [
            tab.get_by_role("button", name="修改用户名", exact=True).element_handle()
            for tab in (page, other)
        ]
        navigations: list[str] = []
        for tab in (page, other):
            tab.on("framenavigated", lambda frame: navigations.append(frame.url))
        untouched = _dialog(other)
        expect(untouched.locator("#new-username")).to_have_value("e2e-owner")
        expect(untouched.locator('button[type="submit"]')).to_be_disabled()
        dialog = _dialog(page)
        expect(dialog.locator("#new-username")).to_have_value("e2e-owner")
        submit = dialog.get_by_role("button", name="修改用户名", exact=True)
        expect(submit).to_be_disabled()
        dialog.locator("#new-username").fill("renamed-owner")
        dialog.locator("#username-current-password").fill(PASSWORD)
        _screenshot(page, tmp_path / "username-dialog-zh.png")
        submit.click()
        expect(page.get_by_text("用户名修改成功", exact=True)).to_be_visible()
        expect(dialog).to_be_hidden()
        sessions = []
        for tab, control in zip((page, other), controls, strict=True):
            _expect_owner(tab, "renamed-owner")
            expect(tab).to_have_url(f"{base}/settings")
            assert control is not None and control.evaluate("el => el.isConnected")
            expect(
                tab.get_by_text("connected-github-owner", exact=True)
            ).to_be_visible()
            sessions.append(_session(tab))
        assert sessions[0] == sessions[1]
        assert sessions[0]["accessToken"] != old_session["accessToken"]
        expect(untouched.locator("#new-username")).to_have_value("renamed-owner")
        expect(untouched.locator("#username-current-password")).to_have_value("")
        expect(untouched.locator('button[type="submit"]')).to_be_disabled()
        assert not navigations
        _screenshot(page, tmp_path / "username-success-zh.png")
        for token, expected_status in (
            (old_session["accessToken"], 401),
            (sessions[0]["accessToken"], 200),
        ):
            response = page.request.get(
                f"{base}/api/resumes",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status == expected_status
        signed_out = browser.new_context(locale="en-US")
        try:
            login = signed_out.new_page()
            login.goto(f"{base}/login", wait_until="networkidle")
            login.locator("#username").fill("e2e-owner")
            login.locator("#password").fill(PASSWORD)
            login.locator('form button[type="submit"]').click()
            expect(
                login.get_by_text("Incorrect username or password.", exact=True)
            ).to_be_visible()
            expect(login).to_have_url(f"{base}/login")
            login.locator("#username").fill("renamed-owner")
            login.locator('form button[type="submit"]').click()
            login.wait_for_url(f"{base}/resume")
            assert _session(login)["username"] == "renamed-owner"
        finally:
            signed_out.close()
        assert not errors
    finally:
        context.close()


def test_username_validation_failure_cancel_and_pending_submission(
    browser: Browser, username_workspace: tuple[str, str], tmp_path: Path
) -> None:
    base, _ = username_workspace
    context = browser.new_context(locale="zh-CN")
    page = context.new_page()
    requests: list[Request] = []
    page.on(
        "request",
        lambda request: (
            requests.append(request)
            if request.url.endswith("/api/auth/username")
            else None
        ),
    )
    held: list[Route] = []
    try:
        _login(page, base)
        page.goto(f"{base}/settings", wait_until="networkidle")
        original_session = _session(page)
        dialog = _dialog(page)
        username = dialog.locator("#new-username")
        password = dialog.locator("#username-current-password")
        submit = dialog.get_by_role("button", name="修改用户名", exact=True)
        username.fill("bad name!")
        submit.click()
        expect(username).to_have_attribute("aria-invalid", "true")
        expect(password).to_have_attribute("aria-invalid", "true")
        expect(
            dialog.get_by_text("用户名只能包含字母、数字、下划线或连字符", exact=True)
        ).to_be_visible()
        expect(dialog.get_by_text("请输入密码", exact=True)).to_be_visible()
        assert not requests
        _screenshot(page, tmp_path / "username-validation-errors.png")
        username.fill("retry-owner")
        password.fill("incorrect-password")
        with page.expect_response("**/api/auth/username") as response:
            submit.click()
        assert response.value.status == 400
        expect(page.get_by_text("用户名或密码错误", exact=True)).to_be_visible()
        expect(dialog).to_be_visible()
        assert _session(page) == original_session
        dialog.get_by_role("button", name="取消", exact=True).click()
        expect(dialog).to_be_hidden()
        dialog = _dialog(page)
        expect(username).to_have_value("e2e-owner")
        expect(password).to_have_value("")
        expect(dialog.locator('[aria-invalid="true"]')).to_have_count(0)
        username.fill("retry-owner")
        password.fill(PASSWORD)
        page.route("**/api/auth/username", lambda route: route.abort())
        submit.click()
        expect(page.get_by_text("请求失败，请稍后重试", exact=True)).to_be_visible()
        assert _session(page) == original_session
        expect(dialog).to_be_visible()
        expect(username).to_have_value("retry-owner")
        expect(password).to_have_value(PASSWORD)
        page.unroute("**/api/auth/username")
        page.route("**/api/auth/username", lambda route: held.append(route))
        submit.dblclick()
        pending = dialog.locator('button[type="submit"]')
        expect(pending).to_have_text("修改中")
        expect(pending).to_be_disabled()
        expect(pending).to_have_attribute("aria-busy", "true")
        expect(dialog.get_by_role("button", name="修改中", exact=True)).to_be_disabled()
        expect(password).to_be_disabled()
        expect(username).to_be_disabled()
        expect(dialog.get_by_role("button", name="取消", exact=True)).to_be_disabled()
        page.keyboard.press("Enter")
        page.keyboard.press("Escape")
        expect(dialog).to_be_visible()
        assert len(held) == 1 and len(requests) == 3
        _screenshot(page, tmp_path / "username-pending.png")
        held.pop().continue_()
        expect(page.get_by_text("用户名修改成功", exact=True)).to_be_visible()
        expect(dialog).to_be_hidden()
        _expect_owner(page, "retry-owner")
        assert len(requests) == 3
    finally:
        context.close()


def test_username_rotation_preserves_unsaved_editor_during_stale_401s_on_mobile(
    browser: Browser, username_workspace: tuple[str, str], tmp_path: Path
) -> None:
    base, resume_id = username_workspace
    context = browser.new_context(
        locale="en-US", viewport={"width": 1440, "height": 1000}
    )
    settings = context.new_page()
    editor = context.new_page()
    stale: list[Route] = []
    renames: list[Route] = []
    errors: list[str] = []
    for tab in (settings, editor):
        tab.on("pageerror", lambda error: errors.append(str(error)))
    try:
        _login(settings, base)
        settings.set_viewport_size({"width": 430, "height": 932})
        settings.goto(f"{base}/settings", wait_until="networkidle")
        editor.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        basic = editor.get_by_role(
            "button", name="Basic Info: Toggle section", exact=True
        )
        if basic.get_attribute("aria-expanded") != "true":
            basic.click()
        name = editor.get_by_role("textbox", name="Full Name", exact=True)
        name.click()
        name.press("ControlOrMeta+a")
        name.press_sequentially("Unsaved editor survives username change")
        expect(name).to_have_text("Unsaved editor survives username change")
        name_node = name.element_handle()
        save = editor.get_by_role("button", name="Save Status", exact=True)
        expect(save).to_have_attribute("title", "Unsaved changes")
        old_session = _session(editor)
        editor.route(
            "**/api/resumes?username-race=*", lambda route: stale.append(route)
        )
        editor.evaluate("""async () => {
          const { requestApi } = await import('/src/lib/api-client.ts');
          window.usernameRaceErrors = [];
          for (const timing of ['during', 'after']) {
            void requestApi(`/api/resumes?username-race=${timing}`, {
              cacheTtlMs: 0, notifyOnError: false,
            }).catch(error => window.usernameRaceErrors.push(error.message));
          }
        }""")
        settings.route("**/api/auth/username", lambda route: renames.append(route))
        dialog = _dialog(settings, "Change Username")
        dialog.locator("#new-username").fill("mobile-owner-renamed-2026")
        dialog.locator("#username-current-password").fill(PASSWORD)
        assert settings.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        assert dialog.evaluate("""element => {
          const rect = element.getBoundingClientRect();
          return rect.left >= 0 && rect.right <= innerWidth;
        }""")
        _screenshot(settings, tmp_path / "username-dialog-en-mobile.png")
        dialog.get_by_role("button", name="Change Username", exact=True).click()
        expect(dialog.locator('button[type="submit"]')).to_be_disabled()
        expect(dialog.locator('button[type="submit"]')).to_have_text("Updating")
        assert len(renames) == 1
        rename = renames.pop()
        renamed = rename.fetch()
        assert renamed.status == 200
        assert len(stale) == 2
        old_response = stale[0].fetch()
        assert old_response.status == 401
        stale[0].fulfill(response=old_response)
        editor.wait_for_function("""async () =>
          (await navigator.locks.query()).pending.some(
            lock => lock.name === 'reseno-auth-refresh' && lock.mode === 'shared'
          )
        """)
        assert _session(editor) == old_session
        expect(
            editor.get_by_role("dialog", name="Your session has expired")
        ).to_have_count(0)
        rename.fulfill(response=renamed)
        expect(settings.get_by_text("Username updated.", exact=True)).to_be_visible()
        expect(dialog).to_be_hidden()
        _expect_owner(settings, "mobile-owner-renamed-2026")
        editor.wait_for_function(f"{SESSION}.username === 'mobile-owner-renamed-2026'")
        late_response = stale[1].fetch()
        assert late_response.status == 401
        stale[1].fulfill(response=late_response)
        editor.wait_for_function("window.usernameRaceErrors.length === 2")
        assert _session(editor) == _session(settings)
        assert _session(editor)["accessToken"] != old_session["accessToken"]
        expect(editor).to_have_url(f"{base}/resume/{resume_id}")
        expect(settings).to_have_url(f"{base}/settings")
        expect(
            editor.get_by_role("dialog", name="Your session has expired")
        ).to_have_count(0)
        assert name_node is not None and name_node.evaluate("el => el.isConnected")
        expect(name).to_have_text("Unsaved editor survives username change")
        expect(save).to_have_attribute("title", "Unsaved changes")
        editor.bring_to_front()
        with editor.expect_response(
            lambda response: (
                response.url.split("?", 1)[0].endswith(f"/api/resumes/{resume_id}")
                and response.request.method == "PUT"
            )
        ) as saved:
            editor.keyboard.press("ControlOrMeta+s")
        assert saved.value.status == 200
        assert saved.value.request.headers["authorization"] == (
            f"Bearer {_session(editor)['accessToken']}"
        )
        assert settings.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        _screenshot(settings, tmp_path / "username-success-en-mobile.png")
        _screenshot(editor, tmp_path / "username-editor-preserved.png")
        assert not errors
    finally:
        context.close()
