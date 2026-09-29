from __future__ import annotations

import os
from typing import Any

import pytest
from playwright.sync_api import Locator, Page, expect

from tests.e2e.test_resume_editor_sorting import (
    PANE,
    _item,
    _item_toggle,
    _section,
    _section_toggle,
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


def _continuation_item(page: Page) -> tuple[Locator, str]:
    page.wait_for_function(
        """() => document.querySelector('[data-resume-pagination-ready="true"]')
          && document.querySelectorAll('[data-export-root="resume-page"]').length > 1"""
    )
    continuation = page.locator(
        '[data-slot="document-canvas-viewport"] '
        '[data-export-root="resume-page"] [data-resume-section-id="experience"]'
    ).nth(1)
    visible_heading = continuation.locator("h3").evaluate_all(
        """headings => headings.findIndex(heading => {
          const viewport = heading.closest('.resume-page-content-viewport')
            .getBoundingClientRect();
          const rect = heading.getBoundingClientRect();
          return rect.top >= viewport.top && rect.bottom <= viewport.bottom;
        })"""
    )
    assert visible_heading >= 0
    heading = continuation.locator("h3").nth(visible_heading)
    item_id = heading.evaluate(
        "element => element.closest('[data-resume-item-id]').dataset.resumeItemId"
    )
    assert item_id != "experience-1"
    return heading, item_id


def _expect_at_panel_top(item: Locator) -> None:
    item.page.wait_for_function(
        """element => {
          const panel = element.closest('.resume-editor-panel');
          const top = element.getBoundingClientRect().top
            - panel.getBoundingClientRect().top;
          const maximum = Math.max(0, panel.scrollHeight - panel.clientHeight);
          return Math.abs(top) < 2
            || (Math.abs(panel.scrollTop - maximum) < 2 && top >= -1
              && top + 48 <= panel.clientHeight);
        }""",
        arg=item.element_handle(),
        timeout=5_000,
    )


def _expect_below_sticky_header(page: Page, target: Locator) -> None:
    page.wait_for_function(
        """element => {
          const header = document.querySelector('.app-shell--document > header');
          const gap = element.getBoundingClientRect().top
            - header.getBoundingClientRect().bottom;
          return gap >= -1 && gap < 3;
        }""",
        arg=target.element_handle(),
        timeout=5_000,
    )
    box = target.bounding_box()
    header = page.locator(".app-shell--document > header").bounding_box()
    viewport = page.viewport_size
    assert box is not None and header is not None and viewport is not None
    assert header["y"] + header["height"] - 1 <= box["y"]
    assert box["y"] < header["y"] + header["height"] + 3
    assert box["y"] < viewport["height"]


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
def test_preview_item_navigation_opens_and_locates_entries_and_preserves_memory(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, _, _, messages = sorting_workspace
    pane = page.locator(PANE)
    experience = _section(page, "experience")
    toggle = _section_toggle(experience)
    preview = page.locator('[data-slot="document-canvas-viewport"]')
    heading, item_id = _continuation_item(page)
    target = _item(page, item_id)
    expect(toggle).to_have_attribute("aria-expanded", "false")
    heading.dblclick()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(_item_toggle(target)).to_have_attribute("aria-expanded", "true")
    expect(
        target.get_by_label(messages["fieldLabels"]["company"], exact=True)
    ).to_be_visible()
    _settle(page)
    _expect_at_panel_top(target)

    heading.dblclick()
    expect(_item_toggle(target)).to_have_attribute("aria-expanded", "true")
    _settle(page)
    _expect_at_panel_top(target)

    first_item = _item(page, "experience-1")
    first_item.evaluate(
        """element => {
          const panel = element.closest('.resume-editor-panel');
          window.editorNavigationComplete = false;
          const complete = () => {
            const top = element.getBoundingClientRect().top
              - panel.getBoundingClientRect().top;
            if (Math.abs(top) >= 2) return;
            panel.removeEventListener('scrollend', complete);
            window.editorNavigationComplete = true;
          };
          panel.addEventListener('scrollend', complete);
        }"""
    )
    preview.locator(
        '[data-export-root="resume-page"] [data-resume-item-id="experience-1"] h3'
    ).first.dblclick()
    expect(_item_toggle(first_item)).to_have_attribute("aria-expanded", "true")
    expect(_item_toggle(target)).to_have_attribute("aria-expanded", "true")
    _settle(page)
    _expect_at_panel_top(first_item)
    page.wait_for_function("window.editorNavigationComplete === true", timeout=5_000)
    pane.evaluate("element => { element.scrollTop = 360; }")
    expect(pane).to_have_js_property("scrollTop", 360)

    preview.locator(
        '[data-export-root="resume-page"] [data-resume-section-id="basic"] h1'
    ).first.dblclick()
    basic = page.get_by_role(
        "button",
        name=f"{messages['basicInfo']}: {messages['toggleSection']}",
        exact=True,
    )
    expect(basic).to_have_attribute("aria-expanded", "true")
    expect(toggle).to_have_attribute("aria-expanded", "false")
    _settle(page)

    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(_item_toggle(first_item)).to_have_attribute("aria-expanded", "true")
    expect(_item_toggle(target)).to_have_attribute("aria-expanded", "true")
    _settle(page)
    expect(pane).to_have_js_property("scrollTop", 360)
    assert first_item.get_by_label(
        messages["fieldLabels"]["company"], exact=True
    ).evaluate("element => document.activeElement !== element")

    heading.dblclick()
    expect(_item_toggle(target)).to_have_attribute("aria-expanded", "true")
    _settle(page)
    _expect_at_panel_top(target)

    preview.locator(
        '[data-export-root="resume-page"] [data-resume-section-id="experience"] '
        "[data-resume-section-header]"
    ).first.dblclick()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(_item_toggle(target)).to_have_attribute("aria-expanded", "true")
    _settle(page)
    _expect_at_panel_top(experience)

    basic.click()
    expect(basic).to_have_attribute("aria-expanded", "true")
    _settle(page)
    heading.dblclick()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(_item_toggle(target)).to_have_attribute("aria-expanded", "true")
    _settle(page)
    _expect_at_panel_top(target)


@pytest.mark.parametrize(
    "sorting_workspace",
    [
        {
            "width": 1100,
            "height": 850,
            "item_groups": 6,
            "reduced_motion": "reduce",
        },
        {
            "width": 375,
            "height": 850,
            "item_groups": 6,
            "reduced_motion": "reduce",
        },
        {"width": 430, "height": 850, "item_groups": 6},
    ],
    indirect=True,
    ids=["tablet", "phone-375", "phone-430-animated"],
)
def test_preview_item_navigation_brings_the_entry_into_view_in_stacked_layout(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, _, _, messages = sorting_workspace
    heading, item_id = _continuation_item(page)
    heading.dblclick()
    experience = _section(page, "experience")
    target = _item(page, item_id)
    expect(_section_toggle(experience)).to_have_attribute("aria-expanded", "true")
    expect(_item_toggle(target)).to_have_attribute("aria-expanded", "true")
    expect(
        target.get_by_label(messages["fieldLabels"]["company"], exact=True)
    ).to_be_visible()
    _settle(page)
    _expect_below_sticky_header(page, target)
    heading.dblclick()
    expect(_item_toggle(target)).to_have_attribute("aria-expanded", "true")
    _settle(page)
    _expect_below_sticky_header(page, target)


@pytest.mark.parametrize(
    "sorting_workspace",
    [{"width": 1440, "height": 870}, {"width": 375, "height": 850}],
    indirect=True,
    ids=["desktop", "phone"],
)
def test_preview_simple_list_row_locates_its_content_without_item_disclosure(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, base, resume_id, messages = sorting_workspace
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
    payload["resume"]["sections"].append(
        {
            "id": "skills",
            "kind": "simple_list",
            "title": "Skills",
            "items": [
                {
                    "id": "skills-1",
                    "content": "<ul><li>Python</li><li>TypeScript</li></ul>",
                }
            ],
        }
    )
    saved = page.request.put(f"{base}/api/resumes/{resume_id}", data=payload)
    assert saved.ok, saved.text()
    page.reload(wait_until="domcontentloaded")
    preview_row = (
        page.locator(
            '[data-slot="document-canvas-viewport"] '
            '[data-export-root="resume-page"] [data-resume-item-id="skills-1"] li'
        )
        .filter(has_text="TypeScript")
        .first
    )
    preview_row.dblclick()
    section = _section(page, "skills")
    expect(_section_toggle(section)).to_have_attribute("aria-expanded", "true")
    field = section.get_by_role(
        "textbox", name=messages["fieldLabels"]["content"], exact=True
    )
    expect(field).to_have_text("PythonTypeScript")
    expect(section.locator('[data-slot="editor-item-header"]')).to_have_count(0)
    _settle(page)
    target = _item(page, "skills-1")
    expect(target).to_be_visible()
    if page.viewport_size and page.viewport_size["width"] < 1280:
        _expect_below_sticky_header(page, target)
    else:
        _expect_at_panel_top(target)
