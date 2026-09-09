"""Inline resume formatting through editing, previews, persistence, and export."""

from __future__ import annotations

import io
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Browser, Locator, Page, expect
from pypdf import PdfReader

from app.services.pdf import _wait_for_resume_render
from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _create_resume(page: Page, base: str) -> dict[str, Any]:
    response = page.request.post(
        f"{base}/api/resumes",
        data={
            "documentLocale": "en",
            "title": "Inline formatting",
            "template": "academic",
        },
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
    payload["resume"]["basic"]["name"] = "Jane Doe"
    payload["resume"]["basic"]["headline"] = ""
    payload["resume"]["basic"]["summary"] = ""
    payload["resume"]["sections"] = [
        {
            "id": "experience",
            "kind": "experience",
            "title": "Experience",
            "items": [
                {
                    "id": "experience-1",
                    "company": "Research Lab",
                    "position": "Research Assistant",
                    "location": "Taipei",
                    "period": "2024 - 2026",
                    "description": "",
                    "highlights": [],
                }
            ],
        },
        {
            "id": "publication",
            "kind": "publication",
            "title": "Publications",
            "items": [
                {
                    "id": "publication-1",
                    "title": "Interactive Systems",
                    "authors": "Jane Doe1",
                    "venue": "H2O Journal",
                    "date": "2026",
                    "url": "https://example.org/paper",
                    "description": "",
                }
            ],
        },
    ]
    saved = page.request.put(f"{base}/api/resumes/{created['id']}", data=payload)
    assert saved.ok, saved.text()
    return saved.json()["data"]["resume"]


def _open_section(page: Page, title: str) -> Locator:
    toggle = page.get_by_role("button", name=f"{title}: 展开或收起模块", exact=True)
    if toggle.get_attribute("aria-expanded") != "true":
        toggle.click()
    card = toggle.locator('xpath=ancestor::*[@data-slot="card"][1]')
    item_toggle = card.get_by_role("button", name="展开或收起条目 1", exact=True)
    if item_toggle.get_attribute("aria-expanded") != "true":
        item_toggle.click()
    return card


def _select_all(field: Locator) -> None:
    field.click()
    field.press("ControlOrMeta+a")


def _save(page: Page, resume_id: str) -> None:
    save = page.get_by_role("button", name="保存状态", exact=True)
    expect(save).to_be_enabled()
    expect(save).to_have_attribute("title", "有未保存更改")
    with page.expect_response(
        lambda response: (
            response.request.method == "PUT"
            and f"/api/resumes/{resume_id}" in response.url
        )
    ):
        page.keyboard.press("ControlOrMeta+s")


def _inline_toolbar(page: Page) -> Locator:
    return page.locator('body > div:not(#root) [role="toolbar"]:visible')


def _apply_mark(page: Page, field: Locator, label: str) -> None:
    _select_all(field)
    toolbar = _inline_toolbar(page)
    expect(toolbar).to_have_count(1)
    toolbar.get_by_role("button", name=label, exact=True).click()
    expect(field).to_be_focused()


def _preview_item(page: Page, item_id: str) -> Locator:
    return page.locator(
        '.resume-workspace [data-export-root="resume-page"] '
        f'article[data-resume-item-id="{item_id}"]'
    ).first


def test_inline_marks_preserve_input_geometry_and_saved_content(
    browser: Browser, workspace_servers: tuple[str, str], tmp_path: Path
) -> None:
    base, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 1100}
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        created = _create_resume(page, base)
        resume_id = created["id"]
        initial_version = page.request.get(f"{base}/api/resumes/{resume_id}").json()[
            "data"
        ]["versionId"]
        page.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        _open_section(page, "Experience")
        company = page.get_by_role("textbox", name="公司 / 组织", exact=True)
        position = page.get_by_role("textbox", name="职位 / 角色", exact=True)
        location = page.get_by_role("textbox", name="地点", exact=True)
        period = page.get_by_role("textbox", name="时间", exact=True)
        expect(company).to_have_text("Research Lab")
        company.scroll_into_view_if_needed()
        before = company.bounding_box()
        period_before = period.bounding_box()
        assert before is not None and period_before is not None
        assert abs(before["height"] - period_before["height"]) <= 2

        _select_all(company)
        toolbar = _inline_toolbar(page)
        expect(toolbar).to_have_count(1)
        expect(toolbar.get_by_role("button", name="加粗", exact=True)).to_be_visible()
        company.press("Alt+F10")
        bold = toolbar.get_by_role("button", name="加粗", exact=True)
        expect(bold).to_be_focused()
        bold.press("ArrowRight")
        italic = toolbar.get_by_role("button", name="斜体", exact=True)
        expect(italic).to_be_focused()
        italic.press("Enter")
        expect(company.locator("em")).to_have_text("Research Lab")
        expect(company).to_be_focused()
        company.press("Alt+F10")
        toolbar.get_by_role("button", name="加粗", exact=True).press("Escape")
        expect(company).to_be_focused()
        toolbar.get_by_role("button", name="斜体", exact=True).click()
        expect(company.locator("em")).to_have_count(0)
        assert company.bounding_box() == before
        assert period.bounding_box() == period_before
        page.screenshot(path=str(tmp_path / "inline-toolbar-desktop.png"))
        toolbar.get_by_role("button", name="加粗", exact=True).click()
        expect(company).to_be_focused()
        expect(_preview_item(page, "experience-1").locator("h3 strong")).to_have_text(
            "Research Lab"
        )
        _apply_mark(page, position, "斜体")
        _apply_mark(page, location, "下划线")
        location.press("ControlOrMeta+z")
        expect(location.locator("u")).to_have_count(0)
        location.press("ControlOrMeta+Shift+z")
        expect(location.locator("u")).to_have_text("Taipei")
        company.click()
        company.press("Tab")
        expect(position).to_be_focused()
        expect(period).to_have_text("2024 - 2026")
        expect(period).to_have_attribute("contenteditable", "true")

        _open_section(page, "Publications")
        authors = page.get_by_role("textbox", name="作者", exact=True)
        _select_all(authors)
        authors.press("ArrowRight")
        authors.press("Shift+ArrowLeft")
        _inline_toolbar(page).get_by_role("button", name="上标", exact=True).click()
        expect(authors.locator("sup")).to_have_text("1")
        venue = page.get_by_role("textbox", name="期刊 / 会议", exact=True)
        _select_all(venue)
        venue.press("ArrowLeft")
        venue.press("ArrowRight")
        venue.press("Shift+ArrowRight")
        _inline_toolbar(page).get_by_role("button", name="下标", exact=True).click()
        expect(venue.locator("sub")).to_have_text("2")
        expect(page.get_by_role("textbox", name="链接", exact=True)).to_have_value(
            "https://example.org/paper"
        )
        publication = _preview_item(page, "publication-1")
        expect(publication.locator("sup")).to_have_text("1")
        expect(publication.locator("sub")).to_have_text("2")
        _save(page, resume_id)
        saved = page.request.get(f"{base}/api/resumes/{resume_id}").json()["data"][
            "resume"
        ]
        experience, publication_data = saved["resume"]["sections"]
        assert (
            experience["items"][0]["company"] == "<p><strong>Research Lab</strong></p>"
        )
        assert experience["items"][0]["position"] == (
            "<p><em>Research Assistant</em></p>"
        )
        assert experience["items"][0]["location"] == "<p><u>Taipei</u></p>"
        assert publication_data["items"][0]["authors"] == "<p>Jane Doe<sup>1</sup></p>"
        assert publication_data["items"][0]["venue"] == "<p>H<sub>2</sub>O Journal</p>"
        assert publication_data["items"][0]["title"] == "Interactive Systems"
        page.reload(wait_until="networkidle")
        _open_section(page, "Publications")
        expect(
            page.get_by_role("textbox", name="作者", exact=True).locator("sup")
        ).to_have_text("1")
        expect(_preview_item(page, "publication-1").locator("sub")).to_have_text("2")
        expect(
            page.get_by_role("button", name="保存状态", exact=True)
        ).to_have_attribute("title", re.compile("^已保存"))
        latest_version = page.request.get(f"{base}/api/resumes/{resume_id}").json()[
            "data"
        ]["versionId"]
        versions = page.request.get(f"{base}/api/resumes/{resume_id}/versions").json()[
            "data"
        ]["versions"]
        save_requests: list[str] = []
        page.on(
            "request",
            lambda request: (
                save_requests.append(request.url) if request.method == "PUT" else None
            ),
        )
        for version_id, marked in ((initial_version, False), (latest_version, True)):
            index = next(
                index
                for index, version in enumerate(versions)
                if version["versionId"] == version_id
            )
            page.get_by_role("button", name="历史版本", exact=True).click()
            with page.expect_response(
                lambda response, selected=version_id: (
                    f"/versions/{selected}" in response.url
                )
            ):
                page.locator(
                    '[data-slot="popover-content"][aria-label="历史版本"]'
                ).get_by_role("button").nth(index).click()
            page.keyboard.press("Escape")
            _open_section(page, "Publications")
            authors = page.get_by_role("textbox", name="作者", exact=True)
            expect(authors).to_have_text("Jane Doe1")
            expect(authors.locator("sup")).to_have_count(1 if marked else 0)
            expect(
                page.get_by_role("button", name="保存状态", exact=True)
            ).to_have_attribute("title", re.compile("^已保存"))
        assert not save_requests, save_requests
        assert not errors, errors
    finally:
        context.close()


