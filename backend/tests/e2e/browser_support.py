import json
from typing import Any

from playwright.sync_api import Browser, BrowserContext

browser_session: dict[str, str] = {}


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
            "'resumate-auth-session', "
            f"{json.dumps(session_json)});"
        )
    )
    return context
