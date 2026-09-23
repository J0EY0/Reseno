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


@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
@pytest.mark.parametrize("ready_before_activation", [True, False])
def test_template_images_preload_without_delaying_other_editor_controls(
    browser: Browser,
    workspace_servers: tuple[str, str],
    reduced_motion: str,
    ready_before_activation: bool,
) -> None:
    frontend_url, _ = workspace_servers
    asset = "src/components/templates/editor/images-tab.tsx"
    if os.getenv("E2E_FRONTEND_MODE") == "preview":
        dist = Path(os.getenv("E2E_FRONTEND_DIST_DIR", str(FRONTEND_ROOT / "dist")))
        manifest = json.loads((dist / ".vite/manifest.json").read_text())
        asset = manifest[asset]["file"]
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
        reduced_motion=reduced_motion,
    )
    page = context.new_page()
    held_module = DeferredRoute(page, f"**/{asset}*")
    requests: list[str] = []
    page.on(
        "request",
        lambda request: requests.append(request.url) if asset in request.url else None,
    )

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="domcontentloaded")
        editor = page.locator('[data-slot="template-editor"]')
        layout = editor.get_by_role("tab", name="布局", exact=True)
        images = editor.get_by_role("tab", name="装饰", exact=True)
        image_panel = editor.get_by_role("tabpanel", name="装饰", exact=True)
        loading = image_panel.locator('[aria-busy="true"]')
        add_image = editor.get_by_role("button", name="添加图片占位符", exact=True)
        expect(editor).to_be_visible()
        held_module.wait()
        assert len(requests) == 1
        expect(layout).to_have_attribute("aria-selected", "true")
        expect(
            editor.get_by_role("combobox", name="信息布局", exact=True)
        ).to_be_visible()
        if ready_before_activation:
            held_module.release()
            page.wait_for_load_state("networkidle")
        page.evaluate(
            """() => {
              window.__imageLoadingFrames = [];
              window.__recordImageLoading = true;
              const sample = () => {
                const editor = document.querySelector('[data-slot="template-editor"]');
                const pending = editor.querySelector(
                  '[role="tabpanel"] [aria-busy="true"]',
                );
                const spinner = editor.querySelector(
                  '[role="status"][aria-label="装饰"]',
                );
                window.__imageLoadingFrames.push({
                  skeleton: Boolean(pending?.getBoundingClientRect().width),
                  spinner: Boolean(spinner?.getBoundingClientRect().width),
                });
                if (window.__recordImageLoading) requestAnimationFrame(sample);
              };
              sample();
            }"""
        )
        images.click()
        if not ready_before_activation:
            expect(loading).to_be_visible()
            expect(image_panel.locator('[data-slot="skeleton"]')).to_have_count(2)
            expect(add_image).to_have_count(0)
            page.keyboard.press("Home")
            expect(layout).to_be_focused()
            expect(layout).to_have_attribute("aria-selected", "true")
            expect(image_panel).not_to_be_visible()
            page.keyboard.press("End")
            expect(images).to_be_focused()
            expect(loading).to_be_visible()
            held_module.release()
        expect(add_image).to_be_visible()
        expect(images).to_be_focused()
        expect(loading).to_have_count(0)
        frames = page.evaluate(
            """async () => {
              await new Promise(requestAnimationFrame);
              window.__recordImageLoading = false;
              return window.__imageLoadingFrames;
            }"""
        )
        assert not any(frame["spinner"] for frame in frames), frames
        assert any(frame["skeleton"] for frame in frames) != ready_before_activation
        layout.click()
        images.click()
        expect(add_image).to_be_visible()
        expect(loading).to_have_count(0)
        assert len(requests) == 1
    finally:
        held_module.release()
        context.close()
