from __future__ import annotations

import os

import pytest
from playwright.sync_api import Browser, Request, Route, expect

from tests.e2e.browser_support import RouteReady

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_login_session_is_shared_with_another_open_tab(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(locale="en-US")
    login_page = context.new_page()
    other_page = context.new_page()

    try:
        for page in (login_page, other_page):
            page.goto(f"{frontend_url}/login", wait_until="networkidle")
            expect(page.locator("#username")).to_be_visible()

        login_page.locator("#username").fill("e2e-owner")
        login_page.locator("#password").fill("E2ePassword2026")
        login_page.get_by_role("button", name="Sign In", exact=True).click()
        login_page.wait_for_url(f"{frontend_url}/resume")
        expect(login_page.locator('input[name="resume-search"]')).to_be_visible()

        other_page.wait_for_url(f"{frontend_url}/resume", timeout=5_000)
        expect(other_page.locator('input[name="resume-search"]')).to_be_visible()
        other_page.reload(wait_until="networkidle")
        other_page.wait_for_url(f"{frontend_url}/resume", timeout=5_000)
        expect(other_page.locator('input[name="resume-search"]')).to_be_visible()

        search = login_page.locator('input[name="resume-search"]')
        search.fill("Retained gallery filter")
        search_node = search.element_handle()
        assert search_node is not None
        expect(login_page).to_have_url(
            f"{frontend_url}/resume?q=Retained+gallery+filter"
        )
        original_url = login_page.url
        previous_token = login_page.evaluate(
            "JSON.parse(localStorage.getItem('reseno-auth-session')).accessToken"
        )
        other_page.get_by_role("button", name="Log Out", exact=True).click()
        other_page.wait_for_url(f"{frontend_url}/login", timeout=5_000)
        expect(other_page.locator("#username")).to_be_visible()
        expired = login_page.get_by_role(
            "dialog", name="Your session has expired", exact=True
        )
        expect(expired).to_be_visible()
        expect(login_page).to_have_url(original_url)
        assert search_node.evaluate("node => node.isConnected")
        expect(search).to_have_value("Retained gallery filter")
        for page in (other_page, login_page):
            assert page.evaluate("localStorage.getItem('reseno-auth-session')") is None

        other_page.reload(wait_until="networkidle")
        expect(other_page.locator("#username")).to_be_visible()
        other_page.locator("#username").fill("e2e-owner")
        other_page.locator("#password").fill("E2ePassword2026")
        other_page.get_by_role("button", name="Sign In", exact=True).click()
        other_page.wait_for_url(f"{frontend_url}/resume")
        expect(expired).not_to_be_visible()
        expect(login_page).to_have_url(original_url)
        assert search.evaluate("(node, original) => node === original", search_node)
        expect(search).to_have_value("Retained gallery filter")
        tokens = [
            page.evaluate(
                "JSON.parse(localStorage.getItem('reseno-auth-session')).accessToken"
            )
            for page in (other_page, login_page)
        ]
        assert tokens[0] == tokens[1]
        assert tokens[0] != previous_token
    finally:
        context.close()


def test_login_session_refresh_is_shared_between_tabs(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(locale="en-US")
    login_page = context.new_page()
    other_page = context.new_page()
    refresh_requests: list[Request] = []
    refresh_routes: list[Route] = []
    refresh_ready = RouteReady()

    def hold_refresh(route: Route) -> None:
        refresh_requests.append(route.request)
        refresh_routes.append(route)
        refresh_ready.set()

    context.route("**/api/auth/refresh", hold_refresh)

    try:
        login_page.goto(f"{frontend_url}/login", wait_until="networkidle")
        login_page.locator("#username").fill("e2e-owner")
        login_page.locator("#password").fill("E2ePassword2026")
        login_page.get_by_role("button", name="Sign In", exact=True).click()
        login_page.wait_for_url(f"{frontend_url}/resume")
        expect(login_page.locator('input[name="resume-search"]')).to_be_visible()
        other_page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        expect(other_page.locator('input[name="resume-search"]')).to_be_visible()
        previous_token = login_page.evaluate(
            "async () => (await import('/src/lib/auth-session.ts')).getAccessToken()"
        )

        for page in (login_page, other_page):
            page.evaluate(
                """
                async () => {
                  const { refreshAuthSession } = await import('/src/lib/auth.ts')
                  window.__refreshResult = null
                  void refreshAuthSession().then(
                    result => { window.__refreshResult = result },
                    error => { window.__refreshResult = { error: error.message } },
                  )
                }
                """
            )
        other_page.wait_for_function(
            """
            async () => (await navigator.locks.query()).pending.some(
              lock => lock.name === 'reseno-auth-refresh'
            )
            """
        )
        refresh_ready.wait(other_page)
        assert len(refresh_routes) == 1
        refresh_routes.pop().continue_()

        current_tokens: list[str] = []
        for page in (login_page, other_page):
            page.wait_for_function("window.__refreshResult !== null")
            assert page.evaluate("window.__refreshResult") is True
            current_tokens.append(
                page.evaluate(
                    "async () => (await import('/src/lib/auth-session.ts'))"
                    ".getAccessToken()"
                )
            )
            with page.expect_response("**/api/resumes") as response:
                page.evaluate(
                    """
                    async () => {
                      const { apiRoutes, requestApi } = await import(
                        '/src/lib/api-client.ts'
                      )
                      await requestApi(apiRoutes.resumes, { cacheTtlMs: 0 })
                    }
                    """
                )
            assert response.value.status == 200
            assert page.url == f"{frontend_url}/resume"
            expect(page.locator('input[name="resume-search"]')).to_be_visible()
        assert len(set(current_tokens)) == 1
        assert current_tokens[0] != previous_token
        assert len(refresh_requests) == 1
        assert refresh_requests[0].method == "POST"
    finally:
        context.close()
