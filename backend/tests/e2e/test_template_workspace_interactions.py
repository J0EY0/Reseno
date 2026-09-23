from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Locator, Page, Route, expect

from tests.e2e.browser_support import RouteReady, authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]

WIDTH_KEY = "reseno-template-editor-width-v1"
RESUME_WIDTH_KEY = "reseno-workspace-layout-v1"


def _messages(locale: str) -> dict:
    return json.loads(
        (
            Path(__file__).resolve().parents[3]
            / f"frontend/src/i18n/locales/{locale}.json"
        ).read_text(encoding="utf-8")
    )


def _copy_template(page: Page, base: str, locale: str) -> str:
    page.goto(f"{base}/template/minimal", wait_until="networkidle")
    page.get_by_role(
        "button", name="创建副本" if locale == "zh" else "Create Copy", exact=True
    ).click()
    page.wait_for_url(f"{base}/template/template-*")
    return page.url.rsplit("/", maxsplit=1)[-1]


def _settle(element: Locator) -> None:
    element.evaluate(
        """async element => {
          await new Promise(requestAnimationFrame);
          await Promise.all(element.getAnimations({subtree: true})
            .filter(animation => animation.effect?.getTiming().iterations !== Infinity)
            .map(animation => animation.finished.catch(() => {})));
          await new Promise(requestAnimationFrame);
        }"""
    )


def _delete_template(page: Page, base: str, template_id: str | None) -> None:
    if template_id:
        response = page.request.post(f"{base}/api/templates/{template_id}/trash")
        if response.ok:
            page.request.delete(f"{base}/api/templates/{template_id}")


