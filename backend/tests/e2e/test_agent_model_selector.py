"""Agent model search and keyboard selection in the live workspace."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Route, expect

from tests.e2e.agent_session_support import seed_pending_agent_draft
from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


@pytest.mark.parametrize("search_field", ["id", "nickname", "model"])
def test_model_search_selects_the_configuration_by_id(
    browser: Browser,
    workspace_servers: tuple[str, str],
    search_field: str,
) -> None:
    frontend_url, resume_id = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 900},
    )
    page = context.new_page()
    pending_menu: list[Route] = []
    menu_pattern = "**/copilot-model-selector-menu.tsx*"
    current = {
        "id": "cfg-73ac",
        "provider": "openai",
        "nickname": "Workspace Writer",
        "model": "alpha-text",
        "supportsTools": True,
    }
    target = {
        "id": "cfg-8b23",
        "provider": "openai",
        "nickname": "Resume Advisor",
        "model": "zenith-chat-large",
        "supportsTools": True,
    }

    def fulfill_workspace(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["modelConfigs"] = [current, target]
        payload["data"]["agentSettings"]["defaultModelConfigId"] = current["id"]
        route.fulfill(response=response, json=payload)

    try:
        page.route("**/api/workspace/pages/resume-editor", fulfill_workspace)
        if search_field == "id":
            page.route(menu_pattern, lambda route: pending_menu.append(route))
        page.route(
            "**/api/workspace/user-settings*",
            lambda route: route.fulfill(
                json={
                    "code": 0,
                    "message": "OK",
                    "data": {
                        "locale": "zh",
                        **route.request.post_data_json["settings"],
                    },
                }
            ),
        )
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        assert pending_menu == []
        composer = page.locator('[data-slot="agent-composer"]')
        trigger = composer.get_by_role("button", name=current["nickname"], exact=True)
        trigger_node = trigger.element_handle()
        assert trigger_node is not None
        trigger.click()
        dialog = page.get_by_role("dialog")
        search = dialog.get_by_role("combobox")
        if search_field == "id":
            expect(dialog.locator('[aria-busy="true"]')).to_be_visible()
            assert pending_menu, (
                "the selector menu must remain deferred through opening"
            )
            for route in pending_menu:
                route.continue_()
            pending_menu.clear()
            page.unroute(menu_pattern)
            expect(search).to_be_focused()
            assert trigger_node.evaluate("element => element.isConnected")
            search.press("Escape")
            expect(dialog).not_to_be_visible()
            expect(trigger).to_be_focused()
            trigger.press("Enter")
            expect(search).to_be_focused()
        expect(dialog.get_by_role("option")).to_have_count(2)
        search.fill(target[search_field])
        expect(dialog.get_by_role("option")).to_have_count(1)
        expect(dialog.get_by_role("option")).to_contain_text(target["nickname"])

        search.press("ArrowDown")
        with page.expect_request("**/api/workspace/user-settings*") as save:
            search.press("Enter")
        expect(dialog).not_to_be_visible()
        expect(
            composer.get_by_role("button", name=target["nickname"], exact=True)
        ).to_be_visible()
        assert (
            save.value.post_data_json["settings"]["agentSettings"][
                "defaultModelConfigId"
            ]
            == target["id"]
        )
    finally:
        for route in pending_menu:
            route.abort()
        context.close()


@pytest.mark.parametrize("locale", ["en", "zh"])
@pytest.mark.parametrize("width", [390, 1440], ids=["mobile", "desktop-panel"])
def test_long_model_id_keeps_composer_and_review_actions_visible(
    browser: Browser,
    workspace_servers: tuple[str, str],
    tmp_path: Path,
    locale: str,
    width: int,
) -> None:
    url, _ = workspace_servers
    messages = json.loads(
        (
            Path(__file__).resolve().parents[3]
            / f"frontend/src/i18n/locales/{locale}.json"
        ).read_text(encoding="utf-8")
    )
    context = authenticated_context(
        browser,
        locale="en-US" if locale == "en" else "zh-CN",
        viewport={"width": width, "height": 900},
    )
    page = context.new_page()
    model = {
        "id": "long-model-layout",
        "provider": "openai",
        "nickname": "Resume Advisor",
        "model": "qwen/qwen3-235b-a22b-thinking-2507",
        "supportsTools": True,
    }

    def load_workspace(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["modelConfigs"] = [model]
        payload["data"]["agentSettings"]["defaultModelConfigId"] = model["id"]
        route.fulfill(response=response, json=payload)

    def assert_actions_fit() -> None:
        geometry = page.locator('[data-slot="agent-panel-shell"]').evaluate(
            """panel => {
              const bounds = panel.getBoundingClientRect();
              const buttons = [...panel.querySelectorAll(
                '[data-slot="agent-composer"] button'
              )].filter(button => button.getBoundingClientRect().width > 0);
              return {
                panel: {left: bounds.left, right: bounds.right},
                buttons: buttons.map(button => {
                  const rect = button.getBoundingClientRect();
                  return {
                    label: button.getAttribute('aria-label') || button.innerText,
                    left: rect.left, right: rect.right,
                    top: rect.top, bottom: rect.bottom,
                    clientWidth: button.clientWidth, scrollWidth: button.scrollWidth,
                  };
                }),
              };
            }"""
        )
        buttons = geometry["buttons"]
        assert len(buttons) >= 6, geometry
        for button in buttons:
            assert button["left"] >= geometry["panel"]["left"] - 1, geometry
            assert button["right"] <= geometry["panel"]["right"] + 1, geometry
            assert button["scrollWidth"] <= button["clientWidth"] + 1, geometry
        for index, first in enumerate(buttons):
            for second in buttons[index + 1 :]:
                overlap_width = min(first["right"], second["right"]) - max(
                    first["left"], second["left"]
                )
                overlap_height = min(first["bottom"], second["bottom"]) - max(
                    first["top"], second["top"]
                )
                assert overlap_width <= 1 or overlap_height <= 1, geometry

    try:
        resume_id, _, _ = seed_pending_agent_draft(
            page,
            url,
            message_id=f"layout-{locale}-{width}",
            summary="A factual summary ready for review.",
            headline="Frontend Engineer",
        )
        page.route("**/api/workspace/pages/resume-editor", load_workspace)
        page.goto(f"{url}/resume/{resume_id}", wait_until="networkidle")
        panel = page.locator('[data-slot="agent-panel-shell"]')
        if not panel.is_visible():
            toggle = page.locator('[data-slot="agent-panel-toggle"]')
            if toggle.is_visible():
                toggle.click()
            else:
                page.locator(
                    '#main-content > header [data-slot="dropdown-menu-trigger"]'
                ).click()
                page.get_by_role(
                    "menuitem", name=messages["agentExpandPanel"], exact=True
                ).click()
        dock = page.locator('[data-slot="agent-draft-review-dock"]')
        expect(dock).to_be_visible()
        composer = page.locator('[data-slot="agent-composer"]')
        composer.scroll_into_view_if_needed()
        panel.screenshot(path=str(tmp_path / f"{locale}-all.png"))
        assert_actions_fit()
        model_button = composer.get_by_role(
            "button", name=model["nickname"], exact=True
        )
        expect(model_button).to_have_attribute("title", model["model"])
        model_button.click()
        dialog = page.get_by_role("dialog")
        expect(dialog).to_be_visible()
        expect(dialog).to_have_accessible_name(messages["agentSelectModel"])
        expect(
            dialog.get_by_role("button", name=messages["close"], exact=True)
        ).to_be_visible()
        expect(dialog.get_by_role("option")).to_contain_text(model["model"])
        page.keyboard.press("Escape")
        composer.locator('input[type="file"]').set_input_files(
            {
                "name": "Supporting-experience-notes-for-the-current-resume.txt",
                "mimeType": "text/plain",
                "buffer": b"Only review the facts already in my resume.",
            }
        )
        remove_attachment = composer.get_by_role(
            "button", name=messages["agentRemoveAttachment"], exact=True
        )
        remove_attachment.hover()
        expect(remove_attachment).to_be_visible()
        assert_actions_fit()
        remove_attachment.click()
        expect(remove_attachment).to_have_count(0)
        dock.get_by_role(
            "button", name=messages["agentReviewOneByOne"], exact=True
        ).click()
        expect(
            dock.get_by_role("button", name=messages["agentReviewAll"], exact=True)
        ).to_be_visible()
        panel.screenshot(path=str(tmp_path / f"{locale}-single.png"))
        assert_actions_fit()
        page.get_by_role(
            "button", name=messages["agentDiscardThis"], exact=True
        ).click()
        expect(dock).to_contain_text("1")
        expect(
            dock.get_by_role("button", name=messages["agentDiscardThis"], exact=True)
        ).to_be_enabled()
        assert_actions_fit()
    finally:
        context.close()
