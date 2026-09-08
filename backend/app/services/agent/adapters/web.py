from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, cast

from app.schemas.agent import AgentChatRequest, AgentSource, AgentToolInvocation
from app.services.llm import LlmToolCall

from ..integrations import web as web_transport
from ..localization import agent_text
from ..privacy import sanitize_agent_text, sanitize_agent_value
from ..runtime.context import AgentRuntimeContext

PUBLIC_URL_PATTERN = re.compile(r'https?://[^\s)>"\]]+')
SEARCH_OBSERVATION_MAX_PASSAGES = 8
WEB_PASSAGE_SECTION_MAX_CHARS = 160


@dataclass
class WebToolAdapter:
    """Fetch public references behind one small, security-preserving interface."""

    _locale: str
    _prompt: str
    _hidden_terms: tuple[str, ...]
    _fetch_context_by_url: dict[str, tuple[str, str]]
    _reference_by_url: dict[str, web_transport.WebReference]
    _browser: web_transport.WebBrowser

    @classmethod
    def open(
        cls,
        request: AgentChatRequest,
        prompt: str,
        hidden_terms: tuple[str, ...],
    ) -> WebToolAdapter:
        """Open one turn-scoped adapter with reusable search context."""

        adapter = cls(
            _locale=request.locale,
            _prompt=prompt,
            _hidden_terms=hidden_terms,
            _fetch_context_by_url={},
            _reference_by_url={},
            _browser=web_transport.WebBrowser(),
        )
        for prompt_url in PUBLIC_URL_PATTERN.findall(prompt):
            adapter._remember_url(prompt_url)
        for item in request.messages:
            response = item.response
            if not isinstance(response, dict):
                continue
            sources = response.get("sources")
            if not isinstance(sources, list):
                continue
            for source in sources:
                if not isinstance(source, dict) or source.get("sourceType") != "web":
                    continue
                source_url = source.get("url")
                if not isinstance(source_url, str):
                    continue
                adapter._remember_url(
                    source_url,
                    title=sanitize_agent_text(
                        str(source.get("title") or ""),
                        hidden_terms=hidden_terms,
                    ),
                )
        return adapter

    async def invoke(
        self,
        tool_call: LlmToolCall,
        runtime: AgentRuntimeContext,
    ) -> AgentToolInvocation:
        """Execute one schema-validated public-web call."""

        if tool_call.name == "web_search":
            return await self._search(tool_call, runtime)
        if tool_call.name == "web_fetch":
            return await self._fetch(tool_call, runtime)
        raise ValueError(f"Unsupported web tool: {tool_call.name}")

    def sources(
        self,
        tools: tuple[AgentToolInvocation, ...],
    ) -> tuple[AgentSource, ...]:
        """Project readable page results into stable web sources."""

        sources: dict[str, AgentSource] = {}
        for tool in tools:
            if tool.title not in {"web_search", "web_fetch"} or not isinstance(
                tool.output,
                dict,
            ):
                continue
            references = tool.output.get("references")
            if not isinstance(references, list):
                continue
            for result in references:
                if not isinstance(result, dict):
                    continue
                source_id = result.get("sourceId")
                url = result.get("url")
                if (
                    not isinstance(source_id, str)
                    or not source_id
                    or not isinstance(url, str)
                    or not url
                ):
                    continue
                title = result.get("title")
                excerpt = _reference_excerpt(result)
                sources[source_id] = AgentSource(
                    id=source_id,
                    title=(
                        title.strip()
                        if isinstance(title, str) and title.strip()
                        else url
                    ),
                    sourceType="web",
                    url=url,
                    excerpt=(excerpt.strip() if excerpt.strip() else None),
                )
        return tuple(sources.values())

    async def _search(
        self,
        tool_call: LlmToolCall,
        runtime: AgentRuntimeContext,
    ) -> AgentToolInvocation:
        prompt_text = self._prompt.casefold()
        query_hidden_terms = tuple(
            term if term.casefold() not in prompt_text else ""
            for term in self._hidden_terms
        )
        query = sanitize_agent_text(
            str(tool_call.arguments.get("query") or "").strip(),
            hidden_terms=query_hidden_terms,
        )[:500].strip()
        if not query:
            return self._error(
                tool_call,
                "error.web_search_failed",
                input_payload={"query": query},
                output={"reason": "invalid_query"},
            )

        time_range = cast(str | None, tool_call.arguments.get("timeRange"))
        include_domains = web_transport._normalized_search_domains(
            tuple(
                domain
                for raw_domain in cast(
                    list[str],
                    tool_call.arguments.get("includeDomains") or [],
                )
                if (domain := raw_domain.strip().casefold())
                and sanitize_agent_text(
                    domain,
                    hidden_terms=self._hidden_terms,
                )
                == domain
            ),
        )
        response = await runtime.run_async(
            web_transport._async_search_web,
            query,
            time_range,
            include_domains,
            self._browser,
            timeout_seconds=web_transport.SEARCH_TIMEOUT_SECONDS + 1.0,
        )
        input_payload: dict[str, Any] = {"query": query}
        if time_range:
            input_payload["timeRange"] = time_range
        if include_domains:
            input_payload["includeDomains"] = list(include_domains)
        if response.error_reason:
            return self._error(
                tool_call,
                "error.web_search_failed",
                input_payload=input_payload,
                output={"reason": response.error_reason},
            )

        references: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        for result in response.results[: web_transport.SEARCH_MAX_RESULTS]:
            if (
                sanitize_agent_text(
                    result.url,
                    hidden_terms=self._hidden_terms,
                )
                != result.url
            ):
                continue
            self._remember_url(
                result.url,
                query=query,
                title=sanitize_agent_text(
                    result.title,
                    hidden_terms=self._hidden_terms,
                ),
            )
            if result.source_kind == "fetched_page":
                reference = web_transport.WebReference(
                    title=result.title,
                    excerpt=result.excerpt,
                    final_url=result.url,
                    published_date=result.published_date,
                    valid_through=result.valid_through,
                    passages=result.passages,
                )
                self._remember_reference(
                    result.url,
                    reference,
                )
                references.append(_web_reference_payload(reference))
            else:
                candidates.append(_web_candidate_payload(result))

        return AgentToolInvocation(
            id=tool_call.id,
            type="tool-web_search",
            title="web_search",
            state="output-available",
            input=input_payload,
            output=self._sanitize_output(
                {
                    "references": _bounded_search_references(references),
                    "candidates": candidates,
                },
            ),
        )

    async def _fetch(
        self,
        tool_call: LlmToolCall,
        runtime: AgentRuntimeContext,
    ) -> AgentToolInvocation:
        url = str(tool_call.arguments.get("url") or "").strip()
        canonical_url = _canonical_fetch_url(url)
        known_url = canonical_url in self._fetch_context_by_url
        if (
            sanitize_agent_text(url, hidden_terms=self._hidden_terms) != url
            and not known_url
        ):
            return self._error(
                tool_call,
                "error.web_fetch_failed",
                output={"reason": "invalid_url"},
            )
        search_query, reference_title = self._fetch_context(url)
        relevance_query = search_query or sanitize_agent_text(
            self._prompt,
            hidden_terms=self._hidden_terms,
        )
        reference = self._reference_by_url.get(canonical_url)
        if reference is None:
            reference = await runtime.run_async(
                web_transport._async_fetch_web_reference,
                url,
                relevance_query,
                reference_title,
                self._browser,
            )
        if reference is None:
            return self._error(
                tool_call,
                "error.web_fetch_failed",
                output={"reason": "unreadable"},
            )

        source_url = reference.final_url or url
        output = self._sanitize_output(
            {
                "references": [
                    _web_reference_payload(
                        web_transport.WebReference(
                            title=reference_title or reference.title,
                            excerpt=reference.excerpt,
                            final_url=source_url,
                            published_date=reference.published_date,
                            valid_through=reference.valid_through,
                            passages=reference.passages,
                        ),
                    ),
                ],
            },
        )
        self._remember_reference(url, reference)
        self._remember_reference(source_url, reference)
        if known_url and _canonical_fetch_url(source_url) == canonical_url:
            output["references"][0]["url"] = source_url
        return AgentToolInvocation(
            id=tool_call.id,
            type="tool-web_fetch",
            title="web_fetch",
            state="output-available",
            input={"url": url},
            output=output,
        )

    async def close(self) -> None:
        await self._browser.close()

    def _remember_url(
        self,
        url: str,
        *,
        query: str = "",
        title: str = "",
    ) -> None:
        canonical = _canonical_fetch_url(url)
        if canonical:
            self._fetch_context_by_url[canonical] = (query, title)

    def _fetch_context(self, url: str) -> tuple[str, str]:
        return self._fetch_context_by_url.get(_canonical_fetch_url(url), ("", ""))

    def _remember_reference(
        self,
        url: str,
        reference: web_transport.WebReference,
    ) -> None:
        canonical = _canonical_fetch_url(url)
        if canonical:
            self._reference_by_url[canonical] = reference

    def _sanitize_output(self, value: dict[str, Any]) -> dict[str, Any]:
        sanitized = sanitize_agent_value(value, hidden_terms=self._hidden_terms)
        return sanitized if isinstance(sanitized, dict) else {}

    def _error(
        self,
        tool_call: LlmToolCall,
        message_key: str,
        *,
        input_payload: dict[str, Any] | None = None,
        output: dict[str, Any],
        error_text: str | None = None,
    ) -> AgentToolInvocation:
        sanitized_input = sanitize_agent_value(
            input_payload if input_payload is not None else tool_call.arguments,
            hidden_terms=self._hidden_terms,
        )
        return AgentToolInvocation(
            id=tool_call.id,
            type=f"tool-{tool_call.name}",
            title=tool_call.name,
            state="output-error",
            input=sanitized_input if isinstance(sanitized_input, dict) else {},
            output=self._sanitize_output(output),
            errorText=error_text or agent_text(self._locale, message_key),
        )


