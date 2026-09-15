from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


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
            name="创建可编辑副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        page.get_by_text("内置模板 · 只读", exact=True).wait_for(state="hidden")
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
        edit_name_button = image_editor.get_by_role(
            "button", name="编辑图片名称", exact=True
        )
        edit_name_button.click()
        image_name_input = image_editor.get_by_role(
            "textbox", name="图片名称", exact=True
        )
        assert image_name_input.input_value() == "图片 1"
        image_name_input.fill("临时名称")
        image_name_input.press("Escape")
        image_name_input.wait_for(state="hidden")
        image_editor.get_by_text("图片 1", exact=True).wait_for(state="visible")
        edit_name_button.click()
        image_name_input = image_editor.get_by_role(
            "textbox", name="图片名称", exact=True
        )
        image_name_input.fill("头像")
        image_name_input.press("Enter")
        image_name_input.wait_for(state="hidden")
        image_editor.get_by_text("头像", exact=True).wait_for(state="visible")
        assert (
            image_editor.locator('[data-slot="template-image-thumbnail"]')
            .inner_text()
            .strip()
            == ""
        )
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
        source_label = image_editor.get_by_text("图片来源", exact=True)
        source_label.wait_for(state="visible")
        fit_label = image_editor.get_by_text("适配方式", exact=True)
        fit_label.wait_for(state="visible")
        fit_select = page.get_by_role("combobox", name="适配方式", exact=True)
        fit_select.wait_for(state="visible")
        source_label_box = source_label.bounding_box()
        fit_label_box = fit_label.bounding_box()
        upload_button_box = upload_button.bounding_box()
        fit_select_box = fit_select.bounding_box()
        assert source_label_box is not None
        assert fit_label_box is not None
        assert upload_button_box is not None
        assert fit_select_box is not None
        assert (
            image_editor.get_by_role("button", name="图片 URL", exact=True).count() == 0
        )
        assert page.get_by_role("dialog", name="图片 URL", exact=True).count() == 0
        assert source_label_box["x"] + source_label_box["width"] <= (
            upload_button_box["x"] + 1
        )
        assert fit_label_box["x"] + fit_label_box["width"] <= (fit_select_box["x"] + 1)
        assert (
            abs(
                source_label_box["y"]
                + source_label_box["height"] / 2
                - upload_button_box["y"]
                - upload_button_box["height"] / 2
            )
            <= 2
        )
        assert (
            abs(
                fit_label_box["y"]
                + fit_label_box["height"] / 2
                - fit_select_box["y"]
                - fit_select_box["height"] / 2
            )
            <= 2
        )
        assert fit_label_box["y"] >= (
            source_label_box["y"] + source_label_box["height"]
        )
        assert (
            abs(
                upload_button_box["x"]
                + upload_button_box["width"]
                - fit_select_box["x"]
                - fit_select_box["width"]
            )
            <= 2
        )

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

        for field_label in (
            "横向位置",
            "纵向位置",
            "宽度",
            "高度",
        ):
            image_editor.get_by_text(field_label, exact=True).wait_for(state="visible")

        assert image_editor.get_by_text("图片宽度", exact=True).count() == 0
        assert image_editor.get_by_text("图片高度", exact=True).count() == 0
        assert image_editor.get_by_text("位置", exact=True).count() == 0
        assert image_editor.get_by_text("尺寸", exact=True).count() == 0

        numeric_field_geometries = []
        for numeric_input in (
            x_input,
            y_input,
            width_input,
            height_input,
        ):
            assert (
                numeric_input.evaluate(
                    "(element) => getComputedStyle(element).appearance"
                )
                == "textfield"
            )
            inline_field_geometry = numeric_input.evaluate(
                """
                (element) => {
                  const field = element.closest('[data-slot="field"]');
                  const label = field?.querySelector('[data-slot="field-label"]');
                  const inputGroup = element.closest('[data-slot="input-group"]');
                  if (!label || !inputGroup) {
                    throw new Error('Inline numeric field is incomplete.');
                  }
                  const labelRect = label.getBoundingClientRect();
                  const inputRect = inputGroup.getBoundingClientRect();
                  return {
                    fieldLeft: field.getBoundingClientRect().left,
                    fieldTop: field.getBoundingClientRect().top,
                    labelRight: labelRect.right,
                    labelCenterY: labelRect.top + labelRect.height / 2,
                    inputLeft: inputRect.left,
                    inputRight: inputRect.right,
                    inputCenterY: inputRect.top + inputRect.height / 2,
                    inputWidth: inputRect.width,
                  };
                }
                """
            )
            numeric_field_geometries.append(inline_field_geometry)
            assert inline_field_geometry["labelRight"] <= (
                inline_field_geometry["inputLeft"] + 1
            )
            assert (
                abs(
                    inline_field_geometry["labelCenterY"]
                    - inline_field_geometry["inputCenterY"]
                )
                <= 2
            )
            assert inline_field_geometry["inputWidth"] <= 120

        for upper, lower in (
            (numeric_field_geometries[0], numeric_field_geometries[2]),
            (numeric_field_geometries[1], numeric_field_geometries[3]),
        ):
            assert abs(upper["fieldLeft"] - lower["fieldLeft"]) <= 1
            assert abs(upper["inputLeft"] - lower["inputLeft"]) <= 1
            assert abs(upper["inputRight"] - lower["inputRight"]) <= 1

        for left, right in (
            (numeric_field_geometries[0], numeric_field_geometries[1]),
            (numeric_field_geometries[2], numeric_field_geometries[3]),
        ):
            assert abs(left["fieldTop"] - right["fieldTop"]) <= 1

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

        assert image_editor.locator('[data-slot="separator"]').count() == 0

        assert image_editor.get_by_role("button", name="外观", exact=True).count() == 0
        image_editor.get_by_text("外观", exact=True).wait_for(state="visible")
        opacity_slider = page.get_by_role("slider", name="不透明度", exact=True)
        opacity_slider.wait_for(state="visible")
        assert opacity_slider.get_attribute("aria-valuetext") == "100%"
        opacity_input = image_editor.get_by_role(
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
        radius_row_geometry = border_radius_input.evaluate(
            """
            (element) => {
              const field = element.closest('[data-slot="field"]');
              const label = field?.querySelector('[data-slot="field-label"]');
              const input = element.closest('[data-slot="input-group"]');
              if (!field || !label || !input) {
                throw new Error('Compact radius row is incomplete.');
              }
              const labelRect = label.getBoundingClientRect();
              const inputRect = input.getBoundingClientRect();
              return {
                labelRight: labelRect.right,
                labelCenterY: labelRect.top + labelRect.height / 2,
                inputLeft: inputRect.left,
                inputCenterY: inputRect.top + inputRect.height / 2,
                inputWidth: inputRect.width,
              };
            }
            """
        )
        assert radius_row_geometry["labelRight"] < (radius_row_geometry["inputLeft"])
        assert (
            abs(
                radius_row_geometry["labelCenterY"]
                - radius_row_geometry["inputCenterY"]
            )
            <= 2
        )
        assert radius_row_geometry["inputWidth"] <= 120

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

        radius_geometry = field_geometry(border_radius_input)
        border_width_geometry = field_geometry(border_width_input)
        border_geometry = field_geometry(border_switch)
        border_color_geometry = field_geometry(border_color_input)
        assert abs(radius_geometry["top"] - border_width_geometry["top"]) <= 1
        assert radius_geometry["left"] < border_width_geometry["left"]
        assert abs(border_geometry["top"] - border_color_geometry["top"]) <= 1
        assert border_geometry["left"] < border_color_geometry["left"]
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

        x_label_box = page.get_by_text("横向位置", exact=True).bounding_box()
        assert x_label_box is not None
        assert x_label_box["width"] >= 50
        assert x_label_box["height"] <= 24

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
        first_image_editor.get_by_text("外观", exact=True).wait_for(state="visible")
        assert (
            first_image_editor.get_by_role(
                "spinbutton", name="不透明度", exact=True
            ).input_value()
            == "75"
        )
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
        card_style = first_image_editor.evaluate(
            """
            (element) => {
              const cardReference = document.createElement("div");
              cardReference.className = "rounded-lg bg-muted/35 shadow-xs";
              cardReference.style.position = "fixed";
              cardReference.style.visibility = "hidden";
              const transparentReference = document.createElement("div");
              transparentReference.style.position = "fixed";
              transparentReference.style.visibility = "hidden";
              document.body.append(cardReference, transparentReference);

              const actual = getComputedStyle(element);
              const headerElement = element.querySelector(
                '[data-slot="template-image-card-header"]'
              );
              const contentElement = element.querySelector(
                '[data-slot="template-image-card-content"]'
              );
              const header = getComputedStyle(headerElement);
              const content = getComputedStyle(contentElement);
              const expectedCard = getComputedStyle(cardReference);
              const expectedTransparent = getComputedStyle(
                transparentReference
              );
              const rootRect = element.getBoundingClientRect();
              const headerRect = headerElement.getBoundingClientRect();
              const contentRect = contentElement.getBoundingClientRect();
              const result = {
                borderWidths: [
                  actual.borderTopWidth,
                  actual.borderRightWidth,
                  actual.borderBottomWidth,
                  actual.borderLeftWidth,
                ],
                backgroundColor: actual.backgroundColor,
                borderRadius: actual.borderRadius,
                boxShadow: actual.boxShadow,
                headerBackgroundColor: header.backgroundColor,
                contentBackgroundColor: content.backgroundColor,
                headerBoxShadow: header.boxShadow,
                contentBoxShadow: content.boxShadow,
                containsHeader:
                  rootRect.top <= headerRect.top + 1 &&
                  rootRect.bottom >= headerRect.bottom - 1,
                containsContent:
                  rootRect.top <= contentRect.top + 1 &&
                  rootRect.bottom >= contentRect.bottom - 1,
                expectedBackgroundColor: expectedCard.backgroundColor,
                expectedTransparentBackgroundColor:
                  expectedTransparent.backgroundColor,
                expectedBorderRadius: expectedCard.borderRadius,
                expectedBoxShadow: expectedCard.boxShadow,
              };

              cardReference.remove();
              transparentReference.remove();
              return result;
            }
            """
        )
        assert set(card_style["borderWidths"]) == {"0px"}
        assert card_style["backgroundColor"] == card_style["expectedBackgroundColor"]
        assert card_style["borderRadius"] == card_style["expectedBorderRadius"]
        assert card_style["boxShadow"] == card_style["expectedBoxShadow"]
        assert card_style["boxShadow"] != "none"
        assert (
            card_style["headerBackgroundColor"]
            == card_style["expectedTransparentBackgroundColor"]
        )
        assert (
            card_style["contentBackgroundColor"]
            == card_style["expectedTransparentBackgroundColor"]
        )
        assert card_style["headerBoxShadow"] == "none"
        assert card_style["contentBoxShadow"] == "none"
        assert card_style["containsHeader"] is True
        assert card_style["containsContent"] is True

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

        second_image_editor.get_by_role("button", name="删除图片", exact=True).click()
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
            name="创建可编辑副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        page.get_by_text("内置模板 · 只读", exact=True).wait_for(state="hidden")
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
