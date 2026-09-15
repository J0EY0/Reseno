from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import APIResponse, Browser, Route, expect

from tests.e2e.browser_support import RouteReady
from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_leave_reprepares_gallery_after_edit_during_target_load(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()
    resume_id: str | None = None
    gallery_request_count = 0
    held_gallery_snapshots: list[tuple[Route, APIResponse]] = []
    updated_name = "Saved During Target Preparation"

    def hold_first_gallery_snapshot(route: Route) -> None:
        nonlocal gallery_request_count
        gallery_request_count += 1
        if gallery_request_count > 1:
            route.continue_()
            return

        held_gallery_snapshots.append((route, route.fetch()))

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": "Before Target Preparation",
            },
        )
        assert create_response.ok
        resume_id = create_response.json()["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        page.route(
            "**/api/workspace/pages/resumes",
            hold_first_gallery_snapshot,
        )
        with page.expect_request("**/api/workspace/pages/resumes"):
            page.get_by_role("button", name="返回简历列表", exact=True).click()
        deadline = time.monotonic() + 3
        while not held_gallery_snapshots and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert len(held_gallery_snapshots) == 1
        page.get_by_role("textbox", name="姓名", exact=True).fill(updated_name)
        expect(page.locator('[data-slot="save-status-announcement"]')).to_have_text(
            "有未保存更改"
        )
        route, snapshot = held_gallery_snapshots.pop()
        route.fulfill(response=snapshot)

        page.get_by_role(
            "heading",
            name="有未保存的更改",
            exact=True,
        ).wait_for(state="visible")
        assert gallery_request_count == 1

        page.get_by_role(
            "button",
            name="保存并离开",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/resume", timeout=5_000)
        page.wait_for_load_state("networkidle")

        assert gallery_request_count == 2
        expect(
            page.locator(f'a[href="/resume/{resume_id}"]').get_by_text(
                updated_name, exact=True
            )
        ).to_have_count(1)
    finally:
        if resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_leaving_resume_promotes_completed_autosave_to_checkpoint(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()
    save_urls: list[str] = []

    def capture_save(route: Route) -> None:
        if route.request.method == "PUT":
            save_urls.append(route.request.url)
        route.continue_()

    page.route(f"**/api/resumes/{resume_id}*", capture_save)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        page.get_by_role("textbox", name="姓名", exact=True).fill(
            "Autosaved Before Leave"
        )

        deadline = time.monotonic() + 8
        while len(save_urls) < 1 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert len(save_urls) == 1, save_urls
        assert "saveMode=autosave" in save_urls[0]
        page.wait_for_load_state("networkidle")
        page.get_by_role(
            "button",
            name="返回简历列表",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/resume")

        assert len(save_urls) == 2, save_urls
        assert "saveMode=checkpoint" in save_urls[1]
    finally:
        context.close()


def test_latest_navigation_waits_for_active_checkpoint_promotion(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()
    resume_id: str | None = None

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"documentLocale": "zh"},
        )
        assert create_response.ok
        resume_id = create_response.json()["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
                and parse_qs(urlparse(response.url).query).get("saveMode")
                == ["autosave"]
            ),
            timeout=8_000,
        ) as autosave_response_info:
            page.get_by_role("textbox", name="姓名", exact=True).fill(
                "Autosaved Before Superseded Navigation"
            )
        assert autosave_response_info.value.ok
        page.wait_for_load_state("networkidle")

        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
                and parse_qs(urlparse(response.url).query).get("saveMode")
                == ["checkpoint"]
            )
        ) as checkpoint_response_info:
            page.evaluate(
                """
                () => {
                  const back = [...document.querySelectorAll("button")].find(
                    (button) => button.textContent?.includes("返回简历列表"),
                  );
                  const logout = [...document.querySelectorAll("button")].find(
                    (button) => button.textContent?.trim() === "退出登录",
                  );
                  if (!(back instanceof HTMLButtonElement) ||
                      !(logout instanceof HTMLButtonElement)) {
                    throw new Error("Resume navigation targets are unavailable.");
                  }
                  back.click();
                  logout.click();
                }
                """
            )
        assert checkpoint_response_info.value.ok

        page.wait_for_url(f"{frontend_url}/login", timeout=5_000)
        page.wait_for_load_state("networkidle")
        assert page.url == f"{frontend_url}/login"
    finally:
        if resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_checkpoint_failure_after_autosave_does_not_block_leaving_resume(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()
    save_urls: list[str] = []

    def fail_checkpoint(route: Route) -> None:
        if route.request.method != "PUT":
            route.continue_()
            return

        save_urls.append(route.request.url)
        if "saveMode=checkpoint" not in route.request.url:
            route.continue_()
            return

        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "code": 40000,
                    "message": "RESUME_DOCUMENT_INVALID",
                    "data": None,
                }
            ),
        )

    page.route(f"**/api/resumes/{resume_id}*", fail_checkpoint)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        page.get_by_role("textbox", name="姓名", exact=True).fill(
            "Autosaved Before Failed Checkpoint"
        )

        deadline = time.monotonic() + 8
        while len(save_urls) < 1 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert len(save_urls) == 1, save_urls
        assert "saveMode=autosave" in save_urls[0]
        page.wait_for_load_state("networkidle")
        page.get_by_role(
            "button",
            name="返回简历列表",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/resume", timeout=3_000)
        page.get_by_text(
            "内容已自动保存，但未能创建历史版本",
            exact=True,
        ).wait_for(state="visible")

        assert len(save_urls) == 2, save_urls
        assert "saveMode=checkpoint" in save_urls[1]
        assert page.get_by_text("请求失败，请稍后重试", exact=True).count() == 0
    finally:
        context.close()


def test_checkpoint_failure_keeps_new_edit_made_before_logout(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()
    save_urls: list[str] = []
    held_checkpoints: list[Route] = []
    route_ready = RouteReady()

    def fail_delayed_checkpoint(route: Route) -> None:
        if route.request.method != "PUT":
            route.continue_()
            return

        save_urls.append(route.request.url)
        if "saveMode=checkpoint" not in route.request.url:
            route.continue_()
            return

        held_checkpoints.append(route)
        route_ready.set()

    page.route(f"**/api/resumes/{resume_id}*", fail_delayed_checkpoint)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        page.get_by_role("textbox", name="姓名", exact=True).fill(
            "Autosaved Before Promotion"
        )

        deadline = time.monotonic() + 8
        while len(save_urls) < 1 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert len(save_urls) == 1, save_urls
        assert "saveMode=autosave" in save_urls[0]
        page.wait_for_load_state("networkidle")
        with page.expect_request(
            lambda request: (
                request.method == "PUT"
                and urlparse(request.url).path == f"/api/resumes/{resume_id}"
                and parse_qs(urlparse(request.url).query).get("saveMode")
                == ["checkpoint"]
            )
        ):
            page.get_by_role("button", name="退出登录", exact=True).click()
        route_ready.wait(page)
        assert len(held_checkpoints) == 1
        page.get_by_role("textbox", name="姓名", exact=True).fill(
            "New Edit During Failed Checkpoint"
        )
        held_checkpoints.pop().fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {"code": 40000, "message": "RESUME_DOCUMENT_INVALID", "data": None}
            ),
        )

        page.get_by_role(
            "heading",
            name="有未保存的更改",
            exact=True,
        ).wait_for(state="visible")
        assert page.url == f"{frontend_url}/resume/{resume_id}"
        assert (
            page.get_by_role(
                "textbox", name="姓名", exact=True, include_hidden=True
            ).inner_text()
            == "New Edit During Failed Checkpoint"
        )
        assert len(save_urls) == 2, save_urls
        assert "saveMode=checkpoint" in save_urls[1]
    finally:
        context.close()