def _canonical_fetch_url(value: str) -> str:
    candidate = value.strip().rstrip(".,;:!?，。；：！？]}'】》")
    return web_transport._canonical_web_url(candidate)


def _web_reference_payload(
    reference: web_transport.WebReference,
) -> dict[str, Any]:
    url = reference.final_url
    result: dict[str, Any] = {
        "url": url,
        "title": reference.title,
        "passages": _web_passage_payloads(reference),
        "sourceId": _web_source_id(url),
    }
    if reference.published_date:
        result["publishedDate"] = reference.published_date
    if reference.valid_through:
        result["validThrough"] = reference.valid_through
    return result


def _web_passage_payloads(
    reference: web_transport.WebReference,
) -> list[dict[str, str]]:
    passages = reference.passages
    if not passages and reference.excerpt.strip():
        passages = (
            web_transport.WebPassage(
                section=reference.title,
                text=reference.excerpt,
            ),
        )
    payloads: list[dict[str, str]] = []
    for passage in passages:
        text = web_transport._compact_text(
            passage.text,
            web_transport.PAGE_PASSAGE_MAX_CHARS,
        )
        if not text:
            continue
        payloads.append(
            {
                "section": web_transport._compact_text(
                    passage.section or reference.title,
                    WEB_PASSAGE_SECTION_MAX_CHARS,
                ),
                "text": text,
            },
        )
    return payloads


