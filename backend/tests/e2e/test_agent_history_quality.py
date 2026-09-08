"""Agent history rendering and attachment interactions in Chromium."""

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
                "id": "history-model",
                "provider": "openai",
                "nickname": "History",
                "model": "test-model",
                "supportsTools": True,
            }
        ]
        payload["data"]["agentSettings"]["defaultModelConfigId"] = "history-model"
        route.fulfill(response=response, json=payload)

    page.route("**/api/workspace/pages/resume-editor", fulfill_workspace)
    page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
    expect(page.locator('[data-slot="agent-composer"]')).to_be_visible()


@pytest.mark.parametrize(
    ("filename", "mime_type", "delivery"),
    [
        ("job.YAML", "", "picker"),
        ("job.yml", "application/x-yaml", "drop"),
        ("job.MD", "", "picker"),
    ],
)
def test_agent_accepts_advertised_file_extensions(
    browser: Browser,
    workspace_servers: tuple[str, str],
    filename: str,
    mime_type: str,
    delivery: str,
) -> None:
    frontend_url, resume_id = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 900},
    )
    page = context.new_page()
    try:
        _open_agent(page, frontend_url, resume_id)
        composer = page.locator('[data-slot="agent-composer"]')
        if delivery == "picker":
            composer.locator('input[type="file"]').set_input_files(
                {
                    "name": filename,
                    "mimeType": mime_type,
                    "buffer": b"Job description",
                }
            )
        else:
            composer.evaluate(
                """(element, { filename, mimeType }) => {
                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(new File(['Job description'], filename, {
                    type: mimeType,
                }));
                element.dispatchEvent(new DragEvent('drop', {
                    bubbles: true, dataTransfer,
                }));
            }""",
                {"filename": filename, "mimeType": mime_type},
            )
        expect(composer.get_by_text(filename, exact=True)).to_be_visible()
    finally:
        context.close()


