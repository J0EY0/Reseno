"""Concurrent edits and document preview work through the live workspace."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


@pytest.mark.parametrize("edit", ["move", "remove", "rename", "replace"])
def test_image_upload_preserves_edits_made_while_reading(
    browser: Browser, workspace_servers: tuple[str, str], edit: str
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 900}
    )
    context.add_init_script("""(() => {
      const read = FileReader.prototype.readAsDataURL;
      window.pendingImageReads = [];
      FileReader.prototype.readAsDataURL = function(file) {
        window.pendingImageReads.push(() => read.call(this, file));
      };
    })()""")
    page = context.new_page()
    try:
        presets = json.loads(
            (
                Path(__file__).resolve().parents[2]
                / "app/services/template_presets.json"
            ).read_text(encoding="utf-8")
        )
        response = page.request.post(
            f"{frontend_url}/api/templates",
            data={
                "template": {
                    "preset": "minimal",
                    "name": "Image transactions",
                    "description": "",
                    **{
                        key: presets["minimal"][key]
                        for key in ("layout", "typography", "settings")
                    },
                }
            },
        )
        assert response.ok
        template_id = response.json()["data"]["template"]["id"]
        page.goto(f"{frontend_url}/template/{template_id}", wait_until="networkidle")
        page.get_by_role("tab", name="装饰", exact=True).click()
        page.get_by_role("button", name="添加图片占位符", exact=True).click()
        card = page.get_by_role("group", name="图片元素 1", exact=True)
        expect(card).to_be_visible()
        save = page.get_by_role("button", name="保存状态", exact=True)
        expect(save).to_be_enabled()
        expect(save).to_have_attribute("title", "有未保存更改")
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT" and "/api/templates/" in response.url
            )
        ):
            save.click()
        card.locator('input[type="file"]').set_input_files(
            {
                "name": "portrait.svg",
                "mimeType": "image/svg+xml",
                "buffer": (
                    b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
                ),
            }
        )
        assert page.evaluate("window.pendingImageReads.length") == 1
        if edit == "move":
            x = card.get_by_role("spinbutton", name="横向位置", exact=True)
            x.fill("88")
            x.press("Tab")
            expect(x).to_have_value("88")
        elif edit == "remove":
            card.get_by_role("button", name="删除图片", exact=True).click()
            expect(card).to_have_count(0)
        elif edit == "rename":
            card.get_by_role("button", name="编辑图片名称", exact=True).click()
            name = card.get_by_role("textbox", name="图片名称", exact=True)
            name.fill("Keep this name")
            name.press("Enter")
        else:
            card.locator('input[type="file"]').set_input_files(
                {
                    "name": "newer.svg",
                    "mimeType": "image/svg+xml",
                    "buffer": (
                        b'<svg xmlns="http://www.w3.org/2000/svg" '
                        b'width="2" height="2"/>'
                    ),
                }
            )
            page.evaluate("window.pendingImageReads.pop()()")
            card.locator(
                '[data-slot="template-image-thumbnail"] img[alt="newer.svg"]'
            ).wait_for()
        page.evaluate("window.pendingImageReads.pop()()")
        if edit == "move":
            card.locator('[data-slot="template-image-thumbnail"] img').wait_for()
            expect(x).to_have_value("88")
        else:
            page.wait_for_timeout(100)
            if edit == "remove":
                expect(card).to_have_count(0)
            elif edit == "rename":
                expect(card.get_by_text("Keep this name", exact=True)).to_be_visible()
            else:
                expect(
                    card.locator('[data-slot="template-image-thumbnail"] img')
                ).to_have_attribute("alt", "newer.svg")
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT" and "/api/templates/" in response.url
            )
        ):
            page.keyboard.press("ControlOrMeta+s")
        page.reload(wait_until="networkidle")
        page.get_by_role("tab", name="装饰", exact=True).click()
        if edit == "move":
            card.get_by_role("button", name="展开图片设置", exact=True).click()
            expect(
                card.get_by_role("spinbutton", name="横向位置", exact=True)
            ).to_have_value("88")
        elif edit == "remove":
            expect(card).to_have_count(0)
        elif edit == "rename":
            expect(card.get_by_text("Keep this name", exact=True)).to_be_visible()
        else:
            expect(
                card.locator('[data-slot="template-image-thumbnail"] img')
            ).to_have_attribute("alt", "newer.svg")
    finally:
        context.close()


@pytest.mark.parametrize("operation", ["edit", "save"])
def test_smart_fit_keeps_trial_styles_out_of_saved_edits(
    browser: Browser, workspace_servers: tuple[str, str], operation: str
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 900}
    )
    page = context.new_page()
    try:
        baseline = _create_experience_resume(page, frontend_url, 30)
        resume_id = baseline["id"]
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        fit = page.get_by_role("button", name="智能一页", exact=True)
        expect(fit).to_be_enabled()
        preview = page.locator(
            '.resume-workspace [data-export-root="resume-page"]'
        ).first
        initial_padding = preview.evaluate("element => element.style.paddingTop")
        page.evaluate("""() => {
          const original = requestAnimationFrame;
          window.requestAnimationFrame = callback =>
            original(time => setTimeout(() => callback(time), 100));
        }""")
        fit.click()
        page.wait_for_function(
            """initial =>
          document.querySelector('.resume-workspace [data-export-root="resume-page"]')
            .style.paddingTop !== initial
        """,
            arg=initial_padding,
        )
        if operation == "edit":
            page.get_by_role("button", name="格式", exact=True).click()
            font_size = page.get_by_role("combobox", name="字号", exact=True)
            font_size.click()
            page.get_by_role("option", name="15 pt", exact=True).click()
            expect(font_size).to_have_text("15 pt")
            expect(fit).to_be_enabled(timeout=15000)
            expect(font_size).to_have_text("15 pt")
            page.keyboard.press("Escape")
        page.keyboard.press("ControlOrMeta+s")
        page.wait_for_timeout(300)
        persisted = page.request.get(f"{frontend_url}/api/resumes/{resume_id}").json()[
            "data"
        ]["resume"]
        if operation == "edit":
            assert persisted["typography"]["fontSize"] == 20
        else:
            assert persisted["typography"] == baseline["typography"]
            assert persisted["templateSettings"] == baseline["templateSettings"]
    finally:
        context.close()


def _create_experience_resume(page: Page, frontend_url: str, item_count: int):
    response = page.request.post(
        f"{frontend_url}/api/resumes",
        data={"documentLocale": "zh", "title": "Smart fit transaction"},
    )
    assert response.ok
    created = response.json()["data"]["resume"]
    resume_id = created["id"]
    payload = {
        key: created[key]
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
    payload["resume"]["sections"] = [
        {
            "id": "experience",
            "kind": "experience",
            "title": "Experience",
            "items": [
                {
                    "id": f"experience-{index}",
                    "company": f"Company {index}",
                    "position": "Engineer",
                    "location": "",
                    "period": "2024 - 2025",
                    "description": "",
                    "highlights": [
                        "<p>React TypeScript and browser development</p>",
                        "<p>Debugging complex document rendering</p>",
                        "<p>Application performance evaluation</p>",
                    ],
                }
                for index in range(item_count)
            ],
        }
    ]
    saved = page.request.put(f"{frontend_url}/api/resumes/{resume_id}", data=payload)
    assert saved.ok
    baseline = saved.json()["data"]["resume"]
    return baseline


def test_unchanged_preview_content_is_reused_while_typing(
    browser: Browser, workspace_servers: tuple[str, str]
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 900}
    )
    context.add_init_script("""(() => {
      window.previewWork = {parses: 0, scans: 0};
      const parse = DOMParser.prototype.parseFromString;
      DOMParser.prototype.parseFromString = function(html, type) {
        if (String(html).includes('React TypeScript')) window.previewWork.parses++;
        return parse.call(this, html, type);
      };
      const rect = Element.prototype.getBoundingClientRect;
      Element.prototype.getBoundingClientRect = function() {
        if (this.classList.contains('resume-page-content-flow--measure')) {
          window.previewWork.scans++;
        }
        return rect.call(this);
      };
    })()""")
    page = context.new_page()
    try:
        baseline = _create_experience_resume(page, frontend_url, 15)
        page.goto(f"{frontend_url}/resume/{baseline['id']}", wait_until="networkidle")
        page.get_by_role("button", name="基本信息: 展开或收起模块", exact=True).click()
        name = page.get_by_role("textbox", name="姓名", exact=True)
        name.fill("Preview Person")
        page.wait_for_timeout(300)
        page.wait_for_function("""() => document.querySelector(
          '.resume-workspace .resume-page-stack'
        )?.dataset.resumePaginationReady === 'true'""")
        page.evaluate("window.previewWork = {parses: 0, scans: 0}")
        name.fill("Preview Person 2")
        page.locator(".resume-workspace .resume-page h1").first.get_by_text(
            "Preview Person 2", exact=True
        ).wait_for()
        page.wait_for_timeout(300)
        work = page.evaluate("window.previewWork")
        assert work["parses"] == 0, work
        assert 1 <= work["scans"] <= 4, work
    finally:
        context.close()


@pytest.mark.parametrize("item_count", [9, 30])
def test_smart_fit_completion_and_undo_preserve_the_document(
    browser: Browser, workspace_servers: tuple[str, str], item_count: int
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1100, "height": 900},
        reduced_motion="reduce",
    )
    page = context.new_page()
    try:
        baseline = _create_experience_resume(page, frontend_url, item_count)
        page.goto(f"{frontend_url}/resume/{baseline['id']}", wait_until="networkidle")
        page.get_by_role("button", name="操作", exact=True).click()
        fit = page.get_by_role("menuitem", name="智能一页", exact=True)
        expect(fit).to_be_enabled()
        stack = page.locator(".resume-workspace .resume-page-stack")
        initial_pages = stack.get_attribute("data-resume-page-count")
        assert int(initial_pages) > 1
        fit.click()
        if item_count == 9:
            page.get_by_text("已压缩到一页", exact=True).wait_for()
            expect(stack).to_have_attribute("data-resume-page-count", "1")
            page.get_by_role("button", name="撤销", exact=True).click()
        else:
            page.get_by_text("未能排到一页，已保留原排版", exact=True).wait_for()
        expect(stack).to_have_attribute("data-resume-page-count", initial_pages)
        page.keyboard.press("ControlOrMeta+s")
        page.wait_for_timeout(200)
        persisted = page.request.get(
            f"{frontend_url}/api/resumes/{baseline['id']}"
        ).json()["data"]["resume"]
        for field in ("resume", "typography", "templateSettings"):
            assert persisted[field] == baseline[field]
    finally:
        context.close()
