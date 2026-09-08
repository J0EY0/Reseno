import asyncio
import json
import os
import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from app.services.agent.integrations import web as agent_web
from app.services.agent.integrations import web_proxy

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


@pytest.fixture
def public_site(monkeypatch) -> Iterator[tuple[int, list[tuple[str, str, str]]]]:
    requests: list[tuple[str, str, str]] = []
    description = (
        "Build React interfaces and tested TypeScript components for the recruiting "
        "product. Improve accessibility, browser performance, and reliability. "
        "Work with designers to deliver reusable components and document behavior."
    )

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(
                (
                    self.path,
                    self.headers.get("Host", ""),
                    self.headers.get("Cookie", ""),
                )
            )
            port = self.server.server_port
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", f"http://jobs.example:{port}/roles/7")
                self.end_headers()
                return
            if self.path.startswith("/redirect-private"):
                target = "rebound.example" if "dns" in self.path else "127.0.0.1"
                self.send_response(302)
                self.send_header("Location", f"http://{target}:{port}/private")
                self.end_headers()
                return
            if self.path == "/roles/7":
                content_type = "text/html"
                body = b"""<html><head><title>Frontend Intern</title></head>
                <body><main id="job"></main><script src="details.js"></script></body>
                </html>"""
            elif self.path == "/roles/details.js":
                content_type = "application/javascript"
                body = b"""fetch('requirements.json').then(r => r.json()).then(data => {
                    document.querySelector('#job').textContent = data.description;
                });"""
            elif self.path == "/roles/requirements.json":
                content_type = "application/json"
                body = json.dumps({"description": description}).encode()
            else:
                content_type = "text/plain"
                body = b"private endpoint must never be requested"
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            if self.path == "/roles/7":
                self.send_header("Set-Cookie", "session=browser-test; Path=/; HttpOnly")
                self.send_header("Set-Cookie", "locale=en; Path=/")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    real_resolve = web_proxy.safe_web_target_addresses
    real_getaddrinfo = socket.getaddrinfo

    def resolve(url: str) -> tuple[str, ...] | None:
        if urlsplit(url).hostname in {"careers.example", "jobs.example"}:
            return ("127.0.0.1",)
        return real_resolve(url)

    def getaddrinfo(host, port, *args, **kwargs):
        if host in {"rebound.example", b"rebound.example"}:
            host = "127.0.0.1"
        return real_getaddrinfo(host, port, *args, **kwargs)

    monkeypatch.setattr(web_proxy, "safe_web_target_addresses", resolve)
    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    try:
        yield server.server_port, requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_dynamic_fetch_preserves_redirects_scripts_cookies_and_final_url(public_site):
    port, requests = public_site
    url = f"http://careers.example:{port}/start"
    rendered = asyncio.run(
        agent_web._async_render_web_references(
            [(url, "React TypeScript frontend", "Frontend Intern")],
        )
    )
    assert rendered[url].final_url == f"http://jobs.example:{port}/roles/7"
    assert "tested TypeScript components" in rendered[url].excerpt
    assert [path for path, _, _ in requests] == [
        "/start",
        "/roles/7",
        "/roles/details.js",
        "/roles/requirements.json",
    ]
    api = requests[-1]
    assert api[1] == f"jobs.example:{port}"
    assert "session=browser-test" in api[2]
    assert "locale=en" in api[2]


@pytest.mark.parametrize("path", ["/redirect-private", "/redirect-private-dns"])
def test_browser_redirect_cannot_reach_private_network(public_site, path):
    port, requests = public_site
    url = f"http://careers.example:{port}{path}"
    rendered = asyncio.run(
        agent_web._async_render_web_references(
            [(url, "React TypeScript frontend", "Frontend Intern")],
        )
    )
    assert rendered == {}
    assert all(request_path != "/private" for request_path, _, _ in requests)


def test_browser_websocket_cannot_bypass_proxy_for_loopback(public_site):
    port, requests = public_site

    async def scenario():
        browser = agent_web.WebBrowser()
        try:
            context = await browser.context()
            page = await context.new_page()
            outcome = await page.evaluate(
                """url => new Promise(resolve => {
                const socket = new WebSocket(url);
                socket.onopen = () => { socket.close(); resolve('opened'); };
                socket.onerror = () => resolve('blocked');
                setTimeout(() => { socket.close(); resolve('timeout'); }, 3000);
            })""",
                f"ws://127.0.0.1:{port}/private-websocket",
            )
            assert outcome == "blocked"
        finally:
            await browser.close()

    asyncio.run(scenario())
    assert requests == []
