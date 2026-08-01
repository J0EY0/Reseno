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
from playwright.sync_api import Browser, Request, sync_playwright
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
