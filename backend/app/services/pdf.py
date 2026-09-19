import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from re import sub
from time import monotonic
from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException, status
from playwright.sync_api import (
    Browser,
    BrowserContext,
    Page,
)
from playwright.sync_api import (
    Error as PlaywrightError,
)
from playwright.sync_api import (
    TimeoutError as PlaywrightTimeoutError,
)

from app.config import get_settings
from app.document_locales import DocumentLocale
from app.schemas.exports import ExportResumeRenderRequest
from app.services.pdf_text import coalesce_pdf_text_runs
from app.services.render_assets import route_render_image
from app.services.resume_renderer import ResumeRenderer

EXPORT_FILE_TTL = timedelta(hours=1)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResumeImageExportResult:
    """Generated image artifact and the page metadata needed by the API."""

    path: Path
    page_count: int
    is_archive: bool


def safe_file_name(seed: str) -> str:
    """Convert user-provided text into a safe PDF filename."""

    normalized = sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", seed.strip()).strip(" .-_")
    file_name = normalized or "resume"

    return file_name if file_name.lower().endswith(".pdf") else f"{file_name}.pdf"


def create_export_id() -> str:
    """Create a unique id for one generated export file."""

    return f"export-{uuid4().hex}"


def export_expires_at(export_path: Path) -> str:
    """Return the fixed expiry derived from an export artifact's write time."""

    expires_at = datetime.fromtimestamp(export_path.stat().st_mtime, UTC)
    expires_at += EXPORT_FILE_TTL
    return expires_at.isoformat().replace("+00:00", "Z")


def _export_has_expired(export_path: Path, now: datetime) -> bool:
    modified_at = datetime.fromtimestamp(export_path.stat().st_mtime, UTC)
    return modified_at + EXPORT_FILE_TTL <= now


def cleanup_expired_exports() -> None:
    """Delete expired generated PDF, PNG, and ZIP artifacts."""

    export_dir = get_settings().export_dir
    if not export_dir.exists():
        return

    now = datetime.now(UTC)
    for extension in ("pdf", "png", "zip"):
        for export_path in export_dir.glob(f"export-*.{extension}"):
            try:
                if export_path.is_file() and _export_has_expired(export_path, now):
                    export_path.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                logger.warning(
                    "Could not remove expired export artifact %s",
                    export_path,
                    exc_info=True,
                )


def get_export_path(export_id: str) -> Path:
    """Return the filesystem path for one export id."""

    return get_settings().export_dir / f"{export_id}.pdf"


def _normalize_render_base_url() -> str:
    """Validate and normalize the configured frontend resume renderer URL."""

    base_url = get_settings().frontend_render_base_url.strip().rstrip("/")
    parsed = urlsplit(base_url)

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="EXPORT_RENDER_URL_INVALID",
        )

    return base_url