@pytest.mark.parametrize("width", [1672, 430])
def test_inline_paste_flattens_paragraphs_and_keeps_plain_text(
    browser: Browser, workspace_servers: tuple[str, str], width: int, tmp_path: Path
) -> None:
    base, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": width, "height": 1100}
    )
    page = context.new_page()
    try:
        created = _create_resume(page, base)
        resume_id = created["id"]
        page.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        _open_section(page, "Experience")
        company = page.get_by_role("textbox", name="公司 / 组织", exact=True)
        _select_all(company)
        company.press("Backspace")
        company.press_sequentially("A < B & C")
        expect(company).to_have_text("A < B & C")
        company.press("Enter")
        expect(company.locator("p")).to_have_count(1)
        _save(page, resume_id)
        saved = page.request.get(f"{base}/api/resumes/{resume_id}").json()["data"][
            "resume"
        ]
        assert saved["resume"]["sections"][0]["items"][0]["company"] == "A < B & C"

        _select_all(company)
        company.press_sequentially("<p>Hello</p>")
        _save(page, resume_id)
        page.reload(wait_until="networkidle")
        _open_section(page, "Experience")
        expect(company).to_have_text("<p>Hello</p>")
        expect(_preview_item(page, "experience-1").locator("h3")).to_have_text(
            "<p>Hello</p>"
        )

        _select_all(company)
        company.evaluate("""element => {
          const data = new DataTransfer();
          data.setData("text/plain", "First line\\nSecond <tag> & third");
          data.setData("text/html",
            "<p><strong>First line</strong></p>" +
            "<p>Second &lt;tag&gt; &amp; third" +
            "<img src=x onerror='window.inlineInjected=true'></p>");
          element.dispatchEvent(new ClipboardEvent("paste", {
            clipboardData: data, bubbles: true, cancelable: true
          }));
        }""")
        expect(company).to_have_text("First line Second <tag> & third")
        expect(company.locator("p")).to_have_count(1)
        expect(company.locator("img, script, tag")).to_have_count(0)
        assert page.evaluate("window.inlineInjected") is None
        _select_all(company)
        toolbar = _inline_toolbar(page)
        expect(toolbar).to_be_visible()
        bounds = toolbar.bounding_box()
        assert bounds is not None
        assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
        toolbar.get_by_role("button", name="斜体", exact=True).click()
        expect(company).to_be_focused()
        page.screenshot(path=str(tmp_path / f"inline-toolbar-{width}.png"))
        _save(page, resume_id)
        page.reload(wait_until="networkidle")
        _open_section(page, "Experience")
        expect(
            page.get_by_role("textbox", name="公司 / 组织", exact=True)
        ).to_have_text("First line Second <tag> & third")
        expect(_preview_item(page, "experience-1").locator("h3")).to_have_text(
            "First line Second <tag> & third"
        )
    finally:
        context.close()


