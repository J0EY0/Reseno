from __future__ import annotations

import json
import os
import re
import time
from collections import Counter
from urllib.parse import urlparse

import pytest
from playwright.sync_api import APIResponse, Browser, Request, Route, expect

from tests.e2e.browser_support import RouteReady
from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_workspace_load_error_can_retry_same_route(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1280, "height": 800}
    )
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
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1280, "height": 800}
    )
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
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1280, "height": 800}
    )
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


def test_resume_card_preloads_detail_module_and_reports_local_pending(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1280, "height": 800})
    page = context.new_page()
    requests: list[tuple[str, str]] = []
    page.on(
        "request",
        lambda request: requests.append((request.method, urlparse(request.url).path)),
    )

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        requests.clear()
        resume_link = page.locator(f'a[href="/resume/{resume_id}"]')

        resume_link.focus()
        page.wait_for_timeout(300)

        assert any("resume-detail-workspace-page" in path for _, path in requests), (
            requests
        )
        assert not any(
            path == "/api/workspace/pages/resume-editor"
            or path == f"/api/resumes/{resume_id}"
            or path == f"/api/resumes/{resume_id}/versions"
            for _, path in requests
        ), requests

        page.evaluate(
            """
            () => {
              const originalFetch = window.fetch.bind(window);
              window.__releaseResumeDetailRoute = null;
              window.fetch = async (input, init) => {
                const request = new Request(input, init);
                if (
                  new URL(request.url).pathname ===
                  "/api/workspace/pages/resume-editor"
                ) {
                  await new Promise((resolve) => {
                    window.__releaseResumeDetailRoute = resolve;
                  });
                }
                return originalFetch(input, init);
              };
            }
            """
        )

        resume_link.click()
        page.wait_for_function("window.__releaseResumeDetailRoute !== null")

        expect(resume_link).to_have_attribute("aria-busy", "true")
        assert resume_link.get_by_role("status").count() == 0
        assert page.url == f"{frontend_url}/resume"

        page.evaluate("window.__releaseResumeDetailRoute()")
        page.wait_for_url(f"{frontend_url}/resume/{resume_id}")
        page.locator(".resume-preview-card article.resume-page").wait_for(
            state="visible"
        )
    finally:
        context.close()


