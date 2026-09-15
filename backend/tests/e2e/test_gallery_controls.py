from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from playwright.sync_api import Browser, expect
from playwright.sync_api import Error as PlaywrightError

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_resume_gallery_hides_card_delete_actions_for_multi_selection(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()
    extra_resume_id: str | None = None

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": "Multi-selection delete regression",
            },
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
        bulk_delete = page.get_by_role("button", name="批量删除", exact=True)
        bulk_delete.wait_for(state="visible")
        expect(bulk_delete).to_have_attribute("data-variant", "destructive")
        expect(bulk_delete).to_have_attribute("data-size", "default")
        new_resume = page.get_by_role("button", name="新建", exact=True)
        toolbar_height_delta = page.evaluate(
            """
            ([bulkDelete, newResume]) =>
              bulkDelete.getBoundingClientRect().height -
              newResume.getBoundingClientRect().height
            """,
            [bulk_delete.element_handle(), new_resume.element_handle()],
        )
        assert abs(toolbar_height_delta) <= 1, toolbar_height_delta
        assert page.locator('button[aria-label="确认删除"]').count() == 0

        resume_cards.nth(1).click()
        assert page.locator('button[aria-label="确认删除"]').count() == 1
    finally:
        if extra_resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{extra_resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{extra_resume_id}")
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize(
    ("gallery_path", "search_name", "search_placeholder_key"),
    [
        ("/resume", "resume-search", "searchResumesPlaceholder"),
        ("/templates", "template-search", "searchTemplatesPlaceholder"),
    ],
)
def test_gallery_search_scope_stays_inside_input(
    browser: Browser,
    workspace_servers: tuple[str, str],
    gallery_path: str,
    search_name: str,
    search_placeholder_key: str,
) -> None:
    frontend_url, _ = workspace_servers
    messages = json.loads(
        (Path(__file__).parents[3] / "frontend/src/i18n/locales/zh.json").read_text(
            encoding="utf-8"
        )
    )
    search_placeholder = messages[search_placeholder_key]
    context = _authenticated_context(browser, locale="zh-CN")
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}{gallery_path}", wait_until="networkidle")
        search = page.locator(f'input[name="{search_name}"]')
        expect(search).to_have_attribute("placeholder", search_placeholder)
        expect(page.get_by_text(search_placeholder, exact=True)).to_have_count(0)
    finally:
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize(
    ("gallery_path", "create_path"),
    [
        ("/resume", "/api/resumes"),
        ("/templates", "/api/templates"),
    ],
)
def test_gallery_new_button_keeps_its_geometry_while_creating(
    browser: Browser,
    workspace_servers: tuple[str, str],
    gallery_path: str,
    create_path: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}{gallery_path}", wait_until="networkidle")
        page.evaluate(
            """
            createPath => {
              const originalFetch = window.fetch.bind(window);
              window.__rejectGalleryCreate = null;
              window.fetch = async (input, init) => {
                const request = new Request(input, init);
                if (
                  request.method === "POST" &&
                  new URL(request.url).pathname === createPath
                ) {
                  return await new Promise((_, reject) => {
                    window.__rejectGalleryCreate = () => {
                      reject(new DOMException("Aborted", "AbortError"));
                    };
                  });
                }
                return originalFetch(input, init);
              };
            }
            """,
            create_path,
        )
        new_button = page.get_by_role("button", name="新建", exact=True)
        button = new_button.element_handle()
        assert button
        before = button.evaluate(
            """
            element => {
              const rect = element.getBoundingClientRect();
              return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
            }
            """
        )

        new_button.click()
        if gallery_path == "/resume":
            dialog = page.get_by_role("dialog")
            dialog.get_by_role("combobox", name="简历语言", exact=True).click()
            page.get_by_role("option", name="中文", exact=True).click()
            dialog.get_by_role("button", name="创建简历", exact=True).click()

        page.wait_for_function(
            "button => button.getAttribute('aria-busy') === 'true'",
            arg=button,
        )
        after = button.evaluate(
            """
            element => {
              const rect = element.getBoundingClientRect();
              return {x: rect.x, y: rect.y, width: rect.width, height: rect.height};
            }
            """
        )
        assert button.evaluate("element => element.innerText") == "新建"
        assert button.evaluate("element => element.getAttribute('aria-label')") == (
            "创建中…"
        )
        assert (
            button.evaluate(
                "element => Boolean(element.querySelector('[role=\"status\"]'))"
            )
            is False
        )
        assert all(
            abs(after[key] - before[key]) <= 0.5
            for key in ("x", "y", "width", "height")
        ), {"before": before, "after": after}
    finally:
        try:
            page.evaluate("window.__rejectGalleryCreate?.()")
        except PlaywrightError:
            pass
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize(
    ("gallery_path", "search_name"),
    [
        ("/resume", "resume-search"),
        ("/templates", "template-search"),
    ],
)
def test_gallery_search_commits_chromium_ime_without_leaking_composition(
    browser: Browser,
    workspace_servers: tuple[str, str],
    gallery_path: str,
    search_name: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, locale="zh-CN")
    page = context.new_page()

    try:
        page.goto(
            f"{frontend_url}{gallery_path}?page=2",
            wait_until="networkidle",
        )
        search = page.locator(f'input[name="{search_name}"]')
        search.focus()
        cdp = context.new_cdp_session(page)

        cdp.send(
            "Input.imeSetComposition",
            {
                "text": "ni",
                "selectionStart": 2,
                "selectionEnd": 2,
                "replacementStart": 0,
                "replacementEnd": 0,
            },
        )

        expect(search).to_have_value("ni")
        page.wait_for_timeout(100)
        assert parse_qs(urlparse(page.url).query) == {"page": ["2"]}

        cdp.send("Input.insertText", {"text": "你"})
        page.wait_for_function(
            "new URLSearchParams(window.location.search).get('q') === '你'"
        )

        expect(search).to_have_value("你")
        assert parse_qs(urlparse(page.url).query) == {"q": ["你"]}
    finally:
        context.close()


