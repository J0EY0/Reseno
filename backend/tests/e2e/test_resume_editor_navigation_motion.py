from __future__ import annotations

import os
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, expect

from app.services.resume_document_contract import (
    ITEM_LIST_FIELDS_BY_KIND,
    ITEM_STRING_FIELDS_BY_KIND,
)
from tests.e2e.test_resume_editor_navigation import (
    _continuation_item,
    _expect_at_panel_top,
)
from tests.e2e.test_resume_editor_sorting import (
    PANE,
    _item,
    _item_toggle,
    _section,
    _settle,
)
from tests.e2e.test_resume_editor_sorting import (
    sorting_workspace as sorting_workspace,
)

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _record_navigation_scroll(page: Page) -> None:
    page.evaluate(
        """() => {
          window.navigationScroll = {recording: true, positions: []};
          document.addEventListener('dblclick', () => {
            const panel = document.querySelector('.resume-editor-panel');
            const sample = () => {
              if (!window.navigationScroll.recording) return;
              window.navigationScroll.positions.push(panel.scrollTop);
              requestAnimationFrame(sample);
            };
            sample();
          }, {capture: true, once: true});
        }"""
    )


def _finish_navigation_scroll(page: Page) -> list[float]:
    return page.evaluate(
        """() => {
          window.navigationScroll.recording = false;
          window.navigationScroll.positions.push(
            document.querySelector('.resume-editor-panel').scrollTop);
          return window.navigationScroll.positions;
        }"""
    )


def _preview_heading(page: Page, item_id: str) -> Locator:
    return page.locator(
        '[data-slot="document-canvas-viewport"] '
        f'[data-export-root="resume-page"] [data-resume-item-id="{item_id}"] h3'
    ).first


def _open_continuation_item(page: Page, heading: Locator, target: Locator) -> None:
    page.locator(PANE).evaluate(
        """element => {
          window.initialNavigationComplete = false;
          element.addEventListener('scrollend', () => {
            window.initialNavigationComplete = true;
          }, {once: true});
        }"""
    )
    heading.dblclick()
    expect(_item_toggle(target)).to_have_attribute("aria-expanded", "true")
    _settle(page)
    _expect_at_panel_top(target)
    page.wait_for_function("window.initialNavigationComplete === true")


def _add_projects(page: Page, base: str, resume_id: str) -> None:
    response = page.request.get(f"{base}/api/resumes/{resume_id}")
    assert response.ok, response.text()
    document = response.json()["data"]["resume"]
    payload = {
        key: document[key]
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
    payload["resume"]["sections"][2]["items"] = [
        {
            **{key: "" for key in ITEM_STRING_FIELDS_BY_KIND["project"]},
            **{key: [] for key in ITEM_LIST_FIELDS_BY_KIND["project"]},
            "id": f"project-{index}",
            "name": f"Project {index}",
        }
        for index in range(1, 7)
    ]
    response = page.request.put(f"{base}/api/resumes/{resume_id}", data=payload)
    assert response.ok, response.text()
    page.reload(wait_until="networkidle")


@pytest.mark.parametrize(
    "sorting_workspace",
    [
        {"width": 1440, "height": 870, "item_groups": 6},
        {
            "width": 1440,
            "height": 870,
            "item_groups": 6,
            "reduced_motion": "reduce",
        },
    ],
    indirect=True,
    ids=["animated", "reduced-motion"],
)
@pytest.mark.parametrize("scenario", ["cold", "warm", "different", "cross", "module"])
def test_preview_navigation_scrolls_continuously_and_arrives_at_target(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]], scenario: str
) -> None:
    page, base, resume_id, _ = sorting_workspace
    reduced = page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
    if scenario == "cross":
        _add_projects(page, base, resume_id)
    heading, item_id = _continuation_item(page)
    target = _item(page, item_id)
    if scenario != "cold":
        _open_continuation_item(page, heading, target)
    if scenario == "warm":
        page.locator(PANE).evaluate("element => { element.scrollTop = 0; }")
        expect(page.locator(PANE)).to_have_js_property("scrollTop", 0)
    elif scenario == "different":
        item_id = "experience-1"
        heading = _preview_heading(page, item_id)
        target = _item(page, item_id)
    elif scenario == "cross":
        item_id = "project-3"
        heading = _preview_heading(page, item_id)
        target = _item(page, item_id)
    elif scenario == "module":
        item_id = None
        heading = page.locator(
            '[data-slot="document-canvas-viewport"] '
            '[data-export-root="resume-page"] [data-resume-section-id="experience"] '
            "[data-resume-section-header]"
        ).first
        target = _section(page, "experience")
    _record_navigation_scroll(page)
    heading.dblclick()
    if item_id:
        expect(_item_toggle(target)).to_have_attribute("aria-expanded", "true")
    _settle(page)
    _expect_at_panel_top(target)
    positions = _finish_navigation_scroll(page)
    assert abs(positions[-1] - positions[0]) > 100, positions
    intermediate = {
        position
        for position in positions
        if min(positions[0], positions[-1]) + 4
        < position
        < max(positions[0], positions[-1]) - 4
    }
    assert len(intermediate) <= 1 if reduced else len(intermediate) >= 2, positions


@pytest.mark.parametrize(
    "sorting_workspace",
    [{"width": 1440, "height": 870, "item_groups": 6}],
    indirect=True,
)
def test_wheel_input_stops_preview_navigation_before_the_target(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, _, _, _ = sorting_workspace
    pane = page.locator(PANE)
    heading, item_id = _continuation_item(page)
    target = _item(page, item_id)
    _open_continuation_item(page, heading, target)
    destination = pane.evaluate("element => element.scrollTop")
    assert destination > 400
    pane.evaluate("element => { element.scrollTop = 0; }")
    expect(pane).to_have_js_property("scrollTop", 0)
    pane.evaluate(
        """element => {
          window.navigationInterruption = {wheelAt: null, stopped: false};
          element.addEventListener('wheel', () => {
            window.navigationInterruption.wheelAt = element.scrollTop;
            element.addEventListener('scrollend', () => {
              window.navigationInterruption.stopped = true;
            }, {once: true});
          }, {capture: true, once: true});
        }"""
    )
    box = pane.bounding_box()
    assert box is not None
    heading.dblclick()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.wait_for_function(
        """destination => {
          const top = document.querySelector('.resume-editor-panel').scrollTop;
          return top > 80 && top < destination / 2;
        }""",
        arg=destination,
        timeout=5_000,
    )
    page.mouse.wheel(0, -400)
    page.wait_for_function("window.navigationInterruption.stopped")
    _settle(page)
    interruption = page.evaluate("window.navigationInterruption")
    final_scroll = pane.evaluate("element => element.scrollTop")
    assert 0 < interruption["wheelAt"] < destination
    assert final_scroll <= interruption["wheelAt"] + 2, interruption
    assert destination - final_scroll > 100
    page.mouse.wheel(0, -120)
    page.wait_for_function(
        """previous => document.querySelector('.resume-editor-panel').scrollTop
          < previous - 40""",
        arg=final_scroll,
    )
