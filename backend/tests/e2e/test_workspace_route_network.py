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
from typing import TextIO
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Page, Request, Route, sync_playwright
from playwright.sync_api import Error as PlaywrightError

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
FRONTEND_ROOT = REPOSITORY_ROOT / "frontend"


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
            "APP_ENV": "development",
            "FRONTEND_RENDER_BASE_URL": frontend_url,
            "BACKEND_CORS_ORIGINS": frontend_url,
        }
        frontend_env = {
            **os.environ,
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
                headers={"Content-Type": "application/json"},
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


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(headless=True)
        except PlaywrightError:
            # Local development often already has Chrome while the optional
            # Playwright-managed browser bundle has not been downloaded.
            instance = playwright.chromium.launch(channel="chrome", headless=True)
        try:
            yield instance
        finally:
            instance.close()


ApiRequest = tuple[str, str]


def _api_request(request: Request) -> ApiRequest | None:
    path = urlparse(request.url).path
    if not path.startswith("/api/"):
        return None
    return request.method, path


def _observe_api_requests(browser: Browser, url: str) -> list[ApiRequest]:
    context = browser.new_context()
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
                'main main a[href^="/resume/"]',
              );
              const resumeDetail = visibleElement(
                ".resume-workspace .resume-preview-card article.resume-page",
              );
              const resumePreviewFrame = visibleElement(
                ".resume-workspace .resume-preview-scale-frame",
              );
              const templateGallery = visibleElement(
                'main main a[href="/template/minimal"]',
              );
              const templateDetail = visibleElement(
                ".template-workspace .resume-preview-card article.resume-page",
              );
              const trashContent = visibleElement(
                'main main section [data-slot="tabs-trigger"]',
              );
              const modelsContent = visibleElement(
                'main main [data-slot="empty-title"]',
              );
              const settingsContent = visibleElement(
                'main main [data-slot="tabs-trigger"][data-state="active"]',
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
                hasResumeDetail: Boolean(resumeDetail),
                resumePreviewFits,
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
        ("/resume", [("GET", "/api/workspace/pages/resumes")]),
        ("/templates", [("GET", "/api/workspace/pages/templates")]),
        ("/template/minimal", [("GET", "/api/workspace/pages/templates")]),
        ("/trash", [("GET", "/api/workspace/pages/trash")]),
        ("/models", [("GET", "/api/workspace/pages/models")]),
        ("/settings", [("GET", "/api/workspace/pages/settings")]),
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
        ("GET", "/api/workspace/pages/resume-editor"),
        ("GET", f"/api/resumes/{resume_id}"),
        ("GET", f"/api/resumes/{resume_id}/versions"),
    ]
    actual_paths = _observe_api_requests(
        browser,
        f"{frontend_url}/resume/{resume_id}",
    )

    assert Counter(actual_paths) == Counter(expected_paths)


def test_resume_navigation_keeps_cached_views_mounted_and_preview_fits(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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
            frame
            for frame in detail_frames
            if frame["path"] == f"/resume/{resume_id}"
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


def test_template_navigation_keeps_cached_views_mounted(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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
            frame
            for frame in detail_frames
            if frame["path"] == "/template/minimal"
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
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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
        routed_frames = [
            frame for frame in frames if frame["path"] == target_route
        ]

        assert len(routed_frames) >= 2
        _assert_visible_once_mounted(routed_frames, frame_key)
    finally:
        context.close()


def test_pdf_export_route_request_allowlist(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    expected_paths = [
        ("GET", "/api/workspace/pages/templates"),
        ("GET", f"/api/resumes/{resume_id}"),
    ]
    actual_paths = _observe_api_requests(
        browser,
        f"{frontend_url}/pdf-export?resumeId={resume_id}&locale=en",
    )

    assert Counter(actual_paths) == Counter(expected_paths)
