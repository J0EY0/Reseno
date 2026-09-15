from __future__ import annotations

from urllib.parse import urlparse

from playwright.sync_api import Request

ApiRequest = tuple[str, str]
AUTH_SETUP_STATUS_REQUEST: ApiRequest = ("GET", "/api/auth/setup")


def api_request_key(request: Request) -> ApiRequest | None:
    path = urlparse(request.url).path
    if not path.startswith("/api/"):
        return None
    return request.method, path
