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
        page.wait_for_function("window.pendingImageReads.length === 1")
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
            page.wait_for_function("window.pendingImageReads.length === 2")
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
        canvas = page.locator('[data-slot="document-canvas-viewport"]').element_handle()
        assert canvas is not None
        page.evaluate("window.previewWork = {parses: 0, scans: 0}")
        name.fill("Preview Person 2")
        page.locator(".resume-workspace .resume-page h1").first.get_by_text(
            "Preview Person 2", exact=True
        ).wait_for()
        page.wait_for_timeout(300)
        work = page.evaluate("window.previewWork")
        assert work["parses"] == 0, work
        assert 1 <= work["scans"] <= 4, work
        assert canvas.evaluate("""element => element.isConnected && element ===
          document.querySelector('[data-slot="document-canvas-viewport"]')
        """)
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


def _create_template_for_preview_checks(
    page: Page, frontend_url: str, name: str, settings: dict | None = None
) -> dict:
    preset = json.loads(
        (
            Path(__file__).resolve().parents[2] / "app/services/template_presets.json"
        ).read_text(encoding="utf-8")
    )["minimal"]
    response = page.request.post(
        f"{frontend_url}/api/templates",
        data={
            "template": {
                "preset": "minimal",
                "name": name,
                "description": "",
                "layout": preset["layout"],
                "typography": preset["typography"],
                "settings": {**preset["settings"], **(settings or {})},
            }
        },
    )
    assert response.ok, response.text()
    return response.json()["data"]["template"]


