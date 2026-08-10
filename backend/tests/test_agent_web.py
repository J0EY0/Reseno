from __future__ import annotations

import asyncio
import socket
from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import urlparse

import httpx
import pytest

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.integrations import web as agent_web
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.tools.runner import AgentToolRunner
from app.services.llm import LlmToolCall


class _FakeNetworkStream:
    """Expose the peer metadata that httpcore attaches to real responses."""

    def __init__(self, address: str) -> None:
        self.address = address

    def get_extra_info(self, key: str):
        if key == "server_addr":
            return (self.address, 443)
        return None


def _peer_extensions(address: str = "93.184.216.34") -> dict[str, object]:
    return {"network_stream": _FakeNetworkStream(address)}


def _web_tool_call(name: str, arguments: dict[str, object]) -> LlmToolCall:
    return LlmToolCall(
        id=f"call-{name}",
        name=name,
        arguments=arguments,
        raw_arguments="{}",
    )


def _agent_runner(
    *,
    prompt: str,
    target_description: str = "",
) -> AgentToolRunner:
    messages = (
        [
            AgentConversationItem(
                id="assistant-agent-web-target",
                role="assistant",
                text="目标已更新。",
                response={
                    "id": "assistant-agent-web-target",
                    "role": "assistant",
                    "text": "目标已更新。",
                    "targetContext": {
                        "kind": "general",
                        "description": target_description,
                    },
                },
            ),
        ]
        if target_description
        else []
    )
    request = AgentChatRequest(
        message=AgentConversationItem(
            id=f"turn-agent-web-{prompt}",
            role="user",
            text=prompt,
        ),
        messages=messages,
        locale="zh",
        resume={"basic": {}, "sections": []},
    )
    return AgentToolRunner(AgentPlanExecutor(request))


