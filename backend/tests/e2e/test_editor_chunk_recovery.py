from __future__ import annotations

import json
import os
import re
from contextlib import suppress
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Dialog, Error, Route, expect

from tests.e2e.browser_support import RouteReady, authenticated_context
from tests.e2e.conftest import FRONTEND_ROOT

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1" or os.getenv("E2E_FRONTEND_MODE") != "preview",
    reason="build the frontend and set RUN_BROWSER_E2E=1, E2E_FRONTEND_MODE=preview",
)


@pytest.mark.parametrize("failed_chunk", ["section-entry", "shared-dependency"])
def test_editor_chunk_recovery_saves_latest_content_before_reloading(
    browser: Browser, workspace_servers: tuple[str, str], failed_chunk: str
) -> None:
    frontend_url, _ = workspace_servers
    dist = Path(os.getenv("E2E_FRONTEND_DIST_DIR", str(FRONTEND_ROOT / "dist")))
    manifest = json.loads((dist / ".vite/manifest.json").read_text(encoding="utf-8"))
    if failed_chunk == "section-entry":
        asset = manifest["src/components/editor/resume-section-content.tsx"]["file"]
    else:
        matches = [
            entry
            for entry in manifest.values()
            if entry.get("name") == "resume-text-marks"
        ]
        assert len(matches) == 1
        asset = matches[0]["file"]
    messages = json.loads(
        (FRONTEND_ROOT / "src/i18n/locales/en.json").read_text(encoding="utf-8")
    )
    context = authenticated_context(
        browser, locale="en-US", viewport={"width": 1672, "height": 900}
    )
    page = context.new_page()
    dialogs: list[str] = []
    chunk_requests: list[str] = []
    held_chunks: list[Route] = []
    held_saves: list[Route] = []
    save_payloads: list[dict] = []
    failed_saves = 0
    save_phase = "hold"
    save_ready = RouteReady()
    chunk_ready = RouteReady()

    def dismiss_dialog(dialog: Dialog) -> None:
        dialogs.append(dialog.type)
        dialog.dismiss()

    def load_chunk(route: Route) -> None:
        chunk_requests.append(route.request.url)
        if len(chunk_requests) == 1:
            held_chunks.append(route)
            chunk_ready.set()
        else:
            route.continue_()

    def reject_save(route: Route) -> None:
        nonlocal failed_saves
        failed_saves += 1
        route.fulfill(
            status=500,
            content_type="application/json",
            body=json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "INTERNAL_ERROR",
                        "message": "Injected save failure",
                    },
                }
            ),
        )

    def handle_save(route: Route) -> None:
        if route.request.method != "PUT":
            route.continue_()
            return
        save_payloads.append(route.request.post_data_json)
        if save_phase == "hold":
            held_saves.append(route)
            save_ready.set()
        elif save_phase == "fail":
            reject_save(route)
        else:
            route.continue_()

    page.on("dialog", dismiss_dialog)
    try:
        response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"documentLocale": "en", "title": "Editor chunk recovery"},
        )
        assert response.ok, response.text()
        initial = response.json()["data"]["resume"]
        resume_id = initial["id"]
        payload = {
            key: initial[key]
            for key in (
                "title",
                "documentLocale",
                "resume",
                "jobBrief",
                "typography",
                "template",
                "templateSettings",
            )
        }
        payload["resume"]["basic"]["phone"] = "1111111111"
        payload["resume"]["sections"] = [
            {
                "id": "chunk-experience",
                "kind": "experience",
                "title": "Recovery experience",
                "items": [],
            }
        ]
        saved = page.request.put(
            f"{frontend_url}/api/resumes/{resume_id}", data=payload
        )
        assert saved.ok, saved.text()
        page.route(
            re.compile(r"^https?://[^/]+/" + re.escape(asset) + r"(?:\?.*)?$"),
            load_chunk,
        )
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.evaluate("window.__editorChunkRecoveryMarker = true")
        assert chunk_requests == []
        editor = page.locator(".resume-editor-panel")
        editor_node = editor.element_handle()
        assert editor_node is not None
        basic_toggle = page.get_by_role(
            "button",
            name=f"{messages['basicInfo']}: {messages['toggleSection']}",
            exact=True,
        )
        section = editor.locator('[data-resume-section-id="chunk-experience"]')
        section_toggle = section.get_by_role(
            "button",
            name=f"Recovery experience: {messages['toggleSection']}",
            exact=True,
        )
        basic_toggle.click()
        phone = page.get_by_role(
            "textbox", name=messages["fieldLabels"]["phone"], exact=True
        )
        expect(phone).to_have_value("1111111111")
        page.route(f"**/api/resumes/{resume_id}*", handle_save)
        phone.fill("2222222222")
        page.keyboard.press("ControlOrMeta+s")
        save_ready.wait(page)
        assert held_saves
        if failed_chunk == "section-entry":
            section_toggle.click()
        chunk_ready.wait(page)
        assert len(held_chunks) == 1
        held_chunks.pop().abort("failed")
        local_error = editor.get_by_role("alert")
        recovery = local_error.get_by_role("button")
        expect(recovery).to_be_visible()
        expect(recovery).to_have_text("Save and reload")
        expect(local_error).to_be_visible()
        assert len(chunk_requests) == 1
        assert dialogs == []
        assert editor_node.evaluate("element => element.isConnected")

        recovery.click()
        expect(recovery).to_be_disabled()
        save_phase = "fail"
        for route in held_saves:
            reject_save(route)
        held_saves.clear()
        expect(recovery).to_be_enabled()
        expect(local_error).to_contain_text(messages["resourceRecoverySaveError"])
        assert failed_saves >= 1
        assert dialogs == []
        assert editor_node.evaluate("element => element.isConnected")
        assert page.url == f"{frontend_url}/resume/{resume_id}"
        unchanged = page.request.get(f"{frontend_url}/api/resumes/{resume_id}")
        assert (
            unchanged.json()["data"]["resume"]["resume"]["basic"]["phone"]
            == "1111111111"
        )
        if failed_chunk == "section-entry":
            basic_toggle.click()
            expect(phone).to_have_value("2222222222")
            section_toggle.click()

        save_phase = "hold"
        save_ready.clear()
        recovery.click()
        save_ready.wait(page)
        expect(recovery).to_be_disabled()
        assert held_saves
        latest_phone = "2222222222"
        if failed_chunk == "section-entry":
            basic_toggle.click()
            expect(local_error).to_have_count(0)
            phone.fill("3333333333")
            latest_phone = "3333333333"
            expect(phone).to_have_value(latest_phone)
        assert dialogs == []
        save_phase = "pass"
        with page.expect_navigation(wait_until="networkidle"):
            for route in held_saves:
                route.continue_()
            held_saves.clear()
        assert page.evaluate("window.__editorChunkRecoveryMarker") is None
        expect(editor).to_be_visible()
        basic_toggle.click()
        expect(phone).to_have_value(latest_phone)
        section_toggle.click()
        section.get_by_role(
            "button", name=f"Recovery experience: {messages['moreActions']}", exact=True
        ).click()
        page.get_by_role(
            "menuitem", name=messages["renameSectionAction"], exact=True
        ).click()
        name = page.get_by_role("textbox", name=messages["renameSection"], exact=True)
        expect(name).to_have_value("Recovery experience")
        name.press("Escape")
        expect(recovery).to_have_count(0)
        assert len(chunk_requests) >= 2
        assert dialogs == []
        assert save_payloads[-1]["resume"]["basic"]["phone"] == latest_phone
        persisted = page.request.get(f"{frontend_url}/api/resumes/{resume_id}")
        assert persisted.ok, persisted.text()
        assert (
            persisted.json()["data"]["resume"]["resume"]["basic"]["phone"]
            == latest_phone
        )
    finally:
        for route in [*held_saves, *held_chunks]:
            with suppress(Error):
                route.abort()
        context.close()


