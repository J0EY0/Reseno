import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Locator, Page, expect

from tests.e2e.browser_support import authenticated_context

BACKEND_ROOT = Path(__file__).resolve().parents[2]
pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _settle_animations(locator: Locator) -> None:
    locator.evaluate(
        """async element => {
          await Promise.all(element.getAnimations({subtree: true}).map(
            animation => animation.finished.catch(() => {})
          ));
        }"""
    )


def _assert_text_fits(trigger: Locator) -> None:
    geometry = trigger.locator('[data-slot="select-value"]').evaluate(
        """element => {
          const visible = element.getBoundingClientRect();
          const range = document.createRange();
          range.selectNodeContents(element);
          const text = range.getBoundingClientRect();
          return {
            label: element.textContent,
            left: visible.left,
            right: visible.right,
            textLeft: text.left,
            textRight: text.right,
          };
        }"""
    )
    assert geometry["textLeft"] >= geometry["left"] - 0.5, geometry
    assert geometry["textRight"] <= geometry["right"] + 0.5, geometry


def _open_aligned_select(page: Page, trigger: Locator) -> Locator:
    trigger.click()
    menu = page.get_by_role("listbox")
    expect(menu).to_be_visible()
    _settle_animations(menu)
    trigger_box = trigger.bounding_box()
    menu_box = menu.bounding_box()
    assert trigger_box and menu_box
    assert abs(trigger_box["x"] - menu_box["x"]) <= 0.5
    assert abs(trigger_box["width"] - menu_box["width"]) <= 0.5
    assert menu_box["y"] >= trigger_box["y"] + trigger_box["height"]
    return menu


