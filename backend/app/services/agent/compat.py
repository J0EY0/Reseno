from collections.abc import Awaitable
from typing import Protocol, cast

from .integrations import WebReference, WebSearchReference, WebSearchResult


class AgentApi(Protocol):
    """Monkeypatch surface for agent web integrations."""

    def _fetch_web_reference(self, url: str) -> WebReference | None: ...

    def _async_fetch_web_reference(
        self,
        url: str,
    ) -> Awaitable[WebReference | None]: ...

    def _search_web_reference(
        self,
        query: str,
    ) -> tuple[WebSearchResult | None, int, str | None]: ...

    def _async_search_web_reference(
        self,
        query: str,
    ) -> Awaitable[tuple[WebSearchResult | None, int, str | None]]: ...

    def _search_web_reference_summary(
        self,
        queries: list[str],
        max_results: int = ...,
    ) -> WebSearchReference: ...

    def _async_search_web_reference_summary(
        self,
        queries: list[str],
        max_results: int = ...,
    ) -> Awaitable[WebSearchReference]: ...


def get_agent_api() -> AgentApi:
    """Return the package root so tests can monkeypatch legacy import paths."""

    import app.services.agent as agent_api

    return cast(AgentApi, agent_api)
