from __future__ import annotations

import os
import re
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Locator, expect

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


@pytest.mark.browser_smoke
@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
def test_template_tabs_animate_and_preserve_image_controls_when_switching_quickly(
    browser: Browser,
    workspace_servers: tuple[str, str],
    reduced_motion: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 1000},
        reduced_motion=reduced_motion,
    )
    page = context.new_page()
    template_id: str | None = None

    def wait_for_indicator(tablist: Locator) -> None:
        page.wait_for_function(
            """list => {
              const indicator = list.querySelector(
                '[data-slot="template-tabs-indicator"]',
              );
              const active = list.querySelector('[role="tab"][aria-selected="true"]');
              if (!indicator || !active) return false;
              const actual = indicator.getBoundingClientRect();
              const expected = active.getBoundingClientRect();
              return Math.abs(actual.x - expected.x) <= 1
                && Math.abs(actual.width - expected.width) <= 1
                && !indicator.getAnimations().some(
                  item => item.playState === 'running',
                );
            }""",
            arg=tablist.element_handle(),
        )

    def record_switch(tablist: Locator, start: str, target: str) -> None:
        wait_for_indicator(tablist)
        tablist.evaluate(
            """list => {
              const indicator = list.querySelector(
                '[data-slot="template-tabs-indicator"]',
              );
              window.__templateTabFrames = [];
              window.__templateTabRecording = true;
              const sample = () => {
                const active = list.querySelector('[role="tab"][aria-selected="true"]');
                const panel = document.getElementById(
                  active.getAttribute('aria-controls'),
                );
                const rect = indicator.getBoundingClientRect();
                const target = active.getBoundingClientRect();
                window.__templateTabFrames.push({
                  x: rect.x,
                  targetX: target.x,
                  moving: indicator.getAnimations().some(
                    item => item.playState === 'running',
                  ),
                  panelOpacity: panel ? Number(getComputedStyle(panel).opacity) : null,
                });
                if (window.__templateTabRecording) requestAnimationFrame(sample);
              };
              sample();
            }"""
        )
        source = tablist.get_by_role("tab", name=start, exact=True)
        source.focus()
        source.press("ArrowRight")
        destination = tablist.get_by_role("tab", name=target, exact=True)
        expect(destination).to_be_focused()
        expect(destination).to_have_attribute("aria-selected", "true")
        wait_for_indicator(tablist)
        frames = page.evaluate(
            """() => {
              window.__templateTabRecording = false;
              return window.__templateTabFrames;
            }"""
        )
        if reduced_motion == "reduce":
            assert not any(frame["moving"] for frame in frames), frames
            assert all(frame["panelOpacity"] in (None, 1) for frame in frames), frames
        else:
            assert any(frame["moving"] for frame in frames), frames
            initial_x = frames[0]["x"]
            assert any(
                min(initial_x, frame["targetX"])
                < frame["x"]
                < max(initial_x, frame["targetX"])
                for frame in frames
            ), frames
            if target == "字体":
                assert any(
                    frame["panelOpacity"] is not None and 0 < frame["panelOpacity"] < 1
                    for frame in frames
                ), frames

    def record_border(image_editor: Locator, *, reverse: bool = False) -> None:
        image_editor.evaluate(
            """(editor, options) => {
              const record = { active: true, frames: [], reversed: false };
              window.__templateBorderRecording = record;
              const sample = () => {
                if (!record.active || window.__templateBorderRecording !== record) {
                  return;
                }
                const toggle = editor.querySelector('[role="switch"]');
                const panel = editor.querySelector('.template-image-border-presence');
                const width = panel?.querySelector('input[type="number"]');
                const inputs = [...(panel?.querySelectorAll('input') ?? [])];
                const checked = toggle.getAttribute('aria-checked') === 'true';
                const opacity = panel ? Number(getComputedStyle(panel).opacity) : null;
                const moving = panel?.getAnimations().some(
                  animation => animation.playState === 'running',
                ) ?? false;
                let acceptedFocus = false;
                if (!checked && width) {
                  width.focus();
                  acceptedFocus = document.activeElement === width;
                }
                record.frames.push({
                  checked, opacity, moving,
                  rendered: Boolean(panel?.getBoundingClientRect().width),
                  inputs: inputs.length,
                  inert: panel?.inert ?? false,
                  ariaHidden: panel?.getAttribute('aria-hidden'),
                  disabled: inputs.length > 0 && inputs.every(input => input.disabled),
                  width: width?.value,
                  acceptedFocus,
                  borderWidth: Number.parseFloat(editor.querySelector(
                    '[data-slot="template-image-thumbnail"]',
                  ).style.borderWidth),
                });
                if (options.reverse && !record.reversed && !checked
                    && (options.reduce || (moving && opacity > 0 && opacity < 1))) {
                  record.reversed = true;
                  toggle.click();
                }
                if (record.active) requestAnimationFrame(sample);
              };
              sample();
            }""",
            {"reverse": reverse, "reduce": reduced_motion == "reduce"},
        )

    def finish_border_recording() -> list[dict]:
        return page.evaluate(
            """async () => {
              const record = window.__templateBorderRecording;
              await new Promise(requestAnimationFrame);
              record.active = false;
              return record.frames;
            }"""
        )

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role("button", name="创建副本", exact=True).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        expect(
            page.get_by_role("button", name="修改模板信息", exact=True)
        ).to_be_visible()
        template_id = urlparse(page.url).path.rsplit("/", maxsplit=1)[-1]
        top_tabs = page.get_by_role("tablist", name="简历模板", exact=True)
        density = page.get_by_role("tablist", name="内容密度", exact=True)
        density.get_by_role("tab", name="紧凑", exact=True).click()
        record_switch(density, "紧凑", "标准")
        line_height = page.get_by_role("spinbutton", name="行距", exact=True)
        expect(line_height).to_have_value("19.2")
        original_line_height = line_height.element_handle()
        assert original_line_height is not None
        line_height.fill("22.8")
        expect(density.get_by_role("tab", selected=True)).to_have_count(0)
        expect(line_height).to_be_focused()
        assert original_line_height.evaluate("element => element.isConnected")
        assert line_height.evaluate(
            "(element, original) => element === original", original_line_height
        )
        record_switch(top_tabs, "布局", "字体")
        for label in ("配色", "布局", "装饰"):
            top_tabs.get_by_role("tab", name=label, exact=True).click()
        expect(top_tabs.get_by_role("tab", name="装饰", exact=True)).to_have_attribute(
            "aria-selected", "true"
        )
        wait_for_indicator(top_tabs)
        page.get_by_role("button", name="添加图片占位符", exact=True).click()
        image_editor = page.get_by_role("group", name="图片元素 1", exact=True)
        collapse = image_editor.get_by_role("button", name="收起图片设置", exact=True)
        expect(collapse).to_have_attribute("aria-expanded", "true")
        top_tabs.get_by_role("tab", name="布局", exact=True).click()
        top_tabs.get_by_role("tab", name="装饰", exact=True).click()
        expect(collapse).to_have_attribute("aria-expanded", "true")
        x_input = image_editor.get_by_role("spinbutton", name="横向位置", exact=True)
        expect(x_input).to_be_visible()
        original_input = x_input.element_handle()
        assert original_input is not None
        image_editor.locator('input[type="file"]').set_input_files(
            {
                "name": "fit.svg",
                "mimeType": "image/svg+xml",
                "buffer": (
                    b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="5"/>'
                ),
            }
        )
        thumbnail = image_editor.locator('[data-slot="template-image-thumbnail"] img')
        expect(thumbnail).to_be_visible()
        fit_tabs = image_editor.get_by_role("tablist", name="适配方式", exact=True)
        record_switch(fit_tabs, "完整显示", "填满裁剪")
        expect(thumbnail).to_have_css("object-fit", "cover")
        assert original_input.evaluate("element => element.isConnected")
        assert x_input.evaluate(
            "(element, original) => element === original", original_input
        )
        border_switch = image_editor.get_by_role("switch", name="边框", exact=True)
        border_width = image_editor.get_by_role(
            "spinbutton", name="边框粗细", exact=True
        )
        border_inputs = image_editor.locator(".template-image-border-presence input")
        border_width.fill("3")
        border_width.press("Enter")
        record_border(image_editor)
        border_switch.press("Space")
        expect(border_switch).to_have_attribute("aria-checked", "false")
        expect(border_inputs).to_have_count(0)
        closing_frames = finish_border_recording()
        exiting = [
            frame
            for frame in closing_frames
            if not frame["checked"] and frame["inputs"] > 0
        ]
        if reduced_motion == "reduce":
            assert not exiting, closing_frames
            assert not any(frame["moving"] for frame in closing_frames), closing_frames
        else:
            assert any(
                frame["moving"] and 0 < frame["opacity"] < 1 for frame in exiting
            ), closing_frames
            assert all(
                frame["inert"]
                and frame["ariaHidden"] == "true"
                and frame["disabled"]
                and not frame["acceptedFocus"]
                and frame["width"] == "3"
                and frame["borderWidth"] == 0
                for frame in exiting
            ), exiting

        record_border(image_editor)
        border_switch.press("Space")
        expect(border_width).to_be_enabled()
        page.wait_for_function(
            """editor => !editor.querySelector('.template-image-border-presence')
              .getAnimations().some(animation => animation.playState === 'running')""",
            arg=image_editor.element_handle(),
        )
        opening_frames = finish_border_recording()
        assert any(frame["checked"] and frame["inputs"] > 0 for frame in opening_frames)
        if reduced_motion == "reduce":
            assert not any(frame["moving"] for frame in opening_frames), opening_frames
        else:
            assert any(
                frame["checked"] and frame["moving"] and 0 < frame["opacity"] < 1
                for frame in opening_frames
            ), opening_frames

        border_width.fill("3")
        border_width.press("Enter")
        record_border(image_editor, reverse=True)
        border_switch.press("Space")
        page.wait_for_function(
            """editor => window.__templateBorderRecording.reversed
              && editor.querySelector('[role="switch"]').getAttribute('aria-checked')
                === 'true'
              && !editor.querySelector('.template-image-border-presence')
                .getAnimations().some(animation => animation.playState === 'running')
            """,
            arg=image_editor.element_handle(),
        )
        reversed_frames = finish_border_recording()
        assert any(not frame["checked"] for frame in reversed_frames), reversed_frames
        expect(border_width).to_be_visible()
        expect(border_width).to_be_enabled()
        expect(border_width).to_have_value("1")
        border_width.focus()
        expect(border_width).to_be_focused()
        expect(image_editor.get_by_label("边框颜色", exact=True)).to_be_enabled()
        final_frame = reversed_frames[-1]
        assert final_frame["checked"] and final_frame["rendered"], final_frame
        assert final_frame["opacity"] == 1 and not final_frame["inert"], final_frame
        assert final_frame["ariaHidden"] == "false", final_frame
        content = image_editor.locator(
            '[data-slot="template-image-card-content"]'
        ).element_handle()
        assert content is not None
        collapse.focus()
        page.keyboard.press("Enter")
        for _ in range(3):
            page.keyboard.press("Tab")
            assert not content.evaluate(
                "element => element.contains(document.activeElement)"
            )
        expect(x_input).to_be_hidden()
        expand = image_editor.get_by_role("button", name="展开图片设置", exact=True)
        expand.focus()
        page.keyboard.press("Enter")
        expect(x_input).to_be_visible()
        expect(border_width).to_have_value("1")
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/templates/{template_id}"
                and response.request.post_data_json["saveMode"] == "checkpoint"
            )
        ) as saved:
            page.keyboard.press("ControlOrMeta+s")
        assert saved.value.ok
        assert (
            saved.value.request.post_data_json["template"]["layout"]["images"][0][
                "objectFit"
            ]
            == "cover"
        )
        assert (
            saved.value.request.post_data_json["template"]["layout"]["images"][0][
                "borderWidth"
            ]
            == 1
        )
    finally:
        page.close()
        if template_id:
            response = context.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if response.ok:
                context.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


