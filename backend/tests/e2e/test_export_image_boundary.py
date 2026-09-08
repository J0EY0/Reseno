import base64
import json
import os
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import httpx
import pytest

from tests.e2e.browser_support import browser_session

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1", reason="Browser E2E is opt-in."
)
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl9ZeoAAAAASUVORK5CYII="
)


@pytest.fixture
def image_server() -> Iterator[tuple[str, list[str]]]:
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            self.wfile.write(PNG)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/private.png", seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.browser_smoke
@pytest.mark.parametrize("export_kind", ["pdf", "images"])
def test_export_imported_avatar_cannot_request_private_image(
    workspace_servers, image_server, export_kind
):
    frontend_url, _ = workspace_servers
    image_url, seen = image_server
    document = {
        "schemaVersion": 2,
        "basic": {
            "name": "Imported avatar",
            "headline": "",
            "phone": "",
            "email": "",
            "location": "",
            "avatar": image_url,
            "summary": "",
            "customFields": [],
        },
        "sections": [],
    }
    artifact = {
        "format": "reseno.resume",
        "formatVersion": 1,
        "templates": [],
        "resumes": [
            {
                "title": "Image boundary",
                "documentLocale": "en",
                "resume": document,
                "template": "minimal",
                "jobBrief": "",
                "typography": {"fontFamily": "inter", "fontSize": 16},
                "templateSettings": None,
            }
        ],
    }
    with httpx.Client(
        base_url=frontend_url,
        headers={"Authorization": f"Bearer {browser_session['accessToken']}"},
        timeout=90,
        trust_env=False,
    ) as client:
        imported = client.post(
            "/api/import/resume",
            files={"file": ("resume.json", json.dumps(artifact), "application/json")},
        )
        assert imported.status_code == 200, imported.text
        created = client.post(
            "/api/resumes", json=imported.json()["data"]["resumes"][0]
        )
        assert created.status_code == 200, created.text
        saved = created.json()["data"]
        exported = client.post(
            f"/api/exports/resume-{export_kind}",
            json={
                "resumeId": saved["resume"]["id"],
                "fileNameSeed": "avatar",
                "savedAt": saved["savedAt"],
                "versionId": saved["versionId"],
            },
        )
        assert exported.status_code == 200, exported.text
        assert exported.json()["data"]["downloadUrl"]
    assert seen == []


@pytest.mark.browser_smoke
def test_renderer_keeps_data_and_public_images(browser, monkeypatch):
    from app.services import render_assets
    from app.services.pdf import _create_render_context

    fetched = []

    async def fetch_image(url):
        fetched.append(url)
        return PNG, "image/png"

    monkeypatch.setattr(render_assets, "_fetch_public_image", fetch_image)
    context = _create_render_context(
        browser, access_token=None, token_expires_at=None, username=None
    )
    try:
        page = context.new_page()
        data_url = "data:image/png;base64," + base64.b64encode(PNG).decode()
        page.set_content(
            f'<img id="local" src="{data_url}">'
            '<img id="public" src="https://images.example/avatar.png">'
        )
        page.wait_for_function(
            "[...document.images].every(image => "
            "image.complete && image.naturalWidth === 1)"
        )
        assert fetched == ["https://images.example/avatar.png"]
    finally:
        context.close()