ACADEMIC_MARK = '[data-academic-italic="true"]'


def _select_text(field: Locator, start: int, length: int) -> None:
    element = field.element_handle()
    assert element is not None

    def wait_for_selection(anchor: int, head: int) -> None:
        field.page.wait_for_function(
            """({element, anchor, head}) => {
              const selection = getSelection();
              const editor = element.editor;
              if (!selection || !editor ||
                  !element.contains(selection.anchorNode) ||
                  !element.contains(selection.focusNode)) return false;
              const offset = (node, position) => {
                const range = document.createRange();
                range.selectNodeContents(element);
                range.setEnd(node, position);
                return range.toString().length;
              };
              const {doc, selection: current} = editor.state;
              return offset(selection.anchorNode, selection.anchorOffset) === anchor
                && offset(selection.focusNode, selection.focusOffset) === head
                && doc.textBetween(0, current.anchor).length === anchor
                && doc.textBetween(0, current.head).length === head;
            }""",
            arg={"element": element, "anchor": anchor, "head": head},
        )

    _select_all(field)
    wait_for_selection(0, len(field.text_content() or ""))
    field.press("ArrowLeft")
    wait_for_selection(0, 0)
    for offset in range(1, start + 1):
        field.press("ArrowRight")
        wait_for_selection(offset, offset)
    for offset in range(1, length + 1):
        field.press("Shift+ArrowRight")
        wait_for_selection(start, start + offset)


