from __future__ import annotations

import json
import os
import time
from collections import Counter
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Request, Route, expect
from playwright.sync_api import Error as PlaywrightError

from tests.e2e.browser_support import RouteReady
from tests.e2e.browser_support import authenticated_context as _authenticated_context
from tests.e2e.workspace_network_support import ApiRequest, api_request_key

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


@pytest.mark.browser_smoke
def test_first_agent_expand_keeps_one_stable_loading_shell(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    held_module_routes: list[Route] = []
    held_recovery_routes: list[Route] = []
    module_ready = RouteReady()
    recovery_ready = RouteReady()
    module_pattern = "**/src/components/copilot/copilot-panel.tsx*"
    recovery_pattern = f"**/api/agent/resumes/{resume_id}/recovery"

    def hold_module(route: Route) -> None:
        held_module_routes.append(route)
        module_ready.set()

    def hold_recovery(route: Route) -> None:
        held_recovery_routes.append(route)
        recovery_ready.set()

    try:
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )
        page.route(module_pattern, hold_module)
        page.route(recovery_pattern, hold_recovery)

        trigger = page.locator('.resume-workspace [data-slot="agent-panel-toggle"]')
        trigger.evaluate("button => button.click()")
        module_ready.wait(page)

        loading = page.locator(
            '[data-slot="agent-panel-stable-loader"] '
            '[data-slot="agent-panel-loading"][role="status"]'
        )
        loading.wait_for(state="visible", timeout=5_000)
        page.wait_for_timeout(320)
        fallback_shell = page.evaluate(
            """
            () => {
              const shell = document.querySelector(
                '.resume-workspace .agent-panel-card',
              );
              if (!(shell instanceof HTMLElement)) {
                throw new Error('Missing Agent loading shell.');
              }
              const loading = shell.querySelector(
                '[data-slot="agent-panel-stable-loader"] ' +
                '[data-slot="agent-panel-loading"]',
              );
              window.__firstAgentPanelShell = shell;
              window.__firstAgentPanelLoading = loading;
              const rect = shell.getBoundingClientRect();
              const loadingRect = loading?.getBoundingClientRect();
              return {
                count: document.querySelectorAll(
                  '.resume-workspace .agent-panel-card',
                ).length,
                radius: getComputedStyle(shell).borderTopLeftRadius,
                rect: {
                  height: rect.height,
                  width: rect.width,
                  x: rect.x,
                  y: rect.y,
                },
                loadingRect: loadingRect ? {
                  height: loadingRect.height,
                  width: loadingRect.width,
                  x: loadingRect.x,
                  y: loadingRect.y,
                } : null,
                statusCount: document.querySelectorAll(
                  '[data-slot="agent-panel-stable-loader"] ' +
                  '[data-slot="agent-panel-loading"][role="status"]',
                ).length,
              };
            }
            """
        )
        assert fallback_shell["count"] == 1, fallback_shell
        assert fallback_shell["statusCount"] == 1, fallback_shell

        page.unroute(module_pattern, hold_module)
        for route in held_module_routes:
            try:
                route.continue_()
            except PlaywrightError:
                pass
        held_module_routes.clear()
        page.wait_for_function(
            "() => window.__firstAgentPanelShell?.isConnected === true"
        )
        expect(trigger).to_have_attribute("data-agent-status", "loading")
        recovery_ready.wait(page)
        assert held_recovery_routes

        hydration_shell = page.evaluate(
            """
            () => {
              const shell = document.querySelector(
                '.resume-workspace .agent-panel-card',
              );
              const rect = shell?.getBoundingClientRect();
              const loading = shell?.querySelector(
                '[data-slot="agent-panel-stable-loader"] ' +
                '[data-slot="agent-panel-loading"]',
              );
              const loadingRect = loading?.getBoundingClientRect();
              return {
                count: document.querySelectorAll(
                  '.resume-workspace .agent-panel-card',
                ).length,
                sameNode: shell === window.__firstAgentPanelShell,
                sameLoadingNode:
                  loading === window.__firstAgentPanelLoading,
                radius: shell ? getComputedStyle(shell).borderTopLeftRadius : null,
                rect: rect ? {
                  height: rect.height,
                  width: rect.width,
                  x: rect.x,
                  y: rect.y,
                } : null,
                loadingRect: loadingRect ? {
                  height: loadingRect.height,
                  width: loadingRect.width,
                  x: loadingRect.x,
                  y: loadingRect.y,
                } : null,
                statusCount: document.querySelectorAll(
                  '[data-slot="agent-panel-stable-loader"] ' +
                  '[data-slot="agent-panel-loading"][role="status"]',
                ).length,
              };
            }
            """
        )
        assert hydration_shell["count"] == 1, hydration_shell
        assert hydration_shell["sameNode"], hydration_shell
        assert hydration_shell["sameLoadingNode"], hydration_shell
        assert hydration_shell["radius"] == fallback_shell["radius"]
        assert hydration_shell["rect"] == fallback_shell["rect"]
        assert hydration_shell["statusCount"] == 1, hydration_shell
        assert hydration_shell["loadingRect"] is not None, hydration_shell
        assert fallback_shell["loadingRect"] is not None, fallback_shell
        assert all(
            abs(
                hydration_shell["loadingRect"][key] - fallback_shell["loadingRect"][key]
            )
            <= 1.5
            for key in ("height", "width", "x", "y")
        ), {"fallback": fallback_shell, "hydration": hydration_shell}

        page.unroute(recovery_pattern, hold_recovery)
        for route in held_recovery_routes:
            try:
                route.continue_()
            except PlaywrightError:
                pass
        held_recovery_routes.clear()
        loading.wait_for(state="hidden")
        ready_shell = page.evaluate(
            """
            () => {
              const shell = document.querySelector(
                '.resume-workspace .agent-panel-card',
              );
              return {
                count: document.querySelectorAll(
                  '.resume-workspace .agent-panel-card',
                ).length,
                sameNode: shell === window.__firstAgentPanelShell,
              };
            }
            """
        )
        assert ready_shell == {"count": 1, "sameNode": True}
    finally:
        for route in held_module_routes:
            try:
                route.continue_()
            except PlaywrightError:
                pass
        for route in held_recovery_routes:
            try:
                route.continue_()
            except PlaywrightError:
                pass
        context.close()


