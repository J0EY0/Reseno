from __future__ import annotations

import os

import pytest
from playwright.sync_api import Browser, expect

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_document_canvas_defaults_to_and_remembers_manual_zoom(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )

        viewport = page.locator('[data-slot="document-canvas-viewport"]')
        viewport.wait_for(state="visible")
        actual_size = page.get_by_role(
            "button",
            name="实际大小",
            exact=True,
        )
        expect(actual_size).to_have_text("90%")

        page.get_by_role("button", name="放大", exact=True).click()
        expect(actual_size).to_have_text("100%")
        page.reload(wait_until="networkidle")
        expect(actual_size).to_have_text("100%")

        fit_to_width = page.get_by_role(
            "button",
            name="适合宽度",
            exact=True,
        )
        fit_to_width.click()
        fitted_scale = actual_size.inner_text()
        expect(fit_to_width).to_have_attribute("aria-pressed", "true")

        page.reload(wait_until="networkidle")
        expect(actual_size).to_have_text(fitted_scale)
        expect(fit_to_width).to_have_attribute("aria-pressed", "false")
    finally:
        context.close()


def test_resume_workspace_focus_does_not_draw_full_frame(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        skip_link = page.get_by_role("link", name="跳到主要内容", exact=True)
        page.keyboard.press("Tab")
        assert skip_link.evaluate("element => document.activeElement === element")
        assert skip_link.evaluate("element => element.matches(':focus-visible')")
        expect(skip_link).not_to_have_css("box-shadow", "none")

        page.keyboard.press("Enter")
        main_content = page.locator("#main-content")
        assert main_content.evaluate("element => document.activeElement === element")
        expect(main_content).to_have_css("outline-style", "none")

        page.locator(f'a[href="/resume/{resume_id}"]').click()
        page.wait_for_url(f"{frontend_url}/resume/{resume_id}")

        viewport = page.locator('[data-slot="document-canvas-viewport"]')
        viewport.wait_for(state="visible")
        assert main_content.evaluate("element => document.activeElement === element")

        page.keyboard.press("F1")
        assert main_content.evaluate("element => element.matches(':focus-visible')")
        expect(main_content).to_have_css("outline-style", "none")

        back_button = page.get_by_role("button", name="返回简历列表", exact=True)
        page.keyboard.press("Tab")
        assert back_button.evaluate("element => document.activeElement === element")
        assert back_button.evaluate("element => element.matches(':focus-visible')")
        expect(back_button).not_to_have_css("box-shadow", "none")

        viewport.click(position={"x": 8, "y": 8})

        assert viewport.evaluate("element => document.activeElement === element")
        expect(viewport).to_have_attribute("data-focus-origin", "pointer")
        expect(viewport).to_have_css("box-shadow", "none")

        actual_size = page.get_by_role(
            "button",
            name="实际大小",
            exact=True,
        )
        actual_size.click()
        expect(viewport).not_to_have_attribute("data-focus-origin", "pointer")

        page.keyboard.press("Tab")
        viewport.focus()
        assert viewport.evaluate("element => document.activeElement === element")
        assert viewport.evaluate("element => element.matches(':focus-visible')")
        expect(viewport).not_to_have_css("box-shadow", "none")

        page.locator("[data-document-canvas-paper]").click(position={"x": 8, "y": 8})
        expect(viewport).to_have_attribute("data-focus-origin", "pointer")
        expect(viewport).to_have_css("box-shadow", "none")

        actual_size.click()
        viewport_box = viewport.bounding_box()
        assert viewport_box is not None
        scroll_top = viewport.evaluate("element => element.scrollTop")
        page.mouse.move(viewport_box["x"] + 8, viewport_box["y"] + 160)
        page.mouse.down()
        page.mouse.move(
            viewport_box["x"] + 8,
            viewport_box["y"] + 80,
            steps=4,
        )
        page.mouse.up()
        assert viewport.evaluate("element => element.scrollTop") > scroll_top
        assert viewport.evaluate("element => document.activeElement === element")
        assert not viewport.evaluate("element => element.matches(':focus-visible')")

        current_scale = actual_size.inner_text()
        page.keyboard.press("Control+=")
        expect(actual_size).not_to_have_text(current_scale)
    finally:
        context.close()


def test_document_canvas_supports_trackpad_and_keyboard_zoom(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )

        viewport = page.locator('[data-slot="document-canvas-viewport"]')
        viewport.wait_for(state="visible")
        page.locator(
            '[data-slot="document-canvas-viewport"] '
            '[data-resume-pagination-ready="true"]'
        ).wait_for(state="visible")
        actual_size = page.get_by_role(
            "button",
            name="实际大小",
            exact=True,
        )
        actual_size.click()
        expect(actual_size).to_have_text("100%")

        plain_wheel_prevented = viewport.evaluate(
            """
            element => {
              const event = new WheelEvent('wheel', {
                bubbles: true,
                cancelable: true,
                deltaY: 100,
              });
              element.dispatchEvent(event);
              return event.defaultPrevented;
            }
            """
        )
        assert plain_wheel_prevented is False
        expect(actual_size).to_have_text("100%")

        viewport.evaluate(
            "element => { element.scrollTop = Math.min(220, element.scrollHeight); }"
        )
        viewport_box = viewport.bounding_box()
        assert viewport_box is not None
        gesture_point = {
            "clientX": viewport_box["x"] + viewport_box["width"] * 0.5,
            "clientY": viewport_box["y"] + viewport_box["height"] * 0.45,
        }
        anchor_before = page.evaluate(
            """
            point => {
              const paper = document.querySelector(
                '[data-document-canvas-paper]',
              );
              if (!(paper instanceof HTMLElement)) {
                throw new Error('Missing document canvas paper.');
              }
              const bounds = paper.getBoundingClientRect();
              return {
                ...point,
                paperXRatio: (point.clientX - bounds.left) / bounds.width,
                paperYRatio: (point.clientY - bounds.top) / bounds.height,
              };
            }
            """,
            gesture_point,
        )
        pinch_result = viewport.evaluate(
            """
            (element, point) => {
              const event = new WheelEvent('wheel', {
                bubbles: true,
                cancelable: true,
                clientX: point.clientX,
                clientY: point.clientY,
                ctrlKey: true,
                deltaY: -100,
              });
              const dispatched = element.dispatchEvent(event);
              return {
                defaultPrevented: event.defaultPrevented,
                dispatched,
              };
            }
            """,
            gesture_point,
        )
        assert pinch_result == {
            "defaultPrevented": True,
            "dispatched": False,
        }
        expect(actual_size).to_have_text("126%")

        anchor_after = page.evaluate(
            """
            anchor => {
              const paper = document.querySelector(
                '[data-document-canvas-paper]',
              );
              if (!(paper instanceof HTMLElement)) {
                throw new Error('Missing document canvas paper.');
              }
              const bounds = paper.getBoundingClientRect();
              return {
                x: bounds.left + bounds.width * anchor.paperXRatio,
                y: bounds.top + bounds.height * anchor.paperYRatio,
              };
            }
            """,
            anchor_before,
        )
        assert abs(anchor_after["x"] - anchor_before["clientX"]) <= 1
        assert abs(anchor_after["y"] - anchor_before["clientY"]) <= 1

        actual_size.press("Control+-")
        expect(actual_size).to_have_text("116%")
        actual_size.press("Control+0")
        expect(actual_size).to_have_text("100%")
        actual_size.press("Control+=")
        expect(actual_size).to_have_text("110%")
    finally:
        context.close()


@pytest.mark.parametrize("document_type", ["resume", "template"])
def test_document_canvas_safely_centers_small_documents(
    browser: Browser,
    workspace_servers: tuple[str, str],
    document_type: str,
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        document_path = (
            f"resume/{resume_id}" if document_type == "resume" else "template/minimal"
        )
        page.goto(
            f"{frontend_url}/{document_path}",
            wait_until="networkidle",
        )

        viewport = page.locator('[data-slot="document-canvas-viewport"]')
        viewport.wait_for(state="visible")
        page.locator(
            '[data-slot="document-canvas-viewport"] '
            '[data-resume-pagination-ready="true"]'
        ).wait_for(state="visible")
        actual_size = page.get_by_role(
            "button",
            name="实际大小",
            exact=True,
        )
        actual_size.click()
        for _ in range(5):
            actual_size.press("Control+-")
        expect(actual_size).to_have_text("50%")

        def canvas_geometry() -> dict[str, float]:
            return viewport.evaluate(
                """
                element => {
                  const stage = element.querySelector('.document-canvas-stage');
                  const paper = element.querySelector(
                    '[data-document-canvas-paper]',
                  );
                  if (!(stage instanceof HTMLElement) ||
                      !(paper instanceof HTMLElement)) {
                    throw new Error('Missing document canvas geometry.');
                  }
                  const stageBounds = stage.getBoundingClientRect();
                  const paperBounds = paper.getBoundingClientRect();
                  const stageStyle = getComputedStyle(stage);
                  const paddingTop = Number.parseFloat(stageStyle.paddingTop);
                  const paddingBottom = Number.parseFloat(stageStyle.paddingBottom);
                  return {
                    bottomGap:
                      stageBounds.bottom - paddingBottom - paperBounds.bottom,
                    clientHeight: element.clientHeight,
                    scrollHeight: element.scrollHeight,
                    topGap: paperBounds.top - stageBounds.top - paddingTop,
                  };
                }
                """
            )

        centered = canvas_geometry()
        assert centered["scrollHeight"] == pytest.approx(
            centered["clientHeight"],
            abs=1,
        )
        assert centered["topGap"] > 0
        assert centered["topGap"] == pytest.approx(
            centered["bottomGap"],
            abs=1,
        )

        actual_size.press("Control+0")
        expect(actual_size).to_have_text("100%")
        overflowing = canvas_geometry()
        assert overflowing["scrollHeight"] > overflowing["clientHeight"]
        assert overflowing["topGap"] == pytest.approx(0, abs=1)
    finally:
        context.close()
