import logging
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore, Lock
from typing import TypeVar

from fastapi import HTTPException, status
from playwright.sync_api import Browser, Playwright, sync_playwright
from playwright.sync_api import Error as PlaywrightError

from app.config import get_settings

MAX_PENDING_RENDERS = 4
T = TypeVar("T")
logger = logging.getLogger(__name__)


class ResumeRenderer:
    """Own one browser on a dedicated thread with bounded export admission."""

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="resume-render",
        )
        self._capacity = BoundedSemaphore(MAX_PENDING_RENDERS)
        self._lock = Lock()
        self._closing: Future[None] | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None

    def render(self, operation: Callable[[Browser], T]) -> T:
        if not self._capacity.acquire(blocking=False):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="EXPORT_RENDERER_BUSY",
                headers={"Retry-After": "1"},
            )
        try:
            with self._lock:
                if self._closing is not None:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="EXPORT_RENDERER_UNAVAILABLE",
                    )
                future = self._executor.submit(self._render, operation)
            return future.result()
        finally:
            self._capacity.release()

    def _render(self, operation: Callable[[Browser], T]) -> T:
        try:
            if self._browser is None or not self._browser.is_connected():
                self._close_browser()
                self._playwright = sync_playwright().start()
                executable = get_settings().chromium_executable
                self._browser = (
                    self._playwright.chromium.launch(
                        headless=True,
                        executable_path=executable,
                    )
                    if executable
                    else self._playwright.chromium.launch(headless=True)
                )
            return operation(self._browser)
        except PlaywrightError:
            self._close_browser()
            raise

    def close(self) -> None:
        """Finish admitted exports and stop browser resources on their owning thread."""

        with self._lock:
            if self._closing is None:
                self._closing = self._executor.submit(self._close_browser)
            closing = self._closing
        try:
            closing.result()
        finally:
            self._executor.shutdown(wait=True)

    def _close_browser(self) -> None:
        browser, playwright = self._browser, self._playwright
        self._browser = None
        self._playwright = None
        if browser is not None:
            try:
                browser.close()
            except PlaywrightError:
                logger.warning("Could not close the export browser cleanly.")
        if playwright is not None:
            try:
                playwright.stop()
            except PlaywrightError:
                logger.warning("Could not stop the export browser driver cleanly.")
