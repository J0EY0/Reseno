from collections.abc import Awaitable, Iterator
from typing import Any, Protocol, cast

from app.services.llm_client import (
    AgentLlmConfig,
    LlmStreamDelta,
    LlmToolCallResponse,
)

from .integrations import WebReference, WebSearchResult


class AgentApi(Protocol):
    """Legacy monkeypatch surface exposed through app.services.agent."""

    def complete_chat(
        self,
        config: AgentLlmConfig,
        messages: list[dict[str, Any]],
    ) -> str: ...

    def complete_chat_stream(
        self,
        config: AgentLlmConfig,
        messages: list[dict[str, Any]],
    ) -> Iterator[LlmStreamDelta]: ...

    def complete_chat_tool_call(
        self,
        config: AgentLlmConfig,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LlmToolCallResponse: ...

    def _fetch_web_reference(self, url: str) -> WebReference | None: ...

    def _async_fetch_web_reference(
        self,
        url: str,
    ) -> Awaitable[WebReference | None]: ...

    def _search_jd_reference(
        self,
        query: str,
    ) -> tuple[WebSearchResult | None, int, str | None]: ...

    def _async_search_jd_reference(
        self,
        query: str,
    ) -> Awaitable[tuple[WebSearchResult | None, int, str | None]]: ...


def get_agent_api() -> AgentApi:
    """Return the package root so tests can monkeypatch legacy import paths."""

    import app.services.agent as agent_api

    return cast(AgentApi, agent_api)
