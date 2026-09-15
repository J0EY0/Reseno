from __future__ import annotations

import os
import re
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Browser, Request, Route

from tests.e2e.browser_support import RouteReady
from tests.e2e.browser_support import authenticated_context as _authenticated_context
from tests.e2e.workspace_frame_support import (
    install_workspace_frame_recorder,
    start_workspace_frame_recording,
    stop_workspace_frame_recording,
)
from tests.e2e.workspace_network_support import api_request_key

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_duplicate_saved_resume_opens_only_from_toast_action(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 2048, "height": 1226})
    page = context.new_page()
    install_workspace_frame_recorder(page)
    resume_id: str | None = None
    duplicate_id: str | None = None
    duplicate_request_count = 0

    def count_duplicate_request(request: Request) -> None:
        nonlocal duplicate_request_count
        if resume_id and api_request_key(request) == (
            "POST",
            f"/api/resumes/{resume_id}/duplicate",
        ):
            duplicate_request_count += 1

    page.on("request", count_duplicate_request)

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": "王小明-zh-minimal（1）-frontend-fullstack-resume-2026",
            },
        )
        assert create_response.ok
        create_payload = create_response.json()
        assert create_payload["code"] == 0
        resume_id = create_payload["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.get_by_role(
            "button",
            name=re.compile(r"^(Basic Info: Toggle section|基本信息: 展开或收起模块)$"),
        ).click()
        page.get_by_role("textbox", name=re.compile(r"^(Full Name|姓名)$")).fill(
            "Duplicate Regression Source"
        )

        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
            )
        ) as save_response_info:
            page.get_by_role(
                "button",
                name=re.compile(r"^(Save Status|保存状态)$"),
            ).click()
        save_response = save_response_info.value
        assert save_response.ok
        assert save_response.json()["code"] == 0

        preview_page = page.locator(
            ".resume-preview-card article.resume-page",
        )
        preview_page.wait_for(state="visible")
        page.wait_for_timeout(600)
        initial_preview_bounds = preview_page.bounding_box()
        assert initial_preview_bounds is not None

        start_workspace_frame_recording(page)
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}/duplicate"
            )
        ) as duplicate_response_info:
            page.get_by_role(
                "button",
                name=re.compile(r"^(Duplicate|创建副本)$"),
            ).click()

        duplicate_response = duplicate_response_info.value
        assert duplicate_response.ok
        assert urlparse(duplicate_response.request.url).query == ""
        duplicate_payload = duplicate_response.json()
        assert duplicate_payload["code"] == 0
        duplicate_id = duplicate_payload["data"]["resume"]["id"]
        duplicate_title = duplicate_payload["data"]["resume"]["title"]
        copy_created_label = re.compile(r"Copy created|副本已创建")
        page.get_by_text(copy_created_label, exact=True).wait_for(state="visible")
        open_copy_action = page.get_by_role(
            "button",
            name=re.compile(r"^(View copy|查看副本)$"),
        )
        open_copy_action.wait_for(state="visible")
        success_toast = page.locator('[data-sonner-toast][data-type="success"]').filter(
            has_text=copy_created_label
        )
        toast_description = success_toast.locator("[data-description]")
        assert toast_description.inner_text() == duplicate_title
        assert (
            toast_description.evaluate(
                "(description) => getComputedStyle(description).whiteSpace"
            )
            == "nowrap"
        )
        assert (
            toast_description.evaluate(
                "(description) => getComputedStyle(description).overflow"
            )
            == "hidden"
        )
        assert (
            toast_description.evaluate(
                "(description) => getComputedStyle(description).textOverflow"
            )
            == "ellipsis"
        )
        assert toast_description.evaluate(
            "(description) => description.scrollWidth > description.clientWidth"
        )
        assert success_toast.locator("[data-icon]").count() == 0
        assert (
            open_copy_action.evaluate(
                "(button) => getComputedStyle(button).backgroundColor"
            )
            == "rgba(0, 0, 0, 0)"
        )
        assert (
            open_copy_action.evaluate(
                "(button) => getComputedStyle(button).borderTopWidth"
            )
            == "1px"
        )
        assert (
            open_copy_action.evaluate(
                "(button) => getComputedStyle(button).borderTopStyle"
            )
            == "solid"
        )
        assert open_copy_action.locator("svg").count() == 0
        close_button = success_toast.locator("[data-close-button]")
        close_shadow_before_hover = close_button.evaluate(
            "(button) => getComputedStyle(button).boxShadow"
        )
        close_button.hover()
        assert (
            close_button.evaluate("(button) => getComputedStyle(button).boxShadow")
            == close_shadow_before_hover
        )
        action_bounds = open_copy_action.bounding_box()
        close_bounds = close_button.bounding_box()
        assert action_bounds is not None
        assert close_bounds is not None
        assert action_bounds["x"] + action_bounds["width"] <= close_bounds["x"]
        assert page.url == f"{frontend_url}/resume/{resume_id}"

        source_preview_bounds = preview_page.bounding_box()
        assert source_preview_bounds is not None
        assert source_preview_bounds["width"] == pytest.approx(
            initial_preview_bounds["width"],
            abs=1,
        )

        open_copy_action.click()
        page.wait_for_url(f"{frontend_url}/resume/{duplicate_id}", timeout=5_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        frames = stop_workspace_frame_recording(page)

        final_preview_page = page.locator(
            ".resume-preview-card article.resume-page",
        )
        final_preview_page.wait_for(state="visible")
        final_preview_bounds = final_preview_page.bounding_box()
        assert final_preview_bounds is not None
        toolbar_title = page.locator("#main-content > header h1")
        assert toolbar_title.get_attribute("title") == duplicate_title
        assert toolbar_title.inner_text().endswith(
            duplicate_title.rsplit(" - ", maxsplit=1)[-1]
        )
        assert toolbar_title.evaluate(
            "(element) => element.scrollWidth <= element.clientWidth"
        )
        routed_frames = [
            frame for frame in frames if frame["path"] == f"/resume/{duplicate_id}"
        ]

        assert duplicate_request_count == 1
        assert page.get_by_role("dialog").count() == 0
        assert len(routed_frames) >= 2
        # Opening the copy revalidates its detail route. Once the target mounts,
        # every rendered preview frame must keep its A4 width.
        assert all(bool(frame["hasResumeDetail"]) for frame in routed_frames[-2:])
        assert all(
            bool(frame["resumePreviewFits"])
            for frame in routed_frames
            if frame["hasResumeDetail"]
        )
        assert all(
            float(frame["resumePreviewWidth"])
            == pytest.approx(initial_preview_bounds["width"], abs=1)
            for frame in routed_frames
            if frame["resumePreviewWidth"] is not None
        )
        assert final_preview_bounds["width"] == pytest.approx(
            initial_preview_bounds["width"],
            abs=1,
        )
    finally:
        for cleanup_resume_id in (duplicate_id, resume_id):
            if not cleanup_resume_id:
                continue
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{cleanup_resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{cleanup_resume_id}")
        context.close()


def test_duplicate_resume_stops_if_content_changes_during_save(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 2048, "height": 1226},
    )
    page = context.new_page()
    resume_id: str | None = None
    duplicate_request_count = 0
    held_saves: list[Route] = []
    route_ready = RouteReady()

    def count_duplicate_request(request: Request) -> None:
        nonlocal duplicate_request_count
        if resume_id and api_request_key(request) == (
            "POST",
            f"/api/resumes/{resume_id}/duplicate",
        ):
            duplicate_request_count += 1

    page.on("request", count_duplicate_request)

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"documentLocale": "zh"},
        )
        assert create_response.ok
        create_payload = create_response.json()
        assert create_payload["code"] == 0
        resume_id = create_payload["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()

        def hold_checkpoint_save(route: Route) -> None:
            if route.request.method != "PUT":
                route.continue_()
                return

            held_saves.append(route)
            route_ready.set()

        page.route(f"**/api/resumes/{resume_id}*", hold_checkpoint_save)

        name_input = page.get_by_role("textbox", name="姓名", exact=True)
        name_input.fill("Snapshot captured for copy")
        with page.expect_request(
            lambda request: (
                request.method == "PUT"
                and urlparse(request.url).path == f"/api/resumes/{resume_id}"
            )
        ):
            page.get_by_role("button", name="创建副本", exact=True).click()

        route_ready.wait(page)
        assert len(held_saves) == 1
        held_request = held_saves[0].request
        assert parse_qs(urlparse(held_request.url).query)["saveMode"] == ["checkpoint"]
        submitted_payload = held_request.post_data_json
        assert submitted_payload["resume"]["basic"]["name"] == (
            "Snapshot captured for copy"
        )

        headline_input = page.get_by_role("textbox", name="职位 / 标题", exact=True)
        headline_input.fill("Newer edit must stay in the editor")
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
            )
        ) as save_response_info:
            held_saves[0].continue_()
        save_response = save_response_info.value
        assert save_response.ok
        assert save_response.json()["code"] == 0

        page.get_by_text(
            "保存期间内容发生变化，请再次创建副本",
            exact=True,
        ).wait_for(state="visible")

        assert duplicate_request_count == 0
        assert page.url == f"{frontend_url}/resume/{resume_id}"
        assert page.get_by_role("dialog").count() == 0
        assert headline_input.inner_text() == "Newer edit must stay in the editor"
        page.get_by_role("button", name="保存状态", exact=True).hover()
        page.get_by_text("有未保存更改", exact=True).wait_for(state="visible")
    finally:
        if resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()
