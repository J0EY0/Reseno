from __future__ import annotations

import json
import os
import time

import pytest
from playwright.sync_api import Browser, Request, Route, expect

from tests.e2e.browser_support import browser_session
from tests.e2e.workspace_frame_support import (
    install_workspace_frame_recorder,
    start_workspace_frame_recording,
    stop_workspace_frame_recording,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_password_login_preserves_button_content_and_keeps_success_handoff_locked(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(
        viewport={"width": 375, "height": 812}, locale="en-US"
    )
    page = context.new_page()
    login_requests: list[Request] = []
    pending_routes: list[Route] = []

    def submit_login(route: Route) -> None:
        login_requests.append(route.request)
        if len(login_requests) == 1:
            pending_routes.append(route)
            return
        route.continue_()

    page.route("**/api/auth/login", submit_login)

    try:
        page.goto(f"{frontend_url}/login", wait_until="networkidle")
        github_button = page.get_by_role(
            "button", name="Continue with GitHub", exact=True
        )
        password_button = page.locator('form button[type="submit"]')
        loading_buttons = page.locator("form button.auth-loading-button")
        expect(loading_buttons).to_have_count(2)
        loading_sweeps = loading_buttons.locator(".auth-loading-sweep")
        expect(loading_sweeps).to_have_count(2)
        password_sweep = password_button.locator(".auth-loading-sweep")
        github_sweep = github_button.locator(".auth-loading-sweep")
        expect(password_sweep).to_have_attribute("aria-hidden", "true")
        expect(github_sweep).to_have_attribute("aria-hidden", "true")
        expect(password_sweep).to_have_css("opacity", "0")
        expect(github_sweep).to_have_css("opacity", "0")
        input_borders = page.locator('form [data-slot="input-group"]')
        expect(input_borders).to_have_count(2)
        password_spinner = password_button.locator(
            '[data-slot="auth-pending-indicator"]'
        )
        github_spinner = github_button.locator('[data-slot="auth-pending-indicator"]')
        pending_announcement = page.locator(
            'form > [data-slot="field-group"] > [data-slot="auth-pending-announcement"]'
        )
        page.locator("#username").fill("e2e-owner")
        page.locator("#password").fill("E2ePassword2026")
        initial_bounds = password_button.bounding_box()
        assert initial_bounds is not None
        initial_github_bounds = github_button.bounding_box()
        assert initial_github_bounds is not None

        page.clock.install()
        page.clock.pause_at(page.evaluate("Date.now()") / 1_000)
        password_button.click()

        expect(password_button).to_be_disabled()
        expect(password_button).to_have_js_property("disabled", True)
        expect(github_button).to_be_disabled()
        expect(github_button).to_have_js_property("disabled", True)
        expect(password_button).to_have_attribute("aria-disabled", "true")
        expect(github_button).to_have_attribute("aria-disabled", "true")
        expect(password_button).to_have_attribute("aria-busy", "true")
        expect(github_button).not_to_have_attribute("aria-busy", "true")
        expect(password_button).to_have_text("Sign In")
        expect(password_spinner).to_have_count(0)
        expect(github_spinner).to_have_count(0)
        expect(pending_announcement).to_have_attribute("aria-live", "polite")
        assert pending_announcement.text_content()

        page.clock.run_for(150)
        expect(password_spinner).to_have_count(0)
        assert pending_announcement.text_content()
        page.clock.run_for(100)
        expect(password_spinner).to_have_count(0)
        expect(github_spinner).to_have_count(0)
        assert pending_announcement.text_content()
        expect(password_button).to_have_text("Sign In")
        pending_bounds = password_button.bounding_box()
        assert pending_bounds == initial_bounds
        assert github_button.bounding_box() == initial_github_bounds
        page.clock.resume()
        expect(password_button).to_have_css("opacity", "1")
        expect(github_button).to_have_css("opacity", "0.5")
        expect(password_sweep).to_have_css("opacity", "1")
        expect(github_sweep).to_have_css("opacity", "0")
        sweep_style = password_sweep.evaluate(
            """
            element => {
              const style = getComputedStyle(element, '::after')
              return {
                animation: style.animationName,
                iterations: style.animationIterationCount,
                playState: style.animationPlayState,
                transform: style.transform,
              }
            }
            """
        )
        assert sweep_style["animation"] != "none", sweep_style
        assert sweep_style["iterations"] == "infinite", sweep_style
        assert sweep_style["playState"] == "running", sweep_style
        assert (
            github_sweep.evaluate(
                "element => getComputedStyle(element, '::after').animationPlayState"
            )
            == "paused"
        )
        assert input_borders.evaluate_all(
            """
            elements => elements.map(element => {
              const style = getComputedStyle(element, '::after')
              return [style.animationName, style.content, style.backgroundImage]
            })
            """
        ) == [["none", "none", "none"], ["none", "none", "none"]]
        page.wait_for_function(
            """
            previous => getComputedStyle(document.querySelector(
              'form button[type="submit"] .auth-loading-sweep'
            ), '::after').transform !== previous
            """,
            arg=sweep_style["transform"],
        )
        page.emulate_media(reduced_motion="reduce")
        expect(password_sweep).to_have_css("opacity", "1")
        assert loading_sweeps.evaluate_all(
            """
            elements => elements.map(element => {
              const style = getComputedStyle(element, '::after')
              return style.animationName
            })
            """
        ) == ["none", "none"]
        reduced_style = password_sweep.evaluate(
            """
            element => {
              const style = getComputedStyle(element, '::after')
              return {
                transform: style.transform,
                background: style.backgroundImage,
                display: style.display,
                visibility: style.visibility,
                opacity: style.opacity,
              }
            }
            """
        )
        assert reduced_style["transform"] == "none", reduced_style
        assert "linear-gradient(" in reduced_style["background"], reduced_style
        assert reduced_style["display"] != "none", reduced_style
        assert reduced_style["visibility"] == "visible", reduced_style
        assert float(reduced_style["opacity"]) > 0, reduced_style
        expect(github_sweep).to_have_css("opacity", "0")
        page.emulate_media(reduced_motion="no-preference")

        pending_routes.pop().fulfill(
            status=503, json={"detail": {"code": "REQUEST_FAILED"}}
        )
        page.clock.resume()
        expect(
            page.get_by_text("Request failed. Please try again later.", exact=True)
        ).to_be_visible()
        expect(password_button).to_be_enabled()
        expect(password_button).to_have_js_property("disabled", False)
        expect(github_button).to_be_enabled()
        expect(github_button).to_have_js_property("disabled", False)
        expect(password_button).not_to_have_attribute("aria-busy", "true")
        expect(password_spinner).to_have_count(0)
        expect(github_spinner).to_have_count(0)
        expect(pending_announcement).to_have_text("")
        expect(password_sweep).to_have_css("opacity", "0")
        expect(github_sweep).to_have_css("opacity", "0")
        assert loading_sweeps.evaluate_all(
            "elements => elements.map(element => "
            "getComputedStyle(element, '::after').animationPlayState)"
        ) == ["paused", "paused"]
        paused_positions = loading_sweeps.evaluate_all(
            "elements => elements.map(element => "
            "getComputedStyle(element, '::after').transform)"
        )
        page.wait_for_timeout(80)
        assert (
            loading_sweeps.evaluate_all(
                "elements => elements.map(element => "
                "getComputedStyle(element, '::after').transform)"
            )
            == paused_positions
        )
        expect(password_button).to_have_text("Sign In")
        expect(page.locator("#username")).to_have_value("e2e-owner")
        expect(page.locator("#password")).to_have_value("E2ePassword2026")

        page.evaluate(
            """
            () => {
              const password = document.querySelector('form button[type="submit"]')
              const github = document.querySelector(
                '[aria-label="Continue with GitHub"]'
              )
              const states = []
              const record = () => {
                states.push({
                  github: github?.disabled,
                  password: password?.disabled,
                })
                window.name = JSON.stringify(states)
              }
              record()
              new MutationObserver(() => queueMicrotask(record)).observe(
                document.body,
                {
                  attributes: true,
                  subtree: true,
                  attributeFilter: ['disabled'],
                },
              )
            }
            """
        )
        password_button.click()
        page.wait_for_url(f"{frontend_url}/resume")
        handoff_states = json.loads(page.evaluate("window.name"))
        for key in ("password", "github"):
            first_locked = next(
                index for index, state in enumerate(handoff_states) if state[key]
            )
            assert all(state[key] for state in handoff_states[first_locked:]), (
                handoff_states
            )
        assert len(login_requests) == 2
    finally:
        context.close()


def test_password_login_mounts_complete_gallery_with_workspace_shell(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(
        locale="en-US", viewport={"width": 1280, "height": 800}
    )
    page = context.new_page()
    module_routes: list[Route] = []
    data_routes: list[Route] = []
    destination_module = (
        "**/src/components/workspace/resume-gallery-workspace-page.tsx*"
    )
    install_workspace_frame_recorder(page)
    page.route(destination_module, lambda route: module_routes.append(route))
    page.route(
        "**/api/workspace/pages/resumes*", lambda route: data_routes.append(route)
    )

    try:
        page.goto(f"{frontend_url}/login", wait_until="domcontentloaded")
        page.locator("#username").fill("e2e-owner")
        page.locator("#password").fill("E2ePassword2026")
        start_workspace_frame_recording(page)
        page.locator('form button[type="submit"]').click()

        deadline = time.monotonic() + 5
        while not module_routes and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert len(module_routes) == 1
        page.evaluate(
            """
            () => new Promise(resolve => {
              requestAnimationFrame(() => requestAnimationFrame(resolve));
            })
            """
        )
        module_routes.pop().continue_()

        deadline = time.monotonic() + 5
        while not data_routes and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert len(data_routes) == 1
        page.evaluate(
            """
            async () => {
              for (let frame = 0; frame < 6; frame += 1) {
                await new Promise(requestAnimationFrame);
              }
            }
            """
        )
        data_routes.pop().continue_()

        page.wait_for_url(f"{frontend_url}/resume")
        expect(page.locator('input[name="resume-search"]')).to_be_visible()
        page.evaluate(
            """
            () => new Promise(resolve => {
              requestAnimationFrame(() => requestAnimationFrame(resolve));
            })
            """
        )
        frames = stop_workspace_frame_recording(page)
        resume_frames = [frame for frame in frames if frame["path"] == "/resume"]
        timeline: list[dict[str, object]] = []
        for frame in frames:
            state = {
                key: frame[key]
                for key in (
                    "path",
                    "hasResumeGallery",
                    "hasLogin",
                    "hasAuthCard",
                    "hasEntrySkeleton",
                    "hasRouteSkeleton",
                    "hasAppFallback",
                    "hasSidebar",
                )
            }
            if not timeline or state != timeline[-1]:
                timeline.append(state)
        diagnostics = json.dumps(
            {
                "entry": "password",
                "timeline": timeline,
                "resumeFrames": len(resume_frames),
                "skeletonFrames": sum(
                    bool(frame["hasRouteSkeleton"]) for frame in resume_frames
                ),
            }
        )
        assert resume_frames, diagnostics
        assert not any(frame["hasAppFallback"] for frame in frames), diagnostics
        first_workspace_frame = next(
            index for index, frame in enumerate(frames) if frame["hasSidebar"]
        )
        assert all(
            frame["path"] == "/resume"
            and frame["hasSidebar"]
            and frame["hasResumeGallery"]
            and not frame["hasRouteSkeleton"]
            and not frame["hasEntrySkeleton"]
            and not frame["hasLogin"]
            for frame in frames[first_workspace_frame:]
        ), diagnostics
        page.screenshot(path="/tmp/reseno-login-entry-password.png")
    finally:
        context.close()


def test_setup_entry_retries_gallery_without_repeating_authentication(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    session = browser_session
    assert session
    auth_payload = {
        "username": session["username"],
        "accessToken": session["accessToken"],
        "expiresAt": session["expiresAt"],
        "tokenType": "bearer",
    }
    context = browser.new_context(locale="en-US")
    page = context.new_page()
    auth_requests: list[Request] = []
    data_requests: list[Request] = []
    fail_data = True

    def authenticate(route: Route) -> None:
        if route.request.method == "GET":
            data = {
                "setupRequired": not auth_requests,
                "githubLoginAvailable": False,
            }
        else:
            auth_requests.append(route.request)
            data = auth_payload
        route.fulfill(json={"code": 0, "message": "OK", "data": data})

    def load_gallery(route: Route) -> None:
        data_requests.append(route.request)
        if fail_data:
            route.fulfill(status=503, json={"detail": {"code": "REQUEST_FAILED"}})
        else:
            route.continue_()

    page.route("**/api/auth/setup", authenticate)
    page.route("**/api/workspace/pages/resumes*", load_gallery)

    try:
        page.goto(f"{frontend_url}/setup", wait_until="domcontentloaded")
        page.locator("#setup-username").fill("e2e-owner")
        page.locator("#setup-password").fill("E2ePassword2026")
        page.locator("#setup-confirm-password").fill("E2ePassword2026")
        page.get_by_role("button", name="Create and Continue", exact=True).click()

        page.wait_for_url(f"{frontend_url}/resume")
        retry_button = page.get_by_role("button", name="Retry", exact=True)
        expect(retry_button).to_be_visible()
        expect(page.locator('[data-slot="sidebar-container"]')).to_be_visible()
        expect(page.locator('[data-slot="workspace-entry-skeleton"]')).to_have_count(0)
        expect(page.locator("#username, #setup-username")).to_have_count(0)
        assert len(auth_requests) == 1
        assert auth_requests[0].method == "POST"
        assert len(data_requests) >= 2

        previous_data_requests = len(data_requests)
        fail_data = False
        retry_button.click()
        expect(page.locator('input[name="resume-search"]')).to_be_visible()
        expect(retry_button).to_have_count(0)
        assert page.url == f"{frontend_url}/resume"
        assert len(data_requests) == previous_data_requests + 1
        assert len(auth_requests) == 1
    finally:
        context.close()


def test_password_login_recovers_when_session_is_lost_during_gallery_preparation(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(locale="en-US")
    page = context.new_page()
    data_routes: list[Route] = []
    page.route(
        "**/api/workspace/pages/resumes*", lambda route: data_routes.append(route)
    )

    try:
        page.goto(f"{frontend_url}/login", wait_until="domcontentloaded")
        page.locator("#username").fill("e2e-owner")
        page.locator("#password").fill("E2ePassword2026")
        password_button = page.locator('form button[type="submit"]')
        github_button = page.get_by_role(
            "button", name="Continue with GitHub", exact=True
        )
        with page.expect_request("**/api/workspace/pages/resumes*"):
            password_button.click()
        deadline = time.monotonic() + 3
        while not data_routes and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert len(data_routes) == 1
        expect(password_button).to_be_disabled()
        expect(github_button).to_be_disabled()
        page.evaluate("localStorage.removeItem('reseno-auth-session')")
        data_routes.pop().continue_()

        expect(password_button).to_be_enabled()
        expect(password_button).not_to_have_attribute("aria-busy", "true")
        expect(github_button).to_be_enabled()
        expect(
            page.get_by_text("Request failed. Please try again later.", exact=True)
        ).to_be_visible()
        assert page.url == f"{frontend_url}/login"
        assert page.evaluate("localStorage.getItem('reseno-auth-session')") is None
        expect(page.locator('[data-slot="sidebar-container"]')).to_have_count(0)

        page.unroute("**/api/workspace/pages/resumes*")
        password_button.click()
        page.wait_for_url(f"{frontend_url}/resume")
        expect(page.locator('input[name="resume-search"]')).to_be_visible()
    finally:
        context.close()
