import asyncio
import json
from typing import Any
from uuid import uuid4

from playwright.sync_api import Browser, BrowserContext, Page

browser_session: dict[str, str] = {}


class RouteReady:
    """Signal that a route callback has captured the request for the test."""

    def __init__(self) -> None:
        self._event = asyncio.Event()

    def set(self) -> None:
        self._event.set()

    def clear(self) -> None:
        self._event.clear()

    def wait(self, page: Page, *, timeout: float = 5_000) -> None:
        if self._event.is_set():
            return

        async def wait_for_callback() -> None:
            try:
                await asyncio.wait_for(self._event.wait(), timeout=timeout / 1_000)
            except TimeoutError:
                raise TimeoutError(
                    f"Route callback was not ready within {timeout:g}ms."
                ) from None

        name = f"__reseno_route_ready_{uuid4().hex}"
        page.expose_function(name, wait_for_callback)
        page.evaluate(
            """async name => {
              try {
                await window[name]();
              } finally {
                delete window[name];
              }
            }""",
            name,
        )


def authenticated_context(
    browser: Browser,
    **kwargs: Any,
) -> BrowserContext:
    session = browser_session
    if not session:
        raise RuntimeError("Browser auth session has not been initialized.")

    context = browser.new_context(
        extra_http_headers={"Authorization": f"Bearer {session['accessToken']}"},
        **kwargs,
    )
    session_json = json.dumps(session)
    context.add_init_script(
        script=(
            "window.localStorage.setItem("
            "'reseno-auth-session', "
            f"{json.dumps(session_json)});"
        )
    )
    return context
