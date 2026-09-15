import json
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Browser, Page, Request, Route, expect

from app.services.auth_oauth_callback import oauth_callback_response
from tests.e2e.browser_support import browser_session

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


class TabFlow:
    def __init__(
        self, browser: Browser, frontend_url: str, mode: str, **options: Any
    ) -> None:
        self.url = frontend_url
        self.mode = mode
        self.intent = "login" if mode == "login" else "bind"
        self.context = browser.new_context(locale="en-US", **options)
        self.context.add_init_script(
            "localStorage.setItem('reseno-locale', 'en');"
            "localStorage.setItem('reseno-theme', 'light');"
        )
        if self.intent == "bind":
            self.context.add_init_script(
                f"if (location.origin === {json.dumps(frontend_url)}) "
                "localStorage.setItem('reseno-auth-session', "
                f"{json.dumps(json.dumps(browser_session))});"
            )
        self.available = True
        self.bound = False
        self.hold_start = False
        self.hold_identity = False
        self.hold_gallery = False
        self.identity_failures = 0
        self.gallery_failures = 0
        self.setup_failures = 0
        self.starts: list[Route] = []
        self.completions: list[Route] = []
        self.identities: list[Route] = []
        self.galleries: list[Route] = []
        self.requests: list[Request] = []
        self.provider_requests: list[Request] = []
        self.unexpected: list[str] = []
        self.provider_url = "https://github-provider.test/authorize" + (
            "?prompt=select_account" if self.intent == "bind" else ""
        )
        self.registration_url = (
            "https://github-provider.test/apps/new?state=setup-state"
        )
        self.manifest = {
            "name": "Reseno Browser Test",
            "url": frontend_url,
            "redirect_url": f"{frontend_url}/api/auth/oauth/github/setup/callback",
            "callback_urls": [f"{frontend_url}/api/auth/oauth/github/callback"],
            "public": False,
            "default_permissions": {},
            "default_events": [],
        }
        self.context.route("**/*", self.route)
        self.page = self.context.new_page()

    @staticmethod
    def respond(route: Route, data: dict[str, Any]) -> None:
        route.fulfill(json={"code": 0, "message": "OK", "data": data})

    def identity_data(self) -> dict[str, Any]:
        return {
            "identities": [
                {
                    "provider": "github",
                    "label": "connected-owner",
                    "createdAt": "2026-09-07T00:00:00Z",
                }
            ]
            if self.bound
            else [],
            "providers": [{"provider": "github", "configured": self.mode != "setup"}],
        }

    def gallery_data(self) -> dict[str, Any]:
        return {
            "theme": "light",
            "resumes": [],
            "customTemplates": [],
            "defaultTemplateIds": {"zh": "minimal", "en": "minimal"},
        }

    def release_start(self, route: Route) -> None:
        self.respond(
            route,
            {
                "registrationUrl": self.registration_url,
                "manifest": self.manifest,
            }
            if self.mode == "setup"
            else {"authorizationUrl": self.provider_url},
        )

    def finish(self, *, intent: str | None = None) -> None:
        result_intent = intent or self.intent
        self.bound = result_intent == "bind"
        self.respond(
            self.completions[-1],
            {
                "provider": "github",
                "intent": result_intent,
                "auth": {
                    "username": browser_session["username"],
                    "accessToken": browser_session["accessToken"],
                    "expiresAt": browser_session["expiresAt"],
                    "tokenType": "bearer",
                }
                if result_intent == "login"
                else None,
            },
        )

    def route(self, route: Route) -> None:
        request = route.request
        url = urlparse(request.url)
        if url.netloc == "github-provider.test":
            self.provider_requests.append(request)
            callback = f"{self.url}/api/auth/oauth/github/callback?code=provider-code"
            route.fulfill(
                content_type="text/html",
                body=(
                    "<h1>Choose a GitHub account</h1>"
                    f"<a href={json.dumps(callback)}>Use selected account</a>"
                ),
            )
            return
        if url.netloc != urlparse(self.url).netloc:
            self.unexpected.append(request.url)
            route.abort()
            return
        if not url.path.startswith("/api/"):
            route.continue_()
            return
        self.requests.append(request)
        if url.path == "/api/auth/setup" and request.method == "GET":
            if self.setup_failures:
                self.setup_failures -= 1
                route.fulfill(status=503, json={"detail": {"code": "REQUEST_FAILED"}})
            else:
                self.respond(
                    route,
                    {
                        "setupRequired": False,
                        "githubLoginAvailable": self.available,
                    },
                )
        elif url.path == f"/api/auth/oauth/github/{self.mode}":
            self.starts.append(route)
            if not self.hold_start:
                self.release_start(route)
        elif url.path == "/api/auth/oauth/github/callback":
            response = oauth_callback_response(
                self.url,
                {"error": "OAUTH_CANCELLED"}
                if parse_qs(url.query).get("error") == ["access_denied"]
                else {"code": "tab-code", "intent": self.intent},
            )
            route.fulfill(
                status=response.status_code,
                headers=dict(response.headers),
                body=bytes(response.body),
            )
        elif url.path == "/api/auth/oauth/complete":
            self.completions.append(route)
        elif url.path == "/api/auth/oauth/identities":
            self.identities.append(route)
            if self.hold_identity and self.bound:
                return
            if self.identity_failures:
                self.identity_failures -= 1
                route.fulfill(status=503, json={"detail": {"code": "REQUEST_FAILED"}})
            else:
                self.respond(route, self.identity_data())
        elif url.path == "/api/workspace/pages/settings":
            self.respond(
                route,
                {
                    "theme": "light",
                    "modelConfigs": [],
                    "agentSettings": {
                        "defaultModelConfigId": "",
                        "responseLanguage": "follow",
                        "behaviorMode": "balanced",
                        "confirmationMode": "always",
                    },
                },
            )
        elif url.path == "/api/workspace/pages/resumes":
            self.galleries.append(route)
            if self.hold_gallery:
                return
            if self.gallery_failures:
                self.gallery_failures -= 1
                route.fulfill(status=503, json={"detail": {"code": "REQUEST_FAILED"}})
            else:
                self.respond(route, self.gallery_data())
        else:
            self.unexpected.append(f"{request.method} {url.path}")
            route.abort()

    def open(self) -> None:
        self.page.goto(
            f"{self.url}/{'login' if self.intent == 'login' else 'settings'}",
            wait_until="networkidle",
        )
        expect(self.button()).to_be_enabled()
        self.page.evaluate("""() => {
          window.__parentDocument = document;
          window.__parentPageHides = 0;
          window.__parentElements = [...document.querySelectorAll(
            '#username, #password, [data-slot="auth-particle-background"], '
            + '[role="group"][aria-label="GitHub"], [data-slot="sidebar-inset"]'
          )];
          addEventListener('pagehide', () => window.__parentPageHides++);
        }""")
        if self.intent == "login":
            self.page.locator("#username").fill(" retained-owner ")
            self.page.locator("#password").fill("retained-password")

    def button(self):
        return self.page.get_by_role(
            "button",
            name=(
                "Continue with GitHub"
                if self.intent == "login"
                else "Connect GitHub"
            ),
            exact=True,
            include_hidden=True,
        )

    def start(self) -> Page:
        with self.page.expect_popup() as tab:
            self.button().click()
        return tab.value

    def begin(self) -> None:
        previous_count = len(self.starts)
        self.button().click()
        deadline = time.monotonic() + 5
        while len(self.starts) == previous_count and time.monotonic() < deadline:
            self.page.wait_for_timeout(10)
        assert len(self.starts) == previous_count + 1

    def release_tab(self, start_index: int = -1) -> Page:
        with self.page.expect_popup() as tab:
            self.release_start(self.starts[start_index])
        return tab.value

    def assert_binding_toast(
        self, *, success: bool = False, locale: str = "en", count: int = 1
    ) -> None:
        kind = "success" if success else "error"
        title = (
            ("绑定成功" if success else "绑定失败")
            if locale == "zh"
            else ("Connection successful" if success else "Connection failed")
        )
        toast = self.page.locator(f'[data-sonner-toast][data-type="{kind}"]')
        expect(toast).to_have_count(count)
        if count:
            expect(toast.locator("[data-title]")).to_have_text([title] * count)
            expect(toast).to_have_text([title] * count)
            expect(toast.locator("[data-description]")).to_have_count(0)

    def confirm(self, tab: Page) -> None:
        expect(
            tab.get_by_role("heading", name="Choose a GitHub account")
        ).to_be_visible()
        assert not tab.is_closed()
        previous_count = len(self.completions)
        with self.page.expect_request("**/api/auth/oauth/complete"):
            tab.get_by_role("link", name="Use selected account").click()
        deadline = time.monotonic() + 5
        while len(self.completions) == previous_count and time.monotonic() < deadline:
            self.page.wait_for_timeout(10)
        assert len(self.completions) == previous_count + 1

    def assert_parent(self, *, retained: bool = True) -> None:
        assert self.page.evaluate("window.__parentDocument === document")
        assert self.page.evaluate("window.__parentPageHides") == 0
        if retained:
            assert self.page.evaluate(
                "window.__parentElements.every(e => e.isConnected)"
            )
            assert self.page.url == (
                f"{self.url}/{'login' if self.intent == 'login' else 'settings'}"
            )
            if self.intent == "login":
                expect(self.page.locator("#username")).to_have_value(" retained-owner ")
                expect(self.page.locator("#password")).to_have_value(
                    "retained-password"
                )


