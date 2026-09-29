"""Resume history and export transactions through the live editor."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, Request, Route, expect

from tests.e2e.browser_support import DeferredRoute, RouteReady, authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _open_basic_info(page: Page) -> None:
    page.get_by_role("button", name="基本信息: 展开或收起模块", exact=True).click()
    expect(page.get_by_role("textbox", name="姓名", exact=True)).to_be_visible()


@pytest.mark.parametrize(
    ("width", "reduced_motion"), [(1672, "no-preference"), (1100, "reduce")]
)
def test_history_loading_and_preview_preserve_current_editor_title_and_format(
    browser: Browser,
    workspace_servers: tuple[str, str],
    width: int,
    reduced_motion: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": width, "height": 900},
        reduced_motion=reduced_motion,
    )
    page = context.new_page()
    version_gate: DeferredRoute | None = None
    save_requests: list[Request] = []
    try:
        created_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"documentLocale": "zh", "title": "History request"},
        )
        assert created_response.ok
        created = created_response.json()["data"]
        resume = created["resume"]
        resume_id = resume["id"]
        historical_name = resume["resume"]["basic"]["name"]
        payload = {
            key: resume[key]
            for key in (
                "documentLocale",
                "title",
                "resume",
                "jobBrief",
                "typography",
                "template",
                "templateSettings",
            )
        }
        payload["resume"]["basic"]["name"] = "Current checkpoint"
        checkpoint = page.request.put(
            f"{frontend_url}/api/resumes/{resume_id}?saveMode=checkpoint",
            data=payload,
        )
        assert checkpoint.ok
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        _open_basic_info(page)
        name_input = page.get_by_role("textbox", name="姓名", exact=True)
        title_trigger = page.get_by_role("button", name="修改简历标题", exact=True)
        format_trigger = page.get_by_role("button", name="格式", exact=True)
        editor = page.locator(".resume-editor-panel")
        preview = page.locator(".resume-preview-card article.resume-page").first
        current_name = "Name saved before history preview"
        current_title = "Title saved before history preview"
        name_input.fill(current_name)
        title_trigger.click()
        dialog = page.get_by_role("dialog", name="修改简历标题", exact=True)
        dialog.get_by_role("textbox").fill(current_title)
        dialog.get_by_role("button", name="保存", exact=True).click()
        format_trigger.click()
        font_size = page.get_by_role("combobox", name="字号", exact=True)
        font_size.click()
        page.get_by_role("option", name="15 pt", exact=True).click()
        page.keyboard.press("Escape")
        pattern = f"**/api/resumes/{resume_id}/versions/{created['versionId']}"
        version_gate = DeferredRoute(page, pattern)
        page.get_by_role("button", name="历史版本", exact=True).click()
        version_popover = page.locator(
            '[data-slot="popover-content"][aria-label="历史版本"]'
        )
        version_popover.get_by_role("button").last.click()
        leave_dialog = page.get_by_role("dialog", name="有未保存的更改", exact=True)
        expect(leave_dialog).to_be_visible()
        assert version_gate.pending == ()
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and f"/api/resumes/{resume_id}?" in response.url
            )
        ) as saved_response:
            leave_dialog.get_by_role("button", name="保存并离开", exact=True).click()
        assert saved_response.value.ok
        saved_checkpoint = saved_response.value.json()["data"]

        def record_save(request: Request) -> None:
            if request.method == "PUT" and f"/api/resumes/{resume_id}?" in request.url:
                save_requests.append(request)

        page.on("request", record_save)
        version_gate.wait()
        expect(leave_dialog).not_to_be_visible()

        expect(editor).to_have_attribute("inert", "")
        expect(title_trigger).to_be_disabled()
        expect(format_trigger).to_be_disabled()
        expect(name_input).to_have_text(current_name)
        expect(page.locator("header h1[title]")).to_have_text(current_title)
        expect(preview).to_contain_text(current_name)
        page.keyboard.press("ControlOrMeta+z")
        page.keyboard.press("ControlOrMeta+s")
        expect(name_input).to_have_text(current_name)
        assert save_requests == []

        version_gate.release()
        toolbar = page.get_by_role("region", name="正在查看历史版本", exact=True)
        expect(toolbar).to_be_visible()
        expect(toolbar).to_contain_text("只读")
        expect(editor).to_have_attribute("inert", "")
        expect(title_trigger).to_be_disabled()
        expect(format_trigger).to_be_disabled()
        expect(name_input).to_have_text(historical_name)
        expect(preview).not_to_contain_text(current_name)
        expect(page.locator("header h1[title]")).to_have_text("History request")
        page.keyboard.press("Escape")
        expect(version_popover).not_to_be_visible()
        page.keyboard.press("ControlOrMeta+s")
        current_detail = page.request.get(
            f"{frontend_url}/api/resumes/{resume_id}"
        ).json()["data"]
        assert current_detail == saved_checkpoint
        assert save_requests == []

        toolbar.get_by_role("button", name="回到最新版", exact=True).click()
        expect(toolbar).not_to_be_visible()
        expect(editor).not_to_have_attribute("inert", "")
        expect(title_trigger).to_be_enabled()
        expect(format_trigger).to_be_enabled()
        expect(name_input).to_have_text(current_name)
        expect(preview).to_contain_text(current_name)
        expect(page.locator("header h1[title]")).to_have_text(current_title)
        format_trigger.click()
        expect(page.get_by_role("combobox", name="字号", exact=True)).to_have_text(
            "15 pt"
        )
        page.keyboard.press("Escape")
        assert save_requests == []

        name_input.fill("Name edited after returning to latest")
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and f"/api/resumes/{resume_id}?" in response.url
            )
        ):
            page.keyboard.press("ControlOrMeta+s")
        saved = page.request.get(f"{frontend_url}/api/resumes/{resume_id}").json()[
            "data"
        ]["resume"]
        assert saved["resume"]["basic"]["name"] == (
            "Name edited after returning to latest"
        )
        assert saved["title"] == current_title
        assert saved["typography"]["fontSize"] == 20
    finally:
        if version_gate:
            version_gate.release(Route.abort)
        context.close()


def test_json_export_uses_saved_document_and_matching_custom_template(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 900}
    )
    page = context.new_page()
    pending: list[Route] = []
    route_ready = RouteReady()
    has_held_save = False

    def hold_first_save(route: Route) -> None:
        nonlocal has_held_save
        if route.request.method == "PUT" and not has_held_save:
            has_held_save = True
            pending.append(route)
            route_ready.set()
        else:
            route.continue_()

    try:
        presets = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "app/services/template_presets.json"
            ).read_text(encoding="utf-8")
        )
        templates = []
        for name in ("Snapshot A", "Snapshot B"):
            response = page.request.post(
                f"{frontend_url}/api/templates",
                data={
                    "template": {
                        "preset": "minimal",
                        "name": name,
                        "description": "",
                        **{
                            key: presets["minimal"][key]
                            for key in ("layout", "typography", "settings")
                        },
                    }
                },
            )
            assert response.ok
            templates.append(response.json()["data"]["template"])
        response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"documentLocale": "zh", "template": templates[0]["id"]},
        )
        assert response.ok
        resume_id = response.json()["data"]["resume"]["id"]
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        _open_basic_info(page)
        name_input = page.get_by_role("textbox", name="姓名", exact=True)
        name_input.fill("Saved export name")
        page.route(f"**/api/resumes/{resume_id}?*", hold_first_save)
        with page.expect_download() as download_info:
            page.get_by_role("button", name="导出", exact=True).click()
            with page.expect_request(lambda request: request.method == "PUT"):
                page.get_by_role("menuitem", name="JSON", exact=True).click()
            route_ready.wait(page)
            assert pending
            name_input.fill("Newer live name")
            page.get_by_role("button", name="格式", exact=True).click()
            page.get_by_role("combobox", name="应用模板", exact=True).click()
            page.get_by_role("option", name="Snapshot B", exact=True).click()
            page.keyboard.press("Escape")
            pending.pop().continue_()
        download_path = download_info.value.path()
        assert download_path is not None
        artifact = json.loads(Path(download_path).read_text(encoding="utf-8"))
        assert artifact["resumes"][0]["resume"]["basic"]["name"] == (
            "Saved export name"
        )
        assert artifact["templates"][0]["definition"]["name"] == "Snapshot A"
        expect(name_input).to_have_text("Newer live name")
        page.get_by_role("button", name="格式", exact=True).click()
        expect(page.get_by_role("combobox", name="应用模板", exact=True)).to_have_text(
            "Snapshot B"
        )
    finally:
        for route in pending:
            route.abort()
        context.close()
