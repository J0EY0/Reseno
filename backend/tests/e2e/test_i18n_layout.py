"""Localized workspace controls show complete text at supported viewport widths."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Locator, expect

from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _expect_readable(locator: Locator) -> None:
    expect(locator).to_be_visible()
    locator.scroll_into_view_if_needed()
    geometry = locator.evaluate(
        """element => {
          const bounds = element.getBoundingClientRect();
          const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT);
          const failures = [];
          let node;
          let lines = 0;
          while ((node = walker.nextNode())) {
            if (!node.textContent.trim()) continue;
            const range = document.createRange();
            range.selectNodeContents(node);
            for (const rect of range.getClientRects()) {
              if (!rect.width || !rect.height) continue;
              lines++;
              if (rect.left < bounds.left - 1 || rect.right > bounds.right + 1 ||
                  rect.top < bounds.top - 1 || rect.bottom > bounds.bottom + 1) {
                failures.push({text: node.textContent, clippedBy: 'text container'});
              }
              for (let parent = node.parentElement; parent;
                   parent = parent.parentElement) {
                const style = getComputedStyle(parent);
                const box = parent.getBoundingClientRect();
                if (/(hidden|clip|auto|scroll)/.test(style.overflowX) &&
                    (rect.left < box.left - 1 || rect.right > box.right + 1)) {
                  failures.push({text: node.textContent, clippedBy: parent.tagName});
                }
                if (/(hidden|clip|auto|scroll)/.test(style.overflowY) &&
                    (rect.top < box.top - 1 || rect.bottom > box.bottom + 1)) {
                  failures.push({text: node.textContent, clippedBy: parent.tagName});
                }
              }
            }
          }
          return {lines, failures, left: bounds.left, right: bounds.right,
            viewport: innerWidth};
        }"""
    )
    assert geometry["lines"] > 0, geometry
    assert geometry["failures"] == [], geometry
    assert geometry["left"] >= -1, geometry
    assert geometry["right"] <= geometry["viewport"] + 1, geometry


def _expect_placeholder_fits(locator: Locator) -> None:
    expect(locator).to_be_visible()
    locator.scroll_into_view_if_needed()
    assert locator.evaluate(
        """element => {
          const style = getComputedStyle(element);
          const canvas = document.createElement('canvas').getContext('2d');
          canvas.font = style.font;
          const available = element.clientWidth - parseFloat(style.paddingLeft)
            - parseFloat(style.paddingRight);
          const rect = element.getBoundingClientRect();
          return canvas.measureText(element.placeholder).width <= available + 1
            && rect.left >= 0 && rect.right <= innerWidth;
        }"""
    )


@pytest.mark.parametrize("locale", ["en", "zh"])
@pytest.mark.parametrize("width", [390, 768, 1440])
def test_localized_workspace_text_is_complete_and_unclipped(
    browser: Browser,
    workspace_servers: tuple[str, str],
    locale: str,
    width: int,
) -> None:
    url, _ = workspace_servers
    messages = json.loads(
        (
            Path(__file__).parents[3]
            / "frontend/src/i18n/locales"
            / f"{locale}.json"
        ).read_text(encoding="utf-8")
    )
    context = authenticated_context(
        browser,
        locale="en-US" if locale == "en" else "zh-CN",
        viewport={"width": width, "height": 900},
        reduced_motion="reduce",
    )
    try:
        response = context.request.put(
            f"{url}/api/workspace/user-settings?locale={locale}",
            data={"settings": {"agentSettings": {"responseLanguage": "follow"}}},
        )
        assert response.ok, response.text()
        context.add_init_script(
            f"localStorage.setItem('reseno-locale', {json.dumps(locale)})"
        )
        page = context.new_page()
        page.goto(f"{url}/settings?tab=agent", wait_until="networkidle")
        language = page.get_by_role(
            "combobox", name=messages["agentResponseLanguage"], exact=True
        )
        expect(language).to_have_text(messages["followResumeLanguage"])
        _expect_readable(language.locator('[data-slot="select-value"]'))
        language.click()
        option = page.get_by_role(
            "option", name=messages["followResumeLanguage"], exact=True
        )
        _expect_readable(option)
        page.keyboard.press("Escape")

        for route, prefix in (
            ("resume", "searchResumes"),
            ("templates", "searchTemplates"),
        ):
            page.goto(f"{url}/{route}", wait_until="networkidle")
            search = page.get_by_role(
                "textbox", name=messages[f"{prefix}Label"], exact=True
            )
            placeholder = messages[f"{prefix}Placeholder"]
            expect(search).to_have_attribute("placeholder", placeholder)
            assert search.get_attribute("aria-describedby") is None
            expect(page.get_by_text(placeholder, exact=True)).to_have_count(0)

        page.goto(f"{url}/template/compact", wait_until="networkidle")
        editor = page.locator('[data-slot="template-editor"]')
        for key in ("basicInfoLayout", "sectionTemplateStyle", "timelineItemLayout"):
            control = editor.get_by_role("combobox", name=messages[key], exact=True)
            expect(control).to_be_visible()
            label = control.locator("xpath=ancestor::label[1]")
            _expect_readable(label.get_by_text(messages[key], exact=True))
        control = editor.get_by_role(
            "combobox", name=messages["timelineItemLayout"], exact=True
        )
        expect(control).to_have_text(messages["timelineItemLayoutCompact"])
        _expect_readable(control.locator('[data-slot="select-value"]'))

        page.goto(f"{url}/models", wait_until="networkidle")
        create = page.get_by_role("button", name=messages["addModelConfig"], exact=True)
        _expect_readable(create)
        create.click()
        dialog = page.get_by_role("dialog")
        dialog.locator("#model-provider").click()
        page.get_by_role("option").filter(
            has=page.locator("span", has_text=re.compile(r"^OpenAI$"))
        ).click()
        name = dialog.get_by_role(
            "textbox", name="Name" if locale == "en" else "名称", exact=True
        )
        expect(name).to_have_attribute(
            "placeholder",
            "For example: Primary Model" if locale == "en" else "例如：主要模型",
        )
        _expect_readable(dialog.locator('label[for="model-nickname"]'))
        _expect_placeholder_fits(name)
        dialog.locator("#model-api-key").fill("test-i18n-layout")
        discovery = dialog.get_by_role(
            "button", name=messages["fetchModels"], exact=True
        )
        expect(discovery).to_be_enabled()
        expect(discovery).to_be_in_viewport(ratio=1)
        _expect_readable(discovery)
        model = dialog.locator("#model-select")
        expect(model).to_have_text(messages["modelDiscoveryRequired"])
        _expect_readable(model.locator('[data-slot="select-value"]'))
        model_box = model.bounding_box()
        discovery_box = discovery.bounding_box()
        assert model_box and discovery_box
        assert (
            discovery_box["y"] >= model_box["y"] + model_box["height"] - 1
            or discovery_box["y"] + discovery_box["height"] <= model_box["y"] + 1
            or discovery_box["x"] >= model_box["x"] + model_box["width"] - 1
            or discovery_box["x"] + discovery_box["width"] <= model_box["x"] + 1
        )
    finally:
        context.close()