def _keyboard_academic_mark(
    page: Page, field: Locator, toolbar: Locator, *, floating: bool
) -> None:
    field.press("Alt+F10" if floating else "Shift+Tab")
    if not floating:
        for _ in range(8):
            if toolbar.evaluate("element => element.contains(document.activeElement)"):
                break
            page.keyboard.press("Shift+Tab")
    assert toolbar.evaluate("element => element.contains(document.activeElement)")
    button = toolbar.get_by_role("button", name="学术花体", exact=True)
    for _ in range(toolbar.get_by_role("button").count()):
        if button.evaluate("element => element === document.activeElement"):
            break
        focused = toolbar.locator("button:focus").element_handle()
        assert focused is not None
        page.keyboard.press("ArrowRight")
        page.wait_for_function(
            "previous => document.activeElement !== previous", arg=focused
        )
    expect(button).to_be_focused()
    page.keyboard.press("Enter")
    expect(field).to_be_focused()


@pytest.mark.parametrize("width", [1672, 430])
def test_academic_italic_is_local_in_inline_fields_and_highlights(
    browser: Browser, workspace_servers: tuple[str, str], width: int, tmp_path: Path
) -> None:
    base, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": width, "height": 1100}
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        created = _create_resume(page, base)
        resume_id = created["id"]
        page.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        _open_section(page, "Experience")
        company = page.get_by_role("textbox", name="公司 / 组织", exact=True)
        _select_text(company, 0, len("Research"))
        toolbar = _inline_toolbar(page)
        expect(toolbar).to_have_count(1)
        _keyboard_academic_mark(page, company, toolbar, floating=True)
        expect(company.locator(ACADEMIC_MARK)).to_have_text("Research")
        expect(company).to_have_text("Research Lab")
        academic = toolbar.get_by_role("button", name="学术花体", exact=True)
        expect(academic).to_have_attribute("aria-pressed", "true")
        academic.click()
        expect(company.locator(ACADEMIC_MARK)).to_have_count(0)
        expect(company).to_have_text("Research Lab")
        expect(academic).to_have_attribute("aria-pressed", "false")
        page.screenshot(path=str(tmp_path / f"academic-inline-unmarked-{width}.png"))
        academic.click()
        expect(company.locator(ACADEMIC_MARK)).to_have_text("Research")
        company.press("Alt+F10")
        page.keyboard.press("Escape")
        expect(company).to_be_focused()
        bounds = toolbar.bounding_box()
        assert bounds is not None
        assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
        page.evaluate("document.fonts.ready")
        font_state = page.evaluate("""() => ({
          ready: document.fonts.check(
            'italic 16px "Latin Modern Roman"', 'Research'
          ),
          faces: Array.from(document.fonts)
            .filter(face => face.family.includes('Latin Modern Roman'))
            .map(face => ({
              family: face.family, style: face.style,
              weight: face.weight, status: face.status
            }))
        })""")
        assert font_state["ready"]
        assert any(face["status"] == "loaded" for face in font_state["faces"])
        (tmp_path / f"academic-font-state-{width}.json").write_text(
            json.dumps(font_state, indent=2), encoding="utf-8"
        )
        page.screenshot(path=str(tmp_path / f"academic-inline-toolbar-{width}.png"))
        company.press("ArrowRight")
        expect(_inline_toolbar(page)).to_have_count(0)
        page.screenshot(path=str(tmp_path / f"academic-inline-collapsed-{width}.png"))
        if width == 1672:
            _select_all(company)
            company.evaluate("""element => {
              const data = new DataTransfer();
              data.setData("text/plain", "Research Lab");
              data.setData("text/html",
                '<p><span data-academic-italic="true" style="color:red" ' +
                'onclick="window.academicInjected=true">Research</span> ' +
                '<span data-academic-italic="false" style="font-family:monospace">' +
                'Lab</span></p>');
              element.dispatchEvent(new ClipboardEvent("paste", {
                clipboardData: data, bubbles: true, cancelable: true
              }));
            }""")
            expect(company.locator(ACADEMIC_MARK)).to_have_text("Research")
            expect(company.locator("[style], [onclick]")).to_have_count(0)
            expect(company.locator('[data-academic-italic="false"]')).to_have_count(0)
            expect(company).to_have_text("Research Lab")
            assert page.evaluate("window.academicInjected") is None

        group = page.get_by_role("group", name="要点", exact=True)
        highlights = group.locator('[contenteditable="true"]')
        highlights.click()
        highlights.press_sequentially("Built robust systems")
        _select_text(highlights, len("Built "), len("robust"))
        fixed_toolbar = group.get_by_role("toolbar", name="文字格式", exact=True)
        fancy = fixed_toolbar.get_by_role("button", name="学术花体", exact=True)
        fancy.click()
        expect(highlights.locator(ACADEMIC_MARK)).to_have_text("robust")
        fancy.click()
        expect(highlights.locator(ACADEMIC_MARK)).to_have_count(0)
        _keyboard_academic_mark(page, highlights, fixed_toolbar, floating=False)
        expect(highlights.locator(ACADEMIC_MARK)).to_have_text("robust")
        group.get_by_role("button", name="无序列表", exact=True).click()
        expect(highlights.locator(f"li {ACADEMIC_MARK}")).to_have_text("robust")
        expect(highlights).to_have_text("Built robust systems")
        expect(highlights.locator("ul > li")).to_have_count(1)
        group_bounds = group.bounding_box()
        assert group_bounds is not None
        for button in fixed_toolbar.get_by_role("button").all():
            box = button.bounding_box()
            assert box is not None
            assert box["x"] >= group_bounds["x"]
            assert box["x"] + box["width"] <= min(
                width, group_bounds["x"] + group_bounds["width"]
            )
        page.screenshot(path=str(tmp_path / f"academic-highlights-toolbar-{width}.png"))
        highlights.press("ArrowRight")
        page.get_by_role("textbox", name="职位 / 角色", exact=True).click()
        expect(_inline_toolbar(page)).to_have_count(0)
        _save(page, resume_id)
        saved = page.request.get(f"{base}/api/resumes/{resume_id}").json()["data"][
            "resume"
        ]
        experience, publication = saved["resume"]["sections"]
        item = experience["items"][0]
        assert item["company"] == (
            '<p><span data-academic-italic="true">Research</span> Lab</p>'
        )
        assert (
            '<span data-academic-italic="true">robust</span>' in item["highlights"][0]
        )
        assert item["position"] == "Research Assistant"
        assert publication["items"][0]["authors"] == "Jane Doe1"
        page.reload(wait_until="networkidle")
        _open_section(page, "Experience")
        expect(company.locator(ACADEMIC_MARK)).to_have_text("Research")
        expect(highlights.locator(f"li {ACADEMIC_MARK}")).to_have_text("robust")
        preview = _preview_item(page, "experience-1")
        expect(preview.locator(ACADEMIC_MARK)).to_have_text(["Research", "robust"])
        expect(
            page.get_by_role("button", name="保存状态", exact=True)
        ).to_have_attribute("title", re.compile("^已保存"))
        assert not errors, errors
    finally:
        context.close()