@pytest.mark.browser_smoke
def test_template_image_drag_near_page_edge_persists_without_repositioning(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 2048, "height": 1226}
    )
    page = context.new_page()
    template_id: str | None = None

    def get_image_frame():
        preview_page = page.locator('[data-export-root="resume-page"]:visible').last
        image_frame = preview_page.locator('[data-template-image-frame="true"]').first
        image_frame.wait_for(state="visible")
        return image_frame

    def get_rendered_left_mm() -> float:
        return get_image_frame().evaluate(
            "(element) => Number.parseFloat(element.style.left)"
        )

    def drag_image_to_x(target_x: float) -> None:
        geometry = get_image_frame().evaluate(
            """
            (element) => {
              const frame = element.getBoundingClientRect();
              const resumePage = element.closest('[data-export-root="resume-page"]');
              const pageRect = resumePage.getBoundingClientRect();
              return {
                centerX: frame.left + frame.width / 2,
                centerY: frame.top + frame.height / 2,
                currentX: Number.parseFloat(element.style.left),
                pxPerMm: pageRect.width / 210,
              };
            }
            """
        )

        page.mouse.move(geometry["centerX"], geometry["centerY"])
        page.mouse.down()
        page.mouse.move(
            geometry["centerX"]
            + (target_x - geometry["currentX"]) * geometry["pxPerMm"],
            geometry["centerY"],
            steps=20,
        )
        page.mouse.up()

    def assert_x_control_value(expected: float) -> None:
        x_input = page.get_by_role("spinbutton", name="横向位置", exact=True)
        assert float(x_input.input_value()) == expected

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="创建副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        page.get_by_title("内置模板 · 只读", exact=True).wait_for(state="hidden")
        template_id = urlparse(page.url).path.rsplit("/", maxsplit=1)[-1]

        page.get_by_role("tab", name="装饰", exact=True).click()
        page.get_by_role(
            "button",
            name="添加图片占位符",
            exact=True,
        ).click()

        image_editor = page.get_by_role("group", name="图片元素 1", exact=True)
        image_editor.get_by_text("图片 1", exact=True).wait_for(state="visible")
        assert (
            image_editor.get_by_role("textbox", name="图片名称", exact=True).count()
            == 0
        )

        def edit_image_name() -> None:
            image_editor.get_by_role("button", name="更多操作", exact=True).click()
            page.get_by_role("menuitem", name="编辑图片名称", exact=True).click()

        edit_image_name()
        image_name_input = image_editor.get_by_role(
            "textbox", name="图片名称", exact=True
        )
        assert image_name_input.input_value() == "图片 1"
        image_name_input.fill("临时名称")
        image_name_input.press("Escape")
        image_name_input.wait_for(state="hidden")
        image_editor.get_by_text("图片 1", exact=True).wait_for(state="visible")
        edit_image_name()
        image_name_input = image_editor.get_by_role(
            "textbox", name="图片名称", exact=True
        )
        image_name_input.fill("头像")
        image_name_input.press("Enter")
        image_name_input.wait_for(state="hidden")
        image_editor.get_by_text("头像", exact=True).wait_for(state="visible")
        expect(
            image_editor.locator('[data-slot="template-image-thumbnail"]')
        ).to_have_count(0)
        editor_widths = image_editor.evaluate(
            """
            (element) => ({
              clientWidth: element.clientWidth,
              scrollWidth: element.scrollWidth,
            })
            """
        )
        assert editor_widths["scrollWidth"] <= editor_widths["clientWidth"] + 1
        upload_button = page.get_by_role("button", name="上传图片", exact=True)
        upload_button.wait_for(state="visible")
        header = image_editor.locator('[data-slot="template-image-card-header"]')
        expect(
            header.get_by_role("button", name="上传图片", exact=True)
        ).to_be_visible()
        fit_group = image_editor.get_by_role("tablist", name="适配方式", exact=True)
        contain = fit_group.get_by_role("tab", name="完整显示", exact=True)
        cover = fit_group.get_by_role("tab", name="填满裁剪", exact=True)
        expect(contain).to_have_attribute("aria-selected", "true")
        contain.focus()
        contain.press("ArrowRight")
        expect(cover).to_be_focused()
        expect(cover).to_have_attribute("aria-selected", "true")
        cover.press("ArrowLeft")
        expect(contain).to_be_focused()
        expect(contain).to_have_attribute("aria-selected", "true")

        image_editor.locator('input[type="file"]').set_input_files(
            {
                "name": "头像.svg",
                "mimeType": "image/svg+xml",
                "buffer": (
                    b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
                ),
            }
        )
        uploaded_thumbnail = image_editor.locator(
            '[data-slot="template-image-thumbnail"] img'
        )
        uploaded_thumbnail.wait_for(state="visible")
        assert uploaded_thumbnail.get_attribute("src").startswith(
            "data:image/svg+xml;base64,"
        )
        image_editor.get_by_role("button", name="替换图片", exact=True).wait_for(
            state="visible"
        )

        x_input = page.get_by_role("spinbutton", name="横向位置", exact=True)
        y_input = page.get_by_role("spinbutton", name="纵向位置", exact=True)
        width_input = page.get_by_role("spinbutton", name="宽度", exact=True)
        height_input = page.get_by_role("spinbutton", name="高度", exact=True)
        x_input.fill("166")
        x_input.press("Enter")

        numeric_field_geometries = []
        for numeric_input in (x_input, y_input, width_input, height_input):
            expect(numeric_input).to_be_visible()
            assert (
                numeric_input.evaluate(
                    "(element) => getComputedStyle(element).appearance"
                )
                == "textfield"
            )
            numeric_field_geometries.append(
                numeric_input.evaluate(
                    """
                element => {
                  const group = element.closest('[data-slot="input-group"]');
                  const rect = group.getBoundingClientRect();
                  return { left: rect.left, right: rect.right, top: rect.top };
                }
                """
                )
            )
        for upper, lower in (
            (numeric_field_geometries[0], numeric_field_geometries[2]),
            (numeric_field_geometries[1], numeric_field_geometries[3]),
        ):
            assert upper["left"] == pytest.approx(lower["left"], abs=1)
            assert upper["right"] == pytest.approx(lower["right"], abs=1)
        for left, right in (
            (numeric_field_geometries[0], numeric_field_geometries[1]),
            (numeric_field_geometries[2], numeric_field_geometries[3]),
        ):
            assert left["top"] == pytest.approx(right["top"], abs=1)
            assert left["right"] < right["left"]

        assert x_input.get_attribute("max") == "180"
        assert y_input.get_attribute("max") == "277"
        assert width_input.get_attribute("max") == "44"
        assert height_input.get_attribute("max") == "120"

        assert (
            image_editor.get_by_role("button", name="锁定宽高比", exact=True).count()
            == 0
        )
        assert (
            image_editor.get_by_role(
                "button", name="解除宽高比锁定", exact=True
            ).count()
            == 0
        )
        width_input.fill("36")
        width_input.press("Enter")
        assert float(width_input.input_value()) == 36
        assert float(height_input.input_value()) == 20
        width_input.fill("30")
        width_input.press("Enter")
        assert float(height_input.input_value()) == 20

        assert image_editor.get_by_role("button", name="外观", exact=True).count() == 0
        appearance = image_editor.get_by_role("group", name="外观", exact=True)
        expect(appearance).to_be_visible()
        opacity_slider = appearance.get_by_role("slider", name="不透明度", exact=True)
        opacity_slider.wait_for(state="visible")
        assert opacity_slider.get_attribute("aria-valuetext") == "100%"
        opacity_input = appearance.get_by_role(
            "spinbutton", name="不透明度", exact=True
        )
        opacity_input.wait_for(state="visible")
        assert opacity_input.input_value() == "100"
        assert (
            opacity_input.evaluate("(element) => getComputedStyle(element).appearance")
            == "textfield"
        )
        opacity_input.fill("")
        assert opacity_input.input_value() == ""
        opacity_input.type("75")
        opacity_input.press("Enter")
        assert opacity_input.input_value() == "75"
        assert opacity_slider.get_attribute("aria-valuenow") == "0.75"
        assert opacity_slider.get_attribute("aria-valuetext") == "75%"
        opacity_row_geometry = opacity_slider.evaluate(
            """
            (element) => {
              const row = element.closest(
                '[data-slot="template-image-slider-field"]'
              );
              const label = row?.querySelector('[data-slot="field-label"]');
              const slider = row?.querySelector('[data-slot="slider"]');
              const value = row?.querySelector(
                '[data-template-image-slider-value="true"]'
              );
              if (!row || !label || !slider || !value) {
                throw new Error('Compact opacity row is incomplete.');
              }
              const labelRect = label.getBoundingClientRect();
              const sliderRect = slider.getBoundingClientRect();
              const valueRect = value.getBoundingClientRect();
              return {
                labelRight: labelRect.right,
                labelCenterY: labelRect.top + labelRect.height / 2,
                sliderLeft: sliderRect.left,
                sliderRight: sliderRect.right,
                sliderCenterY: sliderRect.top + sliderRect.height / 2,
                valueLeft: valueRect.left,
                valueCenterY: valueRect.top + valueRect.height / 2,
                valueWidth: valueRect.width,
                valueText: value.querySelector('input')?.value,
              };
            }
            """
        )
        assert opacity_row_geometry["labelRight"] < (opacity_row_geometry["sliderLeft"])
        assert opacity_row_geometry["sliderRight"] < (opacity_row_geometry["valueLeft"])
        assert (
            abs(
                opacity_row_geometry["labelCenterY"]
                - opacity_row_geometry["sliderCenterY"]
            )
            <= 2
        )
        assert (
            abs(
                opacity_row_geometry["sliderCenterY"]
                - opacity_row_geometry["valueCenterY"]
            )
            <= 2
        )
        assert opacity_row_geometry["valueWidth"] <= 120
        assert opacity_row_geometry["valueText"] == "75"

        border_radius_input = image_editor.get_by_role(
            "spinbutton", name="圆角", exact=True
        )
        radius_slider = image_editor.get_by_role("slider", name="圆角", exact=True)
        expect(radius_slider).to_be_visible()
        border_radius_input.fill("12")
        border_radius_input.press("Enter")
        expect(radius_slider).to_have_attribute("aria-valuenow", "12")

        border_switch = image_editor.get_by_role("switch", name="边框", exact=True)
        assert border_switch.get_attribute("aria-checked") == "true"
        border_width_input = image_editor.get_by_role(
            "spinbutton", name="边框粗细", exact=True
        )
        border_color_input = image_editor.get_by_label("边框颜色", exact=True)
        border_width_input.wait_for(state="visible")
        border_color_input.wait_for(state="visible")

        def field_geometry(control):
            return control.evaluate(
                """
                (element) => {
                  const rect = element.closest(
                    '[data-slot="field"]'
                  ).getBoundingClientRect();
                  return { top: rect.top, left: rect.left };
                }
                """
            )

        border_width_geometry = field_geometry(border_width_input)
        border_color_geometry = field_geometry(border_color_input)
        assert border_width_geometry["top"] == pytest.approx(
            border_color_geometry["top"], abs=1
        )
        assert border_color_geometry["left"] < border_width_geometry["left"]
        image_editor.locator("label").filter(has_text=re.compile(r"^边框$")).click()
        expect(border_switch).to_have_attribute("aria-checked", "false")
        expect(border_width_input).to_be_hidden()
        expect(border_color_input).to_be_hidden()
        border_switch.click()
        expect(border_switch).to_have_attribute("aria-checked", "true")
        expect(border_width_input).to_be_visible()
        expect(border_color_input).to_be_visible()
        border_switch.click()
        assert border_switch.get_attribute("aria-checked") == "false"
        border_width_input.wait_for(state="hidden")
        border_color_input.wait_for(state="hidden")

        expanded_editor_widths = image_editor.evaluate(
            """
            (element) => ({
              clientWidth: element.clientWidth,
              scrollWidth: element.scrollWidth,
            })
            """
        )
        assert (
            expanded_editor_widths["scrollWidth"]
            <= expanded_editor_widths["clientWidth"] + 1
        )

        assert get_rendered_left_mm() == 166
        drag_image_to_x(16.5)
        assert get_rendered_left_mm() == 16.5
        drag_image_to_x(15.5)
        assert get_rendered_left_mm() == 15.5
        assert_x_control_value(15.5)
        assert width_input.get_attribute("max") == "120"

        x_input.fill("12")
        x_input.press("Enter")
        assert get_rendered_left_mm() == 12
        x_input.fill("15.5")
        x_input.press("Enter")
        assert get_rendered_left_mm() == 15.5

        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/templates/{template_id}"
            )
        ) as save_response_info:
            page.keyboard.press("Control+S")

        save_response = save_response_info.value
        assert save_response.ok
        save_payload = save_response.request.post_data_json
        saved_images = save_payload["template"]["layout"]["images"]
        assert len(saved_images) == 1
        assert saved_images[0]["name"] == "头像"
        assert saved_images[0]["x"] == 15.5
        assert saved_images[0]["y"] == 18
        assert saved_images[0]["opacity"] == 0.75
        assert saved_images[0]["borderWidth"] == 0
        assert saved_images[0]["borderRadius"] == 12
        assert saved_images[0]["objectFit"] == "contain"
        assert saved_images[0]["src"].startswith("data:image/svg+xml;base64,")

        page.reload(wait_until="networkidle")
        page.get_by_role("tab", name="装饰", exact=True).click()
        assert get_rendered_left_mm() == 15.5

        first_image_editor = page.get_by_role("group", name="图片元素 1", exact=True)
        first_image_editor.get_by_text("头像", exact=True).wait_for(state="visible")
        single_expand_button = first_image_editor.get_by_role(
            "button", name="展开图片设置", exact=True
        )
        assert single_expand_button.get_attribute("aria-expanded") == "false"
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="hidden")
        single_expand_button.focus()
        page.keyboard.press("Enter")
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="visible")
        assert_x_control_value(15.5)
        assert (
            first_image_editor.get_by_role("button", name="外观", exact=True).count()
            == 0
        )
        persisted_appearance = first_image_editor.get_by_role(
            "group", name="外观", exact=True
        )
        expect(persisted_appearance).to_be_visible()
        persisted_opacity_input = persisted_appearance.get_by_role(
            "spinbutton", name="不透明度", exact=True
        )
        expect(persisted_opacity_input).to_be_visible()
        expect(persisted_opacity_input).to_have_value("75")
        persisted_border_switch = first_image_editor.get_by_role(
            "switch", name="边框", exact=True
        )
        assert persisted_border_switch.get_attribute("aria-checked") == "false"
        first_image_editor.get_by_role(
            "spinbutton", name="边框粗细", exact=True
        ).wait_for(state="hidden")
        first_image_editor.get_by_label("边框颜色", exact=True).wait_for(state="hidden")
        first_image_editor.evaluate(
            """
            (element) => Promise.all(
              element.getAnimations({ subtree: true }).map(
                (animation) => animation.finished
              )
            )
            """
        )
        panel_geometry = first_image_editor.evaluate(
            """
            element => {
              const root = element.getBoundingClientRect();
              const header = element.querySelector(
                '[data-slot="template-image-card-header"]'
              ).getBoundingClientRect();
              const content = element.querySelector(
                '[data-slot="template-image-card-content"]'
              ).getBoundingClientRect();
              return {
                containsHeader: root.top <= header.top && root.bottom >= header.bottom,
                containsContent:
                  root.top <= content.top && root.bottom >= content.bottom,
                overflows: element.scrollWidth > element.clientWidth + 1,
              };
            }
            """
        )
        assert panel_geometry == {
            "containsHeader": True,
            "containsContent": True,
            "overflows": False,
        }

        single_collapse_button = first_image_editor.get_by_role(
            "button", name="收起图片设置", exact=True
        )
        single_collapse_button.focus()
        page.keyboard.press("Space")
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="hidden")
        single_expand_button = first_image_editor.get_by_role(
            "button", name="展开图片设置", exact=True
        )
        assert single_expand_button.get_attribute("aria-expanded") == "false"
        single_expand_button.focus()
        page.keyboard.press("Enter")
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="visible")

        page.get_by_role("button", name="添加图片占位符", exact=True).click()
        first_image_editor = page.get_by_role("group", name="图片元素 1", exact=True)
        second_image_editor = page.get_by_role("group", name="图片元素 2", exact=True)
        second_image_editor.get_by_text("图片 1", exact=True).wait_for(state="visible")
        first_expand_button = first_image_editor.get_by_role(
            "button", name="展开图片设置", exact=True
        )
        second_collapse_button = second_image_editor.get_by_role(
            "button", name="收起图片设置", exact=True
        )
        assert first_expand_button.get_attribute("aria-expanded") == "false"
        assert second_collapse_button.get_attribute("aria-expanded") == "true"
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="hidden")
        second_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="visible")

        first_expand_button.focus()
        page.keyboard.press("Enter")
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="visible")
        assert (
            first_image_editor.get_by_role(
                "button", name="收起图片设置", exact=True
            ).get_attribute("aria-expanded")
            == "true"
        )
        second_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="hidden")
        second_expand_button = second_image_editor.get_by_role(
            "button", name="展开图片设置", exact=True
        )
        assert second_expand_button.get_attribute("aria-expanded") == "false"

        second_expand_button.focus()
        page.keyboard.press("Enter")
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="hidden")
        second_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="visible")

        second_image_editor.get_by_role("button", name="更多操作", exact=True).click()
        page.get_by_role("menuitem", name="删除图片", exact=True).click()
        remaining_expand_button = first_image_editor.get_by_role(
            "button", name="展开图片设置", exact=True
        )
        assert remaining_expand_button.get_attribute("aria-expanded") == "false"
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="hidden")
    finally:
        if not page.is_closed():
            page.close()
        if template_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


