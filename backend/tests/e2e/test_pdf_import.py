"""PDF import reports file-specific errors without persisting incomplete resumes."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Route, expect
from pypdf import PdfWriter

from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _messages(locale: str) -> dict[str, str]:
    path = (
        Path(__file__).resolve().parents[3]
        / "frontend/src/i18n/locales"
        / f"{locale}.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _pdf(pages: int = 1, *, encrypted: bool = False) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    if encrypted:
        writer.encrypt("import-test-password")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize("locale", ["zh", "en"])
@pytest.mark.parametrize(
    ("kind", "message_key"),
    [
        ("encrypted", "pdfImportPasswordProtected"),
        ("invalid", "pdfImportInvalidPdf"),
        ("blank", "pdfImportNoText"),
        ("pages", "pdfImportTooManyPages"),
        ("size", "pdfImportFileTooLarge"),
    ],
)
def test_pdf_import_error_is_specific_and_keeps_gallery_unchanged(
    browser: Browser,
    workspace_servers: tuple[str, str],
    locale: str,
    kind: str,
    message_key: str,
) -> None:
    url, _ = workspace_servers
    messages = _messages(locale)
    context = authenticated_context(
        browser, locale="zh-CN" if locale == "zh" else "en-US"
    )
    page = context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        before = page.request.get(f"{url}/api/resumes").json()["data"]["resumes"]
        page.goto(f"{url}/resume", wait_until="networkidle")
        if kind == "invalid":
            payload = b"This is not a PDF document."
        elif kind == "size":
            payload = b"x" * (10 * 1024 * 1024 + 1)
        else:
            payload = _pdf(51 if kind == "pages" else 1, encrypted=kind == "encrypted")
        page.locator('input[type="file"]').set_input_files(
            {"name": f"{kind}.pdf", "mimeType": "application/pdf", "buffer": payload}
        )
        expect(page.get_by_text(messages[message_key], exact=True)).to_be_visible()
        expect(
            page.get_by_role("button", name=messages["importResume"], exact=True)
        ).to_be_enabled()
        expect(page).to_have_url(f"{url}/resume")
        after = page.request.get(f"{url}/api/resumes").json()["data"]["resumes"]
        assert {item["id"] for item in after} == {item["id"] for item in before}
        assert page_errors == []
    finally:
        context.close()


def test_pdf_import_cancel_is_silent_while_parser_configuration_is_pending(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    url, _ = workspace_servers
    messages = _messages("en")
    context = authenticated_context(browser, locale="en-US")
    page = context.new_page()
    pending: list[Route] = []
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        before = page.request.get(f"{url}/api/resumes").json()["data"]["resumes"]
        page.goto(f"{url}/resume", wait_until="networkidle")
        page.route("**/api/resume-import-lexicon", lambda route: pending.append(route))
        with page.expect_request("**/api/resume-import-lexicon"):
            page.locator('input[type="file"]').set_input_files(
                {
                    "name": "cancelled.pdf",
                    "mimeType": "application/pdf",
                    "buffer": _pdf(),
                }
            )
        expect(
            page.get_by_role("button", name=messages["resumeImportCancel"], exact=True)
        ).to_be_visible()
        page.get_by_role(
            "button", name=messages["resumeImportCancel"], exact=True
        ).click()
        expect(
            page.get_by_role("button", name=messages["importResume"], exact=True)
        ).to_be_enabled()
        assert pending
        pending.pop().continue_()
        page.wait_for_load_state("networkidle")
        expect(page.locator("[data-sonner-toast]")).to_have_count(0)
        after = page.request.get(f"{url}/api/resumes").json()["data"]["resumes"]
        assert {item["id"] for item in after} == {item["id"] for item in before}
        assert page_errors == []
    finally:
        for route in pending:
            route.abort()
        context.close()
