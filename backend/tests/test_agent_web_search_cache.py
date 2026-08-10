import asyncio
import json
import threading

import pytest

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.integrations import WebSearchReference, WebSearchResult
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.tools.runner import (
    MAX_WEB_SEARCH_CACHE_ENTRIES,
    AgentToolRunner,
)
from app.services.llm import LlmToolCall


def _runner() -> AgentToolRunner:
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-web-search-cache",
            role="user",
            text="Search for public target context.",
        ),
        locale="en",
        resume={"basic": {}, "sections": []},
    )
    return AgentToolRunner(AgentPlanExecutor(request))


def _search_call(call_id: str, query: str) -> LlmToolCall:
    arguments = {
        "purpose": "company_reference",
        "query": query,
        "maxResults": 1,
    }
    return LlmToolCall(
        id=call_id,
        name="web_search",
        arguments=arguments,
        raw_arguments=json.dumps(arguments),
    )


def _summary_search_call(call_id: str, queries: list[str]) -> LlmToolCall:
    arguments = {
        "purpose": "company_reference",
        "queries": queries,
        "maxResults": 3,
    }
    return LlmToolCall(
        id=call_id,
        name="web_search",
        arguments=arguments,
        raw_arguments=json.dumps(arguments),
    )


def test_duplicate_normalized_web_search_calls_network_once(monkeypatch) -> None:
    runner = _runner()
    network_queries: list[str] = []
    result = WebSearchResult(
        title="Platform engineering",
        url="https://example.test/platform",
        excerpt="Public platform engineering context.",
    )

    def fake_search(query: str) -> tuple[WebSearchResult, int, None]:
        network_queries.append(query)
        return result, 1, None

    monkeypatch.setattr(
        "app.services.agent._search_web_reference",
        fake_search,
    )

    async def run_duplicate_searches() -> None:
        runtime = AgentRuntimeContext()
        first = await runner.run_web_search_async(
            _search_call("search-1", "  Platform   Engineering  "),
            runtime,
        )
        second = await runner.run_web_search_async(
            _search_call("search-2", "platform engineering"),
            runtime,
        )
        assert first.state == "output-available"
        assert second.state == "output-available"

    asyncio.run(run_duplicate_searches())

    assert network_queries == ["Platform Engineering"]


def test_duplicate_normalized_web_search_summary_calls_network_once(
    monkeypatch,
) -> None:
    runner = _runner()
    network_calls: list[tuple[list[str], int]] = []
    result = WebSearchResult(
        title="Platform engineering",
        url="https://example.test/platform",
        excerpt="Public platform engineering context.",
    )

    def fake_search_summary(
        queries: list[str],
        max_results: int,
    ) -> WebSearchReference:
        network_calls.append((queries, max_results))
        return WebSearchReference(
            query=queries[0],
            results=(result,),
            query_count=len(queries),
            result_count=1,
            timed_out=True,
            partial=True,
        )

    monkeypatch.setattr(
        "app.services.agent._search_web_reference_summary",
        fake_search_summary,
    )

    async def run_duplicate_searches() -> None:
        runtime = AgentRuntimeContext()
        first = await runner.run_web_search_async(
            _summary_search_call(
                "search-1",
                ["  Platform   Engineering  ", "Developer Experience"],
            ),
            runtime,
        )
        second = await runner.run_web_search_async(
            _summary_search_call(
                "search-2",
                ["platform engineering", "developer experience"],
            ),
            runtime,
        )
        assert first.state == "output-available"
        assert second.state == "output-available"
        assert second.output["partial"] is True

    asyncio.run(run_duplicate_searches())

    assert network_calls == [
        (["Platform Engineering", "Developer Experience"], 3),
    ]


def test_failed_web_search_is_not_cached(monkeypatch) -> None:
    runner = _runner()
    network_queries: list[str] = []

    def fake_search(
        query: str,
    ) -> tuple[None, int, str]:
        network_queries.append(query)
        return None, 0, "temporary search failure"

    monkeypatch.setattr(
        "app.services.agent._search_web_reference",
        fake_search,
    )

    async def run_failed_searches() -> None:
        runtime = AgentRuntimeContext()
        await runner.run_web_search_async(
            _search_call("search-1", "Platform Engineering"),
            runtime,
        )
        await runner.run_web_search_async(
            _search_call("search-2", "platform engineering"),
            runtime,
        )

    asyncio.run(run_failed_searches())

    assert network_queries == [
        "Platform Engineering",
        "platform engineering",
    ]


def test_cancelled_web_search_is_not_cached(monkeypatch) -> None:
    runner = _runner()
    network_queries: list[str] = []
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()
    result = WebSearchResult(
        title="Platform engineering",
        url="https://example.test/platform",
        excerpt="Public platform engineering context.",
    )

    def blocked_search(query: str) -> tuple[WebSearchResult, int, None]:
        network_queries.append(query)
        if len(network_queries) == 1:
            worker_started.set()
            try:
                release_worker.wait(timeout=2)
            finally:
                worker_finished.set()
        return result, 1, None

    monkeypatch.setattr(
        "app.services.agent._search_web_reference",
        blocked_search,
    )

    async def cancel_then_retry() -> None:
        runtime = AgentRuntimeContext()
        task = asyncio.create_task(
            runner.run_web_search_async(
                _search_call("search-1", "Platform Engineering"),
                runtime,
            ),
        )
        assert await asyncio.to_thread(worker_started.wait, 1)
        task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await task
        finally:
            release_worker.set()
            assert await asyncio.to_thread(worker_finished.wait, 1)

        retry = await runner.run_web_search_async(
            _search_call("search-2", "platform engineering"),
            runtime,
        )
        assert retry.state == "output-available"

    asyncio.run(cancel_then_retry())

    assert network_queries == [
        "Platform Engineering",
        "platform engineering",
    ]


def test_web_search_cache_evicts_least_recent_entry() -> None:
    runner = _runner()

    for index in range(MAX_WEB_SEARCH_CACHE_ENTRIES + 1):
        result = WebSearchResult(
            title=f"Result {index}",
            url=f"https://example.test/{index}",
            excerpt=f"Public context {index}.",
        )
        runner.cache_web_search(
            [f"query {index}"],
            1,
            WebSearchReference(
                query=f"query {index}",
                results=(result,),
                query_count=1,
                result_count=1,
            ),
        )

    assert len(runner._web_search_cache) == MAX_WEB_SEARCH_CACHE_ENTRIES
    assert runner.cached_web_search(["query 0"], 1) is None
    assert runner.cached_web_search(["query 1"], 1) is not None