@pytest.mark.parametrize("locale", ["zh", "en"])
@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
def test_created_resume_is_not_published_before_detail_is_ready(
    browser: Browser,
    workspace_servers: tuple[str, str],
    locale: str,
    reduced_motion: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN" if locale == "zh" else "en-US",
        viewport={"width": 1280, "height": 800},
        reduced_motion=reduced_motion,
    )
    context.add_init_script(f"localStorage.setItem('reseno-locale', '{locale}')")
    page = context.new_page()
    created_resume_id: str | None = None
    create_requests: list[Request] = []
    page.on(
        "request",
        lambda request: (
            create_requests.append(request)
            if request.method == "POST" and urlparse(request.url).path == "/api/resumes"
            else None
        ),
    )

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        initial_card_count = page.locator('a[href^="/resume/"]').count()
        page.evaluate(
            """
            () => {
              const originalFetch = window.fetch.bind(window);
              window.__releaseCreatedResumeDetail = null;
              window.fetch = async (input, init) => {
                const request = new Request(input, init);
                if (
                  new URL(request.url).pathname ===
                  "/api/workspace/pages/resume-editor"
                ) {
                  await new Promise((resolve) => {
                    window.__releaseCreatedResumeDetail = resolve;
                  });
                }
                return originalFetch(input, init);
              };
            }
            """
        )

        create_button = page.get_by_role(
            "button",
            name=re.compile(r"^(New|新建)$"),
        ).first
        create_button.click()
        create_dialog = page.get_by_role("dialog")
        create_dialog.get_by_role(
            "combobox",
            name=re.compile(r"^(Resume language|简历语言)$"),
        ).click()
        page.get_by_role("option", name=re.compile(r"^(English|英文)$")).click()
        selected_template_id = (
            create_dialog.locator("#new-resume-template")
            .locator("xpath=..")
            .locator("select")
            .input_value()
        )
        assert selected_template_id
        submit = create_dialog.get_by_role(
            "button", name=re.compile(r"^(Create Resume|创建简历)$")
        )
        submit.hover()
        submit.evaluate(
            """async button => {
              await Promise.all(button.getAnimations().map(
                animation => animation.finished.catch(() => {})
              ));
              window.__createButtonFrames = [];
              window.__recordCreateButton = true;
              const sample = () => {
                if (!window.__recordCreateButton) return;
                const rect = button.getBoundingClientRect();
                const style = getComputedStyle(button);
                window.__createButtonFrames.push({
                  text: button.textContent,
                  width: rect.width,
                  height: rect.height,
                  opacity: style.opacity,
                  hasSpinner: !!button.querySelector('[role="status"], .animate-spin'),
                });
                requestAnimationFrame(sample);
              };
              sample();
            }"""
        )
        before = page.evaluate("window.__createButtonFrames[0]")
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlparse(response.url).path == "/api/resumes"
            )
        ) as create_response_info:
            submit.click()
        assert create_response_info.value.request.post_data_json == {
            "documentLocale": "en",
            "template": selected_template_id,
        }
        created_resume_id = str(
            create_response_info.value.json()["data"]["resume"]["id"]
        )
        page.wait_for_function("window.__releaseCreatedResumeDetail !== null")

        expect(submit).to_have_attribute("aria-disabled", "true")
        assert not submit.evaluate("button => button.disabled")
        box = submit.bounding_box()
        assert box is not None
        page.mouse.dblclick(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        expect(submit).to_be_focused()
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        page.evaluate(
            """() => new Promise(resolve => requestAnimationFrame(
              () => requestAnimationFrame(resolve)
            ))"""
        )
        frames = page.evaluate("window.__createButtonFrames")
        assert len(frames) > 1
        assert before["text"] == ("创建简历" if locale == "zh" else "Create Resume")
        assert before["opacity"] == "1"
        assert not before["hasSpinner"]
        assert all(frame == before for frame in frames), frames
        assert len(create_requests) == 1

        pending_create_button = page.locator('button[aria-busy="true"]')
        expect(pending_create_button).to_have_count(1)
        assert pending_create_button.inner_text() in {"New", "新建"}
        assert pending_create_button.get_attribute("aria-label") in {
            "Creating…",
            "创建中…",
        }
        assert pending_create_button.locator('[role="status"]').count() == 0
        assert page.locator('a[href^="/resume/"]').count() == initial_card_count
        assert page.url == f"{frontend_url}/resume"

        page.evaluate(
            """() => {
              window.__recordCreateButton = false;
              window.__releaseCreatedResumeDetail();
            }"""
        )
        page.wait_for_url(f"{frontend_url}/resume/*")
        page.locator(".resume-preview-card article.resume-page").wait_for(
            state="visible"
        )
        assert len(create_requests) == 1
    finally:
        if created_resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{created_resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{created_resume_id}")
        context.close()


def test_lateral_navigation_stays_on_current_page_when_preparation_fails(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1280, "height": 800}
    )
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


def test_lateral_navigation_reports_pending_and_preserves_workspace_shell(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1280, "height": 800})
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.evaluate(
            """
            () => {
              const originalFetch = window.fetch.bind(window);
              window.__releaseModelsRoute = null;
              window.__workspaceSidebarBeforeNavigation = document.querySelector(
                '[data-slot="sidebar-container"]',
              );
              window.fetch = async (input, init) => {
                const request = new Request(input, init);
                if (new URL(request.url).pathname === "/api/workspace/pages/models") {
                  await new Promise((resolve) => {
                    window.__releaseModelsRoute = resolve;
                  });
                }
                return originalFetch(input, init);
              };
            }
            """
        )

        models_link = page.locator('a[href="/models"]')
        models_link.click()
        page.wait_for_function("window.__releaseModelsRoute !== null")

        expect(models_link).to_have_attribute("aria-busy", "true")
        assert models_link.get_by_role("status").count() == 0
        assert page.url == f"{frontend_url}/resume"
        assert page.locator('input[name="resume-search"]').is_visible()

        page.evaluate("window.__releaseModelsRoute()")
        page.wait_for_url(f"{frontend_url}/models")
        route_stage = page.locator(
            '.workspace-route-stage[data-workspace-view="models"]'
        )
        route_stage.wait_for(state="attached")
        assert (
            route_stage.evaluate("element => getComputedStyle(element).animationName")
            == "workspace-route-enter"
        )
        assert (
            route_stage.evaluate(
                "element => getComputedStyle(element).animationDuration"
            )
            == "0.18s"
        )
        page.locator('[data-slot="empty-description"]').wait_for(state="visible")

        assert (
            page.evaluate(
                """
            () => window.__workspaceSidebarBeforeNavigation ===
              document.querySelector('[data-slot="sidebar-container"]')
            """
            )
            is True
        )
    finally:
        context.close()