def _pdf_font_name(font: Any) -> str:
    if font is None:
        return ""
    descriptor = font.get("/FontDescriptor")
    if descriptor is not None:
        return str(descriptor.get_object().get("/FontName", ""))
    return str(font.get("/BaseFont", ""))


def test_inline_marks_follow_template_fonts_and_real_pdf_export(
    browser: Browser, workspace_servers: tuple[str, str], tmp_path: Path
) -> None:
    base, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 1100}
    )
    page = context.new_page()
    try:
        created = _create_resume(page, base)
        resume_id = created["id"]
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
        publication = payload["resume"]["sections"][1]["items"][0]
        publication.update(
            {
                "title": (
                    '<p><span data-academic-italic="true">Interactive</span> '
                    "<em>Systems</em></p>"
                ),
                "authors": (
                    "<p><strong>Jane Doe</strong><sup>1</sup>, Coauthor<sub>2</sub></p>"
                ),
                "venue": "<p><u>Journal of Interfaces</u></p>",
            }
        )
        payload["resume"]["sections"][0]["items"][0]["highlights"] = [
            '<p>Built <span data-academic-italic="true">robust</span> systems</p>'
        ]
        response = page.request.put(f"{base}/api/resumes/{resume_id}", data=payload)
        assert response.ok, response.text()
        page.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        metrics: dict[str, Any] = {}
        for template in (
            "Minimal",
            "Modern",
            "Compact",
            "Classic",
            "Executive",
            "Academic",
        ):
            page.get_by_role("button", name="格式", exact=True).click()
            page.get_by_role("combobox", name="应用模板", exact=True).click()
            page.get_by_role("option", name=template, exact=True).click()
            page.keyboard.press("Escape")
            item = _preview_item(page, "publication-1")
            expect(item.locator("strong")).to_have_text("Jane Doe")
            expect(item.locator("sup")).to_have_text("1")
            expect(item.locator("sub")).to_have_text("2")
            expect(item.locator("u")).to_have_text("Journal of Interfaces")
            expect(item.locator(ACADEMIC_MARK)).to_have_text("Interactive")
            page.evaluate("document.fonts.ready")
            metrics[template] = item.evaluate("""element => {
              const sample = tag => {
                const node = element.querySelector(tag), style = getComputedStyle(node);
                const parent = getComputedStyle(node.parentElement);
                return {
                  family: style.fontFamily, parentFamily: parent.fontFamily,
                  size: parseFloat(style.fontSize),
                  parentSize: parseFloat(parent.fontSize),
                  weight: style.fontWeight, parentWeight: parent.fontWeight,
                  verticalAlign: style.verticalAlign,
                  top: parseFloat(style.top) || 0,
                  lineHeight: style.lineHeight, fontStyle: style.fontStyle,
                  decoration: style.textDecorationLine
                };
              };
              return Object.fromEntries(
                ["strong", "em", "u", "sup", "sub", "[data-academic-italic]"]
                  .map(tag => [tag, sample(tag)])
              );
            }""")
            for tag in ("sup", "sub"):
                mark = metrics[template][tag]
                assert mark["family"] == mark["parentFamily"]
                assert mark["size"] < mark["parentSize"]
                assert mark["verticalAlign"] == tag or (
                    mark["top"] < 0 if tag == "sup" else mark["top"] > 0
                )
            assert int(metrics[template]["strong"]["weight"]) >= 600
            assert metrics[template]["em"]["fontStyle"] == "italic"
            assert "underline" in metrics[template]["u"]["decoration"]
            academic = metrics[template]["[data-academic-italic]"]
            assert "Latin Modern Roman" in academic["family"]
            assert academic["fontStyle"] == "italic"
            assert academic["weight"] == academic["parentWeight"]
            for tag in ("strong", "em", "u"):
                assert "Latin Modern Roman" not in metrics[template][tag]["family"]
            _save(page, resume_id)
            saved = page.request.get(f"{base}/api/resumes/{resume_id}").json()["data"][
                "resume"
            ]
            assert saved["template"] == template.lower()
            response = page.request.post(
                f"{base}/api/exports/resume-pdf",
                data={
                    "resumeId": resume_id,
                    "fileNameSeed": f"inline-{template.lower()}",
                    "savedAt": saved["updatedAt"],
                },
                timeout=60000,
            )
            assert response.ok, response.text()
            download = page.request.get(base + response.json()["data"]["downloadUrl"])
            assert download.ok, download.text()
            pdf = download.body()
            (tmp_path / f"inline-{template.lower()}.pdf").write_bytes(pdf)
            reader = PdfReader(io.BytesIO(pdf))
            assert len(reader.pages) == 1
            text = "\n".join(pdf_page.extract_text() or "" for pdf_page in reader.pages)
            for expected in (
                "Jane Doe",
                "Interactive",
                "Systems",
                "Journal of Interfaces",
            ):
                assert expected in text, text
            assert "<p>" not in text and "<sup>" not in text, text
            font_runs: list[dict[str, str]] = []
            for pdf_page in reader.pages:
                pdf_page.extract_text(
                    visitor_text=lambda text, _cm, _tm, font, _size, runs=font_runs: (
                        runs.append(
                            {
                                "text": text,
                                "font": _pdf_font_name(font),
                            }
                        )
                        if text.strip()
                        else None
                    )
                )
            marked_runs = [
                run
                for run in font_runs
                if "lmroman10" in re.sub(r"[^a-z0-9]", "", run["font"].lower())
            ]
            marked_text = "".join(run["text"] for run in marked_runs)
            assert "Interactive" in marked_text and "robust" in marked_text, font_runs
            assert all("italic" in run["font"].lower() for run in marked_runs), (
                marked_runs
            )
            for marked_text, font_name in (
                ("robust", "lmroman10italic"),
                ("Interactive", "lmroman10bolditalic"),
            ):
                matching_text = "".join(
                    run["text"]
                    for run in marked_runs
                    if font_name in re.sub(r"[^a-z0-9]", "", run["font"].lower())
                )
                assert marked_text in matching_text, marked_runs
            ordinary_text = "".join(
                run["text"] for run in font_runs if run not in marked_runs
            )
            for plain in ("Research Lab", "Jane Doe", "Systems", "Built", "systems"):
                assert "".join(plain.split()) in "".join(ordinary_text.split()), (
                    font_runs
                )
            metrics[template]["pdfFontRuns"] = font_runs
            _wait_for_resume_render(
                page, f"{base}/pdf-export?resumeId={resume_id}&documentLocale=en", 30000
            )
            page.locator('[data-export-root="resume-page"]').first.screenshot(
                path=str(tmp_path / f"inline-{template.lower()}-export.png")
            )
            if template != "Academic":
                page.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        assert len({values["strong"]["family"] for values in metrics.values()}) >= 3
        (tmp_path / "inline-font-metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    finally:
        context.close()


def _create_timeline_resume(page: Page, base: str) -> dict[str, Any]:
    created = _create_resume(page, base)
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
    experience, publication = payload["resume"]["sections"]
    payload["resume"]["sections"] = [
        {
            "id": "education",
            "kind": "education",
            "title": "Education",
            "items": [
                {
                    "id": "education-1",
                    "school": "Sample University",
                    "degree": "BSc",
                    "major": "Computer Science",
                    "gpa": "",
                    "location": "",
                    "period": "",
                    "description": "",
                    "highlights": [],
                }
            ],
        },
        experience,
        {
            "id": "project",
            "kind": "project",
            "title": "Projects",
            "items": [
                {
                    "id": "project-1",
                    "name": "Search platform",
                    "role": "Developer",
                    "techStack": ["React", "TypeScript"],
                    "period": "",
                    "url": "",
                    "description": "",
                    "highlights": [],
                }
            ],
        },
        {
            "id": "achievement",
            "kind": "achievement",
            "title": "Awards",
            "items": [
                {
                    "id": "achievement-1",
                    "name": "Research Award",
                    "issuer": "Sample University",
                    "date": "",
                    "url": "",
                    "description": "",
                }
            ],
        },
        publication,
    ]
    response = page.request.put(f"{base}/api/resumes/{created['id']}", data=payload)
    assert response.ok, response.text()
    return response.json()["data"]["resume"]


def _saved_project(page: Page, base: str, resume_id: str) -> dict[str, Any]:
    saved = page.request.get(f"{base}/api/resumes/{resume_id}").json()["data"]["resume"]
    return next(
        section["items"][0]
        for section in saved["resume"]["sections"]
        if section["kind"] == "project"
    )


def test_rich_technology_list_splits_marks_and_preserves_trailing_input(
    browser: Browser, workspace_servers: tuple[str, str], tmp_path: Path
) -> None:
    base, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 1100}
    )
    page = context.new_page()
    try:
        created = _create_timeline_resume(page, base)
        resume_id = created["id"]
        page.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        card = _open_section(page, "Projects")
        technologies = card.get_by_role("textbox", name="技术栈", exact=True)
        expect(technologies).to_have_text("React, TypeScript")
        _select_text(technologies, 2, len("act, Type"))
        _inline_toolbar(page).get_by_role("button", name="加粗", exact=True).click()
        expect(technologies).to_have_text("React, TypeScript")
        _save(page, resume_id)
        assert _saved_project(page, base, resume_id)["techStack"] == [
            "<p>Re<strong>act</strong></p>",
            "<p><strong>Type</strong>Script</p>",
        ]
        preview = _preview_item(page, "project-1")
        expect(preview.locator("strong")).to_have_text(["act", "Type"])
        page.screenshot(path=str(tmp_path / "technologies-cross-comma-bold.png"))

        _select_text(technologies, 2, len("act, Type"))
        _inline_toolbar(page).get_by_role("button", name="加粗", exact=True).click()
        _save(page, resume_id)
        assert _saved_project(page, base, resume_id)["techStack"] == [
            "React",
            "TypeScript",
        ]
        expect(technologies.locator("strong")).to_have_count(0)
        _select_all(technologies)
        technologies.press("ArrowRight")
        expect(_inline_toolbar(page)).to_have_count(0)
        assert technologies.evaluate("""element => {
          const selection = getSelection();
          const range = document.createRange();
          range.selectNodeContents(element);
          range.setEnd(selection.anchorNode, selection.anchorOffset);
          return {collapsed: selection.isCollapsed, offset: range.toString().length};
        }""") == {"collapsed": True, "offset": len("React, TypeScript")}
        expected = "React, TypeScript"
        for character in ", Rust":
            technologies.press_sequentially(character)
            expected += character
            assert technologies.text_content() == expected
            caret = technologies.evaluate("""element => {
              const selection = getSelection();
              const range = document.createRange();
              range.selectNodeContents(element);
              range.setEnd(selection.anchorNode, selection.anchorOffset);
              return {
                collapsed: selection.isCollapsed, offset: range.toString().length
              };
            }""")
            assert caret == {"collapsed": True, "offset": len(expected)}
        _save(page, resume_id)
        assert _saved_project(page, base, resume_id)["techStack"] == [
            "React",
            "TypeScript",
            "Rust",
        ]
        page.reload(wait_until="networkidle")
        _open_section(page, "Projects")
        expect(technologies).to_have_text("React, TypeScript, Rust")
        expect(_preview_item(page, "project-1")).to_contain_text(
            "React · TypeScript · Rust"
        )
        _select_all(technologies)
        technologies.evaluate("""element => {
          const clipboardData = new DataTransfer();
          clipboardData.setData("text/plain", "  R&D， C++ , Rust <core>  ");
          clipboardData.setData("text/html",
            '<p>  <span data-academic-italic="true">' +
            '<strong>R&amp;D， C++</strong></span> , Rust &lt;core&gt;  </p>');
          element.dispatchEvent(new ClipboardEvent("paste", {
            clipboardData, bubbles: true, cancelable: true
          }));
        }""")
        _save(page, resume_id)
        items = _saved_project(page, base, resume_id)["techStack"]
        assert len(items) == 3 and items[2] == "Rust <core>"
        for item, expected in zip(items[:2], ("R&D", "C++"), strict=True):
            structure = page.evaluate(
                """html => {
              const body = new DOMParser().parseFromString(html, "text/html").body;
              return {
                html: body.innerHTML,
                text: body.textContent,
                bold: body.querySelector("strong")?.textContent,
                academic: body.querySelector(
                  '[data-academic-italic="true"]'
                )?.textContent,
                paragraphs: body.querySelectorAll("p").length
              };
            }""",
                item,
            )
            assert structure == {
                "html": item,
                "text": expected,
                "bold": expected,
                "academic": expected,
                "paragraphs": 1,
            }
        page.reload(wait_until="networkidle")
        _open_section(page, "Projects")
        expect(technologies).to_have_text("R&D, C++, Rust <core>")
        expect(technologies.locator(ACADEMIC_MARK)).to_have_text(["R&D", "C++"])
        expect(technologies.locator("strong")).to_have_text(["R&D", "C++"])
        preview = _preview_item(page, "project-1")
        expect(preview).to_contain_text("R&D · C++ · Rust <core>")
        expect(preview.locator(ACADEMIC_MARK)).to_have_text(["R&D", "C++"])
        expect(preview.locator("core")).to_have_count(0)
        page.evaluate("document.fonts.ready")
        page.screenshot(path=str(tmp_path / "technologies-nested-marks.png"))
    finally:
        context.close()


