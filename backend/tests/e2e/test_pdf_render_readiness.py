"""Export readiness with real delayed fonts, images, and pagination."""

from __future__ import annotations

import base64
import io
import os
from time import monotonic
from typing import Any, Literal

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, Route
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from pypdf import PdfReader

from app.services.pdf import _wait_for_resume_render
from tests.e2e.browser_support import authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)

AVATAR_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAF"
    "gAI/ScLbtAAAAABJRU5ErkJggg=="
)


def _create_render_url(
    context: BrowserContext,
    frontend_url: str,
    *,
    avatar: bool,
) -> str:
    response = context.request.post(
        f"{frontend_url}/api/resumes",
        data={
            "documentLocale": "en",
            "title": "Render readiness",
            "template": "minimal",
        },
    )
    assert response.ok
    created: dict[str, Any] = response.json()["data"]["resume"]
    resume_id = created["id"]
    resume = created["resume"]
    resume["basic"]["name"] = "Export Readiness"
    resume["basic"]["avatar"] = (
        f"{frontend_url}/render-readiness-avatar.png" if avatar else ""
    )
    resume["sections"] = [
        {
            "id": "readiness-content",
            "kind": "simple_list",
            "title": "Experience",
            "items": [
                {
                    "id": "readiness-paragraphs",
                    "content": "".join(
                        f"<p>PAGE_SENTINEL_{index:02d} Reliable document rendering "
                        "keeps every paragraph in its final page.</p>"
                        for index in range(80)
                    ),
                }
            ],
        }
    ]
    saved = context.request.put(
        f"{frontend_url}/api/resumes/{resume_id}",
        data={
            key: created[key]
            for key in (
                "documentLocale",
                "title",
                "resume",
                "jobBrief",
                "template",
                "templateSettings",
                "typography",
            )
        },
    )
    assert saved.ok, saved.text()
    return f"{frontend_url}/pdf-export?resumeId={resume_id}&documentLocale=en"


def _assert_multipage_pdf(page: Page) -> None:
    page_count = page.locator('[data-export-root="resume-page"]').count()
    assert page_count > 1
    page.emulate_media(media="print")
    reader = PdfReader(io.BytesIO(page.pdf(prefer_css_page_size=True)))
    assert len(reader.pages) == page_count
    text = " ".join(pdf_page.extract_text() for pdf_page in reader.pages)
    for index in range(80):
        assert f"PAGE_SENTINEL_{index:02d}" in text


@pytest.mark.parametrize("asset", ["font", "image"])
@pytest.mark.parametrize("outcome", ["loaded", "failed"])
def test_pdf_ready_waits_for_delayed_assets_before_exporting_all_pages(
    browser: Browser,
    workspace_servers: tuple[str, str],
    asset: Literal["font", "image"],
    outcome: Literal["loaded", "failed"],
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(browser)
    page = context.new_page()
    pending: list[Route] = []
    try:
        url = _create_render_url(context, frontend_url, avatar=asset == "image")
        pattern = "**/*.woff2*" if asset == "font" else "**/render-readiness-avatar.png"
        page.route(pattern, lambda route: pending.append(route))
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_selector('[data-export-root="resume-page"]', state="attached")
        if asset == "image":
            page.wait_for_function("document.fonts.status === 'loaded'")
        page.wait_for_timeout(3_200)
        assert pending
        assert (
            page.locator("[data-pdf-ready]").get_attribute("data-pdf-ready") == "false"
        )

        for route in pending:
            if outcome == "failed":
                route.abort("failed")
            elif asset == "image":
                route.fulfill(content_type="image/png", body=AVATAR_PNG)
            else:
                route.continue_()
        pending.clear()
        page.unroute(pattern)
        page.wait_for_selector("[data-pdf-ready='true']")
        assert page.evaluate("document.fonts.status") == "loaded"
        if asset == "image":
            image = page.locator("[data-avatar-image]").first.evaluate(
                "image => ({ complete: image.complete, width: image.naturalWidth })"
            )
            assert image == {
                "complete": True,
                "width": 1 if outcome == "loaded" else 0,
            }
        _assert_multipage_pdf(page)
    finally:
        for route in pending:
            route.abort()
        context.close()


def test_export_ready_does_not_wait_for_unrelated_network_activity(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(browser)
    page = context.new_page()
    pending: list[Route] = []
    try:
        url = _create_render_url(context, frontend_url, avatar=False)
        page.route("**/unrelated-export-request", lambda route: pending.append(route))
        page.add_init_script("void fetch('/unrelated-export-request');")

        _wait_for_resume_render(page, url, 8_000)

        assert pending
        assert page.locator("[data-pdf-ready='true']").is_visible()
        _assert_multipage_pdf(page)
    finally:
        for route in pending:
            route.abort()
        context.close()


def test_export_times_out_when_a_visual_asset_never_settles(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(browser)
    page = context.new_page()
    pending: list[Route] = []
    try:
        url = _create_render_url(context, frontend_url, avatar=True)
        page.route(
            "**/render-readiness-avatar.png", lambda route: pending.append(route)
        )
        started = monotonic()

        with pytest.raises(PlaywrightTimeoutError):
            _wait_for_resume_render(page, url, 2_000)

        assert pending
        assert monotonic() - started < 3
        assert (
            page.locator("[data-pdf-ready]").get_attribute("data-pdf-ready") == "false"
        )
    finally:
        for route in pending:
            route.abort()
        context.close()
