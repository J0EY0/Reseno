import os
import time
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Browser, Route, expect

from tests.e2e.browser_support import browser_session
from tests.e2e.test_oauth_tab import TabFlow

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


class LoginFlow(TabFlow):
    def __init__(self, browser: Browser, frontend_url: str, **options: Any) -> None:
        super().__init__(browser, frontend_url, "login", **options)
        self.open_calls: list[str] = []
        self.created_pages = [self.page]
        self.context.on("page", lambda page: self.created_pages.append(page))
        self.context.add_init_script("""(() => {
          const open = window.open;
          window.open = (...args) => {
            console.debug('__OAUTH_LOGIN_OPEN__' + JSON.stringify(args));
            return open(...args);
          };
        })();""")
        self.page.on(
            "console",
            lambda message: (
                self.open_calls.append(message.text)
                if message.text.startswith("__OAUTH_LOGIN_OPEN__")
                else None
            ),
        )

    def route(self, route: Route) -> None:
        url = urlparse(route.request.url)
        if (
            url.netloc == urlparse(self.url).netloc
            and url.path == "/api/auth/oauth/github/callback"
        ):
            self.requests.append(route.request)
            fragment = (
                "oauth_error=OAUTH_CANCELLED"
                if parse_qs(url.query).get("error") == ["access_denied"]
                else "oauth_code=tab-code"
            )
            route.fulfill(
                status=303,
                headers={
                    "location": f"{self.url}/login#{fragment}",
                    "cache-control": "no-store",
                    "referrer-policy": "no-referrer",
                },
                body="",
            )
            return
        super().route(route)

    def start(self) -> None:
        self.button().click()
        expect(self.page).to_have_url(self.provider_url)
        expect(
            self.page.get_by_role("heading", name="Choose a GitHub account")
        ).to_be_visible()
        self.assert_single_page()

    def confirm(self) -> None:
        previous_count = len(self.completions)
        self.page.get_by_role("link", name="Use selected account").click()
        self.wait_count(self.completions, previous_count + 1)
        expect(self.page).to_have_url(f"{self.url}/login")

    def wait_count(self, values: list[Any], count: int) -> None:
        deadline = time.monotonic() + 5
        while len(values) < count and time.monotonic() < deadline:
            self.page.wait_for_timeout(10)
        assert len(values) == count

    def assert_single_page(self) -> None:
        assert self.context.pages == [self.page]
        assert self.created_pages == [self.page]
        assert not self.open_calls

    def assert_callback_spinner(self) -> None:
        spinner = self.page.locator('#root svg[role="status"][aria-label="Loading"]')
        expect(spinner).to_have_count(1)
        expect(spinner).to_be_visible()
        expect(self.page.locator("#username, #password")).to_have_count(0)
        expect(self.page.locator('[data-slot="card"]')).to_have_count(0)
        expect(self.page.get_by_role("dialog")).to_have_count(0)
        assert spinner.evaluate("""element => {
          const rect = element.getBoundingClientRect();
          const parent = element.parentElement.getBoundingClientRect();
          return Math.abs(rect.x + rect.width / 2 - innerWidth / 2) <= 1
            && Math.abs(rect.y + rect.height / 2 - innerHeight / 2) <= 1
            && parent.width === innerWidth && parent.height === innerHeight;
        }""")


