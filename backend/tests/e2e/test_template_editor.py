from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Route, expect

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


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
            name="创建可编辑副本",
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
            name="创建可编辑副本",
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
            name="创建可编辑副本",
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


def test_builtin_template_header_keeps_actions_on_one_row(
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
        page.goto(f"{frontend_url}/template/modern", wait_until="networkidle")

        action_boxes = [
            locator.bounding_box()
            for locator in (
                page.get_by_role("combobox", name="简历语言", exact=True),
                page.get_by_role("button", name="创建可编辑副本", exact=True),
                page.get_by_role("button", name="设为默认模板", exact=True),
            )
        ]
        assert all(box is not None for box in action_boxes)
        action_rows = {round(float(box["y"])) for box in action_boxes if box}
        assert len(action_rows) == 1, action_boxes
    finally:
        context.close()


def test_builtin_template_previews_default_to_one_page(
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
    templates = {
        "minimal": "Alex Lin",
        "modern": "Jordan Zhou",
        "compact": "Jordan Zhou",
        "classic": "Jordan Zhou",
        "executive": "Evelyn Zhao",
        "academic": "Ruoan Shen",
    }

    try:
        for template_id, english_name in templates.items():
            page.goto(
                f"{frontend_url}/template/{template_id}",
                wait_until="networkidle",
            )
            preview = page.locator(
                ".template-workspace .resume-preview-card "
                '[data-resume-pagination-ready="true"]'
            )
            expect(preview).to_have_attribute("data-resume-page-count", "1")

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
            expect(
                preview.locator(".resume-page-shell").first.locator("h1")
            ).to_have_text(english_name)
            expect(preview).to_have_attribute("data-resume-page-count", "1")
    finally:
        context.close()


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
        page.wait_for_timeout(150)

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
        assert scroll_state["paddingLeft"] == "16px"
        assert scroll_state["paddingRight"] == "16px"
        assert scroll_state["position"] == "relative"
        assert scroll_state["previewPosition"] == "relative"
        assert scroll_state["scrollTop"] == 0
        assert scroll_state["windowScrollY"] > 0
        assert editor_delta < -100
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
        assert narrow_geometry["paddingLeft"] == "0px"
        assert narrow_geometry["paddingRight"] == "0px"
        assert (
            narrow_geometry["documentScrollWidth"] <= narrow_geometry["viewportWidth"]
        )
    finally:
        context.close()


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

    def assert_template_header_rows() -> None:
        description_box = page.locator(
            '[data-slot="template-description"]'
        ).bounding_box()
        actions_box = page.locator(
            '[data-slot="template-editor-actions"]'
        ).bounding_box()
        assert description_box is not None
        assert actions_box is not None
        assert abs(actions_box["x"] - description_box["x"]) <= 1
        assert actions_box["y"] >= description_box["y"] + description_box["height"]

    def delay_default_template_response(route: Route) -> None:
        response = route.fetch()
        time.sleep(0.25)
        route.fulfill(response=response)

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        assert_template_header_rows()
        expect(
            page.get_by_role(
                "button",
                name="修改模板信息",
                exact=True,
            )
        ).to_have_count(0)
        page.get_by_role(
            "button",
            name="创建可编辑副本",
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
        assert description_note_box["height"] >= 24
        assert_template_header_rows()

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
        assert not any(frame["hasSpinner"] for frame in default_button_frames)
        assert any(frame["label"] == "默认模板" for frame in default_button_frames)
        for key in ("x", "y", "width", "height"):
            values = [frame[key] for frame in default_button_frames]
            assert max(values) - min(values) <= 1, {
                "key": key,
                "frames": default_button_frames,
            }

        for label in (
            "基本信息布局",
            "模块标题样式",
            "经历条目布局",
            "列表条目布局",
            "头像位置",
            "头像尺寸",
            "页边距",
            "内容密度",
            "分隔线样式",
        ):
            expect(page.get_by_role("combobox", name=label, exact=True)).to_be_visible()

        basic_info_select = page.get_by_role(
            "combobox",
            name="基本信息布局",
            exact=True,
        )
        page.locator("label").filter(has=basic_info_select).get_by_text(
            "基本信息布局",
            exact=True,
        ).click()
        page.get_by_role("option", name="左对齐标题", exact=True).click()
        expect(basic_info_select).to_have_text("左对齐标题")

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

        avatar_position_select = page.get_by_role(
            "combobox",
            name="头像位置",
            exact=True,
        )
        avatar_position_select.click()
        page.get_by_role("option", name="不显示头像", exact=True).click()
        expect(avatar_size_select).to_have_count(0)

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
            assert slider.get_attribute("aria-label") == label

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
