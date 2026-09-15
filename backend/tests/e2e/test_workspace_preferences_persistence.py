from __future__ import annotations

import os
import re
import time
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Browser, Page, Request, Route, expect

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


@pytest.fixture
def workspace_preferences_page(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> Iterator[tuple[Page, dict[str, Any]]]:
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        color_scheme="light",
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    preferences: dict[str, Any] = {
        "settings": {
            "theme": "light",
            "agentSettings": {
                "defaultModelConfigId": "llm-shared-preferences",
                "responseLanguage": "en",
                "behaviorMode": "strict",
                "confirmationMode": "suggestOnly",
            },
        },
        "writes": [],
        "localeWrites": [],
    }

    def load_workspace(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["theme"] = preferences["settings"]["theme"]
        if "agentSettings" in payload["data"]:
            payload["data"]["agentSettings"] = preferences["settings"]["agentSettings"]
            payload["data"]["modelConfigs"] = [
                {
                    "id": "llm-shared-preferences",
                    "provider": "openai",
                    "nickname": "Shared preferences model",
                    "model": "preferences-model",
                    "supportsTools": True,
                }
            ]
        route.fulfill(response=response, json=payload)

    def save_preferences(route: Route) -> None:
        assert route.request.method == "PUT"
        settings = route.request.post_data_json["settings"]
        locale = parse_qs(urlparse(route.request.url).query)["locale"][0]
        preferences["writes"].append(settings)
        preferences["localeWrites"].append(locale)
        preferences["settings"].update(settings)
        route.fulfill(
            json={
                "code": 0,
                "message": "OK",
                "data": {"locale": locale, **preferences["settings"]},
            }
        )

    page.route("**/api/workspace/pages/*", load_workspace)
    page.route("**/api/workspace/user-settings*", save_preferences)
    try:
        yield page, preferences
    finally:
        context.close()


@pytest.mark.browser_smoke
def test_workspace_preferences_gallery_theme_preserves_saved_agent_settings(
    workspace_preferences_page: tuple[Page, dict[str, Any]],
    workspace_servers: tuple[str, str],
) -> None:
    page, preferences = workspace_preferences_page
    frontend_url, _ = workspace_servers
    original_agent_settings = dict(preferences["settings"]["agentSettings"])
    page.goto(f"{frontend_url}/resume", wait_until="networkidle")

    with page.expect_response("**/api/workspace/user-settings*"):
        page.get_by_role("button", name="切换日间 / 夜间模式", exact=True).click()

    assert preferences["settings"]["theme"] == "dark"
    assert preferences["settings"]["agentSettings"] == original_agent_settings
    page.locator('a[href="/settings"]').click()
    page.wait_for_url(f"{frontend_url}/settings")
    page.get_by_role("tab", name="AI 助手", exact=True).click()
    expect(page.get_by_role("combobox", name="建议风格", exact=True)).to_have_text(
        "保守"
    )
    expect(page.get_by_role("combobox", name="修改确认方式", exact=True)).to_have_text(
        "仅给建议"
    )
    expect(page.get_by_role("combobox", name="默认模型", exact=True)).to_contain_text(
        "Shared preferences model"
    )


@pytest.mark.browser_smoke
def test_workspace_preferences_follow_route_changes_and_history(
    workspace_preferences_page: tuple[Page, dict[str, Any]],
    workspace_servers: tuple[str, str],
) -> None:
    page, preferences = workspace_preferences_page
    frontend_url, resume_id = workspace_servers
    page.goto(f"{frontend_url}/settings?tab=agent", wait_until="networkidle")
    page.get_by_role("combobox", name="建议风格", exact=True).click()
    with page.expect_response("**/api/workspace/user-settings*"):
        page.get_by_role("option", name="大幅优化", exact=True).click()
    page.get_by_role("tab", name="通用设置", exact=True).click()
    page.get_by_role("combobox", name="主题", exact=True).click()
    with page.expect_response("**/api/workspace/user-settings*"):
        page.get_by_role("option", name="夜间", exact=True).click()
    page.evaluate("window.__preferencesDocument = document")

    for route_path, back_label in (
        ("/resume", None),
        (f"/resume/{resume_id}", "返回简历列表"),
        ("/templates", None),
        ("/template/minimal", "返回模板列表"),
        ("/settings", None),
    ):
        page.locator(f'a[href="{route_path}"]').click()
        page.wait_for_url(f"{frontend_url}{route_path}")
        page.wait_for_load_state("networkidle")
        expect(page.locator("html")).to_have_class(re.compile(r"\bdark\b"))
        assert preferences["settings"]["agentSettings"]["behaviorMode"] == (
            "aggressive"
        )
        if back_label:
            gallery_path = (
                "/resume" if route_path.startswith("/resume/") else "/templates"
            )
            page.go_back()
            page.wait_for_url(f"{frontend_url}{gallery_path}")
            page.wait_for_load_state("networkidle")
            expect(page.locator("html")).to_have_class(re.compile(r"\bdark\b"))
            page.go_forward()
            page.wait_for_url(f"{frontend_url}{route_path}")
            page.wait_for_load_state("networkidle")
            expect(page.locator("html")).to_have_class(re.compile(r"\bdark\b"))
            page.get_by_role("button", name=back_label, exact=True).click()
            page.wait_for_url(f"{frontend_url}{gallery_path}")
            page.wait_for_load_state("networkidle")

    expect(page.get_by_role("combobox", name="主题", exact=True)).to_have_text("夜间")
    page.get_by_role("tab", name="AI 助手", exact=True).click()
    expect(page.get_by_role("combobox", name="建议风格", exact=True)).to_have_text(
        "大幅优化"
    )
    expect(page.get_by_role("combobox", name="修改确认方式", exact=True)).to_have_text(
        "仅给建议"
    )
    assert page.evaluate("window.__preferencesDocument === document")
    assert len(preferences["writes"]) == 2


@pytest.mark.browser_smoke
def test_workspace_preferences_queue_keeps_latest_change_before_navigation(
    workspace_preferences_page: tuple[Page, dict[str, Any]],
    workspace_servers: tuple[str, str],
) -> None:
    page, preferences = workspace_preferences_page
    frontend_url, _ = workspace_servers
    held_routes: list[Route] = []
    page.goto(f"{frontend_url}/settings?tab=agent", wait_until="networkidle")
    page.route(
        "**/api/workspace/user-settings*", lambda route: held_routes.append(route)
    )

    page.get_by_role("combobox", name="建议风格", exact=True).click()
    page.get_by_role("option", name="大幅优化", exact=True).click()
    deadline = time.monotonic() + 3
    while not held_routes and time.monotonic() < deadline:
        page.wait_for_timeout(20)
    assert len(held_routes) == 1

    page.get_by_role("combobox", name="建议风格", exact=True).click()
    page.get_by_role("option", name="平衡", exact=True).click()
    page.get_by_role("combobox", name="修改确认方式", exact=True).click()
    page.get_by_role("option", name="始终确认", exact=True).click()
    expect(page.get_by_role("combobox", name="建议风格", exact=True)).to_have_text(
        "平衡"
    )
    expect(page.get_by_role("combobox", name="修改确认方式", exact=True)).to_have_text(
        "始终确认"
    )
    assert len(held_routes) == 1

    page.locator('a[href="/templates"]').click()
    page.wait_for_timeout(100)
    assert urlparse(page.url).path == "/settings"
    for expected_count in range(1, 4):
        deadline = time.monotonic() + 3
        while len(held_routes) < expected_count and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert len(held_routes) == expected_count
        held_routes[expected_count - 1].fallback()

    page.wait_for_url(f"{frontend_url}/templates")
    page.wait_for_load_state("networkidle")
    assert preferences["settings"]["theme"] == "light"
    assert preferences["settings"]["agentSettings"]["behaviorMode"] == "balanced"
    assert preferences["settings"]["agentSettings"]["confirmationMode"] == "always"
    page.goto(f"{frontend_url}/settings?tab=agent", wait_until="networkidle")
    expect(page.get_by_role("combobox", name="建议风格", exact=True)).to_have_text(
        "平衡"
    )
    expect(page.get_by_role("combobox", name="修改确认方式", exact=True)).to_have_text(
        "始终确认"
    )


@pytest.mark.browser_smoke
def test_workspace_preferences_latest_failure_rolls_back_every_route(
    workspace_preferences_page: tuple[Page, dict[str, Any]],
    workspace_servers: tuple[str, str],
) -> None:
    page, preferences = workspace_preferences_page
    frontend_url, _ = workspace_servers
    page.goto(f"{frontend_url}/settings?tab=agent", wait_until="networkidle")
    page.get_by_role("combobox", name="建议风格", exact=True).click()
    with page.expect_response("**/api/workspace/user-settings*"):
        page.get_by_role("option", name="大幅优化", exact=True).click()
    page.get_by_role("tab", name="通用设置", exact=True).click()

    page.route(
        "**/api/workspace/user-settings*",
        lambda route: route.fulfill(
            status=503,
            json={"code": 50000, "message": "REQUEST_FAILED", "data": None},
        ),
    )
    page.get_by_role("combobox", name="主题", exact=True).click()
    with page.expect_response("**/api/workspace/user-settings*"):
        page.get_by_role("option", name="夜间", exact=True).click()
    expect(page.locator("html")).not_to_have_class(re.compile(r"\bdark\b"))
    expect(page.get_by_role("combobox", name="主题", exact=True)).to_have_text("日间")

    for route_path in ("/resume", "/templates", "/settings"):
        page.locator(f'a[href="{route_path}"]').click()
        page.wait_for_url(f"{frontend_url}{route_path}")
        page.wait_for_load_state("networkidle")
        expect(page.locator("html")).not_to_have_class(re.compile(r"\bdark\b"))
    expect(page.get_by_role("combobox", name="主题", exact=True)).to_have_text("日间")
    page.get_by_role("tab", name="AI 助手", exact=True).click()
    page.get_by_role("combobox", name="建议风格", exact=True).click()
    with page.expect_response("**/api/workspace/user-settings*"):
        page.get_by_role("option", name="平衡", exact=True).click()
    expect(page.get_by_role("combobox", name="建议风格", exact=True)).to_have_text(
        "大幅优化"
    )
    assert preferences["settings"]["theme"] == "light"
    assert preferences["settings"]["agentSettings"]["behaviorMode"] == "aggressive"


@pytest.mark.browser_smoke
def test_workspace_preferences_locale_changes_share_persistence_and_rollback(
    workspace_preferences_page: tuple[Page, dict[str, Any]],
    workspace_servers: tuple[str, str],
) -> None:
    page, preferences = workspace_preferences_page
    frontend_url, _ = workspace_servers
    page.goto(f"{frontend_url}/resume", wait_until="networkidle")

    page.get_by_role("combobox", name="语言", exact=True).click()
    with page.expect_response("**/api/workspace/user-settings*", timeout=5000):
        page.get_by_role("option", name="EN", exact=True).click()
    expect(page.get_by_role("combobox", name="Language", exact=True)).to_have_text("EN")
    assert preferences["localeWrites"] == ["en"]
    assert page.evaluate("localStorage.getItem('reseno-locale')") == "en"

    page.locator('a[href="/settings"]').click()
    page.wait_for_url(f"{frontend_url}/settings")
    expect(page.locator('[data-workspace-view="settings"]')).to_be_visible()
    language = page.get_by_role("combobox", name="Language", exact=True)
    expect(language).to_have_text("EN")
    language.click()
    with page.expect_response("**/api/workspace/user-settings*", timeout=5000):
        page.get_by_role("option", name="中文", exact=True).click()
    expect(page.get_by_role("tab", name="通用设置", exact=True)).to_be_visible()
    assert preferences["localeWrites"] == ["en", "zh"]
    assert page.evaluate("localStorage.getItem('reseno-locale')") == "zh"

    page.locator('a[href="/templates"]').click()
    page.wait_for_url(f"{frontend_url}/templates")
    expect(page.locator('[data-workspace-view="templates"]')).to_be_visible()
    language = page.get_by_role("combobox", name="语言", exact=True)
    expect(language).to_have_text("中文")
    failed_writes: list[Request] = []

    def fail_locale_save(route: Route) -> None:
        failed_writes.append(route.request)
        route.fulfill(
            status=503,
            json={"code": 50000, "message": "REQUEST_FAILED", "data": None},
        )

    page.route("**/api/workspace/user-settings*", fail_locale_save)
    language.click()
    with page.expect_response("**/api/workspace/user-settings*", timeout=5000):
        page.get_by_role("option", name="EN", exact=True).click()
    expect(page.get_by_role("combobox", name="语言", exact=True)).to_have_text("中文")
    page.wait_for_function("localStorage.getItem('reseno-locale') === 'zh'")
    assert len(failed_writes) == 1
    assert preferences["localeWrites"] == ["en", "zh"]
    page.locator('a[href="/settings"]').click()
    page.wait_for_url(f"{frontend_url}/settings")
    expect(page.locator('[data-workspace-view="settings"]')).to_be_visible()
    expect(page.get_by_role("combobox", name="语言", exact=True)).to_have_text("中文")
    assert preferences["settings"]["agentSettings"]["behaviorMode"] == "strict"


@pytest.mark.browser_smoke
def test_workspace_preferences_use_restored_locale_after_password_login(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = browser.new_context(
        locale="en-US", viewport={"width": 1440, "height": 900}
    )
    context.add_init_script("localStorage.setItem('reseno-locale', 'zh')")
    page = context.new_page()
    held_catalogs: list[Route] = []
    settings_requests: list[Request] = []
    page.route(
        "**/src/i18n/locales/zh.json*",
        lambda route: held_catalogs.append(route),
        times=1,
    )

    def save_preferences(route: Route) -> None:
        settings_requests.append(route.request)
        settings = route.request.post_data_json["settings"]
        locale = parse_qs(urlparse(route.request.url).query)["locale"][0]
        route.fulfill(
            json={"code": 0, "message": "OK", "data": {"locale": locale, **settings}}
        )

    page.route("**/api/workspace/user-settings*", save_preferences)
    try:
        page.goto(f"{frontend_url}/login", wait_until="networkidle")
        page.locator("#username").fill("e2e-owner")
        page.locator("#password").fill("E2ePassword2026")
        page.locator('form button[type="submit"]').click()
        deadline = time.monotonic() + 3
        while not held_catalogs and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert len(held_catalogs) == 1
        assert page.url == f"{frontend_url}/login"
        expect(page.locator('form button[type="submit"]')).to_be_disabled()
        held_catalogs.pop().continue_()
        page.wait_for_url(f"{frontend_url}/resume")
        expect(page.get_by_role("combobox", name="语言", exact=True)).to_be_visible()

        with page.expect_response("**/api/workspace/user-settings*"):
            page.get_by_role("button", name="切换日间 / 夜间模式", exact=True).click()
        assert len(settings_requests) == 1
        assert parse_qs(urlparse(settings_requests[0].url).query)["locale"] == ["zh"]
        expect(page.get_by_role("combobox", name="语言", exact=True)).to_have_text(
            "中文"
        )
        assert page.evaluate("localStorage.getItem('reseno-locale')") == "zh"
    finally:
        context.close()