@pytest.mark.parametrize("locale", ["zh", "en"])
def test_template_editor_resize_preserves_controls_and_preview(
    browser: Browser, workspace_servers: tuple[str, str], locale: str
) -> None:
    base, _ = workspace_servers
    messages = _messages(locale)
    minimum = 340 if locale == "zh" else 400
    context = authenticated_context(
        browser,
        locale="zh-CN" if locale == "zh" else "en-US",
        viewport={"width": 1440, "height": 1000},
    )
    resume_preference = json.dumps(
        {"editorWidth": 480, "agentWidth": 360, "agentCollapsed": False}
    )
    context.add_init_script(
        f"localStorage.setItem({json.dumps(RESUME_WIDTH_KEY)}, "
        f"{json.dumps(resume_preference)})"
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    template_id = None
    try:
        template_id = _copy_template(page, base, locale)
        workspace = page.locator(".template-workspace")
        editor = workspace.locator(".resume-template-editor-panel")
        preview = workspace.locator(".resume-preview-card")
        handle = workspace.get_by_role(
            "separator",
            name="调整编辑区宽度" if locale == "zh" else "Resize editor panel",
            exact=True,
        )
        expect(handle).to_be_visible()
        expect(handle).to_have_attribute("aria-orientation", "vertical")
        expect(handle).to_have_attribute("aria-valuemin", str(minimum))
        expect(handle).to_have_attribute("aria-valuemax", "560")

        def width() -> float:
            return editor.evaluate("el => el.getBoundingClientRect().width")

        def stored() -> str | None:
            return page.evaluate("key => localStorage.getItem(key)", WIDTH_KEY)

        def check_width(expected: float) -> None:
            _settle(workspace)
            assert width() == pytest.approx(expected, abs=1)
            assert float(handle.get_attribute("aria-valuenow")) == pytest.approx(
                expected, abs=1
            )
            assert preview.evaluate("el => el.getBoundingClientRect().width") >= 419

        def drag(distance: float) -> None:
            box = handle.bounding_box()
            assert box is not None
            x = box["x"] + box["width"] / 2
            y = box["y"] + min(box["height"] / 2, 160)
            assert handle.evaluate(
                "(el, p) => el.contains(document.elementFromPoint(p.x, p.y))",
                {"x": x, "y": y},
            )
            before = stored()
            before_width = width()
            before_preview = preview.evaluate("el => el.getBoundingClientRect().width")
            page.mouse.move(x, y)
            page.mouse.down()
            for step in range(1, 9):
                page.mouse.move(x + distance * step / 8, y)
                assert minimum - 1 <= width() <= 561
                assert preview.evaluate(
                    "el => el.getBoundingClientRect().width"
                ) == pytest.approx(before_preview + before_width - width(), abs=1)
                assert stored() == before
            page.mouse.up()
            _settle(workspace)
            assert float(stored()) == pytest.approx(width(), abs=1)

        check_width(minimum)
        color_tab = page.get_by_role(
            "tab", name=messages["templateVisualTab"], exact=True
        )
        color_tab.click()
        color = page.get_by_role("textbox", name=messages["headingColor"], exact=True)
        color.fill("#8855aa")
        color.press("Tab")
        original_control = color.element_handle()
        assert original_control is not None

        def check_control() -> None:
            assert original_control.evaluate("el => el.isConnected")
            expect(color).to_have_value("#8855aa")
            expect(color_tab).to_have_attribute("aria-selected", "true")

        _settle(workspace)
        handle_box, editor_box = handle.bounding_box(), editor.bounding_box()
        assert handle_box is not None and editor_box is not None
        assert handle_box["y"] == pytest.approx(editor_box["y"], abs=1)
        assert handle_box["height"] == pytest.approx(editor_box["height"], abs=1)
        fit = page.get_by_role("button", name=messages["fitToWidth"], exact=True)
        fit.click()
        expect(fit).to_have_attribute("aria-pressed", "true")
        _settle(workspace)
        scale = page.get_by_role("button", name=messages["actualSize"], exact=True)
        initial_scale = float(scale.inner_text().removesuffix("%"))
        pages = preview.locator(".resume-page-stack")
        page_count = pages.get_attribute("data-resume-page-count")
        assert page_count is not None
        drag(80)
        check_width(minimum + 80)
        drag(2000)
        check_width(560)
        check_control()
        expect(pages).to_have_attribute("data-resume-page-count", page_count)
        assert float(scale.inner_text().removesuffix("%")) < initial_scale
        canvas = preview.locator('[data-slot="document-canvas-viewport"]').evaluate(
            """el => {
              const paper = el.querySelector('[data-document-canvas-paper]')
                .getBoundingClientRect();
              const bounds = el.getBoundingClientRect();
              return {left: bounds.left, right: bounds.right,
                paperLeft: paper.left, paperRight: paper.right,
                width: el.clientWidth, contentWidth: el.scrollWidth};
            }"""
        )
        assert canvas["paperLeft"] >= canvas["left"] - 1, canvas
        assert canvas["paperRight"] <= canvas["right"] + 1, canvas
        assert canvas["contentWidth"] <= canvas["width"] + 1, canvas
        drag(-2000)
        check_width(minimum)

        handle.focus()
        for key, expected in (
            ("ArrowRight", minimum + 16),
            ("Shift+ArrowRight", minimum + 80),
            ("ArrowLeft", minimum + 64),
            ("Shift+ArrowLeft", minimum),
            ("End", 560),
            ("Home", minimum),
        ):
            page.keyboard.press(key)
            check_width(expected)
            expect(handle).to_be_focused()
            check_control()
        drag(96)
        check_width(minimum + 96)
        handle.dblclick(position={"x": 3, "y": 120})
        check_width(minimum)
        drag(80)
        expected_width = minimum + 80
        check_width(expected_width)
        box = handle.bounding_box()
        assert box is not None
        x = box["x"] + box["width"] / 2
        y = box["y"] + min(box["height"] / 2, 160)
        page.mouse.move(x, y)
        page.mouse.down()
        page.mouse.move(x + 32, y, steps=4)
        expect(workspace).to_have_attribute("data-resizing", "true")
        assert width() == pytest.approx(expected_width + 32, abs=1)
        assert float(stored()) == pytest.approx(expected_width, abs=1)
        expected_width += 32
        page.set_viewport_size({"width": 1279, "height": 1000})
        expect(handle).to_have_count(0)
        page.mouse.up()
        _settle(workspace)
        assert workspace.get_attribute("data-resizing") is None
        assert float(stored()) == pytest.approx(expected_width, abs=1)
        check_control()
        editor_box, preview_box = editor.bounding_box(), preview.bounding_box()
        assert editor_box is not None and preview_box is not None
        assert editor_box["y"] + editor_box["height"] <= preview_box["y"] + 1
        assert page.evaluate(
            "document.documentElement.scrollWidth <= "
            "document.documentElement.clientWidth + 1"
        )
        page.set_viewport_size({"width": 1440, "height": 1000})
        expect(handle).to_be_visible()
        check_width(expected_width)
        check_control()
        assert (
            page.evaluate("key => localStorage.getItem(key)", RESUME_WIDTH_KEY)
            == resume_preference
        )
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and response.url.endswith(f"/api/templates/{template_id}")
                and response.request.post_data_json["saveMode"] == "checkpoint"
            )
        ) as saved:
            page.keyboard.press("ControlOrMeta+s")
        assert saved.value.ok
        page.reload(wait_until="networkidle")
        expect(handle).to_be_visible()
        check_width(expected_width)
        assert (
            page.evaluate("key => localStorage.getItem(key)", RESUME_WIDTH_KEY)
            == resume_preference
        )
        assert errors == []
    finally:
        _delete_template(page, base, template_id)
        context.close()