def test_template_image_chunk_recovery_preserves_edits_until_latest_save_succeeds(
    browser: Browser, workspace_servers: tuple[str, str]
) -> None:
    frontend_url, _ = workspace_servers
    dist = Path(os.getenv("E2E_FRONTEND_DIST_DIR", str(FRONTEND_ROOT / "dist")))
    manifest = json.loads((dist / ".vite/manifest.json").read_text(encoding="utf-8"))
    asset = manifest["src/components/templates/editor/images-tab.tsx"]["file"]
    messages = json.loads(
        (FRONTEND_ROOT / "src/i18n/locales/en.json").read_text(encoding="utf-8")
    )
    presets = json.loads(
        (Path(__file__).parents[2] / "app/services/template_presets.json").read_text(
            encoding="utf-8"
        )
    )
    context = authenticated_context(
        browser,
        locale="en-US",
        viewport={"width": 1672, "height": 900},
        reduced_motion="reduce",
    )
    page = context.new_page()
    held_chunks: list[Route] = []
    held_saves: list[Route] = []
    chunk_requests: list[str] = []
    save_payloads: list[dict] = []
    dialogs: list[str] = []
    chunk_ready = RouteReady()
    save_ready = RouteReady()
    save_phase = "fail"
    template_id: str | None = None

    def load_chunk(route: Route) -> None:
        chunk_requests.append(route.request.url)
        if len(chunk_requests) == 1:
            held_chunks.append(route)
            chunk_ready.set()
        else:
            route.continue_()

    def handle_save(route: Route) -> None:
        if route.request.method != "PUT":
            route.continue_()
            return
        save_payloads.append(route.request.post_data_json)
        if save_phase == "fail":
            route.fulfill(
                status=503,
                content_type="application/json",
                body=json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "INTERNAL_ERROR",
                            "message": "Injected save failure",
                        },
                    }
                ),
            )
        elif save_phase == "hold":
            held_saves.append(route)
            save_ready.set()
        else:
            route.continue_()

    def dismiss_dialog(dialog: Dialog) -> None:
        dialogs.append(dialog.type)
        dialog.dismiss()

    page.on("dialog", dismiss_dialog)
    try:
        response = page.request.post(
            f"{frontend_url}/api/templates",
            data={
                "template": {
                    "preset": "minimal",
                    "name": "Template chunk recovery",
                    "description": "",
                    **{
                        key: presets["minimal"][key]
                        for key in ("layout", "typography", "settings")
                    },
                }
            },
        )
        assert response.ok, response.text()
        template = response.json()["data"]["template"]
        template_id = template["id"]
        endpoint = f"{frontend_url}/api/templates/{template_id}"
        page.route(
            re.compile(r"^https?://[^/]+/" + re.escape(asset) + r"(?:\?.*)?$"),
            load_chunk,
        )
        page.route(f"**/api/templates/{template_id}", handle_save)
        page.goto(
            f"{frontend_url}/template/{template_id}", wait_until="domcontentloaded"
        )
        chunk_ready.wait(page)
        page.evaluate("window.__templateChunkRecoveryMarker = true")
        assert len(chunk_requests) == 1
        editor = page.locator('[data-slot="template-editor"]')
        expect(editor).to_be_visible()
        editor_node = editor.element_handle()
        assert editor_node is not None
        page.get_by_role(
            "button", name=messages["editTemplateInfo"], exact=True
        ).click()
        metadata = page.get_by_role("dialog", name=messages["editTemplateInfo"])
        metadata.get_by_label(messages["templateName"], exact=True).fill(
            "Unsaved template metadata"
        )
        metadata.get_by_role("button", name=messages["saveTemplateInfo"]).click()
        images_tab = page.get_by_role("tab", name=messages["templateImagesTab"])
        images_tab.click()
        chunk_ready.wait(page)
        held_chunks.pop().abort("failed")
        local_error = editor.get_by_role("alert")
        recovery = local_error.get_by_role("button", name=messages["saveAndReload"])
        expect(recovery).to_be_visible()
        assert editor_node.evaluate("element => element.isConnected")
        expect(
            page.locator('[data-slot="template-workspace-header"]').locator(
                '[data-slot="template-editor-title"]'
            )
        ).to_have_text("Unsaved template metadata")
        recovery.click()
        expect(local_error).to_contain_text(messages["resourceRecoverySaveError"])
        expect(recovery).to_be_enabled()
        assert page.evaluate("window.__templateChunkRecoveryMarker") is True
        persisted = page.request.get(endpoint).json()["data"]["template"]
        assert persisted["name"] == template["name"]
        assert save_payloads
        assert dialogs == []

        save_phase = "hold"
        recovery.click()
        save_ready.wait(page)
        assert held_saves
        page.get_by_role("tab", name=messages["templateTypographyTab"]).click()
        expect(local_error).not_to_be_visible()
        name_size = page.get_by_role(
            "spinbutton", name=messages["nameSize"], exact=True
        )
        latest_scale = 2.7
        latest_points = (
            round(template["typography"]["fontSize"] * 0.75, 2) * latest_scale
        )
        name_size.fill(str(round(latest_points, 2)))
        name_size.press("Enter")
        expect(name_size).to_have_value(str(round(latest_points, 2)))
        images_tab.click()
        expect(local_error.get_by_role("button")).to_be_disabled()
        save_phase = "pass"
        with page.expect_navigation(wait_until="networkidle"):
            for route in held_saves:
                route.continue_()
            held_saves.clear()
        assert page.evaluate("window.__templateChunkRecoveryMarker") is None
        assert save_payloads[-1]["saveMode"] == "checkpoint"
        assert save_payloads[-1]["template"]["settings"]["nameScale"] == latest_scale
        detail = page.request.get(endpoint).json()["data"]
        assert detail["template"]["name"] == "Unsaved template metadata"
        assert detail["template"]["settings"]["nameScale"] == latest_scale
        assert detail["checkpoint"] is None
        images_tab.click()
        expect(
            page.get_by_role("button", name=messages["addTemplateImage"], exact=True)
        ).to_be_visible()
        expect(local_error).to_have_count(0)
        assert len(chunk_requests) >= 2
        assert dialogs == []
    finally:
        for route in [*held_saves, *held_chunks]:
            with suppress(Error):
                route.abort()
        if template_id:
            response = page.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if response.ok:
                page.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()
