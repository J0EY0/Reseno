from __future__ import annotations

import json
import os
import time
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Browser, Route, expect
from playwright.sync_api import Error as PlaywrightError

from tests.e2e.browser_support import RouteReady
from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_resume_autosave_persists_edit_made_during_active_save(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()
    save_payloads: list[dict[str, object]] = []
    save_urls: list[str] = []
    held_saves: list[Route] = []
    route_ready = RouteReady()

    def delay_first_save(route: Route) -> None:
        request = route.request
        if request.method != "PUT":
            route.continue_()
            return

        payload = request.post_data_json
        assert isinstance(payload, dict)
        save_payloads.append(payload)
        save_urls.append(request.url)
        if len(save_payloads) == 1:
            held_saves.append(route)
            route_ready.set()
            return
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
        name_input.fill("First Save Payload")
        with page.expect_request(
            lambda request: (
                request.method == "PUT"
                and urlparse(request.url).path == f"/api/resumes/{resume_id}"
            )
        ):
            page.keyboard.press("Control+S")
        route_ready.wait(page)
        assert len(held_saves) == 1
        name_input.fill("Latest Edit During Save")
        page.get_by_role("button", name="修改简历标题", exact=True).click()
        title_dialog = page.get_by_role("dialog", name="修改简历标题", exact=True)
        title_dialog.get_by_role("textbox").fill("Latest Title During")
        title_dialog.get_by_role("button", name="保存", exact=True).click()
        page.get_by_role("button", name="返回简历列表", exact=True).click()
        held_saves.pop().continue_()

        deadline = time.monotonic() + 8
        while len(save_payloads) < 2 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert len(save_payloads) >= 2, save_payloads
        assert "saveMode=autosave" in save_urls[1]
        autosaved_payload = save_payloads[1]
        assert autosaved_payload["title"] == "Latest Title During"
        assert autosaved_payload["resume"]["basic"]["name"] == (
            "Latest Edit During Save"
        )

        save_and_leave = page.get_by_role(
            "button",
            name="保存并离开",
            exact=True,
        )
        assert save_and_leave.count() == 1
        save_and_leave.click()
        page.wait_for_url(f"{frontend_url}/resume")

        deadline = time.monotonic() + 5
        while len(save_payloads) < 3 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert len(save_payloads) >= 3, save_payloads
        assert "saveMode=checkpoint" in save_urls[-1]
        assert save_payloads[-1]["title"] == "Latest Title During"
        assert save_payloads[-1]["resume"]["basic"]["name"] == (
            "Latest Edit During Save"
        )

        page.wait_for_load_state("networkidle")
        persisted_response = page.request.get(f"{frontend_url}/api/resumes/{resume_id}")
        persisted = persisted_response.json()["data"]["resume"]
        assert persisted["title"] == "Latest Title During"
        assert persisted["resume"]["basic"]["name"] == "Latest Edit During Save"
    finally:
        context.close()


@pytest.mark.browser_smoke
def test_save_status_announces_unsaved_saving_and_saved_states(
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
    held_saves: list[Route] = []
    route_ready = RouteReady()

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": "Save status announcement regression",
            },
        )
        assert create_response.ok
        resume_id = str(create_response.json()["data"]["resume"]["id"])

        def hold_checkpoint_save(route: Route) -> None:
            if route.request.method == "PUT" and parse_qs(
                urlparse(route.request.url).query
            ).get("saveMode") == ["checkpoint"]:
                held_saves.append(route)
                route_ready.set()
                return

            route.continue_()

        page.route(f"**/api/resumes/{resume_id}*", hold_checkpoint_save)
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        page.get_by_role("textbox", name="姓名", exact=True).fill(
            "Accessible Save State"
        )

        announcement = page.locator('[data-slot="save-status-announcement"]')
        expect(announcement).to_have_attribute("role", "status")
        expect(announcement).to_have_attribute("aria-live", "polite")
        expect(announcement).to_have_attribute("aria-atomic", "true")
        expect(announcement).to_have_text("有未保存更改")

        with page.expect_request(
            lambda request: (
                request.method == "PUT"
                and urlparse(request.url).path == f"/api/resumes/{resume_id}"
                and parse_qs(urlparse(request.url).query).get("saveMode")
                == ["checkpoint"]
            )
        ):
            page.get_by_role(
                "button",
                name="保存状态",
                exact=True,
            ).click()

        expect(announcement).to_have_text("正在保存")
        route_ready.wait(page)
        assert len(held_saves) == 1
        held_saves.pop().continue_()
        expect(announcement).to_contain_text("已保存")
    finally:
        for route in held_saves:
            try:
                route.continue_()
            except PlaywrightError:
                pass
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_autosave_max_wait_retries_with_backoff_without_toast_storm(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()
    save_urls: list[str] = []
    active_saves = 0
    max_active_saves = 0

    def fail_autosave(route: Route) -> None:
        nonlocal active_saves, max_active_saves
        if route.request.method != "PUT":
            route.continue_()
            return

        save_urls.append(route.request.url)
        active_saves += 1
        max_active_saves = max(max_active_saves, active_saves)
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
        active_saves -= 1

    page.route(f"**/api/resumes/{resume_id}*", fail_autosave)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        name_input = page.get_by_role("textbox", name="姓名", exact=True)
        page.clock.install()
        first_edit_started_at = page.evaluate("Date.now()")

        # Keep resetting the 5-second idle timer. maxWait must still flush at
        # 30 seconds from the first dirty edit.
        for index in range(7):
            name_input.fill(f"Continuous Edit {index}")
            page.clock.fast_forward(4_000)

        # The final edit lands at 28 seconds. Advance in small steps until the
        # first request appears, then test retry delays relative to that exact
        # failure instead of assuming network callbacks are instantaneous.
        name_input.fill("Continuous Edit 7")
        deadline = time.monotonic() + 3
        while len(save_urls) < 1 and time.monotonic() < deadline:
            page.clock.fast_forward(100)
            page.wait_for_timeout(25)

        assert len(save_urls) == 1, save_urls
        assert page.evaluate("Date.now()") - first_edit_started_at >= 30_000
        assert "saveMode=autosave" in save_urls[0]

        page.clock.fast_forward(1_999)
        assert len(save_urls) == 1, save_urls
        page.clock.fast_forward(1)
        deadline = time.monotonic() + 3
        while len(save_urls) < 2 and time.monotonic() < deadline:
            page.wait_for_timeout(25)
        assert len(save_urls) == 2, save_urls
        assert page.get_by_text("请求失败，请稍后重试", exact=True).count() == 0

        page.clock.fast_forward(4_999)
        assert len(save_urls) == 2, save_urls
        page.clock.fast_forward(1)
        deadline = time.monotonic() + 3
        while len(save_urls) < 3 and time.monotonic() < deadline:
            page.wait_for_timeout(25)
        assert len(save_urls) == 3, save_urls
        page.get_by_text("请求失败，请稍后重试", exact=True).wait_for(state="visible")

        page.clock.fast_forward(60_000)
        assert len(save_urls) == 3, save_urls
        assert max_active_saves == 1
        assert page.get_by_text("请求失败，请稍后重试", exact=True).count() == 1
    finally:
        context.close()
