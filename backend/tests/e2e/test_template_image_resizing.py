from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, expect

from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


@pytest.mark.parametrize("zoom", [0.6, 1.3])
def test_template_image_resizes_at_preview_zoom_and_preserves_geometry(
    browser: Browser,
    workspace_servers: tuple[str, str],
    zoom: float,
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 2048, "height": 1900}
    )
    page = context.new_page()
    template_id: str | None = None
    editor = page.get_by_role("group", name="图片元素 1", exact=True)
    controls = {
        key: editor.get_by_role("spinbutton", name=label, exact=True)
        for key, label in (
            ("x", "横向位置"),
            ("y", "纵向位置"),
            ("width", "宽度"),
            ("height", "高度"),
        )
    }
    preview_page = page.locator('[data-export-root="resume-page"]:visible').last
    frame = preview_page.locator('[data-template-image-frame="true"]').first

    def assert_geometry(x: float, y: float, width: float, height: float) -> None:
        expected = {"x": x, "y": y, "width": width, "height": height}
        for key, value in expected.items():
            expect(controls[key]).to_have_value(f"{value:g}")
        rendered = frame.evaluate(
            """element => {
              const rect = element.getBoundingClientRect();
              const paper = element.closest('[data-export-root="resume-page"]')
                .getBoundingClientRect();
              const origin = element.offsetParent.getBoundingClientRect();
              const pxPerMm = paper.width / 210;
              return {
                x: (rect.left - origin.left) / pxPerMm,
                y: (rect.top - origin.top) / pxPerMm,
                width: rect.width / pxPerMm,
                height: rect.height / pxPerMm,
              };
            }"""
        )
        for key, value in expected.items():
            assert rendered[key] == pytest.approx(value, abs=0.3), rendered

    def set_geometry(x: float, y: float, width: float, height: float) -> None:
        for key, value in (
            ("width", 6),
            ("height", 6),
            ("x", x),
            ("y", y),
            ("width", width),
            ("height", height),
        ):
            controls[key].fill(f"{value:g}")
            controls[key].press("Enter")
        assert_geometry(x, y, width, height)

    def resize(
        direction: str,
        dx: float,
        dy: float,
        expected: tuple[float, float, float, float],
        midpoint: tuple[float, float, float, float] | None = None,
    ) -> None:
        frame.hover()
        handle = frame.locator(f'[data-template-image-resize-handle="{direction}"]')
        expect(handle).to_be_visible()
        handle.scroll_into_view_if_needed()
        box = handle.bounding_box()
        assert box is not None
        px_per_mm = preview_page.evaluate(
            "element => element.getBoundingClientRect().width / 210"
        )
        start_x = round(box["x"] + box["width"] / 2)
        start_y = round(box["y"] + box["height"] / 2)
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        try:
            if midpoint is not None:
                page.mouse.move(
                    start_x + round(dx * px_per_mm / 2),
                    start_y + round(dy * px_per_mm / 2),
                    steps=4,
                )
                assert_geometry(*midpoint)
            page.mouse.move(
                start_x + round(dx * px_per_mm),
                start_y + round(dy * px_per_mm),
                steps=8,
            )
            assert_geometry(*expected)
        finally:
            page.mouse.up()
        assert_geometry(*expected)

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role("button", name="创建副本", exact=True).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = urlparse(page.url).path.rsplit("/", maxsplit=1)[-1]
        page.get_by_title("内置模板 · 只读", exact=True).wait_for(state="hidden")
        page.get_by_role("tab", name="装饰", exact=True).click()
        page.get_by_role("button", name="添加图片占位符", exact=True).click()
        expect(frame.locator("[data-template-image-resize-handle]")).to_have_count(8)

        canvas_controls = page.locator('[data-slot="document-canvas-controls"]')
        actual_size = canvas_controls.get_by_role("button", name="实际大小", exact=True)
        actual_size.click()
        zoom_button = canvas_controls.get_by_role(
            "button", name="缩小" if zoom < 1 else "放大", exact=True
        )
        for _ in range(round(abs(zoom - 1) * 10)):
            zoom_button.click()
        expect(actual_size).to_have_text(f"{round(zoom * 100)}%")

        set_geometry(40, 40, 30, 20)
        resize("right", 10, 0, (40, 40, 40, 20), (40, 40, 35, 20))
        resize("right", -12, 0, (40, 40, 28, 20))
        resize("left", -10, 0, (30, 40, 38, 20))
        resize("left", 8, 0, (38, 40, 30, 20))
        resize("top", 0, -8, (38, 32, 30, 28))
        resize("bottom", 0, 6, (38, 32, 30, 34))
        resize("bottomRight", 10, 12, (38, 32, 40, 46))
        resize("topLeft", 6, 8, (44, 40, 34, 38))
        resize("topRight", 5, -4, (44, 36, 39, 42))
        resize("bottomLeft", -4, 5, (40, 36, 43, 47))

        set_geometry(180, 260, 20, 20)
        resize("bottomRight", 60, 60, (180, 260, 30, 37))
        resize("bottomRight", -60, -60, (180, 260, 6, 6))
        set_geometry(20, 20, 30, 20)
        resize("topLeft", -60, -60, (0, 0, 50, 40))
        resize("bottomRight", 200, 200, (0, 0, 120, 120))
        resize("topLeft", 200, 200, (114, 114, 6, 6))

        set_geometry(40, 40, 30, 20)
        resize("bottomRight", 12.5, 7.5, (40, 40, 42.5, 27.5))
        frame.locator('[data-template-image-resize-handle="bottomRight"]').click()
        assert_geometry(40, 40, 42.5, 27.5)
        frame.scroll_into_view_if_needed()
        box = frame.bounding_box()
        assert box is not None
        px_per_mm = preview_page.evaluate(
            "element => element.getBoundingClientRect().width / 210"
        )
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(start_x + 16.5 * px_per_mm, start_y + 8.5 * px_per_mm, steps=8)
        page.mouse.up()
        assert_geometry(56.5, 48.5, 42.5, 27.5)

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
        expected = {"x": 56.5, "y": 48.5, "width": 42.5, "height": 27.5}
        saved_image = saved.value.request.post_data_json["template"]["layout"][
            "images"
        ][0]
        persisted_image = page.request.get(f"{frontend_url}{path}").json()["data"][
            "template"
        ]["layout"]["images"][0]
        for key, value in expected.items():
            assert saved_image[key] == value
            assert persisted_image[key] == value

        page.reload(wait_until="networkidle")
        page.get_by_role("tab", name="装饰", exact=True).click()
        editor.get_by_role("button", name="展开图片设置", exact=True).click()
        assert_geometry(56.5, 48.5, 42.5, 27.5)
        expect(frame.locator("[data-template-image-resize-handle]")).to_have_count(8)

        set_geometry(40, 40, 30, 20)
        frame.hover()
        handle = frame.locator('[data-template-image-resize-handle="right"]')
        handle.scroll_into_view_if_needed()
        box = handle.bounding_box()
        assert box is not None
        px_per_mm = preview_page.evaluate(
            "element => element.getBoundingClientRect().width / 210"
        )
        start_x = box["x"] + box["width"] / 2
        start_y = box["y"] + box["height"] / 2
        touch = context.new_cdp_session(page)
        try:
            touch.send(
                "Input.dispatchTouchEvent",
                {
                    "type": "touchStart",
                    "touchPoints": [{"x": start_x, "y": start_y}],
                },
            )
            expect(frame).to_have_attribute("data-resizing", "true")
            touch.send(
                "Input.dispatchTouchEvent",
                {
                    "type": "touchMove",
                    "touchPoints": [{"x": start_x + 10 * px_per_mm, "y": start_y}],
                },
            )
            assert_geometry(40, 40, 40, 20)
        finally:
            touch.send(
                "Input.dispatchTouchEvent", {"type": "touchCancel", "touchPoints": []}
            )
            touch.detach()
        expect(frame).not_to_have_attribute("data-resizing", "true")
        assert_geometry(40, 40, 40, 20)
        handle.click(trial=True)
        page.mouse.move(start_x + 20 * px_per_mm, start_y, steps=4)
        assert_geometry(40, 40, 40, 20)
        resize("right", 5, 0, (40, 40, 45, 20))
    finally:
        page.mouse.up()
        if template_id:
            response = context.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if response.ok:
                context.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()