@pytest.mark.browser_smoke
def test_empty_template_image_placeholder_only_renders_in_template_preview(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 960}
    )
    page = context.new_page()
    template_id: str | None = None
    resume_id: str | None = None

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="创建副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        page.get_by_title("内置模板 · 只读", exact=True).wait_for(state="hidden")
        template_id = urlparse(page.url).path.rsplit("/", maxsplit=1)[-1]

        page.get_by_role("tab", name="装饰", exact=True).click()
        page.get_by_role(
            "button",
            name="添加图片占位符",
            exact=True,
        ).click()

        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/templates/{template_id}"
            )
        ) as save_response_info:
            page.keyboard.press("Control+S")

        save_response = save_response_info.value
        assert save_response.ok
        saved_template_payload = save_response.request.post_data_json
        template_preview = page.locator('[data-export-root="resume-page"]:visible').last
        template_placeholder = template_preview.locator(
            '[data-template-image-frame="true"]'
        )
        assert template_placeholder.count() == 1
        assert template_placeholder.locator("img").count() == 0
        assert template_placeholder.get_by_text("图片 1", exact=True).count() == 1

        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": "Empty template image placeholder regression",
                "template": template_id,
            },
        )
        assert create_response.ok
        resume_id = create_response.json()["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        resume_preview = page.locator('[data-export-root="resume-page"]:visible').first
        resume_preview.wait_for(state="visible")
        empty_resume_frame_count = resume_preview.locator(
            '[data-template-image-frame="true"]'
        ).count()

        page.goto(
            f"{frontend_url}/pdf-export?resumeId={resume_id}&documentLocale=zh",
            wait_until="networkidle",
        )
        page.locator('main[data-pdf-ready="true"]').wait_for(state="visible")
        empty_export_frame_count = page.locator(
            '[data-export-root="resume-page"]:visible '
            '[data-template-image-frame="true"]'
        ).count()

        assert empty_resume_frame_count == 0
        assert empty_export_frame_count == 0

        saved_images = saved_template_payload["template"]["layout"]["images"]
        assert len(saved_images) == 1
        assert saved_images[0]["src"] == ""

        image_data_url = (
            "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
        )
        saved_template_payload["template"]["layout"]["images"] = [
            {**saved_images[0], "src": image_data_url}
        ]
        update_response = page.request.put(
            f"{frontend_url}/api/templates/{template_id}",
            data=saved_template_payload,
        )
        assert update_response.ok

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        resume_preview = page.locator('[data-export-root="resume-page"]:visible').first
        rendered_image_frame = resume_preview.locator(
            '[data-template-image-frame="true"]'
        )
        rendered_image = rendered_image_frame.locator("img")
        assert rendered_image_frame.count() == 1
        assert rendered_image.count() == 1
        expect(page.locator("[data-template-image-resize-handle]")).to_have_count(0)
        assert rendered_image.evaluate(
            "(image) => image.complete && image.naturalWidth > 0"
        )

        page.goto(
            f"{frontend_url}/pdf-export?resumeId={resume_id}&documentLocale=zh",
            wait_until="networkidle",
        )
        page.locator('main[data-pdf-ready="true"]').wait_for(state="visible")
        exported_image = page.locator(
            '[data-export-root="resume-page"]:visible '
            '[data-template-image-frame="true"] img'
        )
        assert exported_image.count() == 1
        expect(page.locator("[data-template-image-resize-handle]")).to_have_count(0)
        assert exported_image.evaluate(
            "(image) => image.complete && image.naturalWidth > 0"
        )
    finally:
        if not page.is_closed():
            page.close()
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        if template_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()
