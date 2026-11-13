from __future__ import annotations

import os
from datetime import UTC, datetime

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _export_json(page: Page, *, paused_clock: bool = False) -> None:
    page.get_by_role("button", name="Export", exact=True).click()
    if paused_clock:
        page.clock.run_for(32)
    with page.expect_download():
        page.get_by_role("menuitem", name="JSON", exact=True).click()
    if paused_clock:
        page.clock.run_for(32)
    expect(page.get_by_text("JSON exported", exact=True)).to_be_visible()
    page.mouse.move(0, 0)


def test_notification_keeps_its_identity_and_lifetime_across_workspace_routes(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = authenticated_context(
        browser,
        locale="en-US",
        viewport={"width": 1672, "height": 960},
        reduced_motion="reduce",
    )
    page = context.new_page()
    try:
        page.clock.install(time=datetime(2024, 12, 10, 8, tzinfo=UTC))
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.clock.pause_at(datetime(2024, 12, 10, 10, tzinfo=UTC))
        _export_json(page, paused_clock=True)
        toast = page.locator('[data-sonner-toast][data-type="success"]')
        original = toast.element_handle()
        assert original is not None
        toaster = page.locator("[data-sonner-toaster]")
        expect(toaster).to_have_count(1)
        initial_theme = toaster.get_attribute("data-sonner-theme")
        theme_toggle = page.get_by_role(
            "button", name="Toggle light and dark mode", exact=True
        )
        theme_toggle.click()
        expect(toaster).to_have_attribute(
            "data-sonner-theme", "light" if initial_theme == "dark" else "dark"
        )
        assert original.evaluate("element => element.isConnected")
        theme_toggle.click()
        expect(toaster).to_have_attribute("data-sonner-theme", initial_theme)
        page.clock.run_for(1_500)

        page.get_by_role("button", name="Back to Resumes", exact=True).click()
        page.wait_for_url(f"{frontend_url}/resume")
        expect(page.locator(f'a[href="/resume/{resume_id}"]')).to_be_visible()
        assert original.evaluate("element => element.isConnected")

        page.get_by_role("link", name="Resume Templates", exact=True).click()
        page.wait_for_url(f"{frontend_url}/templates")
        page.locator('a[href="/template/minimal"]').click()
        page.wait_for_url(f"{frontend_url}/template/minimal")
        expect(
            page.get_by_role("button", name="Create Copy", exact=True)
        ).to_be_visible()
        assert original.evaluate("element => element.isConnected")
        expect(page.locator("[data-sonner-toaster]")).to_have_count(1)
        expect(toast).not_to_have_attribute("data-removed", "true")

        page.clock.run_for(2_600)
        expect(
            page.locator('[data-sonner-toast]:not([data-removed="true"])')
        ).to_have_count(0)
        page.clock.run_for(250)
        expect(toast).to_have_count(0)
    finally:
        context.close()


def test_closing_notification_before_navigation_does_not_replay_it(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = authenticated_context(
        browser, locale="en-US", viewport={"width": 1672, "height": 960}
    )
    page = context.new_page()
    try:
        page.clock.install(time=datetime(2024, 12, 10, 8, tzinfo=UTC))
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.clock.pause_at(datetime(2024, 12, 10, 10, tzinfo=UTC))
        _export_json(page, paused_clock=True)
        toast = page.locator('[data-sonner-toast][data-type="success"]')
        toast.locator("[data-close-button]").click()
        expect(toast).to_have_attribute("data-removed", "true")
        page.get_by_role("button", name="Back to Resumes", exact=True).click()
        page.wait_for_url(f"{frontend_url}/resume")
        expect(page.locator(f'a[href="/resume/{resume_id}"]')).to_be_visible()
        expect(
            page.locator('[data-sonner-toast]:not([data-removed="true"])')
        ).to_have_count(0)
        page.clock.run_for(250)
        expect(page.locator("[data-sonner-toast]")).to_have_count(0)
    finally:
        context.close()


def test_logout_does_not_replay_workspace_notifications_on_login(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = authenticated_context(
        browser, locale="en-US", viewport={"width": 1672, "height": 960}
    )
    page = context.new_page()
    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        _export_json(page)
        page.get_by_role("button", name="Log Out", exact=True).click()
        page.wait_for_url(f"{frontend_url}/login")
        expect(page.locator("#username")).to_be_visible()
        page.wait_for_timeout(250)
        assert (
            page.locator('[data-sonner-toast]:not([data-removed="true"])').count() == 0
        )
    finally:
        context.close()


def test_successful_login_does_not_replay_previous_login_error(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(
        locale="en-US", viewport={"width": 1672, "height": 960}
    )
    page = context.new_page()
    try:
        page.goto(f"{frontend_url}/login", wait_until="networkidle")
        page.locator("#username").fill("e2e-owner")
        page.locator("#password").fill("WrongPassword2026")
        page.locator('form button[type="submit"]').click()
        expect(page.locator('[data-sonner-toast][data-type="error"]')).to_be_visible()
        page.locator("#password").fill("E2ePassword2026")
        page.locator('form button[type="submit"]').click()
        page.wait_for_url(f"{frontend_url}/resume")
        expect(page.get_by_role("button", name="New", exact=True)).to_be_visible()
        page.wait_for_timeout(250)
        assert (
            page.locator('[data-sonner-toast]:not([data-removed="true"])').count() == 0
        )
    finally:
        context.close()