def test_collapsed_agent_toggle_keeps_active_run_status(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    run_id = "agent-toggle-status-run"
    held_event_routes: list[Route] = []
    session_pattern = f"**/api/agent/resumes/{resume_id}/session"
    recovery_pattern = f"**/api/agent/resumes/{resume_id}/recovery"
    events_pattern = f"**/api/agent/runs/{run_id}/events*"

    try:
        resume_detail = page.request.get(
            f"{frontend_url}/api/resumes/{resume_id}"
        ).json()["data"]
        base_resume = resume_detail["resume"]["resume"]

        user_messages = [
            {
                "id": "user-agent-toggle-status",
                "role": "user",
                "text": "检查这份简历。",
                "createdAt": "2026-08-10T00:00:00.000Z",
            }
        ]

        def fulfill_session_with_user_message(route: Route) -> None:
            response = route.fetch()
            payload = response.json()
            payload["data"]["messages"] = user_messages
            route.fulfill(
                response=response,
                content_type="application/json",
                body=json.dumps(payload),
            )

        def fulfill_recovery(route: Route) -> None:
            response = route.fetch()
            payload = response.json()
            payload["data"]["session"]["messages"] = user_messages
            payload["data"]["run"] = {
                "id": run_id,
                "resumeId": resume_id,
                "baseResume": base_resume,
                "status": "active",
                "executionState": "running",
                "errorCode": None,
                "lastEventId": 0,
            }
            route.fulfill(
                response=response,
                content_type="application/json",
                body=json.dumps(payload),
            )

        def hold_events(route: Route) -> None:
            held_event_routes.append(route)

        page.route(session_pattern, fulfill_session_with_user_message)
        page.route(recovery_pattern, fulfill_recovery)
        page.route(events_pattern, hold_events)
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )

        trigger = page.locator('.resume-workspace [data-slot="agent-panel-toggle"]')
        trigger.evaluate("button => button.click()")
        expect(trigger).to_have_attribute("data-agent-status", "responding")

        pending_status = page.locator("#resume-detail-agent-panel").get_by_role(
            "status", name="正在分析请求", exact=True
        )
        expect(pending_status).to_be_visible()
        shimmer_start = pending_status.evaluate(
            """
            element => {
              const shimmer = element.querySelector('span');
              if (!shimmer) {
                return null;
              }
              const style = getComputedStyle(shimmer);
              return {
                animationName: style.animationName,
                backgroundImage: style.backgroundImage,
                backgroundPosition: style.backgroundPosition,
              };
            }
            """
        )
        page.wait_for_timeout(80)
        shimmer_end_position = pending_status.evaluate(
            """
            element => {
              const shimmer = element.querySelector('span');
              return shimmer
                ? getComputedStyle(shimmer).backgroundPosition
                : null;
            }
            """
        )
        assert shimmer_start is not None
        assert shimmer_start["animationName"] == "text-shimmer", shimmer_start
        assert shimmer_start["backgroundImage"] != "none", shimmer_start
        assert shimmer_end_position != shimmer_start["backgroundPosition"], {
            "start": shimmer_start,
            "endPosition": shimmer_end_position,
        }

        trigger.click()
        expect(trigger).to_have_attribute("aria-expanded", "false")
        page.wait_for_timeout(320)
        expect(trigger).to_be_visible()
        expect(trigger.locator('[data-slot="agent-status-indicator"]')).to_have_count(0)
        expect(trigger).to_have_attribute("aria-label", "展开 AI 助手")
        live_status = trigger.locator("..").get_by_role("status")
        expect(live_status).to_have_text("正在生成建议…")
        assert page.locator('.agent-panel-dock[aria-hidden="true"]').count() == 1
        assert page.locator(".agent-panel-dock").evaluate("element => element.inert")

        page.set_viewport_size({"width": 1200, "height": 900})
        expect(trigger).to_be_hidden()
        compact_indicator = page.locator('[data-slot="agent-compact-status-indicator"]')
        compact_indicator_state = compact_indicator.evaluate(
            """
            element => {
              const rect = element.getBoundingClientRect();
              return {
                opacity: Number.parseFloat(getComputedStyle(element).opacity),
                width: rect.width,
              };
            }
            """
        )
        assert compact_indicator_state["width"] > 0, compact_indicator_state
        assert compact_indicator_state["opacity"] > 0.35, compact_indicator_state
        expect(live_status).to_have_text("正在生成建议…")
        page.set_viewport_size({"width": 1440, "height": 900})
        expect(trigger).to_be_visible()

        page.unroute(events_pattern, hold_events)
        terminal_event = (
            "id: 1\nevent: run_done\ndata: "
            '{"status":"completed","executionState":"succeeded",'
            '"errorCode":null}\n\n'
        )
        for route in held_event_routes:
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=terminal_event,
            )
        held_event_routes.clear()
        expect(trigger).to_have_attribute("data-agent-status", "ready")
        assert live_status.count() == 0
    finally:
        for route in held_event_routes:
            try:
                route.abort()
            except PlaywrightError:
                pass
        context.close()


