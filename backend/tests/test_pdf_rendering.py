from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi import HTTPException
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from app.config import get_settings
from app.schemas.exports import ExportResumePdfRequest
from app.services import pdf, resume_renderer
from app.services.resume_renderer import ResumeRenderer


class RenderProbe:
    def __init__(self) -> None:
        self.launches = []
        self.browsers = []
        self.contexts = []
        self.thread_ids = set()
        self.stops = 0
        self.active = 0
        self.peak_active = 0
        self.fail_stage = None
        self.failure = PlaywrightError("Internal diagnostic")
        self.page_count = 1
        self.lock = threading.Lock()
        self.entered = threading.Event()
        self.all_entered = threading.Event()
        self.release = threading.Event()
        self.release.set()

    def touch(self, stage):
        self.thread_ids.add(threading.get_ident())
        if self.fail_stage == stage:
            self.fail_stage = None
            raise self.failure

    def driver(self):
        probe = self

        class Driver:
            def __init__(self):
                self.chromium = SimpleNamespace(launch=self.launch)

            def start(self):
                probe.touch("start")
                return self

            def stop(self):
                probe.touch("stop")
                probe.stops += 1

            def launch(self, **kwargs):
                probe.launches.append(kwargs)
                probe.touch("launch")
                browser = Browser()
                probe.browsers.append(browser)
                return browser

        class Browser:
            def __init__(self):
                self.connected = True
                self.closed = False

            def is_connected(self):
                probe.touch("is_connected")
                return self.connected

            def new_context(self, **kwargs):
                probe.touch("new_context")
                context = Context(kwargs)
                probe.contexts.append(context)
                return context

            def close(self):
                self.closed = True
                self.connected = False
                probe.touch("browser_close")

        class Context:
            def __init__(self, options):
                self.options = options
                self.routes = []
                self.scripts = []
                self.closed = False

            def route(self, *args):
                probe.touch("route")
                self.routes.append(args)

            def add_init_script(self, script):
                probe.touch("init_script")
                self.scripts.append(script)

            def new_page(self):
                probe.touch("new_page")
                return Page()

            def close(self):
                self.closed = True
                probe.touch("context_close")

        class Page:
            def goto(self, *args, **kwargs):
                probe.touch("goto")
                with probe.lock:
                    probe.active += 1
                    probe.peak_active = max(probe.active, probe.peak_active)
                    if probe.active == 3:
                        probe.all_entered.set()
                probe.entered.set()
                try:
                    assert probe.release.wait(timeout=3)
                finally:
                    with probe.lock:
                        probe.active -= 1

            def wait_for_selector(self, *args, **kwargs):
                probe.touch("ready")

            def emulate_media(self, **kwargs):
                probe.touch("media")

            def pdf(self, *, path, **kwargs):
                probe.touch("pdf")
                Path(path).write_bytes(b"%PDF-1.4\n")

            def locator(self, selector):
                assert selector == "[data-export-root='resume-page']"
                return Pages()

        class Pages:
            def count(self):
                return probe.page_count

            def nth(self, index):
                return Image(index)

            @property
            def first(self):
                return self.nth(0)

        class Image:
            def __init__(self, index):
                self.index = index

            def screenshot(self, **kwargs):
                probe.touch("screenshot")
                return b"\x89PNG\r\n\x1a\n" + str(self.index).encode()

        return Driver()


def render_request():
    return ExportResumePdfRequest(
        resumeId="render-test",
        savedAt="2026-09-09",
        fileNameSeed="Test",
    )


@pytest.fixture
def render_setup(monkeypatch):
    probe = RenderProbe()
    monkeypatch.setattr(resume_renderer, "sync_playwright", probe.driver)
    monkeypatch.delenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE", raising=False)
    get_settings.cache_clear()
    renderer = ResumeRenderer()

    def render(export_id, **kwargs):
        return pdf.write_resume_pdf(
            export_id,
            render_request(),
            document_locale="en",
            renderer=renderer,
            **kwargs,
        )

    try:
        yield probe, render, renderer
    finally:
        probe.release.set()
        renderer.close()


def test_consecutive_exports_reuse_one_browser(render_setup):
    probe, render, _renderer = render_setup
    render("export-first")
    render("export-second")
    assert len(probe.launches) == 1
    assert len(probe.contexts) == 2
    assert probe.contexts[0] is not probe.contexts[1]
    assert all(context.closed for context in probe.contexts)


def test_simultaneous_exports_have_bounded_browser_concurrency(render_setup):
    probe, render, _renderer = render_setup
    probe.release.clear()
    start = threading.Barrier(4, timeout=3)

    def run(index):
        start.wait()
        return render(f"export-{index}")

    with ThreadPoolExecutor(max_workers=3) as callers:
        pending = [callers.submit(run, index) for index in range(3)]
        try:
            start.wait()
            assert probe.entered.wait(timeout=2)
            probe.all_entered.wait(timeout=0.2)
        finally:
            probe.release.set()
        assert all(future.result(timeout=3).exists() for future in pending)
    assert probe.peak_active == 1
    assert len(probe.launches) == 1
    assert len(probe.thread_ids) == 1
    assert threading.get_ident() not in probe.thread_ids