@pytest.fixture
def login_flow(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> Iterator[Callable[..., LoginFlow]]:
    flows: list[LoginFlow] = []

    def create(**options: Any) -> LoginFlow:
        flow = LoginFlow(browser, workspace_servers[0], **options)
        flows.append(flow)
        return flow

    yield create
    for flow in flows:
        flow.context.unroute_all(behavior="ignoreErrors")
        flow.context.close()
        assert not flow.unexpected
        assert not flow.open_calls
        assert len(flow.created_pages) == 1


@pytest.mark.browser_smoke
def test_github_login_uses_current_page_and_consumes_callback_once(
    login_flow: Callable[..., LoginFlow],
) -> None:
    flow = login_flow()
    flow.context.add_cookies(
        [
            {"name": "oauth-test-session", "value": "browser-proof", "url": flow.url},
        ]
    )
    flow.open()
    flow.start()
    assert parse_qs(urlparse(flow.provider_requests[0].url).query) == {}
    flow.confirm()
    flow.assert_callback_spinner()
    flow.page.wait_for_timeout(100)
    assert len(flow.completions) == 1
    assert flow.completions[0].request.post_data_json == {"code": "tab-code"}
    assert flow.completions[0].request.header_value("authorization") is None
    assert "oauth-test-session=browser-proof" in (
        flow.completions[0].request.header_value("cookie") or ""
    )
    assert flow.starts[0].request.method == "POST"
    assert flow.starts[0].request.header_value("authorization") is None
    for request in flow.provider_requests:
        assert request.frame.page == flow.page
        assert request.header_value("authorization") is None
        assert request.header_value("cookie") is None
    flow.finish()
    expect(flow.page.locator('input[name="resume-search"]')).to_be_visible()
    expect(flow.page).to_have_url(f"{flow.url}/resume")
    expect(flow.page.get_by_role("dialog")).to_have_count(0)
    assert len(flow.starts) == len(flow.completions) == len(flow.galleries) == 1
    assert (
        flow.page.evaluate(
            "JSON.parse(localStorage.getItem('resumate-auth-session')).accessToken"
        )
        == browser_session["accessToken"]
    )
    flow.assert_single_page()


def test_github_unavailable_keeps_form_without_navigation(
    login_flow: Callable[..., LoginFlow],
) -> None:
    flow = login_flow(viewport={"width": 375, "height": 812})
    flow.available = False
    flow.open()
    flow.button().click()
    expect(
        flow.page.get_by_text(
            "GitHub is not connected. Sign in with your password, "
            "then connect it in settings.",
            exact=True,
        )
    ).to_be_visible()
    expect(flow.button()).to_be_enabled()
    flow.assert_parent()
    flow.assert_single_page()
    assert not flow.starts and not flow.completions


def test_github_availability_failure_can_retry_without_authorization(
    login_flow: Callable[..., LoginFlow],
) -> None:
    flow = login_flow()
    flow.setup_failures = 1
    flow.page.goto(f"{flow.url}/login", wait_until="networkidle")
    flow.page.get_by_role("button", name="Retry", exact=True).click()
    expect(flow.button()).to_be_enabled()
    assert not flow.starts
    flow.assert_single_page()


@pytest.mark.parametrize("outcome", ["leave", "failure"])
def test_github_login_preparation_keeps_form_and_late_result_cannot_navigate(
    login_flow: Callable[..., LoginFlow],
    outcome: str,
) -> None:
    flow = login_flow(viewport={"width": 375, "height": 812}, reduced_motion="reduce")
    flow.hold_start = True
    previous_url = f"{flow.url}/login?previous=1"
    if outcome == "leave":
        flow.page.goto(previous_url, wait_until="networkidle")
    flow.open()
    button = flow.button()
    rect = button.bounding_box()
    icon = button.locator('[data-icon="inline-start"]').evaluate(
        "element => element.outerHTML"
    )
    flow.begin()
    flow.page.wait_for_timeout(200)
    expect(flow.page.get_by_role("dialog")).to_have_count(0)
    expect(button).to_be_disabled()
    expect(button).to_have_attribute("aria-busy", "true")
    assert button.bounding_box() == rect
    assert (
        button.locator('[data-icon="inline-start"]').evaluate(
            "element => element.outerHTML"
        )
        == icon
    )
    flow.assert_parent()
    flow.assert_single_page()
    button.evaluate("element => element.click()")
    assert len(flow.starts) == 1
    if outcome == "leave":
        flow.page.go_back(wait_until="domcontentloaded")
        expect(flow.page).to_have_url(previous_url)
        flow.release_start(flow.starts[0])
    else:
        flow.starts[0].fulfill(status=503, json={"detail": {"code": "REQUEST_FAILED"}})
        expect(
            flow.page.get_by_text("Request failed. Please try again later.", exact=True)
        ).to_be_visible()
    expect(button).to_be_enabled()
    flow.page.wait_for_timeout(100)
    if outcome == "leave":
        expect(flow.page).to_have_url(previous_url)
    else:
        flow.assert_parent()
    assert not flow.provider_requests
    flow.begin()
    flow.release_start(flow.starts[1])
    expect(flow.page).to_have_url(flow.provider_url)
    flow.confirm()
    flow.finish()
    expect(flow.page.locator('input[name="resume-search"]')).to_be_visible()
    assert len(flow.starts) == 2 and len(flow.completions) == 1


@pytest.mark.parametrize("failure", ["provider", "complete", "intent"])
def test_github_login_failures_return_to_login_and_allow_retry(
    login_flow: Callable[..., LoginFlow],
    failure: str,
) -> None:
    flow = login_flow()
    flow.open()
    flow.start()
    if failure == "provider":
        flow.page.goto(f"{flow.url}/api/auth/oauth/github/callback?error=access_denied")
        expect(
            flow.page.get_by_text(
                "Authorization was cancelled. You can try again.", exact=True
            )
        ).to_be_visible()
        assert not flow.completions
    else:
        flow.confirm()
        if failure == "complete":
            flow.completions[0].fulfill(
                status=400, json={"detail": "OAUTH_EXCHANGE_EXPIRED"}
            )
        else:
            flow.finish(intent="bind")
        expect(flow.page.locator('[data-slot="field-error"]')).to_be_visible()
    expect(flow.page).to_have_url(f"{flow.url}/login")
    expect(flow.button()).to_be_enabled()
    assert flow.page.evaluate("localStorage.getItem('resumate-auth-session')") is None
    assert not flow.galleries
    flow.start()
    flow.confirm()
    flow.finish()
    expect(flow.page.locator('input[name="resume-search"]')).to_be_visible()
    flow.assert_single_page()


def test_github_login_browser_back_restores_retry(
    login_flow: Callable[..., LoginFlow],
) -> None:
    flow = login_flow()
    flow.open()
    flow.start()
    flow.page.go_back(wait_until="domcontentloaded")
    expect(flow.page).to_have_url(f"{flow.url}/login")
    expect(flow.button()).to_be_enabled()
    expect(flow.page.get_by_role("dialog")).to_have_count(0)
    flow.start()
    flow.confirm()
    flow.finish()
    expect(flow.page.locator('input[name="resume-search"]')).to_be_visible()
    assert len(flow.starts) == 2 and len(flow.completions) == 1
    flow.assert_single_page()


@pytest.mark.parametrize("stage", ["exchange", "workspace"])
def test_leaving_login_callback_ignores_late_results_and_clears_its_session(
    login_flow: Callable[..., LoginFlow],
    stage: str,
) -> None:
    flow = login_flow()
    flow.hold_gallery = True
    flow.open()
    flow.start()
    flow.confirm()
    flow.assert_callback_spinner()
    if stage == "workspace":
        flow.finish()
        flow.wait_count(flow.galleries, 1)
        assert (
            flow.page.evaluate("localStorage.getItem('resumate-auth-session')")
            is not None
        )
    flow.assert_callback_spinner()
    leave_url = f"{flow.url}/login?left=callback"
    flow.page.goto(leave_url, wait_until="domcontentloaded")
    expect(flow.button()).to_be_enabled()
    if stage == "exchange":
        flow.finish()
    else:
        flow.respond(flow.galleries[0], flow.gallery_data())
    flow.page.wait_for_timeout(200)
    expect(flow.page).to_have_url(leave_url)
    assert flow.page.evaluate("localStorage.getItem('resumate-auth-session')") is None
    assert len(flow.galleries) == (1 if stage == "workspace" else 0)
    flow.page.reload(wait_until="networkidle")
    expect(flow.button()).to_be_enabled()
    assert len(flow.completions) == 1
    assert flow.page.evaluate("localStorage.getItem('resumate-auth-session')") is None
    flow.hold_gallery = False
    flow.start()
    flow.confirm()
    flow.finish()
    expect(flow.page.locator('input[name="resume-search"]')).to_be_visible()


def test_github_login_gallery_failure_retries_without_reauthenticating(
    login_flow: Callable[..., LoginFlow],
) -> None:
    flow = login_flow()
    flow.gallery_failures = 100
    flow.open()
    flow.start()
    flow.confirm()
    flow.finish()
    expect(flow.page).to_have_url(f"{flow.url}/resume")
    expect(flow.page.get_by_role("button", name="Retry", exact=True)).to_be_visible()
    expect(flow.page.locator('[data-slot="sidebar-inset"]')).to_be_visible()
    session = flow.page.evaluate("localStorage.getItem('resumate-auth-session')")
    assert session is not None
    flow.gallery_failures = 0
    flow.page.get_by_role("button", name="Retry", exact=True).click()
    expect(flow.page.locator('input[name="resume-search"]')).to_be_visible()
    assert len(flow.starts) == len(flow.completions) == 1
    assert (
        flow.page.evaluate("localStorage.getItem('resumate-auth-session')") == session
    )


def test_github_callback_can_leave_before_auth_bootstrap_finishes(
    login_flow: Callable[..., LoginFlow],
) -> None:
    flow = login_flow()
    bootstrap_routes: list[Route] = []
    previous_url = f"{flow.url}/login?before-callback=1"
    flow.page.goto(previous_url, wait_until="networkidle")

    def hold_bootstrap(route: Route) -> None:
        bootstrap_routes.append(route)

    flow.context.route("**/api/auth/setup", hold_bootstrap)
    flow.page.goto(
        f"{flow.url}/login#oauth_code=tab-code", wait_until="domcontentloaded"
    )
    flow.assert_callback_spinner()
    flow.wait_count(bootstrap_routes, 1)
    assert not flow.completions
    flow.page.go_back(wait_until="domcontentloaded")
    expect(flow.page).to_have_url(previous_url)
    flow.context.unroute("**/api/auth/setup", hold_bootstrap)
    for route in bootstrap_routes:
        flow.respond(route, {"setupRequired": False, "githubLoginAvailable": True})
    expect(flow.button()).to_be_enabled()
    flow.page.wait_for_timeout(100)
    assert not flow.completions and not flow.galleries
    flow.page.go_forward(wait_until="domcontentloaded")
    expect(flow.page).to_have_url(f"{flow.url}/login")
    expect(flow.button()).to_be_enabled()
    assert not flow.completions and not flow.galleries
    assert flow.page.evaluate("location.hash") == ""
    assert flow.page.evaluate("localStorage.getItem('resumate-auth-session')") is None
    flow.start()
    flow.confirm()
    flow.finish()
    expect(flow.page.locator('input[name="resume-search"]')).to_be_visible()
    assert len(flow.starts) == len(flow.completions) == 1
    flow.assert_single_page()


def test_github_callback_browser_back_ignores_late_exchange_and_can_retry(
    login_flow: Callable[..., LoginFlow],
) -> None:
    flow = login_flow()
    flow.open()
    flow.start()
    flow.confirm()
    flow.assert_callback_spinner()
    flow.page.go_back(wait_until="domcontentloaded")
    expect(flow.page).to_have_url(flow.provider_url)
    expect(
        flow.page.get_by_role("heading", name="Choose a GitHub account")
    ).to_be_visible()
    flow.finish()
    flow.page.wait_for_timeout(100)
    expect(flow.page).to_have_url(flow.provider_url)
    assert not flow.galleries
    app_storage = next(
        origin["localStorage"]
        for origin in flow.context.storage_state()["origins"]
        if origin["origin"] == flow.url
    )
    assert not any(item["name"] == "resumate-auth-session" for item in app_storage)
    flow.confirm()
    assert len(flow.completions) == 2
    assert all(
        route.request.post_data_json == {"code": "tab-code"}
        for route in flow.completions
    )
    flow.finish()
    expect(flow.page.locator('input[name="resume-search"]')).to_be_visible()
    expect(flow.page).to_have_url(f"{flow.url}/resume")
    assert len(flow.starts) == 1
    flow.assert_single_page()


def test_github_callback_bootstrap_failure_leaves_retry_accessible(
    login_flow: Callable[..., LoginFlow],
) -> None:
    flow = login_flow()
    flow.setup_failures = 1
    flow.page.goto(
        f"{flow.url}/login#oauth_code=tab-code", wait_until="domcontentloaded"
    )
    retry = flow.page.get_by_role("button", name="Retry", exact=True)
    expect(retry).to_be_visible()
    expect(flow.page.get_by_role("dialog")).to_have_count(0)
    assert not flow.completions
    retry.click()
    flow.wait_count(flow.completions, 1)
    expect(flow.page).to_have_url(f"{flow.url}/login")
    flow.assert_callback_spinner()
    flow.finish()
    expect(flow.page.locator('input[name="resume-search"]')).to_be_visible()
    assert len(flow.completions) == 1
    flow.assert_single_page()
