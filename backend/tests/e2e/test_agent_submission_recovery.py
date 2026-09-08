"""Agent input retention and interrupted run recovery in the live workspace."""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Browser, Page, Route, expect

from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _open_agent(page: Page, frontend_url: str, resume_id: str) -> None:
    def fulfill_workspace(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["modelConfigs"] = [
            {
                "id": "recovery-model",
                "provider": "openai",
                "nickname": "Recovery model",
                "model": "test-model",
                "supportsTools": True,
            }
        ]
        payload["data"]["agentSettings"]["defaultModelConfigId"] = "recovery-model"
        route.fulfill(response=response, json=payload)

    page.route("**/api/workspace/pages/resume-editor", fulfill_workspace)
    page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
    expect(
        page.get_by_role("textbox", name="你想了解什么？", exact=True)
    ).to_be_visible()


def test_rejected_post_preserves_prompt_and_local_attachment(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 900},
    )
    page = context.new_page()
    try:
        page.route("**/api/agent/chat", lambda route: route.abort("failed"))
        _open_agent(page, frontend_url, resume_id)
        prompt = page.get_by_role("textbox", name="你想了解什么？", exact=True)
        expect(prompt).to_have_attribute("placeholder", "你想了解什么？")
        prompt.fill("发送失败后保留这段文字。")
        page.locator('[data-slot="agent-composer"] input[type="file"]').set_input_files(
            {
                "name": "job.txt",
                "mimeType": "text/plain",
                "buffer": b"Job description",
            }
        )
        attachment = page.locator('[data-slot="agent-composer"]').get_by_text(
            "job.txt", exact=True
        )
        expect(attachment).to_be_visible()
        with page.expect_request("**/api/agent/chat"):
            prompt.press("Enter")
        expect(prompt).to_be_enabled()
        expect(prompt).to_have_value("发送失败后保留这段文字。")
        expect(attachment).to_be_visible()
        expect(page.locator(".agent-thread-scroll .is-user")).to_have_count(0)
    finally:
        context.close()


@pytest.mark.parametrize("action", ["retry", "stop"])
def test_exhausted_stream_can_recover_without_reloading(
    browser: Browser,
    workspace_servers: tuple[str, str],
    action: str,
) -> None:
    frontend_url, resume_id = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 900},
    )
    page = context.new_page()
    finished = False
    event_requests = 0
    stops = 0
    run_id = f"recovery-{action}"
    try:
        detail = page.request.get(f"{frontend_url}/api/resumes/{resume_id}").json()[
            "data"
        ]
        run = {
            "id": run_id,
            "resumeId": resume_id,
            "baseResume": detail["resume"]["resume"],
            "status": "active",
            "executionState": "running",
            "errorCode": None,
            "lastEventId": 0,
        }

        def fulfill_run(route: Route) -> None:
            response = route.fetch()
            payload = response.json()
            payload["data"]["run"] = None if finished else run
            route.fulfill(response=response, json=payload)

        def fulfill_events(route: Route) -> None:
            nonlocal event_requests
            event_requests += 1
            route.fulfill(content_type="text/event-stream", body="")

        def stop_run(route: Route) -> None:
            nonlocal finished, stops
            finished = True
            stops += 1
            route.fulfill(json={"code": 0, "message": "OK", "data": run})

        page.route(f"**/api/agent/resumes/{resume_id}/recovery", fulfill_run)
        page.route(f"**/api/agent/runs/{run_id}/events*", fulfill_events)
        page.route(f"**/api/agent/runs/{run_id}", stop_run)
        _open_agent(page, frontend_url, resume_id)
        panel = page.locator("#resume-detail-agent-panel")
        error = panel.get_by_role("alert")
        expect(error).to_be_visible(timeout=15_000)
        assert event_requests == 6
        prompt = page.get_by_role("textbox", name="你想了解什么？", exact=True)
        expect(prompt).to_be_disabled()
        if action == "retry":
            finished = True
            error.get_by_role("button", name="重试", exact=True).click()
        else:
            panel.get_by_role("button", name="停止生成", exact=True).click()
        expect(error).not_to_be_visible()
        expect(prompt).to_be_enabled()
        assert stops == (1 if action == "stop" else 0)
        assert event_requests == 6
    finally:
        context.close()
