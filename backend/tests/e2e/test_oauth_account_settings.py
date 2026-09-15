from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Request, Route, expect

from tests.e2e.browser_support import authenticated_context as _authenticated_context
from tests.e2e.workspace_network_support import ApiRequest, api_request_key

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


@pytest.mark.parametrize("error_code", ["OAUTH_NOT_CONFIGURED", "OAUTH_NOT_BOUND"])
@pytest.mark.parametrize(
    ("locale", "button_label", "toast_message"),
    [
        (
            "en-US",
            "Continue with GitHub",
            "GitHub is not connected. Sign in with your password, "
            "then connect it in settings.",
        ),
        (
            "zh-CN",
            "使用 GitHub 继续",
            "未绑定 GitHub 账号，请先使用密码登录后在设置中绑定",
        ),
    ],
)
def test_oauth_login_keeps_github_visible_and_explains_unbound_account(
    browser: Browser,
    workspace_servers: tuple[str, str],
    error_code: str,
    locale: str,
    button_label: str,
    toast_message: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(viewport={"width": 375, "height": 812}, locale=locale)
    page = context.new_page()
    created_pages = [page]
    context.on("page", lambda opened_page: created_pages.append(opened_page))
    api_requests: list[ApiRequest] = []
    external_requests: list[str] = []
    context.on(
        "request",
        lambda request: (
            api_requests.append(api_request)
            if (api_request := api_request_key(request)) is not None
            else None
        ),
    )

    def isolate_external_requests(route: Route) -> None:
        if urlparse(route.request.url).netloc != urlparse(frontend_url).netloc:
            external_requests.append(route.request.url)
            route.abort()
            return
        route.continue_()

    context.route("**/*", isolate_external_requests)
    context.route(
        "**/api/auth/setup",
        lambda route: route.fulfill(
            json={
                "code": 0,
                "message": "OK",
                "data": {"setupRequired": False, "githubLoginAvailable": True},
            },
        ),
    )
    context.route(
        "**/api/auth/oauth/github/login",
        lambda route: route.fulfill(
            status=503 if error_code == "OAUTH_NOT_CONFIGURED" else 403,
            json={"code": 40000, "message": error_code, "data": None},
        ),
    )

    try:
        page.goto(f"{frontend_url}/login", wait_until="networkidle")
        github_button = page.get_by_role("button", name=button_label, exact=True)
        password_button = page.locator('form button[type="submit"]')
        expect(github_button).to_be_enabled()
        expect(page.locator('[data-slot="field-separator"]')).to_be_visible()
        expect(page.get_by_text("Google", exact=True)).to_have_count(0)
        page.locator("#username").fill(" e2e-owner ")
        page.locator("#password").fill("E2ePassword2026")
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlparse(response.url).path == "/api/auth/oauth/github/login"
            )
        ) as login_response:
            github_button.click()
        response = login_response.value
        assert response.status == (503 if error_code == "OAUTH_NOT_CONFIGURED" else 403)
        assert response.json()["message"] == error_code
        assert response.request.header_value("authorization") is None
        info_toast = page.locator('[data-sonner-toast][data-type="info"]')
        expect(info_toast.get_by_text(toast_message, exact=True)).to_be_visible()
        expect(info_toast).to_have_css("opacity", "1")
        expect(page.locator('[data-slot="field-error"]')).to_have_count(0)
        expect(github_button).to_be_enabled()
        expect(password_button).to_be_enabled()
        expect(page.locator("#username")).to_have_value(" e2e-owner ")
        expect(page.locator("#password")).to_have_value("E2ePassword2026")
        assert page.url == f"{frontend_url}/login"
        assert created_pages == [page]
        assert context.pages == [page]
        assert not external_requests
        assert api_requests.count(("POST", "/api/auth/oauth/github/login")) == 1
        assert ("GET", "/api/auth/oauth/providers") not in api_requests
        assert ("POST", "/api/auth/login") not in api_requests
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        page.screenshot(
            path=f"/tmp/reseno-oauth-unbound-{locale}-{error_code}.png",
            full_page=True,
        )
    finally:
        context.close()


