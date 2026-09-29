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


def test_document_undo_orders_text_template_and_native_input_changes(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    base, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 1100}
    )
    page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    try:
        created_response = page.request.post(
            f"{base}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": "Document history",
                "template": "classic",
                "typography": {"fontFamily": "inter", "fontSize": 20},
                "templateSettings": {"pagePaddingX": 8},
            },
        )
        assert created_response.ok, created_response.text()
        created = created_response.json()["data"]["resume"]
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
        payload["resume"]["basic"]["name"] = "Original Name"
        payload["resume"]["basic"]["email"] = "original@example.org"
        seeded = page.request.put(f"{base}/api/resumes/{resume_id}", data=payload)
        assert seeded.ok, seeded.text()

        page.goto(f"{base}/resume/{resume_id}", wait_until="domcontentloaded")
        basic_toggle = page.get_by_role(
            "button", name="基本信息: 展开或收起模块", exact=True
        )
        basic_toggle.click()
        name = page.get_by_role("textbox", name="姓名", exact=True)
        expect(name).to_have_text("Original Name")
        name.fill("Edited Name")
        expect(name).to_have_text("Edited Name")

        format_button = page.get_by_role("button", name="格式", exact=True)
        format_button.click()
        template = page.get_by_role("combobox", name="应用模板", exact=True)
        template.click()
        page.get_by_role("option", name="Minimal", exact=True).click()
        expect(template).to_have_text("Minimal")
        page.keyboard.press("Escape")

        name.click()
        name.press("ControlOrMeta+z")
        expect(name).to_have_text("Edited Name")
        expect(name).to_be_focused()
        format_button.click()
        expect(template).to_have_text("Classic")
        expect(page.get_by_role("combobox", name="字体", exact=True)).to_have_text(
            "Inter"
        )
        expect(page.get_by_role("textbox", name="页边距", exact=True)).to_have_value(
            "8"
        )
        page.keyboard.press("Escape")

        name.click()
        name.press("ControlOrMeta+z")
        expect(name).to_have_text("Original Name")
        name.press("ControlOrMeta+z")
        expect(name).to_have_text("Original Name")
        name.press("ControlOrMeta+Shift+z")
        expect(name).to_have_text("Edited Name")
        name.press("ControlOrMeta+Shift+z")
        format_button.click()
        expect(template).to_have_text("Minimal")
        margin = page.get_by_role("textbox", name="页边距", exact=True)
        original_margin = margin.input_value()
        margin.fill("12")
        margin.press("Enter")
        expect(margin).to_have_value("12")
        page.keyboard.press("ControlOrMeta+z")
        expect(margin).to_have_value(original_margin)
        page.keyboard.press("ControlOrMeta+Shift+z")
        expect(margin).to_have_value("12")
        page.keyboard.press("Escape")

        email = page.get_by_role("textbox", name="邮箱", exact=True)
        email.fill("edited@example.org")
        email.press("ControlOrMeta+z")
        expect(email).to_have_value("original@example.org")
        email.press("ControlOrMeta+Shift+z")
        expect(email).to_have_value("edited@example.org")
        page.get_by_role("button", name="撤销", exact=True).first.click()
        expect(email).to_have_value("original@example.org")
        expect(name).to_have_text("Edited Name")

        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
            )
        ) as saved_response:
            page.keyboard.press("ControlOrMeta+s")
        assert saved_response.value.ok
        saved = saved_response.value.request.post_data_json
        assert saved["template"] == "minimal"
        assert saved["templateSettings"]["pagePaddingX"] == 12
        assert saved["resume"]["basic"]["name"] == "Edited Name"
        assert saved["resume"]["basic"]["email"] == "original@example.org"

        page.reload(wait_until="domcontentloaded")
        expect(
            page.get_by_role("button", name="撤销", exact=True).first
        ).to_be_disabled()
        expect(
            page.get_by_role("button", name="重做", exact=True).first
        ).to_be_disabled()
        basic_toggle.click()
        expect(name).to_have_text("Edited Name")
        expect(email).to_have_value("original@example.org")
        assert not errors, errors
    finally:
        context.close()