@pytest.mark.browser_smoke
def test_sidebar_navigation_during_route_commit_keeps_latest_destination(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1440, "height": 900}
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/settings", wait_until="networkidle")
        page.evaluate(
            """
            () => {
              const pushState = history.pushState;
              history.pushState = function (...args) {
                const result = pushState.apply(this, args);
                if (location.pathname === "/resume") {
                  history.pushState = pushState;
                  setTimeout(() => {
                    document.querySelector('a[href="/templates"]').click();
                  }, 0);
                }
                return result;
              };
            }
            """,
        )
        page.locator('a[href="/resume"]').click()
        page.wait_for_url(f"{frontend_url}/templates", timeout=5_000)
        expect(page.locator('[data-workspace-view="templates"]')).to_be_visible()
        expect(page.locator('a[href="/templates"]')).to_have_attribute(
            "aria-current", "page"
        )
        page.wait_for_function("history.state.usr === null")
        assert page.url == f"{frontend_url}/templates"

        page.go_back()
        page.wait_for_url(f"{frontend_url}/resume")
        expect(page.locator('input[name="resume-search"]')).to_be_visible()
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
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1280, "height": 800}
    )
    page = context.new_page()
    created_resume_id: str | None = None
    held_create_responses: list[tuple[Route, APIResponse]] = []
    create_ready = RouteReady()

    def delay_create(route: Route) -> None:
        nonlocal created_resume_id
        if route.request.method != "POST":
            route.continue_()
            return
        response = route.fetch()
        assert response.ok
        created_resume_id = response.json()["data"]["resume"]["id"]
        held_create_responses.append((route, response))
        create_ready.set()

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.route("**/api/resumes", delay_create)

        page.get_by_role("button", name="新建", exact=True).click()
        create_dialog = page.get_by_role("dialog")
        create_dialog.get_by_role("combobox", name="简历语言", exact=True).click()
        page.get_by_role("option", name="英文", exact=True).click()
        submit = create_dialog.get_by_role("button", name="创建简历", exact=True)
        submit.click()
        create_ready.wait(page)
        expect(submit).to_have_attribute("aria-disabled", "true")
        create_dialog.get_by_role("button", name="取消", exact=True).click()
        expect(create_dialog).to_have_count(0)
        page.locator('a[href="/models"]').click()
        page.wait_for_url(f"{frontend_url}/models", timeout=5_000)
        expect(page.locator('[data-workspace-view="models"]')).to_be_visible()
        assert len(held_create_responses) == 1

        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlparse(response.url).path == "/api/resumes"
            )
        ) as create_response_info:
            create_route, response = held_create_responses.pop()
            create_route.fulfill(response=response)

        create_response = create_response_info.value
        assert create_response.ok
        assert create_response.json()["data"]["resume"]["id"] == created_resume_id
        page.wait_for_load_state("networkidle")

        assert page.url == f"{frontend_url}/models"
        expect(page.locator('[data-workspace-view="models"]')).to_be_visible()
    finally:
        for create_route, response in held_create_responses:
            create_route.fulfill(response=response)
        if created_resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{created_resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{created_resume_id}")
        context.close()


@pytest.mark.parametrize(
    ("retry_delay_ms", "dismiss_error", "reduced_motion"),
    [
        pytest.param(0, False, "no-preference", id="immediate"),
        pytest.param(80, False, "no-preference", id="during-exit"),
        pytest.param(0, True, "no-preference", id="dismissed"),
        pytest.param(80, False, "reduce", id="reduced-motion"),
    ],
)
def test_resume_detail_retry_owns_a_single_error_notification(
    browser: Browser,
    workspace_servers: tuple[str, str],
    retry_delay_ms: int,
    dismiss_error: bool,
    reduced_motion: str,
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        reduced_motion=reduced_motion,
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()
    held_load_routes: list[Route] = []
    failed_responses: list[tuple[str, int]] = []
    page.on(
        "response",
        lambda response: (
            failed_responses.append((urlparse(response.url).path, response.status))
            if response.status == 503
            else None
        ),
    )

    def fail_pending_load(delay_ms: int = 0) -> None:
        deadline = time.monotonic() + 3
        while len(held_load_routes) < 2 and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert Counter(
            urlparse(route.request.url).path for route in held_load_routes
        ) == Counter(
            [f"/api/resumes/{resume_id}", "/api/workspace/pages/resume-editor"]
        )
        pending_routes = held_load_routes.copy()
        held_load_routes.clear()
        if delay_ms:
            page.wait_for_timeout(delay_ms)
        for route in pending_routes:
            route.fulfill(status=503, json={"detail": {"code": "REQUEST_FAILED"}})

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.route(
            "**/api/workspace/pages/resume-editor",
            lambda route: held_load_routes.append(route),
        )
        page.route(
            f"**/api/resumes/{resume_id}*",
            lambda route: held_load_routes.append(route),
        )

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="domcontentloaded")
        page.locator('section[aria-relevant="additions text"]').wait_for(
            state="attached"
        )
        fail_pending_load()
        retry_button = page.get_by_role("button", name="重试", exact=True)
        retry_button.wait_for(state="visible")
        error_toasts = page.locator(
            '[data-sonner-toast][data-type="error"]:not([data-removed="true"])'
        )
        error_toasts.first.wait_for(state="visible")
        expect(error_toasts).to_have_count(1)

        if dismiss_error:
            error_toasts.locator("[data-close-button]").click()
        retry_started_at = page.evaluate("performance.now()")
        retry_button.click()
        fail_pending_load(retry_delay_ms)

        assert page.url == f"{frontend_url}/resume/{resume_id}"
        expect(retry_button).to_be_visible()
        toast_frames = page.evaluate(
            """
            async retryStartedAt => {
              const frames = [];
              const startedAt = performance.now();
              let previousToasts = null;
              while (performance.now() - startedAt < 500) {
                const toasts = [...document.querySelectorAll(
                  '[data-sonner-toast][data-type="error"]'
                )].map(toast => ({
                  removed: toast.dataset.removed === 'true',
                  text: toast.textContent,
                }));
                const serialized = JSON.stringify(toasts);
                if (serialized !== previousToasts) {
                  frames.push({
                    elapsedMs: performance.now() - retryStartedAt,
                    toasts,
                  });
                  previousToasts = serialized;
                }
                await new Promise(requestAnimationFrame);
              }
              frames.push({
                elapsedMs: performance.now() - retryStartedAt,
                toasts: JSON.parse(previousToasts),
              });
              return frames;
            }
            """,
            retry_started_at,
        )
        assert Counter(failed_responses) == Counter(
            {
                (f"/api/resumes/{resume_id}", 503): 2,
                ("/api/workspace/pages/resume-editor", 503): 2,
            }
        )
        assert all(
            sum(not toast["removed"] for toast in frame["toasts"]) == 1
            for frame in toast_frames
        ), toast_frames
        expect(error_toasts).to_have_count(1)

        page.unroute("**/api/workspace/pages/resume-editor")
        page.unroute(f"**/api/resumes/{resume_id}*")
        retry_button.click()
        expect(page.locator(".resume-editor-panel")).to_be_visible()
        expect(page.locator(".resume-preview-card article.resume-page")).to_be_visible()
        expect(page.get_by_role("button", name="保存状态", exact=True)).to_be_enabled()
        expect(retry_button).to_have_count(0)
        expect(error_toasts).to_have_count(0)
        expect(page.locator('[data-slot="workspace-preview-skeleton"]')).to_have_count(
            0
        )
    finally:
        context.close()
