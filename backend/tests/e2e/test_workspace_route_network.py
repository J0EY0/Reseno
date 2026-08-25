"""Browser-level request allowlist for workspace routes.

Run explicitly because this test starts both application servers and Chromium:

    RUN_BROWSER_E2E=1 pytest tests/e2e/test_workspace_route_network.py -q
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from collections.abc import Iterator
from pathlib import Path
from socket import AF_INET, SOCK_STREAM, socket
from typing import Any, TextIO
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
    Request,
    Route,
    expect,
    sync_playwright,
)
from playwright.sync_api import Error as PlaywrightError

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
FRONTEND_ROOT = REPOSITORY_ROOT / "frontend"
_BROWSER_AUTH_SESSION: dict[str, str] | None = None


def _unused_port() -> int:
    with socket(AF_INET, SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _process_output(log: TextIO) -> str:
    log.flush()
    log.seek(0)
    return log.read()


def _wait_for_url(
    url: str,
    process: subprocess.Popen[str],
    log: TextIO,
    *,
    timeout_seconds: float = 30,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        if process.poll() is not None:
            pytest.fail(
                f"Server exited while waiting for {url}.\n{_process_output(log)}"
            )

        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status < 500:
                    return
        except (OSError, urllib.error.URLError) as error:
            last_error = error

        time.sleep(0.1)

    pytest.fail(f"Timed out waiting for {url}: {last_error}\n{_process_output(log)}")


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


@pytest.fixture(scope="module")
def workspace_servers() -> Iterator[tuple[str, str]]:
    """Start isolated backend/frontend servers and seed one resume."""

    global _BROWSER_AUTH_SESSION

    node = shutil.which("node")
    vite_cli = FRONTEND_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None or not vite_cli.exists():
        pytest.fail("Install frontend dependencies before running browser E2E tests.")

    backend_port = _unused_port()
    frontend_port = _unused_port()
    backend_url = f"http://127.0.0.1:{backend_port}"
    frontend_url = f"http://127.0.0.1:{frontend_port}"
    processes: list[subprocess.Popen[str]] = []
    logs: list[TextIO] = []

    with tempfile.TemporaryDirectory(prefix="resumate-route-e2e-") as data_dir:
        data_path = Path(data_dir)
        backend_env = {
            **os.environ,
            "APP_DATA_DIR": str(data_path),
            "APP_DB_PATH": str(data_path / "app.db"),
            "APP_STORAGE_DIR": str(data_path / "storage"),
            "APP_ENV_FILE": str(data_path / ".env"),
            "FRONTEND_RENDER_BASE_URL": frontend_url,
            "BACKEND_CORS_ORIGINS": frontend_url,
        }
        frontend_env = {
            **os.environ,
            "RESUMATE_VITE_CACHE_DIR": str(data_path / "vite-cache"),
            "VITE_DEV_API_TARGET": backend_url,
        }

        try:
            backend_log = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
            logs.append(backend_log)
            backend_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(backend_port),
                ],
                cwd=BACKEND_ROOT,
                env=backend_env,
                stdout=backend_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            processes.append(backend_process)
            _wait_for_url(f"{backend_url}/health", backend_process, backend_log)

            setup_request = urllib.request.Request(
                f"{backend_url}/api/auth/setup",
                data=json.dumps(
                    {
                        "username": "e2e-owner",
                        "password": "E2ePassword2026",
                        "confirmPassword": "E2ePassword2026",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(setup_request, timeout=10) as response:
                setup_payload = json.load(response)["data"]
            access_token = str(setup_payload["accessToken"])
            _BROWSER_AUTH_SESSION = {
                "username": str(setup_payload["username"]),
                "authenticatedAt": "2026-08-09T00:00:00.000Z",
                "accessToken": access_token,
                "expiresAt": str(setup_payload["expiresAt"]),
            }

            frontend_log = tempfile.TemporaryFile(mode="w+", encoding="utf-8")
            logs.append(frontend_log)
            frontend_process = subprocess.Popen(
                [
                    node,
                    str(vite_cli),
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(frontend_port),
                    "--strictPort",
                ],
                cwd=FRONTEND_ROOT,
                env=frontend_env,
                stdout=frontend_log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            processes.append(frontend_process)
            _wait_for_url(frontend_url, frontend_process, frontend_log)

            create_request = urllib.request.Request(
                f"{backend_url}/api/resumes",
                data=b"{}",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            with urllib.request.urlopen(create_request, timeout=10) as response:
                payload = json.load(response)
            resume_id = str(payload["data"]["resume"]["id"])

            yield frontend_url, resume_id
        finally:
            for process in reversed(processes):
                _stop_process(process)
            for log in logs:
                log.close()
            _BROWSER_AUTH_SESSION = None


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()


def _authenticated_context(
    browser: Browser,
    **kwargs: Any,
) -> BrowserContext:
    session = _BROWSER_AUTH_SESSION
    if session is None:
        raise RuntimeError("Browser auth session has not been initialized.")

    context = browser.new_context(
        extra_http_headers={"Authorization": f"Bearer {session['accessToken']}"},
        **kwargs,
    )
    session_json = json.dumps(session)
    context.add_init_script(
        script=(
            "window.sessionStorage.setItem("
            "'resumate-auth-session', "
            f"{json.dumps(session_json)});"
        )
    )
    return context


ApiRequest = tuple[str, str]
AUTH_SETUP_STATUS_REQUEST: ApiRequest = ("GET", "/api/auth/setup")


def _api_request(request: Request) -> ApiRequest | None:
    path = urlparse(request.url).path
    if not path.startswith("/api/"):
        return None
    return request.method, path


def _observe_api_requests(browser: Browser, url: str) -> list[ApiRequest]:
    context = _authenticated_context(browser)
    page = context.new_page()
    requests: list[ApiRequest] = []
    page.on(
        "request",
        lambda request: (
            requests.append(api_request)
            if (api_request := _api_request(request)) is not None
            else None
        ),
    )

    try:
        page.goto(url, wait_until="networkidle")
    finally:
        context.close()

    return requests


def _install_workspace_frame_recorder(page: Page) -> None:
    page.add_init_script(
        """
        (() => {
          window.__workspaceFrames = [];
          window.__recordWorkspaceFrames = false;
          const visibleElement = (selector) => {
            const element = document.querySelector(selector);
            if (!element) return null;
            const style = window.getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            if (
              style.display === "none" ||
              style.visibility === "hidden" ||
              Number(style.opacity) === 0 ||
              rect.width === 0 ||
              rect.height === 0
            ) {
              return null;
            }
            return { element, rect };
          };
          const capture = (now) => {
            if (window.__recordWorkspaceFrames) {
              const resumeGallery = visibleElement(
                'input[name="resume-search"]',
              );
              const routeSpinner = visibleElement(
                '#root > .min-h-svh > svg[role="status"][aria-label="Loading"]',
              );
              const sidebar = visibleElement('[data-slot="sidebar-container"]');
              const resumeDetail = visibleElement(
                ".resume-workspace .resume-preview-card article.resume-page",
              );
              const resumePreviewFrame = visibleElement(
                ".resume-workspace .resume-preview-scale-frame",
              );
              const templateGallery = visibleElement(
                '[data-slot="sidebar-inset"] a[href="/template/minimal"]',
              );
              const templateDetail = visibleElement(
                ".template-workspace .resume-preview-card article.resume-page",
              );
              const trashContent = visibleElement(
                '[data-slot="sidebar-inset"] section [data-slot="tabs-trigger"]',
              );
              const modelsContent = visibleElement(
                '[data-slot="sidebar-inset"] [data-slot="empty-title"]',
              );
              const settingsContent = visibleElement(
                '[data-slot="sidebar-inset"] ' +
                '[data-slot="tabs-trigger"][data-state="active"]',
              );
              const resumePreviewFits = Boolean(
                resumeDetail &&
                resumePreviewFrame &&
                resumeDetail.rect.left >= resumePreviewFrame.rect.left - 1 &&
                resumeDetail.rect.right <= resumePreviewFrame.rect.right + 1
              );
              window.__workspaceFrames.push({
                time: now,
                path: window.location.pathname,
                hasResumeGallery: Boolean(resumeGallery),
                hasRouteSpinner: Boolean(routeSpinner),
                hasSidebar: Boolean(sidebar),
                hasResumeDetail: Boolean(resumeDetail),
                resumePreviewFits,
                resumePreviewWidth: resumeDetail?.rect.width ?? null,
                hasTemplateGallery: Boolean(templateGallery),
                hasTemplateDetail: Boolean(templateDetail),
                hasTrashContent: Boolean(trashContent),
                hasModelsContent: Boolean(modelsContent),
                hasSettingsContent: Boolean(settingsContent),
              });
            }
            window.requestAnimationFrame(capture);
          };
          window.requestAnimationFrame(capture);
        })();
        """,
    )


def _start_workspace_frame_recording(page: Page) -> None:
    page.evaluate(
        """
        () => {
          window.__workspaceFrames = [];
          window.__recordWorkspaceFrames = true;
        }
        """,
    )


def _stop_workspace_frame_recording(page: Page) -> list[dict[str, object]]:
    return page.evaluate(
        """
        () => {
          window.__recordWorkspaceFrames = false;
          return window.__workspaceFrames;
        }
        """,
    )


def _boolean_runs(values: list[bool]) -> list[tuple[bool, int]]:
    runs: list[tuple[bool, int]] = []

    for value in values:
        if runs and runs[-1][0] == value:
            previous_value, count = runs[-1]
            runs[-1] = previous_value, count + 1
        else:
            runs.append((value, 1))

    return runs


def _assert_visible_once_mounted(
    frames: list[dict[str, object]],
    key: str,
) -> None:
    states = [bool(frame[key]) for frame in frames]

    assert any(states), _boolean_runs(states)
    first_visible_frame = states.index(True)
    assert all(states[first_visible_frame:]), _boolean_runs(states)


@pytest.mark.parametrize(
    ("route", "expected_paths"),
    [
        (
            "/resume",
            [AUTH_SETUP_STATUS_REQUEST, ("GET", "/api/workspace/pages/resumes")],
        ),
        (
            "/templates",
            [AUTH_SETUP_STATUS_REQUEST, ("GET", "/api/workspace/pages/templates")],
        ),
        (
            "/template/minimal",
            [AUTH_SETUP_STATUS_REQUEST, ("GET", "/api/workspace/pages/templates")],
        ),
        (
            "/trash",
            [AUTH_SETUP_STATUS_REQUEST, ("GET", "/api/workspace/pages/trash")],
        ),
        (
            "/models",
            [AUTH_SETUP_STATUS_REQUEST, ("GET", "/api/workspace/pages/models")],
        ),
        (
            "/settings",
            [AUTH_SETUP_STATUS_REQUEST, ("GET", "/api/workspace/pages/settings")],
        ),
    ],
)
def test_workspace_route_request_allowlist(
    browser: Browser,
    workspace_servers: tuple[str, str],
    route: str,
    expected_paths: list[ApiRequest],
) -> None:
    frontend_url, _ = workspace_servers
    actual_paths = _observe_api_requests(browser, f"{frontend_url}{route}")

    assert Counter(actual_paths) == Counter(expected_paths)


def test_resume_editor_route_request_allowlist(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    expected_paths = [
        AUTH_SETUP_STATUS_REQUEST,
        ("GET", "/api/workspace/pages/resume-editor"),
        ("GET", f"/api/resumes/{resume_id}"),
        ("GET", f"/api/resumes/{resume_id}/versions"),
    ]
    actual_paths = _observe_api_requests(
        browser,
        f"{frontend_url}/resume/{resume_id}",
    )

    assert Counter(actual_paths) == Counter(expected_paths)


def _seed_pending_agent_draft(
    page: Page,
    frontend_url: str,
    *,
    message_id: str,
    summary: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    create_response = page.request.post(f"{frontend_url}/api/resumes", data={})
    assert create_response.ok
    resume_id = str(create_response.json()["data"]["resume"]["id"])
    detail = page.request.get(f"{frontend_url}/api/resumes/{resume_id}").json()["data"]
    base_resume = detail["resume"]["resume"]
    candidate_resume = json.loads(json.dumps(base_resume))
    candidate_resume["basic"]["summary"] = summary
    session = page.request.get(
        f"{frontend_url}/api/agent/resumes/{resume_id}/session"
    ).json()["data"]
    seed_response = page.request.put(
        f"{frontend_url}/api/agent/resumes/{resume_id}/session",
        data={
            "locale": "zh",
            "revision": session["revision"],
            "messages": [
                {
                    "id": message_id,
                    "role": "assistant",
                    "text": "草稿等待确认。",
                    "createdAt": "2026-08-10T00:00:00.000Z",
                    "response": {
                        "id": message_id,
                        "role": "assistant",
                        "text": "草稿等待确认。",
                        "edits": [
                            {
                                "id": f"edit-{message_id}",
                                "title": "改写个人总结",
                                "target": "basic.summary",
                                "reason": "验证待确认草稿只能由当前页面确认。",
                                "operation": {
                                    "type": "replace_field",
                                    "path": "basic.summary",
                                    "value": summary,
                                },
                                "status": "executed",
                            }
                        ],
                        "draft": {
                            "baseResume": base_resume,
                            "status": "pending",
                        },
                        "transactionState": "committed",
                    },
                }
            ],
        },
    )
    assert seed_response.ok
    return resume_id, detail, candidate_resume


def _seed_sourced_agent_response(page: Page, frontend_url: str) -> str:
    create_response = page.request.post(f"{frontend_url}/api/resumes", data={})
    assert create_response.ok
    resume_id = str(create_response.json()["data"]["resume"]["id"])
    session = page.request.get(
        f"{frontend_url}/api/agent/resumes/{resume_id}/session"
    ).json()["data"]
    message_id = "assistant-sources"
    response_text = "**公开岗位样本**显示常见要求。\n\n"
    seed_response = page.request.put(
        f"{frontend_url}/api/agent/resumes/{resume_id}/session",
        data={
            "locale": "zh",
            "revision": session["revision"],
            "messages": [
                {
                    "id": "user-sources",
                    "role": "user",
                    "text": "研究 AI 前端工程师的公开要求。",
                    "createdAt": "2026-08-10T00:00:00.000Z",
                },
                {
                    "id": message_id,
                    "role": "assistant",
                    "text": response_text,
                    "createdAt": "2026-08-10T00:00:01.000Z",
                    "response": {
                        "id": message_id,
                        "role": "assistant",
                        "text": response_text,
                        "sources": [
                            {
                                "id": "source-a",
                                "title": "AI Frontend Engineer",
                                "sourceType": "web",
                                "url": "https://aiqicha.baidu.com/details/unknown",
                                "excerpt": (
                                    "Requirements include React and TypeScript."
                                ),
                            },
                            {
                                "id": "source-b",
                                "title": "Duplicate Source",
                                "sourceType": "web",
                                "url": "https://aiqicha.baidu.com/details/unknown",
                            },
                            {
                                "id": "source-c",
                                "title": "Frontend role guide",
                                "sourceType": "web",
                                "url": "https://b.example/frontend-guide",
                            },
                            {
                                "id": "source-d",
                                "title": "Frontend role sample C",
                                "sourceType": "web",
                                "url": "https://c.example/frontend-guide",
                            },
                            {
                                "id": "source-e",
                                "title": "Frontend role sample D",
                                "sourceType": "web",
                                "url": "https://d.example/frontend-guide",
                            },
                            {
                                "id": "source-f",
                                "title": "Frontend role sample E",
                                "sourceType": "web",
                                "url": "https://e.example/frontend-guide",
                            },
                        ],
                    },
                },
            ],
        },
    )
    assert seed_response.ok
    return resume_id


def _seed_long_agent_history(page: Page, frontend_url: str) -> str:
    create_response = page.request.post(f"{frontend_url}/api/resumes", data={})
    assert create_response.ok
    resume_id = str(create_response.json()["data"]["resume"]["id"])
    session = page.request.get(
        f"{frontend_url}/api/agent/resumes/{resume_id}/session"
    ).json()["data"]
    messages: list[dict[str, Any]] = []

    for index in range(12):
        user_id = f"user-scroll-{index}"
        assistant_id = f"assistant-scroll-{index}"
        user_text = f"第 {index + 1} 轮：分析这份简历与目标岗位的匹配情况。"
        assistant_text = (
            f"第 {index + 1} 轮分析结果：保留已有事实，"
            "并从职责、技术栈和可验证成果三个角度说明改进方向。"
        )
        messages.extend(
            [
                {
                    "id": user_id,
                    "role": "user",
                    "text": user_text,
                    "createdAt": f"2026-08-10T00:{index * 2:02d}:00.000Z",
                },
                {
                    "id": assistant_id,
                    "role": "assistant",
                    "text": assistant_text,
                    "createdAt": f"2026-08-10T00:{index * 2 + 1:02d}:00.000Z",
                    "response": {
                        "id": assistant_id,
                        "role": "assistant",
                        "text": assistant_text,
                    },
                },
            ]
        )

    seed_response = page.request.put(
        f"{frontend_url}/api/agent/resumes/{resume_id}/session",
        data={
            "locale": "zh",
            "revision": session["revision"],
            "messages": messages,
        },
    )
    assert seed_response.ok
    return resume_id


def test_agent_history_fades_without_masking_native_scrollbar(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()

    try:
        resume_id = _seed_long_agent_history(page, frontend_url)
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")

        scroll_owner = page.locator(".agent-thread-scroll")
        scroll_owner.wait_for(state="visible")
        fade = page.locator('[data-slot="agent-thread-fade"]')
        composer = page.locator('[data-slot="agent-composer"]')

        assert fade.count() == 1
        assert composer.count() == 1
        metrics = page.locator(".agent-thread-layout").evaluate(
            """
            layout => {
              const scrollOwner = layout.querySelector('.agent-thread-scroll');
              const fade = layout.querySelector('[data-slot="agent-thread-fade"]');
              const composer = layout.querySelector('[data-slot="agent-composer"]');
              const safeArea = layout.querySelector('.agent-thread-safe-area');
              if (!(scrollOwner instanceof HTMLElement) ||
                  !(fade instanceof HTMLElement) ||
                  !(composer instanceof HTMLElement) ||
                  !(safeArea instanceof HTMLElement)) {
                throw new Error('Missing Agent thread layout surfaces.');
              }

              const scrollStyle = getComputedStyle(scrollOwner);
              const fadeStyle = getComputedStyle(fade);
              const layoutStyle = getComputedStyle(layout);
              const scrollRect = scrollOwner.getBoundingClientRect();
              const fadeRect = fade.getBoundingClientRect();
              const composerRect = composer.getBoundingClientRect();
              const safeAreaRect = safeArea.getBoundingClientRect();
              const safeAreaStyle = getComputedStyle(safeArea);
              const contentRight =
                safeAreaRect.right - Number.parseFloat(safeAreaStyle.paddingRight);
              const midpoint = Number.parseFloat(
                layoutStyle.getPropertyValue('--agent-composer-midpoint'),
              );
              const safeGap = Number.parseFloat(
                layoutStyle.getPropertyValue('--agent-thread-safe-gap'),
              );
              const safePadding = Number.parseFloat(
                getComputedStyle(safeArea).paddingBottom,
              );

              scrollOwner.scrollTop = Math.round(
                (scrollOwner.scrollHeight - scrollOwner.clientHeight) / 2,
              );

              return {
                backgroundImage: fadeStyle.backgroundImage,
                backgroundSize: fadeStyle.backgroundSize,
                composerHeight: composerRect.height,
                contentRight,
                fadeBottom: fadeRect.bottom,
                fadeIsOutsideScrollOwner:
                  fade.parentElement === layout && !scrollOwner.contains(fade),
                fadePointerEvents: fadeStyle.pointerEvents,
                fadeRightClearance: scrollRect.right - fadeRect.right,
                fadeRight: fadeRect.right,
                isScrollable: scrollOwner.scrollHeight > scrollOwner.clientHeight,
                maskImage: scrollStyle.maskImage,
                midpoint,
                overflowY: scrollStyle.overflowY,
                safeGap,
                safePadding,
                scrollBottom: scrollRect.bottom,
                scrollbarGutter: scrollStyle.scrollbarGutter,
                scrollTop: scrollOwner.scrollTop,
                webkitMaskImage: scrollStyle.webkitMaskImage,
              };
            }
            """
        )

        assert metrics["isScrollable"] is True
        assert metrics["scrollTop"] > 0
        assert metrics["overflowY"] == "auto"
        assert metrics["maskImage"] == "none"
        assert metrics["webkitMaskImage"] == "none"
        assert metrics["fadeIsOutsideScrollOwner"] is True
        assert metrics["fadePointerEvents"] == "none"
        assert "linear-gradient" in metrics["backgroundImage"]
        assert metrics["backgroundSize"].endswith(f"100% {metrics['midpoint']}px")
        assert "stable" in metrics["scrollbarGutter"]
        assert metrics["fadeRightClearance"] > 0
        assert abs(metrics["fadeRight"] - metrics["contentRight"]) <= 1
        assert abs(metrics["fadeBottom"] - metrics["scrollBottom"]) <= 1
        assert abs(metrics["midpoint"] - metrics["composerHeight"] / 2) <= 1
        assert (
            abs(
                metrics["safePadding"]
                - (metrics["composerHeight"] + metrics["safeGap"])
            )
            <= 1
        )

        scroll_owner.evaluate(
            "element => { element.scrollTop = element.scrollHeight; }"
        )
        page.wait_for_function(
            """
            () => {
              const owner = document.querySelector('.agent-thread-scroll');
              return owner instanceof HTMLElement &&
                Math.abs(
                  owner.scrollHeight - owner.clientHeight - owner.scrollTop
                ) <= 1;
            }
            """
        )
    finally:
        context.close()


def test_agent_sources_render_once_after_the_response(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()
    page.add_init_script(
        """
        Object.defineProperty(navigator, "clipboard", {
          configurable: true,
          value: {
            writeText: async (value) => {
              window.__copiedSourceUrl = value;
            },
          },
        });
        """
    )

    try:
        resume_id = _seed_sourced_agent_response(page, frontend_url)
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")

        claim = page.get_by_text(
            "公开岗位样本显示常见要求。",
            exact=True,
        )
        claim.wait_for(state="visible")
        assert claim.locator('[data-streamdown="strong"]').count() == 1
        assert page.get_by_role("button", name="Sources (1)").count() == 0
        trigger = page.get_by_text("aiqicha.baidu.com +4", exact=True)
        assert trigger.count() == 1

        claim_tail_box = claim.evaluate(
            """
            (element) => {
              const walker = document.createTreeWalker(
                element,
                NodeFilter.SHOW_TEXT,
              );
              let tail = null;
              for (let node = walker.nextNode(); node; node = walker.nextNode()) {
                if (node.textContent) {
                  tail = node;
                }
              }
              const range = document.createRange();
              range.setStart(tail, tail.textContent.length - 1);
              range.setEnd(tail, tail.textContent.length);
              const rect = range.getBoundingClientRect();
              return {
                x: rect.x,
                y: rect.y,
                width: rect.width,
                height: rect.height,
              };
            }
            """
        )
        trigger_box = trigger.bounding_box()
        assert trigger_box is not None
        assert abs(
            (claim_tail_box["y"] + claim_tail_box["height"] / 2)
            - (trigger_box["y"] + trigger_box["height"] / 2)
        ) <= 4
        tail_gap = trigger_box["x"] - (
            claim_tail_box["x"] + claim_tail_box["width"]
        )
        assert 0 <= tail_gap <= 16

        trigger.hover()
        card = page.locator('[data-slot="hover-card-content"]')
        card.wait_for(state="visible")

        card_box = card.bounding_box()
        viewport = page.viewport_size
        assert card_box is not None
        assert viewport is not None
        assert card_box["x"] >= 12
        assert card_box["x"] + card_box["width"] <= viewport["width"] - 12

        source_url = "https://aiqicha.baidu.com/details/unknown"
        source_link = card.locator(f'a[href="{source_url}"]')
        copy_buttons = card.get_by_role(
            "button",
            name="Copy source link",
            exact=True,
        )
        copy_button = copy_buttons.first
        page.evaluate(
            """
            () => {
              window.__citationCardStates = [];
              let lastState = null;
              const record = () => {
                const content = document.querySelector(
                  '[data-slot="hover-card-content"]',
                );
                const state = content?.getAttribute("data-state") ?? "unmounted";
                if (state !== lastState) {
                  window.__citationCardStates.push(state);
                  lastState = state;
                }
              };
              record();
              new MutationObserver(record).observe(document.body, {
                attributeFilter: ["data-state"],
                attributes: true,
                childList: true,
                subtree: true,
              });
            }
            """
        )
        page.mouse.move(
            trigger_box["x"] + trigger_box["width"] / 2,
            trigger_box["y"] + trigger_box["height"] / 2,
        )
        page.mouse.move(
            trigger_box["x"] + trigger_box["width"] / 2,
            (card_box["y"] + card_box["height"] + trigger_box["y"]) / 2,
        )
        page.wait_for_timeout(60)
        gap_state = (
            card.get_attribute("data-state") if card.count() else "unmounted"
        )
        page.mouse.move(
            card_box["x"] + card_box["width"] / 2,
            card_box["y"] + card_box["height"] / 2,
            steps=12,
        )
        page.wait_for_timeout(280)
        arrival_state = (
            card.get_attribute("data-state") if card.count() else "unmounted"
        )
        assert {
            "arrivalState": arrival_state,
            "copyButtonCount": copy_buttons.count(),
            "cardStates": page.evaluate("window.__citationCardStates"),
            "gapState": gap_state,
            "linkCount": source_link.count(),
        } == {
            "arrivalState": "open",
            "copyButtonCount": 5,
            "cardStates": ["open"],
            "gapState": "open",
            "linkCount": 1,
        }

        copy_button.click()
        page.wait_for_function(
            "expected => window.__copiedSourceUrl === expected",
            arg=source_url,
        )
        assert source_link.get_attribute("target") == "_blank"
        assert source_link.get_attribute("rel") == "noreferrer"
        context.route(
            source_url,
            lambda route: route.fulfill(
                status=200,
                content_type="text/plain",
                body="source",
            ),
        )
        with page.expect_popup() as source_page_info:
            source_link.click()
        source_page = source_page_info.value
        source_page.wait_for_load_state("domcontentloaded")
        assert source_page.url == source_url
        source_page.close()
        trigger.hover()
        card.wait_for(state="visible")

        assert card.get_by_text("AI Frontend Engineer", exact=True).count() == 1
        expect(card.get_by_text("1/5", exact=True)).to_be_visible()
        assert page.get_by_text("Duplicate Source", exact=True).count() == 0
        assert card.get_by_text(
            "Requirements include React and TypeScript.",
            exact=True,
        ).count() == 0
        card.get_by_role("button", name="Next", exact=True).click()
        expect(card.get_by_text("Frontend role guide", exact=True)).to_be_visible()
        expect(card.get_by_text("2/5", exact=True)).to_be_visible()
    finally:
        context.close()


def test_pending_agent_draft_page_load_stays_preview_only(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()

    try:
        pending_summary = "Pending Agent preview must never autosave."
        resume_id, detail_before, _ = _seed_pending_agent_draft(
            page,
            frontend_url,
            message_id="assistant-pending-page-load",
            summary=pending_summary,
        )
        formal_resume = detail_before["resume"]["resume"]

        writes: list[ApiRequest] = []

        def record_write(request: Request) -> None:
            api_request = _api_request(request)
            if api_request and request.method in {"PATCH", "POST", "PUT", "DELETE"}:
                writes.append(api_request)

        page.on("request", record_write)
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )
        page.get_by_role("button", name="应用草稿", exact=True).wait_for(
            state="visible"
        )
        assert page.get_by_text(pending_summary, exact=True).count() > 0

        # Cross the complete autosave debounce without touching either draft
        # decision. Hydration may render the candidate, but it is not a user
        # confirmation and must remain read-only.
        page.wait_for_timeout(5_500)

        assert writes == []
        detail_after = page.request.get(
            f"{frontend_url}/api/resumes/{resume_id}"
        ).json()["data"]
        session_after = page.request.get(
            f"{frontend_url}/api/agent/resumes/{resume_id}/session"
        ).json()["data"]
        assistant_response = session_after["messages"][-1]["response"]

        assert detail_after["versionId"] == detail_before["versionId"]
        assert detail_after["resume"]["resume"] == formal_resume
        assert assistant_response["draft"]["status"] == "pending"
    finally:
        context.close()


def test_pending_agent_draft_waits_for_complete_session_hydration(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()

    try:
        pending_summary = "Pending draft restored after complete hydration."
        resume_id, _, _ = _seed_pending_agent_draft(
            page,
            frontend_url,
            message_id="assistant-pending-hydration",
            summary=pending_summary,
        )
        held_active_run_routes: list[Route] = []
        active_run_pattern = f"**/api/agent/resumes/{resume_id}/run"

        def hold_active_run(route: Route) -> None:
            held_active_run_routes.append(route)

        page.route(active_run_pattern, hold_active_run)
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="domcontentloaded",
        )

        loading = page.get_by_text("正在加载 Agent 对话…", exact=True)
        loading.wait_for(state="visible")
        page.wait_for_timeout(100)
        assert held_active_run_routes
        empty_prompt = page.get_by_text(
            "我可以帮你润色经历、调整简历结构。", exact=True
        )
        assert empty_prompt.count() == 0
        assert page.get_by_role("button", name="应用草稿", exact=True).count() == 0
        assert page.get_by_role("button", name="撤回草稿", exact=True).count() == 0

        page.unroute(active_run_pattern, hold_active_run)
        for route in held_active_run_routes:
            try:
                route.continue_()
            except PlaywrightError:
                # React Strict Mode may already have aborted an earlier owner.
                pass
        held_active_run_routes.clear()
        loading.wait_for(state="hidden")
        page.get_by_role("button", name="应用草稿", exact=True).wait_for(
            state="visible"
        )
        assert page.get_by_role("button", name="撤回草稿", exact=True).count() == 1
        assert page.get_by_text(pending_summary, exact=True).count() > 0
    finally:
        for route in held_active_run_routes:
            route.continue_()
        context.close()


@pytest.mark.parametrize(
    ("decision_button_name", "decision_id"),
    [("应用草稿", "apply"), ("撤回草稿", "discard")],
)
def test_agent_draft_decision_revision_is_used_by_next_prompt(
    browser: Browser,
    workspace_servers: tuple[str, str],
    decision_button_name: str,
    decision_id: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()

    try:
        model_response = page.request.post(
            f"{frontend_url}/api/model-configs",
            data={
                "id": "llm-agent-draft-revision",
                "provider": "openai",
                "providerKind": "custom",
                "apiFamily": "openai_compatible_chat",
                "nickname": "Agent draft revision",
                "apiKey": "test-key",
                "model": "test-model",
                "apiUrl": "http://127.0.0.1:9/v1",
                "temperature": None,
                "topP": None,
                "maxTokens": 512,
            },
        )
        assert model_response.ok
        message_id = f"assistant-{decision_id}-next-prompt"
        resume_id, _, _ = _seed_pending_agent_draft(
            page,
            frontend_url,
            message_id=message_id,
            summary="Discard this draft before the next prompt.",
        )
        decision_path = (
            f"/api/agent/resumes/{resume_id}/session/messages/{message_id}/draft"
        )

        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )
        decision_button = page.get_by_role(
            "button",
            name=decision_button_name,
            exact=True,
        )
        decision_button.wait_for(state="visible")
        with page.expect_response(
            lambda response: (
                response.request.method == "PATCH"
                and urlparse(response.url).path == decision_path
            )
        ) as decision_response_info:
            decision_button.click()

        decision_response = decision_response_info.value
        assert decision_response.ok
        decision_session = decision_response.json()["data"]["session"]
        decision_button.wait_for(state="hidden")

        prompt = page.get_by_role(
            "textbox",
            name="你想了解什么？",
            exact=True,
        )
        prompt.fill("继续检查这份简历。")
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

        chat_request = chat_request_info.value
        chat_response = chat_response_info.value
        request_payload = json.loads(chat_request.post_data or "{}")
        assert request_payload["expectedRevision"] == decision_session["revision"]
        assert chat_response.status == 200
    finally:
        context.close()


def test_agent_draft_decision_blocks_a_concurrent_prompt(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()
    held_decision_routes: list[Route] = []
    held_chat_routes: list[Route] = []

    def hold_decision(route: Route) -> None:
        held_decision_routes.append(route)

    def hold_chat(route: Route) -> None:
        held_chat_routes.append(route)

    try:
        model_response = page.request.post(
            f"{frontend_url}/api/model-configs",
            data={
                "id": "llm-agent-draft-decision-gate",
                "provider": "openai",
                "providerKind": "custom",
                "apiFamily": "openai_compatible_chat",
                "nickname": "Agent draft decision gate",
                "apiKey": "test-key",
                "model": "test-model",
                "apiUrl": "http://127.0.0.1:9/v1",
                "temperature": None,
                "topP": None,
                "maxTokens": 512,
            },
        )
        assert model_response.ok
        message_id = "assistant-decision-gates-prompt"
        resume_id, _, _ = _seed_pending_agent_draft(
            page,
            frontend_url,
            message_id=message_id,
            summary="Keep the next prompt behind this decision.",
        )
        decision_path = (
            f"/api/agent/resumes/{resume_id}/session/messages/{message_id}/draft"
        )
        decision_pattern = f"**{decision_path}"
        chat_pattern = "**/api/agent/chat"

        page.route(decision_pattern, hold_decision)
        page.route(chat_pattern, hold_chat)
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )
        prompt = page.get_by_role(
            "textbox",
            name="你想了解什么？",
            exact=True,
        )
        prompt.fill("这条消息必须等草稿决策完成。")
        discard_button = page.get_by_role(
            "button",
            name="撤回草稿",
            exact=True,
        )
        discard_button.click()
        page.wait_for_timeout(100)
        assert held_decision_routes

        prompt.evaluate("element => element.form?.requestSubmit()")
        page.wait_for_timeout(600)

        assert held_chat_routes == []
        assert prompt.is_disabled()

        page.unroute(decision_pattern, hold_decision)
        for route in held_decision_routes:
            route.continue_()
        held_decision_routes.clear()
        discard_button.wait_for(state="hidden")
        expect(prompt).to_be_enabled()
    finally:
        page.unroute("**/api/agent/chat", hold_chat)
        for route in held_chat_routes:
            route.abort()
        for route in held_decision_routes:
            route.continue_()
        context.close()


def test_queued_agent_draft_apply_stops_after_save_owner_unmounts(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()

    try:
        message_id = "assistant-queued-apply-unmount"
        resume_id, detail_before, candidate_resume = _seed_pending_agent_draft(
            page,
            frontend_url,
            message_id=message_id,
            summary="A queued apply must stop when its route owner unmounts.",
        )

        writes: list[ApiRequest] = []

        def delay_save_and_record_writes(route: Route) -> None:
            request = route.request
            api_request = _api_request(request)
            if api_request and request.method in {"PATCH", "POST", "PUT", "DELETE"}:
                writes.append(api_request)
            if (
                request.method == "PUT"
                and urlparse(request.url).path == f"/api/resumes/{resume_id}"
            ):
                time.sleep(0.8)
            route.continue_()

        page.route("**/api/**", delay_save_and_record_writes)
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )

        submitted_resume = json.loads(json.dumps(detail_before["resume"]))
        submitted_resume["title"] = "Save in flight before route unmount"
        page.evaluate(
            """
            async ({ detailBefore, resumeId, submittedResume }) => {
              const ReactModule = await import('/@id/react');
              const ReactDomModule = await import('/@id/react-dom/client');
              const React = ReactModule.default ?? ReactModule;
              const createRoot =
                ReactDomModule.createRoot ?? ReactDomModule.default?.createRoot;
              const { useResumeDetailSave } = await import(
                '/src/components/workspace/use-resume-detail-save.ts'
              );
              const host = document.createElement('div');
              host.hidden = true;
              document.body.append(host);
              if (typeof createRoot !== 'function') {
                throw new Error('React createRoot is unavailable.');
              }
              const root = createRoot(host);
              window.__queuedApplyHarness = { controller: null, root };

              function Harness() {
                const controller = useResumeDetailSave({
                  getSnapshot: () => submittedResume,
                  initialCheckpoint: {
                    savedAt: detailBefore.savedAt,
                    versionId: detailBefore.versionId,
                  },
                  initialResume: detailBefore.resume,
                  isLoading: true,
                  liveFingerprint: 'queued-apply-harness',
                  liveResume: submittedResume,
                  messages: { loadError: 'load error' },
                  onAdoptSavedResume: () => undefined,
                  onHydrateResume: () => undefined,
                  resumeId,
                });
                window.__queuedApplyHarness.controller = controller;
                return null;
              }

              root.render(React.createElement(Harness));
              await new Promise((resolve) => requestAnimationFrame(resolve));
            }
            """,
            {
                "detailBefore": detail_before,
                "resumeId": resume_id,
                "submittedResume": submitted_resume,
            },
        )
        page.evaluate(
            """
            ({ candidateResume, messageId }) => {
              const harness = window.__queuedApplyHarness;
              if (!harness?.controller) {
                throw new Error('The save lifecycle harness is unavailable.');
              }
              const save = harness.controller.save('autosave');
              const decision = harness.controller.resolveAppliedAgentDraft(
                messageId,
                candidateResume,
              );
              window.__queuedApplyPromises = [save, decision];
              window.setTimeout(() => harness.root.unmount(), 50);
            }
            """,
            {"candidateResume": candidate_resume, "messageId": message_id},
        )
        page.wait_for_timeout(1_800)

        draft_patch = (
            "PATCH",
            f"/api/agent/resumes/{resume_id}/session/messages/{message_id}/draft",
        )
        assert draft_patch not in writes, writes
        session_after = page.request.get(
            f"{frontend_url}/api/agent/resumes/{resume_id}/session"
        ).json()["data"]
        assert session_after["messages"][-1]["response"]["draft"]["status"] == (
            "pending"
        )
    finally:
        context.close()


def test_compact_resume_agent_expands_inline_from_right_rail(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )

        header = page.locator("header")
        workspace = page.locator("main.resume-workspace")
        workspace.wait_for(state="visible")

        assert header.get_by_text("ResuMate AI", exact=True).count() == 0
        assert (
            page.locator(
                '[data-slot="sheet-content"], [data-slot="sheet-overlay"]'
            ).count()
            == 0
        )
        assert page.get_by_role("dialog").count() == 0

        trigger = page.get_by_role(
            "button",
            name="展开 Agent 对话栏",
            exact=True,
        )
        trigger.wait_for(state="visible")
        assert trigger.count() == 1
        assert trigger.get_attribute("aria-expanded") == "false"

        trigger_box = trigger.bounding_box()
        viewport_width = page.evaluate("window.innerWidth")
        assert trigger_box is not None
        assert trigger_box["width"] >= 44
        assert 0 <= viewport_width - (trigger_box["x"] + trigger_box["width"]) <= 26

        panel = workspace.locator("section.agent-panel-card")
        assert not panel.is_visible()

        def layout_metrics() -> dict[str, Any]:
            return workspace.evaluate(
                """
                element => {
                  const editor = element.querySelector(".resume-editor-panel");
                  const preview = element.querySelector(".resume-preview-card");
                  const rail = element.querySelector(".agent-seam-rail");
                  const panel = element.querySelector(".agent-panel-card");
                  if (!(editor instanceof HTMLElement) ||
                      !(preview instanceof HTMLElement) ||
                      !(rail instanceof HTMLElement)) {
                    throw new Error("Missing resume workspace panes.");
                  }

                  const editorRect = editor.getBoundingClientRect();
                  const previewRect = preview.getBoundingClientRect();
                  const railRect = rail.getBoundingClientRect();
                  const panelRect = panel?.getBoundingClientRect();
                  return {
                    columns: getComputedStyle(element)
                      .gridTemplateColumns
                      .split(/\\s+/)
                      .map(value => Number.parseFloat(value)),
                    editorPreviewSpan: previewRect.right - editorRect.left,
                    editorWidth: editorRect.width,
                    previewWidth: previewRect.width,
                    preview: {
                      left: previewRect.left,
                      right: previewRect.right,
                    },
                    rail: {
                      left: railRect.left,
                      right: railRect.right,
                    },
                    panel: panelRect ? {
                      left: panelRect.left,
                      right: panelRect.right,
                      width: panelRect.width,
                    } : null,
                  };
                }
                """
            )

        collapsed = layout_metrics()
        assert len(collapsed["columns"]) == 4
        assert collapsed["columns"][3] <= 1
        assert collapsed["editorWidth"] > 0
        assert collapsed["previewWidth"] > 0

        trigger.click()

        collapse_trigger = page.get_by_role(
            "button",
            name="收起 Agent 对话栏",
            exact=True,
        )
        collapse_trigger.wait_for(state="visible")
        assert collapse_trigger.get_attribute("aria-expanded") == "true"

        workspace.evaluate(
            """element => Promise.all(
              element.getAnimations().map(animation => animation.finished)
            )"""
        )

        page.wait_for_function(
            """
            () => {
              const workspace = document.querySelector("main.resume-workspace");
              if (!(workspace instanceof HTMLElement)) return false;
              const columns = getComputedStyle(workspace)
                .gridTemplateColumns
                .split(/\\s+/)
                .map(value => Number.parseFloat(value));
              return columns.length === 4 && columns[3] > 350;
            }
            """
        )

        panel.wait_for(state="visible")

        assert (
            page.locator(
                '[data-slot="sheet-content"], [data-slot="sheet-overlay"]'
            ).count()
            == 0
        )
        assert page.get_by_role("dialog").count() == 0

        expanded = layout_metrics()
        assert len(expanded["columns"]) == 4
        assert expanded["columns"][3] > 350
        assert collapsed["editorPreviewSpan"] - expanded["editorPreviewSpan"] > 300
        assert collapsed["previewWidth"] - expanded["previewWidth"] > 300
        assert expanded["panel"] is not None
        assert expanded["preview"]["right"] <= expanded["rail"]["left"]
        assert expanded["rail"]["right"] <= expanded["panel"]["left"]
        assert abs(expanded["panel"]["width"] - expanded["columns"][3]) <= 1

        collapse_trigger.click()
        trigger.wait_for(state="visible")
        page.set_viewport_size({"width": 1200, "height": 900})

        narrow_layout = workspace.evaluate(
            """
            element => {
              const editor = element.querySelector(".resume-editor-panel");
              const preview = element.querySelector(".resume-preview-card");
              const rail = element.querySelector(".agent-seam-rail");
              if (!(editor instanceof HTMLElement) ||
                  !(preview instanceof HTMLElement) ||
                  !(rail instanceof HTMLElement)) {
                throw new Error("Missing narrow resume workspace panes.");
              }
              const editorRect = editor.getBoundingClientRect();
              const previewRect = preview.getBoundingClientRect();
              const railRect = rail.getBoundingClientRect();
              return {
                editorTop: editorRect.top,
                previewTop: previewRect.top,
                railTop: railRect.top,
              };
            }
            """
        )
        assert abs(narrow_layout["railTop"] - narrow_layout["editorTop"]) <= 1
        assert narrow_layout["previewTop"] > narrow_layout["editorTop"]

        trigger.click()
        panel.wait_for(state="visible")
        narrow_expanded = workspace.evaluate(
            """
            element => {
              const preview = element.querySelector(".resume-preview-card");
              const panel = element.querySelector(".agent-panel-card");
              if (!(preview instanceof HTMLElement) ||
                  !(panel instanceof HTMLElement)) {
                throw new Error("Missing narrow inline Agent panel.");
              }
              const previewRect = preview.getBoundingClientRect();
              const panelRect = panel.getBoundingClientRect();
              return {
                panelBottom: panelRect.bottom,
                panelTop: panelRect.top,
                previewTop: previewRect.top,
              };
            }
            """
        )
        assert narrow_expanded["panelTop"] < narrow_expanded["previewTop"]
        assert narrow_expanded["panelBottom"] <= narrow_expanded["previewTop"]
        assert page.get_by_role("dialog").count() == 0
    finally:
        context.close()


def test_builtin_templates_render_optional_avatars_without_layout_regressions(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 960})
    page = context.new_page()
    resume_ids: list[str] = []
    avatar_data_url = (
        "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
    )

    try:
        for template_id in (
            "minimal",
            "modern",
            "compact",
            "classic",
            "executive",
            "academic",
        ):
            create_response = page.request.post(
                f"{frontend_url}/api/resumes",
                data={
                    "title": f"{template_id} optional avatar regression",
                    "template": template_id,
                },
            )
            assert create_response.ok
            created = create_response.json()["data"]["resume"]
            resume_id = created["id"]
            resume_ids.append(resume_id)

            page.goto(
                f"{frontend_url}/resume/{resume_id}",
                wait_until="networkidle",
            )
            preview_page = page.locator(
                '[data-export-root="resume-page"]:visible'
            ).first
            preview_page.wait_for(state="visible")
            assert preview_page.locator('[data-avatar-frame="true"]').count() == 0
            assert preview_page.locator('[data-avatar-image="true"]').count() == 0

            save_payload = {
                "title": created["title"],
                "resume": {
                    **created["resume"],
                    "basic": {
                        **created["resume"]["basic"],
                        "name": "Example Candidate",
                        "headline": "Software Engineer",
                        "phone": "+86 13800000000",
                        "email": "name@example.com",
                        "location": "Shanghai",
                        "avatar": avatar_data_url,
                    },
                },
                "jobBrief": created["jobBrief"],
                "typography": created["typography"],
                "template": created["template"],
                "templateSettings": created["templateSettings"],
            }
            save_response = page.request.put(
                f"{frontend_url}/api/resumes/{resume_id}",
                data=save_payload,
            )
            assert save_response.ok
            assert save_response.json()["code"] == 0

            page.reload(wait_until="networkidle")
            preview_page = page.locator(
                '[data-export-root="resume-page"]:visible'
            ).first
            avatar_frame = preview_page.locator('[data-avatar-frame="true"]')
            avatar_image = preview_page.locator('img[data-avatar-image="true"]')
            assert avatar_frame.count() == 1
            assert avatar_image.count() == 1
            assert avatar_image.evaluate(
                "(image) => image.complete && image.naturalWidth > 0"
            )

            geometry = preview_page.evaluate(
                """
                (resumePage) => {
                  const avatar = resumePage.querySelector(
                    '[data-avatar-frame="true"]'
                  );
                  if (!(avatar instanceof HTMLElement)) {
                    throw new Error('Avatar frame is unavailable.');
                  }
                  const pageRect = resumePage.getBoundingClientRect();
                  const avatarRect = avatar.getBoundingClientRect();
                  const walker = document.createTreeWalker(
                    resumePage,
                    NodeFilter.SHOW_TEXT
                  );
                  const overlaps = [];
                  let node = walker.nextNode();

                  while (node) {
                    const text = node.textContent?.trim();
                    const parent = node.parentElement;
                    if (text && parent && !parent.closest('[data-avatar-frame]')) {
                      const range = document.createRange();
                      range.selectNodeContents(node);
                      for (const rect of range.getClientRects()) {
                        const intersects =
                          rect.right > avatarRect.left + 1 &&
                          rect.left < avatarRect.right - 1 &&
                          rect.bottom > avatarRect.top + 1 &&
                          rect.top < avatarRect.bottom - 1;
                        if (intersects) overlaps.push(text);
                      }
                    }
                    node = walker.nextNode();
                  }

                  return {
                    avatarInsidePage:
                      avatarRect.left >= pageRect.left - 1 &&
                      avatarRect.top >= pageRect.top - 1 &&
                      avatarRect.right <= pageRect.right + 1 &&
                      avatarRect.bottom <= pageRect.bottom + 1,
                    overlaps,
                  };
                }
                """
            )
            assert geometry["avatarInsidePage"], template_id
            assert geometry["overlaps"] == [], (
                template_id,
                geometry["overlaps"],
            )

            if template_id in {"classic", "academic"}:
                name_alignment = preview_page.locator("header h1").evaluate(
                    "(element) => getComputedStyle(element).textAlign"
                )
                assert name_alignment == "left"

            if template_id == "executive":
                name_box = preview_page.locator("header h1").bounding_box()
                email_box = preview_page.get_by_text(
                    "name@example.com", exact=True
                ).bounding_box()
                assert name_box is not None
                assert email_box is not None
                assert email_box["x"] > name_box["x"] + name_box["width"]
    finally:
        for resume_id in resume_ids:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_empty_optional_avatar_does_not_reserve_resume_or_export_layout_space(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 960})
    page = context.new_page()
    template_id: str | None = None
    resume_id: str | None = None

    def read_header_text_layout() -> list[dict[str, float | str]]:
        preview_page = page.locator('[data-export-root="resume-page"]:visible').first
        preview_page.wait_for(state="visible")
        return preview_page.evaluate(
            """
            (resumePage) => {
              const pageRect = resumePage.getBoundingClientRect();
              const header = resumePage.querySelector('header');
              if (!(header instanceof HTMLElement)) {
                throw new Error('Resume header is unavailable.');
              }

              const result = [];
              const walker = document.createTreeWalker(
                header,
                NodeFilter.SHOW_TEXT
              );
              let node = walker.nextNode();
              while (node) {
                const text = node.textContent?.trim();
                const parent = node.parentElement;
                if (text && parent && !parent.closest('[data-avatar-frame]')) {
                  const range = document.createRange();
                  range.selectNodeContents(node);
                  for (const rect of range.getClientRects()) {
                    result.push({
                      text,
                      left: Math.round((rect.left - pageRect.left) * 10) / 10,
                      top: Math.round((rect.top - pageRect.top) * 10) / 10,
                      width: Math.round(rect.width * 10) / 10,
                      height: Math.round(rect.height * 10) / 10,
                    });
                  }
                }
                node = walker.nextNode();
              }
              return result;
            }
            """
        )

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role("button", name="创建可编辑副本", exact=True).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = urlparse(page.url).path.rsplit("/", maxsplit=1)[-1]

        avatar_position = (
            page.get_by_text("头像位置", exact=True)
            .locator("xpath=../..")
            .get_by_role("combobox")
        )
        avatar_position.click()
        page.get_by_role("option", name="右侧", exact=True).click()

        template_preview = page.locator('[data-export-root="resume-page"]:visible').last
        template_avatar = template_preview.locator('[data-avatar-frame="true"]')
        assert template_avatar.count() == 1
        assert template_avatar.locator('[data-avatar-placeholder="true"]').count() == 1
        assert template_avatar.locator('img[data-avatar-image="true"]').count() == 0

        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/templates/{template_id}"
            )
        ) as save_response_info:
            page.keyboard.press("Control+S")

        save_response = save_response_info.value
        assert save_response.ok
        saved_template_payload = save_response.request.post_data_json

        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "title": "Empty optional avatar layout regression",
                "template": template_id,
            },
        )
        assert create_response.ok
        resume_id = create_response.json()["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        preview_page = page.locator('[data-export-root="resume-page"]:visible').first
        assert preview_page.locator('[data-avatar-frame="true"]').count() == 0
        right_position_layout = read_header_text_layout()
        assert right_position_layout

        page.goto(
            f"{frontend_url}/pdf-export?resumeId={resume_id}&locale=zh",
            wait_until="networkidle",
        )
        page.locator('main[data-pdf-ready="true"]').wait_for(state="visible")
        assert (
            page.locator(
                '[data-export-root="resume-page"]:visible [data-avatar-frame="true"]'
            ).count()
            == 0
        )

        saved_template_payload["template"]["layout"]["avatarPosition"] = "none"
        update_response = page.request.put(
            f"{frontend_url}/api/templates/{template_id}",
            data=saved_template_payload,
        )
        assert update_response.ok

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        hidden_position_layout = read_header_text_layout()
        assert len(right_position_layout) == len(hidden_position_layout)
        for right_rect, hidden_rect in zip(
            right_position_layout, hidden_position_layout, strict=True
        ):
            assert right_rect["text"] == hidden_rect["text"]
            for dimension in ("left", "top", "width", "height"):
                assert (
                    abs(float(right_rect[dimension]) - float(hidden_rect[dimension]))
                    <= 1.0
                ), (right_rect, hidden_rect)
    finally:
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        if template_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


def test_format_popover_focuses_template_without_opening_defaults_tooltip(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        format_button = page.get_by_role("button", name="格式", exact=True)
        format_button.click()

        template_select = page.get_by_role(
            "combobox",
            name="应用模板",
            exact=True,
        )
        page.wait_for_timeout(250)

        assert template_select.evaluate("element => element === document.activeElement")
        assert not page.get_by_role(
            "tooltip",
            name="当前已是模板默认设置",
        ).is_visible()
    finally:
        context.close()


def test_format_reset_restores_current_template_defaults_and_persists(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    resume_id: str | None = None

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "title": "Template defaults reset regression",
                "template": "classic",
                "typography": {"fontFamily": "inter", "fontSize": 20},
                "templateSettings": {
                    "pagePaddingX": 8,
                    "bodyLineHeight": 2.2,
                },
            },
        )
        assert create_response.ok
        create_payload = create_response.json()
        assert create_payload["code"] == 0
        resume_id = create_payload["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role("button", name="格式", exact=True).click()

        reset_button = page.get_by_role(
            "button",
            name="恢复当前模板的默认设置",
            exact=True,
        )
        template_select = page.get_by_role(
            "combobox",
            name="应用模板",
            exact=True,
        )
        font_select = page.get_by_role("combobox", name="字体", exact=True)
        page_margin_input = page.get_by_role(
            "textbox",
            name="页边距",
            exact=True,
        )

        assert not reset_button.is_disabled()
        assert "Inter" in font_select.inner_text()
        assert page_margin_input.input_value() == "8"
        reset_bounds = reset_button.bounding_box()
        template_select_bounds = template_select.bounding_box()
        assert reset_bounds is not None
        assert template_select_bounds is not None
        assert reset_bounds["x"] + reset_bounds["width"] <= template_select_bounds["x"]

        reset_button.click()

        assert reset_button.is_disabled()
        assert "思源宋体" in font_select.inner_text()
        assert page_margin_input.input_value() == "14"
        page.mouse.move(0, 0)
        reset_button.locator("xpath=..").hover()
        tooltip = page.locator('[data-slot="tooltip-content"]')
        tooltip.get_by_text(
            "当前已是模板默认设置",
            exact=True,
        ).wait_for(state="visible")
        tooltip_geometry = tooltip.evaluate(
            """
            (element) => {
              const rect = element.getBoundingClientRect();
              const centerX = rect.left + rect.width / 2;
              const centerY = rect.top + rect.height / 2;
              const topElement = document.elementFromPoint(centerX, centerY);
              return {
                rect: {
                  top: rect.top,
                  right: rect.right,
                  bottom: rect.bottom,
                  left: rect.left,
                  width: rect.width,
                  height: rect.height,
                },
                viewport: {
                  width: window.innerWidth,
                  height: window.innerHeight,
                },
                isTopmost: Boolean(
                  topElement &&
                  (topElement === element || element.contains(topElement))
                ),
              };
            }
            """
        )
        assert tooltip_geometry["rect"]["top"] >= 0, tooltip_geometry
        assert (
            tooltip_geometry["rect"]["right"] <= tooltip_geometry["viewport"]["width"]
        ), tooltip_geometry
        assert tooltip_geometry["isTopmost"], tooltip_geometry

        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
            )
        ) as save_response_info:
            page.get_by_role("button", name="保存状态", exact=True).click()

        save_response = save_response_info.value
        assert save_response.ok
        save_payload = save_response.request.post_data_json
        assert save_payload["typography"] == {
            "fontFamily": "serif",
            "fontSize": 16,
        }
        assert save_payload["templateSettings"] is None

        page.reload(wait_until="networkidle")
        page.get_by_role("button", name="格式", exact=True).click()
        assert page.get_by_role(
            "button",
            name="恢复当前模板的默认设置",
            exact=True,
        ).is_disabled()
        assert (
            "思源宋体"
            in page.get_by_role(
                "combobox",
                name="字体",
                exact=True,
            ).inner_text()
        )
        assert (
            page.get_by_role(
                "textbox",
                name="页边距",
                exact=True,
            ).input_value()
            == "14"
        )
    finally:
        if resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_duplicate_saved_resume_opens_only_from_toast_action(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 2048, "height": 1226})
    page = context.new_page()
    _install_workspace_frame_recorder(page)
    resume_id: str | None = None
    duplicate_id: str | None = None
    duplicate_request_count = 0

    def count_duplicate_request(request: Request) -> None:
        nonlocal duplicate_request_count
        if resume_id and _api_request(request) == (
            "POST",
            f"/api/resumes/{resume_id}/duplicate",
        ):
            duplicate_request_count += 1

    page.on("request", count_duplicate_request)

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"title": "王小明-zh-minimal（1）-frontend-fullstack-resume-2026"},
        )
        assert create_response.ok
        create_payload = create_response.json()
        assert create_payload["code"] == 0
        resume_id = create_payload["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        page.locator('input[name="name"]').fill("Duplicate Regression Source")

        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
            )
        ) as save_response_info:
            page.get_by_role("button", name="保存状态", exact=True).click()
        save_response = save_response_info.value
        assert save_response.ok
        assert save_response.json()["code"] == 0

        preview_page = page.locator(
            ".resume-preview-card article.resume-page",
        )
        preview_page.wait_for(state="visible")
        page.wait_for_timeout(600)
        initial_preview_bounds = preview_page.bounding_box()
        assert initial_preview_bounds is not None

        _start_workspace_frame_recording(page)
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}/duplicate"
            )
        ) as duplicate_response_info:
            page.get_by_role("button", name="创建副本", exact=True).click()

        duplicate_response = duplicate_response_info.value
        assert duplicate_response.ok
        duplicate_payload = duplicate_response.json()
        assert duplicate_payload["code"] == 0
        duplicate_id = duplicate_payload["data"]["resume"]["id"]
        duplicate_title = duplicate_payload["data"]["resume"]["title"]
        page.get_by_text("副本已创建", exact=True).wait_for(state="visible")
        open_copy_action = page.get_by_role(
            "button",
            name="查看副本",
            exact=True,
        )
        open_copy_action.wait_for(state="visible")
        success_toast = page.locator('[data-sonner-toast][data-type="success"]').filter(
            has_text="副本已创建"
        )
        toast_description = success_toast.locator("[data-description]")
        assert toast_description.inner_text() == duplicate_title
        assert (
            toast_description.evaluate(
                "(description) => getComputedStyle(description).whiteSpace"
            )
            == "nowrap"
        )
        assert (
            toast_description.evaluate(
                "(description) => getComputedStyle(description).overflow"
            )
            == "hidden"
        )
        assert (
            toast_description.evaluate(
                "(description) => getComputedStyle(description).textOverflow"
            )
            == "ellipsis"
        )
        assert toast_description.evaluate(
            "(description) => description.scrollWidth > description.clientWidth"
        )
        assert success_toast.locator("[data-icon]").count() == 0
        assert (
            open_copy_action.evaluate(
                "(button) => getComputedStyle(button).backgroundColor"
            )
            == "rgba(0, 0, 0, 0)"
        )
        assert (
            open_copy_action.evaluate(
                "(button) => getComputedStyle(button).borderTopWidth"
            )
            == "1px"
        )
        assert (
            open_copy_action.evaluate(
                "(button) => getComputedStyle(button).borderTopStyle"
            )
            == "solid"
        )
        assert open_copy_action.locator("svg").count() == 0
        close_button = success_toast.locator("[data-close-button]")
        close_shadow_before_hover = close_button.evaluate(
            "(button) => getComputedStyle(button).boxShadow"
        )
        close_button.hover()
        assert (
            close_button.evaluate("(button) => getComputedStyle(button).boxShadow")
            == close_shadow_before_hover
        )
        action_bounds = open_copy_action.bounding_box()
        close_bounds = close_button.bounding_box()
        assert action_bounds is not None
        assert close_bounds is not None
        assert action_bounds["x"] + action_bounds["width"] <= close_bounds["x"]
        assert page.url == f"{frontend_url}/resume/{resume_id}"

        source_preview_bounds = preview_page.bounding_box()
        assert source_preview_bounds is not None
        assert source_preview_bounds["width"] == pytest.approx(
            initial_preview_bounds["width"],
            abs=1,
        )

        open_copy_action.click()
        page.wait_for_url(f"{frontend_url}/resume/{duplicate_id}", timeout=5_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        frames = _stop_workspace_frame_recording(page)

        final_preview_page = page.locator(
            ".resume-preview-card article.resume-page",
        )
        final_preview_page.wait_for(state="visible")
        final_preview_bounds = final_preview_page.bounding_box()
        assert final_preview_bounds is not None
        toolbar_title = page.locator("#main-content > header h1")
        assert toolbar_title.get_attribute("title") == duplicate_title
        assert toolbar_title.inner_text().endswith(
            duplicate_title.rsplit(" - ", maxsplit=1)[-1]
        )
        assert toolbar_title.evaluate(
            "(element) => element.scrollWidth <= element.clientWidth"
        )
        routed_frames = [
            frame for frame in frames if frame["path"] == f"/resume/{duplicate_id}"
        ]

        assert duplicate_request_count == 1
        assert page.get_by_role("dialog").count() == 0
        assert len(routed_frames) >= 2
        # Opening the copy revalidates its detail route. Once the target mounts,
        # every rendered preview frame must keep its A4 width.
        assert all(bool(frame["hasResumeDetail"]) for frame in routed_frames[-2:])
        assert all(
            bool(frame["resumePreviewFits"])
            for frame in routed_frames
            if frame["hasResumeDetail"]
        )
        assert all(
            float(frame["resumePreviewWidth"])
            == pytest.approx(initial_preview_bounds["width"], abs=1)
            for frame in routed_frames
            if frame["resumePreviewWidth"] is not None
        )
        assert final_preview_bounds["width"] == pytest.approx(
            initial_preview_bounds["width"],
            abs=1,
        )
    finally:
        for cleanup_resume_id in (duplicate_id, resume_id):
            if not cleanup_resume_id:
                continue
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{cleanup_resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{cleanup_resume_id}")
        context.close()


def test_duplicate_resume_stops_if_content_changes_during_save(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 2048, "height": 1226})
    page = context.new_page()
    resume_id: str | None = None
    duplicate_request_count = 0
    held_saves: list[Route] = []

    def count_duplicate_request(request: Request) -> None:
        nonlocal duplicate_request_count
        if resume_id and _api_request(request) == (
            "POST",
            f"/api/resumes/{resume_id}/duplicate",
        ):
            duplicate_request_count += 1

    page.on("request", count_duplicate_request)

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={},
        )
        assert create_response.ok
        create_payload = create_response.json()
        assert create_payload["code"] == 0
        resume_id = create_payload["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()

        def hold_checkpoint_save(route: Route) -> None:
            if route.request.method != "PUT":
                route.continue_()
                return

            held_saves.append(route)

        page.route(f"**/api/resumes/{resume_id}*", hold_checkpoint_save)

        name_input = page.locator('input[name="name"]')
        name_input.fill("Snapshot captured for copy")
        with page.expect_request(
            lambda request: (
                request.method == "PUT"
                and urlparse(request.url).path == f"/api/resumes/{resume_id}"
            )
        ):
            page.get_by_role("button", name="创建副本", exact=True).click()

        assert len(held_saves) == 1
        held_request = held_saves[0].request
        assert parse_qs(urlparse(held_request.url).query)["saveMode"] == ["checkpoint"]
        submitted_payload = held_request.post_data_json
        assert submitted_payload["resume"]["basic"]["name"] == (
            "Snapshot captured for copy"
        )

        headline_input = page.locator('input[name="headline"]')
        headline_input.fill("Newer edit must stay in the editor")
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
            )
        ) as save_response_info:
            held_saves[0].continue_()
        save_response = save_response_info.value
        assert save_response.ok
        assert save_response.json()["code"] == 0

        page.get_by_text(
            "保存期间内容发生变化，请再次创建副本",
            exact=True,
        ).wait_for(state="visible")

        assert duplicate_request_count == 0
        assert page.url == f"{frontend_url}/resume/{resume_id}"
        assert page.get_by_role("dialog").count() == 0
        assert headline_input.input_value() == "Newer edit must stay in the editor"
        page.get_by_role("button", name="保存状态", exact=True).hover()
        page.get_by_text("有未保存更改", exact=True).wait_for(state="visible")
    finally:
        if resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_workspace_load_error_can_retry_same_route(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1280, "height": 800})
    page = context.new_page()
    request_count = 0

    def fail_first_load(route: Route) -> None:
        nonlocal request_count
        request_count += 1
        if request_count > 1:
            route.continue_()
            return

        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "code": 50000,
                    "message": "INTERNAL_SERVER_ERROR",
                    "data": None,
                }
            ),
        )

    page.route("**/api/workspace/pages/resumes*", fail_first_load)

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        retry_button = page.get_by_role("button", name="重试", exact=True)
        retry_button.wait_for(state="visible")
        assert request_count == 1

        retry_button.click()
        page.wait_for_load_state("networkidle")

        assert request_count == 2
        assert retry_button.count() == 0
        page.get_by_role("button", name="新建", exact=True).wait_for(state="visible")
    finally:
        context.close()


def test_resume_navigation_stays_on_gallery_when_target_preparation_fails(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1280, "height": 800})
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        context.route("**/api/**", lambda route: route.abort())

        page.locator(f'a[href="/resume/{resume_id}"]').click()
        error_toasts = page.locator(
            '[data-sonner-toast][data-type="error"]:not([data-removed="true"])'
        )
        error_toasts.first.wait_for(state="visible")
        page.wait_for_timeout(250)

        assert page.url == f"{frontend_url}/resume"
        assert error_toasts.count() == 1
        assert page.get_by_role("button", name="重试", exact=True).count() == 0
        assert page.get_by_role("dialog").count() == 0
    finally:
        context.close()


def test_template_navigation_stays_on_gallery_when_target_preparation_fails(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1280, "height": 800})
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/templates", wait_until="networkidle")
        page.route("**/api/workspace/pages/templates", lambda route: route.abort())

        page.locator('a[href="/template/minimal"]').click()
        error_toasts = page.locator(
            '[data-sonner-toast][data-type="error"]:not([data-removed="true"])'
        )
        error_toasts.first.wait_for(state="visible")
        page.wait_for_timeout(250)

        assert page.url == f"{frontend_url}/templates"
        assert error_toasts.count() == 1
        assert page.get_by_role("button", name="重试", exact=True).count() == 0
    finally:
        context.close()


def test_lateral_navigation_stays_on_current_page_when_preparation_fails(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1280, "height": 800})
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.route("**/api/workspace/pages/models", lambda route: route.abort())

        page.locator('a[href="/models"]').first.click()
        error_toasts = page.locator(
            '[data-sonner-toast][data-type="error"]:not([data-removed="true"])'
        )
        error_toasts.first.wait_for(state="visible")
        page.wait_for_timeout(250)

        assert page.url == f"{frontend_url}/resume"
        assert error_toasts.count() == 1
        assert page.get_by_role("button", name="重试", exact=True).count() == 0
    finally:
        context.close()


def test_latest_workspace_navigation_wins_across_card_and_sidebar_owners(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1280, "height": 800})
    page = context.new_page()

    def delay_models(route: Route) -> None:
        time.sleep(0.6)
        route.continue_()

    page.route("**/api/workspace/pages/models", delay_models)

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.evaluate(
            """
            (resumeId) => {
              const resume = document.querySelector(
                `a[href="/resume/${resumeId}"]`,
              );
              const models = document.querySelector('a[href="/models"]');
              if (!(resume instanceof HTMLAnchorElement) ||
                  !(models instanceof HTMLAnchorElement)) {
                throw new Error("Workspace navigation targets are unavailable.");
              }
              resume.click();
              models.click();
            }
            """,
            resume_id,
        )

        page.wait_for_url(f"{frontend_url}/models", timeout=5_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(300)

        assert page.url == f"{frontend_url}/models"
        assert page.locator(f'a[href="/resume/{resume_id}"]').count() == 0
    finally:
        context.close()


def test_active_sidebar_click_cancels_pending_card_navigation(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1280, "height": 800})
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.evaluate(
            """
            (resumeId) => {
              const resume = document.querySelector(
                `a[href="/resume/${resumeId}"]`,
              );
              const activeResume = document.querySelector('a[href="/resume"]');
              if (!(resume instanceof HTMLAnchorElement) ||
                  !(activeResume instanceof HTMLAnchorElement)) {
                throw new Error("Workspace navigation targets are unavailable.");
              }
              resume.click();
              activeResume.click();
            }
            """,
            resume_id,
        )
        page.wait_for_timeout(1_000)

        assert page.url == f"{frontend_url}/resume"
        assert page.locator('input[name="resume-search"]').is_visible()
    finally:
        context.close()


def test_delayed_resume_create_cannot_hijack_newer_workspace_route(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1280, "height": 800})
    page = context.new_page()
    created_resume_id: str | None = None

    def delay_create(route: Route) -> None:
        if route.request.method != "POST":
            route.continue_()
            return
        response = route.fetch()
        time.sleep(0.8)
        route.fulfill(response=response)

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.route("**/api/resumes", delay_create)

        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlparse(response.url).path == "/api/resumes"
            )
        ) as create_response_info:
            page.evaluate(
                """
                () => {
                  const create = [...document.querySelectorAll("button")].find(
                    (button) => button.textContent?.trim() === "新建",
                  );
                  const models = document.querySelector('a[href="/models"]');
                  if (!(create instanceof HTMLButtonElement) ||
                      !(models instanceof HTMLAnchorElement)) {
                    throw new Error("Workspace mutation targets are unavailable.");
                  }
                  create.click();
                  models.click();
                }
                """
            )

        create_response = create_response_info.value
        assert create_response.ok
        created_resume_id = create_response.json()["data"]["resume"]["id"]
        page.wait_for_url(f"{frontend_url}/models", timeout=5_000)
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(800)

        assert page.url == f"{frontend_url}/models"
    finally:
        if created_resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{created_resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{created_resume_id}")
        context.close()


def test_resume_detail_retry_owns_a_single_error_notification(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1280, "height": 800})
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.route("**/api/workspace/pages/resume-editor", lambda route: route.abort())
        page.route(f"**/api/resumes/{resume_id}*", lambda route: route.abort())

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="domcontentloaded")
        retry_button = page.get_by_role("button", name="重试", exact=True)
        retry_button.wait_for(state="visible")
        error_toasts = page.locator(
            '[data-sonner-toast][data-type="error"]:not([data-removed="true"])'
        )
        error_toasts.first.wait_for(state="visible")

        retry_button.click()
        page.wait_for_timeout(500)

        assert page.url == f"{frontend_url}/resume/{resume_id}"
        assert retry_button.is_visible()
        assert error_toasts.count() == 1
    finally:
        context.close()


def test_agent_hydration_failure_stays_local_without_error_notification(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    agent_requests: list[ApiRequest] = []

    def fail_agent_read(route: Route) -> None:
        request = _api_request(route.request)
        assert request is not None
        agent_requests.append(request)
        route.abort()

    page.route(
        f"**/api/agent/resumes/{resume_id}/session",
        fail_agent_read,
    )
    page.route(
        f"**/api/agent/resumes/{resume_id}/run",
        fail_agent_read,
    )

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="domcontentloaded")
        page.get_by_text("对话加载失败", exact=True).wait_for(state="visible")
        page.wait_for_timeout(250)

        request_counts = Counter(agent_requests)
        session_request = ("GET", f"/api/agent/resumes/{resume_id}/session")
        active_run_request = ("GET", f"/api/agent/resumes/{resume_id}/run")
        # Strict Mode may start and cancel a preflight owner. The notification
        # contract only requires that both hydration reads actually failed.
        assert request_counts[session_request] >= 1
        assert request_counts[active_run_request] >= 1
        assert (
            page.locator(
                '[data-sonner-toast][data-type="error"]:not([data-removed="true"])'
            ).count()
            == 0
        )
    finally:
        context.close()


def test_resume_navigation_keeps_cached_views_mounted_and_preview_fits(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    _install_workspace_frame_recorder(page)

    def continue_after_delay(route: Route) -> None:
        time.sleep(0.2)
        route.continue_()

    page.route("**/api/workspace/pages/resume-editor", continue_after_delay)
    page.route("**/api/workspace/pages/resumes", continue_after_delay)

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        resume_link = page.locator(f'a[href="/resume/{resume_id}"]')

        assert resume_link.count() == 1
        _start_workspace_frame_recording(page)
        resume_link.click()
        page.wait_for_url(f"{frontend_url}/resume/{resume_id}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        detail_frames = _stop_workspace_frame_recording(page)

        preview_frame = page.locator(".resume-preview-scale-frame")
        preview_page = page.locator(
            ".resume-preview-card article.resume-page",
        )
        agent_dock = page.locator('.agent-panel-dock[aria-hidden="false"]')

        assert preview_frame.count() == 1
        assert preview_page.count() == 1
        assert agent_dock.count() == 1
        frame_box = preview_frame.bounding_box()
        page_box = preview_page.bounding_box()
        agent_box = agent_dock.bounding_box()

        assert frame_box is not None
        assert page_box is not None
        assert agent_box is not None
        assert agent_box["width"] > 0
        routed_frames = [
            frame for frame in detail_frames if frame["path"] == f"/resume/{resume_id}"
        ]
        assert len(routed_frames) >= 2
        _assert_visible_once_mounted(routed_frames, "hasResumeDetail")
        assert all(
            bool(frame["resumePreviewFits"])
            for frame in routed_frames
            if frame["hasResumeDetail"]
        )
        assert page_box["x"] >= frame_box["x"] - 1
        assert page_box["x"] + page_box["width"] <= (
            frame_box["x"] + frame_box["width"] + 1
        )

        back_button = page.get_by_role(
            "button",
            name="返回简历列表",
            exact=True,
        )
        assert back_button.count() == 1
        _start_workspace_frame_recording(page)
        back_button.click()
        page.wait_for_url(f"{frontend_url}/resume")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        gallery_frames = _stop_workspace_frame_recording(page)
        routed_gallery_frames = [
            frame for frame in gallery_frames if frame["path"] == "/resume"
        ]
        assert len(routed_gallery_frames) >= 2
        _assert_visible_once_mounted(routed_gallery_frames, "hasResumeGallery")
    finally:
        context.close()


@pytest.mark.parametrize(
    "edit_before_checkpoint",
    [False, True],
    ids=["same-content-checkpoint", "edited-checkpoint"],
)
def test_resume_preparation_establishes_checkpoint_before_editor_mount(
    browser: Browser,
    workspace_servers: tuple[str, str],
    edit_before_checkpoint: bool,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    resume_id: str | None = None
    preparation_requests = 0
    checkpoint_responses = 0
    checkpoint_saved_at: str | None = None

    def capture_checkpoint(response) -> None:
        nonlocal checkpoint_responses, checkpoint_saved_at
        if (
            resume_id
            and response.request.method == "PUT"
            and urlparse(response.url).path == f"/api/resumes/{resume_id}"
        ):
            checkpoint_responses += 1
            checkpoint_saved_at = response.json()["data"]["savedAt"]

    def capture_preparation(request: Request) -> None:
        nonlocal preparation_requests
        if (
            resume_id
            and request.method == "GET"
            and urlparse(request.url).path == f"/api/resumes/{resume_id}"
        ):
            preparation_requests += 1

    page.on("response", capture_checkpoint)
    page.on("request", capture_preparation)

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"title": "Prepared checkpoint regression"},
        )
        assert create_response.ok
        resume_id = create_response.json()["data"]["resume"]["id"]
        # Keep the original and new checkpoint labels distinct to make the
        # version-list assertion deterministic at second precision.
        page.wait_for_timeout(1_100)

        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.evaluate(
            f"""
            () => {{
              window.__resumePreparationCheckpointSent = false;
              window.__resumePreparationReleased = false;
              const originalFetch = window.fetch.bind(window);
              window.fetch = async (input, init) => {{
                const request = new Request(input, init);
                const response = await originalFetch(input, init);
                if (
                  request.method === "GET" &&
                  new URL(request.url).pathname ===
                    "/api/resumes/{resume_id}"
                ) {{
                  // Hold the prepared response after transport completes. The
                  // click must keep the gallery URL until this promise settles.
                  await new Promise((resolve) => window.setTimeout(resolve, 2_000));
                  window.__resumePreparationReleased = true;
                }}
                return response;
              }};
              const editBeforeCheckpoint = {str(edit_before_checkpoint).lower()};
              const deadline = performance.now() + 8_000;
              let openedBasicInfo = false;
              const saveWhenReady = () => {{
                const input = document.querySelector('input[name="name"]');
                const saveButton = document.querySelector(
                  'button[aria-label="保存状态"]',
                );
                const valueSetter = Object.getOwnPropertyDescriptor(
                  HTMLInputElement.prototype,
                  "value",
                )?.set;
                if (
                  window.location.pathname === "/resume/{resume_id}" &&
                  saveButton instanceof HTMLButtonElement &&
                  (!editBeforeCheckpoint ||
                    (input instanceof HTMLInputElement && valueSetter))
                ) {{
                  if (
                    editBeforeCheckpoint &&
                    input instanceof HTMLInputElement &&
                    valueSetter
                  ) {{
                    valueSetter.call(
                      input,
                      "Saved After Preparation Returned",
                    );
                    input.dispatchEvent(
                      new Event("input", {{ bubbles: true }}),
                    );
                  }}
                  window.setTimeout(() => {{
                    saveButton.click();
                    window.__resumePreparationCheckpointSent = true;
                  }}, 100);
                  return;
                }}
                if (
                  window.location.pathname === "/resume/{resume_id}" &&
                  editBeforeCheckpoint &&
                  !openedBasicInfo
                ) {{
                  const trigger = [...document.querySelectorAll("button")]
                    .find((candidate) =>
                      candidate.getAttribute("aria-label") ===
                      "基本信息: 展开或收起模块",
                    );
                  if (trigger instanceof HTMLButtonElement) {{
                    openedBasicInfo = true;
                    trigger.click();
                  }}
                }}
                if (performance.now() < deadline) {{
                  requestAnimationFrame(saveWhenReady);
                }}
              }};
              requestAnimationFrame(saveWhenReady);
            }}
            """
        )

        page.locator(f'a[href="/resume/{resume_id}"]').click()
        page.wait_for_timeout(250)
        assert page.url == f"{frontend_url}/resume"
        page.wait_for_url(f"{frontend_url}/resume/{resume_id}")
        deadline = time.monotonic() + 8
        while (
            preparation_requests < 1 or checkpoint_responses < 1
        ) and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        page.wait_for_timeout(150)

        assert preparation_requests == 1
        assert checkpoint_responses == 1
        assert checkpoint_saved_at is not None
        assert page.evaluate("window.__resumePreparationCheckpointSent") is True
        page.wait_for_function("window.__resumePreparationReleased === true")
        page.wait_for_timeout(100)
        if edit_before_checkpoint:
            assert page.locator('input[name="name"]').input_value() == (
                "Saved After Preparation Returned"
            )
        page.get_by_role("button", name="保存状态", exact=True).hover()
        page.get_by_text("有未保存更改", exact=True).wait_for(state="detached")
        checkpoint_label = page.evaluate(
            """
            (savedAt) => new Intl.DateTimeFormat("zh-CN", {
              month: "2-digit",
              day: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            }).format(new Date(savedAt))
            """,
            checkpoint_saved_at,
        )
        page.get_by_text(checkpoint_label, exact=False).first.wait_for(state="visible")
        persisted_response = page.request.get(f"{frontend_url}/api/resumes/{resume_id}")
        assert persisted_response.ok
        if edit_before_checkpoint:
            assert (
                persisted_response.json()["data"]["resume"]["resume"]["basic"]["name"]
                == "Saved After Preparation Returned"
            )
    finally:
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_template_navigation_keeps_cached_views_mounted(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    _install_workspace_frame_recorder(page)

    def continue_after_delay(route: Route) -> None:
        time.sleep(0.2)
        route.continue_()

    page.route("**/api/workspace/pages/templates", continue_after_delay)

    try:
        page.goto(f"{frontend_url}/templates", wait_until="networkidle")
        template_link = page.locator('a[href="/template/minimal"]')

        assert template_link.count() == 1
        _start_workspace_frame_recording(page)
        template_link.click()
        page.wait_for_url(f"{frontend_url}/template/minimal")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        detail_frames = _stop_workspace_frame_recording(page)
        routed_detail_frames = [
            frame for frame in detail_frames if frame["path"] == "/template/minimal"
        ]
        assert len(routed_detail_frames) >= 2
        _assert_visible_once_mounted(routed_detail_frames, "hasTemplateDetail")

        back_button = page.get_by_role(
            "button",
            name="返回模板列表",
            exact=True,
        )
        assert back_button.count() == 1
        _start_workspace_frame_recording(page)
        back_button.click()
        page.wait_for_url(f"{frontend_url}/templates")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        gallery_frames = _stop_workspace_frame_recording(page)
        routed_gallery_frames = [
            frame for frame in gallery_frames if frame["path"] == "/templates"
        ]
        assert len(routed_gallery_frames) >= 2
        _assert_visible_once_mounted(
            routed_gallery_frames,
            "hasTemplateGallery",
        )
    finally:
        context.close()


def test_template_preparation_finishes_before_detail_becomes_editable(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    preparation_requests = 0

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="创建可编辑副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = page.url.rsplit("/", maxsplit=1)[-1]
        page.get_by_role(
            "button",
            name="返回模板列表",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/templates")
        page.wait_for_load_state("networkidle")

        # Expire the shared template-catalog cache so the click must perform a
        # fresh target preparation before it can commit the detail URL.
        page.wait_for_timeout(3_200)

        def delay_preparation(route: Route) -> None:
            nonlocal preparation_requests
            preparation_requests += 1
            time.sleep(1)
            route.continue_()

        page.route("**/api/workspace/pages/templates", delay_preparation)
        page.evaluate(
            f"""
            () => {{
              window.__templatePreparationDraftEdited = false;
              const deadline = performance.now() + 5_000;
              let openedTemplateInfo = false;
              const editWhenReady = () => {{
                const labels = [...document.querySelectorAll("label")];
                const label = labels.find((candidate) =>
                  candidate.textContent?.includes("模板名称"),
                );
                const input = label?.querySelector("input");
                const valueSetter = Object.getOwnPropertyDescriptor(
                  HTMLInputElement.prototype,
                  "value",
                )?.set;
                if (
                  window.location.pathname === "/template/{template_id}" &&
                  input instanceof HTMLInputElement &&
                  valueSetter
                ) {{
                  valueSetter.call(input, "Local Edit After Preparation");
                  input.dispatchEvent(new Event("input", {{ bubbles: true }}));
                  window.__templatePreparationDraftEdited = true;
                  return;
                }}
                if (
                  window.location.pathname === "/template/{template_id}" &&
                  !openedTemplateInfo
                ) {{
                  const trigger = [
                    ...document.querySelectorAll(
                      '[data-slot="collapsible-trigger"]',
                    ),
                  ].find((candidate) =>
                    candidate.textContent?.includes("模板信息"),
                  );
                  if (trigger instanceof HTMLElement) {{
                    openedTemplateInfo = true;
                    trigger.click();
                  }}
                }}
                if (performance.now() < deadline) {{
                  requestAnimationFrame(editWhenReady);
                }}
              }};
              requestAnimationFrame(editWhenReady);
            }}
            """
        )

        page.locator(f'a[href="/template/{template_id}"]').click()
        page.wait_for_url(f"{frontend_url}/template/{template_id}")
        deadline = time.monotonic() + 5
        while preparation_requests < 1 and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        page.wait_for_timeout(100)

        assert preparation_requests == 1
        assert page.evaluate("window.__templatePreparationDraftEdited") is True
        assert page.get_by_label("模板名称", exact=True).input_value() == (
            "Local Edit After Preparation"
        )
    finally:
        context.close()


@pytest.mark.parametrize(
    ("target_route", "api_path", "frame_key"),
    [
        (
            "/templates",
            "/api/workspace/pages/templates",
            "hasTemplateGallery",
        ),
        ("/trash", "/api/workspace/pages/trash", "hasTrashContent"),
        ("/models", "/api/workspace/pages/models", "hasModelsContent"),
        (
            "/settings",
            "/api/workspace/pages/settings",
            "hasSettingsContent",
        ),
    ],
)
def test_lateral_navigation_keeps_target_content_mounted(
    browser: Browser,
    workspace_servers: tuple[str, str],
    target_route: str,
    api_path: str,
    frame_key: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    _install_workspace_frame_recorder(page)

    def continue_after_delay(route: Route) -> None:
        time.sleep(0.2)
        route.continue_()

    page.route(f"**{api_path}", continue_after_delay)

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        target_link = page.locator(f'a[href="{target_route}"]')

        assert target_link.count() == 1
        target_link.hover()
        page.wait_for_timeout(200)
        _start_workspace_frame_recording(page)
        target_link.click()
        page.wait_for_url(f"{frontend_url}{target_route}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        frames = _stop_workspace_frame_recording(page)
        routed_frames = [frame for frame in frames if frame["path"] == target_route]

        assert len(routed_frames) >= 2
        _assert_visible_once_mounted(routed_frames, frame_key)
        handoff_states = [
            bool(frame["hasResumeGallery"]) or bool(frame[frame_key])
            for frame in routed_frames
        ]
        spinner_states = [bool(frame["hasRouteSpinner"]) for frame in routed_frames]
        sidebar_states = [bool(frame["hasSidebar"]) for frame in routed_frames]

        assert all(handoff_states), _boolean_runs(handoff_states)
        assert not any(spinner_states), _boolean_runs(spinner_states)
        assert all(sidebar_states), _boolean_runs(sidebar_states)
    finally:
        context.close()


def test_lateral_history_uses_latest_view_snapshot_without_blank_frame(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    _install_workspace_frame_recorder(page)

    def continue_after_delay(route: Route) -> None:
        time.sleep(0.2)
        route.continue_()

    page.route("**/api/workspace/pages/resumes", continue_after_delay)
    page.route("**/api/workspace/pages/settings", continue_after_delay)

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.locator('a[href="/settings"]').click()
        page.wait_for_url(f"{frontend_url}/settings")
        page.wait_for_load_state("networkidle")
        # Expire requestApi's short GET cache so the first POP frame is proven
        # to come from route memory rather than an already-resolved request.
        page.wait_for_timeout(3200)

        _start_workspace_frame_recording(page)
        page.go_back(wait_until="commit")
        page.wait_for_url(f"{frontend_url}/resume")
        page.wait_for_timeout(600)
        back_frames = _stop_workspace_frame_recording(page)
        routed_back_frames = [
            frame for frame in back_frames if frame["path"] == "/resume"
        ]

        assert len(routed_back_frames) >= 2
        _assert_visible_once_mounted(routed_back_frames, "hasResumeGallery")
        assert all(
            bool(frame["hasSettingsContent"]) or bool(frame["hasResumeGallery"])
            for frame in routed_back_frames
        )
        assert not any(bool(frame["hasRouteSpinner"]) for frame in routed_back_frames)
        assert all(bool(frame["hasSidebar"]) for frame in routed_back_frames)

        _start_workspace_frame_recording(page)
        page.go_forward(wait_until="commit")
        page.wait_for_url(f"{frontend_url}/settings")
        page.wait_for_timeout(600)
        forward_frames = _stop_workspace_frame_recording(page)
        routed_forward_frames = [
            frame for frame in forward_frames if frame["path"] == "/settings"
        ]

        assert len(routed_forward_frames) >= 2
        _assert_visible_once_mounted(
            routed_forward_frames,
            "hasSettingsContent",
        )
        assert all(
            bool(frame["hasResumeGallery"]) or bool(frame["hasSettingsContent"])
            for frame in routed_forward_frames
        )
        assert not any(
            bool(frame["hasRouteSpinner"]) for frame in routed_forward_frames
        )
        assert all(bool(frame["hasSidebar"]) for frame in routed_forward_frames)
    finally:
        context.close()


def test_pdf_export_route_request_allowlist(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    expected_paths = [
        AUTH_SETUP_STATUS_REQUEST,
        ("GET", "/api/workspace/pages/templates"),
        ("GET", f"/api/resumes/{resume_id}"),
    ]
    actual_paths = _observe_api_requests(
        browser,
        f"{frontend_url}/pdf-export?resumeId={resume_id}&locale=en",
    )

    assert Counter(actual_paths) == Counter(expected_paths)


def test_resume_autosave_persists_edit_made_during_active_save(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    save_payloads: list[dict[str, object]] = []
    save_urls: list[str] = []

    def delay_first_save(route: Route) -> None:
        request = route.request
        if request.method != "PUT":
            route.continue_()
            return

        payload = request.post_data_json
        assert isinstance(payload, dict)
        save_payloads.append(payload)
        save_urls.append(request.url)
        if len(save_payloads) == 1:
            time.sleep(1)
        route.continue_()

    page.route(f"**/api/resumes/{resume_id}*", delay_first_save)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        name_input = page.locator('input[name="name"]')
        name_input.fill("First Save Payload")
        page.wait_for_timeout(50)
        page.evaluate(
            """
            () => {
              const input = document.querySelector('input[name="name"]');
              if (!(input instanceof HTMLInputElement)) {
                throw new Error("Name input is unavailable.");
              }
              const valueSetter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype,
                "value",
              )?.set;
              if (!valueSetter) {
                throw new Error("Native input value setter is unavailable.");
              }
              window.setTimeout(() => {
                valueSetter.call(input, "Latest Edit During Save");
                input.dispatchEvent(new Event("input", { bubbles: true }));

                const editTitleButton = document.querySelector(
                  'button[aria-label="修改简历标题"]',
                );
                if (!(editTitleButton instanceof HTMLButtonElement)) {
                  throw new Error("Edit title button is unavailable.");
                }
                editTitleButton.click();
                window.setTimeout(() => {
                  const dialog = document.querySelector('[role="dialog"]');
                  const titleInput = dialog?.querySelector("input");
                  const saveButton = [...(dialog?.querySelectorAll("button") ?? [])]
                    .find((button) => button.textContent?.trim() === "保存");
                  if (
                    !(titleInput instanceof HTMLInputElement) ||
                    !(saveButton instanceof HTMLButtonElement)
                  ) {
                    throw new Error("Resume title dialog is unavailable.");
                  }
                  valueSetter.call(titleInput, "Latest Title During");
                  titleInput.dispatchEvent(new Event("input", { bubbles: true }));
                  saveButton.click();
                }, 0);
              }, 200);
              window.setTimeout(() => {
                const backButton = [...document.querySelectorAll("button")].find(
                  (button) => button.textContent?.includes("返回简历列表"),
                );
                if (!(backButton instanceof HTMLButtonElement)) {
                  throw new Error("Back button is unavailable.");
                }
                backButton.click();
              }, 500);
            }
            """
        )
        page.keyboard.press("Control+S")

        deadline = time.monotonic() + 8
        while len(save_payloads) < 2 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert len(save_payloads) >= 2, save_payloads
        assert "saveMode=autosave" in save_urls[1]
        autosaved_payload = save_payloads[1]
        assert autosaved_payload["title"] == "Latest Title During"
        assert autosaved_payload["resume"]["basic"]["name"] == (
            "Latest Edit During Save"
        )

        save_and_leave = page.get_by_role(
            "button",
            name="保存并离开",
            exact=True,
        )
        assert save_and_leave.count() == 1
        save_and_leave.click()
        page.wait_for_url(f"{frontend_url}/resume")

        deadline = time.monotonic() + 5
        while len(save_payloads) < 3 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert len(save_payloads) >= 3, save_payloads
        assert "saveMode=checkpoint" in save_urls[-1]
        assert save_payloads[-1]["title"] == "Latest Title During"
        assert save_payloads[-1]["resume"]["basic"]["name"] == (
            "Latest Edit During Save"
        )

        page.wait_for_load_state("networkidle")
        persisted_response = page.request.get(f"{frontend_url}/api/resumes/{resume_id}")
        persisted = persisted_response.json()["data"]["resume"]
        assert persisted["title"] == "Latest Title During"
        assert persisted["resume"]["basic"]["name"] == "Latest Edit During Save"
    finally:
        context.close()


def test_resume_title_preserves_draft_and_normalizes_on_commit(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    save_payloads: list[dict[str, object]] = []

    def capture_save(route: Route) -> None:
        if route.request.method == "PUT":
            payload = route.request.post_data_json
            assert isinstance(payload, dict)
            save_payloads.append(payload)
        route.continue_()

    page.route(f"**/api/resumes/{resume_id}*", capture_save)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        persisted_response = page.request.get(f"{frontend_url}/api/resumes/{resume_id}")
        fallback_title = persisted_response.json()["data"]["resume"]["resume"]["basic"][
            "name"
        ]

        page.get_by_role("button", name="修改简历标题", exact=True).click()
        title_input = page.locator("#resume-title-input")
        overlong_draft = "  😀" + "a" * 60
        expected_truncated_draft = "  😀" + "a" * 47
        title_input.fill(overlong_draft)

        assert title_input.input_value() == expected_truncated_draft
        assert page.get_by_text("50/50", exact=True).count() == 1

        title_input.fill("  Trim Me  ")
        assert title_input.input_value() == "  Trim Me  "
        page.get_by_role("button", name="保存", exact=True).click()
        page.keyboard.press("Control+S")

        deadline = time.monotonic() + 5
        while len(save_payloads) < 1 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert save_payloads[-1]["title"] == "Trim Me"
        page.wait_for_load_state("networkidle")

        page.get_by_role("button", name="修改简历标题", exact=True).click()
        title_input.fill("   ")
        assert title_input.input_value() == "   "
        page.get_by_role("button", name="保存", exact=True).click()
        page.keyboard.press("Control+S")

        deadline = time.monotonic() + 5
        while len(save_payloads) < 2 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert save_payloads[-1]["title"] == (fallback_title or "新建简历1")
    finally:
        context.close()


def test_project_tech_stack_is_saved_without_blurring_the_input(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        viewport={"width": 1672, "height": 870},
        locale="zh-CN",
    )
    page = context.new_page()
    save_payloads: list[dict[str, object]] = []

    def capture_save(route: Route) -> None:
        if route.request.method == "PUT":
            payload = route.request.post_data_json
            assert isinstance(payload, dict)
            save_payloads.append(payload)
        route.continue_()

    page.route(f"**/api/resumes/{resume_id}*", capture_save)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="项目经历: 展开或收起模块",
            exact=True,
        ).click()
        item_toggle = page.get_by_role(
            "button",
            name="展开或收起条目 1",
            exact=True,
        )
        item_shell = item_toggle.locator("xpath=ancestor::section[1]")
        item_header = item_shell.locator("h4").locator("xpath=..")
        item_toggle.click()

        tech_stack_input = page.get_by_label("技术栈", exact=True)
        expected_tech_stack = ["React", "TypeScript", "FastAPI"]
        tech_stack_input.fill(", ".join(expected_tech_stack))
        assert tech_stack_input.evaluate(
            "element => element === document.activeElement"
        )

        page.keyboard.press("Control+S")

        deadline = time.monotonic() + 5
        while len(save_payloads) < 1 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert save_payloads, "Focused tech-stack edits did not trigger a save."
        project_section = next(
            section
            for section in save_payloads[-1]["resume"]["sections"]
            if section["kind"] == "project"
        )
        assert project_section["items"][0]["techStack"] == expected_tech_stack
        assert tech_stack_input.evaluate(
            "element => element === document.activeElement"
        )
        item_toggle.click()
        assert item_header.locator("p").count() == 0
    finally:
        context.close()


def test_resume_gallery_hides_card_delete_actions_for_multi_selection(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    extra_resume_id: str | None = None

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"title": "Multi-selection delete regression"},
        )
        assert create_response.ok
        create_payload = create_response.json()
        assert create_payload["code"] == 0
        extra_resume_id = create_payload["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.get_by_role("button", name="选择", exact=True).click()

        resume_cards = page.locator('a[href^="/resume/"]')
        assert resume_cards.count() >= 2
        resume_cards.nth(0).click()
        assert page.locator('button[aria-label="确认删除"]').count() == 1

        resume_cards.nth(1).click()
        page.get_by_role("button", name="批量删除", exact=True).wait_for(
            state="visible"
        )
        assert page.locator('button[aria-label="确认删除"]').count() == 0

        resume_cards.nth(1).click()
        assert page.locator('button[aria-label="确认删除"]').count() == 1
    finally:
        if extra_resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{extra_resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{extra_resume_id}")
        context.close()


def test_gallery_pagination_keeps_active_page_clear_of_previous_action(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 800, "height": 900})
    page = context.new_page()
    extra_resume_ids: list[str] = []

    try:
        for index in range(8):
            create_response = page.request.post(
                f"{frontend_url}/api/resumes",
                data={"title": f"Pagination spacing regression {index + 1}"},
            )
            assert create_response.ok
            create_payload = create_response.json()
            assert create_payload["code"] == 0
            extra_resume_ids.append(create_payload["data"]["resume"]["id"])

        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        pagination = page.locator('[data-slot="pagination-content"]')
        pagination.wait_for(state="visible")
        previous_link = pagination.get_by_role(
            "link",
            name="上一页",
            exact=True,
        )
        next_link = pagination.get_by_role(
            "link",
            name="下一页",
            exact=True,
        )
        active_page_link = pagination.locator('[aria-current="page"]')
        inactive_page_link = pagination.get_by_role("link", name="2", exact=True)
        previous_label = previous_link.locator("span")

        pagination_geometry = page.evaluate(
            r"""
            ([previous, previousLabel, active, inactive, next]) => {
              const hasVisibleShadow = (boxShadow) => {
                if (boxShadow === 'none') return false;
                const colors = boxShadow.match(/rgba?\([^)]*\)/g) ?? [];
                return colors.some((color) => {
                  if (!color.startsWith('rgba(')) return true;
                  const alpha = Number.parseFloat(color.split(',').at(-1));
                  return alpha > 0;
                });
              };
              const previousRect = previous.getBoundingClientRect();
              const previousLabelRect = previousLabel.getBoundingClientRect();
              const activeRect = active.getBoundingClientRect();
              const inactiveRect = inactive.getBoundingClientRect();
              const paginationStyle = getComputedStyle(previous.closest(
                '[data-slot="pagination-content"]'
              ));
              const activeStyle = getComputedStyle(active);
              const inactiveStyle = getComputedStyle(inactive);
              return {
                controlSpacing: activeRect.left - previousRect.right,
                labelSpacing: activeRect.left - previousLabelRect.right,
                previousOverflows: previous.scrollWidth > previous.clientWidth,
                nextOverflows: next.scrollWidth > next.clientWidth,
                outerBorderWidth: paginationStyle.borderTopWidth,
                outerBackgroundColor: paginationStyle.backgroundColor,
                outerBoxShadow: paginationStyle.boxShadow,
                activeBorderWidth: activeStyle.borderTopWidth,
                activeBorderStyle: activeStyle.borderTopStyle,
                activeHasVisibleShadow: hasVisibleShadow(
                  activeStyle.boxShadow
                ),
                activeBorderRadius: Number.parseFloat(
                  activeStyle.borderTopLeftRadius
                ),
                activeWidth: activeRect.width,
                activeHeight: activeRect.height,
                inactiveBorderWidth: inactiveStyle.borderTopWidth,
                inactiveHasVisibleShadow: hasVisibleShadow(
                  inactiveStyle.boxShadow
                ),
                inactiveWidth: inactiveRect.width,
                inactiveHeight: inactiveRect.height,
              };
            }
            """,
            [
                previous_link.element_handle(),
                previous_label.element_handle(),
                active_page_link.element_handle(),
                inactive_page_link.element_handle(),
                next_link.element_handle(),
            ],
        )
        assert not pagination_geometry["previousOverflows"]
        assert not pagination_geometry["nextOverflows"]
        assert pagination_geometry["controlSpacing"] >= 4
        assert pagination_geometry["labelSpacing"] >= 8
        assert pagination_geometry["outerBorderWidth"] == "0px"
        assert pagination_geometry["outerBackgroundColor"] == "rgba(0, 0, 0, 0)"
        assert pagination_geometry["outerBoxShadow"] == "none"
        assert pagination_geometry["activeBorderWidth"] == "1px"
        assert pagination_geometry["activeBorderStyle"] == "solid"
        assert not pagination_geometry["activeHasVisibleShadow"]
        assert pagination_geometry["activeBorderRadius"] == 8
        assert pagination_geometry["activeWidth"] == 32
        assert pagination_geometry["activeHeight"] == 32
        assert pagination_geometry["inactiveBorderWidth"] == "0px"
        assert not pagination_geometry["inactiveHasVisibleShadow"]
        assert pagination_geometry["inactiveWidth"] == 32
        assert pagination_geometry["inactiveHeight"] == 32
    finally:
        for resume_id in extra_resume_ids:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_autosave_max_wait_retries_with_backoff_without_toast_storm(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    save_urls: list[str] = []
    active_saves = 0
    max_active_saves = 0

    def fail_autosave(route: Route) -> None:
        nonlocal active_saves, max_active_saves
        if route.request.method != "PUT":
            route.continue_()
            return

        save_urls.append(route.request.url)
        active_saves += 1
        max_active_saves = max(max_active_saves, active_saves)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "code": 40000,
                    "message": "RESUME_DOCUMENT_INVALID",
                    "data": None,
                }
            ),
        )
        active_saves -= 1

    page.route(f"**/api/resumes/{resume_id}*", fail_autosave)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        name_input = page.locator('input[name="name"]')
        page.clock.install()
        first_edit_started_at = page.evaluate("Date.now()")

        # Keep resetting the 5-second idle timer. maxWait must still flush at
        # 30 seconds from the first dirty edit.
        for index in range(7):
            name_input.fill(f"Continuous Edit {index}")
            page.clock.fast_forward(4_000)

        # The final edit lands at 28 seconds. Advance in small steps until the
        # first request appears, then test retry delays relative to that exact
        # failure instead of assuming network callbacks are instantaneous.
        name_input.fill("Continuous Edit 7")
        deadline = time.monotonic() + 3
        while len(save_urls) < 1 and time.monotonic() < deadline:
            page.clock.fast_forward(100)
            page.wait_for_timeout(25)

        assert len(save_urls) == 1, save_urls
        assert page.evaluate("Date.now()") - first_edit_started_at >= 30_000
        assert "saveMode=autosave" in save_urls[0]

        page.clock.fast_forward(1_999)
        assert len(save_urls) == 1, save_urls
        page.clock.fast_forward(1)
        deadline = time.monotonic() + 3
        while len(save_urls) < 2 and time.monotonic() < deadline:
            page.wait_for_timeout(25)
        assert len(save_urls) == 2, save_urls
        assert page.get_by_text("请求失败，请稍后重试", exact=True).count() == 0

        page.clock.fast_forward(4_999)
        assert len(save_urls) == 2, save_urls
        page.clock.fast_forward(1)
        deadline = time.monotonic() + 3
        while len(save_urls) < 3 and time.monotonic() < deadline:
            page.wait_for_timeout(25)
        assert len(save_urls) == 3, save_urls
        page.get_by_text("请求失败，请稍后重试", exact=True).wait_for(state="visible")

        page.clock.fast_forward(60_000)
        assert len(save_urls) == 3, save_urls
        assert max_active_saves == 1
        assert page.get_by_text("请求失败，请稍后重试", exact=True).count() == 1
    finally:
        context.close()


def test_template_autosave_preserves_edit_made_during_active_save(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="创建可编辑副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = page.url.rsplit("/", maxsplit=1)[-1]
        save_payloads: list[dict[str, object]] = []

        def delay_first_save(route: Route) -> None:
            request = route.request
            if request.method != "PUT":
                route.continue_()
                return

            payload = request.post_data_json
            assert isinstance(payload, dict)
            save_payloads.append(payload)
            if len(save_payloads) == 1:
                time.sleep(1)
            route.continue_()

        page.route(f"**/api/templates/{template_id}", delay_first_save)
        page.locator('[data-slot="collapsible-trigger"]').filter(
            has_text="模板信息"
        ).click()
        template_name_input = page.get_by_label("模板名称", exact=True)
        template_name_input.fill("First Template Save")
        page.wait_for_timeout(50)
        page.evaluate(
            """
            () => {
              const labels = [...document.querySelectorAll("label")];
              const label = labels.find((candidate) =>
                candidate.textContent?.includes("模板名称"),
              );
              const input = label?.querySelector("input");
              const valueSetter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype,
                "value",
              )?.set;
              if (!(input instanceof HTMLInputElement) || !valueSetter) {
                throw new Error("Template name input is unavailable.");
              }
              window.setTimeout(() => {
                valueSetter.call(input, "Latest Template During Save");
                input.dispatchEvent(new Event("input", { bubbles: true }));
              }, 200);
            }
            """
        )
        page.keyboard.press("Control+S")

        deadline = time.monotonic() + 8
        while len(save_payloads) < 2 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert len(save_payloads) >= 2, save_payloads
        assert save_payloads[-1]["template"]["name"] == ("Latest Template During Save")
    finally:
        context.close()


def test_template_image_drag_near_page_edge_persists_without_repositioning(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 2048, "height": 1226})
    page = context.new_page()
    template_id: str | None = None

    def get_image_frame():
        preview_page = page.locator('[data-export-root="resume-page"]:visible').last
        image_frame = preview_page.locator('[data-template-image-frame="true"]').first
        image_frame.wait_for(state="visible")
        return image_frame

    def get_rendered_left_mm() -> float:
        return get_image_frame().evaluate(
            "(element) => Number.parseFloat(element.style.left)"
        )

    def drag_image_to_x(target_x: float) -> None:
        geometry = get_image_frame().evaluate(
            """
            (element) => {
              const frame = element.getBoundingClientRect();
              const resumePage = element.closest('[data-export-root="resume-page"]');
              const pageRect = resumePage.getBoundingClientRect();
              return {
                centerX: frame.left + frame.width / 2,
                centerY: frame.top + frame.height / 2,
                currentX: Number.parseFloat(element.style.left),
                pxPerMm: pageRect.width / 210,
              };
            }
            """
        )

        page.mouse.move(geometry["centerX"], geometry["centerY"])
        page.mouse.down()
        page.mouse.move(
            geometry["centerX"]
            + (target_x - geometry["currentX"]) * geometry["pxPerMm"],
            geometry["centerY"],
            steps=20,
        )
        page.mouse.up()

    def assert_x_control_value(expected: float) -> None:
        x_input = page.get_by_role("spinbutton", name="横向位置", exact=True)
        assert float(x_input.input_value()) == expected

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="创建可编辑副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = urlparse(page.url).path.rsplit("/", maxsplit=1)[-1]

        page.get_by_role("tab", name="装饰", exact=True).click()
        page.get_by_role(
            "button",
            name="添加图片占位符",
            exact=True,
        ).click()

        image_editor = page.get_by_role("group", name="图片元素 1", exact=True)
        image_editor.get_by_text("图片 1", exact=True).wait_for(state="visible")
        assert (
            image_editor.get_by_role("textbox", name="图片名称", exact=True).count()
            == 0
        )
        edit_name_button = image_editor.get_by_role(
            "button", name="编辑图片名称", exact=True
        )
        edit_name_button.click()
        image_name_input = image_editor.get_by_role(
            "textbox", name="图片名称", exact=True
        )
        assert image_name_input.input_value() == "图片 1"
        image_name_input.fill("临时名称")
        image_name_input.press("Escape")
        image_name_input.wait_for(state="hidden")
        image_editor.get_by_text("图片 1", exact=True).wait_for(state="visible")
        edit_name_button.click()
        image_name_input = image_editor.get_by_role(
            "textbox", name="图片名称", exact=True
        )
        image_name_input.fill("头像")
        image_name_input.press("Enter")
        image_name_input.wait_for(state="hidden")
        image_editor.get_by_text("头像", exact=True).wait_for(state="visible")
        assert (
            image_editor.locator('[data-slot="template-image-thumbnail"]')
            .inner_text()
            .strip()
            == ""
        )
        editor_widths = image_editor.evaluate(
            """
            (element) => ({
              clientWidth: element.clientWidth,
              scrollWidth: element.scrollWidth,
            })
            """
        )
        assert editor_widths["scrollWidth"] <= editor_widths["clientWidth"] + 1
        upload_button = page.get_by_role("button", name="上传图片", exact=True)
        upload_button.wait_for(state="visible")
        source_label = image_editor.get_by_text("图片来源", exact=True)
        source_label.wait_for(state="visible")
        fit_label = image_editor.get_by_text("适配方式", exact=True)
        fit_label.wait_for(state="visible")
        fit_select = page.get_by_role("combobox", name="适配方式", exact=True)
        fit_select.wait_for(state="visible")
        source_label_box = source_label.bounding_box()
        fit_label_box = fit_label.bounding_box()
        upload_button_box = upload_button.bounding_box()
        fit_select_box = fit_select.bounding_box()
        assert source_label_box is not None
        assert fit_label_box is not None
        assert upload_button_box is not None
        assert fit_select_box is not None
        assert (
            image_editor.get_by_role("button", name="图片 URL", exact=True).count() == 0
        )
        assert page.get_by_role("dialog", name="图片 URL", exact=True).count() == 0
        assert source_label_box["x"] + source_label_box["width"] <= (
            upload_button_box["x"] + 1
        )
        assert fit_label_box["x"] + fit_label_box["width"] <= (fit_select_box["x"] + 1)
        assert (
            abs(
                source_label_box["y"]
                + source_label_box["height"] / 2
                - upload_button_box["y"]
                - upload_button_box["height"] / 2
            )
            <= 2
        )
        assert (
            abs(
                fit_label_box["y"]
                + fit_label_box["height"] / 2
                - fit_select_box["y"]
                - fit_select_box["height"] / 2
            )
            <= 2
        )
        assert fit_label_box["y"] >= (
            source_label_box["y"] + source_label_box["height"]
        )
        assert (
            abs(
                upload_button_box["x"]
                + upload_button_box["width"]
                - fit_select_box["x"]
                - fit_select_box["width"]
            )
            <= 2
        )

        image_editor.locator('input[type="file"]').set_input_files(
            {
                "name": "头像.svg",
                "mimeType": "image/svg+xml",
                "buffer": (
                    b'<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'
                ),
            }
        )
        uploaded_thumbnail = image_editor.locator(
            '[data-slot="template-image-thumbnail"] img'
        )
        uploaded_thumbnail.wait_for(state="visible")
        assert uploaded_thumbnail.get_attribute("src").startswith(
            "data:image/svg+xml;base64,"
        )
        image_editor.get_by_role("button", name="替换图片", exact=True).wait_for(
            state="visible"
        )

        x_input = page.get_by_role("spinbutton", name="横向位置", exact=True)
        y_input = page.get_by_role("spinbutton", name="纵向位置", exact=True)
        width_input = page.get_by_role("spinbutton", name="宽度", exact=True)
        height_input = page.get_by_role("spinbutton", name="高度", exact=True)

        for field_label in (
            "横向位置",
            "纵向位置",
            "宽度",
            "高度",
        ):
            image_editor.get_by_text(field_label, exact=True).wait_for(state="visible")

        assert image_editor.get_by_text("图片宽度", exact=True).count() == 0
        assert image_editor.get_by_text("图片高度", exact=True).count() == 0
        assert image_editor.get_by_text("位置", exact=True).count() == 0
        assert image_editor.get_by_text("尺寸", exact=True).count() == 0

        numeric_field_geometries = []
        for numeric_input in (
            x_input,
            y_input,
            width_input,
            height_input,
        ):
            assert (
                numeric_input.evaluate(
                    "(element) => getComputedStyle(element).appearance"
                )
                == "textfield"
            )
            inline_field_geometry = numeric_input.evaluate(
                """
                (element) => {
                  const field = element.closest('[data-slot="field"]');
                  const label = field?.querySelector('[data-slot="field-label"]');
                  const inputGroup = element.closest('[data-slot="input-group"]');
                  if (!label || !inputGroup) {
                    throw new Error('Inline numeric field is incomplete.');
                  }
                  const labelRect = label.getBoundingClientRect();
                  const inputRect = inputGroup.getBoundingClientRect();
                  return {
                    fieldLeft: field.getBoundingClientRect().left,
                    fieldTop: field.getBoundingClientRect().top,
                    labelRight: labelRect.right,
                    labelCenterY: labelRect.top + labelRect.height / 2,
                    inputLeft: inputRect.left,
                    inputRight: inputRect.right,
                    inputCenterY: inputRect.top + inputRect.height / 2,
                    inputWidth: inputRect.width,
                  };
                }
                """
            )
            numeric_field_geometries.append(inline_field_geometry)
            assert inline_field_geometry["labelRight"] <= (
                inline_field_geometry["inputLeft"] + 1
            )
            assert (
                abs(
                    inline_field_geometry["labelCenterY"]
                    - inline_field_geometry["inputCenterY"]
                )
                <= 2
            )
            assert inline_field_geometry["inputWidth"] <= 120

        for upper, lower in (
            (numeric_field_geometries[0], numeric_field_geometries[2]),
            (numeric_field_geometries[1], numeric_field_geometries[3]),
        ):
            assert abs(upper["fieldLeft"] - lower["fieldLeft"]) <= 1
            assert abs(upper["inputLeft"] - lower["inputLeft"]) <= 1
            assert abs(upper["inputRight"] - lower["inputRight"]) <= 1

        for left, right in (
            (numeric_field_geometries[0], numeric_field_geometries[1]),
            (numeric_field_geometries[2], numeric_field_geometries[3]),
        ):
            assert abs(left["fieldTop"] - right["fieldTop"]) <= 1

        assert x_input.get_attribute("max") == "180"
        assert y_input.get_attribute("max") == "277"
        assert width_input.get_attribute("max") == "44"
        assert height_input.get_attribute("max") == "120"

        assert (
            image_editor.get_by_role("button", name="锁定宽高比", exact=True).count()
            == 0
        )
        assert (
            image_editor.get_by_role(
                "button", name="解除宽高比锁定", exact=True
            ).count()
            == 0
        )
        width_input.fill("36")
        width_input.press("Enter")
        assert float(width_input.input_value()) == 36
        assert float(height_input.input_value()) == 20
        width_input.fill("30")
        width_input.press("Enter")
        assert float(height_input.input_value()) == 20

        assert image_editor.locator('[data-slot="separator"]').count() == 0

        assert image_editor.get_by_role("button", name="外观", exact=True).count() == 0
        image_editor.get_by_text("外观", exact=True).wait_for(state="visible")
        opacity_slider = page.get_by_role("slider", name="透明度", exact=True)
        opacity_slider.wait_for(state="visible")
        assert opacity_slider.get_attribute("aria-valuetext") == "100%"
        opacity_input = image_editor.get_by_role(
            "spinbutton", name="透明度", exact=True
        )
        opacity_input.wait_for(state="visible")
        assert opacity_input.input_value() == "100"
        assert (
            opacity_input.evaluate("(element) => getComputedStyle(element).appearance")
            == "textfield"
        )
        opacity_input.fill("")
        assert opacity_input.input_value() == ""
        opacity_input.type("75")
        opacity_input.press("Enter")
        assert opacity_input.input_value() == "75"
        assert opacity_slider.get_attribute("aria-valuenow") == "0.75"
        assert opacity_slider.get_attribute("aria-valuetext") == "75%"
        opacity_row_geometry = opacity_slider.evaluate(
            """
            (element) => {
              const row = element.closest(
                '[data-slot="template-image-slider-field"]'
              );
              const label = row?.querySelector('[data-slot="field-label"]');
              const slider = row?.querySelector('[data-slot="slider"]');
              const value = row?.querySelector(
                '[data-template-image-slider-value="true"]'
              );
              if (!row || !label || !slider || !value) {
                throw new Error('Compact opacity row is incomplete.');
              }
              const labelRect = label.getBoundingClientRect();
              const sliderRect = slider.getBoundingClientRect();
              const valueRect = value.getBoundingClientRect();
              return {
                labelRight: labelRect.right,
                labelCenterY: labelRect.top + labelRect.height / 2,
                sliderLeft: sliderRect.left,
                sliderRight: sliderRect.right,
                sliderCenterY: sliderRect.top + sliderRect.height / 2,
                valueLeft: valueRect.left,
                valueCenterY: valueRect.top + valueRect.height / 2,
                valueWidth: valueRect.width,
                valueText: value.querySelector('input')?.value,
              };
            }
            """
        )
        assert opacity_row_geometry["labelRight"] < (opacity_row_geometry["sliderLeft"])
        assert opacity_row_geometry["sliderRight"] < (opacity_row_geometry["valueLeft"])
        assert (
            abs(
                opacity_row_geometry["labelCenterY"]
                - opacity_row_geometry["sliderCenterY"]
            )
            <= 2
        )
        assert (
            abs(
                opacity_row_geometry["sliderCenterY"]
                - opacity_row_geometry["valueCenterY"]
            )
            <= 2
        )
        assert opacity_row_geometry["valueWidth"] <= 120
        assert opacity_row_geometry["valueText"] == "75"

        border_radius_input = image_editor.get_by_role(
            "spinbutton", name="圆角", exact=True
        )
        radius_row_geometry = border_radius_input.evaluate(
            """
            (element) => {
              const field = element.closest('[data-slot="field"]');
              const label = field?.querySelector('[data-slot="field-label"]');
              const input = element.closest('[data-slot="input-group"]');
              if (!field || !label || !input) {
                throw new Error('Compact radius row is incomplete.');
              }
              const labelRect = label.getBoundingClientRect();
              const inputRect = input.getBoundingClientRect();
              return {
                labelRight: labelRect.right,
                labelCenterY: labelRect.top + labelRect.height / 2,
                inputLeft: inputRect.left,
                inputCenterY: inputRect.top + inputRect.height / 2,
                inputWidth: inputRect.width,
              };
            }
            """
        )
        assert radius_row_geometry["labelRight"] < (radius_row_geometry["inputLeft"])
        assert (
            abs(
                radius_row_geometry["labelCenterY"]
                - radius_row_geometry["inputCenterY"]
            )
            <= 2
        )
        assert radius_row_geometry["inputWidth"] <= 120

        border_switch = image_editor.get_by_role("switch", name="边框", exact=True)
        assert border_switch.get_attribute("aria-checked") == "true"
        border_width_input = image_editor.get_by_role(
            "spinbutton", name="边框粗细", exact=True
        )
        border_color_input = image_editor.get_by_label("边框颜色", exact=True)
        border_width_input.wait_for(state="visible")
        border_color_input.wait_for(state="visible")

        def field_geometry(control):
            return control.evaluate(
                """
                (element) => {
                  const rect = element.closest(
                    '[data-slot="field"]'
                  ).getBoundingClientRect();
                  return { top: rect.top, left: rect.left };
                }
                """
            )

        radius_geometry = field_geometry(border_radius_input)
        border_width_geometry = field_geometry(border_width_input)
        border_geometry = field_geometry(border_switch)
        border_color_geometry = field_geometry(border_color_input)
        assert abs(radius_geometry["top"] - border_width_geometry["top"]) <= 1
        assert radius_geometry["left"] < border_width_geometry["left"]
        assert abs(border_geometry["top"] - border_color_geometry["top"]) <= 1
        assert border_geometry["left"] < border_color_geometry["left"]
        border_switch.click()
        assert border_switch.get_attribute("aria-checked") == "false"
        border_width_input.wait_for(state="hidden")
        border_color_input.wait_for(state="hidden")

        expanded_editor_widths = image_editor.evaluate(
            """
            (element) => ({
              clientWidth: element.clientWidth,
              scrollWidth: element.scrollWidth,
            })
            """
        )
        assert (
            expanded_editor_widths["scrollWidth"]
            <= expanded_editor_widths["clientWidth"] + 1
        )

        x_label_box = page.get_by_text("横向位置", exact=True).bounding_box()
        assert x_label_box is not None
        assert x_label_box["width"] >= 50
        assert x_label_box["height"] <= 24

        assert get_rendered_left_mm() == 166
        drag_image_to_x(16.5)
        assert get_rendered_left_mm() == 16.5
        drag_image_to_x(15.5)
        assert get_rendered_left_mm() == 15.5
        assert_x_control_value(15.5)
        assert width_input.get_attribute("max") == "120"

        x_input.fill("12")
        x_input.press("Enter")
        assert get_rendered_left_mm() == 12
        x_input.fill("15.5")
        x_input.press("Enter")
        assert get_rendered_left_mm() == 15.5

        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/templates/{template_id}"
            )
        ) as save_response_info:
            page.keyboard.press("Control+S")

        save_response = save_response_info.value
        assert save_response.ok
        save_payload = save_response.request.post_data_json
        saved_images = save_payload["template"]["layout"]["images"]
        assert len(saved_images) == 1
        assert saved_images[0]["name"] == "头像"
        assert saved_images[0]["x"] == 15.5
        assert saved_images[0]["y"] == 18
        assert saved_images[0]["opacity"] == 0.75
        assert saved_images[0]["borderWidth"] == 0
        assert saved_images[0]["src"].startswith("data:image/svg+xml;base64,")

        page.reload(wait_until="networkidle")
        page.get_by_role("tab", name="装饰", exact=True).click()
        assert get_rendered_left_mm() == 15.5

        first_image_editor = page.get_by_role("group", name="图片元素 1", exact=True)
        first_image_editor.get_by_text("头像", exact=True).wait_for(state="visible")
        single_expand_button = first_image_editor.get_by_role(
            "button", name="展开图片设置", exact=True
        )
        assert single_expand_button.get_attribute("aria-expanded") == "false"
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="hidden")
        single_expand_button.focus()
        page.keyboard.press("Enter")
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="visible")
        assert_x_control_value(15.5)
        assert (
            first_image_editor.get_by_role("button", name="外观", exact=True).count()
            == 0
        )
        first_image_editor.get_by_text("外观", exact=True).wait_for(state="visible")
        assert (
            first_image_editor.get_by_role(
                "spinbutton", name="透明度", exact=True
            ).input_value()
            == "75"
        )
        persisted_border_switch = first_image_editor.get_by_role(
            "switch", name="边框", exact=True
        )
        assert persisted_border_switch.get_attribute("aria-checked") == "false"
        first_image_editor.get_by_role(
            "spinbutton", name="边框粗细", exact=True
        ).wait_for(state="hidden")
        first_image_editor.get_by_label("边框颜色", exact=True).wait_for(state="hidden")
        first_image_editor.evaluate(
            """
            (element) => Promise.all(
              element.getAnimations({ subtree: true }).map(
                (animation) => animation.finished
              )
            )
            """
        )
        card_style = first_image_editor.evaluate(
            """
            (element) => {
              const cardReference = document.createElement("div");
              cardReference.className = "rounded-lg bg-muted/35 shadow-xs";
              cardReference.style.position = "fixed";
              cardReference.style.visibility = "hidden";
              const transparentReference = document.createElement("div");
              transparentReference.style.position = "fixed";
              transparentReference.style.visibility = "hidden";
              document.body.append(cardReference, transparentReference);

              const actual = getComputedStyle(element);
              const headerElement = element.querySelector(
                '[data-slot="template-image-card-header"]'
              );
              const contentElement = element.querySelector(
                '[data-slot="template-image-card-content"]'
              );
              const header = getComputedStyle(headerElement);
              const content = getComputedStyle(contentElement);
              const expectedCard = getComputedStyle(cardReference);
              const expectedTransparent = getComputedStyle(
                transparentReference
              );
              const rootRect = element.getBoundingClientRect();
              const headerRect = headerElement.getBoundingClientRect();
              const contentRect = contentElement.getBoundingClientRect();
              const result = {
                borderWidths: [
                  actual.borderTopWidth,
                  actual.borderRightWidth,
                  actual.borderBottomWidth,
                  actual.borderLeftWidth,
                ],
                backgroundColor: actual.backgroundColor,
                borderRadius: actual.borderRadius,
                boxShadow: actual.boxShadow,
                headerBackgroundColor: header.backgroundColor,
                contentBackgroundColor: content.backgroundColor,
                headerBoxShadow: header.boxShadow,
                contentBoxShadow: content.boxShadow,
                containsHeader:
                  rootRect.top <= headerRect.top + 1 &&
                  rootRect.bottom >= headerRect.bottom - 1,
                containsContent:
                  rootRect.top <= contentRect.top + 1 &&
                  rootRect.bottom >= contentRect.bottom - 1,
                expectedBackgroundColor: expectedCard.backgroundColor,
                expectedTransparentBackgroundColor:
                  expectedTransparent.backgroundColor,
                expectedBorderRadius: expectedCard.borderRadius,
                expectedBoxShadow: expectedCard.boxShadow,
              };

              cardReference.remove();
              transparentReference.remove();
              return result;
            }
            """
        )
        assert set(card_style["borderWidths"]) == {"0px"}
        assert card_style["backgroundColor"] == card_style["expectedBackgroundColor"]
        assert card_style["borderRadius"] == card_style["expectedBorderRadius"]
        assert card_style["boxShadow"] == card_style["expectedBoxShadow"]
        assert card_style["boxShadow"] != "none"
        assert (
            card_style["headerBackgroundColor"]
            == card_style["expectedTransparentBackgroundColor"]
        )
        assert (
            card_style["contentBackgroundColor"]
            == card_style["expectedTransparentBackgroundColor"]
        )
        assert card_style["headerBoxShadow"] == "none"
        assert card_style["contentBoxShadow"] == "none"
        assert card_style["containsHeader"] is True
        assert card_style["containsContent"] is True

        single_collapse_button = first_image_editor.get_by_role(
            "button", name="收起图片设置", exact=True
        )
        single_collapse_button.focus()
        page.keyboard.press("Space")
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="hidden")
        single_expand_button = first_image_editor.get_by_role(
            "button", name="展开图片设置", exact=True
        )
        assert single_expand_button.get_attribute("aria-expanded") == "false"
        single_expand_button.focus()
        page.keyboard.press("Enter")
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="visible")

        page.get_by_role("button", name="添加图片占位符", exact=True).click()
        first_image_editor = page.get_by_role("group", name="图片元素 1", exact=True)
        second_image_editor = page.get_by_role("group", name="图片元素 2", exact=True)
        second_image_editor.get_by_text("图片 1", exact=True).wait_for(state="visible")
        first_expand_button = first_image_editor.get_by_role(
            "button", name="展开图片设置", exact=True
        )
        second_collapse_button = second_image_editor.get_by_role(
            "button", name="收起图片设置", exact=True
        )
        assert first_expand_button.get_attribute("aria-expanded") == "false"
        assert second_collapse_button.get_attribute("aria-expanded") == "true"
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="hidden")
        second_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="visible")

        first_expand_button.focus()
        page.keyboard.press("Enter")
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="visible")
        assert (
            first_image_editor.get_by_role(
                "button", name="收起图片设置", exact=True
            ).get_attribute("aria-expanded")
            == "true"
        )
        second_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="hidden")
        second_expand_button = second_image_editor.get_by_role(
            "button", name="展开图片设置", exact=True
        )
        assert second_expand_button.get_attribute("aria-expanded") == "false"

        second_expand_button.focus()
        page.keyboard.press("Enter")
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="hidden")
        second_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="visible")

        second_image_editor.get_by_role("button", name="删除图片", exact=True).click()
        remaining_expand_button = first_image_editor.get_by_role(
            "button", name="展开图片设置", exact=True
        )
        assert remaining_expand_button.get_attribute("aria-expanded") == "false"
        first_image_editor.get_by_role(
            "spinbutton", name="横向位置", exact=True
        ).wait_for(state="hidden")
    finally:
        if not page.is_closed():
            page.close()
        if template_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


def test_empty_template_image_placeholder_only_renders_in_template_preview(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 960})
    page = context.new_page()
    template_id: str | None = None
    resume_id: str | None = None

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="创建可编辑副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = urlparse(page.url).path.rsplit("/", maxsplit=1)[-1]

        page.get_by_role("tab", name="装饰", exact=True).click()
        page.get_by_role(
            "button",
            name="添加图片占位符",
            exact=True,
        ).click()

        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/templates/{template_id}"
            )
        ) as save_response_info:
            page.keyboard.press("Control+S")

        save_response = save_response_info.value
        assert save_response.ok
        saved_template_payload = save_response.request.post_data_json
        template_preview = page.locator('[data-export-root="resume-page"]:visible').last
        template_placeholder = template_preview.locator(
            '[data-template-image-frame="true"]'
        )
        assert template_placeholder.count() == 1
        assert template_placeholder.locator("img").count() == 0
        assert template_placeholder.get_by_text("图片 1", exact=True).count() == 1

        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "title": "Empty template image placeholder regression",
                "template": template_id,
            },
        )
        assert create_response.ok
        resume_id = create_response.json()["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        resume_preview = page.locator('[data-export-root="resume-page"]:visible').first
        resume_preview.wait_for(state="visible")
        empty_resume_frame_count = resume_preview.locator(
            '[data-template-image-frame="true"]'
        ).count()

        page.goto(
            f"{frontend_url}/pdf-export?resumeId={resume_id}&locale=zh",
            wait_until="networkidle",
        )
        page.locator('main[data-pdf-ready="true"]').wait_for(state="visible")
        empty_export_frame_count = page.locator(
            '[data-export-root="resume-page"]:visible '
            '[data-template-image-frame="true"]'
        ).count()

        assert empty_resume_frame_count == 0
        assert empty_export_frame_count == 0

        saved_images = saved_template_payload["template"]["layout"]["images"]
        assert len(saved_images) == 1
        assert saved_images[0]["src"] == ""

        image_data_url = (
            "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
        )
        saved_template_payload["template"]["layout"]["images"] = [
            {**saved_images[0], "src": image_data_url}
        ]
        update_response = page.request.put(
            f"{frontend_url}/api/templates/{template_id}",
            data=saved_template_payload,
        )
        assert update_response.ok

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        resume_preview = page.locator('[data-export-root="resume-page"]:visible').first
        rendered_image_frame = resume_preview.locator(
            '[data-template-image-frame="true"]'
        )
        rendered_image = rendered_image_frame.locator("img")
        assert rendered_image_frame.count() == 1
        assert rendered_image.count() == 1
        assert rendered_image.evaluate(
            "(image) => image.complete && image.naturalWidth > 0"
        )

        page.goto(
            f"{frontend_url}/pdf-export?resumeId={resume_id}&locale=zh",
            wait_until="networkidle",
        )
        page.locator('main[data-pdf-ready="true"]').wait_for(state="visible")
        exported_image = page.locator(
            '[data-export-root="resume-page"]:visible '
            '[data-template-image-frame="true"] img'
        )
        assert exported_image.count() == 1
        assert exported_image.evaluate(
            "(image) => image.complete && image.naturalWidth > 0"
        )
    finally:
        if not page.is_closed():
            page.close()
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        if template_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


def test_template_return_checks_unsaved_changes_before_navigation(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="创建可编辑副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        page.locator('[data-slot="collapsible-trigger"]').filter(
            has_text="模板信息"
        ).click()
        page.get_by_label("模板名称", exact=True).fill("Template Saved Before Return")
        page.get_by_role(
            "button",
            name="返回模板列表",
            exact=True,
        ).click()

        assert page.url.startswith(f"{frontend_url}/template/template-")
        assert (
            page.get_by_role(
                "heading",
                name="有未保存的更改",
                exact=True,
            ).count()
            == 1
        )

        page.get_by_role(
            "button",
            name="保存并离开",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/templates")
    finally:
        context.close()


def test_leave_reprepares_gallery_after_edit_during_target_load(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    resume_id: str | None = None
    gallery_request_count = 0
    updated_name = "Saved During Target Preparation"

    def hold_first_gallery_snapshot(route: Route) -> None:
        nonlocal gallery_request_count
        gallery_request_count += 1
        if gallery_request_count > 1:
            route.continue_()
            return

        response = route.fetch()
        time.sleep(0.45)
        route.fulfill(response=response)

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"title": "Before Target Preparation"},
        )
        assert create_response.ok
        resume_id = create_response.json()["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        page.route(
            "**/api/workspace/pages/resumes",
            hold_first_gallery_snapshot,
        )
        page.evaluate(
            """
            (nextName) => {
              const back = [...document.querySelectorAll("button")].find(
                (button) => button.textContent?.includes("返回简历列表"),
              );
              const name = document.querySelector('input[name="name"]');
              const valueSetter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype,
                "value",
              )?.set;
              if (!(back instanceof HTMLButtonElement) ||
                  !(name instanceof HTMLInputElement) ||
                  !valueSetter) {
                throw new Error("Resume leave targets are unavailable.");
              }
              back.click();
              valueSetter.call(name, nextName);
              name.dispatchEvent(new Event("input", { bubbles: true }));
            }
            """,
            updated_name,
        )

        page.get_by_role(
            "heading",
            name="有未保存的更改",
            exact=True,
        ).wait_for(state="visible")
        assert gallery_request_count == 1

        page.get_by_role(
            "button",
            name="保存并离开",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/resume", timeout=5_000)
        page.wait_for_load_state("networkidle")

        assert gallery_request_count == 2
        assert (
            page.locator(f'a[href="/resume/{resume_id}"]')
            .get_by_text(
                updated_name,
                exact=True,
            )
            .count()
            == 1
        )
    finally:
        if resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_leaving_resume_promotes_completed_autosave_to_checkpoint(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    save_urls: list[str] = []

    def capture_save(route: Route) -> None:
        if route.request.method == "PUT":
            save_urls.append(route.request.url)
        route.continue_()

    page.route(f"**/api/resumes/{resume_id}*", capture_save)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        page.locator('input[name="name"]').fill("Autosaved Before Leave")

        deadline = time.monotonic() + 8
        while len(save_urls) < 1 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert len(save_urls) == 1, save_urls
        assert "saveMode=autosave" in save_urls[0]
        page.wait_for_load_state("networkidle")
        page.get_by_role(
            "button",
            name="返回简历列表",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/resume")

        assert len(save_urls) == 2, save_urls
        assert "saveMode=checkpoint" in save_urls[1]
    finally:
        context.close()


def test_latest_navigation_waits_for_active_checkpoint_promotion(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    resume_id: str | None = None

    try:
        create_response = page.request.post(f"{frontend_url}/api/resumes", data={})
        assert create_response.ok
        resume_id = create_response.json()["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
                and parse_qs(urlparse(response.url).query).get("saveMode")
                == ["autosave"]
            ),
            timeout=8_000,
        ) as autosave_response_info:
            page.locator('input[name="name"]').fill(
                "Autosaved Before Superseded Navigation"
            )
        assert autosave_response_info.value.ok
        page.wait_for_load_state("networkidle")

        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
                and parse_qs(urlparse(response.url).query).get("saveMode")
                == ["checkpoint"]
            )
        ) as checkpoint_response_info:
            page.evaluate(
                """
                () => {
                  const back = [...document.querySelectorAll("button")].find(
                    (button) => button.textContent?.includes("返回简历列表"),
                  );
                  const logout = [...document.querySelectorAll("button")].find(
                    (button) => button.textContent?.trim() === "退出登录",
                  );
                  if (!(back instanceof HTMLButtonElement) ||
                      !(logout instanceof HTMLButtonElement)) {
                    throw new Error("Resume navigation targets are unavailable.");
                  }
                  back.click();
                  logout.click();
                }
                """
            )
        assert checkpoint_response_info.value.ok

        page.wait_for_url(f"{frontend_url}/login", timeout=5_000)
        page.wait_for_load_state("networkidle")
        assert page.url == f"{frontend_url}/login"
    finally:
        if resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_checkpoint_failure_after_autosave_does_not_block_leaving_resume(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    save_urls: list[str] = []

    def fail_checkpoint(route: Route) -> None:
        if route.request.method != "PUT":
            route.continue_()
            return

        save_urls.append(route.request.url)
        if "saveMode=checkpoint" not in route.request.url:
            route.continue_()
            return

        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "code": 40000,
                    "message": "RESUME_DOCUMENT_INVALID",
                    "data": None,
                }
            ),
        )

    page.route(f"**/api/resumes/{resume_id}*", fail_checkpoint)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        page.locator('input[name="name"]').fill("Autosaved Before Failed Checkpoint")

        deadline = time.monotonic() + 8
        while len(save_urls) < 1 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert len(save_urls) == 1, save_urls
        assert "saveMode=autosave" in save_urls[0]
        page.wait_for_load_state("networkidle")
        page.get_by_role(
            "button",
            name="返回简历列表",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/resume", timeout=3_000)
        page.get_by_text(
            "内容已自动保存，但未能创建历史版本",
            exact=True,
        ).wait_for(state="visible")

        assert len(save_urls) == 2, save_urls
        assert "saveMode=checkpoint" in save_urls[1]
        assert page.get_by_text("请求失败，请稍后重试", exact=True).count() == 0
    finally:
        context.close()


def test_checkpoint_failure_keeps_new_edit_made_before_logout(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    save_urls: list[str] = []

    def fail_delayed_checkpoint(route: Route) -> None:
        if route.request.method != "PUT":
            route.continue_()
            return

        save_urls.append(route.request.url)
        if "saveMode=checkpoint" not in route.request.url:
            route.continue_()
            return

        # Keep the checkpoint in flight while the browser applies a newer edit.
        time.sleep(0.8)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "code": 40000,
                    "message": "RESUME_DOCUMENT_INVALID",
                    "data": None,
                }
            ),
        )

    page.route(f"**/api/resumes/{resume_id}*", fail_delayed_checkpoint)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        page.locator('input[name="name"]').fill("Autosaved Before Promotion")

        deadline = time.monotonic() + 8
        while len(save_urls) < 1 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert len(save_urls) == 1, save_urls
        assert "saveMode=autosave" in save_urls[0]
        page.wait_for_load_state("networkidle")
        page.evaluate(
            """
            () => {
              const input = document.querySelector('input[name="name"]');
              if (!(input instanceof HTMLInputElement)) {
                throw new Error("Name input is unavailable.");
              }
              const valueSetter = Object.getOwnPropertyDescriptor(
                HTMLInputElement.prototype,
                "value",
              )?.set;
              if (!valueSetter) {
                throw new Error("Native input value setter is unavailable.");
              }
              window.setTimeout(() => {
                valueSetter.call(input, "New Edit During Failed Checkpoint");
                input.dispatchEvent(new Event("input", { bubbles: true }));
              }, 150);
            }
            """
        )
        page.get_by_role("button", name="退出登录", exact=True).click()

        page.get_by_role(
            "heading",
            name="有未保存的更改",
            exact=True,
        ).wait_for(state="visible")
        assert page.url == f"{frontend_url}/resume/{resume_id}"
        assert (
            page.locator('input[name="name"]').input_value()
            == "New Edit During Failed Checkpoint"
        )
        assert len(save_urls) == 2, save_urls
        assert "saveMode=checkpoint" in save_urls[1]
    finally:
        context.close()


def test_discard_waits_for_active_save_and_restores_persisted_resume(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    save_count = 0

    def delay_first_save(route: Route) -> None:
        nonlocal save_count
        if route.request.method != "PUT":
            route.continue_()
            return

        save_count += 1
        if save_count == 1:
            time.sleep(1)
        route.continue_()

    page.route(f"**/api/resumes/{resume_id}*", delay_first_save)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        name_input = page.locator('input[name="name"]')
        original_name = name_input.input_value()
        name_input.fill("Discarded During Active Save")
        page.evaluate(
            """
            () => {
              window.setTimeout(() => {
                const backButton = [...document.querySelectorAll("button")].find(
                  (button) => button.textContent?.includes("返回简历列表"),
                );
                if (!(backButton instanceof HTMLButtonElement)) {
                  throw new Error("Back button is unavailable.");
                }
                backButton.click();
              }, 200);
              window.setTimeout(() => {
                const discardButton = [...document.querySelectorAll("button")].find(
                  (button) => button.textContent?.trim() === "放弃更改",
                );
                if (!(discardButton instanceof HTMLButtonElement)) {
                  throw new Error("Discard button is unavailable.");
                }
                discardButton.click();
              }, 400);
            }
            """
        )
        page.keyboard.press("Control+S")
        page.wait_for_url(f"{frontend_url}/resume")
        page.wait_for_load_state("networkidle")

        persisted_response = page.request.get(f"{frontend_url}/api/resumes/{resume_id}")
        persisted = persisted_response.json()["data"]["resume"]
        assert persisted["resume"]["basic"]["name"] == original_name
        assert save_count == 2
    finally:
        context.close()


def test_browser_history_navigation_uses_unsaved_changes_guard(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.locator(f'a[href="/resume/{resume_id}"]').click()
        page.wait_for_url(f"{frontend_url}/resume/{resume_id}")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        page.locator('input[name="name"]').fill("Unsaved Browser Back")
        page.evaluate("window.history.back()")
        page.wait_for_timeout(250)

        assert page.url == f"{frontend_url}/resume/{resume_id}"
        assert (
            page.get_by_role(
                "heading",
                name="有未保存的更改",
                exact=True,
            ).count()
            == 1
        )

        page.get_by_role(
            "button",
            name="继续编辑",
            exact=True,
        ).click()
        assert page.url == f"{frontend_url}/resume/{resume_id}"
    finally:
        context.close()


def test_browser_back_does_not_restore_consumed_resume_handoff(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    resume_id: str | None = None

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"title": "Consumed history handoff"},
        )
        assert create_response.ok
        resume_id = create_response.json()["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.locator(f'a[href="/resume/{resume_id}"]').click()
        page.wait_for_url(f"{frontend_url}/resume/{resume_id}")
        page.get_by_role(
            "button",
            name="基本信息: 展开或收起模块",
            exact=True,
        ).click()
        name_input = page.locator('input[name="name"]')
        name_input.fill("Saved After Initial Handoff")
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
            )
        ):
            page.get_by_role("button", name="保存状态", exact=True).click()
        page.get_by_role("button", name="保存状态", exact=True).hover()
        page.get_by_text("有未保存更改", exact=True).wait_for(state="detached")

        page.locator('a[href="/templates"]').first.click()
        page.wait_for_url(f"{frontend_url}/templates")
        page.wait_for_load_state("networkidle")

        def delay_back_loader(route: Route) -> None:
            current_response = route.fetch()
            time.sleep(2)
            route.fulfill(response=current_response)

        page.route(
            f"**/api/resumes/{resume_id}",
            delay_back_loader,
        )
        page.evaluate(
            f"""
            () => {{
              window.__staleResumeHandoffEdited = false;
              const deadline = performance.now() + 1_200;
              let openedBasicInfo = false;
              const editOnlyAnImmediateSeed = () => {{
                const input = document.querySelector('input[name="name"]');
                if (
                  window.location.pathname === "/resume/{resume_id}" &&
                  input instanceof HTMLInputElement
                ) {{
                  const valueSetter = Object.getOwnPropertyDescriptor(
                    HTMLInputElement.prototype,
                    "value",
                  )?.set;
                  valueSetter?.call(input, "Stale History Handoff");
                  input.dispatchEvent(new Event("input", {{ bubbles: true }}));
                  window.__staleResumeHandoffEdited = true;
                  return;
                }}
                if (
                  window.location.pathname === "/resume/{resume_id}" &&
                  !openedBasicInfo
                ) {{
                  const trigger = [...document.querySelectorAll("button")]
                    .find((candidate) =>
                      candidate.getAttribute("aria-label") ===
                      "基本信息: 展开或收起模块",
                    );
                  if (trigger instanceof HTMLButtonElement) {{
                    openedBasicInfo = true;
                    trigger.click();
                  }}
                }}
                if (performance.now() < deadline) {{
                  requestAnimationFrame(editOnlyAnImmediateSeed);
                }}
              }};
              requestAnimationFrame(editOnlyAnImmediateSeed);
            }}
            """
        )

        page.go_back(wait_until="commit")
        page.wait_for_url(f"{frontend_url}/resume/{resume_id}")
        page.wait_for_load_state("networkidle")
        if not page.locator('input[name="name"]').is_visible():
            page.get_by_role(
                "button",
                name="基本信息: 展开或收起模块",
                exact=True,
            ).click()

        assert page.evaluate("window.__staleResumeHandoffEdited") is False
        assert page.locator('input[name="name"]').input_value() == (
            "Saved After Initial Handoff"
        )
    finally:
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()