@pytest.mark.browser_smoke
def test_agent_streaming_text_uses_character_reveal_animation(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    model_config_id = "llm-agent-stream-animation"
    model_nickname = "Agent stream animation"
    run_id = "agent-stream-animation"
    streaming_text = (
        "正在逐字展示这段中文回复，确保单次收到较长内容时仍然平滑，"
        "而且不会把最后几个字延迟太久。"
    )
    stream_finished = False
    held_event_routes: list[Route] = []
    session_pattern = f"**/api/agent/resumes/{resume_id}/session"
    events_pattern = f"**/api/agent/runs/{run_id}/events*"

    def fulfill_workspace(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["modelConfigs"] = [
            {
                "id": model_config_id,
                "provider": "openai",
                "nickname": model_nickname,
                "model": "stream-animation-model",
                "supportsTools": True,
            }
        ]
        payload["data"]["agentSettings"]["defaultModelConfigId"] = model_config_id
        route.fulfill(
            response=response,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def fulfill_session(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        if stream_finished:
            payload["data"]["messages"] = [
                {
                    "id": "user-stream-animation",
                    "role": "user",
                    "text": "请展示一段流式回复。",
                    "createdAt": "2026-08-10T00:00:00.000Z",
                },
                {
                    "id": "assistant-stream-animation",
                    "role": "assistant",
                    "text": streaming_text,
                    "createdAt": "2026-08-10T00:00:01.000Z",
                    "response": {
                        "id": "assistant-stream-animation",
                        "role": "assistant",
                        "text": streaming_text,
                        "timeline": [
                            {
                                "id": "timeline-stream-animation",
                                "type": "text",
                                "text": streaming_text,
                                "toolIds": [],
                            }
                        ],
                    },
                },
            ]
        route.fulfill(
            response=response,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def fulfill_chat(route: Route) -> None:
        message_start = (
            "id: 1\n"
            "event: message_start\n"
            "data: "
            + json.dumps(
                {
                    "type": "message_start",
                    "message": {
                        "id": "assistant-stream-animation",
                        "role": "assistant",
                        "text": "",
                    },
                },
                separators=(",", ":"),
            )
            + "\n\n"
        )
        text_delta = (
            "id: 2\n"
            "event: text_delta\n"
            "data: "
            + json.dumps(
                {
                    "type": "text_delta",
                    "delta": streaming_text,
                    "timelinePartId": "timeline-stream-animation",
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n\n"
        )
        route.fulfill(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "X-Agent-Run-Id": run_id,
            },
            body=message_start + text_delta,
        )

    def hold_events(route: Route) -> None:
        held_event_routes.append(route)

    page.route("**/api/workspace/pages/resume-editor", fulfill_workspace)
    page.route(session_pattern, fulfill_session)
    page.route("**/api/agent/chat", fulfill_chat)
    page.route(events_pattern, hold_events)

    try:
        page.emulate_media(reduced_motion="no-preference")
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )
        trigger = page.locator('.resume-workspace [data-slot="agent-panel-toggle"]')
        if trigger.get_attribute("aria-expanded") == "false":
            trigger.evaluate("button => button.click()")

        prompt = page.get_by_role(
            "textbox",
            name="你想了解什么？",
            exact=True,
        )
        prompt.fill("请展示一段流式回复。")
        page.evaluate(
            """
            targetText => {
              window.__agentStreamingFrames = [];
              window.__captureAgentStreamingFrames = true;
              const capture = () => {
                const panel = document.querySelector(
                  '#resume-detail-agent-panel'
                );
                const response = [...(panel?.querySelectorAll('p') ?? [])]
                  .find(element => element.textContent?.includes(targetText));
                window.__agentStreamingFrames.push({
                  animatedCount: panel?.querySelectorAll(
                    '[data-sd-animate="true"]'
                  ).length ?? 0,
                  hasVisibleFullText: Boolean(
                    response &&
                    getComputedStyle(response).visibility !== 'hidden'
                  ),
                });
                if (window.__captureAgentStreamingFrames) {
                  requestAnimationFrame(capture);
                }
              };
              requestAnimationFrame(capture);
            }
            """,
            streaming_text,
        )
        prompt.press("Enter")

        panel = page.locator("#resume-detail-agent-panel")
        animated_characters = panel.locator('[data-sd-animate="true"]')
        page.wait_for_function(
            """
            () => document.querySelectorAll(
              '#resume-detail-agent-panel [data-sd-animate="true"]'
            ).length >= 4
            """,
        )
        expect(panel).to_contain_text(streaming_text)
        presentation_frames = page.evaluate(
            """
            () => {
              window.__captureAgentStreamingFrames = false;
              return window.__agentStreamingFrames;
            }
            """
        )
        assert any(frame["hasVisibleFullText"] for frame in presentation_frames)
        assert not any(
            frame["hasVisibleFullText"] and frame["animatedCount"] == 0
            for frame in presentation_frames
        ), presentation_frames
        animation_state = animated_characters.evaluate_all(
            """
            nodes => [nodes[0], nodes[1], nodes[2], nodes.at(-1)].map(node => {
              const style = getComputedStyle(node);
              const toMilliseconds = value => value.endsWith('ms')
                ? Number.parseFloat(value)
                : Number.parseFloat(value) * 1000;
              return {
                animationName: style.animationName,
                delayMs: toMilliseconds(style.animationDelay),
                durationMs: toMilliseconds(style.animationDuration),
              };
            })
            """
        )
        assert all(state["animationName"] != "none" for state in animation_state)
        assert all(state["durationMs"] > 0 for state in animation_state)
        reveal_delays = [state["delayMs"] for state in animation_state]
        assert reveal_delays == sorted(reveal_delays)
        assert reveal_delays[0] < reveal_delays[1] < reveal_delays[2]
        assert reveal_delays[-1] <= 240

        page.emulate_media(reduced_motion="reduce")
        reduced_motion_names = animated_characters.evaluate_all(
            """
            nodes => [...new Set(
              nodes.map(node => getComputedStyle(node).animationName)
            )]
            """
        )
        assert reduced_motion_names == ["none"]

        deadline = time.monotonic() + 3
        while not held_event_routes and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert held_event_routes
        terminal_event = (
            "id: 3\n"
            "event: message_done\n"
            "data: "
            + json.dumps(
                {
                    "type": "message_done",
                    "message": {
                        "id": "assistant-stream-animation",
                        "role": "assistant",
                        "text": streaming_text,
                        "timeline": [
                            {
                                "id": "timeline-stream-animation",
                                "type": "text",
                                "text": streaming_text,
                                "toolIds": [],
                            }
                        ],
                    },
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n\n"
            + "id: 4\nevent: run_done\ndata: "
            + '{"status":"completed","executionState":"succeeded",'
            + '"errorCode":null}\n\n'
        )
        stream_finished = True
        page.unroute(events_pattern, hold_events)
        for route in held_event_routes:
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=terminal_event,
            )
        held_event_routes.clear()
        expect(trigger).to_have_attribute("data-agent-status", "ready")
        expect(animated_characters).to_have_count(0)
        expect(panel).to_contain_text(streaming_text)
    finally:
        for route in held_event_routes:
            try:
                route.abort()
            except PlaywrightError:
                pass
        context.close()


@pytest.mark.parametrize("action", ["send", "retry"])
def test_agent_send_and_retry_show_feedback_while_preflight_is_pending(
    browser: Browser,
    workspace_servers: tuple[str, str],
    action: str,
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    current_model_config_id = f"llm-feedback-current-{action}"
    next_model_config_id = f"llm-feedback-next-{action}"
    current_model_nickname = f"Feedback current {action}"
    next_model_nickname = f"Feedback next {action}"
    user_message_id = f"user-feedback-{action}"
    run_id = f"agent-feedback-{action}"
    held_settings_routes: list[Route] = []
    held_chat_routes: list[Route] = []
    held_event_routes: list[Route] = []
    settings_pattern = "**/api/workspace/user-settings*"
    chat_pattern = "**/api/agent/chat"
    events_pattern = f"**/api/agent/runs/{run_id}/events*"

    def fulfill_workspace(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["modelConfigs"] = [
            {
                "id": model_config_id,
                "provider": "openai",
                "nickname": nickname,
                "model": model_id,
                "supportsTools": True,
            }
            for model_config_id, nickname, model_id in (
                (
                    current_model_config_id,
                    current_model_nickname,
                    "feedback-current-model",
                ),
                (
                    next_model_config_id,
                    next_model_nickname,
                    "feedback-next-model",
                ),
            )
        ]
        payload["data"]["agentSettings"]["defaultModelConfigId"] = (
            current_model_config_id
        )
        route.fulfill(
            response=response,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def fulfill_retryable_session(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        session = (
            payload["data"]["session"]
            if route.request.url.endswith("/recovery")
            else payload["data"]
        )
        session["messages"] = [
            {
                "id": user_message_id,
                "role": "user",
                "text": "请重新检查并生成修改草稿。",
                "createdAt": "2026-08-10T00:00:00.000Z",
            }
        ]
        session["executions"] = [
            {
                "runId": "failed-feedback-run",
                "turnId": user_message_id,
                "status": "failed",
                "errorCode": "AGENT_PROVIDER_ERROR",
                "modelSnapshot": None,
                "startedAt": "2026-08-10T00:00:00.000Z",
                "completedAt": "2026-08-10T00:00:01.000Z",
            }
        ]
        route.fulfill(
            response=response,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def hold_settings(route: Route) -> None:
        if route.request.method != "PUT":
            route.continue_()
            return
        held_settings_routes.append(route)

    def hold_chat(route: Route) -> None:
        held_chat_routes.append(route)

    def hold_events(route: Route) -> None:
        held_event_routes.append(route)

    page.route("**/api/workspace/pages/resume-editor", fulfill_workspace)
    page.route(settings_pattern, hold_settings)
    page.route(chat_pattern, hold_chat)
    page.route(events_pattern, hold_events)
    if action == "retry":
        page.route(
            f"**/api/agent/resumes/{resume_id}/recovery",
            fulfill_retryable_session,
        )
        page.route(
            f"**/api/agent/resumes/{resume_id}/session",
            fulfill_retryable_session,
        )

    try:
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )
        trigger = page.locator('.resume-workspace [data-slot="agent-panel-toggle"]')
        trigger.evaluate("button => button.click()")

        model_trigger = page.locator(
            '[data-slot="agent-composer"] [data-slot="dialog-trigger"]'
        )
        attachment_trigger = page.get_by_role(
            "button",
            name="添加附件",
            exact=True,
        )
        model_trigger.click()
        page.locator('[data-slot="command-item"]').filter(
            has_text=next_model_nickname
        ).click()

        deadline = time.monotonic() + 3
        while not held_settings_routes and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert len(held_settings_routes) == 1

        if action == "send":
            prompt = page.get_by_role(
                "textbox",
                name="你想了解什么？",
                exact=True,
            )
            prompt.fill("请检查并生成修改草稿。")
            prompt.press("Enter")
        else:
            retry = page.get_by_role("button", name="重试", exact=True)
            expect(retry).to_have_count(1)
            retry.click(force=True)

        pending_status = page.locator("#resume-detail-agent-panel").get_by_role(
            "status",
            name="正在分析请求",
            exact=True,
        )
        expect(pending_status).to_be_visible(timeout=750)
        assert held_chat_routes == []
        if action == "send":
            expect(prompt).to_have_value("请检查并生成修改草稿。")
        expect(attachment_trigger).to_be_enabled()
        expect(model_trigger).to_be_enabled()
        if action == "send":
            model_trigger.click()
            page.locator('[data-slot="command-item"]').filter(
                has_text=current_model_nickname
            ).click()
            expect(model_trigger).to_have_attribute(
                "aria-label",
                f"下一条消息将使用 {current_model_nickname}",
            )

        page.unroute(settings_pattern, hold_settings)
        settings_route = held_settings_routes.pop()
        settings_route.fulfill(
            json={
                "code": 0,
                "message": "OK",
                "data": {
                    "locale": "zh",
                    **settings_route.request.post_data_json["settings"],
                },
            },
        )

        deadline = time.monotonic() + 3
        while not held_chat_routes and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert len(held_chat_routes) == 1
        expected_model_nickname = (
            current_model_nickname if action == "send" else next_model_nickname
        )
        expect(model_trigger).to_have_attribute(
            "aria-label",
            f"下一条消息将使用 {expected_model_nickname}",
        )
        if action == "send":
            request_payload = held_chat_routes[0].request.post_data_json
            assert request_payload["message"]["text"] == ("请检查并生成修改草稿。")
            assert request_payload["modelConfig"] == {
                "id": next_model_config_id,
            }
        expect(pending_status).to_be_visible()

        edit_tool = {
            "id": "call-edit-feedback",
            "type": "tool-edit_execute",
            "title": "edit_execute",
            "state": "input-streaming",
            "input": {},
        }
        tool_start_event = (
            "id: 1\n"
            "event: tool_start\n"
            "data: "
            + json.dumps(
                {
                    "timelinePartId": "timeline-edit-feedback",
                    "tool": edit_tool,
                },
                separators=(",", ":"),
            )
            + "\n\n"
        )
        held_chat_routes.pop().fulfill(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "X-Agent-Run-Id": run_id,
            },
            body=tool_start_event,
        )

        edit_status = page.locator("#resume-detail-agent-panel").get_by_role(
            "status",
            name="正在生成可预览草稿",
            exact=True,
        )
        expect(edit_status).to_be_visible(timeout=750)
        if action == "send":
            expect(prompt).to_have_value("")

        deadline = time.monotonic() + 3
        while not held_event_routes and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert held_event_routes
        terminal_event = (
            "id: 2\nevent: run_done\ndata: "
            '{"status":"completed","executionState":"succeeded",'
            '"errorCode":null}\n\n'
        )
        page.unroute(events_pattern, hold_events)
        for route in held_event_routes:
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=terminal_event,
            )
        held_event_routes.clear()
        expect(trigger).to_have_attribute("data-agent-status", "ready")
    finally:
        for route in held_settings_routes:
            try:
                route.fulfill(
                    json={
                        "code": 0,
                        "message": "OK",
                        "data": {
                            "locale": "zh",
                            **route.request.post_data_json["settings"],
                        },
                    },
                )
            except PlaywrightError:
                pass
        for route in held_chat_routes:
            try:
                route.abort()
            except PlaywrightError:
                pass
        for route in held_event_routes:
            try:
                route.abort()
            except PlaywrightError:
                pass
        context.close()


def test_agent_model_switch_during_active_run_applies_to_next_message(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    current_model_config_id = "llm-active-run-current-model"
    next_model_config_id = "llm-active-run-next-model"
    current_model_config_nickname = "Active run current model"
    next_model_config_nickname = "Active run next model"
    run_id = "agent-model-switch-active-run"
    held_event_routes: list[Route] = []
    captured_chat_requests: list[Request] = []

    try:
        resume_detail = page.request.get(
            f"{frontend_url}/api/resumes/{resume_id}"
        ).json()["data"]
        base_resume = resume_detail["resume"]["resume"]
        workspace_pattern = "**/api/workspace/pages/resume-editor"
        settings_pattern = "**/api/workspace/user-settings*"
        recovery_pattern = f"**/api/agent/resumes/{resume_id}/recovery"
        events_pattern = f"**/api/agent/runs/{run_id}/events*"
        chat_pattern = "**/api/agent/chat"
        terminal_event = (
            "id: 1\nevent: run_done\ndata: "
            '{"status":"completed","executionState":"succeeded",'
            '"errorCode":null}\n\n'
        )

        def fulfill_workspace(route: Route) -> None:
            response = route.fetch()
            payload = response.json()
            payload["data"]["modelConfigs"] = [
                {
                    "id": model_config_id,
                    "provider": "openai",
                    "nickname": nickname,
                    "model": model_id,
                    "supportsTools": True,
                }
                for model_config_id, nickname, model_id in (
                    (
                        current_model_config_id,
                        current_model_config_nickname,
                        "test-current-model",
                    ),
                    (
                        next_model_config_id,
                        next_model_config_nickname,
                        "test-next-model",
                    ),
                )
            ]
            payload["data"]["agentSettings"]["defaultModelConfigId"] = (
                current_model_config_id
            )
            route.fulfill(
                response=response,
                content_type="application/json",
                body=json.dumps(payload),
            )

        def fulfill_settings_update(route: Route) -> None:
            route.fulfill(
                json={
                    "code": 0,
                    "message": "OK",
                    "data": {
                        "locale": "zh",
                        **route.request.post_data_json["settings"],
                    },
                },
            )

        def fulfill_recovery(route: Route) -> None:
            response = route.fetch()
            payload = response.json()
            payload["data"]["run"] = {
                "id": run_id,
                "resumeId": resume_id,
                "baseResume": base_resume,
                "status": "active",
                "executionState": "running",
                "errorCode": None,
                "lastEventId": 0,
            }
            route.fulfill(
                response=response,
                content_type="application/json",
                body=json.dumps(payload),
            )

        def hold_events(route: Route) -> None:
            held_event_routes.append(route)

        def fulfill_chat(route: Route) -> None:
            captured_chat_requests.append(route.request)
            route.fulfill(
                status=200,
                headers={
                    "Content-Type": "text/event-stream",
                    "X-Agent-Run-Id": "agent-model-switch-next-run",
                },
                body=terminal_event,
            )

        page.route(workspace_pattern, fulfill_workspace)
        page.route(settings_pattern, fulfill_settings_update)
        page.route(recovery_pattern, fulfill_recovery)
        page.route(events_pattern, hold_events)
        page.route(chat_pattern, fulfill_chat)
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )

        panel_trigger = page.locator(
            '.resume-workspace [data-slot="agent-panel-toggle"]'
        )
        panel_trigger.evaluate("button => button.click()")
        expect(panel_trigger).to_have_attribute("data-agent-status", "responding")

        prompt = page.get_by_role(
            "textbox",
            name="你想了解什么？",
            exact=True,
        )
        expect(prompt).to_be_disabled()
        model_trigger = page.locator(
            '[data-slot="agent-composer"] [data-slot="dialog-trigger"]'
        )
        expect(model_trigger).to_be_enabled()
        expect(model_trigger).to_have_attribute(
            "aria-label",
            f"下一条消息将使用 {current_model_config_nickname}",
        )

        model_trigger.click()
        next_model_config_option = page.locator('[data-slot="command-item"]').filter(
            has_text=next_model_config_nickname
        )
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == "/api/workspace/user-settings"
            )
        ) as settings_update_info:
            next_model_config_option.click()

        assert settings_update_info.value.ok
        expect(model_trigger).to_be_enabled()
        expect(model_trigger).to_have_attribute(
            "aria-label",
            f"下一条消息将使用 {next_model_config_nickname}",
        )
        expect(model_trigger).not_to_contain_text("下一条")
        expect(model_trigger).to_contain_text("TEST-NEXT-MODEL")
        expect(
            page.get_by_text(
                "模型已切换。当前回复继续使用原模型，新模型从下一条消息生效",
                exact=True,
            )
        ).to_be_visible()
        assert captured_chat_requests == []

        page.unroute(events_pattern, hold_events)
        for route in held_event_routes:
            route.fulfill(
                status=200,
                content_type="text/event-stream",
                body=terminal_event,
            )
        held_event_routes.clear()
        expect(panel_trigger).to_have_attribute("data-agent-status", "ready")
        expect(prompt).to_be_enabled()

        prompt.fill("请用新模型检查这份简历。")
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlparse(response.url).path == "/api/agent/chat"
            )
        ) as chat_response_info:
            with page.expect_request(
                lambda request: (
                    request.method == "POST"
                    and urlparse(request.url).path == "/api/agent/chat"
                )
            ) as chat_request_info:
                prompt.press("Enter")

        request_payload = json.loads(chat_request_info.value.post_data or "{}")
        assert request_payload["modelConfig"] == {"id": next_model_config_id}
        assert chat_response_info.value.ok
        assert len(captured_chat_requests) == 1
    finally:
        for route in held_event_routes:
            try:
                route.abort()
            except PlaywrightError:
                pass
        context.close()


def test_agent_hydration_failure_stays_local_without_error_notification(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()
    agent_requests: list[ApiRequest] = []

    def record_agent_read(request: Request) -> None:
        api_request = api_request_key(request)
        if api_request and api_request[1].startswith("/api/agent/"):
            agent_requests.append(api_request)

    def fail_agent_read(route: Route) -> None:
        route.abort()

    page.on("request", record_agent_read)
    page.route(
        f"**/api/agent/resumes/{resume_id}/recovery",
        fail_agent_read,
    )

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="domcontentloaded")
        page.get_by_text("对话加载失败", exact=True).wait_for(state="visible")
        page.wait_for_timeout(250)

        request_counts = Counter(agent_requests)
        recovery_request = ("GET", f"/api/agent/resumes/{resume_id}/recovery")
        assert request_counts[recovery_request] >= 1
        assert set(request_counts) == {recovery_request}
        assert (
            page.locator(
                '[data-sonner-toast][data-type="error"]:not([data-removed="true"])'
            ).count()
            == 0
        )
    finally:
        context.close()
