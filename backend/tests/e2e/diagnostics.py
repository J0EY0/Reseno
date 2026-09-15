import inspect
import json
import re
import shutil
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright import async_api, sync_api

DIAGNOSTICS = pytest.StashKey["BrowserDiagnostics"]()
SERVER_LOGS = pytest.StashKey[dict[str, Path]]()


class BrowserDiagnostics:
    def __init__(self, root: Path, nodeid: str) -> None:
        root.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^a-zA-Z0-9_-]", "-", nodeid)[-100:]
        self.directory = Path(tempfile.mkdtemp(prefix=f"{name}-", dir=root))
        self.contexts: dict[Any, dict[str, Any]] = {}
        self.events: list[dict[str, str]] = []
        self.errors: list[str] = []
        self.failed = False

    def _page(self, context: Any, page: Any) -> None:
        pages = self.contexts[context]["pages"]
        if page in pages:
            return
        pages[page] = len(pages) + 1

        def record(kind: str, message: str) -> None:
            self.events.append({"kind": kind, "url": page.url, "message": message})

        page.on("pageerror", lambda error: record("pageerror", str(error)))
        page.on(
            "console",
            lambda message: (
                record("console", message.text) if message.type == "error" else None
            ),
        )

    def _created(self, value: Any) -> Iterator[Callable[[], Any]]:
        context = (
            value.context
            if isinstance(value, (sync_api.Page, async_api.Page))
            else value
        )
        if context in self.contexts:
            return
        self.contexts[context] = {
            "number": len(self.contexts) + 1,
            "pages": {},
            "captured": set(),
            "finished": False,
            "owned_page": isinstance(value, (sync_api.Page, async_api.Page)),
        }
        context.on("page", lambda page: self._page(context, page))
        for page in context.pages:
            self._page(context, page)
        yield lambda: context.tracing.start(
            screenshots=True, snapshots=True, sources=True
        )

    def _screenshot(self, page: Any) -> Iterator[Callable[[], Any]]:
        record = self.contexts.get(page.context)
        if record is None or page in record["captured"] or page.is_closed():
            return
        self._page(page.context, page)
        record["captured"].add(page)
        path = self.directory / (
            f"context-{record['number']}-page-{record['pages'][page]}.png"
        )
        yield lambda: page.screenshot(path=str(path), timeout=1_000)

    def _context(self, context: Any) -> Iterator[Callable[[], Any]]:
        record = self.contexts.get(context)
        if record is None or record["finished"]:
            return
        record["finished"] = True
        for page in context.pages:
            yield from self._screenshot(page)
        path = self.directory / f"context-{record['number']}-trace.zip"
        yield lambda: context.tracing.stop(path=str(path))

    def _closing(self, value: Any) -> Iterator[Callable[[], Any]]:
        if isinstance(value, (sync_api.Page, async_api.Page)):
            record = self.contexts.get(value.context)
            if record is not None and record["owned_page"]:
                yield from self._context(value.context)
            else:
                yield from self._screenshot(value)
        elif isinstance(value, (sync_api.BrowserContext, async_api.BrowserContext)):
            yield from self._context(value)
        else:
            for context in value.contexts:
                yield from self._context(context)

    def _run(self, operations: Iterator[Callable[[], Any]]) -> None:
        try:
            for operation in operations:
                try:
                    operation()
                except Exception as error:
                    self.errors.append(str(error))
        except Exception as error:
            self.errors.append(str(error))

    async def _run_async(self, operations: Iterator[Callable[[], Any]]) -> None:
        try:
            for operation in operations:
                try:
                    result = operation()
                    if inspect.isawaitable(result):
                        await result
                except Exception as error:
                    self.errors.append(str(error))
        except Exception as error:
            self.errors.append(str(error))

    def _wrap(self, original: Any, *, closing: bool, asynchronous: bool) -> Any:
        if asynchronous:

            async def wrapped(owner: Any, *args: Any, **kwargs: Any) -> Any:
                if closing:
                    await self._run_async(self._closing(owner))
                result = await original(owner, *args, **kwargs)
                if not closing:
                    await self._run_async(self._created(result))
                return result
        else:

            def wrapped(owner: Any, *args: Any, **kwargs: Any) -> Any:
                if closing:
                    self._run(self._closing(owner))
                result = original(owner, *args, **kwargs)
                if not closing:
                    self._run(self._created(result))
                return result

        return wrapped

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for api, asynchronous in ((sync_api, False), (async_api, True)):
            for owner, method, closing in (
                (api.Browser, "new_context", False),
                (api.Browser, "new_page", False),
                (api.Browser, "close", True),
                (api.BrowserContext, "close", True),
                (api.Page, "close", True),
            ):
                monkeypatch.setattr(
                    owner,
                    method,
                    self._wrap(
                        getattr(owner, method),
                        closing=closing,
                        asynchronous=asynchronous,
                    ),
                )

    def finish_open_contexts(self) -> None:
        for context in list(self.contexts):
            if isinstance(context, sync_api.BrowserContext):
                self._run(self._context(context))

    def copy_logs(self, logs: dict[str, Path]) -> None:
        for name, source in logs.items():
            try:
                if source.exists():
                    shutil.copyfile(source, self.directory / name)
            except OSError as error:
                self.errors.append(str(error))

    def report(self, report: pytest.TestReport) -> None:
        if report.failed:
            self.failed = True
            try:
                (self.directory / f"{report.when}-failure.txt").write_text(
                    str(report.longrepr), encoding="utf-8"
                )
            except OSError as error:
                self.errors.append(str(error))

    def finish(self) -> None:
        try:
            if self.failed:
                (self.directory / "page-errors.json").write_text(
                    json.dumps(self.events, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                if self.errors:
                    (self.directory / "diagnostics-errors.txt").write_text(
                        "\n".join(self.errors), encoding="utf-8"
                    )
            else:
                shutil.rmtree(self.directory)
        except OSError:
            pass
        finally:
            self.contexts.clear()
