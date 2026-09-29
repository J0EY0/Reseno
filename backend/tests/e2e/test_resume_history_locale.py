from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import Browser, expect

from tests.e2e.browser_support import DeferredRoute, authenticated_context
from tests.e2e.conftest import FRONTEND_ROOT

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def test_history_locale_loading_preserves_canvas_and_viewport_state(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    asset = "src/i18n/locales/zh.json"
    if os.getenv("E2E_FRONTEND_MODE") == "preview":
        dist = Path(os.getenv("E2E_FRONTEND_DIST_DIR", str(FRONTEND_ROOT / "dist")))
        manifest = json.loads((dist / ".vite/manifest.json").read_text())
        asset = manifest[asset]["file"]
    messages = json.loads((FRONTEND_ROOT / "src/i18n/locales/en.json").read_text())
    chinese_messages = json.loads(
        (FRONTEND_ROOT / "src/i18n/locales/zh.json").read_text()
    )
    context = authenticated_context(
        browser, locale="en-US", viewport={"width": 1672, "height": 870}
    )
    context.add_init_script(
        "localStorage.setItem('reseno-workspace-layout-v1', "
        "JSON.stringify({ agentCollapsed: true }))"
    )
    page = context.new_page()
    locale_gate = DeferredRoute(page, f"**/{asset}*")
    try:
        response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"documentLocale": "zh", "title": "Historical document locale"},
        )
        assert response.ok, response.text()
        created = response.json()["data"]["resume"]
        resume_id = created["id"]
        payload = {
            key: created[key]
            for key in (
                "documentLocale",
                "jobBrief",
                "resume",
                "template",
                "templateSettings",
                "title",
                "typography",
            )
        }
        payload["documentLocale"] = "en"
        payload["resume"]["basic"]["name"] = "Current English Document"
        saved = page.request.put(
            f"{frontend_url}/api/resumes/{resume_id}?saveMode=checkpoint",
            data=payload,
        )
        assert saved.ok, saved.text()
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="domcontentloaded")
        viewport = page.locator('[data-slot="document-canvas-viewport"]')
        expect(viewport).to_contain_text("Current English Document")
        fit = page.get_by_role("button", name=messages["fitToWidth"], exact=True)
        fit.click()
        expect(fit).to_have_attribute("aria-pressed", "true")
        viewport.evaluate("element => { element.scrollTop = 180; }")
        expect(viewport).to_have_js_property("scrollTop", 180)
        viewport_node = viewport.element_handle()
        canvas_node = page.locator(".resume-preview-card").element_handle()
        assert viewport_node is not None and canvas_node is not None
        scale = viewport.evaluate(
            "element => getComputedStyle(element).getPropertyValue('--canvas-scale')"
        )

        page.get_by_role("button", name=messages["saveVersions"], exact=True).click()
        popover = page.get_by_role("dialog", name=messages["saveVersions"], exact=True)
        historical = popover.get_by_role("button").last
        with page.expect_response(f"{frontend_url}/api/resumes/{resume_id}/versions/1"):
            historical.click()
        locale_gate.wait()
        page.evaluate(
            """() => new Promise(resolve =>
              requestAnimationFrame(() => requestAnimationFrame(resolve)))"""
        )
        assert canvas_node.evaluate("element => element.isConnected")
        assert viewport_node.evaluate("element => element.isConnected")
        expect(page.locator('[data-slot="workspace-preview-skeleton"]')).to_have_count(
            0
        )
        expect(viewport).to_contain_text("Current English Document")
        expect(historical).to_be_disabled()
        expect(viewport).to_have_js_property("scrollTop", 180)

        locale_gate.release()
        expect(viewport.locator("h1").first).to_have_text(
            chinese_messages["resumePreviewFallbackName"]
        )
        assert viewport_node.evaluate(
            """element => element === document.querySelector(
              '[data-slot="document-canvas-viewport"]')"""
        )
        assert canvas_node.evaluate("element => element.isConnected")
        expect(viewport).to_have_js_property("scrollTop", 180)
        expect(fit).to_have_attribute("aria-pressed", "true")
        assert (
            viewport.evaluate(
                "element => getComputedStyle(element)"
                ".getPropertyValue('--canvas-scale')"
            )
            == scale
        )
    finally:
        locale_gate.release()
        context.close()