def build_render_url(
    request: ExportResumeRenderRequest,
    document_locale: DocumentLocale,
) -> str:
    """Build the frontend URL that Playwright will render for an export."""

    base_url = _normalize_render_base_url()
    parsed = urlsplit(base_url)
    base_path = parsed.path.rstrip("/")
    query = urlencode(
        {
            "resumeId": request.resume_id,
            "documentLocale": document_locale,
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


def _create_render_context(
    browser: Browser,
    *,
    access_token: str | None,
    token_expires_at: str | None,
    username: str | None,
    device_scale_factor: int = 1,
) -> BrowserContext:
    """Create an authenticated browser context for the frontend render route."""

    context = browser.new_context(
        viewport={"width": 794, "height": 1123},
        device_scale_factor=device_scale_factor,
        service_workers="block",
    )
    try:
        context.route("**/*", route_render_image)
        if access_token and token_expires_at:
            auth_session = {
                "username": username or "resume-render",
                "accessToken": access_token,
                "expiresAt": token_expires_at,
            }
            render_base = json.dumps(_normalize_render_base_url())
            context.add_init_script(
                f"if (window.location.origin === new URL({render_base}).origin) {{"
                "window.localStorage.setItem("
                "'reseno-auth-session', "
                f"{json.dumps(json.dumps(auth_session))}"
                ");}",
            )

    except BaseException:
        context.close()
        raise

    return context


def _wait_for_resume_render(page: Page, render_url: str, timeout: int) -> None:
    """Wait until the saved resume and all visual assets are ready to export."""

    # The frontend owns pagination and marks the page ready only after fonts
    # and images settle. Both PDF and image exports therefore share this gate.
    deadline = monotonic() + timeout / 1000
    page.goto(render_url, wait_until="domcontentloaded", timeout=timeout)
    remaining_timeout = max(1, (deadline - monotonic()) * 1000)
    page.wait_for_selector("[data-pdf-ready='true']", timeout=remaining_timeout)


def write_resume_pdf(
    export_id: str,
    request: ExportResumeRenderRequest,
    *,
    document_locale: DocumentLocale,
    renderer: ResumeRenderer,
    access_token: str | None = None,
    token_expires_at: str | None = None,
    username: str | None = None,
) -> Path:
    """Render the saved frontend resume view and write it as a PDF."""

    settings = get_settings()
    export_dir = settings.export_dir
    export_dir.mkdir(parents=True, exist_ok=True)
    export_path = get_export_path(export_id)
    render_url = build_render_url(request, document_locale)
    timeout = settings.pdf_render_timeout_ms

    def render(browser: Browser) -> Path:
        context = _create_render_context(
            browser,
            access_token=access_token,
            token_expires_at=token_expires_at,
            username=username,
        )

        try:
            page = context.new_page()
            _wait_for_resume_render(page, render_url, timeout)
            page.emulate_media(media="print")
            pdf_bytes = page.pdf(
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
            export_path.write_bytes(coalesce_pdf_text_runs(pdf_bytes))
        finally:
            context.close()
        return export_path

    try:
        return renderer.render(render)
    except PlaywrightTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="PDF_RENDER_TIMEOUT",
        ) from exc
    except PlaywrightError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="PDF_RENDER_FAILED",
        ) from exc


def get_image_export_path(export_id: str, *, is_archive: bool) -> Path:
    """Return the path for a single PNG or a multi-page ZIP image export."""

    extension = "zip" if is_archive else "png"
    return get_settings().export_dir / f"{export_id}.{extension}"


def safe_image_file_name(seed: str, *, is_archive: bool) -> str:
    """Convert user-provided text into a safe PNG or ZIP filename."""

    normalized = sub(r'[\\/:*?"<>|\x00-\x1f]+', "-", seed.strip()).strip(" .-_")
    file_name = normalized or "resume"
    extension = ".zip" if is_archive else ".png"

    if file_name.lower().endswith(extension):
        return file_name

    return f"{file_name}{extension}"


def write_resume_images(
    export_id: str,
    request: ExportResumeRenderRequest,
    *,
    document_locale: DocumentLocale,
    renderer: ResumeRenderer,
    access_token: str | None = None,
    token_expires_at: str | None = None,
    username: str | None = None,
) -> ResumeImageExportResult:
    """Render every resume page as PNG, zipping only multi-page exports."""

    settings = get_settings()
    settings.export_dir.mkdir(parents=True, exist_ok=True)
    render_url = build_render_url(request, document_locale)
    timeout = settings.pdf_render_timeout_ms

    def render(browser: Browser) -> ResumeImageExportResult:
        context = _create_render_context(
            browser,
            access_token=access_token,
            token_expires_at=token_expires_at,
            username=username,
            device_scale_factor=2,
        )
        try:
            page = context.new_page()
            _wait_for_resume_render(page, render_url, timeout)
            page.emulate_media(media="print")
            resume_pages = page.locator("[data-export-root='resume-page']")
            page_count = resume_pages.count()
            if page_count < 1:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="EXPORT_RENDERER_NO_PAGES",
                )

            is_archive = page_count > 1
            export_path = get_image_export_path(
                export_id,
                is_archive=is_archive,
            )
            if is_archive:
                with ZipFile(export_path, "w", ZIP_DEFLATED) as archive:
                    for index in range(page_count):
                        image = resume_pages.nth(index).screenshot(
                            type="png",
                            animations="disabled",
                        )
                        archive.writestr(f"page-{index + 1}.png", image)
            else:
                image = resume_pages.first.screenshot(
                    type="png",
                    animations="disabled",
                )
                export_path.write_bytes(image)
        finally:
            context.close()
        return ResumeImageExportResult(
            path=export_path,
            page_count=page_count,
            is_archive=is_archive,
        )

    try:
        return renderer.render(render)
    except PlaywrightTimeoutError as exc:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="IMAGE_RENDER_TIMEOUT",
        ) from exc
    except PlaywrightError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="IMAGE_RENDER_FAILED",
        ) from exc


def require_export_file(export_id: str) -> Path:
    """Return an export path or raise when the PDF no longer exists."""

    export_path = get_export_path(export_id)
    try:
        expired = _export_has_expired(export_path, datetime.now(UTC))
    except FileNotFoundError:
        expired = False

    if expired:
        export_path.unlink(missing_ok=True)

    if not export_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="EXPORT_FILE_NOT_FOUND",
        )

    return export_path


def require_image_export_file(export_id: str) -> Path:
    """Return an image export path or raise when it no longer exists."""

    for is_archive in (False, True):
        export_path = get_image_export_path(export_id, is_archive=is_archive)
        try:
            expired = _export_has_expired(export_path, datetime.now(UTC))
        except FileNotFoundError:
            continue

        if expired:
            export_path.unlink(missing_ok=True)
            continue

        return export_path

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="EXPORT_FILE_NOT_FOUND",
    )