def test_agent_stream_preserves_historical_user_rows(
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
        base = page.request.get(f"{frontend_url}/api/resumes/{resume_id}").json()[
            "data"
        ]["resume"]["resume"]
        messages = [
            {
                "id": f"{role}-history-{index}",
                "role": role,
                "text": f"{role} history {index}",
                "createdAt": f"2026-08-10T00:{index:02d}:00.000Z",
            }
            for index in range(30)
            for role in ("user", "assistant")
        ]

        def fulfill_session(route: Route) -> None:
            response = route.fetch()
            payload = response.json()
            payload["data"]["session"]["messages"] = messages
            payload["data"]["run"] = {
                "id": "history-run",
                "resumeId": resume_id,
                "baseResume": base,
                "status": "active",
                "executionState": "running",
                "errorCode": None,
                "lastEventId": 0,
            }
            route.fulfill(response=response, json=payload)

        def instrument_user_row(route: Route) -> None:
            response = route.fetch()
            source = response.text()
            needle = "const submitDisabled ="
            assert source.count(needle) == 1
            route.fulfill(
                response=response,
                body=source.replace(
                    needle,
                    "window.__historyUserRenders += 1; " + needle,
                ),
            )

        page.add_init_script("""window.__historyUserRenders = 0;
            const originalFetch = window.fetch;
            window.fetch = async (...args) => {
                if (String(args[0]).includes('/api/agent/runs/history-run/events')) {
                    const stream = new ReadableStream({ start(controller) {
                        window.__emitHistoryEvent = (id, event, payload) => {
                            controller.enqueue(new TextEncoder().encode(
                                `id: ${id}\nevent: ${event}\n` +
                                `data: ${JSON.stringify(payload)}\n\n`
                            ));
                        };
                    }});
                    return new Response(stream, {
                        headers: { 'Content-Type': 'text/event-stream' },
                    });
                }
                return originalFetch(...args);
            };
        """)
        page.route(f"**/api/agent/resumes/{resume_id}/recovery", fulfill_session)
        page.route(
            "**/src/components/copilot/copilot-user-message-row.tsx*",
            instrument_user_row,
        )
        _open_agent(page, frontend_url, resume_id)
        expect(page.locator(".agent-thread-scroll .is-user")).to_have_count(30)
        page.wait_for_function("typeof window.__emitHistoryEvent === 'function'")
        page.evaluate("""() => window.__emitHistoryEvent(1, 'message_start', {
            message: { id: 'active-history', role: 'assistant', text: '' },
        })""")
        page.wait_for_timeout(200)
        renders = page.evaluate("""async () => {
            window.__historyUserRenders = 0;
            for (let index = 0; index < 10; index += 1) {
                window.__emitHistoryEvent(index + 2, 'text_delta', {
                    delta: 'stream chunk ', timelinePartId: 'history-text',
                });
                await new Promise(resolve => setTimeout(resolve, 70));
            }
            return window.__historyUserRenders;
        }""")
        expect(page.locator(".agent-thread-scroll")).to_contain_text(
            "stream chunk " * 10
        )
        assert renders == 0, f"Unchanged historical user rows rendered {renders} times"
    finally:
        context.close()


@pytest.mark.parametrize("action", ["edit", "retry"])
def test_agent_history_actions_keep_the_selected_message_and_attachments(
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
    original_text = "Keep the facts from this message."
    files = [
        {
            "id": "history-file",
            "filename": "history.txt",
            "mediaType": "text/plain",
            "kind": "text",
        }
    ]
    messages = [
        {
            "id": "user-actions",
            "role": "user",
            "text": original_text,
            "files": files,
            "createdAt": "2026-08-10T00:00:00.000Z",
        }
    ]
    replacements = []

    def fulfill_session(route: Route) -> None:
        response = route.fetch(method="GET")
        payload = response.json()
        if route.request.method == "PUT":
            replacements.append(route.request.post_data_json["messages"])
        session = (
            payload["data"]["session"]
            if route.request.url.endswith("/recovery")
            else payload["data"]
        )
        session["messages"] = messages
        session["executions"] = [
            {
                "runId": "failed-actions",
                "turnId": "user-actions",
                "status": "failed",
                "errorCode": "AGENT_PROVIDER_ERROR",
                "modelSnapshot": None,
                "startedAt": "2026-08-10T00:00:00.000Z",
                "completedAt": "2026-08-10T00:00:01.000Z",
            }
        ]
        route.fulfill(response=response, json=payload)

    try:
        page.add_init_script("""Object.defineProperty(navigator, 'clipboard', {
            value: { writeText: async text => { window.__copiedHistoryText = text; } },
        });""")
        page.route(f"**/api/agent/resumes/{resume_id}/session", fulfill_session)
        page.route(f"**/api/agent/resumes/{resume_id}/recovery", fulfill_session)
        page.route("**/api/agent/chat", lambda route: route.abort("failed"))
        page.route(
            "**/attachments/history-file",
            lambda route: route.fulfill(
                content_type="text/plain",
                body="Stored attachment",
            ),
        )
        _open_agent(page, frontend_url, resume_id)
        row = page.locator(".agent-thread-scroll .is-user")
        expect(row).to_have_count(1)
        row.hover()
        row.get_by_role("button", name="复制消息", exact=True).click()
        page.wait_for_function(
            "window.__copiedHistoryText === 'Keep the facts from this message.'"
        )
        attachment = row.get_by_role("button", name="history.txt", exact=True)
        with page.expect_download() as download:
            attachment.click()
        assert download.value.suggested_filename == "history.txt"
        attachment.hover()
        page.get_by_role("button", name="添加到消息", exact=True).click()
        expect(
            page.locator('[data-slot="agent-composer"]').get_by_text(
                "history.txt",
                exact=True,
            )
        ).to_be_visible()
        row.hover()
        row.get_by_role("button", name="修改消息", exact=True).click()
        editor = row.get_by_role("textbox")
        expect(editor).to_have_value(original_text)
        editor.fill("Unsaved edit")
        editor.press("Escape")
        expect(row.get_by_role("textbox")).to_have_count(0)
        expect(row).to_contain_text(original_text)
        with page.expect_request("**/api/agent/chat") as request:
            if action == "edit":
                row.hover()
                row.get_by_role("button", name="修改消息", exact=True).click()
                editor = row.get_by_role("textbox")
                editor.fill("Revised request, with the same attachment.")
                editor.press("Control+Enter")
            else:
                row.hover()
                row.get_by_role("button", name="重试", exact=True).click()
        payload = request.value.post_data_json
        assert payload["message"]["id"] == "user-actions"
        assert payload["message"]["files"] == files
        assert payload["message"]["text"] == (
            "Revised request, with the same attachment."
            if action == "edit"
            else original_text
        )
        assert payload["messages"] == []
        assert replacements == ([[payload["message"]]] if action == "edit" else [])
    finally:
        context.close()


def test_completed_reply_is_restored_from_one_recovery_snapshot(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 900}
    )
    page = context.new_page()
    recovery_reads = []
    separate_reads = []

    def fulfill_recovery(route: Route) -> None:
        recovery_reads.append(route.request.url)
        response = route.fetch()
        payload = response.json()
        payload["data"]["run"] = None
        payload["data"]["session"]["messages"] = [
            {
                "id": "recovered-user",
                "role": "user",
                "text": "Check this resume.",
                "createdAt": "2026-08-10T00:00:00.000Z",
            },
            {
                "id": "recovered-assistant",
                "role": "assistant",
                "text": "The completed reply is preserved.",
                "createdAt": "2026-08-10T00:00:01.000Z",
            },
        ]
        payload["data"]["session"]["executions"] = [
            {
                "runId": "completed-recovery",
                "turnId": "recovered-user",
                "status": "succeeded",
                "errorCode": None,
                "modelSnapshot": None,
                "startedAt": "2026-08-10T00:00:00.000Z",
                "completedAt": "2026-08-10T00:00:01.000Z",
            }
        ]
        route.fulfill(response=response, json=payload)

    def record_separate_read(route: Route) -> None:
        separate_reads.append(route.request.url)
        route.continue_()

    try:
        page.route(f"**/api/agent/resumes/{resume_id}/recovery", fulfill_recovery)
        page.route(f"**/api/agent/resumes/{resume_id}/session", record_separate_read)
        _open_agent(page, frontend_url, resume_id)
        expect(page.locator(".agent-thread-scroll")).to_contain_text(
            "The completed reply is preserved."
        )
        prompt = page.get_by_role("textbox", name="你想了解什么？", exact=True)
        expect(prompt).to_be_enabled()
        expect(prompt).to_have_attribute("placeholder", "")
        assert set(recovery_reads) == {
            f"{frontend_url}/api/agent/resumes/{resume_id}/recovery"
        }
        assert separate_reads == []
    finally:
        context.close()
