"""Preference UI transactions using the installed React runtime in Chromium."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect, sync_playwright

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]
FRONTEND_ROOT = Path(__file__).resolve().parents[3] / "frontend"


@pytest.fixture(scope="module")
def preferences_fixture_script() -> str:
    return subprocess.run(
        ["node", "scripts/build-workspace-preferences-react-fixture.mjs"],
        cwd=FRONTEND_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.fixture(scope="module")
def preferences_browser() -> Iterator[Browser]:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def preferences_page(
    preferences_browser: Browser,
    preferences_fixture_script: str,
) -> Iterator[Page]:
    page = preferences_browser.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route(
        "http://preferences.test/",
        lambda route: route.fulfill(
            content_type="text/html", body='<div id="root"></div>'
        ),
    )
    page.goto("http://preferences.test/")
    page.add_script_tag(content=preferences_fixture_script)
    expect(page.locator("#workspace-locale")).to_have_text("zh")
    try:
        yield page
    finally:
        page.close()
    assert errors == []


def _settle_preferences(page: Page) -> None:
    page.evaluate("""async () => {
        await preferencesTest.flush();
        await new Promise(resolve => requestAnimationFrame(
            () => requestAnimationFrame(resolve),
        ));
    }""")


def test_immediate_locale_save_failure_restores_visible_locale(
    preferences_page: Page,
) -> None:
    page = preferences_page
    page.evaluate("document.querySelector('button').click()")
    page.wait_for_function("preferencesTest.read().writes.length === 1")
    _settle_preferences(page)
    expect(page.locator("#workspace-locale")).to_have_text("zh")
    assert page.evaluate("preferencesTest.read().preferences.locale") == "zh"


def test_successful_locale_change_commits_once(preferences_page: Page) -> None:
    page = preferences_page
    page.evaluate("preferencesTest.mode('success')")
    page.get_by_role("button", name="English", exact=True).click()
    expect(page.locator("#workspace-locale")).to_have_text("en")
    _settle_preferences(page)
    expect(page.locator("#workspace-locale")).to_have_text("en")
    state = page.evaluate("preferencesTest.read()")
    assert state["preferences"]["locale"] == "en"
    assert state["writes"] == [{"locale": "en", "settings": {}}]


def test_slow_locale_save_failure_restores_visible_locale(
    preferences_page: Page,
) -> None:
    page = preferences_page
    page.evaluate("preferencesTest.mode('hold')")
    page.get_by_role("button", name="English", exact=True).click()
    page.wait_for_function("preferencesTest.read().pending === 1")
    expect(page.locator("#workspace-locale")).to_have_text("en")
    page.evaluate("preferencesTest.settle(false)")
    _settle_preferences(page)
    expect(page.locator("#workspace-locale")).to_have_text("zh")
    assert page.evaluate("preferencesTest.read().preferences.locale") == "zh"
    assert page.evaluate("preferencesTest.read().writes.length") == 1


def test_latest_locale_choice_survives_an_older_save_failure(
    preferences_page: Page,
) -> None:
    page = preferences_page
    page.evaluate("preferencesTest.mode('hold')")
    page.get_by_role("button", name="English", exact=True).click()
    page.wait_for_function("preferencesTest.read().pending === 1")
    page.get_by_role("button", name="中文", exact=True).click()
    expect(page.locator("#workspace-locale")).to_have_text("zh")
    page.evaluate("preferencesTest.mode('success'); preferencesTest.settle(false)")
    _settle_preferences(page)
    expect(page.locator("#workspace-locale")).to_have_text("zh")
    state = page.evaluate("preferencesTest.read()")
    assert state["locale"] == "zh"
    assert state["preferences"]["locale"] == "zh"
    assert [write["locale"] for write in state["writes"]] == ["en", "zh"]


def test_same_batch_locale_choices_keep_only_the_last_intent(
    preferences_page: Page,
) -> None:
    page = preferences_page
    page.evaluate("""() => {
        const buttons = document.querySelectorAll('button');
        buttons[0].click();
        buttons[1].click();
    }""")
    _settle_preferences(page)
    expect(page.locator("#workspace-locale")).to_have_text("zh")
    state = page.evaluate("preferencesTest.read()")
    assert state["locale"] == "zh"
    assert state["preferences"]["locale"] == "zh"
    assert state["writes"] == []


def test_restored_app_locale_is_used_by_the_next_preference_write(
    preferences_page: Page,
) -> None:
    page = preferences_page
    page.evaluate("preferencesTest.restoreLocale('en')")
    expect(page.locator("#workspace-locale")).to_have_text("en")
    assert page.evaluate("preferencesTest.read().writes") == []
    page.evaluate("preferencesTest.mode('success')")
    page.get_by_role("button", name="Dark", exact=True).click()
    page.wait_for_function("preferencesTest.read().writes.length === 1")
    _settle_preferences(page)
    expect(page.locator("#workspace-locale")).to_have_text("en")
    state = page.evaluate("preferencesTest.read()")
    assert state["locale"] == "en"
    assert state["preferences"]["locale"] == "en"
    assert state["writes"] == [{"locale": "en", "settings": {"theme": "dark"}}]


def test_unmounted_preferences_cannot_restore_a_late_locale_save(
    preferences_page: Page,
) -> None:
    page = preferences_page
    page.evaluate("preferencesTest.mode('hold')")
    page.get_by_role("button", name="English", exact=True).click()
    page.wait_for_function("preferencesTest.read().pending === 1")
    page.evaluate("preferencesTest.unmount()")
    expect(page.locator("#outside-locale")).to_have_text("zh")
    page.evaluate("preferencesTest.settle(true)")
    _settle_preferences(page)
    expect(page.locator("#workspace-locale")).to_have_count(0)
    expect(page.locator("#outside-locale")).to_have_text("zh")
    assert page.evaluate("preferencesTest.read().writes.length") == 1
