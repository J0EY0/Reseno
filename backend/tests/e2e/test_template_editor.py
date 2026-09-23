from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Locator, Route, expect

from tests.e2e.browser_support import DeferredRoute
from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def _assert_template_actions_align_with_heading(
    editor: Locator, *, stacked: bool = False
) -> None:
    header = editor.locator('[data-slot="template-editor-header"]')
    header_box = header.bounding_box()
    heading_box = header.get_by_role("heading", level=2).bounding_box()
    actions_box = header.locator('[data-slot="template-editor-actions"]').bounding_box()
    assert header_box is not None
    assert heading_box is not None
    assert actions_box is not None
    if stacked:
        assert actions_box["y"] >= heading_box["y"] + heading_box["height"]
        assert actions_box["x"] == pytest.approx(heading_box["x"], abs=1)
    else:
        assert actions_box["y"] + actions_box["height"] / 2 == pytest.approx(
            heading_box["y"] + heading_box["height"] / 2, abs=1
        )
        assert actions_box["x"] >= heading_box["x"] + heading_box["width"]
    assert actions_box["x"] >= header_box["x"]
    assert (
        actions_box["x"] + actions_box["width"]
        <= header_box["x"] + header_box["width"] + 1
    )
    assert (
        actions_box["y"] + actions_box["height"]
        <= header_box["y"] + header_box["height"] + 1
    )


@pytest.mark.browser_smoke
@pytest.mark.parametrize("field", ["nameScale", "bodyLineHeight", "headingColor"])
def test_template_shortcut_saves_focused_style_input(
    browser: Browser,
    workspace_servers: tuple[str, str],
    field: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 900}
    )
    page = context.new_page()
    template_id: str | None = None
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role("button", name="创建副本", exact=True).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = page.url.rsplit("/", maxsplit=1)[-1]
        path = f"/api/templates/{template_id}"
        baseline = page.request.get(f"{frontend_url}{path}").json()["data"]["template"]
        header = page.locator('[data-slot="template-workspace-header"]')
        expect(header.locator('[data-slot="template-editor-title"]')).to_have_text(
            baseline["name"]
        )
        expect(
            header.get_by_role("button", name="修改模板信息", exact=True)
        ).to_be_visible()
        if field == "nameScale":
            tab = "字体"
            control = page.get_by_role("spinbutton", name="姓名字号", exact=True)
            expected = 2.6
            draft = str(round(baseline["typography"]["fontSize"] * 0.75 * expected, 2))
        elif field == "bodyLineHeight":
            tab = "布局"
            control = page.get_by_role("spinbutton", name="行距", exact=True)
            assert baseline["typography"]["fontSize"] == 16
            expected = 1.6
            draft = "19.2"
        else:
            tab = "配色"
            control = page.get_by_role("textbox", name="标题颜色 HEX", exact=True)
            expected = "#abcdef"
            draft = "#ABCDEF"
        page.get_by_role("tab", name=tab, exact=True).click()
        if field == "bodyLineHeight":
            expect(control).to_have_value("20.4")
            expect(
                page.get_by_role("slider", name="行距", exact=True)
            ).to_have_attribute("aria-valuetext", "20.4 pt")
        control.fill(draft)
        expect(control).to_be_focused()
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == path
                and response.request.post_data_json["saveMode"] == "checkpoint"
            )
        ) as saved:
            page.keyboard.press("ControlOrMeta+s")
        assert saved.value.ok
        assert saved.value.request.post_data_json["template"]["settings"][field] == (
            expected
        )
        assert saved.value.json()["data"]["checkpoint"] is None
        expect(control).to_be_focused()
        persisted = page.request.get(f"{frontend_url}{path}").json()["data"]
        assert persisted["template"]["settings"][field] == expected
        page.reload(wait_until="networkidle")
        page.get_by_role("tab", name=tab, exact=True).click()
        expect(control).to_have_value(draft)
        if field == "bodyLineHeight":
            expect(
                page.get_by_role("slider", name="行距", exact=True)
            ).to_have_attribute("aria-valuetext", "19.2 pt")
        assert errors == []
    finally:
        if template_id:
            response = page.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if response.ok:
                page.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
def test_template_custom_avatar_size_updates_preview_and_survives_reload(
    browser: Browser,
    workspace_servers: tuple[str, str],
    reduced_motion: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 960},
        reduced_motion=reduced_motion,
    )
    page = context.new_page()
    template_id: str | None = None
    size = page.get_by_role("combobox", name="头像尺寸", exact=True)
    width = page.get_by_role("spinbutton", name="头像宽度", exact=True)
    height = page.get_by_role("spinbutton", name="头像高度", exact=True)
    preview = page.locator('[data-export-root="resume-page"]:visible').last
    avatar = preview.locator('[data-avatar-frame="true"]')

    def record_size_panel() -> None:
        size.evaluate(
            """trigger => {
              const record = { active: true, frames: [] };
              window.__avatarSizeRecording = record;
              const sample = () => {
                if (!record.active || window.__avatarSizeRecording !== record) return;
                const input = document.querySelector('input[aria-label="头像宽度"]');
                const panel = input?.closest('[data-slot="collapsible-content"]');
                record.frames.push({
                  time: performance.now(),
                  custom: trigger.textContent.trim() === '自定义',
                  height: panel?.getBoundingClientRect().height ?? 0,
                  contentHeight: panel?.firstElementChild
                    ?.getBoundingClientRect().height ?? 0,
                  moving: panel?.getAnimations().some(
                    animation => animation.playState === 'running',
                  ) ?? false,
                });
                requestAnimationFrame(sample);
              };
              sample();
            }"""
        )

    def assert_size_panel_animation(*, custom: bool) -> None:
        page.wait_for_function(
            """custom => {
              const frame = window.__avatarSizeRecording.frames.at(-1);
              return frame?.custom === custom && !frame.moving && (custom
                ? frame.height > 0 && Math.abs(frame.height - frame.contentHeight) < 1
                : frame.height === 0);
            }""",
            arg=custom,
        )
        frames = page.evaluate(
            """() => {
              const record = window.__avatarSizeRecording;
              record.active = false;
              return record.frames;
            }"""
        )
        intermediate = [
            frame
            for frame in frames
            if frame["custom"] == custom
            and 0 < frame["height"] < frame["contentHeight"]
        ]
        if reduced_motion == "reduce":
            assert not any(frame["moving"] for frame in frames), frames
            assert intermediate == [], frames
        else:
            assert any(frame["moving"] for frame in intermediate), frames

    def assert_preview_dimensions(
        expected_width: float, expected_height: float
    ) -> None:
        expect(avatar).to_be_visible()
        page.wait_for_function(
            """({ avatar, width, height }) => {
              const paper = avatar.closest('[data-export-root="resume-page"]');
              const pxPerMm = paper.getBoundingClientRect().width / 210;
              const rect = avatar.getBoundingClientRect();
              return Math.abs(rect.width / pxPerMm - width) < 0.15 &&
                Math.abs(rect.height / pxPerMm - height) < 0.15;
            }""",
            arg={
                "avatar": avatar.element_handle(),
                "width": expected_width,
                "height": expected_height,
            },
        )

    def save_dimensions(expected_width: float, expected_height: float) -> None:
        path = f"/api/templates/{template_id}"
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == path
                and response.request.post_data_json["saveMode"] == "checkpoint"
            )
        ) as saved:
            page.keyboard.press("ControlOrMeta+s")
        assert saved.value.ok
        saved_layout = saved.value.request.post_data_json["template"]["layout"]
        persisted = page.request.get(f"{frontend_url}{path}")
        assert persisted.ok
        persisted_layout = persisted.json()["data"]["template"]["layout"]
        for key, value in (
            ("avatarWidth", expected_width),
            ("avatarHeight", expected_height),
        ):
            assert saved_layout[key] == value
            assert persisted_layout[key] == value

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role("tab", name="布局", exact=True).click()
        expect(size).to_be_disabled()
        expect(width).to_have_count(0)
        expect(height).to_have_count(0)
        assert_preview_dimensions(25, 32)

        page.get_by_role("button", name="创建副本", exact=True).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = urlparse(page.url).path.rsplit("/", maxsplit=1)[-1]
        expect(size).to_be_enabled()
        record_size_panel()
        size.click()
        custom = page.get_by_role("option", name="自定义", exact=True)
        expect(custom).to_be_enabled()
        custom.click()
        expect(size).to_have_text("自定义")
        expect(width).to_have_value("25")
        expect(height).to_have_value("32")
        assert_size_panel_animation(custom=True)
        assert_preview_dimensions(25, 32)

        width.fill("29.5")
        width.press("Enter")
        assert_preview_dimensions(29.5, 32)
        height.fill("37.5")
        expect(height).to_be_focused()
        save_dimensions(29.5, 37.5)
        expect(height).to_be_focused()
        assert_preview_dimensions(29.5, 37.5)

        page.reload(wait_until="networkidle")
        page.get_by_role("tab", name="布局", exact=True).click()
        expect(size).to_have_text("自定义")
        expect(width).to_have_value("29.5")
        expect(height).to_have_value("37.5")
        assert_preview_dimensions(29.5, 37.5)

        record_size_panel()
        size.click()
        page.get_by_role("option", name="标准", exact=True).click()
        expect(size).to_have_text("标准")
        assert_size_panel_animation(custom=False)
        expect(width).to_have_count(0)
        expect(height).to_have_count(0)
        assert_preview_dimensions(25, 32)
        save_dimensions(25, 32)

        page.reload(wait_until="networkidle")
        page.get_by_role("tab", name="布局", exact=True).click()
        expect(size).to_have_text("标准")
        expect(width).to_have_count(0)
        expect(height).to_have_count(0)
        assert_preview_dimensions(25, 32)
    finally:
        if template_id:
            response = context.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if response.ok:
                context.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


