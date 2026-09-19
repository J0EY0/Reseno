from __future__ import annotations

import os
from typing import Any

import pytest
from playwright.sync_api import Browser, Locator, Page, Route, expect

from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]

SECTION_FIELDS = [
    ("experience", "公司 / 组织"),
    ("education", "学校"),
    ("project", "项目名称"),
    ("publication", "论文标题"),
    ("achievement", "证书 / 荣誉名称"),
]
ADD_ITEM_LABELS = {
    "education": "添加教育经历",
    "experience": "添加工作经历",
    "project": "添加项目",
    "publication": "添加论文",
    "achievement": "添加奖项",
}


def _create_resume(page: Page, base: str, *, existing_item: bool) -> str:
    response = page.request.post(
        f"{base}/api/resumes",
        data={"documentLocale": "en", "template": "minimal"},
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
    items: list[dict[str, Any]] = []
    if existing_item:
        items.append(
            {
                "id": "existing-experience",
                "company": "Existing company",
                "position": "Engineer",
                "location": "",
                "period": "",
                "description": "",
                "highlights": [],
            }
        )
    payload["resume"]["sections"] = [
        {
            "id": kind,
            "kind": kind,
            "title": kind.title(),
            "items": items if kind == "experience" else [],
        }
        for kind, _ in SECTION_FIELDS
    ]
    saved = page.request.put(f"{base}/api/resumes/{created['id']}", data=payload)
    assert saved.ok, saved.text()
    return str(created["id"])


def _open_section(page: Page, title: str) -> Locator:
    toggle = page.get_by_role("button", name=f"{title}: 展开或收起模块", exact=True)
    if toggle.get_attribute("aria-expanded") != "true":
        toggle.click()
    return toggle.locator("xpath=ancestor::*[@data-resume-section-id][1]")


def _settle_animations(card: Locator) -> None:
    card.evaluate(
        """async element => {
          await Promise.all(element.getAnimations({subtree: true}).map(
            animation => animation.finished.catch(() => {})
          ));
        }"""
    )


@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
def test_new_resume_items_receive_keyboard_input_without_an_extra_click(
    browser: Browser,
    workspace_servers: tuple[str, str],
    reduced_motion: str,
) -> None:
    base, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 1000},
        reduced_motion=reduced_motion,
    )
    page = context.new_page()
    try:
        resume_id = _create_resume(page, base, existing_item=False)
        page.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        for kind, field_label in SECTION_FIELDS:
            card = _open_section(page, kind.title())
            add = card.get_by_role("button", name=ADD_ITEM_LABELS[kind], exact=True)
            for index in (1, 2):
                add.click()
                expect(card.locator("h4")).to_have_count(index)
                field = card.get_by_role("textbox", name=field_label, exact=True).last
                expect(field).to_be_visible()
                expect(field).to_be_focused()
                page.keyboard.type(f"Entry {index}")
                expect(field).to_have_text(f"Entry {index}")
                _settle_animations(card)
                expect(field).to_be_focused()
                page.keyboard.type(" continued")
                expect(field).to_have_text(f"Entry {index} continued")

            toggle = card.get_by_role("button", name="展开或收起条目 2", exact=True)
            toggle.click()
            _settle_animations(card)
            toggle.click()
            _settle_animations(card)
            expect(toggle).to_be_focused()
            expect(field).not_to_be_focused()
            expect(field).to_have_text("Entry 2 continued")
    finally:
        context.close()


@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
def test_expanding_existing_resume_item_keeps_focus_on_its_toggle(
    browser: Browser,
    workspace_servers: tuple[str, str],
    reduced_motion: str,
) -> None:
    base, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 1000},
        reduced_motion=reduced_motion,
    )
    page = context.new_page()
    try:
        resume_id = _create_resume(page, base, existing_item=True)
        page.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        card = _open_section(page, "Experience")
        toggle = card.get_by_role("button", name="展开或收起条目 1", exact=True)
        expect(toggle).to_have_attribute("aria-expanded", "false")
        toggle.focus()
        page.keyboard.press("Enter")
        field = card.get_by_role("textbox", name="公司 / 组织", exact=True)
        expect(field).to_be_visible()
        _settle_animations(card)
        expect(toggle).to_be_focused()
        expect(field).not_to_be_focused()
        expect(field).to_have_text("Existing company")
    finally:
        context.close()


@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
def test_loading_new_item_editor_does_not_reclaim_user_moved_focus(
    browser: Browser,
    workspace_servers: tuple[str, str],
    reduced_motion: str,
) -> None:
    base, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 1000},
        reduced_motion=reduced_motion,
    )
    page = context.new_page()
    blocked: list[Route] = []
    released = False

    def defer_editor(route: Route) -> None:
        if released:
            route.continue_()
        else:
            blocked.append(route)

    page.route("**/inline-text-editor.tsx*", defer_editor)
    try:
        resume_id = _create_resume(page, base, existing_item=False)
        page.goto(f"{base}/resume/{resume_id}", wait_until="domcontentloaded")
        card = _open_section(page, "Experience")
        card.get_by_role("button", name="添加工作经历", exact=True).click()
        expect(card.locator("h4")).to_have_count(1)
        field = card.get_by_role("textbox", name="公司 / 组织", exact=True)
        expect(field).to_have_count(0)
        assert blocked, "the lazy inline editor request must be held before focus moves"
        toggle = page.get_by_role(
            "button", name="Experience: 展开或收起模块", exact=True
        )
        toggle.focus()
        released = True
        for route in blocked:
            route.continue_()
        page.wait_for_function(
            "element => element.editor?.isInitialized === true",
            arg=field.element_handle(),
        )
        page.evaluate("() => new Promise(requestAnimationFrame)")
        expect(field).to_be_visible()
        _settle_animations(card)
        expect(toggle).to_be_focused()
        expect(field).not_to_be_focused()
    finally:
        context.close()