@pytest.mark.browser_smoke
def test_resume_gallery_search_keeps_latest_rapid_input(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, locale="zh-CN")
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/resume?page=2", wait_until="networkidle")
        search = page.locator('input[name="resume-search"]')
        search.focus()

        page.keyboard.type("ab")
        page.keyboard.press("Backspace")

        assert search.input_value() == "a"
        page.wait_for_function(
            "new URLSearchParams(window.location.search).get('q') === 'a'"
        )
        page.wait_for_timeout(250)
        expect(search).to_have_value("a")
        assert parse_qs(urlparse(page.url).query) == {"q": ["a"]}
    finally:
        context.close()


@pytest.mark.browser_smoke
def test_gallery_pagination_keeps_active_page_clear_of_previous_action(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 800, "height": 900})
    page = context.new_page()
    extra_resume_ids: list[str] = []

    try:
        for index in range(8):
            create_response = page.request.post(
                f"{frontend_url}/api/resumes",
                data={
                    "documentLocale": "zh",
                    "title": f"Pagination spacing regression {index + 1}",
                },
            )
            assert create_response.ok
            create_payload = create_response.json()
            assert create_payload["code"] == 0
            extra_resume_ids.append(create_payload["data"]["resume"]["id"])

        page.goto(
            f"{frontend_url}/resume?q=Pagination",
            wait_until="networkidle",
        )
        search = page.locator('input[name="resume-search"]')
        expect(search).to_have_value("Pagination")
        pagination = page.locator('[data-slot="pagination-content"]')
        pagination.wait_for(state="visible")
        pagination_links = pagination.locator('[data-slot="pagination-link"]')
        previous_link = pagination_links.first
        next_link = pagination_links.last
        active_page_link = pagination.locator('[aria-current="page"]')
        inactive_page_link = pagination.get_by_role("link", name="2", exact=True)
        previous_label = previous_link.locator("span")
        next_url = urlparse(next_link.get_attribute("href") or "")
        inactive_page_url = urlparse(inactive_page_link.get_attribute("href") or "")

        assert previous_link.get_attribute("href") is None
        assert previous_link.get_attribute("tabindex") == "-1"
        assert next_url.path == "/resume"
        assert parse_qs(next_url.query) == {
            "q": ["Pagination"],
            "page": ["2"],
        }
        assert inactive_page_url == next_url

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

        inactive_page_link.click()
        page.wait_for_url("**/resume?q=Pagination&page=2")
        second_page_previous = page.locator(
            '[data-slot="pagination-content"] [data-slot="pagination-link"]'
        ).first
        expect(second_page_previous).to_have_attribute(
            "href",
            "/resume?q=Pagination",
        )
        previous_url = urlparse(second_page_previous.get_attribute("href") or "")
        assert previous_url.path == "/resume"
        assert parse_qs(previous_url.query) == {"q": ["Pagination"]}

        page.go_back(wait_until="networkidle")
        restored_url = urlparse(page.url)
        assert restored_url.path == "/resume"
        assert parse_qs(restored_url.query) == {"q": ["Pagination"]}
        expect(search).to_have_value("Pagination")

        page.go_forward(wait_until="networkidle")
        forwarded_url = urlparse(page.url)
        assert forwarded_url.path == "/resume"
        assert parse_qs(forwarded_url.query) == {
            "q": ["Pagination"],
            "page": ["2"],
        }
        expect(search).to_have_value("Pagination")
    finally:
        for resume_id in extra_resume_ids:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()