def test_default_export_browser_uses_bundled_chromium(render_setup, monkeypatch):
    probe, render, _renderer = render_setup
    monkeypatch.setattr(Path, "exists", lambda _path: True)
    render("export-default-browser")
    assert probe.launches == [{"headless": True}]


def test_only_explicit_executable_selects_an_external_browser(
    render_setup, monkeypatch
):
    probe, render, _renderer = render_setup
    monkeypatch.setenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "/custom/browser")
    get_settings.cache_clear()
    render("export-custom-browser")
    assert probe.launches == [{"headless": True, "executable_path": "/custom/browser"}]


def test_export_contexts_isolate_auth_and_keep_image_routing(render_setup):
    probe, render, _renderer = render_setup
    render("export-auth", access_token="private-token", token_expires_at="expiry")
    render("export-anonymous")
    first, second = probe.contexts
    assert first.options["service_workers"] == "block"
    assert first.routes == second.routes == [("**/*", pdf.route_render_image)]
    assert len(first.scripts) == 1
    assert "private-token" in first.scripts[0]
    assert "window.location.origin ===" in first.scripts[0]
    assert not second.scripts
    assert first.closed and second.closed


@pytest.mark.parametrize("page_count", [1, 3])
def test_png_and_archive_exports_reuse_pdf_browser(render_setup, page_count):
    probe, render, renderer = render_setup
    render("export-pdf")
    probe.page_count = page_count
    result = pdf.write_resume_images(
        "export-images",
        render_request(),
        document_locale="en",
        renderer=renderer,
    )
    assert result.page_count == page_count
    assert result.is_archive is (page_count > 1)
    if result.is_archive:
        with ZipFile(result.path) as archive:
            assert archive.namelist() == [
                f"page-{i + 1}.png" for i in range(page_count)
            ]
            assert all(
                archive.read(name).startswith(b"\x89PNG") for name in archive.namelist()
            )
    else:
        assert result.path.read_bytes().startswith(b"\x89PNG")
    assert probe.contexts[-1].options["device_scale_factor"] == 2
    assert all(context.closed for context in probe.contexts)
    assert len(probe.launches) == 1


@pytest.mark.parametrize(
    "stage",
    [
        "launch",
        "new_context",
        "route",
        "init_script",
        "new_page",
        "goto",
        "pdf",
        "context_close",
    ],
)
def test_failed_exports_close_resources_and_allow_the_next_export(render_setup, stage):
    probe, render, _renderer = render_setup
    probe.fail_stage = stage
    with pytest.raises(HTTPException) as caught:
        render("export-failed", access_token="token", token_expires_at="expiry")
    assert (caught.value.status_code, caught.value.detail) == (503, "PDF_RENDER_FAILED")
    assert all(context.closed for context in probe.contexts)
    assert probe.stops == 1
    assert render("export-recovered").exists()
    assert len(probe.launches) == 2


def test_timeout_keeps_stable_error_and_allows_recovery(render_setup):
    probe, render, _renderer = render_setup
    probe.fail_stage = "ready"
    probe.failure = PlaywrightTimeoutError("Private renderer location")
    with pytest.raises(HTTPException) as caught:
        render("export-timeout")
    assert (caught.value.status_code, caught.value.detail) == (
        504,
        "PDF_RENDER_TIMEOUT",
    )
    assert probe.contexts[0].closed
    assert render("export-recovered").exists()


def test_disconnected_browser_is_replaced(render_setup):
    probe, render, _renderer = render_setup
    render("export-before-disconnect")
    probe.browsers[0].connected = False
    render("export-after-disconnect")
    assert len(probe.launches) == 2
    assert probe.browsers[0].closed
    assert probe.stops == 1


def track_submissions(monkeypatch, renderer, expected):
    submitted = threading.Event()
    original = renderer._executor.submit
    calls = 0

    def submit(*args, **kwargs):
        nonlocal calls
        future = original(*args, **kwargs)
        calls += 1
        if calls == expected:
            submitted.set()
        return future

    monkeypatch.setattr(renderer._executor, "submit", submit)
    return submitted


