from __future__ import annotations

import os
from collections import Counter

import pytest
from playwright.sync_api import Browser

from tests.e2e.browser_support import authenticated_context as _authenticated_context
from tests.e2e.workspace_network_support import (
    AUTH_SETUP_STATUS_REQUEST,
    ApiRequest,
    api_request_key,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def _observe_api_requests(browser: Browser, url: str) -> list[ApiRequest]:
    context = _authenticated_context(browser)
    page = context.new_page()
    requests: list[ApiRequest] = []
    page.on(
        "request",
        lambda request: (
            requests.append(api_request)
            if (api_request := api_request_key(request)) is not None
            else None
        ),
    )

    try:
        page.goto(url, wait_until="networkidle")
    finally:
        context.close()

    return requests


@pytest.mark.browser_smoke
@pytest.mark.parametrize(
    ("route", "expected_paths"),
    [
        (
            "/resume",
            [AUTH_SETUP_STATUS_REQUEST, ("GET", "/api/workspace/pages/resumes")],
        ),
        (
            "/templates",
            [AUTH_SETUP_STATUS_REQUEST, ("GET", "/api/workspace/pages/templates")],
        ),
        (
            "/template/minimal",
            [AUTH_SETUP_STATUS_REQUEST, ("GET", "/api/workspace/pages/templates")],
        ),
        (
            "/trash",
            [AUTH_SETUP_STATUS_REQUEST, ("GET", "/api/workspace/pages/trash")],
        ),
        (
            "/models",
            [AUTH_SETUP_STATUS_REQUEST, ("GET", "/api/workspace/pages/models")],
        ),
        (
            "/settings",
            [
                AUTH_SETUP_STATUS_REQUEST,
                ("GET", "/api/workspace/pages/settings"),
                ("GET", "/api/auth/oauth/identities"),
            ],
        ),
    ],
)
def test_workspace_route_request_allowlist(
    browser: Browser,
    workspace_servers: tuple[str, str],
    route: str,
    expected_paths: list[ApiRequest],
) -> None:
    frontend_url, _ = workspace_servers
    actual_paths = _observe_api_requests(browser, f"{frontend_url}{route}")

    assert Counter(actual_paths) == Counter(expected_paths)


@pytest.mark.browser_smoke
def test_resume_editor_route_request_allowlist(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    expected_paths = [
        AUTH_SETUP_STATUS_REQUEST,
        ("GET", "/api/workspace/pages/resume-editor"),
        ("GET", f"/api/resumes/{resume_id}"),
        ("GET", f"/api/resumes/{resume_id}/versions"),
    ]
    actual_paths = _observe_api_requests(
        browser,
        f"{frontend_url}/resume/{resume_id}",
    )

    assert Counter(actual_paths) == Counter(expected_paths)


def test_pdf_export_route_request_allowlist(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    expected_paths = [
        AUTH_SETUP_STATUS_REQUEST,
        ("GET", "/api/workspace/pages/templates"),
        ("GET", f"/api/resumes/{resume_id}"),
    ]
    actual_paths = _observe_api_requests(
        browser,
        f"{frontend_url}/pdf-export?resumeId={resume_id}&documentLocale=en",
    )

    assert Counter(actual_paths) == Counter(expected_paths)