def test_discard_waits_for_active_save_and_restores_persisted_resume(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()
    save_count = 0

    def delay_first_save(route: Route) -> None:
        nonlocal save_count
        if route.request.method != "PUT":
            route.continue_()
            return

        save_count += 1
        if save_count == 1:
            time.sleep(1)
        route.continue_()

    page.route(f"**/api/resumes/{resume_id}*", delay_first_save)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        name_input = page.get_by_role("textbox", name="姓名", exact=True)
        original_name = name_input.inner_text()
        name_input.fill("Discarded During Active Save")
        page.evaluate(
            """
            () => {
              window.setTimeout(() => {
                const backButton = [...document.querySelectorAll("button")].find(
                  (button) => button.textContent?.includes("返回简历列表"),
                );
                if (!(backButton instanceof HTMLButtonElement)) {
                  throw new Error("Back button is unavailable.");
                }
                backButton.click();
              }, 200);
              window.setTimeout(() => {
                const discardButton = [...document.querySelectorAll("button")].find(
                  (button) => button.textContent?.trim() === "放弃更改",
                );
                if (!(discardButton instanceof HTMLButtonElement)) {
                  throw new Error("Discard button is unavailable.");
                }
                discardButton.click();
              }, 400);
            }
            """
        )
        page.keyboard.press("Control+S")
        page.wait_for_url(f"{frontend_url}/resume")
        page.wait_for_load_state("networkidle")

        persisted_response = page.request.get(f"{frontend_url}/api/resumes/{resume_id}")
        persisted = persisted_response.json()["data"]["resume"]
        assert persisted["resume"]["basic"]["name"] == original_name
        assert save_count == 2
    finally:
        context.close()


def test_browser_history_navigation_uses_unsaved_changes_guard(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.locator(f'a[href="/resume/{resume_id}"]').click()
        page.wait_for_url(f"{frontend_url}/resume/{resume_id}")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        page.get_by_role("textbox", name="姓名", exact=True).fill(
            "Unsaved Browser Back"
        )
        page.evaluate("window.history.back()")
        page.wait_for_timeout(250)

        assert page.url == f"{frontend_url}/resume/{resume_id}"
        assert (
            page.get_by_role(
                "heading",
                name="有未保存的更改",
                exact=True,
            ).count()
            == 1
        )

        page.get_by_role(
            "button",
            name="继续编辑",
            exact=True,
        ).click()
        assert page.url == f"{frontend_url}/resume/{resume_id}"
    finally:
        context.close()


@pytest.mark.browser_smoke
def test_resume_leave_dialog_enter_activates_only_focused_action(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()
    resume_id: str | None = None
    save_payloads: list[dict[str, object]] = []

    def capture_save(route: Route) -> None:
        if route.request.method == "PUT":
            payload = route.request.post_data_json
            assert isinstance(payload, dict)
            save_payloads.append(payload)
        route.continue_()

    def open_leave_dialog() -> None:
        page.get_by_role(
            "button",
            name="返回简历列表",
            exact=True,
        ).click()
        page.get_by_role(
            "heading",
            name="有未保存的更改",
            exact=True,
        ).wait_for(state="visible")

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": "Leave dialog Enter actions",
            },
        )
        assert create_response.ok
        resume_id = create_response.json()["data"]["resume"]["id"]
        page.route(f"**/api/resumes/{resume_id}*", capture_save)

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        name_input = page.get_by_role("textbox", name="姓名", exact=True)
        name_input.fill("Continue editing via Enter")
        open_leave_dialog()

        continue_editing = page.get_by_role(
            "button",
            name="继续编辑",
            exact=True,
        )
        continue_editing.focus()
        page.keyboard.press("Enter")

        page.get_by_role(
            "heading",
            name="有未保存的更改",
            exact=True,
        ).wait_for(state="hidden")
        assert page.url == f"{frontend_url}/resume/{resume_id}"
        assert name_input.inner_text() == "Continue editing via Enter"

        open_leave_dialog()
        save_payloads.clear()
        discard = page.get_by_role(
            "button",
            name="放弃更改",
            exact=True,
        )
        discard.focus()
        page.keyboard.press("Enter")
        page.wait_for_url(f"{frontend_url}/resume")

        discarded_name = "Continue editing via Enter"
        assert all(
            payload["resume"]["basic"]["name"] != discarded_name
            for payload in save_payloads
        )

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        saved_name = "Save and leave via Enter"
        page.get_by_role("textbox", name="姓名", exact=True).fill(saved_name)
        open_leave_dialog()

        save_payloads.clear()
        save_and_leave = page.get_by_role(
            "button",
            name="保存并离开",
            exact=True,
        )
        save_and_leave.focus()
        page.keyboard.press("Enter")
        page.wait_for_url(f"{frontend_url}/resume")

        assert any(
            payload["resume"]["basic"]["name"] == saved_name
            for payload in save_payloads
        )
    finally:
        if resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_browser_back_does_not_restore_consumed_resume_handoff(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()
    resume_id: str | None = None

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": "Consumed history handoff",
            },
        )
        assert create_response.ok
        resume_id = create_response.json()["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.locator(f'a[href="/resume/{resume_id}"]').click()
        page.wait_for_url(f"{frontend_url}/resume/{resume_id}")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        name_input = page.get_by_role("textbox", name="姓名", exact=True)
        name_input.fill("Saved After Initial Handoff")
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
            )
        ):
            page.get_by_role("button", name="保存状态", exact=True).click()
        page.get_by_role("button", name="保存状态", exact=True).hover()
        page.get_by_text("有未保存更改", exact=True).wait_for(state="detached")

        page.get_by_role("button", name="返回简历列表", exact=True).click()
        page.wait_for_url(f"{frontend_url}/resume")
        page.wait_for_load_state("networkidle")

        def delay_back_loader(route: Route) -> None:
            current_response = route.fetch()
            time.sleep(2)
            route.fulfill(response=current_response)

        page.route(
            f"**/api/resumes/{resume_id}",
            delay_back_loader,
        )
        page.evaluate(
            f"""
            () => {{
              window.__staleResumeHandoffEdited = false;
              const deadline = performance.now() + 1_200;
              let openedBasicInfo = false;
              const editOnlyAnImmediateSeed = () => {{
                const input = document.querySelector(
                  '[role="textbox"][aria-label="姓名"]',
                );
                if (
                  window.location.pathname === "/resume/{resume_id}" &&
                  input instanceof HTMLElement && input.isContentEditable
                ) {{
                  input.focus();
                  window.getSelection()?.selectAllChildren(input);
                  if (!document.execCommand(
                    "insertText", false, "Stale History Handoff",
                  )) {{
                    throw new Error("Name editor could not accept text.");
                  }}
                  window.__staleResumeHandoffEdited = true;
                  return;
                }}
                if (
                  window.location.pathname === "/resume/{resume_id}" &&
                  !openedBasicInfo
                ) {{
                  const trigger = [...document.querySelectorAll("button")]
                    .find((candidate) =>
                      candidate.getAttribute("aria-label") ===
                      "基本信息: 展开或收起模块",
                    );
                  if (trigger instanceof HTMLButtonElement) {{
                    openedBasicInfo = true;
                    trigger.click();
                  }}
                }}
                if (performance.now() < deadline) {{
                  requestAnimationFrame(editOnlyAnImmediateSeed);
                }}
              }};
              requestAnimationFrame(editOnlyAnImmediateSeed);
            }}
            """
        )

        page.go_back(wait_until="commit")
        page.wait_for_url(f"{frontend_url}/resume/{resume_id}")
        page.wait_for_load_state("networkidle")
        if not page.get_by_role("textbox", name="姓名", exact=True).is_visible():
            page.get_by_role(
                "button",
                name=re.compile(
                    r"^(Basic Info: Toggle section|基本信息: 展开或收起模块)$"
                ),
            ).click()

        assert page.evaluate("window.__staleResumeHandoffEdited") is False
        assert page.get_by_role("textbox", name="姓名", exact=True).inner_text() == (
            "Saved After Initial Handoff"
        )
    finally:
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()
