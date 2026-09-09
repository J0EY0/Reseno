from __future__ import annotations

import io
import os
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from playwright.sync_api import BrowserType
from pypdf import PdfReader

from app.config import get_settings
from app.schemas.exports import ExportResumePdfRequest
from app.services.pdf import write_resume_images, write_resume_pdf
from app.services.resume_renderer import ResumeRenderer

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


@pytest.fixture
def render_server(monkeypatch) -> Iterator[tuple[str, list[str]]]:
    requests: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            requests.append(self.path)
            resume_id = parse_qs(urlsplit(self.path).query).get("resumeId", [""])[0]
            count = 2 if resume_id == "multi" else 1
            script = """
                const token = JSON.parse(localStorage.getItem('reseno-auth-session')
                    || '{}').accessToken || 'anonymous';
                const prior = localStorage.getItem('prior-render') || 'clean';
                const cookies = document.cookie || 'empty';
                localStorage.setItem('prior-render', 'private-state');
                document.cookie = 'prior-render=private-cookie';
                document.querySelector('article').textContent +=
                    ' ' + token + ' ' + prior + ' ' + cookies;
                const image = document.querySelector('img');
                image.onerror = () => {
                    document.body.dataset.pdfReady = 'true';
                };
                image.src = '/private.png';
            """
            if resume_id == "timeout":
                script = ""
            pages = "".join(
                f'<article data-export-root="resume-page">PAGE_{index + 1}</article>'
                for index in range(count)
            )
            html = (
                "<!doctype html><style>@page{size:A4;margin:0}"
                "body{margin:0}article{height:297mm;width:210mm;box-sizing:border-box;"
                "padding:20mm;break-after:page;font:20px sans-serif}"
                "article:last-of-type{break-after:auto}img{display:none}</style>"
                f"{pages}<img><script>{script}</script>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}"
    monkeypatch.setenv("FRONTEND_RENDER_BASE_URL", url)
    monkeypatch.setenv("PDF_RENDER_TIMEOUT_MS", "5000")
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE", raising=False)
    get_settings.cache_clear()
    try:
        yield url, requests
    finally:
        server.shutdown()
        worker.join(timeout=3)
        server.server_close()


def request(resume_id: str) -> ExportResumePdfRequest:
    return ExportResumePdfRequest(
        resumeId=resume_id,
        savedAt="2026-09-09",
        fileNameSeed="Test",
    )


def test_bundled_renderer_reuses_browser_and_isolates_real_pdf_and_png_exports(
    render_server,
    monkeypatch,
):
    _url, requests = render_server
    launches = []
    disconnected = threading.Event()
    original = BrowserType.launch

    def launch(self, **kwargs):
        launches.append(kwargs)
        browser = original(self, **kwargs)
        browser.on("disconnected", lambda _browser: disconnected.set())
        return browser

    monkeypatch.setattr(BrowserType, "launch", launch)
    renderer = ResumeRenderer()
    try:
        first = write_resume_pdf(
            "export-authenticated",
            request("first"),
            document_locale="en",
            renderer=renderer,
            access_token="synthetic-owner-token",
            token_expires_at="2099-01-01T00:00:00Z",
        )
        first_text = PdfReader(first).pages[0].extract_text()
        assert "synthetic-owner-token clean empty" in first_text
        second = write_resume_pdf(
            "export-anonymous",
            request("second"),
            document_locale="en",
            renderer=renderer,
        )
        second_text = PdfReader(second).pages[0].extract_text()
        assert "anonymous clean empty" in second_text
        assert "synthetic-owner-token" not in second_text
        image = write_resume_images(
            "export-image",
            request("single"),
            document_locale="en",
            renderer=renderer,
        )
        assert image.page_count == 1
        assert image.path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        archive = write_resume_images(
            "export-archive",
            request("multi"),
            document_locale="en",
            renderer=renderer,
        )
        with ZipFile(archive.path) as images:
            assert images.namelist() == ["page-1.png", "page-2.png"]
            assert all(
                images.read(name).startswith(b"\x89PNG") for name in images.namelist()
            )
        assert archive.page_count == 2
        assert renderer.render(lambda browser: len(browser.contexts)) == 0
        assert launches == [{"headless": True}]
        assert not any(urlsplit(path).path == "/private.png" for path in requests)
    finally:
        renderer.close()
    assert disconnected.is_set()


def test_real_renderer_recovers_after_a_readiness_timeout(render_server, monkeypatch):
    renderer = ResumeRenderer()
    try:
        monkeypatch.setenv("PDF_RENDER_TIMEOUT_MS", "200")
        get_settings.cache_clear()
        with pytest.raises(HTTPException) as caught:
            write_resume_pdf(
                "export-timeout",
                request("timeout"),
                document_locale="en",
                renderer=renderer,
            )
        assert caught.value.detail == "PDF_RENDER_TIMEOUT"
        monkeypatch.setenv("PDF_RENDER_TIMEOUT_MS", "5000")
        get_settings.cache_clear()
        recovered = write_resume_pdf(
            "export-recovered",
            request("recovered"),
            document_locale="en",
            renderer=renderer,
        )
        assert (
            "anonymous clean empty"
            in PdfReader(io.BytesIO(recovered.read_bytes())).pages[0].extract_text()
        )
    finally:
        renderer.close()
