from __future__ import annotations

import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Locator, Page, Route, expect

from tests.e2e.browser_support import DeferredRoute, authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]

EDITOR = ".resume-workspace .resume-editor-panel"
PREVIEW = ".resume-workspace .resume-preview-card"
AGENT = "#resume-detail-agent-panel"


@pytest.fixture
def resize_workspace(
    browser: Browser,
    workspace_servers: tuple[str, str],
    request: pytest.FixtureRequest,
) -> Iterator[tuple[Page, dict[str, Any]]]:
    base, _ = workspace_servers
    locale = getattr(request, "param", "en")
    messages = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / f"frontend/src/i18n/locales/{locale}.json"
        ).read_text(encoding="utf-8")
    )
    messages.update(
        json.loads(
            (
                Path(__file__).resolve().parents[3]
                / "frontend/src/i18n/workspace-resize.json"
            ).read_text(encoding="utf-8")
        )[locale]
    )
    context = authenticated_context(
        browser,
        locale="zh-CN" if locale == "zh" else "en-US",
        viewport={"width": 1600, "height": 1000},
    )
    context.add_init_script(f"localStorage.setItem('reseno-locale', '{locale}')")
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def configure_test_model(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["modelConfigs"] = [
            {
                "id": "workspace-resize-model",
                "provider": "openai",
                "nickname": "Workspace resize model",
                "model": "workspace-resize-model",
                "supportsTools": True,
            }
        ]
        payload["data"]["agentSettings"]["defaultModelConfigId"] = (
            "workspace-resize-model"
        )
        route.fulfill(response=response, json=payload)

    page.route("**/api/workspace/pages/resume-editor", configure_test_model)
    page.route("**/api/agent/chat", lambda route: route.abort())
    try:
        created = page.request.post(
            f"{base}/api/resumes",
            data={"documentLocale": locale, "title": "Workspace resizing"},
        )
        assert created.ok, created.text()
        resume_id = created.json()["data"]["resume"]["id"]
        page.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        expect(page.locator(EDITOR)).to_be_visible()
        expect(page.locator(PREVIEW)).to_be_visible()
        toggle = page.locator('[data-slot="agent-panel-toggle"]')
        if toggle.get_attribute("aria-expanded") != "true":
            toggle.click()
        expect(page.locator(AGENT).locator("textarea")).to_be_enabled()
        _settle_layout(page)
        yield page, messages
        assert errors == []
    finally:
        context.close()


def _settle_layout(page: Page) -> None:
    page.locator(".resume-workspace").evaluate(
        """async element => {
          await new Promise(resolve => requestAnimationFrame(resolve));
          await Promise.all(element.getAnimations({subtree: true})
            .filter(animation => animation.effect?.getTiming().iterations !== Infinity)
            .map(animation => animation.finished.catch(() => {})));
          await new Promise(resolve => requestAnimationFrame(resolve));
        }"""
    )


def _width(page: Page, selector: str) -> float:
    return float(
        page.locator(selector).evaluate(
            "element => element.getBoundingClientRect().width"
        )
    )


def _handles(page: Page, messages: dict[str, Any]) -> tuple[Locator, Locator]:
    chinese = messages["basicInfo"] == "基本信息"
    return (
        page.get_by_role(
            "separator",
            name="调整编辑区宽度" if chinese else "Resize editor panel",
            exact=True,
        ),
        page.get_by_role(
            "separator",
            name="调整 Agent 区宽度" if chinese else "Resize Agent panel",
            exact=True,
        ),
    )


def _drag(page: Page, handle: Locator, distance: float) -> None:
    box = handle.bounding_box()
    assert box is not None
    x = box["x"] + box["width"] / 2
    y = box["y"] + min(box["height"] / 2, 160)
    hit = handle.evaluate(
        """(element, point) => {
          const hit = document.elementFromPoint(point.x, point.y);
          return {matches: element.contains(hit), target: hit?.outerHTML.slice(0, 350)};
        }""",
        {"x": x, "y": y},
    )
    assert hit["matches"], hit
    storage = page.evaluate("localStorage.getItem('reseno-workspace-layout-v1')")
    before = {selector: _width(page, selector) for selector in (EDITOR, AGENT)}
    resizing_editor = "editor" in (
        handle.get_attribute("aria-label") or ""
    ).lower() or (handle.get_attribute("aria-label") == "调整编辑区宽度")
    stationary = AGENT if resizing_editor else EDITOR
    page.mouse.move(x, y)
    page.mouse.down()
    for index in range(1, 9):
        page.mouse.move(x + distance * index / 8, y)
        assert 371 <= _width(page, EDITOR) <= 561
        assert 299 <= _width(page, AGENT) <= 521
        assert _width(page, PREVIEW) >= 419
        assert _width(page, stationary) == pytest.approx(before[stationary], abs=1)
    assert (
        page.evaluate("localStorage.getItem('reseno-workspace-layout-v1')") == storage
    )
    page.mouse.up()
    _settle_layout(page)


def _assert_page_fits(page: Page) -> None:
    geometry = page.evaluate(
        """() => ({
          width: document.documentElement.clientWidth,
          contentWidth: document.documentElement.scrollWidth,
        })"""
    )
    assert geometry["contentWidth"] <= geometry["width"] + 1, geometry


def _open_basic_info(page: Page, messages: dict[str, Any]) -> Locator:
    toggle = page.get_by_role(
        "button",
        name=f"{messages['basicInfo']}: {messages['toggleSection']}",
        exact=True,
    )
    if toggle.get_attribute("aria-expanded") != "true":
        toggle.click()
    name = page.get_by_role("textbox", name=messages["fieldLabels"]["name"], exact=True)
    expect(name).to_be_visible()
    _settle_layout(page)
    return name


def test_resize_handles_bound_each_panel_without_squeezing_the_other(
    resize_workspace: tuple[Page, dict[str, Any]],
) -> None:
    page, messages = resize_workspace
    page.set_viewport_size({"width": 1440, "height": 1000})
    _settle_layout(page)
    editor_handle, agent_handle = _handles(page, messages)
    for handle in (editor_handle, agent_handle):
        expect(handle).to_be_visible()
        expect(handle).to_have_attribute("aria-orientation", "vertical")
    default_editor = _width(page, EDITOR)
    default_agent = _width(page, AGENT)
    fit = page.get_by_role("button", name=messages["fitToWidth"], exact=True)
    fit.click()
    expect(fit).to_have_attribute("aria-pressed", "true")
    _settle_layout(page)
    actual_size = page.get_by_role("button", name=messages["actualSize"], exact=True)
    initial_scale = float(actual_size.inner_text().removesuffix("%"))
    pages = page.locator(f"{PREVIEW} .resume-page-stack")
    page_count = pages.get_attribute("data-resume-page-count")
    assert page_count is not None

    _drag(page, editor_handle, -2000)
    assert _width(page, EDITOR) == pytest.approx(372, abs=1)
    assert _width(page, AGENT) == pytest.approx(default_agent, abs=1)
    _drag(page, agent_handle, 2000)
    assert _width(page, AGENT) == pytest.approx(300, abs=1)
    assert _width(page, EDITOR) == pytest.approx(372, abs=1)

    _drag(page, editor_handle, 2000)
    assert _width(page, EDITOR) == pytest.approx(560, abs=1)
    assert _width(page, AGENT) == pytest.approx(300, abs=1)
    _drag(page, agent_handle, -2000)
    assert _width(page, EDITOR) == pytest.approx(560, abs=1)
    assert 300 <= _width(page, AGENT) <= 520
    assert _width(page, PREVIEW) == pytest.approx(420, abs=1)
    expect(fit).to_have_attribute("aria-pressed", "true")
    expect(pages).to_have_attribute("data-resume-page-count", page_count)
    assert float(actual_size.inner_text().removesuffix("%")) < initial_scale
    canvas = page.locator('[data-slot="document-canvas-viewport"]').evaluate(
        """viewport => {
          const bounds = viewport.getBoundingClientRect();
          const paper = viewport.querySelector('[data-document-canvas-paper]')
            .getBoundingClientRect();
          return {left: bounds.left, right: bounds.right,
            paperLeft: paper.left, paperRight: paper.right,
            width: viewport.clientWidth, contentWidth: viewport.scrollWidth};
        }"""
    )
    assert canvas["paperLeft"] >= canvas["left"] - 1, canvas
    assert canvas["paperRight"] <= canvas["right"] + 1, canvas
    assert canvas["contentWidth"] <= canvas["width"] + 1, canvas
    _assert_page_fits(page)

    agent_width = _width(page, AGENT)
    editor_handle.dblclick(position={"x": 3, "y": 120})
    _settle_layout(page)
    assert _width(page, EDITOR) == pytest.approx(default_editor, abs=1)
    assert _width(page, AGENT) == pytest.approx(agent_width, abs=1)
    agent_handle.dblclick(position={"x": 3, "y": 120})
    _settle_layout(page)
    assert _width(page, AGENT) == pytest.approx(default_agent, abs=1)

    editor_handle.focus()
    page.keyboard.press("ArrowRight")
    _settle_layout(page)
    assert _width(page, EDITOR) > default_editor
    assert _width(page, AGENT) == pytest.approx(default_agent, abs=1)
    expect(editor_handle).to_be_focused()
    page.keyboard.press("ArrowLeft")
    _settle_layout(page)
    assert _width(page, EDITOR) == pytest.approx(default_editor, abs=1)
    page.keyboard.press("Shift+ArrowRight")
    _settle_layout(page)
    assert _width(page, EDITOR) == pytest.approx(default_editor + 64, abs=1)
    page.keyboard.press("Shift+ArrowLeft")
    _settle_layout(page)
    agent_handle.focus()
    page.keyboard.press("ArrowLeft")
    _settle_layout(page)
    assert _width(page, AGENT) > default_agent
    assert _width(page, EDITOR) == pytest.approx(default_editor, abs=1)
    page.keyboard.press("ArrowRight")
    _settle_layout(page)
    assert _width(page, AGENT) == pytest.approx(default_agent, abs=1)


@pytest.mark.parametrize("resize_workspace", ["zh", "en"], indirect=True)
def test_minimum_panel_widths_keep_localized_controls_inside_their_panels(
    resize_workspace: tuple[Page, dict[str, Any]],
) -> None:
    page, messages = resize_workspace
    editor_handle, agent_handle = _handles(page, messages)
    _drag(page, editor_handle, -2000)
    _drag(page, agent_handle, 2000)
    page.set_viewport_size({"width": 1280, "height": 1000})
    _settle_layout(page)
    expect(editor_handle).to_be_visible()
    expect(agent_handle).to_be_visible()
    _open_basic_info(page, messages)
    assert _width(page, EDITOR) == pytest.approx(372, abs=1)
    assert _width(page, AGENT) == pytest.approx(300, abs=1)
    for selector in (EDITOR, AGENT):
        overflowing = page.locator(selector).evaluate(
            """panel => {
              const bounds = panel.getBoundingClientRect();
              return Array.from(panel.querySelectorAll(
                'button, input:not([type="file"]), textarea, [role="combobox"], '
                + '[contenteditable="true"]'
              )).flatMap(control => {
                const rect = control.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return [];
                return rect.left < bounds.left - 1 || rect.right > bounds.right + 1
                  ? [{label: control.getAttribute('aria-label') ?? control.textContent,
                      left: rect.left, right: rect.right,
                      panelLeft: bounds.left, panelRight: bounds.right}]
                  : [];
              });
            }"""
        )
        assert overflowing == [], overflowing
    _assert_page_fits(page)


def test_resize_dividers_keep_a_horizontal_cursor_without_arrow_buttons(
    resize_workspace: tuple[Page, dict[str, Any]],
) -> None:
    page, messages = resize_workspace
    editor_handle, agent_handle = _handles(page, messages)
    for handle, panel, stationary, delta in (
        (editor_handle, EDITOR, AGENT, 40),
        (agent_handle, AGENT, EDITOR, -40),
    ):
        box = handle.bounding_box()
        assert box is not None
        x = box["x"] + box["width"] / 2
        y = box["y"] + min(box["height"] / 2, 160)
        before = _width(page, panel)
        other_width = _width(page, stationary)
        page.mouse.move(x, y)
        expect(
            handle.locator("..").get_by_role("button", include_hidden=True)
        ).to_have_count(0)
        assert (
            page.evaluate(
                "point => getComputedStyle(document.elementFromPoint("
                "point.x, point.y)).cursor",
                {"x": x, "y": y},
            )
            == "ew-resize"
        )
        page.mouse.down()
        try:
            page.mouse.move(x + 40, y, steps=4)
            assert (
                page.evaluate(
                    "point => getComputedStyle(document.elementFromPoint("
                    "point.x, point.y)).cursor",
                    {"x": x + 40, "y": y},
                )
                == "ew-resize"
            )
            assert _width(page, panel) == pytest.approx(before + delta, abs=1)
            assert _width(page, stationary) == pytest.approx(other_width, abs=1)
        finally:
            page.mouse.up()
        _settle_layout(page)
        assert _width(page, panel) == pytest.approx(before + delta, abs=1)


def test_cold_section_menu_receives_keyboard_focus_and_returns_it_on_escape(
    resize_workspace: tuple[Page, dict[str, Any]],
) -> None:
    page, messages = resize_workspace
    asset = "src/components/editor/add-section-menu.tsx"
    if os.getenv("E2E_FRONTEND_MODE") == "preview":
        frontend = Path(__file__).resolve().parents[3] / "frontend"
        dist = Path(os.getenv("E2E_FRONTEND_DIST_DIR", str(frontend / "dist")))
        manifest = json.loads((dist / ".vite/manifest.json").read_text())
        asset = manifest[asset]["file"]
    deferred_menu = DeferredRoute(page, f"**/{asset}*")
    trigger = page.get_by_role("button", name=messages["addSection"], exact=True)
    popover = page.locator('[data-slot="popover-content"]')
    try:
        trigger.focus()
        page.keyboard.press("Enter")
        deferred_menu.wait()
        expect(popover.locator('[aria-busy="true"]')).to_be_visible()
        assert deferred_menu.pending, (
            "the menu module must remain deferred through opening"
        )
        deferred_menu.release()
        menu = popover.locator('[data-slot="command"]')
        page.wait_for_function(
            "element => element.contains(document.activeElement)",
            arg=menu.element_handle(),
            timeout=5_000,
        )
        page.keyboard.press("Escape")
        expect(popover).to_have_count(0)
        expect(trigger).to_be_focused()

        page.keyboard.press("Enter")
        page.wait_for_function(
            "element => element.contains(document.activeElement)",
            arg=menu.element_handle(),
            timeout=5_000,
        )
        options = menu.get_by_role("option")
        expect(options.first).to_have_attribute("aria-selected", "true")
        page.keyboard.press("ArrowDown")
        expect(options.nth(1)).to_have_attribute("aria-selected", "true")
        title = options.nth(1).locator("span.font-medium").inner_text()
        section = page.get_by_role(
            "button", name=f"{title}: {messages['toggleSection']}", exact=True
        )
        before = section.count()
        page.keyboard.press("Enter")
        expect(popover).to_have_count(0)
        expect(section).to_have_count(before + 1)
        expect(section.last).to_have_attribute("aria-expanded", "true")
    finally:
        for route in deferred_menu.pending:
            route.abort()


def test_resizing_preserves_live_editors_and_restores_widths_after_reload(
    resize_workspace: tuple[Page, dict[str, Any]],
) -> None:
    page, messages = resize_workspace
    name = _open_basic_info(page, messages)
    name.fill("Taylor Morgan")
    composer = page.locator(AGENT).locator("textarea")
    composer.fill("Refine this draft after resizing")
    editor_node = name.element_handle()
    composer_node = composer.element_handle()
    assert editor_node is not None and composer_node is not None
    editor_handle, agent_handle = _handles(page, messages)
    _drag(page, editor_handle, 60)
    _drag(page, agent_handle, -60)
    editor_width = _width(page, EDITOR)
    agent_width = _width(page, AGENT)
    assert editor_node.evaluate("element => element.isConnected")
    assert composer_node.evaluate("element => element.isConnected")
    expect(name).to_have_text("Taylor Morgan")
    expect(composer).to_have_value("Refine this draft after resizing")

    toggle = page.locator('[data-slot="agent-panel-toggle"]')
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(agent_handle).to_have_count(0)
    _settle_layout(page)
    assert _width(page, EDITOR) == pytest.approx(editor_width, abs=1)
    assert composer_node.evaluate("element => element.isConnected")
    toggle.click()
    _settle_layout(page)
    assert _width(page, AGENT) == pytest.approx(agent_width, abs=1)
    expect(composer).to_have_value("Refine this draft after resizing")

    page.set_viewport_size({"width": 1279, "height": 1000})
    _settle_layout(page)
    expect(editor_handle).to_have_count(0)
    expect(agent_handle).to_have_count(0)
    assert page.locator('.resume-workspace [role="separator"]').evaluate_all(
        "elements => elements.every(element => element.tabIndex < 0 "
        "|| element.getClientRects().length === 0)"
    )
    assert editor_node.evaluate("element => element.isConnected")
    assert composer_node.evaluate("element => element.isConnected")
    expect(name).to_have_text("Taylor Morgan")
    expect(composer).to_have_value("Refine this draft after resizing")
    _assert_page_fits(page)
    page.set_viewport_size({"width": 1600, "height": 1000})
    _settle_layout(page)
    expect(editor_handle).to_be_visible()
    expect(agent_handle).to_be_visible()
    assert _width(page, EDITOR) == pytest.approx(editor_width, abs=1)
    assert _width(page, AGENT) == pytest.approx(agent_width, abs=1)
    assert editor_node.evaluate("element => element.isConnected")
    assert composer_node.evaluate("element => element.isConnected")

    page.reload(wait_until="networkidle")
    expect(page.locator(AGENT).locator("textarea")).to_be_enabled()
    _settle_layout(page)
    assert _width(page, EDITOR) == pytest.approx(editor_width, abs=1)
    assert _width(page, AGENT) == pytest.approx(agent_width, abs=1)

    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "false")
    page.reload(wait_until="networkidle")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    expect(agent_handle).to_have_count(0)
    assert _width(page, EDITOR) == pytest.approx(editor_width, abs=1)
    toggle.click()
    expect(page.locator(AGENT).locator("textarea")).to_be_enabled()
    _settle_layout(page)
    assert _width(page, AGENT) == pytest.approx(agent_width, abs=1)
