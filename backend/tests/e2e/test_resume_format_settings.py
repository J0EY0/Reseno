from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, expect

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_format_popover_focuses_template_without_opening_defaults_tooltip(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        format_button = page.get_by_role("button", name="格式", exact=True)
        format_button.click()

        template_select = page.get_by_role(
            "combobox",
            name="应用模板",
            exact=True,
        )
        page.wait_for_timeout(250)

        assert template_select.evaluate("element => element === document.activeElement")
        assert not page.get_by_role(
            "tooltip",
            name="当前已是模板默认设置",
        ).is_visible()
    finally:
        context.close()


def test_format_popover_font_options_stay_on_one_line(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role("button", name="格式", exact=True).click()
        font_select = page.get_by_role("combobox", name="字体", exact=True)
        font_select.click()

        option = page.get_by_role("option", name="Times New Roman", exact=True)
        expect(option).to_be_visible()
        line_count = option.evaluate(
            """
            element => {
              const walker = document.createTreeWalker(
                element,
                NodeFilter.SHOW_TEXT,
              );
              let node;
              while ((node = walker.nextNode())) {
                if (node.textContent?.trim() !== 'Times New Roman') continue;
                const range = document.createRange();
                range.selectNodeContents(node);
                return new Set(
                  Array.from(range.getClientRects(), rect => Math.round(rect.top)),
                ).size;
              }
              return 0;
            }
            """
        )
        assert line_count == 1

        option.click()
        value = font_select.locator('[data-slot="select-value"]')
        expect(value).to_have_text("Times New Roman")
        assert value.evaluate(
            "element => element.scrollWidth <= element.clientWidth + 1"
        )
    finally:
        context.close()


def test_format_reset_restores_current_template_defaults_and_persists(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()
    resume_id: str | None = None

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": "Template defaults reset regression",
                "template": "classic",
                "typography": {"fontFamily": "inter", "fontSize": 20},
                "templateSettings": {
                    "pagePaddingX": 8,
                    "bodyLineHeight": 2.2,
                },
            },
        )
        assert create_response.ok
        create_payload = create_response.json()
        assert create_payload["code"] == 0
        resume_id = create_payload["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role("button", name="格式", exact=True).click()

        reset_button = page.get_by_role(
            "button",
            name="恢复当前模板的默认设置",
            exact=True,
        )
        template_select = page.get_by_role(
            "combobox",
            name="应用模板",
            exact=True,
        )
        font_select = page.get_by_role("combobox", name="字体", exact=True)
        page_margin_input = page.get_by_role(
            "textbox",
            name="页边距",
            exact=True,
        )

        assert not reset_button.is_disabled()
        assert "Inter" in font_select.inner_text()
        assert page_margin_input.input_value() == "8"
        reset_bounds = reset_button.bounding_box()
        template_select_bounds = template_select.bounding_box()
        assert reset_bounds is not None
        assert template_select_bounds is not None
        assert (
            template_select_bounds["x"] + template_select_bounds["width"]
            <= reset_bounds["x"]
        )

        reset_button.click()

        assert reset_button.is_disabled()
        assert "思源宋体" in font_select.inner_text()
        assert page_margin_input.input_value() == "14"
        page.mouse.move(0, 0)
        reset_button.locator("xpath=..").hover()
        tooltip = page.locator('[data-slot="tooltip-content"]')
        tooltip.get_by_text(
            "当前已是模板默认设置",
            exact=True,
        ).wait_for(state="visible")
        tooltip_geometry = tooltip.evaluate(
            """
            (element) => {
              const rect = element.getBoundingClientRect();
              const centerX = rect.left + rect.width / 2;
              const centerY = rect.top + rect.height / 2;
              const topElement = document.elementFromPoint(centerX, centerY);
              return {
                rect: {
                  top: rect.top,
                  right: rect.right,
                  bottom: rect.bottom,
                  left: rect.left,
                  width: rect.width,
                  height: rect.height,
                },
                viewport: {
                  width: window.innerWidth,
                  height: window.innerHeight,
                },
                isTopmost: Boolean(
                  topElement &&
                  (topElement === element || element.contains(topElement))
                ),
              };
            }
            """
        )
        assert tooltip_geometry["rect"]["top"] >= 0, tooltip_geometry
        assert (
            tooltip_geometry["rect"]["right"] <= tooltip_geometry["viewport"]["width"]
        ), tooltip_geometry
        assert tooltip_geometry["isTopmost"], tooltip_geometry

        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
            )
        ) as save_response_info:
            page.get_by_role("button", name="保存状态", exact=True).click()

        save_response = save_response_info.value
        assert save_response.ok
        save_payload = save_response.request.post_data_json
        assert save_payload["typography"] == {
            "fontFamily": "serif",
            "fontSize": 16,
        }
        assert save_payload["templateSettings"] is None

        page.reload(wait_until="networkidle")
        page.get_by_role("button", name="格式", exact=True).click()
        assert page.get_by_role(
            "button",
            name="恢复当前模板的默认设置",
            exact=True,
        ).is_disabled()
        assert (
            "思源宋体"
            in page.get_by_role(
                "combobox",
                name="字体",
                exact=True,
            ).inner_text()
        )
        assert (
            page.get_by_role(
                "textbox",
                name="页边距",
                exact=True,
            ).input_value()
            == "14"
        )
    finally:
        if resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()