def test_oauth_settings_disconnect_retry_and_connect_on_mobile(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, viewport={"width": 375, "height": 812}, locale="en-US"
    )
    context.set_extra_http_headers({})
    page = context.new_page()
    binding_requests: list[Request] = []
    external_requests: list[str] = []
    provider_requests: list[Request] = []
    identity_label = "a-very-long-connected-owner-account-label@example.com"

    def isolate_external_requests(route: Route) -> None:
        if urlparse(route.request.url).netloc != urlparse(frontend_url).netloc:
            external_requests.append(route.request.url)
            route.abort()
            return
        route.continue_()

    context.route("**/*", isolate_external_requests)
    context.route(
        "**/api/auth/oauth/identities",
        lambda route: route.fulfill(
            json={
                "code": 0,
                "message": "OK",
                "data": {
                    "identities": [
                        {
                            "provider": "github",
                            "label": identity_label,
                            "createdAt": "2026-09-05T00:00:00Z",
                        }
                    ],
                    "providers": [
                        {"provider": "github", "configured": True},
                    ],
                },
            },
        ),
    )

    def change_binding(route: Route) -> None:
        binding_requests.append(route.request)
        if len(binding_requests) == 1:
            route.fulfill(status=503, json={"detail": {"code": "REQUEST_FAILED"}})
            return
        route.fulfill(
            json={
                "code": 0,
                "message": "OK",
                "data": {"deleted": True}
                if route.request.method == "DELETE"
                else {
                    "authorizationUrl": "https://github.com/oauth-binding-check",
                },
            },
        )

    def show_provider(route: Route) -> None:
        provider_requests.append(route.request)
        route.fulfill(content_type="text/html", body="Binding authorization")

    context.route("**/api/auth/oauth/github/binding", change_binding)
    context.route("**/api/auth/oauth/github/bind", change_binding)
    context.route("https://github.com/oauth-binding-check", show_provider)

    try:
        page.goto(f"{frontend_url}/settings", wait_until="networkidle")
        disconnect_button = page.get_by_role(
            "button", name="Disconnect GitHub", exact=True
        )
        expect(disconnect_button).to_be_enabled()
        expect(page.get_by_text("Google", exact=True)).to_have_count(0)
        expect(page.get_by_text(identity_label, exact=True)).to_be_visible()
        assert page.evaluate(
            "document.documentElement.scrollWidth <= window.innerWidth"
        )
        assert page.get_by_role("group", name="GitHub", exact=True).evaluate(
            """
            row => {
              const bounds = row.getBoundingClientRect();
              return [...row.querySelectorAll('button, p, [title]')].every(
                element => {
                  const rect = element.getBoundingClientRect();
                  return rect.left >= bounds.left && rect.right <= bounds.right;
                },
              );
            }
            """
        ), "Connected account details and controls must fit inside their settings row."
        disconnect_button.scroll_into_view_if_needed()
        page.screenshot(path="/tmp/reseno-oauth-settings-mobile.png", full_page=True)
        page.set_viewport_size({"width": 1440, "height": 900})
        page.screenshot(path="/tmp/reseno-oauth-settings-desktop.png", full_page=True)
        page.set_viewport_size({"width": 375, "height": 812})

        disconnect_button.click()
        expect(
            page.get_by_text("Request failed. Please try again later.", exact=True)
        ).to_be_visible()
        expect(disconnect_button).to_be_enabled()
        expect(page.get_by_text(identity_label, exact=True)).to_be_visible()
        disconnect_button.click()
        connect_button = page.get_by_role(
            "button", name="Connect GitHub", exact=True, include_hidden=True
        )
        expect(connect_button).to_be_enabled()
        expect(page.get_by_text(identity_label, exact=True)).to_have_count(0)
        page.locator(
            '[data-sonner-toast][data-type="success"] [data-close-button]'
        ).click()
        with page.expect_popup() as popup_event:
            connect_button.click()
        popup = popup_event.value
        popup.wait_for_url("https://github.com/oauth-binding-check")
        assert page.url == f"{frontend_url}/settings"
        expect(connect_button).to_be_disabled()
        expect(connect_button).to_have_attribute("aria-busy", "true")
        expect(page.get_by_text(identity_label, exact=True)).to_have_count(0)
        assert [request.method for request in binding_requests] == [
            "DELETE",
            "DELETE",
            "POST",
        ]
        assert all(
            request.headers.get("authorization", "").startswith("Bearer ")
            for request in binding_requests
        )
        assert len(context.pages) == 2
        assert len(provider_requests) == 1
        assert "authorization" not in provider_requests[0].headers
        assert not external_requests
    finally:
        context.close()