@pytest.mark.parametrize(
    "url",
    (
        "http://localhost/private",
        "http://127.0.0.1/private",
        "http://10.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://100.100.100.200/latest/meta-data",
        "http://198.18.0.157/fake-ip-must-not-be-addressable-directly",
        "http://224.0.0.1/multicast",
        "http://0.0.0.0/unspecified",
        "http://240.0.0.1/reserved",
        "http://[::1]/private",
        "http://metadata.google.internal/computeMetadata/v1",
    ),
)
def test_fetch_web_reference_rejects_non_public_targets_before_request(
    monkeypatch,
    url: str,
) -> None:
    real_client = httpx.Client

    def fail_if_requested(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Non-public targets must not reach the HTTP client.")

    transport = httpx.MockTransport(fail_if_requested)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    assert agent_web._fetch_web_reference(url) is None


def test_fetch_web_reference_rejects_domain_when_any_dns_address_is_private(
    monkeypatch,
) -> None:
    real_client = httpx.Client

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", port)),
        ]

    def fail_if_requested(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Unsafe DNS targets must not reach the HTTP client.")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    transport = httpx.MockTransport(fail_if_requested)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    assert agent_web._fetch_web_reference("https://public.example/resume") is None


def test_fetch_web_reference_accepts_tun_fake_ip_for_external_hostname(
    monkeypatch,
) -> None:
    real_client = httpx.Client
    body = (
        b"<html><head><title>External careers</title></head><body>"
        + (b"Frontend engineering role requirements and responsibilities. " * 8)
        + b"</body></html>"
    )

    def fake_getaddrinfo(
        host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        assert host == "careers.example"
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.157", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions=_peer_extensions("198.18.0.157"),
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    reference = agent_web._fetch_web_reference(
        "https://careers.example/frontend-engineer",
    )

    assert reference is not None
    assert reference.title == "External careers"


def test_fetch_web_reference_rejects_unresolved_fake_ip_peer(monkeypatch) -> None:
    real_client = httpx.Client

    class UnreadableStream(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("An unbound fake-IP response body must not be read.")

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            stream=UnreadableStream(),
            extensions=_peer_extensions("198.18.0.157"),
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    assert agent_web._fetch_web_reference("https://public.example/rebound") is None


def test_fetch_web_reference_revalidates_redirect_targets(monkeypatch) -> None:
    real_client = httpx.Client
    requested_urls: list[str] = []

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def redirect_to_private(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.host == "public.example":
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/private"},
                extensions=_peer_extensions(),
            )
        return httpx.Response(
            200,
            text="<html><body>" + ("private metadata " * 20) + "</body></html>",
            extensions=_peer_extensions(),
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    transport = httpx.MockTransport(redirect_to_private)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=transport,
            follow_redirects=kwargs.get("follow_redirects", False),
        ),
    )

    assert agent_web._fetch_web_reference("https://public.example/start") is None
    assert requested_urls == ["https://public.example/start"]


def test_fetch_web_reference_records_final_public_redirect_url(monkeypatch) -> None:
    real_client = httpx.Client
    body = b"<html><body>" + (b"Public resume evidence. " * 10) + b"</body></html>"

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def redirect_to_public(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(
                302,
                headers={"location": "/final"},
                extensions=_peer_extensions(),
            )
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions=_peer_extensions(),
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    transport = httpx.MockTransport(redirect_to_public)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=transport,
            follow_redirects=kwargs.get("follow_redirects", False),
        ),
    )

    reference = agent_web._fetch_web_reference("https://public.example/start")

    assert reference is not None
    assert reference.final_url == "https://public.example/final"
    assert reference.status_code == 200
    assert reference.content_sha256 == sha256(body).hexdigest()


def test_web_reference_selects_relevant_jd_content_near_page_end() -> None:
    early_filler = "Generic company introduction without role details. " * 30
    html = f"""
        <html>
          <head><title>Staff Platform Engineer</title></head>
          <body>
            <nav>Home Careers About Contact</nav>
            <main>
              <article>
                <p>{early_filler}</p>
                <h2>Qualifications</h2>
                <p>
                  Build Kubernetes platform services and improve observability
                  for production Go workloads.
                </p>
              </article>
            </main>
          </body>
        </html>
    """.encode()

    reference = agent_web._web_reference_from_response(
        "https://jobs.example/roles/platform",
        html,
        "text/html; charset=utf-8",
        "utf-8",
        status_code=200,
        fetched_at="2026-07-28T00:00:00Z",
        content_sha256=sha256(html).hexdigest(),
        relevance_query="platform engineer Kubernetes observability Go",
        reference_title="Staff Platform Engineer",
    )

    assert reference is not None
    assert "Kubernetes platform services" in reference.excerpt
    assert "Generic company introduction" not in reference.excerpt
    assert reference.final_url == "https://jobs.example/roles/platform"
    assert reference.excerpt_section == "Qualifications"
    assert reference.excerpt_start > 0
    assert reference.excerpt_end > reference.excerpt_start


def test_web_fetch_rejects_model_invented_url_before_network(monkeypatch) -> None:
    runner = _agent_runner(prompt="请优化目标岗位简历")

    def fail_if_network_boundary_is_reached() -> object:
        raise AssertionError("An untrusted model URL reached the network boundary.")

    monkeypatch.setattr(
        "app.services.agent.tools.runner.get_agent_api",
        fail_if_network_boundary_is_reached,
    )

    tool = asyncio.run(
        runner.run_web_fetch_async(
            _web_tool_call(
                "web_fetch",
                {
                    "url": "https://invented.example/jobs/123",
                    "purpose": "jd",
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-error"
    assert tool.output == {"blocked": True, "reason": "url_not_authorized"}


@pytest.mark.parametrize("source_field", ("prompt", "target_context"))
def test_web_fetch_allows_url_from_user_context(
    monkeypatch,
    source_field: str,
) -> None:
    url = "https://portfolio.example/projects/search"
    runner = _agent_runner(
        prompt=f"请查看 {url}" if source_field == "prompt" else "请查看项目材料",
        target_description=url if source_field == "target_context" else "",
    )

    def fake_fetch(requested_url: str) -> agent_web.WebReference:
        assert requested_url == url
        return agent_web.WebReference(
            title="Search project",
            excerpt="Implemented a public search project with measurable outcomes.",
            final_url=url,
            excerpt_end=62,
        )

    monkeypatch.setattr(
        "app.services.agent._fetch_web_reference",
        fake_fetch,
    )

    tool = asyncio.run(
        runner.run_web_fetch_async(
            _web_tool_call(
                "web_fetch",
                {"url": url, "purpose": "project_reference"},
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-available"
    assert tool.output and tool.output["url"] == url


def test_web_fetch_allows_url_returned_by_current_web_search(monkeypatch) -> None:
    url = "https://company.example/careers/platform"
    runner = _agent_runner(prompt="请搜索并分析目标公司")
    search_result = agent_web.WebSearchResult(
        title="Platform careers",
        url=url,
        excerpt="Public company platform engineering information.",
    )

    monkeypatch.setattr(
        "app.services.agent._search_web_reference",
        lambda _query: (search_result, 1, None),
    )
    search_tool = asyncio.run(
        runner.run_web_search_async(
            _web_tool_call(
                "web_search",
                {
                    "query": "company platform engineering",
                    "purpose": "company_reference",
                },
            ),
            AgentRuntimeContext(),
        ),
    )
    assert search_tool.state == "output-available"

    monkeypatch.setattr(
        "app.services.agent._fetch_web_reference",
        lambda requested_url: agent_web.WebReference(
            title="Platform careers",
            excerpt="Detailed public company platform engineering information.",
            final_url=requested_url,
            excerpt_end=56,
        ),
    )
    fetch_tool = asyncio.run(
        runner.run_web_fetch_async(
            _web_tool_call(
                "web_fetch",
                {"url": url, "purpose": "company_reference"},
            ),
            AgentRuntimeContext(),
        ),
    )

    assert fetch_tool.state == "output-available"
    assert fetch_tool.output and fetch_tool.output["url"] == url


def test_fetch_web_reference_limits_redirect_count(monkeypatch) -> None:
    real_client = httpx.Client
    requested_urls: list[str] = []

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def redirect_forever(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        hop = int(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(
            302,
            headers={"location": f"/hop/{hop + 1}"},
            extensions=_peer_extensions(),
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    transport = httpx.MockTransport(redirect_forever)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=transport,
            follow_redirects=kwargs.get("follow_redirects", False),
        ),
    )

    assert agent_web._fetch_web_reference("https://public.example/hop/0") is None
    assert len(requested_urls) == agent_web.MAX_WEB_REDIRECTS + 1


def test_fetch_web_reference_allows_public_target_and_records_metadata(
    monkeypatch,
) -> None:
    real_client = httpx.Client
    body = (
        b"<html><head><title>Public resume guide</title></head><body>"
        + (b"Evidence-based resume guidance for applicants. " * 8)
        + b"</body></html>"
    )

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions=_peer_extensions(),
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    reference = agent_web._fetch_web_reference(
        "https://public.example/resume-guide",
    )

    assert reference is not None
    assert reference.final_url == "https://public.example/resume-guide"
    assert reference.status_code == 200
    assert reference.content_sha256 == sha256(body).hexdigest()
    assert datetime.fromisoformat(reference.fetched_at.replace("Z", "+00:00"))


def test_web_reference_rejects_binary_pdf_content() -> None:
    raw = b"%PDF-1.7\n" + (b"apparently readable resume evidence " * 10)

    reference = agent_web._web_reference_from_response(
        "https://public.example/resume.pdf",
        raw,
        "application/pdf",
        "utf-8",
        status_code=200,
        fetched_at="2026-07-27T08:00:00Z",
        content_sha256=sha256(raw).hexdigest(),
    )

    assert reference is None


def test_fetch_web_reference_rejects_private_connected_peer_before_body_read(
    monkeypatch,
) -> None:
    real_client = httpx.Client

    class UnreadableStream(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("A private peer response body must not be read.")

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            stream=UnreadableStream(),
            extensions=_peer_extensions("10.0.0.8"),
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    assert agent_web._fetch_web_reference("https://public.example/rebound") is None


def test_fetch_web_reference_rejects_missing_connected_peer_before_body_read(
    monkeypatch,
) -> None:
    real_client = httpx.Client

    class UnreadableStream(httpx.SyncByteStream):
        def __iter__(self):
            raise AssertionError("An unverifiable peer response body must not be read.")

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, stream=UnreadableStream()),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    assert agent_web._fetch_web_reference("https://public.example/no-peer") is None


def test_fetch_web_reference_stops_reading_at_response_limit(monkeypatch) -> None:
    real_client = httpx.Client
    prefix = (
        b"<html><head><title>Bounded page</title></head><body>"
        + (b"Public resume evidence. " * 8)
        + b"</body></html>"
    )
    second_chunk = b"x" * agent_web.FETCH_MAX_BYTES

    class GuardedStream(httpx.SyncByteStream):
        def __init__(self) -> None:
            self.chunks_read = 0

        def __iter__(self):
            self.chunks_read += 1
            yield prefix
            self.chunks_read += 1
            yield second_chunk
            raise AssertionError("The response body limit was not enforced.")

    stream = GuardedStream()

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            stream=stream,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions=_peer_extensions(),
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **_kwargs: real_client(transport=transport),
    )

    reference = agent_web._fetch_web_reference("https://public.example/large")

    expected_body = (prefix + second_chunk)[: agent_web.FETCH_MAX_BYTES]
    assert reference is not None
    assert stream.chunks_read == 2
    assert reference.content_sha256 == sha256(expected_body).hexdigest()


def test_search_web_results_revalidates_redirect_targets(monkeypatch) -> None:
    real_client = httpx.Client
    requested_urls: list[str] = []

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def redirect_to_private(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        if request.url.host == "search.example":
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/private-search"},
                extensions=_peer_extensions(),
            )
        return httpx.Response(
            200,
            text=(
                '<a class="result__a" href="https://public.example/result">'
                "Public result</a>"
            ),
            extensions=_peer_extensions(),
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web,
        "SEARCH_PROVIDERS",
        (("https://search.example/?q={query}", "html"),),
    )
    transport = httpx.MockTransport(redirect_to_private)
    monkeypatch.setattr(
        agent_web.httpx,
        "Client",
        lambda **kwargs: real_client(
            transport=transport,
            follow_redirects=kwargs.get("follow_redirects", False),
        ),
    )

    results, error = agent_web._search_web_results("resume")

    assert results == []
    assert error
    assert requested_urls == ["https://search.example/?q=resume"]


def test_parse_search_results_canonicalizes_urls_before_deduplication() -> None:
    raw = b"""
        <a class="result__a"
           href="https://Careers.Example:443/jobs/frontend?utm_source=search&amp;team=web#apply">
          Frontend Engineer
        </a>
        <a class="result__a"
           href="https://careers.example/jobs/frontend?team=web&amp;utm_medium=email">
          Duplicate Frontend Engineer
        </a>
    """

    results, error = agent_web._parse_search_results(raw, "utf-8")

    assert error is None
    assert [result.url for result in results] == [
        "https://careers.example/jobs/frontend?team=web",
    ]


def test_parse_rss_search_results_extracts_canonical_links_and_text() -> None:
    raw = b"""<?xml version="1.0" encoding="utf-8"?>
        <rss version="2.0"><channel>
          <item>
            <title>Frontend Engineer</title>
            <link>https://Careers.Example:443/jobs/frontend?utm_source=bing&amp;team=web#apply</link>
            <description>
              &lt;b&gt;React&lt;/b&gt; and TypeScript role requirements.
            </description>
          </item>
          <item>
            <title>Duplicate</title>
            <link>https://careers.example/jobs/frontend?team=web</link>
            <description>Duplicate result.</description>
          </item>
        </channel></rss>
    """

    results, error = agent_web._parse_rss_search_results(raw, "utf-8")

    assert error is None
    assert len(results) == 1
    assert results[0].url == "https://careers.example/jobs/frontend?team=web"
    assert results[0].excerpt == "React and TypeScript role requirements."


def test_repeated_search_survives_one_provider_becoming_unavailable(
    monkeypatch,
) -> None:
    duckduckgo_successes_remaining = 1

    async def fake_get_bounded_response(
        _client: httpx.AsyncClient,
        url: str,
        _byte_limit: int,
    ) -> agent_web._BoundedWebResponse | None:
        nonlocal duckduckgo_successes_remaining
        hostname = urlparse(url).hostname or ""
        if hostname.endswith("duckduckgo.com"):
            if duckduckgo_successes_remaining == 0:
                return None
            duckduckgo_successes_remaining -= 1
            raw = b"""
                <a class="result__a" href="https://careers.alpha.example/jobs/frontend">
                  Alpha Frontend Engineer
                </a>
                <div class="result__snippet">
                  Alpha frontend responsibilities and current role requirements.
                </div>
            """
            content_type = "text/html; charset=utf-8"
        elif hostname == "www.bing.com":
            raw = b"""<?xml version="1.0" encoding="utf-8"?>
                <rss version="2.0"><channel><item>
                  <title>Beta Frontend Engineer</title>
                  <link>https://jobs.beta.example/openings/frontend</link>
                  <description>
                    Beta frontend responsibilities and current role requirements.
                  </description>
                </item></channel></rss>
            """
            content_type = "application/rss+xml; charset=utf-8"
        else:
            raise AssertionError(f"Unexpected search provider URL: {url}")

        return agent_web._BoundedWebResponse(
            raw=raw,
            content_type=content_type,
            charset="utf-8",
            final_url=url,
            status_code=200,
            fetched_at="2026-08-10T00:00:00Z",
            content_sha256=sha256(raw).hexdigest(),
        )

    monkeypatch.setattr(
        agent_web,
        "_async_get_bounded_web_response",
        fake_get_bounded_response,
    )

    async def run() -> list[tuple[list[agent_web.WebSearchResult], str | None]]:
        return [
            await agent_web._async_search_web_results("frontend engineer role")
            for _ in range(5)
        ]

    attempts = asyncio.run(run())

    assert [len(results) for results, _error in attempts] == [1, 1, 1, 1, 1]
    assert [error for _results, error in attempts] == [None] * 5


def test_async_fetch_web_reference_revalidates_redirect_targets(monkeypatch) -> None:
    real_client = httpx.AsyncClient
    requested_urls: list[str] = []

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def redirect_to_private(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/private"},
            extensions=_peer_extensions(),
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    transport = httpx.MockTransport(redirect_to_private)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=transport,
            follow_redirects=kwargs.get("follow_redirects", False),
        ),
    )

    reference = asyncio.run(
        agent_web._async_fetch_web_reference("https://public.example/start"),
    )

    assert reference is None
    assert requested_urls == ["https://public.example/start"]


def test_async_fetch_web_reference_accepts_public_connected_peer(
    monkeypatch,
) -> None:
    real_client = httpx.AsyncClient
    body = (
        b"<html><head><title>Public peer</title></head><body>"
        + (b"Public resume evidence. " * 8)
        + b"</body></html>"
    )

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions=_peer_extensions(),
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )

    reference = asyncio.run(
        agent_web._async_fetch_web_reference(
            "https://public.example/public-peer",
        ),
    )

    assert reference is not None
    assert reference.content_sha256 == sha256(body).hexdigest()


def test_async_fetch_web_reference_rejects_private_connected_peer_before_body_read(
    monkeypatch,
) -> None:
    real_client = httpx.AsyncClient

    class UnreadableStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("A private peer response body must not be read.")
            yield b""  # pragma: no cover

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            stream=UnreadableStream(),
            extensions=_peer_extensions("10.0.0.8"),
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )

    reference = asyncio.run(
        agent_web._async_fetch_web_reference(
            "https://public.example/rebound",
        ),
    )

    assert reference is None


def test_async_search_web_results_revalidates_redirect_targets(monkeypatch) -> None:
    real_client = httpx.AsyncClient
    requested_urls: list[str] = []

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args,
        **_kwargs,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def redirect_to_private(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/private-search"},
            extensions=_peer_extensions(),
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web,
        "SEARCH_PROVIDERS",
        (("https://search.example/?q={query}", "html"),),
    )
    transport = httpx.MockTransport(redirect_to_private)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(
            transport=transport,
            follow_redirects=kwargs.get("follow_redirects", False),
        ),
    )

    results, error = asyncio.run(agent_web._async_search_web_results("resume"))

    assert results == []
    assert error
    assert requested_urls == ["https://search.example/?q=resume"]


def test_search_web_reference_preserves_fetched_evidence_metadata(
    monkeypatch,
) -> None:
    search_result = agent_web.WebSearchResult(
        title="Search title",
        url="https://public.example/redirect",
        excerpt="Search snippet",
    )
    fetched_at = "2026-07-26T08:00:00Z"
    content_sha256 = "a" * 64

    monkeypatch.setattr(
        agent_web,
        "_search_web_results",
        lambda _query: ([search_result], None),
    )
    monkeypatch.setattr(
        agent_web,
        "_fetch_web_reference",
        lambda _url, **_kwargs: agent_web.WebReference(
            title="Fetched title",
            excerpt="Fetched evidence " * 10,
            final_url="https://public.example/final",
            status_code=200,
            fetched_at=fetched_at,
            content_sha256=content_sha256,
        ),
    )

    result, result_count, error = agent_web._search_web_reference("resume")

    assert error is None
    assert result_count == 1
    assert result is not None
    assert result.url == "https://public.example/final"
    assert result.final_url == "https://public.example/final"
    assert result.status_code == 200
    assert result.fetched_at == fetched_at
    assert result.content_sha256 == content_sha256
    assert result.source_kind == "fetched_page"


def test_search_web_reference_marks_search_snippet_fallback(monkeypatch) -> None:
    search_result = agent_web.WebSearchResult(
        title="Search title",
        url="https://public.example/result",
        excerpt="Useful search result evidence for the target role. " * 4,
    )
    monkeypatch.setattr(
        agent_web,
        "_search_web_results",
        lambda _query: ([search_result], None),
    )
    monkeypatch.setattr(
        agent_web,
        "_fetch_web_reference",
        lambda _url, **_kwargs: None,
    )

    result, result_count, error = agent_web._search_web_reference("resume")

    assert error is None
    assert result_count == 1
    assert result is not None
    assert result.source_kind == "search_snippet"
    assert result.final_url == ""
    assert result.status_code is None


def test_async_search_summary_bounds_query_concurrency(monkeypatch) -> None:
    async def run() -> None:
        release = asyncio.Event()
        concurrency_reached = asyncio.Event()
        active = 0
        maximum_active = 0
        started = 0

        async def fake_search(query: str):
            nonlocal active, maximum_active, started
            active += 1
            started += 1
            maximum_active = max(maximum_active, active)
            if active == 2:
                concurrency_reached.set()
            try:
                await release.wait()
            finally:
                active -= 1
            return (
                [
                    agent_web.WebSearchResult(
                        title=query,
                        url=f"https://example.com/{query}",
                        excerpt="Useful search evidence " * 5,
                    ),
                ],
                None,
            )

        async def fake_fetch(url: str, **_kwargs):
            return agent_web.WebReference(
                title=url,
                excerpt="Fetched reference evidence " * 5,
                final_url=url,
            )

        monkeypatch.setattr(agent_web, "WEB_SEARCH_MAX_CONCURRENCY", 2)
        monkeypatch.setattr(agent_web, "_async_search_web_results", fake_search)
        monkeypatch.setattr(agent_web, "_async_fetch_web_reference", fake_fetch)

        task = asyncio.create_task(
            agent_web._async_search_web_reference_summary(
                ["first", "second", "third"],
            ),
        )
        await asyncio.wait_for(concurrency_reached.wait(), timeout=0.2)

        assert started == 2
        assert maximum_active == 2

        release.set()
        summary = await asyncio.wait_for(task, timeout=0.2)

        assert [result.title for result in summary.results] == [
            "https://example.com/first",
            "https://example.com/second",
            "https://example.com/third",
        ]

    asyncio.run(run())


def test_async_search_summary_bounds_page_fetches_and_preserves_order(
    monkeypatch,
) -> None:
    async def run() -> None:
        release = asyncio.Event()
        concurrency_reached = asyncio.Event()
        active = 0
        maximum_active = 0
        started = 0

        search_results = [
            agent_web.WebSearchResult(
                title=f"result-{index}",
                url=f"https://example.com/{index}",
                excerpt="Useful search evidence " * 5,
            )
            for index in range(4)
        ]

        async def fake_search(_query: str):
            return search_results, None

        async def fake_fetch(url: str, **_kwargs):
            nonlocal active, maximum_active, started
            active += 1
            started += 1
            maximum_active = max(maximum_active, active)
            if active == 2:
                concurrency_reached.set()
            try:
                await release.wait()
            finally:
                active -= 1
            return agent_web.WebReference(
                title=url,
                excerpt="Fetched reference evidence " * 5,
                final_url=url,
            )

        monkeypatch.setattr(agent_web, "WEB_SEARCH_MAX_CONCURRENCY", 2)
        monkeypatch.setattr(agent_web, "_async_search_web_results", fake_search)
        monkeypatch.setattr(agent_web, "_async_fetch_web_reference", fake_fetch)

        task = asyncio.create_task(
            agent_web._async_search_web_reference_summary(["resume"]),
        )
        await asyncio.wait_for(concurrency_reached.wait(), timeout=0.2)

        assert started == 2
        assert maximum_active == 2

        release.set()
        summary = await asyncio.wait_for(task, timeout=0.2)

        assert [result.url for result in summary.results] == [
            f"https://example.com/{index}" for index in range(4)
        ]

    asyncio.run(run())


def test_async_search_summary_uses_one_round_robin_fetch_budget(monkeypatch) -> None:
    async def run() -> None:
        query_results = {
            "first": [
                ("shared", "https://example.com/shared"),
                ("first-2", "https://example.com/first-2"),
                ("first-3", "https://example.com/first-3"),
            ],
            "second": [
                ("shared duplicate", "https://example.com/shared"),
                ("second-2", "https://example.com/second-2"),
                ("second-3", "https://example.com/second-3"),
            ],
            "third": [
                ("third-1", "https://example.com/third-1"),
                ("third-2", "https://example.com/third-2"),
                ("third-3", "https://example.com/third-3"),
            ],
        }
        fetched_urls: list[str] = []

        async def fake_search(query: str):
            return (
                [
                    agent_web.WebSearchResult(
                        title=title,
                        url=url,
                        excerpt="Useful search evidence " * 5,
                    )
                    for title, url in query_results[query]
                ],
                None,
            )

        async def fake_fetch(url: str, **_kwargs):
            fetched_urls.append(url)
            return agent_web.WebReference(
                title=url,
                excerpt="Fetched reference evidence " * 5,
                final_url=url,
            )

        monkeypatch.setattr(agent_web, "_async_search_web_results", fake_search)
        monkeypatch.setattr(agent_web, "_async_fetch_web_reference", fake_fetch)

        summary = await agent_web._async_search_web_reference_summary(
            ["first", "second", "third"],
            max_results=4,
        )

        expected_urls = [
            "https://example.com/shared",
            "https://example.com/third-1",
            "https://example.com/second-2",
            "https://example.com/first-2",
        ]
        assert fetched_urls == expected_urls
        assert [result.url for result in summary.results] == expected_urls

    asyncio.run(run())


def test_async_search_summary_balances_queries_domains_and_source_quality(
    monkeypatch,
) -> None:
    async def run() -> None:
        current_year = datetime.now(UTC).year
        query_results = {
            "role": [
                agent_web.WebSearchResult(
                    title=f"Frontend job roundup {current_year - 2}",
                    url="https://board.example/frontend?utm_source=search",
                    excerpt="Third-party frontend job roundup and role summary. " * 3,
                ),
                agent_web.WebSearchResult(
                    title=f"Acme Frontend Engineer {current_year}",
                    url="https://careers.acme.example/jobs/frontend?team=web",
                    excerpt="Official Acme frontend engineering responsibilities. " * 3,
                ),
            ],
            "skills": [
                agent_web.WebSearchResult(
                    title=f"Beta Frontend Engineer {current_year}",
                    url="https://jobs.beta.example/openings/frontend",
                    excerpt="Official Beta frontend engineering requirements. " * 3,
                ),
                agent_web.WebSearchResult(
                    title="Acme duplicate",
                    url=(
                        "https://careers.acme.example/jobs/frontend"
                        "?utm_medium=email&team=web#apply"
                    ),
                    excerpt="Duplicate official Acme role result. " * 3,
                ),
            ],
            "practice": [
                agent_web.WebSearchResult(
                    title=f"Frontend engineering practices {current_year - 1}",
                    url="https://engineering.example/frontend-guide",
                    excerpt=(
                        "Current frontend engineering practices and expectations. " * 3
                    ),
                ),
            ],
        }

        async def fake_search(query: str):
            return query_results[query], None

        async def fake_fetch(url: str, **_kwargs):
            return agent_web.WebReference(
                title=url,
                excerpt="Fetched role evidence and engineering requirements. " * 4,
                final_url=url,
            )

        monkeypatch.setattr(agent_web, "_async_search_web_results", fake_search)
        monkeypatch.setattr(agent_web, "_async_fetch_web_reference", fake_fetch)

        summary = await agent_web._async_search_web_reference_summary(
            ["role", "skills", "practice"],
            max_results=4,
        )

        assert [result.url for result in summary.results] == [
            "https://jobs.beta.example/openings/frontend",
            "https://careers.acme.example/jobs/frontend?team=web",
            "https://engineering.example/frontend-guide",
            "https://board.example/frontend",
        ]
        assert len({urlparse(result.url).hostname for result in summary.results}) == 4

    asyncio.run(run())


def test_async_search_summary_returns_partial_results_and_cancels_on_timeout(
    monkeypatch,
) -> None:
    async def run() -> None:
        slow_query_started = asyncio.Event()
        slow_query_cancelled = asyncio.Event()
        slow_fetch_cancelled = asyncio.Event()

        async def fake_search(query: str):
            if query == "slow":
                slow_query_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    slow_query_cancelled.set()
                    raise

            return (
                [
                    agent_web.WebSearchResult(
                        title="fast",
                        url="https://example.com/fast",
                        excerpt="Useful search evidence " * 5,
                    ),
                    agent_web.WebSearchResult(
                        title="slow page",
                        url="https://example.com/slow-page",
                        excerpt="short",
                    ),
                ],
                None,
            )

        async def fake_fetch(url: str, **_kwargs):
            if url.endswith("/slow-page"):
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    slow_fetch_cancelled.set()
                    raise

            return agent_web.WebReference(
                title="fast fetched",
                excerpt="Fetched reference evidence " * 5,
                final_url=url,
            )

        monkeypatch.setattr(agent_web, "_async_search_web_results", fake_search)
        monkeypatch.setattr(agent_web, "_async_fetch_web_reference", fake_fetch)

        summary = await asyncio.wait_for(
            agent_web._async_search_web_reference_summary(
                ["fast", "slow"],
                operation_timeout=0.05,
            ),
            timeout=0.2,
        )

        assert slow_query_started.is_set()
        assert slow_query_cancelled.is_set()
        assert slow_fetch_cancelled.is_set()
        assert summary.timed_out is True
        assert summary.partial is True
        assert [result.url for result in summary.results] == [
            "https://example.com/fast",
        ]
        assert summary.error is None

    asyncio.run(run())


def test_async_search_summary_propagates_external_cancellation(monkeypatch) -> None:
    async def run() -> None:
        started = asyncio.Event()
        cancelled = asyncio.Event()

        async def fake_search(_query: str):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        monkeypatch.setattr(agent_web, "_async_search_web_results", fake_search)

        task = asyncio.create_task(
            agent_web._async_search_web_reference_summary(["resume"]),
        )
        await asyncio.wait_for(started.wait(), timeout=0.2)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert cancelled.is_set()

    asyncio.run(run())
