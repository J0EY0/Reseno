from __future__ import annotations

import os
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.e2e.test_resume_editor_sorting import (
    OVERLAY,
    _item,
    _item_action,
    _item_title,
    _item_toggle,
    _save_and_read,
    _section,
    _section_title,
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


@pytest.mark.parametrize(
    "sorting_workspace", [{"locale": "en"}, {"locale": "zh"}], indirect=True
)
def test_cold_section_menu_pointer_rename_remains_open(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, _, _, messages = sorting_workspace
    section = _section(page, "experience")
    more = section.get_by_role(
        "button", name=f"Experience: {messages['moreActions']}", exact=True
    )
    more.click()
    page.get_by_role(
        "menuitem", name=messages["renameSectionAction"], exact=True
    ).click()
    rename = page.get_by_role("textbox", name=messages["renameSection"], exact=True)
    expect(rename).to_be_focused()
    rename.fill("Selected Experience")
    _settle(page)
    expect(rename).to_be_focused()
    expect(rename).to_have_value("Selected Experience")
    expect(_section_title(section)).to_have_accessible_name("Selected Experience")
    rename.press("Escape")
    expect(rename).not_to_be_visible()
    expect(
        section.get_by_role(
            "button", name=f"Selected Experience: {messages['moreActions']}", exact=True
        )
    ).to_be_focused()


@pytest.mark.parametrize(
    "sorting_workspace", [{"locale": "en"}, {"locale": "zh"}], indirect=True
)
def test_section_rename_and_inline_rich_edits_survive_fold_move_and_reload(
    sorting_workspace: tuple[Page, str, str, dict[str, Any]],
) -> None:
    page, base, resume_id, messages = sorting_workspace
    section = _section(page, "experience")
    expect(section.locator('[data-slot="editor-card-header"]')).to_contain_text(
        f"3 {messages['itemCount']}"
    )
    expect(
        section.get_by_role("textbox", name=messages["renameSection"], exact=True)
    ).to_have_count(0)
    more = section.get_by_role(
        "button", name=f"Experience: {messages['moreActions']}", exact=True
    )
    more.focus()
    more.press("Enter")
    menu = page.get_by_role("menu")
    rename_action = menu.get_by_role(
        "menuitem", name=messages["renameSectionAction"], exact=True
    )
    expect(rename_action).to_be_focused()
    expect(_section_toggle(section)).to_have_attribute("aria-expanded", "false")
    page.keyboard.press("Escape")
    expect(menu).not_to_be_visible()
    expect(more).to_be_focused()
    more.press("Space")
    rename_action.press("Enter")
    rename = page.get_by_role("textbox", name=messages["renameSection"], exact=True)
    expect(rename).to_be_focused()
    rename.fill("Selected Experience")
    rename.press("Escape")
    expect(rename).not_to_be_visible()
    expect(_section_title(section)).to_have_accessible_name("Selected Experience")
    renamed_more = section.get_by_role(
        "button", name=f"Selected Experience: {messages['moreActions']}", exact=True
    )
    expect(renamed_more).to_be_focused()
    renamed_more.press("Enter")
    menu.get_by_role("menuitem", name=messages["deleteSection"], exact=True).press(
        "Enter"
    )
    dialog = page.get_by_role("alertdialog")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name=messages["cancel"], exact=True).press("Enter")
    expect(dialog).not_to_be_visible()
    expect(renamed_more).to_be_focused()
    expect(section).to_be_visible()
    expect(_section_toggle(section)).to_have_attribute("aria-expanded", "false")
    renamed_more.click()
    rename_action.click()
    expect(rename).to_be_focused()
    expect(rename).to_have_value("Selected Experience")
    rename.press("Escape")
    expect(rename).not_to_be_visible()
    expect(renamed_more).to_be_focused()
    _section_toggle(section).click()
    expect(_section_toggle(section)).to_have_attribute("aria-expanded", "true")

    item = _item(page, "experience-1")
    _item_toggle(item).click()
    company = item.get_by_role(
        "textbox", name=messages["fieldLabels"]["company"], exact=True
    )
    expect(company).to_have_count(1)
    expect(
        item.locator('[data-slot="editor-item-header"]').get_by_role(
            "textbox", name=messages["fieldLabels"]["company"], exact=True
        )
    ).to_have_count(1)
    renamed_more.click()
    rename_action.click()
    expect(rename).to_be_focused()
    description = item.get_by_role(
        "textbox", name=messages["fieldLabels"]["description"], exact=True
    )
    description.click()
    expect(rename).not_to_be_visible()
    expect(description).to_be_focused()
    company.fill("Atlas Research")
    expect(company).to_be_focused()
    expect(_item_toggle(item)).to_have_attribute("aria-expanded", "true")
    expect(page.locator(OVERLAY)).to_have_count(0)
    box = company.bounding_box()
    assert box is not None
    x, y = box["x"] + 2, box["y"] + box["height"] / 2
    page.mouse.move(x, y)
    page.mouse.down()
    page.mouse.move(x + 70, y, steps=8)
    page.mouse.up()
    expect(page.locator(OVERLAY)).to_have_count(0)
    assert page.evaluate("Boolean(window.getSelection()?.toString().trim())")
    company.press("ControlOrMeta+a")
    page.keyboard.press("Space")
    expect(company).to_be_focused()
    assert company.text_content() == " "
    expect(page.locator(OVERLAY)).to_have_count(0)
    company.fill("Atlas Research")

    body = item.get_by_role(
        "textbox", name=messages["fieldLabels"]["highlights"], exact=True
    )
    body.fill("Shipped a reliable resume editor")
    body.press("ControlOrMeta+a")
    item.get_by_role("button", name=messages["richTextBold"], exact=True).click()
    expect(body.locator("strong")).to_have_text("Shipped a reliable resume editor")
    expect(body).to_be_focused()
    item.get_by_role(
        "button", name=messages["richTextBulletedList"], exact=True
    ).click()
    expect(body.locator("ul > li strong")).to_have_text(
        "Shipped a reliable resume editor"
    )
    expect(body).to_be_focused()
    item.get_by_role(
        "button", name=messages["richTextMoreFormatting"], exact=True
    ).click()
    expect(body).to_be_focused()
    item.get_by_role("button", name=messages["richTextUnderline"], exact=True).click()
    expect(body.locator("u")).to_have_text("Shipped a reliable resume editor")

    expect(body).to_be_focused()
    item.get_by_role("button", name=messages["richTextUndo"], exact=True).click()
    expect(body.locator("u")).to_have_count(0)
    item.get_by_role("button", name=messages["richTextRedo"], exact=True).click()
    expect(body.locator("u")).to_have_text("Shipped a reliable resume editor")
    _item_action(item, messages["moveItemDown"]).click()
    _settle(page)
    expect(_item_toggle(item)).to_have_attribute("aria-expanded", "true")
    expect(company).to_have_text("Atlas Research")
    expect(body.locator("ul > li strong")).to_have_text(
        "Shipped a reliable resume editor"
    )
    _item_toggle(item).click()
    _settle(page)
    _item_toggle(item).click()
    expect(company).to_have_text("Atlas Research")
    expect(body.locator("ul > li strong")).to_have_text(
        "Shipped a reliable resume editor"
    )

    saved = _save_and_read(page, base, resume_id)
    experience = saved["sections"][0]
    assert experience["title"] == "Selected Experience"
    assert experience["items"][1]["id"] == "experience-1"
    assert experience["items"][1]["company"] == "Atlas Research"
    saved_highlights = "".join(experience["items"][1]["highlights"])
    assert "Shipped a reliable resume editor" in saved_highlights
    assert all(tag in saved_highlights for tag in ("<ul>", "<strong>", "<u>"))

    page.reload(wait_until="networkidle")
    expect(_section_title(section)).to_have_accessible_name("Selected Experience")
    _section_toggle(section).click()
    _item_toggle(item).click()
    expect(company).to_have_text("Atlas Research")
    expect(body.locator("ul > li strong")).to_have_text(
        "Shipped a reliable resume editor"
    )
    expect(body.locator("u")).to_have_text("Shipped a reliable resume editor")

    _settle(page)
    header = _item_title(item)
    header.scroll_into_view_if_needed()
    source = header.bounding_box()
    target = _item_title(_item(page, "experience-2")).bounding_box()
    assert source is not None and target is not None
    x, y = source["x"] + source["width"] / 3, source["y"] + 4
    page.mouse.move(x, y)
    page.mouse.down()
    try:
        page.mouse.move(x, y + 10, steps=2)
        expect(page.locator(OVERLAY)).to_be_visible()
        page.mouse.move(x, target["y"] + target["height"] / 2, steps=10)
    finally:
        page.mouse.up()
    expect(page.locator(OVERLAY)).to_have_count(0)
    _settle(page)
    expect(_item_toggle(item)).to_have_attribute("aria-expanded", "true")
    expect(company).to_have_text("Atlas Research")
    expect(body.locator("ul > li strong")).to_have_text(
        "Shipped a reliable resume editor"
    )
    saved = _save_and_read(page, base, resume_id)
    assert saved["sections"][0]["items"][0]["id"] == "experience-1"
