import json
import os
from datetime import UTC, datetime
from pathlib import Path
from re import sub
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import uuid4

from fastapi import HTTPException, status
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.config import get_settings
from app.schemas.exports import ExportResumePdfRequest


def safe_file_name(seed: str) -> str:
    """Convert user-provided text into a safe PDF filename."""

    normalized = sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", seed.strip()).strip(" .-_")
    file_name = normalized or "resume"

    return file_name if file_name.lower().endswith(".pdf") else f"{file_name}.pdf"


def create_export_id() -> str:
    """Create a unique id for one generated export file."""

    return f"export-{uuid4().hex}"


def datetime_now_iso() -> str:
    """Return the current UTC time as an ISO string."""

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def get_export_path(export_id: str) -> Path:
    """Return the filesystem path for one export id."""

    return get_settings().export_dir / f"{export_id}.pdf"


def _normalize_render_base_url(value: str | None) -> str:
    """Validate and normalize the frontend URL used for PDF rendering."""

    base_url = (value or get_settings().frontend_render_base_url).strip().rstrip("/")
    parsed = urlsplit(base_url)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid frontend render base URL.",
        )

    return base_url


def build_render_url(request: ExportResumePdfRequest) -> str:
    """Build the frontend render URL that Playwright will print to PDF."""

    base_url = _normalize_render_base_url(request.render_base_url)
    parsed = urlsplit(base_url)
    base_path = parsed.path.rstrip("/")
    query = urlencode(
        {
            "resumeId": request.resume_id,
            "locale": request.locale,
            "savedAt": request.saved_at,
            "versionId": request.version_id or "",
        },
    )

    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            f"{base_path}/pdf-export",
            query,
            "",
        ),
    )


def _get_chromium_executable() -> str | None:
    """Find a locally installed Chromium-based browser for Playwright."""

    configured = os.getenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    candidates = [
        configured,
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]

    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate

    return None


def write_resume_pdf(
    export_id: str,
    request: ExportResumePdfRequest,
    *,
    access_token: str | None = None,
    token_expires_at: str | None = None,
    username: str | None = None,
) -> Path:
    """Render the saved frontend resume view and write it as a PDF."""

    settings = get_settings()
    export_dir = settings.export_dir
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = get_export_path(export_id)
    render_url = build_render_url(request)
    timeout = settings.pdf_render_timeout_ms
    executable_path = _get_chromium_executable()

    try:
        with sync_playwright() as playwright:
            if executable_path:
                browser = playwright.chromium.launch(
                    headless=True,
                    executable_path=executable_path,
                )
            else:
                browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 794, "height": 1123})
            if access_token and token_expires_at:
                auth_session = {
                    "username": username or "pdf-render",
                    "authenticatedAt": datetime_now_iso(),
                    "accessToken": access_token,
                    "expiresAt": token_expires_at,
                }
                context.add_init_script(
                    "window.sessionStorage.setItem("
                    "'resumate-auth-session', "
                    f"{json.dumps(json.dumps(auth_session))}"
                    ");",
                )

            page = context.new_page()

            try:
                # The frontend /pdf-export route loads the saved backend
                # workspace and marks data-pdf-ready only after fonts/images settle.
                page.goto(render_url, wait_until="networkidle", timeout=timeout)
                page.wait_for_selector(
                    "[data-pdf-ready='true']",
                    timeout=timeout,
                )
                page.emulate_media(media="print")
                page.pdf(
                    path=str(export_path),
                    format="A4",
                    print_background=True,
                    prefer_css_page_size=True,
                    margin={
                        "top": "0",
                        "right": "0",
                        "bottom": "0",
                        "left": "0",
                    },
                )
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timed out while rendering the resume PDF.",
        ) from exc
    except PlaywrightError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Unable to render PDF. Install Playwright browsers or set "
                "PLAYWRIGHT_CHROMIUM_EXECUTABLE to a Chromium-based browser."
            ),
        ) from exc

    return export_path


def require_export_file(export_id: str) -> Path:
    """Return an export path or raise when the PDF no longer exists."""

    export_path = get_export_path(export_id)
    if not export_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Export file not found.",
        )

    return export_path
