import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from socket import AF_INET, SOCK_STREAM, socket
from typing import TextIO

import pytest
from playwright.sync_api import Browser, sync_playwright

from app.services.model_metadata import (
    MODEL_METADATA_CACHE_NAME,
    MODEL_METADATA_SNAPSHOT_PATH,
)
from tests.e2e.browser_support import browser_session
from tests.e2e.diagnostics import DIAGNOSTICS, SERVER_LOGS, BrowserDiagnostics
from tests.runtime_environment import runtime_environment

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
FRONTEND_ROOT = REPOSITORY_ROOT / "frontend"


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    artifacts_dir = os.environ.get("E2E_ARTIFACTS_DIR")
    if not artifacts_dir:
        return
    try:
        diagnostics = BrowserDiagnostics(Path(artifacts_dir), item.nodeid)
    except OSError as error:
        item.add_report_section("setup", "browser diagnostics", str(error))
        return
    item.stash[DIAGNOSTICS] = diagnostics
    module = item.getparent(pytest.Module)
    if module is not None:
        module.stash[DIAGNOSTICS] = diagnostics


@pytest.fixture(autouse=True)
def browser_diagnostics(request: pytest.FixtureRequest) -> Iterator[None]:
    diagnostics = request.node.stash.get(DIAGNOSTICS, None)
    if diagnostics is None:
        yield
        return
    with pytest.MonkeyPatch.context() as monkeypatch:
        diagnostics.install(monkeypatch)
        try:
            yield
        finally:
            diagnostics.finish_open_contexts()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo):
    outcome = yield
    report = outcome.get_result()
    diagnostics = item.stash.get(DIAGNOSTICS, None)
    if diagnostics is None:
        return
    diagnostics.report(report)
    if report.failed:
        module = item.getparent(pytest.Module)
        if module is not None:
            diagnostics.copy_logs(module.stash.get(SERVER_LOGS, {}))
    if report.when == "teardown":
        diagnostics.finish()


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


@pytest.fixture(scope="session")
def vite_cache_directory() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="reseno-vite-e2e-") as cache_dir:
        yield Path(cache_dir)


@pytest.fixture(scope="module")
def workspace_servers(request: pytest.FixtureRequest) -> Iterator[tuple[str, str]]:
    """Start isolated backend/frontend servers and seed one resume."""

    node = shutil.which("node")
    vite_cli = FRONTEND_ROOT / "node_modules" / "vite" / "bin" / "vite.js"
    if node is None or not vite_cli.exists():
        pytest.fail("Install frontend dependencies before running browser E2E tests.")

    frontend_mode = os.getenv("E2E_FRONTEND_MODE", "dev")
    if frontend_mode not in {"dev", "preview"}:
        pytest.fail("E2E_FRONTEND_MODE must be dev or preview.")
    frontend_command = [node, str(vite_cli)]
    if frontend_mode == "preview":
        dist = Path(
            os.getenv("E2E_FRONTEND_DIST_DIR", str(FRONTEND_ROOT / "dist"))
        ).resolve()
        if not all(
            (dist / name).is_file() for name in ("index.html", ".vite/manifest.json")
        ):
            pytest.fail(f"Build the production frontend with a manifest in {dist}.")
        frontend_command.extend(["preview", "--outDir", str(dist)])

    backend_port = _unused_port()
    frontend_port = _unused_port()
    backend_url = f"http://127.0.0.1:{backend_port}"
    frontend_url = f"http://127.0.0.1:{frontend_port}"
    processes: list[subprocess.Popen[str]] = []
    logs: list[TextIO] = []

    with tempfile.TemporaryDirectory(prefix="reseno-route-e2e-") as data_dir:
        data_path = Path(data_dir)
        server_logs = {
            "backend.log": data_path / "backend.log",
            "frontend.log": data_path / "frontend.log",
        }
        module = request.node.getparent(pytest.Module)
        if module is not None:
            module.stash[SERVER_LOGS] = server_logs
        model_metadata_path = data_path / MODEL_METADATA_CACHE_NAME
        model_metadata_path.parent.mkdir(parents=True)
        model_metadata_snapshot = json.loads(
            MODEL_METADATA_SNAPSHOT_PATH.read_text(encoding="utf-8")
        )
        fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
        for catalog in model_metadata_snapshot["catalogs"].values():
            catalog["fetchedAt"] = fetched_at
        model_metadata_path.write_text(
            json.dumps(model_metadata_snapshot), encoding="utf-8"
        )
        backend_env = {
            **os.environ,
            **runtime_environment(data_path),
            "FRONTEND_RENDER_BASE_URL": frontend_url,
            "BACKEND_CORS_ORIGINS": frontend_url,
        }
        frontend_env = {
            **os.environ,
            "RESENO_VITE_CACHE_DIR": str(
                request.getfixturevalue("vite_cache_directory")
            ),
            "VITE_DEV_API_TARGET": backend_url,
        }

        try:
            backend_log = server_logs["backend.log"].open(mode="w+", encoding="utf-8")
            logs.append(backend_log)
            backend_process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:create_app",
                    "--factory",
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
            browser_session.update(
                {
                    "username": str(setup_payload["username"]),
                    "accessToken": access_token,
                    "expiresAt": str(setup_payload["expiresAt"]),
                }
            )

            frontend_log = server_logs["frontend.log"].open(mode="w+", encoding="utf-8")
            logs.append(frontend_log)
            frontend_process = subprocess.Popen(
                [
                    *frontend_command,
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
                data=b'{"documentLocale":"en"}',
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
            diagnostics = request.node.stash.get(DIAGNOSTICS, None)
            if diagnostics is not None:
                diagnostics.copy_logs(server_logs)
            for log in logs:
                log.close()
            browser_session.clear()


@pytest.fixture(scope="module")
def browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        instance = playwright.chromium.launch(headless=True)
        try:
            yield instance
        finally:
            instance.close()
