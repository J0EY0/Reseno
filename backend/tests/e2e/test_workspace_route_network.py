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
from urllib.parse import parse_qs, urlparse

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


def test_format_reset_restores_current_template_defaults_and_persists(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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
        assert (
            reset_bounds["x"] + reset_bounds["width"]
            <= template_select_bounds["x"]
        )

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
            tooltip_geometry["rect"]["right"]
            <= tooltip_geometry["viewport"]["width"]
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
        assert "思源宋体" in page.get_by_role(
            "combobox",
            name="字体",
            exact=True,
        ).inner_text()
        assert page.get_by_role(
            "textbox",
            name="页边距",
            exact=True,
        ).input_value() == "14"
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
    context = browser.new_context(viewport={"width": 2048, "height": 1226})
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
            data={
                "title": "王小明-zh-minimal（1）-frontend-fullstack-resume-2026"
            },
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
        success_toast = page.locator(
            '[data-sonner-toast][data-type="success"]'
        ).filter(has_text="副本已创建")
        toast_description = success_toast.locator("[data-description]")
        assert toast_description.inner_text() == duplicate_title
        assert toast_description.evaluate(
            "(description) => getComputedStyle(description).whiteSpace"
        ) == "nowrap"
        assert toast_description.evaluate(
            "(description) => getComputedStyle(description).overflow"
        ) == "hidden"
        assert toast_description.evaluate(
            "(description) => getComputedStyle(description).textOverflow"
        ) == "ellipsis"
        assert toast_description.evaluate(
            "(description) => description.scrollWidth > description.clientWidth"
        )
        assert success_toast.locator("[data-icon]").count() == 0
        assert open_copy_action.evaluate(
            "(button) => getComputedStyle(button).backgroundColor"
        ) == "rgba(0, 0, 0, 0)"
        assert open_copy_action.evaluate(
            "(button) => getComputedStyle(button).borderTopWidth"
        ) == "1px"
        assert open_copy_action.evaluate(
            "(button) => getComputedStyle(button).borderTopStyle"
        ) == "solid"
        assert open_copy_action.locator("svg").count() == 0
        close_button = success_toast.locator("[data-close-button]")
        close_shadow_before_hover = close_button.evaluate(
            "(button) => getComputedStyle(button).boxShadow"
        )
        close_button.hover()
        assert close_button.evaluate(
            "(button) => getComputedStyle(button).boxShadow"
        ) == close_shadow_before_hover
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
    context = browser.new_context(viewport={"width": 2048, "height": 1226})
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
    context = browser.new_context(viewport={"width": 1280, "height": 800})
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
        page.get_by_role("button", name="新建", exact=True).wait_for(
            state="visible"
        )
    finally:
        context.close()


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


def test_resume_autosave_persists_edit_made_during_active_save(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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
        persisted_response = page.request.get(
            f"{frontend_url}/api/resumes/{resume_id}"
        )
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
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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
        persisted_response = page.request.get(
            f"{frontend_url}/api/resumes/{resume_id}"
        )
        fallback_title = persisted_response.json()["data"]["resume"]["resume"][
            "basic"
        ]["name"]

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
    context = browser.new_context(
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
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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
                page.request.delete(
                    f"{frontend_url}/api/resumes/{extra_resume_id}"
                )
        context.close()


def test_gallery_pagination_keeps_active_page_clear_of_previous_action(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(viewport={"width": 800, "height": 900})
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
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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
        page.get_by_text("请求失败，请稍后重试", exact=True).wait_for(
            state="visible"
        )

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
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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
        assert save_payloads[-1]["template"]["name"] == (
            "Latest Template During Save"
        )
    finally:
        context.close()


def test_template_return_checks_unsaved_changes_before_navigation(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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
        page.get_by_label("模板名称", exact=True).fill(
            "Template Saved Before Return"
        )
        page.get_by_role(
            "button",
            name="返回模板列表",
            exact=True,
        ).click()

        assert page.url.startswith(f"{frontend_url}/template/template-")
        assert page.get_by_role(
            "heading",
            name="有未保存的更改",
            exact=True,
        ).count() == 1

        page.get_by_role(
            "button",
            name="保存并离开",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/templates")
    finally:
        context.close()


def test_leaving_resume_promotes_completed_autosave_to_checkpoint(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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


def test_checkpoint_failure_after_autosave_does_not_block_leaving_resume(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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

        persisted_response = page.request.get(
            f"{frontend_url}/api/resumes/{resume_id}"
        )
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
    context = browser.new_context(viewport={"width": 1672, "height": 870})
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
        assert page.get_by_role(
            "heading",
            name="有未保存的更改",
            exact=True,
        ).count() == 1

        page.get_by_role(
            "button",
            name="继续编辑",
            exact=True,
        ).click()
        assert page.url == f"{frontend_url}/resume/{resume_id}"
    finally:
        context.close()