@pytest.fixture
def tab_flow(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> Iterator[Callable[..., TabFlow]]:
    flows: list[TabFlow] = []

    def create(mode: str, **options: Any) -> TabFlow:
        flow = TabFlow(browser, workspace_servers[0], mode, **options)
        flows.append(flow)
        return flow

    yield create
    for flow in flows:
        flow.context.unroute_all(behavior="ignoreErrors")
        flow.context.close()
        assert not flow.unexpected


@pytest.mark.browser_smoke
@pytest.mark.parametrize("mode", ["bind", "setup"])
def test_github_tab_completes_in_parent_without_document_navigation(
    tab_flow: Callable[..., TabFlow],
    mode: str,
    tmp_path: Path,
) -> None:
    width = 1440
    reduced_motion = "no-preference"
    flow = tab_flow(
        mode,
        reduced_motion=reduced_motion,
        viewport={"width": width, "height": 900},
    )
    flow.hold_start = True
    flow.hold_gallery = True
    flow.hold_identity = True
    flow.context.add_cookies(
        [
            {"name": "oauth-test-session", "value": "browser-proof", "url": flow.url},
        ]
    )
    flow.open()
    initial_identity_count = len(flow.identities)
    button = flow.button()
    label = button.inner_text()
    rect = button.bounding_box()
    assert rect is not None
    flow.page.evaluate(
        """mode => {
      const fetch = window.fetch;
      window.__githubCredentials = [];
      window.fetch = function(input, init) {
        if (String(input).endsWith('/api/auth/oauth/github/' + mode)) {
          window.__githubCredentials.push(init?.credentials);
        }
        return fetch.call(this, input, init);
      };
    }""",
        mode,
    )
    frames: list[dict[str, Any]] = []
    prefix = "__GITHUB_TAB_PARENT_FRAME__"
    flow.page.on(
        "console",
        lambda message: (
            frames.append(json.loads(message.text.removeprefix(prefix)))
            if message.text.startswith(prefix)
            else None
        ),
    )
    flow.page.evaluate(
        """({prefix}) => {
      window.__tabStage = 'idle';
      window.__tabStageFrameCounts = {};
      const capture = () => {
        const button = document.querySelector(
          '[role="group"][aria-label="GitHub"] button');
        const rect = button?.getBoundingClientRect();
        console.debug(prefix + JSON.stringify({
          stage: window.__tabStage,
          path: location.pathname,
          retained: window.__parentElements.every(e => e.isConnected),
          label: button?.innerText,
          width: rect?.width, height: rect?.height,
          disabled: button?.disabled,
          busy: button?.getAttribute('aria-busy'),
          passwordDisabled: document.querySelector(
            'form button[type="submit"]')?.disabled,
          icon: button?.querySelector('[data-icon="inline-start"]')?.outerHTML,
          sidebar: Boolean(document.querySelector('[data-slot="sidebar-inset"]')),
          gallery: Boolean(document.querySelector('input[name="resume-search"]')),
          skeleton: Boolean(document.querySelector(
            '[data-slot="workspace-entry-skeleton"]')),
        }));
        window.__tabStageFrameCounts[window.__tabStage] =
          (window.__tabStageFrameCounts[window.__tabStage] ?? 0) + 1;
        requestAnimationFrame(capture);
      };
      requestAnimationFrame(capture);
    }""",
        {"prefix": prefix},
    )

    def sample(stage: str) -> None:
        flow.page.bring_to_front()
        flow.page.evaluate("stage => window.__tabStage = stage", stage)
        flow.page.wait_for_timeout(100)
        flow.page.wait_for_function(
            "stage => (window.__tabStageFrameCounts[stage] ?? 0) >= 2",
            arg=stage,
            timeout=5_000,
        )

    flow.begin()
    expect(button).to_be_disabled()
    dialog = flow.page.get_by_role("dialog")
    expect(dialog).to_be_visible()
    sample("authorization")
    button.evaluate("element => element.click()")
    assert len(flow.starts) == 1
    assert len(flow.context.pages) == 1
    assert not flow.provider_requests
    tab = flow.release_tab()
    expect(tab.get_by_role("heading", name="Choose a GitHub account")).to_be_visible()
    sample("provider")
    flow.assert_parent()
    assert not flow.completions
    assert not tab.is_closed()
    if width == 1440 and reduced_motion == "no-preference":
        flow.page.screenshot(path=tmp_path / f"reseno-tab-{mode}-parent.png")
        tab.screenshot(path=tmp_path / f"reseno-tab-{mode}-provider-mock.png")
    flow.confirm(tab)
    expect(tab).to_have_url(f"{flow.url}/api/auth/oauth/github/callback")
    sample("completion")
    flow.assert_parent()
    assert button.inner_text() == label
    assert button.bounding_box() == rect
    assert len(flow.starts) == 1
    assert len(flow.completions) == 1
    assert flow.completions[0].request.frame.page == flow.page
    assert flow.completions[0].request.post_data_json == {"code": "tab-code"}
    assert flow.completions[0].request.header_value("authorization") is None
    for request in flow.provider_requests:
        assert request.frame.page == tab
        assert request.header_value("authorization") is None
        assert request.header_value("cookie") is None
    start = flow.starts[0].request
    assert start.method == "POST"
    assert start.post_data_json == (
        {"publicBaseUrl": flow.url} if mode == "setup" else {}
    )
    assert start.header_value("authorization") == (
        f"Bearer {browser_session['accessToken']}"
    )
    assert start.header_value("origin") == flow.url
    assert "oauth-test-session=browser-proof" in (start.header_value("cookie") or "")
    assert flow.page.evaluate("window.__githubCredentials") == ["include"]
    if mode == "setup":
        registration = flow.provider_requests[0]
        assert registration.method == "POST"
        assert registration.header_value("origin") == flow.url
        assert registration.header_value("content-type") == (
            "application/x-www-form-urlencoded"
        )
        fields = parse_qs(registration.post_data or "")
        assert set(fields) == {"manifest"}
        assert json.loads(fields["manifest"][0]) == flow.manifest
    else:
        assert parse_qs(urlparse(tab.url).query) == {}
        assert parse_qs(urlparse(flow.provider_requests[0].url).query) == (
            {"prompt": ["select_account"]}
        )
    flow.finish()
    expect(button).to_be_disabled()
    flow.page.wait_for_timeout(100)
    sample("data")
    flow.assert_parent()
    assert not tab.is_closed()
    expect(flow.page.locator("[data-sonner-toast]")).to_have_count(0)
    flow.page.evaluate("window.__tabStage = 'finished'")
    assert len(flow.identities) == initial_identity_count + 1
    flow.respond(flow.identities[-1], flow.identity_data())
    expect(flow.page.get_by_text("connected-owner", exact=True)).to_be_visible()
    expect(flow.page.get_by_role("button", name="Disconnect GitHub")).to_be_enabled()
    flow.assert_parent()
    flow.assert_binding_toast(success=True)
    expect(flow.page.locator('[data-slot="field-error"]')).to_have_count(0)
    flow.page.wait_for_timeout(100)
    assert tab.is_closed()
    assert len(flow.context.pages) == 1
    expect(dialog).to_have_count(0)
    for stage in ("authorization", "provider", "completion", "data"):
        stage_frames = [frame for frame in frames if frame["stage"] == stage]
        assert len(stage_frames) >= 2, (stage, frames)
        assert all(
            frame["retained"]
            and frame["label"] == label
            and abs(frame["width"] - rect["width"]) < 0.5
            and abs(frame["height"] - rect["height"]) < 0.5
            and frame["disabled"]
            and frame["busy"] == "true"
            and not frame["skeleton"]
            for frame in stage_frames
        ), (stage, stage_frames)
    if width == 1440 and reduced_motion == "no-preference":
        flow.page.screenshot(path=tmp_path / f"reseno-tab-{mode}-complete.png")
    assert flow.page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("mode", ["bind", "setup"])
def test_github_start_failure_keeps_parent_and_preserves_retry(
    tab_flow: Callable[..., TabFlow],
    mode: str,
) -> None:
    flow = tab_flow(mode)
    flow.hold_start = True
    flow.open()
    button = flow.button()
    rect = button.bounding_box()
    label = button.inner_text()
    flow.begin()
    expect(button).to_be_disabled()
    flow.page.wait_for_timeout(100)
    assert len(flow.starts) == 1
    flow.starts[0].fulfill(status=503, json={"detail": {"code": "REQUEST_FAILED"}})
    expect(button).to_be_enabled()
    flow.assert_binding_toast()
    expect(flow.page.locator('[data-slot="field-error"]')).to_have_count(0)
    assert len(flow.context.pages) == 1
    assert not flow.provider_requests
    assert button.inner_text() == label
    current_rect = button.bounding_box()
    assert current_rect is not None and rect is not None
    assert (current_rect["width"], current_rect["height"]) == (
        rect["width"],
        rect["height"],
    )
    flow.assert_parent()
    flow.begin()
    expect(button).to_be_disabled()
    flow.page.wait_for_timeout(100)
    assert len(flow.starts) == 2
    retry_tab = flow.release_tab()
    flow.confirm(retry_tab)
    flow.finish()
    expect(flow.page.get_by_text("connected-owner", exact=True)).to_be_visible()
    flow.assert_binding_toast(success=True)
    assert len(flow.completions) == 1


def test_github_binding_identity_failure_retries_without_reauthorizing(
    tab_flow: Callable[..., TabFlow],
) -> None:
    flow = tab_flow("bind")
    flow.open()
    session = flow.page.evaluate("localStorage.getItem('reseno-auth-session')")
    tab = flow.start()
    flow.confirm(tab)
    flow.identity_failures = 1
    flow.finish()
    flow.assert_binding_toast()
    flow.assert_binding_toast(success=True, count=0)
    github_row = flow.page.get_by_role("group", name="GitHub", exact=True)
    expect(github_row).to_be_visible()
    expect(github_row.get_by_role("button", name="Retry", exact=True)).to_be_enabled()
    expect(flow.page.locator('[data-slot="field-error"]')).to_have_count(0)
    expect(flow.button()).to_have_count(0)
    assert tab.is_closed()
    assert flow.page.url == f"{flow.url}/settings"
    expect(flow.page.locator('[data-slot="sidebar-inset"]')).to_be_visible()
    flow.page.get_by_role("button", name="Retry", exact=True).click()
    expect(flow.page.get_by_text("connected-owner", exact=True)).to_be_visible()
    expect(flow.page.get_by_role("button", name="Disconnect GitHub")).to_be_enabled()
    assert flow.page.evaluate("localStorage.getItem('reseno-auth-session')") == session
    assert len(flow.starts) == 1
    assert len(flow.completions) == 1
    flow.assert_binding_toast()
    flow.assert_binding_toast(success=True, count=0)


def test_github_callback_without_opener_never_exchanges_or_loads_workspace(
    tab_flow: Callable[..., TabFlow],
) -> None:
    flow = tab_flow("bind")
    flow.page.goto(
        f"{flow.url}/api/auth/oauth/github/callback?code=orphan",
        wait_until="networkidle",
    )
    expect(
        flow.page.get_by_text(
            "Could not connect to the original page. Close this tab and try again.",
            exact=True,
        )
    ).to_be_visible()
    assert flow.page.url == f"{flow.url}/auth/callback"
    assert [urlparse(request.url).path for request in flow.requests] == [
        "/api/auth/oauth/github/callback"
    ]
    assert flow.page.evaluate("localStorage.getItem('reseno-auth-session')") is not None


@pytest.mark.browser_smoke
def test_direct_callback_route_keeps_session_and_clears_unused_credentials(
    tab_flow: Callable[..., TabFlow],
) -> None:
    flow = tab_flow("bind")
    flow.page.goto(
        f"{flow.url}/auth/callback?code=unused#oauth_code=unused",
        wait_until="networkidle",
    )
    expect(
        flow.page.get_by_text(
            "Could not connect to the original page. Close this tab and try again.",
            exact=True,
        )
    ).to_be_visible()
    expect(
        flow.page.get_by_role("button", name="Close tab", exact=True)
    ).to_be_visible()
    assert flow.page.url == f"{flow.url}/auth/callback"
    assert not flow.requests
    assert flow.page.evaluate("localStorage.getItem('reseno-auth-session')") is not None


def test_github_callback_requires_acknowledgement_from_original_page(
    tab_flow: Callable[..., TabFlow],
) -> None:
    flow = tab_flow("bind")
    flow.open()
    with flow.page.expect_popup() as opened:
        flow.page.evaluate(
            "url => window.open(url, 'unclaimed-github-authorization')",
            f"{flow.url}/api/auth/oauth/github/callback?code=orphan",
        )
    tab = opened.value
    expect(tab).to_have_url(f"{flow.url}/api/auth/oauth/github/callback")
    tab.evaluate("window.postMessage({type: 'reseno:oauth:received'}, location.origin)")
    expect(tab).to_have_url(f"{flow.url}/auth/callback", timeout=10_000)
    expect(
        tab.get_by_text(
            "Could not connect to the original page. Close this tab and try again.",
            exact=True,
        )
    ).to_be_visible()
    assert not flow.starts
    assert not flow.completions
    assert not flow.galleries
    flow.assert_parent()


@pytest.mark.parametrize("mode", ["bind"])
def test_github_provider_cancellation_returns_error_to_unchanged_parent(
    tab_flow: Callable[..., TabFlow],
    mode: str,
) -> None:
    flow = tab_flow(mode)
    flow.open()
    tab = flow.start()
    expect(tab.get_by_role("heading", name="Choose a GitHub account")).to_be_visible()
    tab.evaluate(
        "url => { location.href = url }",
        f"{flow.url}/api/auth/oauth/github/callback?error=access_denied",
    )
    flow.assert_binding_toast()
    expect(flow.page.locator('[data-slot="field-error"]')).to_have_count(0)
    expect(flow.button()).to_be_enabled()
    flow.assert_parent()
    assert tab.is_closed()
    assert not flow.completions


@pytest.mark.parametrize("mode", ["bind"])
def test_github_completion_rejects_server_intent_mismatch(
    tab_flow: Callable[..., TabFlow],
    mode: str,
) -> None:
    flow = tab_flow(mode)
    flow.open()
    session = flow.page.evaluate("localStorage.getItem('reseno-auth-session')")
    tab = flow.start()
    flow.confirm(tab)
    flow.finish(intent="login")
    expect(flow.button()).to_be_enabled()
    flow.assert_binding_toast()
    expect(flow.page.locator('[data-slot="field-error"]')).to_have_count(0)
    assert tab.is_closed()
    flow.assert_parent()
    assert flow.page.evaluate("localStorage.getItem('reseno-auth-session')") == session
    assert len(flow.completions) == 1