def test_template_autosave_preserves_edit_made_during_active_save(
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

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="创建副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = page.url.rsplit("/", maxsplit=1)[-1]
        save_payloads: list[dict[str, object]] = []

        def delay_first_save(route: Route) -> None:
            request = route.request
            if request.method != "PUT":
                route.continue_()
                return

            payload = request.post_data_json
            assert isinstance(payload, dict)
            save_payloads.append(payload)
            if len(save_payloads) == 1:
                time.sleep(1)
            route.continue_()

        page.route(f"**/api/templates/{template_id}", delay_first_save)
        page.get_by_role(
            "button",
            name="修改模板信息",
            exact=True,
        ).click()
        page.get_by_label("模板名称", exact=True).fill("First Template Save")
        page.get_by_role("button", name="保存", exact=True).click()
        page.wait_for_timeout(50)
        page.evaluate(
            """
            () => {
              window.setTimeout(() => {
                const trigger = document.querySelector(
                  '[data-template-metadata-trigger="true"]',
                );
                if (!(trigger instanceof HTMLButtonElement)) {
                  throw new Error("Template metadata trigger is unavailable.");
                }
                trigger.click();
                requestAnimationFrame(() => {
                  const input = document.querySelector(
                    'input[name="templateName"]',
                  );
                  const valueSetter = Object.getOwnPropertyDescriptor(
                    HTMLInputElement.prototype,
                    "value",
                  )?.set;
                  if (!(input instanceof HTMLInputElement) || !valueSetter) {
                    throw new Error("Template name input is unavailable.");
                  }
                  valueSetter.call(input, "Latest Template During Save");
                  input.dispatchEvent(new Event("input", { bubbles: true }));
                  input.closest("form")?.requestSubmit();
                });
              }, 200);
            }
            """
        )
        page.keyboard.press("Control+S")

        deadline = time.monotonic() + 8
        while len(save_payloads) < 2 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert len(save_payloads) >= 2, save_payloads
        assert save_payloads[-1]["template"]["name"] == ("Latest Template During Save")
    finally:
        context.close()


def test_template_return_checks_unsaved_changes_before_navigation(
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

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="创建副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        page.get_by_role(
            "button",
            name="修改模板信息",
            exact=True,
        ).click()
        page.get_by_label("模板名称", exact=True).fill("Template Saved Before Return")
        page.get_by_role("button", name="保存", exact=True).click()
        page.get_by_role(
            "button",
            name="返回模板列表",
            exact=True,
        ).click()

        assert page.url.startswith(f"{frontend_url}/template/template-")
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
            name="保存并离开",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/templates")
    finally:
        context.close()


@pytest.mark.browser_smoke
def test_template_leave_dialog_enter_activates_only_focused_action(
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
    template_id: str | None = None
    template_url: str | None = None
    save_payloads: list[dict[str, object]] = []

    def capture_save(route: Route) -> None:
        if route.request.method == "PUT":
            payload = route.request.post_data_json
            assert isinstance(payload, dict)
            save_payloads.append(payload)
        route.continue_()

    def update_template_name(name: str) -> None:
        page.get_by_role(
            "button",
            name="修改模板信息",
            exact=True,
        ).click()
        page.get_by_label("模板名称", exact=True).fill(name)
        page.get_by_role("button", name="保存", exact=True).click()

    def open_leave_dialog() -> None:
        page.get_by_role(
            "button",
            name="返回模板列表",
            exact=True,
        ).click()
        page.get_by_role(
            "heading",
            name="有未保存的更改",
            exact=True,
        ).wait_for(state="visible")

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="创建副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_url = page.url
        template_id = urlparse(template_url).path.rsplit("/", maxsplit=1)[-1]
        page.route(f"**/api/templates/{template_id}", capture_save)

        update_template_name("Continue template editing via Enter")
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
        assert page.url == template_url
        assert page.locator('[data-slot="template-editor-title"]').inner_text() == (
            "Continue template editing via Enter"
        )

        open_leave_dialog()
        save_payloads.clear()
        discard = page.get_by_role(
            "button",
            name="放弃更改",
            exact=True,
        )
        discard.focus()
        page.keyboard.press("Enter")
        page.wait_for_url(f"{frontend_url}/templates")

        discarded_name = "Continue template editing via Enter"
        assert all(
            payload["template"]["name"] != discarded_name for payload in save_payloads
        )

        page.goto(template_url, wait_until="networkidle")
        saved_name = "Save template and leave via Enter"
        update_template_name(saved_name)
        open_leave_dialog()

        save_payloads.clear()
        save_and_leave = page.get_by_role(
            "button",
            name="保存并离开",
            exact=True,
        )
        save_and_leave.focus()
        page.keyboard.press("Enter")
        page.wait_for_url(f"{frontend_url}/templates")

        assert any(
            payload["template"]["name"] == saved_name for payload in save_payloads
        )
    finally:
        if template_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize("locale", ["zh", "en"])
@pytest.mark.parametrize("width", [1672, 1440, 1280, 360])
def test_template_workspace_places_actions_and_preview_language_in_context(
    browser: Browser,
    workspace_servers: tuple[str, str],
    locale: str,
    width: int,
) -> None:
    frontend_url, _ = workspace_servers
    messages = json.loads(
        (
            Path(__file__).parents[3] / "frontend/src/i18n/locales" / f"{locale}.json"
        ).read_text(encoding="utf-8")
    )
    context = _authenticated_context(
        browser,
        locale="zh-CN" if locale == "zh" else "en-US",
        viewport={"width": width, "height": 870},
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/template/modern", wait_until="networkidle")

        header = page.locator('[data-slot="template-workspace-header"]')
        editor = page.locator('[data-slot="template-editor"]')
        editor_header = editor.locator('[data-slot="template-editor-header"]')
        actions = editor_header.locator('[data-slot="template-editor-actions"]')
        preview = page.locator(".template-workspace .resume-preview-card")
        toolbar = preview.locator('[data-slot="template-preview-toolbar"]')
        language = toolbar.get_by_role(
            "combobox", name=messages["resumeLanguage"], exact=True
        )
        expect(language).to_have_text(
            messages["chinesePreview" if locale == "zh" else "englishPreview"]
        )
        expect(header.locator('[data-slot="template-editor-actions"]')).to_have_count(0)
        readonly_status = (
            "内置模板 · 只读" if locale == "zh" else "Built-in · Read-only"
        )
        readonly_badge = header.get_by_text(
            "只读" if locale == "zh" else "Read-only", exact=True
        )
        expect(readonly_badge).to_be_visible()
        expect(readonly_badge).to_have_attribute("title", readonly_status)
        expect(editor.get_by_title(readonly_status, exact=True)).to_have_count(0)
        expect(
            editor.get_by_role("combobox", name=messages["resumeLanguage"], exact=True)
        ).to_have_count(0)
        expect(
            header.get_by_role("combobox", name=messages["resumeLanguage"], exact=True)
        ).to_have_count(0)

        action_controls = (
            actions.get_by_role(
                "button",
                name="创建副本" if locale == "zh" else "Create Copy",
                exact=True,
            ),
            actions.get_by_role(
                "button", name=messages["setDefaultTemplate"], exact=True
            ),
        )
        action_boxes = []
        for control in action_controls:
            expect(control).to_have_css("font-size", "12px")
            box = control.bounding_box()
            assert box is not None
            assert box["height"] == pytest.approx(32, abs=1)
            icon = control.locator("svg")
            expect(icon).to_have_count(1)
            icon_box = icon.bounding_box()
            assert icon_box is not None
            assert icon_box["width"] == pytest.approx(16, abs=1)
            assert icon_box["height"] == pytest.approx(16, abs=1)
            action_boxes.append(box)
        assert all(box is not None for box in action_boxes)
        action_rows = {round(float(box["y"])) for box in action_boxes if box}
        assert len(action_rows) == 1, action_boxes
        _assert_template_actions_align_with_heading(
            editor, stacked=locale == "en" and width == 360
        )
        title_box = header.locator('[data-slot="template-editor-title"]').bounding_box()
        header_box = header.bounding_box()
        badge_box = readonly_badge.bounding_box()
        assert title_box is not None
        assert header_box is not None
        assert badge_box is not None
        assert badge_box["y"] + badge_box["height"] / 2 == pytest.approx(
            title_box["y"] + title_box["height"] / 2, abs=1
        )
        assert badge_box["x"] > title_box["x"] + title_box["width"]
        assert (
            badge_box["x"] + badge_box["width"] <= header_box["x"] + header_box["width"]
        )
        assert badge_box["y"] >= header_box["y"]
        assert (
            badge_box["y"] + badge_box["height"]
            <= header_box["y"] + header_box["height"]
        )

        tablist = editor.get_by_role(
            "tablist", name=messages["resumeTemplates"], exact=True
        )
        tab_labels = [
            messages[key]
            for key in (
                "templateLayoutTab",
                "templateTypographyTab",
                "templateVisualTab",
                "templateImagesTab",
            )
        ]
        expect(tablist.get_by_role("tab")).to_have_count(4)
        for label in tab_labels:
            tab = tablist.get_by_role("tab", name=label, exact=True)
            expect(tab).to_be_visible()
            geometry = tab.evaluate(
                """tab => {
                  const list = tab.closest('[role="tablist"]');
                  const listBounds = list.getBoundingClientRect();
                  const tabBounds = tab.getBoundingClientRect();
                  const walker = document.createTreeWalker(tab, NodeFilter.SHOW_TEXT);
                  const nodes = [];
                  while (walker.nextNode()) {
                    const node = walker.currentNode;
                    if (node.textContent.trim() && !node.parentElement.closest('svg')) {
                      nodes.push(node);
                    }
                  }
                  if (nodes.length !== 1) throw new Error('Expected one tab label.');
                  const range = document.createRange();
                  range.selectNodeContents(nodes[0]);
                  const textBounds = range.getBoundingClientRect();
                  const ancestors = [];
                  for (
                    let element = nodes[0].parentElement;
                    element;
                    element = element.parentElement
                  ) {
                    const rect = element.getBoundingClientRect();
                    const style = getComputedStyle(element);
                    ancestors.push({
                      ellipsis: style.textOverflow === 'ellipsis',
                      clipped: ['hidden', 'clip'].includes(style.overflowX)
                        && (textBounds.left < rect.left
                          || textBounds.right > rect.right),
                    });
                    if (element === tab) break;
                  }
                  return {
                    text: nodes[0].textContent,
                    lines: [...range.getClientRects()]
                      .filter(rect => rect.width > 0).length,
                    textLeft: textBounds.left,
                    textRight: textBounds.right,
                    tabLeft: tabBounds.left,
                    tabRight: tabBounds.right,
                    listLeft: listBounds.left,
                    listRight: listBounds.right,
                    scrollWidth: list.scrollWidth,
                    clientWidth: list.clientWidth,
                    ancestors,
                  };
                }"""
            )
            assert geometry["text"] == label, geometry
            assert geometry["lines"] == 1, geometry
            assert geometry["textLeft"] >= geometry["tabLeft"], geometry
            assert geometry["textRight"] <= geometry["tabRight"], geometry
            assert geometry["tabLeft"] >= geometry["listLeft"], geometry
            assert geometry["tabRight"] <= geometry["listRight"], geometry
            assert geometry["scrollWidth"] <= geometry["clientWidth"] + 1, geometry
            assert not any(
                ancestor["ellipsis"] or ancestor["clipped"]
                for ancestor in geometry["ancestors"]
            ), geometry

        actual_size = preview.get_by_role(
            "button", name=messages["actualSize"], exact=True
        )
        actual_size.click()
        preview.get_by_role("button", name=messages["zoomIn"], exact=True).click()
        expect(actual_size).to_have_text("110%")
        language.scroll_into_view_if_needed()
        overlay = preview.evaluate(
            """element => {
              const toolbar = element.querySelector(
                '[data-slot="template-preview-toolbar"]',
              );
              const language = toolbar.querySelector('[role="combobox"]');
              const viewport = element.querySelector(
                '[data-slot="document-canvas-viewport"]',
              );
              const frame = element.getBoundingClientRect();
              const floating = toolbar.getBoundingClientRect();
              const control = language.getBoundingClientRect();
              const canvas = viewport.getBoundingClientRect();
              const outsideOverlay = document.elementFromPoint(
                floating.right + 12, floating.top + floating.height / 2,
              );
              return {
                contentTop: frame.top
                  + Number.parseFloat(getComputedStyle(element).borderTopWidth),
                viewportTop: canvas.top,
                frameLeft: frame.left,
                frameRight: frame.right,
                toolbarTop: floating.top,
                toolbarLeft: floating.left,
                toolbarRight: floating.right,
                toolbarWidth: floating.width,
                toolbarHeight: floating.height,
                controlWidth: control.width,
                controlHeight: control.height,
                canvasReceivesPointer: viewport.contains(outsideOverlay),
                toolbarText: toolbar.textContent,
              };
            }"""
        )
        assert overlay["viewportTop"] == pytest.approx(overlay["contentTop"], abs=1)
        assert overlay["toolbarTop"] > overlay["contentTop"]
        assert overlay["toolbarLeft"] > overlay["frameLeft"]
        assert overlay["toolbarRight"] < overlay["frameRight"]
        assert overlay["toolbarWidth"] == pytest.approx(overlay["controlWidth"], abs=1)
        assert overlay["toolbarHeight"] == pytest.approx(
            overlay["controlHeight"], abs=1
        )
        assert overlay["canvasReceivesPointer"], overlay
        assert overlay["toolbarText"] == (
            messages["resumeLanguage"]
            + messages["chinesePreview" if locale == "zh" else "englishPreview"]
        )
        language.click()
        for label in (messages["chinesePreview"], messages["englishPreview"]):
            option = page.get_by_role("option", name=label, exact=True)
            expect(option).to_be_visible()
            geometry = option.evaluate(
                """element => {
                  const text = element.querySelector(':scope > span:last-child');
                  const indicator = element.querySelector(
                    '[data-slot="select-item-indicator"]',
                  );
                  const menu = element.closest('[data-slot="select-content"]');
                  if (!text || !indicator || !menu) {
                    throw new Error('Missing preview language option content.');
                  }
                  const range = document.createRange();
                  range.selectNodeContents(text);
                  const lines = [...range.getClientRects()]
                    .filter(rect => rect.width > 0 && rect.height > 0);
                  const textBounds = range.getBoundingClientRect();
                  const optionBounds = element.getBoundingClientRect();
                  const menuBounds = menu.getBoundingClientRect();
                  const indicatorBounds = indicator.getBoundingClientRect();
                  return {
                    lines: lines.length,
                    text: text.textContent,
                    textLeft: textBounds.left,
                    textRight: textBounds.right,
                    textTop: textBounds.top,
                    textBottom: textBounds.bottom,
                    optionLeft: optionBounds.left,
                    optionTop: optionBounds.top,
                    optionBottom: optionBounds.bottom,
                    indicatorLeft: indicatorBounds.left,
                    menuLeft: menuBounds.left,
                    menuRight: menuBounds.right,
                    viewportWidth: innerWidth,
                  };
                }"""
            )
            assert geometry["text"] == label, geometry
            assert geometry["lines"] == 1, geometry
            assert geometry["textLeft"] >= geometry["optionLeft"], geometry
            assert geometry["textRight"] <= geometry["indicatorLeft"], geometry
            assert geometry["textTop"] >= geometry["optionTop"], geometry
            assert geometry["textBottom"] <= geometry["optionBottom"], geometry
            assert geometry["menuLeft"] >= 0, geometry
            assert geometry["menuRight"] <= geometry["viewportWidth"], geometry

        target_label = messages[
            "englishPreview" if locale == "zh" else "chinesePreview"
        ]
        page.get_by_role("option", name=target_label, exact=True).click()
        expect(language).to_have_text(target_label)
        expect(
            page.locator(".template-workspace .resume-page-shell").first.locator("h1")
        ).to_have_text("Jordan Zhou" if locale == "zh" else "周行远")
        expect(actual_size).to_have_text("110%")
        expect(language).to_be_focused()
        layout = tablist.get_by_role("tab", name=tab_labels[0], exact=True)
        layout.focus()
        for label in tab_labels[1:]:
            page.keyboard.press("ArrowRight")
            tab = tablist.get_by_role("tab", name=label, exact=True)
            expect(tab).to_be_focused()
            expect(tab).to_have_attribute("aria-selected", "true")
            expect(
                editor.get_by_role("tabpanel", name=label, exact=True)
            ).to_have_attribute("aria-labelledby", tab.get_attribute("id"))
        add_image = editor.get_by_role(
            "button", name=messages["addTemplateImage"], exact=True
        )
        expect(add_image).to_be_visible()
        expect(add_image).to_be_disabled()
        page.keyboard.press("Home")
        expect(layout).to_be_focused()
        expect(layout).to_have_attribute("aria-selected", "true")
        page.keyboard.press("End")
        images = tablist.get_by_role("tab", name=tab_labels[-1], exact=True)
        expect(images).to_be_focused()
        expect(images).to_have_attribute("aria-selected", "true")
        expect(add_image).to_be_visible()
    finally:
        context.close()


@pytest.mark.browser_smoke
def test_template_preview_language_preserves_keyboard_focus_without_pointer_ring(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1280, "height": 900},
        reduced_motion="reduce",
    )
    page = context.new_page()
    initial_dark: bool | None = None

    def focus_indicator() -> dict[str, str]:
        return language.evaluate(
            r"""element => {
              const style = getComputedStyle(element);
              const transparent =
                /(?:rgba\([^)]*,|\/)\s*0(?:\.0+)?%?\s*\)|\btransparent\b/;
              return {
                shadow: style.boxShadow.split(/,(?![^(]*\))/)
                  .filter(shadow => [...shadow.matchAll(/(-?[\d.]+)px/g)]
                    .some(match => Number(match[1]) !== 0))
                  .filter(shadow => !transparent.test(shadow))
                  .join(','),
                outline: style.outlineStyle !== 'none'
                  && Number.parseFloat(style.outlineWidth) > 0
                  ? style.outline : 'none',
              };
            }"""
        )

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        language = page.locator('[data-slot="template-preview-toolbar"]').get_by_role(
            "combobox", name="简历语言", exact=True
        )
        theme_toggle = page.get_by_role(
            "button", name="切换日间 / 夜间模式", exact=True
        )
        initial_dark = page.locator("html").evaluate(
            "element => element.classList.contains('dark')"
        )
        for dark in (False, True):
            if (
                page.locator("html").evaluate(
                    "element => element.classList.contains('dark')"
                )
                != dark
            ):
                theme_toggle.click()
            dark_class = re.compile(r"(^|\s)dark(\s|$)")
            if dark:
                expect(page.locator("html")).to_have_class(dark_class)
            else:
                expect(page.locator("html")).not_to_have_class(dark_class)
            theme_toggle.focus()
            unfocused = focus_indicator()

            language.click()
            page.get_by_role("option", name="英文预览", exact=True).click()
            expect(language).to_have_text("英文预览")
            expect(language).to_be_focused()
            assert focus_indicator() == unfocused, {"dark": dark}

            page.keyboard.press("Tab")
            expect(language).not_to_be_focused()
            page.keyboard.press("Shift+Tab")
            expect(language).to_be_focused()
            assert focus_indicator() != unfocused, {"dark": dark}

            language.click()
            expect(page.get_by_role("listbox")).to_be_visible()
            viewport = page.locator(
                '[data-slot="document-canvas-viewport"]'
            ).bounding_box()
            assert viewport is not None
            page.mouse.click(viewport["x"] + 8, viewport["y"] + 8)
            expect(page.get_by_role("listbox")).to_have_count(0)
            expect(language).to_be_focused()
            assert focus_indicator() == unfocused, {"dark": dark}

            language.click()
            expect(page.get_by_role("listbox")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.get_by_role("listbox")).to_have_count(0)
            expect(language).to_be_focused()
            assert focus_indicator() != unfocused, {"dark": dark}
            page.keyboard.press("Enter")
            expect(
                page.get_by_role("option", name="英文预览", exact=True)
            ).to_be_focused()
            page.keyboard.press("ArrowUp")
            expect(
                page.get_by_role("option", name="中文预览", exact=True)
            ).to_be_focused()
            page.keyboard.press("Enter")
            expect(language).to_have_text("中文预览")
            expect(language).to_be_focused()
            assert focus_indicator() != unfocused, {"dark": dark}

            page.keyboard.press("Enter")
            expect(page.get_by_role("listbox")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.get_by_role("listbox")).to_have_count(0)
            expect(language).to_be_focused()
            assert focus_indicator() != unfocused, {"dark": dark}
    finally:
        if (
            initial_dark is not None
            and page.locator("html").evaluate(
                "element => element.classList.contains('dark')"
            )
            != initial_dark
        ):
            theme_toggle.click()
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize(
    "template_id,english_name",
    [
        ("minimal", "Alex Lin"),
        ("modern", "Jordan Zhou"),
        ("compact", "Jordan Zhou"),
        ("classic", "Jordan Zhou"),
        ("executive", "Evelyn Zhao"),
        ("academic", "Ruoan Shen"),
    ],
    ids=["minimal", "modern", "compact", "classic", "executive", "academic"],
)
def test_builtin_template_previews_default_to_one_page(
    browser: Browser,
    workspace_servers: tuple[str, str],
    template_id: str,
    english_name: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()
    preview = page.locator(
        '.template-workspace .resume-preview-card [data-resume-pagination-ready="true"]'
    )

    def assert_content_fits_one_page() -> None:
        expect(preview).to_have_attribute("data-resume-page-count", "1")
        geometry = preview.evaluate(
            """root => {
              const viewport = root.querySelector(
                '.resume-page-content-viewport, .resume-page-flow-viewport',
              );
              const content = viewport.querySelector('[data-resume-flow-content]');
              return {
                viewportBottom: viewport.getBoundingClientRect().bottom,
                contentBottom: content.getBoundingClientRect().bottom,
                sectionBottoms: [...content.querySelectorAll(
                  '[data-resume-section-id]',
                )].map(section => section.getBoundingClientRect().bottom),
              };
            }"""
        )
        assert geometry["sectionBottoms"]
        assert geometry["contentBottom"] <= geometry["viewportBottom"] + 0.5
        assert all(
            bottom <= geometry["viewportBottom"] + 0.5
            for bottom in geometry["sectionBottoms"]
        )

    try:
        page.goto(
            f"{frontend_url}/template/{template_id}",
            wait_until="networkidle",
        )
        assert_content_fits_one_page()

        locale_select = page.get_by_role(
            "combobox",
            name="简历语言",
            exact=True,
        )
        locale_select.click()
        page.get_by_role(
            "option",
            name="英文预览",
            exact=True,
        ).click()

        expect(locale_select).to_have_text("英文预览")
        expect(preview.locator(".resume-page-shell").first.locator("h1")).to_have_text(
            english_name
        )
        assert_content_fits_one_page()
    finally:
        context.close()


@pytest.mark.browser_smoke
def test_template_editor_matches_workspace_boundaries_and_page_scroll(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 720},
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/template/modern", wait_until="networkidle")
        page.evaluate("window.scrollTo(0, 0)")

        editor_panel = page.locator(".template-workspace .resume-template-editor-panel")
        editor_surface = editor_panel.locator('[data-slot="template-editor"]')
        preview_card = page.locator(".template-workspace .resume-preview-card")
        panel_box = editor_panel.bounding_box()
        assert panel_box is not None
        workspace_geometry = page.locator(".template-workspace").evaluate(
            """
            element => {
              const header = element.parentElement?.querySelector(':scope > header');
              const editor = element.querySelector('.resume-template-editor-panel');
              const preview = element.querySelector('.resume-preview-card');
              if (!(header instanceof HTMLElement) ||
                  !(editor instanceof HTMLElement) ||
                  !(preview instanceof HTMLElement)) {
                throw new Error('Missing template workspace panes.');
              }
              const headerRect = header.getBoundingClientRect();
              const editorRect = editor.getBoundingClientRect();
              const previewRect = preview.getBoundingClientRect();
              return {
                headerBottom: headerRect.bottom,
                editorTop: editorRect.top,
                editorRight: editorRect.right,
                previewTop: previewRect.top,
                previewLeft: previewRect.left,
                previewRight: previewRect.right,
                previewBottom: previewRect.bottom,
                viewportWidth: window.innerWidth,
                viewportHeight: window.innerHeight,
                maxScrollY: document.documentElement.scrollHeight - innerHeight,
              };
            }
            """
        )

        assert workspace_geometry["editorTop"] == pytest.approx(
            workspace_geometry["headerBottom"], abs=1
        )
        assert workspace_geometry["previewTop"] == pytest.approx(
            workspace_geometry["headerBottom"], abs=1
        )
        assert workspace_geometry["editorRight"] == pytest.approx(
            panel_box["x"] + panel_box["width"], abs=1
        )
        assert workspace_geometry["editorRight"] == pytest.approx(
            workspace_geometry["previewLeft"], abs=1
        )
        assert workspace_geometry["previewRight"] == pytest.approx(
            workspace_geometry["viewportWidth"], abs=1
        )
        assert workspace_geometry["previewBottom"] == pytest.approx(
            workspace_geometry["viewportHeight"], abs=1
        )

        before = {
            "editor": editor_surface.bounding_box(),
            "preview": preview_card.bounding_box(),
        }
        assert before["editor"] is not None
        assert before["preview"] is not None

        page.mouse.move(
            panel_box["x"] + panel_box["width"] / 2,
            panel_box["y"] + min(panel_box["height"] / 2, 360),
        )
        page.mouse.wheel(0, 160)
        expected_scroll = min(160, workspace_geometry["maxScrollY"])
        assert expected_scroll > 0
        page.wait_for_function(
            "expected => Math.abs(window.scrollY - expected) <= 1",
            arg=expected_scroll,
        )

        after = {
            "editor": editor_surface.bounding_box(),
            "preview": preview_card.bounding_box(),
        }
        assert after["editor"] is not None
        assert after["preview"] is not None
        scroll_state = editor_panel.evaluate(
            """
            element => ({
              borderRightWidth: getComputedStyle(element).borderRightWidth,
              overflowY: getComputedStyle(element).overflowY,
              paddingLeft: getComputedStyle(element).paddingLeft,
              paddingRight: getComputedStyle(element).paddingRight,
              position: getComputedStyle(element).position,
              previewPosition: getComputedStyle(
                document.querySelector('.template-workspace .resume-preview-card')
              ).position,
              scrollTop: element.scrollTop,
              windowScrollY: window.scrollY,
            })
            """
        )
        editor_delta = after["editor"]["y"] - before["editor"]["y"]
        preview_delta = after["preview"]["y"] - before["preview"]["y"]

        expect(editor_panel.locator('[data-slot="card"]')).to_have_count(0)
        assert scroll_state["borderRightWidth"] == "1px"
        assert scroll_state["overflowY"] == "visible"
        assert scroll_state["paddingLeft"] == "20px"
        assert scroll_state["paddingRight"] == "20px"
        assert scroll_state["position"] == "relative"
        assert scroll_state["previewPosition"] == "relative"
        assert scroll_state["scrollTop"] == 0
        assert scroll_state["windowScrollY"] > 0
        assert editor_delta == pytest.approx(-expected_scroll, abs=1)
        assert editor_delta == pytest.approx(preview_delta, abs=1)

        page.evaluate("window.scrollTo(0, 0)")
        page.set_viewport_size({"width": 1440, "height": 1000})

        def divider_geometry() -> dict[str, float | str]:
            return page.locator(".template-workspace").evaluate(
                """
                element => {
                  const editor = element.querySelector(
                    '.resume-template-editor-panel',
                  );
                  const surface = editor?.querySelector(
                    '[data-slot="template-editor"]',
                  );
                  if (!(editor instanceof HTMLElement) ||
                      !(surface instanceof HTMLElement)) {
                    throw new Error('Missing template editor surface.');
                  }
                  const editorRect = editor.getBoundingClientRect();
                  const surfaceRect = surface.getBoundingClientRect();
                  const workspaceRect = element.getBoundingClientRect();
                  return {
                    alignSelf: getComputedStyle(editor).alignSelf,
                    editorBottom: editorRect.bottom,
                    editorHeight: editorRect.height,
                    overflowY: getComputedStyle(editor).overflowY,
                    surfaceBottom: surfaceRect.bottom,
                    viewportHeight: window.innerHeight,
                    workspaceBottom: workspaceRect.bottom,
                  };
                }
                """
            )

        short_editor = divider_geometry()
        assert short_editor["surfaceBottom"] < short_editor["workspaceBottom"]
        assert short_editor["editorBottom"] == pytest.approx(
            short_editor["workspaceBottom"], abs=1
        )
        assert short_editor["alignSelf"] == "stretch"

        editor_surface.evaluate("element => { element.style.minHeight = '1500px'; }")
        tall_editor = divider_geometry()
        assert tall_editor["overflowY"] == "visible"
        assert tall_editor["editorHeight"] > tall_editor["viewportHeight"]
        assert tall_editor["editorBottom"] > short_editor["editorBottom"]
        assert tall_editor["surfaceBottom"] <= tall_editor["editorBottom"]
        assert tall_editor["editorBottom"] == pytest.approx(
            tall_editor["workspaceBottom"], abs=1
        )
        editor_surface.evaluate("element => { element.style.minHeight = ''; }")

        page.set_viewport_size({"width": 1200, "height": 900})
        narrow_geometry = page.locator(".template-workspace").evaluate(
            """
            element => {
              const editor = element.querySelector('.resume-template-editor-panel');
              const preview = element.querySelector('.resume-preview-card');
              if (!(editor instanceof HTMLElement) ||
                  !(preview instanceof HTMLElement)) {
                throw new Error('Missing narrow template workspace panes.');
              }
              const editorRect = editor.getBoundingClientRect();
              const previewRect = preview.getBoundingClientRect();
              const editorStyle = getComputedStyle(editor);
              return {
                borderRightWidth: editorStyle.borderRightWidth,
                documentScrollWidth: document.documentElement.scrollWidth,
                editorBottom: editorRect.bottom,
                editorLeft: editorRect.left,
                editorRight: editorRect.right,
                paddingLeft: editorStyle.paddingLeft,
                paddingRight: editorStyle.paddingRight,
                previewLeft: previewRect.left,
                previewRight: previewRect.right,
                previewTop: previewRect.top,
                viewportWidth: window.innerWidth,
              };
            }
            """
        )
        assert narrow_geometry["editorBottom"] <= narrow_geometry["previewTop"]
        assert narrow_geometry["editorLeft"] == pytest.approx(
            narrow_geometry["previewLeft"], abs=1
        )
        assert narrow_geometry["editorRight"] == pytest.approx(
            narrow_geometry["previewRight"], abs=1
        )
        assert narrow_geometry["borderRightWidth"] == "0px"
        assert narrow_geometry["paddingLeft"] == "20px"
        assert narrow_geometry["paddingRight"] == "20px"
        assert (
            narrow_geometry["documentScrollWidth"] <= narrow_geometry["viewportWidth"]
        )
    finally:
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
def test_default_template_action_transitions_after_success_and_allows_retry(
    browser: Browser,
    workspace_servers: tuple[str, str],
    reduced_motion: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
        reduced_motion=reduced_motion,
    )
    context.add_init_script(
        """
        window.__defaultButtonTransitions = [];
        for (const eventName of ['transitionrun', 'animationstart']) {
          document.addEventListener(eventName, event => {
            if (event.target instanceof Element && event.target.closest(
              '[data-slot="template-default-button"]',
            )) {
              window.__defaultButtonTransitions.push(event.type);
            }
          }, true);
        }
        """
    )
    page = context.new_page()
    path = f"{frontend_url}/api/workspace/default-template"

    def assert_selected_button() -> None:
        expect(button).to_have_accessible_name("默认模板")
        expect(button).to_be_disabled()
        expect(button.locator("svg")).to_have_count(0)
        expect(button).to_have_css("background-color", selected_color)
        expect(button.locator('[data-slot="template-default-action"]')).to_have_css(
            "opacity", "0"
        )
        expect(button.locator('[data-slot="template-default-status"]')).to_have_css(
            "opacity", "1"
        )

    try:
        response = page.request.put(
            path, data={"documentLocale": "zh", "templateId": "minimal"}
        )
        assert response.ok
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        button = page.locator('[data-slot="template-default-button"]')
        selected_color = button.evaluate(
            """button => {
              const sample = document.createElement('span');
              sample.style.backgroundColor = 'var(--secondary)';
              button.append(sample);
              const color = getComputedStyle(sample).backgroundColor;
              sample.remove();
              return color;
            }"""
        )
        assert selected_color != "rgba(0, 0, 0, 0)"
        assert_selected_button()
        assert page.evaluate("window.__defaultButtonTransitions") == []

        page.goto(f"{frontend_url}/template/modern", wait_until="networkidle")
        expect(button).to_have_accessible_name("设为默认模板")
        expect(button).to_be_enabled()
        assert page.evaluate("window.__defaultButtonTransitions") == []
        button.evaluate(
            """button => {
              window.__defaultButton = button;
              window.__defaultButtonFrames = [];
              window.__defaultButtonRecording = true;
              const sample = () => {
                const rect = button.getBoundingClientRect();
                const action = button.querySelector(
                  '[data-slot="template-default-action"]',
                );
                const status = button.querySelector(
                  '[data-slot="template-default-status"]',
                );
                window.__defaultButtonFrames.push({
                  x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                  selected: button.getAttribute('aria-label') === '默认模板',
                  busy: button.getAttribute('aria-busy') === 'true',
                  actionOpacity: Number(getComputedStyle(action).opacity),
                  statusOpacity: Number(getComputedStyle(status).opacity),
                  background: getComputedStyle(button).backgroundColor,
                  animations: button.getAnimations({ subtree: true }).length,
                });
                if (window.__defaultButtonRecording) requestAnimationFrame(sample);
              };
              sample();
            }"""
        )

        failed_save = DeferredRoute(page, "**/api/workspace/default-template")
        button.click()
        failed_save.wait()
        expect(button).to_have_attribute("aria-busy", "true")
        expect(button).to_be_disabled()
        expect(button.locator('[role="status"]')).to_be_visible()
        page.wait_for_function("window.__defaultButtonFrames.some(frame => frame.busy)")
        failed_save.release(
            lambda route: route.fulfill(
                status=500,
                content_type="application/json",
                body=json.dumps({"detail": "Default template update failed."}),
            )
        )
        expect(button).to_be_enabled()
        expect(button).not_to_have_attribute("aria-busy", "true")
        expect(button).to_have_accessible_name("设为默认模板")
        expect(button.locator('[role="status"]')).to_have_count(0)
        expect(button.locator('[data-slot="template-default-action"]')).to_have_css(
            "opacity", "1"
        )

        successful_save = DeferredRoute(page, "**/api/workspace/default-template")
        button.click()
        successful_save.wait()
        expect(button).to_have_attribute("aria-busy", "true")
        expect(button.locator('[role="status"]')).to_be_visible()
        successful_save.release()
        assert_selected_button()
        frames = page.evaluate(
            """() => {
              window.__defaultButtonRecording = false;
              return window.__defaultButtonFrames;
            }"""
        )
        assert button.evaluate("button => button === window.__defaultButton")
        for key in ("x", "y", "width", "height"):
            values = [frame[key] for frame in frames]
            assert max(values) - min(values) <= 1, {"key": key, "frames": frames}
        selected_frames = [frame for frame in frames if frame["selected"]]
        assert selected_frames
        if reduced_motion == "reduce":
            assert all(frame["animations"] == 0 for frame in frames), frames
            assert all(
                frame["actionOpacity"] == 0 and frame["statusOpacity"] == 1
                for frame in selected_frames
            ), selected_frames
            assert all(
                frame["background"] == selected_color for frame in selected_frames
            ), selected_frames
        else:
            assert any(
                0 < frame["actionOpacity"] < 1 and 0 < frame["statusOpacity"] < 1
                for frame in selected_frames
            ), selected_frames
            assert len({frame["background"] for frame in selected_frames}) > 2, (
                selected_frames
            )

        page.reload(wait_until="networkidle")
        assert_selected_button()
        assert page.evaluate("window.__defaultButtonTransitions") == []
    finally:
        page.request.put(path, data={"documentLocale": "zh", "templateId": "minimal"})
        context.close()


@pytest.mark.browser_smoke
def test_template_editor_fields_use_visible_labels_as_accessible_names(
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
    template_id: str | None = None

    def assert_template_metadata_in_header() -> None:
        header = page.locator('[data-slot="template-workspace-header"]')
        editor = page.locator('[data-slot="template-editor"]')
        expect(header.locator('[data-slot="template-editor-title"]')).to_be_visible()
        expect(header.locator('[data-slot="template-description"]')).to_be_visible()
        expect(
            editor.locator(
                '[data-slot="template-editor-title"], '
                '[data-slot="template-description"]'
            )
        ).to_have_count(0)
        header_box = header.bounding_box()
        expect(header.locator('[data-slot="template-editor-actions"]')).to_have_count(0)
        actions_box = editor.locator(
            '[data-slot="template-editor-actions"]'
        ).bounding_box()
        tabs_box = editor.get_by_role(
            "tablist", name="简历模板", exact=True
        ).bounding_box()
        assert header_box is not None
        assert actions_box is not None
        assert tabs_box is not None
        assert actions_box["y"] >= header_box["y"] + header_box["height"]
        assert tabs_box["y"] >= actions_box["y"] + actions_box["height"]
        _assert_template_actions_align_with_heading(editor)

    def delay_default_template_response(route: Route) -> None:
        response = route.fetch()
        time.sleep(0.25)
        route.fulfill(response=response)

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        assert_template_metadata_in_header()
        expect(
            page.get_by_role("combobox", name="头像位置", exact=True)
        ).to_be_disabled()
        for label in ("页边距", "行距"):
            expect(page.get_by_role("slider", name=label, exact=True)).to_be_disabled()
        expect(page.get_by_role("spinbutton", name="行距", exact=True)).to_be_disabled()
        margin_details = page.get_by_role("button", name="页边距详情", exact=True)
        expect(margin_details).to_be_enabled()
        margin_details.click()
        margin_dialog = page.get_by_role("dialog", name="页边距", exact=True)
        for label in ("上", "左右", "下"):
            expect(
                margin_dialog.get_by_role("spinbutton", name=label, exact=True)
            ).to_be_disabled()
        expect(
            margin_dialog.get_by_role("button", name="统一为左右边距", exact=True)
        ).to_have_count(0)
        page.keyboard.press("Escape")
        expect(margin_dialog).to_have_count(0)
        expect(margin_details).to_be_focused()
        expect(
            page.get_by_role(
                "button",
                name="修改模板信息",
                exact=True,
            )
        ).to_have_count(0)
        page.get_by_role(
            "button",
            name="创建副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = urlparse(page.url).path.rsplit("/", maxsplit=1)[-1]

        expect(page.get_by_text("自定义模板 · 可编辑", exact=True)).to_have_count(0)
        expect(page.get_by_text("模板信息", exact=True)).to_have_count(0)

        metadata_trigger = page.get_by_role(
            "button",
            name="修改模板信息",
            exact=True,
        )
        expect(metadata_trigger).to_be_visible()
        original_title = page.locator(
            '[data-slot="template-editor-title"]'
        ).inner_text()
        original_description = page.locator(
            '[data-slot="template-description"]'
        ).inner_text()
        page.evaluate(
            """
            () => {
              window.__templateDialogAnimations = [];
              document.addEventListener('animationstart', (event) => {
                const target = event.target;
                if (!(target instanceof HTMLElement)) {
                  return;
                }
                if (
                  target.matches(
                    '[data-slot="dialog-content"], [data-slot="dialog-overlay"]',
                  )
                ) {
                  window.__templateDialogAnimations.push({
                    animationName: event.animationName,
                    slot: target.dataset.slot,
                  });
                }
              }, true);
            }
            """
        )

        metadata_trigger.click()
        page.get_by_role(
            "heading",
            name="修改模板信息",
            exact=True,
        ).wait_for(state="visible")
        name_input = page.get_by_label("模板名称", exact=True)
        description_input = page.get_by_placeholder(
            "可在模板编辑器中补充这套版式适用的岗位或使用场景",
            exact=True,
        )
        expect(name_input).to_have_value(original_title)
        expect(description_input).to_have_value(original_description)
        expect(description_input).to_have_attribute(
            "placeholder",
            "可在模板编辑器中补充这套版式适用的岗位或使用场景",
        )
        name_input.fill("不应保存的模板名称")
        description_input.fill("不应保存的模板描述")
        page.get_by_role("button", name="取消", exact=True).click()
        page.get_by_role(
            "heading",
            name="修改模板信息",
            exact=True,
        ).wait_for(state="hidden")
        expect(metadata_trigger).to_be_focused()
        expect(page.locator('[data-slot="template-editor-title"]')).to_have_text(
            original_title
        )
        expect(page.locator('[data-slot="template-description"]')).to_have_text(
            original_description
        )

        template_name = "产品岗位模板"
        template_description = "适合产品岗位与跨职能项目经历"
        metadata_trigger.click()
        page.get_by_label("模板名称", exact=True).fill(template_name)
        description_input = page.get_by_label("模板描述", exact=True)
        description_input.fill(template_description)
        page.get_by_role("button", name="保存", exact=True).click()
        page.get_by_role(
            "heading",
            name="修改模板信息",
            exact=True,
        ).wait_for(state="hidden")
        page.wait_for_timeout(200)
        expect(metadata_trigger).to_be_focused()

        dialog_animation_names = {
            item["animationName"]
            for item in page.evaluate("window.__templateDialogAnimations")
        }
        assert {
            "dialog-content-enter",
            "dialog-content-exit",
            "dialog-overlay-enter",
            "dialog-overlay-exit",
        }.issubset(dialog_animation_names)

        expect(page.locator('[data-slot="template-editor-title"]')).to_have_text(
            template_name
        )
        description_note = page.locator('[data-slot="template-description"]')
        expect(description_note).to_be_visible()
        expect(description_note).to_have_text(template_description)
        expect(
            page.get_by_text(
                "可在模板编辑器中补充这套版式适用的岗位或使用场景",
                exact=True,
            )
        ).to_have_count(0)
        description_note_box = description_note.bounding_box()
        assert description_note_box is not None
        assert description_note_box["height"] > 0
        assert_template_metadata_in_header()

        with page.expect_request(
            lambda request: (
                request.method == "PUT"
                and urlparse(request.url).path == f"/api/templates/{template_id}"
            )
        ) as save_request:
            page.keyboard.press("Control+S")
        save_payload = save_request.value.post_data_json
        assert save_payload["template"]["name"] == template_name
        assert save_payload["template"]["description"] == template_description

        page.route(
            "**/api/workspace/default-template",
            delay_default_template_response,
        )
        set_default_button = page.locator('[data-slot="template-default-button"]')
        expect(set_default_button).to_have_attribute(
            "aria-label",
            "设为默认模板",
        )
        set_default_button.evaluate(
            """
            (button) => {
              const frames = [];
              window.__defaultTemplateButtonFrames = frames;
              const startedAt = performance.now();
              const sample = () => {
                const rect = button.getBoundingClientRect();
                frames.push({
                  elapsed: performance.now() - startedAt,
                  x: rect.x,
                  y: rect.y,
                  width: rect.width,
                  height: rect.height,
                  label: button.getAttribute('aria-label'),
                  isBusy: button.getAttribute('aria-busy') === 'true',
                  hasSpinner: Boolean(button.querySelector('[role="status"]')),
                });
                if (performance.now() - startedAt < 900) {
                  requestAnimationFrame(sample);
                }
              };
              requestAnimationFrame(sample);
            }
            """
        )
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == "/api/workspace/default-template"
            )
        ):
            set_default_button.click()
        expect(set_default_button).to_have_attribute(
            "aria-label",
            "默认模板",
        )
        page.wait_for_timeout(700)
        default_button_frames = page.evaluate("window.__defaultTemplateButtonFrames")
        assert len(default_button_frames) >= 20
        assert any(frame["isBusy"] for frame in default_button_frames)
        assert any(frame["hasSpinner"] for frame in default_button_frames)
        assert any(frame["label"] == "默认模板" for frame in default_button_frames)
        expect(set_default_button.locator("svg")).to_have_count(0)
        for key in ("x", "y", "width", "height"):
            values = [frame[key] for frame in default_button_frames]
            assert max(values) - min(values) <= 1, {
                "key": key,
                "frames": default_button_frames,
            }

        for label in (
            "信息布局",
            "模块标题",
            "经历布局",
            "列表布局",
            "头像位置",
            "头像尺寸",
            "分隔线",
        ):
            expect(page.get_by_role("combobox", name=label, exact=True)).to_be_visible()

        basic_info_select = page.get_by_role(
            "combobox",
            name="信息布局",
            exact=True,
        )
        basic_info_select.click()
        left_header = page.get_by_role("option", name="左对齐标题", exact=True)
        left_header_preview = left_header.locator("svg").inner_html()
        left_header.click()
        expect(basic_info_select).to_have_text("左对齐标题")
        selected_preview = basic_info_select.locator('[data-slot="select-value"] svg')
        expect(selected_preview).to_be_visible()
        expect(selected_preview).to_have_attribute("aria-hidden", "true")
        assert selected_preview.inner_html() == left_header_preview

        section_style = page.get_by_role("combobox", name="模块标题", exact=True)
        section_style.focus()
        section_style.press("Enter")
        for option in (
            "标题横线",
            "下划线标题",
            "边框卡片",
            "强调标题",
            "纯标题",
            "色带标题",
        ):
            expect(page.get_by_role("option", name=option, exact=True)).to_be_visible()
        boxed_preview = (
            page.get_by_role("option", name="边框卡片", exact=True)
            .locator("svg")
            .inner_html()
        )
        page.keyboard.press("Home")
        expect(page.get_by_role("option", name="标题横线", exact=True)).to_be_focused()
        page.keyboard.press("ArrowDown")
        expect(
            page.get_by_role("option", name="下划线标题", exact=True)
        ).to_be_focused()
        page.keyboard.press("ArrowDown")
        expect(page.get_by_role("option", name="边框卡片", exact=True)).to_be_focused()
        page.keyboard.press("Enter")
        expect(section_style).to_have_text("边框卡片")
        expect(section_style).to_be_focused()
        selected_preview = section_style.locator('[data-slot="select-value"] svg')
        expect(selected_preview).to_be_visible()
        expect(selected_preview).to_have_attribute("aria-hidden", "true")
        assert selected_preview.inner_html() == boxed_preview

        avatar_size_select = page.get_by_role(
            "combobox",
            name="头像尺寸",
            exact=True,
        )
        avatar_size_select.click()
        page.get_by_role("option", name="大", exact=True).click()
        expect(avatar_size_select).to_have_text("大")
        assert page.locator('[data-avatar-frame="true"]').first.evaluate(
            "element => [element.style.width, element.style.height]"
        ) == ["29mm", "37mm"]

        avatar_position = page.get_by_role("combobox", name="头像位置", exact=True)
        avatar_position.click()
        page.get_by_role("option", name="不显示头像", exact=True).click()
        expect(avatar_position).to_have_text("不显示头像")
        expect(avatar_size_select).to_have_count(0)
        density = page.get_by_role("tablist", name="内容密度", exact=True)
        density.get_by_role("tab", name="宽松", exact=True).click()
        expect(density.get_by_role("tab", name="宽松", exact=True)).to_have_attribute(
            "aria-selected", "true"
        )
        for label in ("页边距", "行距"):
            slider = page.get_by_role("slider", name=label, exact=True)
            expect(slider).to_be_visible()
            expect(slider).to_be_enabled()
            expect(slider).to_have_accessible_name(label)
        expect(page.get_by_role("spinbutton", name="行距", exact=True)).to_be_enabled()
        margin_details.click()
        for label in ("上", "左右", "下"):
            expect(
                margin_dialog.get_by_role("spinbutton", name=label, exact=True)
            ).to_be_enabled()
        expect(
            margin_dialog.get_by_role("button", name="统一为左右边距", exact=True)
        ).to_be_enabled()
        page.keyboard.press("Escape")
        expect(margin_dialog).to_have_count(0)
        expect(margin_details).to_be_focused()

        page.get_by_role("tab", name="字体", exact=True).click()
        for label in (
            "姓名字号",
            "模块标题字号",
            "条目标题字号",
            "辅助信息字号",
            "正文字号",
        ):
            slider = page.get_by_role("slider", name=label, exact=True)
            expect(slider).to_be_visible()
            expect(slider).to_have_accessible_name(label)
            expect(
                page.get_by_role("spinbutton", name=label, exact=True)
            ).to_be_visible()

        page.get_by_role("tab", name="配色", exact=True).click()
        for label in (
            "页面背景",
            "块面背景",
            "标题颜色",
            "正文字色",
            "辅助文字颜色",
            "分隔线颜色",
        ):
            color_input = page.get_by_label(label, exact=True)
            expect(color_input).to_be_visible()
            assert color_input.get_attribute("type") == "color"
    finally:
        page.request.put(
            f"{frontend_url}/api/workspace/default-template",
            data={"documentLocale": "zh", "templateId": "minimal"},
        )
        if template_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()
