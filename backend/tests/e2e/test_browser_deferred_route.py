import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.sync_api import Browser, Route, expect

from tests.e2e.browser_support import DeferredRoute

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


@pytest.fixture
def module_server() -> Iterator[str]:
    resources = {
        "/": (
            "text/html",
            """<!doctype html><button>Load</button><output></output><script>
              document.querySelector('button').onclick = () => {
                import('/assets/entry.js').then(module => {
                  document.querySelector('output').textContent = module.value;
                });
              };
            </script>""",
        ),
        "/assets/entry.js": (
            "text/javascript",
            "import {value as dependency} from './dependency.js';"
            "export const value = 'entry-' + dependency;",
        ),
        "/assets/dependency.js": (
            "text/javascript",
            "export const value = 'dependency';",
        ),
        "/assets/late.js": ("text/javascript", "export const value = 'late';"),
        "/assets/value": ("text/plain", "original"),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            resource = resources.get(self.path)
            if resource is None:
                self.send_error(404)
                return
            content_type, body = resource
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_deferred_route_releases_a_module_and_continues_its_late_dependencies(
    browser: Browser,
    module_server: str,
) -> None:
    context = browser.new_context()
    page = context.new_page()
    older_mock_requests: list[str] = []

    def older_mock(route: Route) -> None:
        older_mock_requests.append(route.request.url)
        route.fulfill(status=503)

    try:
        page.route("**/assets/**", older_mock)
        deferred = DeferredRoute(page, "**/assets/**")
        page.goto(module_server)
        page.get_by_role("button", name="Load").click()
        deferred.wait()
        assert len(deferred.pending) == 1
        assert deferred.pending[0].request.url == f"{module_server}/assets/entry.js"
        expect(page.locator("output")).to_have_text("")

        deferred.release()
        expect(page.locator("output")).to_have_text("entry-dependency")
        assert deferred.pending == ()
        assert (
            page.evaluate("import('/assets/late.js').then(module => module.value)")
            == "late"
        )
        assert older_mock_requests == []
        deferred.release()
    finally:
        context.close()


@pytest.mark.parametrize("outcome", ["fulfilled", "aborted"])
def test_deferred_route_applies_custom_action_only_to_captured_requests(
    browser: Browser,
    module_server: str,
    outcome: str,
) -> None:
    context = browser.new_context()
    page = context.new_page()
    try:
        deferred = DeferredRoute(page, "**/assets/value")
        page.goto(module_server)
        page.evaluate(
            """() => {
              window.initial = fetch('/assets/value')
                .then(response => response.text()).catch(() => 'failed');
            }"""
        )
        deferred.wait()
        assert len(deferred.pending) == 1
        if outcome == "fulfilled":
            deferred.release(lambda route: route.fulfill(body="overridden"))
        else:
            deferred.release(lambda route: route.abort("failed"))
        assert page.evaluate("window.initial") == (
            "overridden" if outcome == "fulfilled" else "failed"
        )
        assert deferred.pending == ()
        assert (
            page.evaluate("fetch('/assets/value').then(response => response.text())")
            == "original"
        )
    finally:
        context.close()