def test_all_timeline_fields_preserve_freeform_rich_text_in_layouts_and_pdf(
    browser: Browser, workspace_servers: tuple[str, str], tmp_path: Path
) -> None:
    base, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 1100}
    )
    page = context.new_page()
    cases = [
        ("Education", "education-1", "Sep 2020 - Jun 2024", "斜体", "em"),
        ("Experience", "experience-1", "Jul 2024 - 至今", "加粗", "strong"),
        ("Projects", "project-1", "Summer term / remote", "下划线", "u"),
        ("Awards", "achievement-1", "Granted on request", "学术花体", ACADEMIC_MARK),
        ("Publications", "publication-1", "Accepted · March 2026", "斜体", "em"),
    ]
    try:
        created = _create_timeline_resume(page, base)
        resume_id = created["id"]
        page.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        for title, item_id, value, label, selector in cases:
            card = _open_section(page, title)
            field = card.get_by_role("textbox", name="时间", exact=True)
            _select_all(field)
            field.press_sequentially(value)
            _apply_mark(page, field, label)
            expect(field).to_have_text(value)
            expect(_preview_item(page, item_id).locator(selector)).to_have_text(value)
        _save(page, resume_id)
        page.reload(wait_until="networkidle")
        for title, _item_id, value, _label, selector in cases:
            card = _open_section(page, title)
            field = card.get_by_role("textbox", name="时间", exact=True)
            expect(field.locator(selector)).to_have_text(value)
        for template in ("Modern", "Compact", "Academic"):
            page.get_by_role("button", name="格式", exact=True).click()
            page.get_by_role("combobox", name="应用模板", exact=True).click()
            page.get_by_role("option", name=template, exact=True).click()
            page.keyboard.press("Escape")
            expect(
                page.get_by_role("combobox", name="应用模板", exact=True)
            ).to_be_hidden()
            for _title, item_id, value, _label, selector in cases:
                expect(_preview_item(page, item_id).locator(selector)).to_have_text(
                    value
                )
            page.evaluate("document.fonts.ready")
            page.locator(
                '.resume-workspace [data-export-root="resume-page"]'
            ).first.screenshot(path=str(tmp_path / f"timeline-{template.lower()}.png"))
            _save(page, resume_id)
        saved = page.request.get(f"{base}/api/resumes/{resume_id}").json()["data"][
            "resume"
        ]
        response = page.request.post(
            f"{base}/api/exports/resume-pdf",
            data={
                "resumeId": resume_id,
                "fileNameSeed": "rich-timeline",
                "savedAt": saved["updatedAt"],
            },
            timeout=60000,
        )
        assert response.ok, response.text()
        download = page.request.get(base + response.json()["data"]["downloadUrl"])
        assert download.ok, download.text()
        pdf = download.body()
        (tmp_path / "rich-timeline.pdf").write_bytes(pdf)
        reader = PdfReader(io.BytesIO(pdf))
        assert len(reader.pages) == 1
        text = "\n".join(pdf_page.extract_text() or "" for pdf_page in reader.pages)
        compact = "".join(text.split())
        for _title, _item_id, value, _label, _selector in cases:
            assert "".join(value.split()) in compact, text
        assert "<p>" not in text and "<span" not in text, text
        (tmp_path / "rich-timeline-text.txt").write_text(text, encoding="utf-8")
    finally:
        context.close()
