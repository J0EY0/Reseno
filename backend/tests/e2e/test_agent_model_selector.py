"""Agent model search and keyboard selection in the live workspace."""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Browser, Route, expect

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
        composer = page.locator('[data-slot="agent-composer"]')
        composer.get_by_role("button", name=current["nickname"], exact=True).click()
        dialog = page.get_by_role("dialog")
        search = dialog.get_by_role("combobox")
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
        context.close()
