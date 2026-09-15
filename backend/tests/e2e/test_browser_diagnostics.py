import json
import os
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

import pytest

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def test_browser_diagnostics_preserve_failures_after_contexts_close(tmp_path: Path):
    probe = tmp_path / "test_probe.py"
    probe.write_text(
        """import pytest
from tests.e2e.diagnostics import DIAGNOSTICS, SERVER_LOGS

@pytest.fixture(autouse=True)
def server_logs(request, tmp_path):
    log = tmp_path / "server.log"
    log.write_text("synthetic server output")
    request.node.getparent(pytest.Module).stash[SERVER_LOGS] = {"backend.log": log}

def test_pass(browser, request):
    page = browser.new_page()
    page.set_content("<h1>Successful probe</h1>")
    page.close()
    directory = request.node.stash[DIAGNOSTICS].directory
    assert list(directory.glob("*.png"))
    assert list(directory.glob("*-trace.zip"))

def test_diagnostic_error_pass(browser, monkeypatch):
    page = browser.new_page()
    def broken_screenshot(**kwargs):
        raise RuntimeError("synthetic screenshot failure")
    monkeypatch.setattr(page, "screenshot", broken_screenshot)
    page.close()

def test_call_failure(browser):
    context = browser.new_context()
    page = context.new_page()
    try:
        page.set_content("<h1>Failed probe</h1>")
        with page.expect_event("pageerror"):
            page.evaluate("setTimeout(() => { throw Error('synthetic page error') })")
        pytest.fail("intended call failure")
    finally:
        context.close()

def test_page_failure(browser):
    page = browser.new_page()
    try:
        page.set_content("<h1>Owned context</h1>")
        pytest.fail("intended page failure")
    finally:
        page.close()

@pytest.fixture
def broken_setup(browser):
    context = browser.new_context()
    page = context.new_page()
    page.set_content("<h1>Setup failure</h1>")
    context.close()
    pytest.fail("intended setup failure")

def test_setup_failure(broken_setup):
    pass

@pytest.fixture
def broken_teardown(browser):
    context = browser.new_context()
    page = context.new_page()
    page.set_content("<h1>Teardown failure</h1>")
    yield page
    context.close()
    pytest.fail("intended teardown failure")

def test_teardown_failure(broken_teardown):
    assert broken_teardown.locator("h1").inner_text() == "Teardown failure"
""",
        encoding="utf-8",
    )
    async_probe = tmp_path / "test_probe_async.py"
    async_probe.write_text(
        """import asyncio
import pytest
from playwright.async_api import async_playwright

def test_async_failure():
    async def scenario():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context()
                page = await context.new_page()
                await page.set_content("<h1>Async failure</h1>")
                pytest.fail("intended async failure")
            finally:
                await browser.close()
    asyncio.run(scenario())
""",
        encoding="utf-8",
    )
    artifacts = tmp_path / "artifacts"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-p",
            "tests.conftest",
            "-p",
            "tests.e2e.conftest",
            "-p",
            "no:cacheprovider",
            "-q",
            str(probe),
            str(async_probe),
        ],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "E2E_ARTIFACTS_DIR": str(artifacts)},
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    directories = list(artifacts.iterdir())
    assert len(directories) == 5, result.stdout + result.stderr
    for name in ("call", "page", "setup", "teardown", "async"):
        directory = next(
            path for path in directories if f"test_{name}_failure" in path.name
        )
        assert list(directory.glob("*.png")), directory
        traces = list(directory.glob("*-trace.zip"))
        assert traces, directory
        for trace in traces:
            with ZipFile(trace) as archive:
                assert archive.testzip() is None
                assert any(name.endswith(".trace") for name in archive.namelist())
        assert not (directory / "diagnostics-errors.txt").exists(), directory
        if name != "async":
            assert (directory / "backend.log").read_text() == "synthetic server output"
        if name == "call":
            errors = json.loads((directory / "page-errors.json").read_text())
            assert any("synthetic page error" in error["message"] for error in errors)
        phase = name if name in {"setup", "teardown"} else "call"
        failure = (directory / f"{phase}-failure.txt").read_text()
        assert f"intended {name} failure" in failure