def test_export_admission_rejects_excess_work_and_recovers(render_setup, monkeypatch):
    probe, render, renderer = render_setup
    probe.release.clear()
    submitted = track_submissions(monkeypatch, renderer, expected=4)
    with ThreadPoolExecutor(max_workers=4) as callers:
        pending = [callers.submit(render, f"export-{index}") for index in range(4)]
        try:
            assert submitted.wait(timeout=2)
            with pytest.raises(HTTPException) as caught:
                render("export-overflow")
            assert (caught.value.status_code, caught.value.detail) == (
                503,
                "EXPORT_RENDERER_BUSY",
            )
            assert caught.value.headers == {"Retry-After": "1"}
        finally:
            probe.release.set()
        assert all(future.result(timeout=3).exists() for future in pending)
    assert render("export-after-overflow").exists()
    assert len(probe.launches) == 1


def test_shutdown_drains_admitted_work_and_rejects_new_exports(
    render_setup, monkeypatch
):
    probe, render, renderer = render_setup
    probe.release.clear()
    submitted = track_submissions(monkeypatch, renderer, expected=2)
    with ThreadPoolExecutor(max_workers=3) as callers:
        first = callers.submit(render, "export-first")
        assert probe.entered.wait(timeout=2)
        closing = callers.submit(renderer.close)
        try:
            assert submitted.wait(timeout=2)
            assert not closing.done()
            with pytest.raises(HTTPException) as caught:
                render("export-after-close")
            assert caught.value.detail == "EXPORT_RENDERER_UNAVAILABLE"
        finally:
            probe.release.set()
        assert first.result(timeout=3).exists()
        closing.result(timeout=3)
    renderer.close()
    assert probe.stops == 1
    assert probe.browsers[0].closed
    assert all(context.closed for context in probe.contexts)
    assert len(probe.thread_ids) == 1


def test_unused_renderer_shutdown_does_not_launch_a_browser(render_setup):
    probe, _render, renderer = render_setup
    renderer.close()
    assert not probe.launches
    assert probe.stops == 0


def test_invalid_external_browser_path_does_not_fall_back(render_setup, monkeypatch):
    probe, render, _renderer = render_setup
    monkeypatch.setenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE", "/missing/browser")
    get_settings.cache_clear()
    probe.fail_stage = "launch"
    with pytest.raises(HTTPException) as caught:
        render("export-invalid-browser")
    assert caught.value.detail == "PDF_RENDER_FAILED"
    assert probe.launches == [
        {"headless": True, "executable_path": "/missing/browser"},
    ]


@pytest.mark.parametrize(
    ("failure", "status_code", "key"),
    [
        (PlaywrightError("Internal image details"), 503, "IMAGE_RENDER_FAILED"),
        (PlaywrightTimeoutError("Image wait details"), 504, "IMAGE_RENDER_TIMEOUT"),
    ],
)
def test_image_export_failure_releases_context_and_recovers(
    render_setup,
    failure,
    status_code,
    key,
):
    probe, _render, renderer = render_setup
    probe.fail_stage = "screenshot"
    probe.failure = failure
    with pytest.raises(HTTPException) as caught:
        pdf.write_resume_images(
            "export-failed-image",
            render_request(),
            document_locale="en",
            renderer=renderer,
        )
    assert (caught.value.status_code, caught.value.detail) == (status_code, key)
    assert probe.contexts[0].closed
    assert probe.stops == 1
    result = pdf.write_resume_images(
        "export-recovered-image",
        render_request(),
        document_locale="en",
        renderer=renderer,
    )
    assert result.path.read_bytes().startswith(b"\x89PNG")
    assert len(probe.launches) == 2


def test_empty_renderer_page_response_preserves_browser_for_next_export(render_setup):
    probe, _render, renderer = render_setup
    probe.page_count = 0
    with pytest.raises(HTTPException) as caught:
        pdf.write_resume_images(
            "export-no-pages",
            render_request(),
            document_locale="en",
            renderer=renderer,
        )
    assert (caught.value.status_code, caught.value.detail) == (
        502,
        "EXPORT_RENDERER_NO_PAGES",
    )
    assert probe.contexts[0].closed
    probe.page_count = 1
    result = pdf.write_resume_images(
        "export-next-image",
        render_request(),
        document_locale="en",
        renderer=renderer,
    )
    assert result.path.exists()
    assert len(probe.launches) == 1


def test_shutdown_stops_driver_even_when_browser_close_fails(render_setup):
    probe, render, renderer = render_setup
    render("export-close-failure")
    probe.fail_stage = "browser_close"
    renderer.close()
    assert probe.stops == 1
    assert probe.browsers[0].closed
    assert len(probe.thread_ids) == 1


@pytest.mark.parametrize("endpoint", ["resume-pdf", "resume-images"])
def test_missing_export_resume_keeps_its_domain_error(client, endpoint):
    response = client.post(
        f"/api/exports/{endpoint}",
        json={
            "resumeId": "missing-resume",
            "fileNameSeed": "Missing",
            "savedAt": "2026-09-09",
        },
    )
    assert response.status_code == 404
    assert response.json()["message"] == "RESUME_NOT_FOUND"
