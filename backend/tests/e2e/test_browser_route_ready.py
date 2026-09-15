import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.sync_api import Browser, Route
from playwright.sync_api import Error as PlaywrightError

from tests.e2e.browser_support import RouteReady

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


@pytest.fixture
def delayed_save_page() -> Iterator[tuple[str, threading.Event, threading.Event]]:
    preparing = threading.Event()
    release = threading.Event()
    document = b"""<!doctype html><button>Rename</button><script>
      const save = async () => {
        await fetch('/prepare');
        await fetch('/save', {method: 'PUT', body: JSON.stringify({name: 'Draft'})});
      };
      document.querySelector('button').onclick = () => setTimeout(save, 5000);
      document.addEventListener('keydown', event => {
        if (event.ctrlKey && event.key.toLowerCase() === 's') {
          event.preventDefault();
          save();
        }
      });
    </script>"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/prepare":
                preparing.set()
                release.wait(5)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(document)

        def log_message(self, _format: str, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", preparing, release
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("save_mode", ["autosave", "checkpoint"])
@pytest.mark.parametrize("paused_clock", [False, True])
def test_route_ready_waits_for_capture_after_the_request_event(
    browser: Browser,
    delayed_save_page: tuple[str, threading.Event, threading.Event],
    save_mode: str,
    paused_clock: bool,
) -> None:
    origin, preparing, release = delayed_save_page
    context = browser.new_context()
    page = context.new_page()
    held: list[Route] = []
    ready = RouteReady()

    def hold_save(route: Route) -> None:
        held.append(route)
        ready.set()

    try:
        page.goto(origin)
        page.route("**/save", hold_save)
        page.clock.install(time=datetime(2026, 9, 15, tzinfo=UTC))
        if paused_clock:
            page.clock.pause_at(datetime(2026, 9, 15, 0, 0, 1, tzinfo=UTC))
        if save_mode == "autosave":
            page.get_by_role("button", name="Rename").click()
            page.clock.fast_forward(5_000)
        else:
            page.keyboard.press("Control+S")
        assert preparing.wait(5), "Save preparation did not reach the local server."
        with page.expect_request("**/save") as request:
            release.set()
        ready.wait(page)
        assert len(held) == 1
        assert held[0].request == request.value
        assert held[0].request.post_data_json == {"name": "Draft"}
        with page.expect_response("**/save") as response:
            held.pop().fulfill(status=200, json={"saved": True})
        assert response.value.ok
    finally:
        for route in held:
            route.abort()
        context.close()


def test_route_ready_times_out_and_can_be_reset_with_a_paused_clock(
    browser: Browser,
) -> None:
    context = browser.new_context()
    page = context.new_page()
    ready = RouteReady()
    try:
        page.clock.install(time=datetime(2026, 9, 15, tzinfo=UTC))
        page.clock.pause_at(datetime(2026, 9, 15, 0, 0, 1, tzinfo=UTC))
        with pytest.raises(PlaywrightError, match="Route callback was not ready"):
            ready.wait(page, timeout=50)
        ready.set()
        ready.wait(page, timeout=50)
        ready.clear()
        with pytest.raises(PlaywrightError, match="Route callback was not ready"):
            ready.wait(page, timeout=50)
    finally:
        context.close()
