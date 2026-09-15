from __future__ import annotations

import os
import re
import time
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Request, Route, expect

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_template_language_select_keeps_default_templates_independent(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1280, "height": 800})
    page = context.new_page()
    created_resume_ids: list[str] = []

    def delay_default_template_response(route: Route) -> None:
        response = route.fetch()
        time.sleep(0.25)
        route.fulfill(response=response)

    def select_template_language(document_locale: str) -> None:
        labels = {
            "zh": re.compile(r"^(Chinese template|中文模板)$"),
            "en": re.compile(r"^(English template|英文模板)$"),
        }
        page.get_by_role(
            "combobox",
            name=re.compile(r"^(Resume language|简历语言)$"),
        ).click()
        page.get_by_role("option", name=labels[document_locale]).click()

    def set_default(template_id: str, document_locale: str) -> None:
        card = page.locator(f'[data-gallery-item-id="{template_id}"]')
        button = card.get_by_role(
            "button",
            name=re.compile(r"^(Set as Default|设为默认模板)$"),
        )
        button.evaluate(
            """
            button => {
              const frames = [];
              window.__galleryDefaultButtonFrames = frames;
              const startedAt = performance.now();
              const sample = () => {
                frames.push({
                  isBusy: button.getAttribute('aria-busy') === 'true',
                  hasSpinner: Boolean(button.querySelector('[role="status"]')),
                });
                if (performance.now() - startedAt < 500) {
                  requestAnimationFrame(sample);
                }
              };
              requestAnimationFrame(sample);
            }
            """
        )
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == "/api/workspace/default-template"
            )
        ) as response_info:
            button.click()
        page.wait_for_timeout(300)
        frames = page.evaluate("window.__galleryDefaultButtonFrames")
        assert any(frame["isBusy"] for frame in frames)
        assert not any(frame["hasSpinner"] for frame in frames)
        assert response_info.value.request.post_data_json == {
            "documentLocale": document_locale,
            "templateId": template_id,
        }
        expect(
            card.get_by_text(
                re.compile(r"^(Default Template|默认模板)$"),
                exact=True,
            )
        ).to_be_visible()

    try:
        page.route(
            "**/api/workspace/default-template",
            delay_default_template_response,
        )
        page.goto(f"{frontend_url}/templates", wait_until="networkidle")

        select_template_language("zh")
        set_default("modern", "zh")
        select_template_language("en")
        set_default("academic", "en")

        route_response = page.request.get(
            f"{frontend_url}/api/workspace/pages/templates"
        )
        assert route_response.ok
        assert route_response.json()["data"]["defaultTemplateIds"] == {
            "zh": "modern",
            "en": "academic",
        }

        for document_locale, template_id in (
            ("zh", "modern"),
            ("en", "academic"),
        ):
            create_response = page.request.post(
                f"{frontend_url}/api/resumes",
                data={"documentLocale": document_locale},
            )
            assert create_response.ok
            resume = create_response.json()["data"]["resume"]
            created_resume_ids.append(str(resume["id"]))
            assert resume["documentLocale"] == document_locale
            assert resume["template"] == template_id
    finally:
        for document_locale in ("zh", "en"):
            page.request.put(
                f"{frontend_url}/api/workspace/default-template",
                data={
                    "documentLocale": document_locale,
                    "templateId": "minimal",
                },
            )
        for resume_id in created_resume_ids:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_template_selection_keeps_default_actions_visible_but_disabled(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()
    default_template_requests: list[str] = []

    def track_default_template_requests(request: Request) -> None:
        if (
            request.method == "PUT"
            and urlparse(request.url).path == "/api/workspace/default-template"
        ):
            default_template_requests.append(request.url)

    page.on("request", track_default_template_requests)

    try:
        page.goto(f"{frontend_url}/templates", wait_until="networkidle")
        default_card = page.locator('[data-gallery-item-id="minimal"]')
        action = page.locator('[data-gallery-item-id="modern"]').get_by_role(
            "button",
            name="设为默认模板",
            exact=True,
        )
        default_badge = default_card.get_by_text("默认模板", exact=True)
        expect(action).to_be_visible()
        expect(action).to_be_enabled()
        expect(default_badge).to_be_visible()
        initial_box = action.bounding_box()
        assert initial_box is not None

        page.get_by_role("button", name="选择", exact=True).click()
        expect(page.get_by_role("button", name="取消选择", exact=True)).to_be_visible()
        expect(action).to_be_visible()
        expect(action).to_be_disabled()
        expect(default_badge).to_be_visible()
        selecting_box = action.bounding_box()
        assert selecting_box is not None
        for key in ("x", "y", "width", "height"):
            assert abs(initial_box[key] - selecting_box[key]) <= 1

        action.evaluate("button => button.click()")
        page.wait_for_timeout(100)
        assert default_template_requests == []

        page.get_by_role("button", name="取消选择", exact=True).click()
        expect(action).to_be_enabled()
    finally:
        context.close()