@pytest.mark.parametrize("locale,width", [("zh", 1440), ("en", 1440), ("en", 360)])
def test_template_save_and_leave_keeps_geometry_and_recovers_from_failure(
    browser: Browser,
    workspace_servers: tuple[str, str],
    tmp_path: Path,
    locale: str,
    width: int,
) -> None:
    base, _ = workspace_servers
    messages = _messages(locale)
    context = authenticated_context(
        browser,
        locale="zh-CN" if locale == "zh" else "en-US",
        viewport={"width": width, "height": 1000},
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    template_id = None
    pending: list[Route] = []
    requests: list[dict] = []
    ready = RouteReady()
    samples: dict[str, list[dict]] = {}
    try:
        template_id = _copy_template(page, base, locale)
        page.get_by_role(
            "button", name=messages["editTemplateInfo"], exact=True
        ).click()
        info = page.get_by_role("dialog", name=messages["editTemplateInfo"], exact=True)
        info.get_by_label(messages["templateName"], exact=True).fill("Delayed save")
        info.get_by_role(
            "button", name=messages["saveTemplateInfo"], exact=True
        ).click()
        page.get_by_role("button", name=messages["backToTemplates"], exact=True).click()
        dialog = page.get_by_role(
            "dialog", name=messages["unsavedChangesTitle"], exact=True
        )
        expect(dialog).to_be_visible()
        _settle(dialog)
        dialog.evaluate(
            """el => {
              const box = node => {
                const r = node.getBoundingClientRect();
                return {x: r.x, y: r.y, width: r.width, height: r.height};
              };
              const footer = [...el.querySelectorAll(
                '[data-slot="dialog-footer"] button')];
              const header = [...document.querySelectorAll(
                '[data-slot="template-workspace-header"] button')]
                .filter(button => button.getBoundingClientRect().width > 0);
              const recording = {active: true, phase: 'before', frames: {}};
              const capture = () => {
                (recording.frames[recording.phase] ??= []).push({dialog: box(el),
                  buttons: footer.map(box), header: header.map(box)});
              };
              recording.mark = phase => {recording.phase = phase; capture();};
              const tick = () => {
                if (!recording.active || window.__leaveRecording !== recording)
                  return;
                capture();
                requestAnimationFrame(tick);
              };
              window.__leaveRecording = recording;
              tick();
            }"""
        )

        def mark_phase(phase: str) -> None:
            page.evaluate("phase => window.__leaveRecording.mark(phase)", phase)

        def observe_frames() -> None:
            page.evaluate(
                """async () => {
                  for (let i = 0; i < 12; i++)
                    await new Promise(requestAnimationFrame);
                }"""
            )

        def hold_checkpoint(route: Route) -> None:
            if (
                route.request.method == "PUT"
                and route.request.post_data_json.get("saveMode") == "checkpoint"
            ):
                requests.append(route.request.post_data_json)
                pending.append(route)
                ready.set()
            else:
                route.continue_()

        page.route(f"**/api/templates/{template_id}", hold_checkpoint)
        save = dialog.get_by_role(
            "button", name=messages["unsavedChangesSaveAndLeave"], exact=True
        )
        observe_frames()
        for attempt in range(2):
            ready.clear()
            mark_phase(f"saving-{attempt}")
            save.click()
            ready.wait(page)
            saving = dialog.get_by_role("button", name=messages["saving"], exact=True)
            expect(saving).to_be_disabled()
            for button in dialog.locator('[data-slot="dialog-footer"] button').all():
                expect(button).to_be_disabled()
            expect(page.locator(".template-workspace")).to_be_visible()
            page.keyboard.press("Enter")
            page.keyboard.press("Escape")
            expect(dialog).to_be_visible()
            observe_frames()
            assert len(requests) == attempt + 1
            assert len(pending) == 1
            if attempt == 0:
                mark_phase("failure")
                pending.pop().fulfill(
                    status=503,
                    json={
                        "ok": False,
                        "error": {
                            "code": "TEMPORARY_FAILURE",
                            "message": "Temporary save failure",
                        },
                    },
                )
                expect(save).to_be_enabled()
                expect(page).to_have_url(f"{base}/template/{template_id}")
                observe_frames()
            else:
                samples = page.evaluate(
                    """() => {
                      const recording = window.__leaveRecording;
                      recording.active = false;
                      delete window.__leaveRecording;
                      return recording.frames;
                    }"""
                )
                pending.pop().continue_()
        page.wait_for_url(f"{base}/templates")
        persisted = page.request.get(f"{base}/api/templates/{template_id}")
        assert persisted.ok
        assert persisted.json()["data"]["template"]["name"] == "Delayed save"
        assert persisted.json()["data"]["checkpoint"] is None
        artifacts = Path(os.getenv("E2E_ARTIFACTS_DIR", str(tmp_path)))
        artifacts.mkdir(parents=True, exist_ok=True)
        (artifacts / f"save-leave-{locale}-{width}.json").write_text(
            json.dumps(samples, indent=2), encoding="utf-8"
        )
        baseline = samples["before"][-1]
        for phase, frames in samples.items():
            for frame in frames:
                for group, before in baseline.items():
                    before_boxes = before if isinstance(before, list) else [before]
                    current = frame[group]
                    boxes = current if isinstance(current, list) else [current]
                    assert len(boxes) == len(before_boxes)
                    for actual, expected in zip(boxes, before_boxes, strict=True):
                        assert actual == pytest.approx(expected, abs=1), (phase, group)
        assert errors == []
    finally:
        for route in pending:
            route.abort()
        _delete_template(page, base, template_id)
        context.close()