@pytest.mark.parametrize("locale", ["zh", "en"])
@pytest.mark.parametrize("width", [1440, 390])
@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
def test_resume_creation_keeps_template_independent_of_document_language(
    browser: Browser,
    workspace_servers: tuple[str, str],
    locale: str,
    width: int,
    reduced_motion: str,
) -> None:
    frontend_url, _ = workspace_servers
    messages = json.loads(
        (BACKEND_ROOT.parent / f"frontend/src/i18n/locales/{locale}.json").read_text(
            encoding="utf-8"
        )
    )
    presets = json.loads(
        (BACKEND_ROOT / "app/services/template_presets.json").read_text(
            encoding="utf-8"
        )
    )
    context = authenticated_context(
        browser,
        locale="zh-CN" if locale == "zh" else "en-US",
        viewport={"width": width, "height": 900},
        reduced_motion=reduced_motion,
    )
    context.add_init_script(f"localStorage.setItem('reseno-locale', '{locale}')")
    page = context.new_page()
    resume_ids: list[str] = []
    template_ids: list[str] = []
    original_defaults: dict[str, str] = {}
    defaults = {"zh": "modern", "en": "academic"}
    default_name = messages["templateCards"][defaults[locale]]["name"]
    opposite_locale = "en" if locale == "zh" else "zh"
    custom_names = [
        "Research CV",
        "Research and Engineering Leadership Across International Organizations",
    ]
    custom_typography = {"fontFamily": "serif", "fontSize": 18}

    try:
        initial = context.request.get(f"{frontend_url}/api/workspace/pages/resumes")
        assert initial.ok, initial.text()
        original_defaults = initial.json()["data"]["defaultTemplateIds"]
        for document_locale, template_id in defaults.items():
            response = context.request.put(
                f"{frontend_url}/api/workspace/default-template",
                data={"documentLocale": document_locale, "templateId": template_id},
            )
            assert response.ok, response.text()
        for name in custom_names:
            response = context.request.post(
                f"{frontend_url}/api/templates",
                data={
                    "template": {
                        "preset": "minimal",
                        "name": name,
                        "description": "",
                        "layout": presets["minimal"]["layout"],
                        "settings": presets["minimal"]["settings"],
                        "typography": custom_typography,
                    }
                },
            )
            assert response.ok, response.text()
            template_ids.append(response.json()["data"]["template"]["id"])

        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        opener = page.get_by_role("button", name=messages["newResume"], exact=True)
        opener.click()
        dialog = page.locator('[data-slot="dialog-content"]')
        language = dialog.locator("#new-resume-language")
        template = dialog.locator("#new-resume-template")
        create = dialog.get_by_role("button", name=messages["createResume"], exact=True)
        expect(language).to_be_focused()
        expect(language).to_have_accessible_name(messages["resumeLanguage"])
        expect(template).to_have_accessible_name(messages["template"])
        expect(template).to_be_enabled()
        expect(template).to_have_text(default_name)
        _assert_text_fits(template)
        expect(create).to_be_disabled()
        _settle_animations(dialog)
        dialog_box = dialog.bounding_box()
        assert dialog_box
        assert dialog_box["x"] >= 0
        assert dialog_box["x"] + dialog_box["width"] <= width

        _open_aligned_select(page, template)
        expect(
            page.get_by_role("option", name=default_name, exact=True)
        ).to_have_attribute("aria-selected", "true")
        expected_names = {
            card["name"] for card in messages["templateCards"].values()
        } | set(custom_names)
        assert set(page.get_by_role("option").all_text_contents()) == expected_names
        page.keyboard.press("Escape")
        expect(page.get_by_role("listbox")).not_to_be_visible()
        expect(dialog).to_be_visible()
        expect(template).to_be_focused()
        template.click()
        page.get_by_role("option", name=custom_names[0], exact=True).click()
        expect(template).to_have_text(custom_names[0])
        expect(language).to_have_text(messages["selectResumeLanguage"])
        expect(create).to_be_disabled()

        for document_locale in (locale, opposite_locale, locale):
            _open_aligned_select(page, language)
            label = messages[
                "languageChinese" if document_locale == "zh" else "languageEnglish"
            ]
            page.get_by_role("option", name=label, exact=True).click()
            expect(template).to_have_text(custom_names[0])
            expect(create).to_be_enabled()
            _assert_text_fits(language)
            _assert_text_fits(template)

        dialog.get_by_role("button", name=messages["cancel"], exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(opener).to_be_focused()
        opener.click()
        expect(language).to_have_text(messages["selectResumeLanguage"])
        expect(template).to_be_enabled()
        expect(template).to_have_text(default_name)
        expect(create).to_be_disabled()
        _settle_animations(dialog)

        for document_locale in (opposite_locale, locale, opposite_locale):
            _open_aligned_select(page, language)
            label = messages[
                "languageChinese" if document_locale == "zh" else "languageEnglish"
            ]
            page.get_by_role("option", name=label, exact=True).click()
            expect(template).to_have_text(default_name)
            _assert_text_fits(template)
            _open_aligned_select(page, template)
            assert set(page.get_by_role("option").all_text_contents()) == expected_names
            page.keyboard.press("Escape")
            expect(page.get_by_role("listbox")).not_to_be_visible()
            expect(dialog).to_be_visible()
            expect(template).to_be_focused()

        template.click()
        page.get_by_role("option", name=custom_names[1], exact=True).click()
        expect(template).to_have_text(custom_names[1])
        assert dialog.bounding_box() == dialog_box
        template_box = template.bounding_box()
        assert template_box
        assert template_box["x"] + template_box["width"] <= (
            dialog_box["x"] + dialog_box["width"]
        )
        page.keyboard.press("Escape")
        expect(dialog).not_to_be_visible()
        expect(opener).to_be_focused()

        for explicit_template in (False, True):
            opener.click()
            expect(language).to_be_focused()
            expect(language).to_have_text(messages["selectResumeLanguage"])
            expect(template).to_be_enabled()
            expect(template).to_have_text(default_name)
            expect(create).to_be_disabled()
            if explicit_template:
                template.click()
                page.get_by_role("option", name=custom_names[0], exact=True).click()
                expect(create).to_be_disabled()
                _assert_text_fits(template)
            language.click()
            document_locale = locale if explicit_template else opposite_locale
            label = messages[
                "languageChinese" if document_locale == "zh" else "languageEnglish"
            ]
            page.get_by_role("option", name=label, exact=True).click()
            expect(template).to_have_text(
                custom_names[0] if explicit_template else default_name
            )
            with page.expect_response(
                lambda response: (
                    response.request.method == "POST"
                    and urlparse(response.url).path == "/api/resumes"
                )
            ) as created:
                create.click()
            response = created.value
            assert response.ok, response.text()
            expected_template = (
                template_ids[0] if explicit_template else defaults[locale]
            )
            assert response.request.post_data_json == {
                "documentLocale": document_locale,
                "template": expected_template,
            }
            resume = response.json()["data"]["resume"]
            resume_id = resume["id"]
            resume_ids.append(resume_id)
            page.wait_for_url(f"**/resume/{resume_id}")
            saved_response = context.request.get(
                f"{frontend_url}/api/resumes/{resume_id}"
            )
            assert saved_response.ok, saved_response.text()
            saved = saved_response.json()["data"]["resume"]
            assert saved["documentLocale"] == document_locale
            assert saved["template"] == expected_template
            assert saved["typography"] == (
                custom_typography
                if explicit_template
                else presets[defaults[locale]]["typography"]
            )
            page.goto(f"{frontend_url}/resume", wait_until="networkidle")

        response = context.request.put(
            f"{frontend_url}/api/workspace/default-template",
            data={"documentLocale": locale, "templateId": "minimal"},
        )
        assert response.ok, response.text()
        page.reload(wait_until="networkidle")
        opener.click()
        expect(language).to_be_focused()
        expect(language).to_have_text(messages["selectResumeLanguage"])
        expect(template).to_have_text(messages["templateCards"]["minimal"]["name"])
        expect(create).to_be_disabled()
        dialog.get_by_role("button", name=messages["close"], exact=True).click()
        expect(dialog).not_to_be_visible()
        expect(opener).to_be_focused()
    finally:
        for document_locale, template_id in original_defaults.items():
            context.request.put(
                f"{frontend_url}/api/workspace/default-template",
                data={"documentLocale": document_locale, "templateId": template_id},
            )
        for collection, ids in (("resumes", resume_ids), ("templates", template_ids)):
            for item_id in ids:
                context.request.post(f"{frontend_url}/api/{collection}/{item_id}/trash")
                context.request.delete(f"{frontend_url}/api/{collection}/{item_id}")
        context.close()