@pytest.mark.parametrize(
    ("mime_type", "dense"),
    [("image/png", False), ("image/jpeg", False), ("image/png", True)],
    ids=["transparent-png", "jpeg", "dense-png"],
)
def test_template_image_resampling_keeps_print_size_and_transparency(
    browser: Browser, workspace_servers: tuple[str, str], mime_type: str, dense: bool
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(browser, locale="en-US")
    page = context.new_page()
    try:
        page.goto(frontend_url, wait_until="networkidle")
        result = page.evaluate(
            """async ({mimeType, dense}) => {
              const {prepareTemplateImage} =
                await import('/src/lib/template-image-upload.ts');
              const source = document.createElement('canvas');
              source.width = dense ? 1500 : 3600;
              source.height = dense ? 1500 : 2400;
              const drawing = source.getContext('2d');
              const gradient = drawing.createLinearGradient(0, 0, 3600, 2400);
              gradient.addColorStop(0, 'rgba(255, 0, 0, 0.5)');
              gradient.addColorStop(1, 'rgba(0, 0, 255, 0.5)');
              drawing.fillStyle = gradient;
              drawing.fillRect(900, 0, 2700, 2400);
              if (dense) {
                const pixels = drawing.createImageData(1500, 1500);
                let seed = 7;
                for (let index = 0; index < pixels.data.length; index += 4) {
                  seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
                  pixels.data[index] = seed & 255;
                  pixels.data[index + 1] = (seed >>> 8) & 255;
                  pixels.data[index + 2] = (seed >>> 16) & 255;
                  pixels.data[index + 3] = 128;
                }
                drawing.putImageData(pixels, 0, 0);
              }
              const blob = await new Promise(resolve =>
                source.toBlob(resolve, mimeType, 1));
              const file = new File([blob], 'decoration', {type: mimeType});
              const src = await prepareTemplateImage(file);
              const image = new Image();
              image.src = src;
              await image.decode();
              const sample = document.createElement('canvas');
              sample.width = image.naturalWidth;
              sample.height = image.naturalHeight;
              const pixels = sample.getContext('2d');
              pixels.drawImage(image, 0, 0);
              return {
                inputBytes: file.size,
                outputBytes: (await (await fetch(src)).blob()).size,
                width: image.naturalWidth,
                height: image.naturalHeight,
                mimeType: src.slice(5, src.indexOf(';')),
                emptyAlpha: pixels.getImageData(2, 2, 1, 1).data[3],
                filledAlpha: pixels.getImageData(sample.width - 2, 2, 1, 1).data[3],
              };
            }""",
            {"mimeType": mime_type, "dense": dense},
        )
        if dense:
            assert result["inputBytes"] > 1024 * 1024
            assert 1 < result["width"] < 1418
            assert result["height"] == result["width"]
        else:
            assert result["width"] == 1418
            assert result["height"] == 945
        assert result["outputBytes"] < result["inputBytes"]
        assert result["outputBytes"] <= 1024 * 1024
        assert result["mimeType"] == mime_type
        if mime_type == "image/png":
            assert result["emptyAlpha"] == (128 if dense else 0)
            assert result["filledAlpha"] == pytest.approx(128, abs=1)
    finally:
        context.close()


def test_template_image_validation_keeps_small_vector_and_animated_files(
    browser: Browser, workspace_servers: tuple[str, str]
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(browser, locale="en-US")
    page = context.new_page()
    try:
        page.goto(frontend_url, wait_until="networkidle")
        result = page.evaluate(
            """async () => {
              const {prepareTemplateImage} =
                await import('/src/lib/template-image-upload.ts');
              const encode = bytes => new File([bytes], 'image', {type: 'image/png'});
              const svg = new File([
                '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10">',
                '<rect width="10" height="10" fill="red"/></svg>',
              ], 'small.svg', {type: 'image/svg+xml'});
              const gifBytes = Uint8Array.from(
                atob('R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=='),
                char => char.charCodeAt(0));
              const gif = new File([gifBytes], 'small.gif', {type: 'image/gif'});
              const originals = [];
              for (const file of [svg, gif]) {
                const result = await prepareTemplateImage(file);
                originals.push(
                  await (await fetch(result)).text() === await file.text());
              }
              const dimensions = new Uint8Array(24);
              dimensions.set([137, 80, 78, 71, 13, 10, 26, 10]);
              const header = new DataView(dimensions.buffer);
              header.setUint32(16, 100000);
              header.setUint32(20, 100000);
              const outcomes = [];
              for (const file of [
                new File(['hello'], 'plain.txt', {type: 'text/plain'}),
                new File([new Uint8Array(10 * 1024 * 1024 + 1)],
                  'large.png', {type: 'image/png'}),
                encode(dimensions),
                encode('not an image'),
                new File([await svg.text(), ' '.repeat(1024 * 1024)],
                  'large.svg', {type: 'image/svg+xml'}),
              ]) {
                try { await prepareTemplateImage(file); outcomes.push('accepted'); }
                catch (error) { outcomes.push(error.message); }
              }
              return {originals, outcomes};
            }"""
        )
        assert result["originals"] == [True, True]
        assert result["outcomes"] == [
            "templateImageInvalidFile",
            "templateImageTooLarge",
            "templateImageTooManyPixels",
            "templateImageInvalidFile",
            "templateImageOriginalTooLarge",
        ]
        template = _create_template_for_preview_checks(
            page, frontend_url, "Image errors"
        )
        page.goto(f"{frontend_url}/template/{template['id']}", wait_until="networkidle")
        page.get_by_role("tab", name="Decoration", exact=True).click()
        page.get_by_role("button", name="Add Image Placeholder", exact=True).click()
        card = page.get_by_role("group", name="Image Elements 1", exact=True)
        file_input = card.locator('input[type="file"]')
        file_input.set_input_files(
            {
                "name": "kept.svg",
                "mimeType": "image/svg+xml",
                "buffer": (
                    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
                ),
            }
        )
        thumbnail = card.locator('[data-slot="template-image-thumbnail"] img')
        expect(thumbnail).to_be_visible()
        original = thumbnail.get_attribute("src")
        file_input.set_input_files(
            {
                "name": "broken.png",
                "mimeType": "image/png",
                "buffer": b"not an image",
            }
        )
        expect(
            page.get_by_text(
                "Choose a valid image that your browser can open.", exact=True
            )
        ).to_be_visible()
        expect(thumbnail).to_have_attribute("src", original)
        expect(thumbnail).to_have_attribute("alt", "kept.svg")
    finally:
        context.close()


def test_template_margin_custom_values_change_only_when_a_preset_is_selected(
    browser: Browser, workspace_servers: tuple[str, str]
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(browser, locale="en-US")
    page = context.new_page()
    try:
        template = _create_template_for_preview_checks(
            page,
            frontend_url,
            "Custom margins",
            {"pagePaddingTop": 16, "pagePaddingX": 10, "pagePaddingBottom": 10},
        )
        page.goto(f"{frontend_url}/template/{template['id']}", wait_until="networkidle")
        page.get_by_role("tab", name="Layout", exact=True).click()
        canvas = page.locator('[data-slot="document-canvas-viewport"]').element_handle()
        assert canvas is not None
        margin = page.get_by_role("combobox", name="Page Margin", exact=True)
        expect(margin).to_have_text("Custom")
        margin.click()
        expect(page.get_by_role("option", name="Custom", exact=True)).to_be_disabled()
        page.keyboard.press("Escape")
        unchanged = next(
            item
            for item in page.request.get(f"{frontend_url}/api/templates").json()[
                "data"
            ]["templates"]
            if item["id"] == template["id"]
        )
        assert [
            unchanged["settings"][key]
            for key in ("pagePaddingTop", "pagePaddingX", "pagePaddingBottom")
        ] == [16, 10, 10]
        margin.click()
        page.get_by_role("option", name="Standard", exact=True).click()
        expect(margin).to_have_text("Standard")
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT" and "/api/templates/" in response.url
            )
        ):
            page.keyboard.press("ControlOrMeta+s")
        stored = next(
            item
            for item in page.request.get(f"{frontend_url}/api/templates").json()[
                "data"
            ]["templates"]
            if item["id"] == template["id"]
        )
        assert [
            stored["settings"][key]
            for key in ("pagePaddingTop", "pagePaddingX", "pagePaddingBottom")
        ] == [14, 12, 12]
        assert canvas.evaluate("""element => element.isConnected && element ===
          document.querySelector('[data-slot="document-canvas-viewport"]')
        """)
    finally:
        context.close()


def test_template_gallery_mounts_only_its_page_when_switching_preview_language(
    browser: Browser, workspace_servers: tuple[str, str]
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser, locale="en-US", viewport={"width": 1440, "height": 900}
    )
    page = context.new_page()
    template_ids = []
    try:
        for index in range(30):
            template = _create_template_for_preview_checks(
                page, frontend_url, f"Paged template {index}"
            )
            template_ids.append(template["id"])
        page.goto(f"{frontend_url}/templates", wait_until="networkidle")
        grid = page.locator('[data-slot="gallery-grid"]')
        columns = grid.evaluate(
            "element => getComputedStyle(element).gridTemplateColumns.split(' ').length"
        )
        cards = grid.locator(":scope > [data-gallery-item-id]")
        previews = grid.locator('[data-export-root="resume-page"]')
        expect(cards).to_have_count(columns * 2)
        expect(previews).to_have_count(columns * 2)
        assert cards.count() < 30
        first_ids = cards.evaluate_all(
            "items => items.map(item => item.dataset.galleryItemId)"
        )
        before = previews.first.inner_text()
        page.get_by_role("combobox", name="Resume language", exact=True).click()
        page.get_by_role("option", name="Chinese template", exact=True).click()
        expect(previews.first).not_to_have_text(before)
        expect(previews).to_have_count(columns * 2)
        assert (
            cards.evaluate_all("items => items.map(item => item.dataset.galleryItemId)")
            == first_ids
        )
        page.get_by_role("link", name="Next", exact=True).click()
        page.wait_for_url("**/templates?**page=2**")
        expect(cards.first).not_to_have_attribute("data-gallery-item-id", first_ids[0])
        second_ids = cards.evaluate_all(
            "items => items.map(item => item.dataset.galleryItemId)"
        )
        assert not set(first_ids).intersection(second_ids)
        expect(previews).to_have_count(columns * 2)
    finally:
        for template_id in template_ids:
            page.request.post(f"{frontend_url}/api/templates/{template_id}/trash")
            page.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()
