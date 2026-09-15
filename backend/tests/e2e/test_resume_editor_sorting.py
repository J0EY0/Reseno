from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Locator, Page, expect

from app.services.resume_document_contract import (
    ITEM_LIST_FIELDS_BY_KIND,
    ITEM_STRING_FIELDS_BY_KIND,
)
from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]

PANE = ".resume-editor-panel"
SECTION = "[data-resume-section-id]"
ITEM = "[data-resume-item-id]"
SORT_TRIGGER = '[data-slot="editor-sort-trigger"]'
OVERLAY = '[data-slot="editor-drag-overlay"]'


@pytest.fixture
def sorting_workspace(
    browser: Browser,
    workspace_servers: tuple[str, str],
    request: pytest.FixtureRequest,
) -> Iterator[tuple[Page, str, str, dict[str, Any]]]:
    options = getattr(request, "param", {})
    locale = options.get("locale", "en")
    base, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN" if locale == "zh" else "en-US",
        viewport={
            "width": options.get("width", 1440),
            "height": options.get("height", 1100),
        },
        reduced_motion=options.get("reduced_motion", "no-preference"),
        has_touch=options.get("touch", False),
        is_mobile=options.get("touch", False),
    )
    context.add_init_script(f"localStorage.setItem('reseno-locale', '{locale}')")
    messages = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / f"frontend/src/i18n/locales/{locale}.json"
        ).read_text(encoding="utf-8")
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        response = page.request.post(
            f"{base}/api/resumes",
            data={"documentLocale": "en", "template": "minimal", "title": "Sorting"},
        )
        assert response.ok, response.text()
        created = response.json()["data"]["resume"]
        payload = {
            key: created[key]
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
        payload["resume"]["basic"]["name"] = "Taylor Morgan"
        payload["resume"]["sections"] = [
            {
                "id": "experience",
                "kind": "experience",
                "title": "Experience",
                "items": [
                    {
                        "id": f"experience-{index}",
                        "company": company,
                        "position": "Engineer",
                        "location": "",
                        "period": "",
                        "description": "",
                        "highlights": [],
                    }
                    for index, company in enumerate(
                        ("Atlas Lab", "Beacon Studio", "Cedar Works")
                        * options.get("item_groups", 1),
                        start=1,
                    )
                ],
            },
            {"id": "education", "kind": "education", "title": "Education", "items": []},
            {"id": "project", "kind": "project", "title": "Projects", "items": []},
        ]
        resume_id = created["id"]
        saved = page.request.put(f"{base}/api/resumes/{resume_id}", data=payload)
        assert saved.ok, saved.text()
        page.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        expect(page.locator(PANE)).to_be_visible()
        expect(page.locator(f"{PANE} {SECTION}")).to_have_count(3)
        yield page, base, resume_id, messages
        assert errors == []
    finally:
        context.close()


def _section(page: Page, section_id: str) -> Locator:
    return page.locator(f'{PANE} [data-resume-section-id="{section_id}"]')


def _item(page: Page, item_id: str) -> Locator:
    return page.locator(f'{PANE} [data-resume-item-id="{item_id}"]')


def _section_title(section: Locator) -> Locator:
    return section.locator('[data-slot="editor-card-header"]').locator(SORT_TRIGGER)


def _item_title(item: Locator) -> Locator:
    return item.locator('[data-slot="editor-item-header"]').locator(SORT_TRIGGER)


def _section_toggle(section: Locator) -> Locator:
    return section.locator('[data-slot="editor-card-header"]').locator(
        '[data-slot="editor-toggle-trigger"]'
    )


def _item_toggle(item: Locator) -> Locator:
    return item.locator('[data-slot="editor-item-header"]').locator(
        '[data-slot="editor-toggle-trigger"]'
    )


def _expect_order(elements: Locator, attribute: str, ids: list[str]) -> None:
    expect(elements).to_have_count(len(ids))
    for index, expected_id in enumerate(ids):
        expect(elements.nth(index)).to_have_attribute(attribute, expected_id)


def _settle(page: Page) -> None:
    page.locator(PANE).evaluate(
        """async element => {
          await new Promise(resolve => requestAnimationFrame(resolve));
          await Promise.all(element.getAnimations({subtree: true})
            .filter(animation => animation.effect?.getTiming().iterations !== Infinity)
            .map(animation => animation.finished.catch(() => {})));
          await new Promise(resolve => requestAnimationFrame(resolve));
        }"""
    )


def _drag(page: Page, source: Locator, target: Locator) -> None:
    source.scroll_into_view_if_needed()
    source_box = source.bounding_box()
    target_box = target.bounding_box()
    assert source_box is not None and target_box is not None
    x = source_box["x"] + source_box["width"] / 3
    y = source_box["y"] + source_box["height"] / 2
    target_y = target_box["y"] + target_box["height"] * 0.8
    page.mouse.move(x, y)
    page.mouse.down()
    try:
        page.mouse.move(x, y + 10, steps=2)
        expect(page.locator(OVERLAY)).to_be_visible()
        page.mouse.move(x, target_y, steps=12)
    finally:
        page.mouse.up()
    expect(page.locator(OVERLAY)).to_have_count(0)
    _settle(page)


def _save_and_read(page: Page, base: str, resume_id: str) -> dict[str, Any]:
    with page.expect_response(
        lambda response: (
            response.request.method == "PUT"
            and urlparse(response.url).path == f"/api/resumes/{resume_id}"
        )
    ) as saving:
        page.keyboard.press("ControlOrMeta+s")
    assert saving.value.ok, saving.value.text()
    response = page.request.get(f"{base}/api/resumes/{resume_id}")
    assert response.ok, response.text()
    return response.json()["data"]["resume"]["resume"]


def _item_action(item: Locator, label: str) -> Locator:
    return item.get_by_role("button", name=re.compile(f"^{re.escape(label)} \\d+$"))


def _effective_opacity(locator: Locator) -> float:
    return float(
        locator.evaluate(
            """element => {
              let opacity = 1;
              for (let node = element; node; node = node.parentElement) {
                const style = getComputedStyle(node);
                if (style.visibility === 'hidden' || style.display === 'none') return 0;
                opacity *= Number(style.opacity);
              }
              return opacity;
            }"""
        )
    )


@pytest.mark.parametrize(
    "sorting_workspace",
    [{"locale": "en", "width": 1280}, {"locale": "zh", "width": 1280}],
    indirect=True,
    ids=["english", "chinese"],
)
def test_item_titles_show_primary_fields_without_clipping_controls_or_losing_focus(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, base, resume_id, messages = sorting_workspace
    chinese = messages["itemCountSingular"] == "条目"
    long_name = (
        "星河科技与人工智能研究中心企业级数据分析平台及基础设施研发团队"
        if chinese
        else "Atlas & Beacon Research Institute for Distributed Systems "
        "and Infrastructure"
    )
    fields = [
        ("education", "school", "school", "Northbridge University"),
        ("experience", "company", "company", long_name),
        ("project", "name", "projectName", "Reseno <Lab>"),
        ("publication", "title", "publicationTitle", "Reliable Systems Research"),
        ("achievement", "name", "achievementName", "Research Excellence Award"),
    ]
    response = page.request.get(f"{base}/api/resumes/{resume_id}")
    assert response.ok, response.text()
    data = response.json()["data"]["resume"]
    payload = {
        key: data[key]
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
    sections = []
    for kind, field, _, name in fields:
        escaped_name = (
            name.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        items = []
        for index, value in enumerate(
            (f"<p><strong>{escaped_name}</strong></p>", "<p> </p>"), start=1
        ):
            items.append(
                {
                    **{key: "" for key in ITEM_STRING_FIELDS_BY_KIND[kind]},
                    **{key: [] for key in ITEM_LIST_FIELDS_BY_KIND[kind]},
                    "id": f"{kind}-{index}",
                    field: value,
                }
            )
        sections.append(
            {"id": kind, "kind": kind, "title": kind.title(), "items": items}
        )
    payload["resume"]["sections"] = sections
    response = page.request.put(f"{base}/api/resumes/{resume_id}", data=payload)
    assert response.ok, response.text()
    page.reload(wait_until="networkidle")

    for kind, _, field_label, name in fields:
        section = _section(page, kind)
        _section_toggle(section).click()
        _settle(page)
        item = _item(page, f"{kind}-1")
        title = _item_title(item)
        expect(title).to_have_text(name)
        expect(title).to_have_accessible_name(name)
        expect(title.locator("strong, p")).to_have_count(0)
        expect(_item_title(_item(page, f"{kind}-2"))).to_have_text(
            f"{messages['itemCountSingular']} 2"
        )
        if kind == "experience":
            geometry = title.evaluate(
                """title => {
                  const label = title.querySelector('span');
                  const range = document.createRange();
                  range.selectNodeContents(label);
                  const text = range.getBoundingClientRect();
                  const rect = label.getBoundingClientRect();
                  const style = getComputedStyle(label);
                  const header = title.closest('[data-slot="editor-item-header"]');
                  const bounds = header.getBoundingClientRect();
                  return {
                    clipped: text.width > rect.width + 1,
                    singleLine: rect.height <= parseFloat(style.lineHeight) + 1,
                    ellipsis: style.textOverflow,
                    withinRow: Array.from(header.querySelectorAll('button')).every(
                      button => {
                        const box = button.getBoundingClientRect();
                        return box.left >= bounds.left - 1 &&
                          box.right <= bounds.right + 1 &&
                          box.top >= bounds.top - 1 && box.bottom <= bounds.bottom + 1;
                      }
                    ),
                  };
                }"""
            )
            assert geometry == {
                "clipped": True,
                "singleLine": True,
                "ellipsis": "ellipsis",
                "withinRow": True,
            }
            instructions = title.evaluate(
                "element => element.getAttribute('aria-describedby').split(' ')"
                ".map(id => document.getElementById(id)?.textContent).join(' ')"
            )
            assert (
                "按空格开始排序" if chinese else "Press Space to start sorting"
            ) in (instructions)
            title.hover()
            tooltip = page.get_by_role("tooltip", name=name, exact=True)
            tooltip_surface = page.locator('[data-slot="tooltip-content"]').filter(
                has=tooltip
            )
            expect(tooltip_surface).to_be_visible()
            expect(tooltip).to_have_text(name)
            expect(title).to_have_accessible_description(
                re.compile(re.escape(instructions))
            )
            page.mouse.move(1278, 10)
            page.keyboard.press("Escape")
            _item_toggle(item).focus()
            for _ in range(5):
                page.keyboard.press("Shift+Tab")
                if title.evaluate("element => element === document.activeElement"):
                    break
            expect(title).to_be_focused()
            expect(tooltip_surface).to_be_visible()
            expect(tooltip).to_have_text(name)
            title.press("Space")
            expect(page.locator(OVERLAY)).to_have_text(name)
            expect(tooltip_surface).not_to_be_visible()
            page.keyboard.press("Escape")
            expect(page.locator(OVERLAY)).to_have_count(0)
            expect(title).to_be_focused()

        _item_toggle(item).click()
        field = item.get_by_role(
            "textbox", name=messages["fieldLabels"][field_label], exact=True
        )
        field_node = field.element_handle()
        assert field_node is not None
        field.click()
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.type(f"Updated {kind}")
        expect(title).to_have_text(f"Updated {kind}")
        expect(field).to_be_focused()
        assert field_node.evaluate("element => element.isConnected")
        page.keyboard.type(" continued")
        expect(title).to_have_accessible_name(f"Updated {kind} continued")
        expect(field).to_be_focused()
        assert field_node.evaluate("element => element.isConnected")
        _section_toggle(section).click()
        _settle(page)
    document = _save_and_read(page, base, resume_id)
    for section, (kind, field, _, _) in zip(document["sections"], fields, strict=True):
        assert f"Updated {kind} continued" in section["items"][0][field]


def test_only_collapse_arrows_toggle_sections_and_items(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, _, _, messages = sorting_workspace
    experience = _section(page, "experience")
    title = _section_title(experience)
    toggle = _section_toggle(experience)
    delete = experience.get_by_role(
        "button", name=f"Experience: {messages['deleteSection']}", exact=True
    )
    basic_toggle = page.locator(PANE).get_by_role(
        "button",
        name=f"{messages['basicInfo']}: {messages['toggleSection']}",
        exact=True,
    )
    page.mouse.move(1438, 10)
    basic_toggle.focus()
    _settle(page)
    assert _effective_opacity(delete) == pytest.approx(1)
    expect(title).to_have_accessible_name("Experience")

    def assert_title_is_inert(title: Locator, toggle: Locator) -> None:
        expanded = toggle.get_attribute("aria-expanded")
        assert title.get_attribute("aria-expanded") is None
        assert title.get_attribute("aria-controls") is None
        title.click()
        expect(toggle).to_have_attribute("aria-expanded", expanded)
        if title.locator("svg").count():
            title.locator("svg").click()
            expect(toggle).to_have_attribute("aria-expanded", expanded)
        box = title.bounding_box()
        assert box is not None
        page.mouse.click(box["x"] + box["width"] - 2, box["y"] + box["height"] - 2)
        expect(toggle).to_have_attribute("aria-expanded", expanded)
        header = title.locator(
            'xpath=ancestor::*[@data-slot="editor-card-header" or '
            '@data-slot="editor-item-header"][1]'
        )
        header_box = header.bounding_box()
        assert header_box is not None
        header.click(position={"x": 4, "y": header_box["height"] / 2})
        expect(toggle).to_have_attribute("aria-expanded", expanded)
        if title.evaluate("element => element.tagName") == "BUTTON":
            title.press("Enter")
            expect(toggle).to_have_attribute("aria-expanded", expanded)
        else:
            assert title.evaluate("element => element.tabIndex") == -1
        expect(page.locator(OVERLAY)).to_have_count(0)

    def exercise_toggle(title: Locator, toggle: Locator) -> None:
        expect(toggle).to_have_attribute("data-slot", "editor-toggle-trigger")
        assert toggle.evaluate("element => getComputedStyle(element).cursor") == (
            "pointer"
        )
        assert_title_is_inert(title, toggle)
        if title.evaluate("element => element.tagName") == "BUTTON":
            title.focus()
            for _ in range(5):
                page.keyboard.press("Tab")
                if toggle.evaluate("element => element === document.activeElement"):
                    break
        else:
            toggle.focus()
        expect(toggle).to_be_focused()
        toggle.press("Space")
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(page.locator(OVERLAY)).to_have_count(0)
        expect(toggle).to_be_focused()
        toggle.press("Enter")
        expect(toggle).to_have_attribute("aria-expanded", "false")
        expect(page.locator(OVERLAY)).to_have_count(0)
        toggle.click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        _settle(page)
        assert_title_is_inert(title, toggle)

    basic_title = page.locator(f'{PANE} [data-slot="editor-title"]')
    exercise_toggle(basic_title, basic_toggle)
    basic_toggle.click()
    _settle(page)
    exercise_toggle(title, toggle)
    first = _item(page, "experience-1")
    item_delete = _item_action(first, messages["removeItem"])
    page.mouse.move(1438, 10)
    basic_toggle.focus()
    _settle(page)
    assert _effective_opacity(item_delete) == pytest.approx(1)
    exercise_toggle(_item_title(first), _item_toggle(first))
    expect(
        first.get_by_role(
            "textbox", name=messages["fieldLabels"]["company"], exact=True
        )
    ).to_have_text("Atlas Lab")
    _expect_order(
        page.locator(f"{PANE} {SECTION}"),
        "data-resume-section-id",
        ["experience", "education", "project"],
    )
    _expect_order(
        experience.locator(ITEM),
        "data-resume-item-id",
        ["experience-1", "experience-2", "experience-3"],
    )


@pytest.mark.parametrize(
    "sorting_workspace",
    [{"reduced_motion": "no-preference"}, {"reduced_motion": "reduce"}],
    indirect=True,
    ids=["motion", "reduced-motion"],
)
def test_pointer_sorting_preserves_content_and_persists_section_and_entry_order(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, base, resume_id, messages = sorting_workspace
    sections = page.locator(f"{PANE} {SECTION}")
    experience = _section(page, "experience")
    basic = page.locator(PANE).get_by_role(
        "button",
        name=f"{messages['basicInfo']}: {messages['toggleSection']}",
        exact=True,
    )
    basic_node = basic.element_handle()
    assert basic_node is not None
    _drag(page, _section_title(experience), _section_title(_section(page, "project")))
    _expect_order(
        sections, "data-resume-section-id", ["education", "project", "experience"]
    )
    assert basic_node.evaluate("element => element.isConnected")
    assert basic.evaluate(
        """element => Boolean(element.compareDocumentPosition(
          document.querySelector('.resume-editor-panel [data-resume-section-id]')
        ) & Node.DOCUMENT_POSITION_FOLLOWING)"""
    )

    title = _section_title(experience)
    box = title.bounding_box()
    assert box is not None
    x, y = box["x"] + box["width"] / 3, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 3, y + 2)
    page.mouse.up()
    expect(_section_toggle(experience)).to_have_attribute("aria-expanded", "false")
    expect(page.locator(OVERLAY)).to_have_count(0)
    _section_toggle(experience).click()
    first = _item(page, "experience-1")
    _item_toggle(first).click()
    company = first.get_by_role(
        "textbox", name=messages["fieldLabels"]["company"], exact=True
    )
    expect(company).to_be_visible()
    company.fill("Atlas Lab — retained edit")
    _settle(page)
    box = company.bounding_box()
    assert box is not None
    page.mouse.move(box["x"] + 8, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(box["x"] + 70, box["y"] + box["height"] / 2, steps=5)
    page.mouse.up()
    expect(page.locator(OVERLAY)).to_have_count(0)
    expect(company).to_have_text("Atlas Lab — retained edit")
    _settle(page)
    section_actions = experience.get_by_role(
        "button", name=f"Experience: {messages['moveSectionUp']}", exact=True
    )
    entry_actions = _item_action(first, messages["moveItemDown"])
    section_opacity = _effective_opacity(section_actions)
    entry_opacity = _effective_opacity(entry_actions)
    assert section_opacity > 0
    assert entry_opacity > 0
    section_color = section_actions.evaluate(
        "element => getComputedStyle(element).color"
    )
    entry_color = entry_actions.evaluate("element => getComputedStyle(element).color")
    entry_actions.hover()
    _settle(page)
    assert (
        _effective_opacity(entry_actions) > entry_opacity
        or entry_actions.evaluate("element => getComputedStyle(element).color")
        != entry_color
    )
    assert _effective_opacity(section_actions) == pytest.approx(section_opacity)
    assert (
        section_actions.evaluate("element => getComputedStyle(element).color")
        == section_color
    )
    _item_toggle(first).click()
    _settle(page)
    _drag(page, _item_title(first), _item_title(_item(page, "experience-3")))
    _expect_order(
        experience.locator(ITEM),
        "data-resume-item-id",
        ["experience-2", "experience-3", "experience-1"],
    )
    _expect_order(
        sections, "data-resume-section-id", ["education", "project", "experience"]
    )
    _item_toggle(first).click()
    expect(company).to_have_text("Atlas Lab — retained edit")

    document = _save_and_read(page, base, resume_id)
    assert [section["id"] for section in document["sections"]] == [
        "education",
        "project",
        "experience",
    ]
    assert document["basic"]["name"] == "Taylor Morgan"
    assert [item["id"] for item in document["sections"][-1]["items"]] == [
        "experience-2",
        "experience-3",
        "experience-1",
    ]
    assert "retained edit" in document["sections"][-1]["items"][-1]["company"]
    page.reload(wait_until="networkidle")
    _expect_order(
        sections, "data-resume-section-id", ["education", "project", "experience"]
    )
    _section_toggle(experience).click()
    _expect_order(
        experience.locator(ITEM),
        "data-resume-item-id",
        ["experience-2", "experience-3", "experience-1"],
    )
    _item_toggle(first).click()
    expect(company).to_have_text("Atlas Lab — retained edit")


def test_keyboard_sorting_and_row_actions_keep_delete_undo_working(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, base, resume_id, messages = sorting_workspace
    experience = _section(page, "experience")
    title = _section_title(experience)
    title.focus()
    title.press("Space")
    expect(page.locator(OVERLAY)).to_be_visible()
    _settle(page)
    page.keyboard.press("ArrowDown")
    _settle(page)
    page.keyboard.press("Escape")
    expect(page.locator(OVERLAY)).to_have_count(0)
    _expect_order(
        page.locator(f"{PANE} {SECTION}"),
        "data-resume-section-id",
        ["experience", "education", "project"],
    )
    expect(title).to_be_focused()
    title.press("Space")
    expect(page.locator(OVERLAY)).to_be_visible()
    _settle(page)
    page.keyboard.press("ArrowDown")
    _settle(page)
    page.keyboard.press("Space")
    _expect_order(
        page.locator(f"{PANE} {SECTION}"),
        "data-resume-section-id",
        ["education", "experience", "project"],
    )
    expect(title).to_be_focused()
    _section_toggle(experience).press("Enter")
    expect(_section_toggle(experience)).to_have_attribute("aria-expanded", "true")
    _settle(page)
    first = _item(page, "experience-1")
    entry_title = _item_title(first)
    entry_title.focus()
    entry_title.press("Space")
    expect(page.locator(OVERLAY)).to_be_visible()
    _settle(page)
    page.keyboard.press("ArrowDown")
    _settle(page)
    page.keyboard.press("Space")
    _expect_order(
        experience.locator(ITEM),
        "data-resume-item-id",
        ["experience-2", "experience-1", "experience-3"],
    )
    entry_title.focus()
    _settle(page)
    up = _item_action(first, messages["moveItemUp"])
    assert _effective_opacity(up) == pytest.approx(1)
    up.focus()
    up.press("Enter")
    _expect_order(
        experience.locator(ITEM),
        "data-resume-item-id",
        ["experience-1", "experience-2", "experience-3"],
    )
    down = _item_action(first, messages["moveItemDown"])
    down.focus()
    down.press("Enter")
    _expect_order(
        experience.locator(ITEM),
        "data-resume-item-id",
        ["experience-2", "experience-1", "experience-3"],
    )
    delete = _item_action(first, messages["removeItem"])
    delete.focus()
    delete.press("Enter")
    expect(first).to_have_count(0)
    undo = page.locator("[data-sonner-toast]").get_by_role(
        "button", name=messages["undoAction"], exact=True
    )
    undo.focus()
    undo.press("Enter")
    _expect_order(
        experience.locator(ITEM),
        "data-resume-item-id",
        ["experience-2", "experience-1", "experience-3"],
    )
    _item_toggle(first).press("Enter")
    expect(
        first.get_by_role(
            "textbox", name=messages["fieldLabels"]["company"], exact=True
        )
    ).to_have_text("Atlas Lab")
    education = _section(page, "education")
    _section_title(education).focus()
    delete_section = education.get_by_role(
        "button", name=f"Education: {messages['deleteSection']}", exact=True
    )
    delete_section.focus()
    delete_section.press("Enter")
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name=messages["deleteSection"], exact=True).press(
        "Enter"
    )
    expect(education).to_have_count(0)
    document = _save_and_read(page, base, resume_id)
    assert [section["id"] for section in document["sections"]] == [
        "experience",
        "project",
    ]
    assert [item["id"] for item in document["sections"][0]["items"]] == [
        "experience-2",
        "experience-1",
        "experience-3",
    ]


@pytest.mark.parametrize(
    "sorting_workspace", [{"locale": "zh", "width": 390, "touch": True}], indirect=True
)
def test_touch_title_and_move_delete_actions_work_without_hover(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, base, resume_id, messages = sorting_workspace
    experience = _section(page, "experience")
    title = _section_title(experience)
    _section_toggle(experience).tap()
    expect(_section_toggle(experience)).to_have_attribute("aria-expanded", "true")
    first = _item(page, "experience-1")
    _item_toggle(first).tap()
    company = first.get_by_role(
        "textbox", name=messages["fieldLabels"]["company"], exact=True
    )
    company.fill("移动端内容保留")
    _item_toggle(first).tap()
    down = _item_action(first, messages["moveItemDown"])
    assert _effective_opacity(down) > 0
    down.tap()
    _expect_order(
        experience.locator(ITEM),
        "data-resume-item-id",
        ["experience-2", "experience-1", "experience-3"],
    )
    up = _item_action(first, messages["moveItemUp"])
    up.tap()
    _expect_order(
        experience.locator(ITEM),
        "data-resume-item-id",
        ["experience-1", "experience-2", "experience-3"],
    )
    _item_action(first, messages["removeItem"]).tap()
    expect(first).to_have_count(0)
    page.locator("[data-sonner-toast]").get_by_role(
        "button", name=messages["undoAction"], exact=True
    ).tap()
    _expect_order(
        experience.locator(ITEM),
        "data-resume-item-id",
        ["experience-1", "experience-2", "experience-3"],
    )
    _item_toggle(first).tap()
    expect(company).to_have_text("移动端内容保留")
    _section_toggle(experience).tap()
    move_section = experience.get_by_role(
        "button", name=f"Experience: {messages['moveSectionDown']}", exact=True
    )
    assert _effective_opacity(move_section) > 0
    move_section.tap()
    _expect_order(
        page.locator(f"{PANE} {SECTION}"),
        "data-resume-section-id",
        ["education", "experience", "project"],
    )
    expect(page.locator(OVERLAY)).to_have_count(0)
    title.scroll_into_view_if_needed()
    source_box = title.bounding_box()
    target_box = _section_title(_section(page, "project")).bounding_box()
    assert source_box is not None and target_box is not None
    x = source_box["x"] + source_box["width"] / 3
    start_y = source_box["y"] + source_box["height"] / 2
    end_y = target_box["y"] + target_box["height"] * 0.8
    touch = page.context.new_cdp_session(page)
    try:
        touch.send(
            "Input.dispatchTouchEvent",
            {"type": "touchStart", "touchPoints": [{"x": x, "y": start_y}]},
        )
        expect(page.locator(OVERLAY)).to_be_visible()
        for step in range(1, 9):
            touch.send(
                "Input.dispatchTouchEvent",
                {
                    "type": "touchMove",
                    "touchPoints": [
                        {"x": x, "y": start_y + (end_y - start_y) * step / 8}
                    ],
                },
            )
    finally:
        touch.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        touch.detach()
    expect(page.locator(OVERLAY)).to_have_count(0)
    _expect_order(
        page.locator(f"{PANE} {SECTION}"),
        "data-resume-section-id",
        ["education", "project", "experience"],
    )
    document = _save_and_read(page, base, resume_id)
    assert "移动端内容保留" in document["sections"][2]["items"][0]["company"]


@pytest.mark.parametrize(
    "sorting_workspace", [{"height": 720, "item_groups": 5}], indirect=True
)
def test_dragging_a_long_entry_list_scrolls_and_saves_the_new_order(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, base, resume_id, _ = sorting_workspace
    experience = _section(page, "experience")
    _section_toggle(experience).click()
    _settle(page)
    source = _item_title(_item(page, "experience-1"))
    source.scroll_into_view_if_needed()
    source_box = source.bounding_box()
    pane_box = page.locator(PANE).bounding_box()
    assert source_box is not None and pane_box is not None
    assert page.locator(PANE).evaluate(
        "element => element.scrollHeight > element.clientHeight"
    )
    x = source_box["x"] + source_box["width"] / 3
    y = source_box["y"] + source_box["height"] / 2
    initial_scroll = page.locator(PANE).evaluate("element => element.scrollTop")
    page.mouse.move(x, y)
    page.mouse.down()
    try:
        page.mouse.move(x, y + 10, steps=2)
        expect(page.locator(OVERLAY)).to_be_visible()
        page.mouse.move(x, pane_box["y"] + pane_box["height"] - 12, steps=12)
        page.wait_for_function(
            """initial =>
              document.querySelector('.resume-editor-panel').scrollTop > initial + 300
            """,
            arg=initial_scroll,
        )
    finally:
        page.mouse.up()
    expect(page.locator(OVERLAY)).to_have_count(0)
    _settle(page)
    order = experience.locator(ITEM).evaluate_all(
        "elements => elements.map(element => element.dataset.resumeItemId)"
    )
    assert order.index("experience-1") > 5
    assert [item_id for item_id in order if item_id != "experience-1"] == [
        f"experience-{index}" for index in range(2, 16)
    ]
    document = _save_and_read(page, base, resume_id)
    assert [section["id"] for section in document["sections"]] == [
        "experience",
        "education",
        "project",
    ]
    assert [item["id"] for item in document["sections"][0]["items"]] == order