def _web_candidate_payload(
    result: web_transport.WebSearchResult,
) -> dict[str, Any]:
    candidate: dict[str, Any] = {
        "url": result.url,
        "title": result.title,
        "snippet": result.excerpt,
    }
    if result.published_date:
        candidate["publishedDate"] = result.published_date
    return candidate


def _bounded_search_references(
    references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Distribute one model-visible passage budget across readable sources."""

    selected_passages: list[list[dict[str, Any]]] = [[] for _reference in references]
    passage_lists = [
        passages if isinstance((passages := reference.get("passages")), list) else []
        for reference in references
    ]
    passage_count = 0
    passage_index = 0
    while passage_count < SEARCH_OBSERVATION_MAX_PASSAGES:
        added = False
        for index, passages in enumerate(passage_lists):
            if passage_index >= len(passages):
                continue
            passage = passages[passage_index]
            if isinstance(passage, dict):
                selected_passages[index].append(passage)
                passage_count += 1
                added = True
            if passage_count >= SEARCH_OBSERVATION_MAX_PASSAGES:
                break
        if not added:
            break
        passage_index += 1

    return [
        {**reference, "passages": passages}
        for reference, passages in zip(
            references,
            selected_passages,
            strict=True,
        )
    ]


def _reference_excerpt(reference: dict[str, Any]) -> str:
    passages = reference.get("passages")
    if not isinstance(passages, list):
        return ""
    return " ".join(
        text.strip()
        for passage in passages
        if isinstance(passage, dict)
        and isinstance((text := passage.get("text")), str)
        and text.strip()
    )


def _web_source_id(url: str) -> str:
    canonical_url = _canonical_fetch_url(url) or url.strip()
    digest = sha256(canonical_url.encode("utf-8")).hexdigest()[:16]
    return f"source-web-{digest}"


__all__ = ["WebToolAdapter"]
