from __future__ import annotations

import asyncio
import re
import socket
from urllib.parse import parse_qs

import httpx
import pytest

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
    AgentToolInvocation,
)
from app.services.agent.adapters.web import WebToolAdapter
from app.services.agent.integrations import web as agent_web
from app.services.agent.integrations.web_network import safe_web_target_addresses
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.llm import LlmToolCall


def _web_tool_call(
    name: str,
    arguments: dict[str, object],
    *,
    call_id: str | None = None,
) -> LlmToolCall:
    return LlmToolCall(
        id=call_id or f"call-{name}",
        name=name,
        arguments=arguments,
        raw_arguments="{}",
    )


def _web_adapter(
    *,
    prompt: str,
    resume: dict[str, object] | None = None,
    hidden_terms: tuple[str, ...] = (),
    messages: list[dict[str, object]] | None = None,
) -> WebToolAdapter:
    request = AgentChatRequest(
        message=AgentConversationItem(
            id=f"turn-agent-web-{prompt}",
            role="user",
            text=prompt,
        ),
        messages=messages or [],
        locale="zh",
        resume=resume or {"basic": {}, "sections": []},
    )
    return WebToolAdapter.open(request, prompt, hidden_terms)


def test_web_search_parses_duckduckgo_results_without_a_search_sdk() -> None:
    html = b"""
        <div class="result results_links web-result">
          <h2 class="result__title">
            <a class="result__a"
               href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fcareers.example%2Fjobs%2F7%3Futm_source%3Dddg">
              Frontend Intern
            </a>
          </h2>
          <span>2026-08-01T08:00:00.0000000</span>
          <a class="result__snippet">React and TypeScript responsibilities.</a>
        </div>
        <div class="result results_links web-result">
          <h2 class="result__title">
            <a class="result__a" href="https://careers.example/jobs/7">
              Duplicate
            </a>
          </h2>
          <a class="result__snippet">Duplicate result.</a>
        </div>
    """

    results = agent_web._parse_duckduckgo_results(html, "utf-8")

    assert results == [
        agent_web.WebSearchResult(
            url="https://careers.example/jobs/7",
            title="Frontend Intern",
            excerpt="React and TypeScript responsibilities.",
            published_date="2026-08-01T08:00:00.0000000",
        ),
    ]


def test_web_search_diversifies_a_larger_discovery_pool() -> None:
    urls = [
        *(f"https://directory.example/jobs/{index}" for index in range(4)),
        "https://careers.example/jobs/frontend",
        "https://jobs.example.org/roles/frontend",
        "https://ats.example.net/openings/frontend",
    ]
    html = "".join(
        f"""
        <div class="result results_links web-result">
          <h2><a class="result__a" href="{url}">Result {index}</a></h2>
          <a class="result__snippet">Frontend internship result {index}.</a>
        </div>
        """
        for index, url in enumerate(urls)
    ).encode()

    discovered = agent_web._parse_duckduckgo_results(html, "utf-8")
    selected = agent_web._select_search_results(discovered)

    assert [result.url for result in discovered] == urls
    assert [result.url for result in selected] == [
        urls[0],
        urls[1],
        urls[4],
        urls[5],
        urls[6],
    ]

    browser_candidates = agent_web._select_search_results(
        discovered,
        limit=2,
        per_source=1,
    )
    assert [result.url for result in browser_candidates] == [urls[0], urls[4]]


def test_web_search_keeps_distinct_tenants_on_a_shared_ats() -> None:
    results = [
        agent_web.WebSearchResult(
            url="https://jobs.lever.co/acme/frontend-intern",
            title="Acme Frontend Intern",
            excerpt="Build Acme frontend products.",
        ),
        agent_web.WebSearchResult(
            url="https://jobs.lever.co/example/frontend-intern",
            title="Example Frontend Intern",
            excerpt="Build Example frontend products.",
        ),
        agent_web.WebSearchResult(
            url="https://directory.example/jobs/frontend",
            title="Frontend internship directory",
            excerpt="A third-party internship directory.",
        ),
    ]

    selected = agent_web._select_search_results(
        results,
        limit=2,
        per_source=1,
    )

    assert selected == results[:2]


def test_web_fetch_extracts_the_query_relevant_page_passage_locally() -> None:
    html = b"""
        <html>
          <head><title>Frontend Intern</title></head>
          <body>
            <nav>Home Products About News Careers Contact</nav>
            <main>
              <h1>Frontend Intern</h1>
              <p>Join our product engineering team in Shanghai.</p>
              <h2>Responsibilities</h2>
              <p>Build accessible web interfaces with React and TypeScript.</p>
              <h2>Requirements</h2>
              <p>Understand browser performance, HTML, CSS, and testing.</p>
            </main>
          </body>
        </html>
    """

    reference = agent_web._web_reference_from_response(
        "https://careers.example/jobs/7",
        html,
        "text/html; charset=utf-8",
        "utf-8",
        relevance_query="React TypeScript frontend intern requirements",
        reference_title="Frontend Intern",
    )

    assert reference is not None
    assert reference.title == "Frontend Intern"
    assert "Build accessible web interfaces with React and TypeScript" in (
        reference.excerpt
    )
    assert "Home Products About" not in reference.excerpt


def test_web_fetch_keeps_relevant_passages_from_multiple_job_sections() -> None:
    responsibilities = " ".join(
        [
            "Build React and TypeScript interfaces with product and design partners."
            for _ in range(14)
        ],
    )
    requirements = " ".join(
        [
            "Understand accessibility, automated testing, and browser performance."
            for _ in range(14)
        ],
    )
    html = f"""
        <html>
          <head><title>Frontend Intern</title></head>
          <body><main>
            <h1>Frontend Intern</h1>
            <h2>Responsibilities</h2>
            <p>{responsibilities}</p>
            <h2>Requirements</h2>
            <p>{requirements}</p>
          </main></body>
        </html>
    """.encode()

    reference = agent_web._web_reference_from_response(
        "https://careers.example/jobs/7",
        html,
        "text/html; charset=utf-8",
        "utf-8",
        relevance_query=(
            "React TypeScript frontend intern accessibility testing performance"
        ),
        reference_title="Frontend Intern",
    )

    assert reference is not None
    assert {passage.section for passage in reference.passages} >= {
        "Responsibilities",
        "Requirements",
    }
    assert any(
        "Build React and TypeScript" in passage.text for passage in reference.passages
    )
    assert any("automated testing" in passage.text for passage in reference.passages)


def test_web_fetch_drops_leading_job_board_chrome_from_the_excerpt() -> None:
    html = b"""
        <html>
          <head><title>Frontend Intern</title></head>
          <body>
            <div>Campus Jobs</div>
            <div>Intern TV</div>
            <div>Career Wiki</div>
            <div>Employer Portal</div>
            <div>Sign in or register</div>
            <div>Frontend Intern</div>
            <div>12:26:09 refreshed, 200-300 per day, Shanghai</div>
            <div>Job description</div>
            <div>Responsibilities</div>
            <p>Build and maintain React interfaces for the core frontend system.</p>
            <p>Develop reusable React components and TypeScript modules.</p>
            <div>Requirements</div>
            <p>Understand JavaScript, browser APIs, testing, and web performance.</p>
          </body>
        </html>
    """

    reference = agent_web._web_reference_from_response(
        "https://jobs.example/positions/7",
        html,
        "text/html; charset=utf-8",
        "utf-8",
        relevance_query="React TypeScript frontend intern",
        reference_title="Frontend Intern",
    )

    assert reference is not None
    assert reference.excerpt.startswith("Build and maintain React interfaces")
    assert "Sign in or register" not in reference.excerpt
    assert "12:26:09 refreshed" not in reference.excerpt
    assert "Understand JavaScript" in reference.excerpt


def test_web_fetch_focuses_a_relevant_passage_inside_one_large_listing_block() -> None:
    unrelated_before = " ".join(
        f"岗位 {index} Java 后端开发，负责微服务和数据库。" for index in range(120)
    )
    target = (
        "前端开发实习生，使用 React 和 TypeScript 开发无障碍 Web 界面，"
        "与产品和设计协作，并编写自动化测试。"
    )
    unrelated_after = " ".join(
        f"岗位 {index} 财务分析，负责报表和预算。" for index in range(120)
    )
    html = (
        "<html><head><title>校园招聘职位列表</title></head><body><main><p>"
        f"{unrelated_before} {target} {unrelated_after}"
        "</p></main></body></html>"
    ).encode()

    reference = agent_web._web_reference_from_response(
        "https://jobs.example/search",
        html,
        "text/html; charset=utf-8",
        "utf-8",
        relevance_query="React TypeScript 前端开发实习生",
        reference_title="校园招聘职位列表",
    )

    assert reference is not None
    assert target in reference.excerpt
    assert "岗位 0 Java 后端开发" not in reference.excerpt
    assert "岗位 119 财务分析" not in reference.excerpt


def test_web_fetch_reads_job_posting_dates_and_rejects_expired_roles() -> None:
    current_html = b"""
        <html>
          <head>
            <title>Frontend Intern</title>
            <script type="application/ld+json">
              {
                "@context": "https://schema.org",
                "@type": "JobPosting",
                "title": "Frontend Intern",
                "datePosted": "2026-08-20",
                "validThrough": "2099-09-30T23:59:59+08:00"
              }
            </script>
          </head>
          <body><main>
            <p>Build accessible React and TypeScript interfaces.</p>
            <p>Work with product engineers on browser performance.</p>
          </main></body>
        </html>
    """
    expired_html = current_html.replace(
        b"2099-09-30T23:59:59+08:00",
        b"2000-08-01T23:59:59+08:00",
    )

    reference = agent_web._web_reference_from_response(
        "https://careers.example/jobs/7",
        current_html,
        "text/html; charset=utf-8",
        "utf-8",
        relevance_query="React TypeScript frontend intern",
    )
    expired = agent_web._web_reference_from_response(
        "https://careers.example/jobs/7",
        expired_html,
        "text/html; charset=utf-8",
        "utf-8",
        relevance_query="React TypeScript frontend intern",
    )

    assert reference is not None
    assert reference.published_date == "2026-08-20"
    assert reference.valid_through == "2099-09-30T23:59:59+08:00"
    assert expired is None


def test_web_fetch_downloads_and_extracts_a_public_page_without_an_sdk(
    monkeypatch,
) -> None:
    real_client = httpx.AsyncClient
    page = b"""
        <html><head><title>Frontend Intern</title></head><body><main>
        <p>Build React and TypeScript interfaces for the recruiting product.</p>
        <p>Write accessible, tested, and maintainable frontend code.</p>
        </main></body></html>
    """

    class PublicPeer:
        def get_extra_info(self, name: str):
            return ("93.184.216.34", 443) if name == "server_addr" else None

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=page,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions={"network_stream": PublicPeer()},
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
            "https://careers.example/jobs/7",
            "React TypeScript frontend",
            "Frontend Intern",
        ),
    )

    assert reference is not None
    assert reference.final_url == "https://careers.example/jobs/7"
    assert "Build React and TypeScript interfaces" in reference.excerpt


def test_web_search_reads_top_result_pages_before_returning_to_the_model(
    monkeypatch,
) -> None:
    real_client = httpx.AsyncClient
    search_html = b"""
        <div class="result results_links web-result">
          <h2><a class="result__a" href="https://careers.example/jobs/7">
            Frontend Intern
          </a></h2>
          <a class="result__snippet">Short discovery snippet.</a>
        </div>
    """
    job_html = b"""
        <html><head><title>Frontend Intern</title></head><body><main>
          <h1>Frontend Intern</h1>
          <p>Build React and TypeScript interfaces for the recruiting product.</p>
          <p>Understand accessibility, testing, and browser performance.</p>
        </main></body></html>
    """

    class PublicPeer:
        def get_extra_info(self, name: str):
            return ("93.184.216.34", 443) if name == "server_addr" else None

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "html.duckduckgo.com":
            form = parse_qs(request.content.decode())
            assert request.method == "POST"
            assert "site:careers.example" in form["q"][0]
            assert form["df"] == ["y"]
            assert form["kl"] == ["cn-zh"]
            body = search_html
        else:
            assert str(request.url) == "https://careers.example/jobs/7"
            body = job_html
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions={"network_stream": PublicPeer()},
        )

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )

    response = asyncio.run(
        agent_web._async_search_web(
            "上海 React TypeScript 前端实习",
            "year",
            ("careers.example",),
        ),
    )

    assert response.error_reason == ""
    assert response.results == (
        agent_web.WebSearchResult(
            url="https://careers.example/jobs/7",
            title="Frontend Intern",
            excerpt=(
                "Build React and TypeScript interfaces for the recruiting "
                "product. Understand accessibility, testing, and browser "
                "performance."
            ),
            source_kind="fetched_page",
            passages=(
                agent_web.WebPassage(
                    section="Frontend Intern",
                    text=(
                        "Build React and TypeScript interfaces for the recruiting "
                        "product."
                    ),
                ),
                agent_web.WebPassage(
                    section="Frontend Intern",
                    text=(
                        "Understand accessibility, testing, and browser performance."
                    ),
                ),
            ),
        ),
    )
    assert [passage.text for passage in response.results[0].passages] == [
        "Build React and TypeScript interfaces for the recruiting product.",
        "Understand accessibility, testing, and browser performance.",
    ]


def test_web_search_reads_at_most_five_candidates_concurrently(
    monkeypatch,
) -> None:
    real_client = httpx.AsyncClient
    urls = [f"https://careers.example/jobs/{index}" for index in range(6)]
    search_html = "".join(
        f"""
        <div class="result results_links web-result">
          <h2><a class="result__a" href="{url}">
            React Frontend Role {index}
          </a></h2>
          <a class="result__snippet">
            React TypeScript frontend responsibilities for role {index}.
          </a>
        </div>
        """
        for index, url in enumerate(urls)
    ).encode()
    started_urls: list[str] = []
    all_five_started = asyncio.Event()

    class PublicPeer:
        def get_extra_info(self, name: str):
            return ("93.184.216.34", 443) if name == "server_addr" else None

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "html.duckduckgo.com":
            body = search_html
        else:
            requested_url = str(request.url)
            started_urls.append(requested_url)
            if len(started_urls) == 5:
                all_five_started.set()
            try:
                await asyncio.wait_for(all_five_started.wait(), timeout=0.25)
            except TimeoutError:
                pass
            index = int(request.url.path.rsplit("/", 1)[-1])
            body = (
                f"""
                    <html><head><title>React Frontend Role {index}</title></head>
                    <body><main>
                      <p>
                        Build React and TypeScript frontend interfaces for role {index}.
                      </p>
                      <p>Improve accessibility, testing, and browser performance.</p>
                    </main></body></html>
                """.encode()
                if index >= 3
                else b"<html><body><nav>Home Sign in Contact</nav></body></html>"
            )
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions={"network_stream": PublicPeer()},
        )

    async def no_browser_results(
        _requests: list[tuple[str, str, str]],
        _browser: agent_web.WebBrowser | None,
    ) -> dict[str, agent_web.WebReference]:
        raise AssertionError("two static references must stop browser fallback")

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )
    monkeypatch.setattr(
        agent_web,
        "_async_render_web_references",
        no_browser_results,
    )

    response = asyncio.run(
        agent_web._async_search_web("React TypeScript frontend roles"),
    )

    assert set(started_urls) == set(urls[:5])
    assert len(response.results) == 5
    assert [result.url for result in response.results] == urls[:5]
    assert [result.source_kind for result in response.results] == [
        "search_snippet",
        "search_snippet",
        "search_snippet",
        "fetched_page",
        "fetched_page",
    ]


def test_web_search_renders_a_result_when_static_html_is_only_site_chrome(
    monkeypatch,
) -> None:
    real_client = httpx.AsyncClient
    url = "https://jobs.example/positions/7"
    search_html = f"""
        <div class="result results_links web-result">
          <h2><a class="result__a" href="{url}">
            Frontend Intern in Shanghai
          </a></h2>
          <a class="result__snippet">React internship responsibilities.</a>
        </div>
    """.encode()
    shell_html = b"""
        <html><head><title>Join us</title></head><body><nav>
          Home Campus Programs Teams Benefits News Sign in Contact us
        </nav></body></html>
    """

    class PublicPeer:
        def get_extra_info(self, name: str):
            return ("93.184.216.34", 443) if name == "server_addr" else None

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def respond(request: httpx.Request) -> httpx.Response:
        body = search_html if request.url.host == "html.duckduckgo.com" else shell_html
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions={"network_stream": PublicPeer()},
        )

    async def render(
        requests: list[tuple[str, str, str]],
        _browser: agent_web.WebBrowser | None,
    ):
        assert requests == [
            (
                url,
                "Shanghai React frontend intern",
                "Frontend Intern in Shanghai",
            ),
        ]
        return {
            url: agent_web.WebReference(
                title="Frontend Intern in Shanghai",
                excerpt=(
                    "Build React and TypeScript interfaces in Shanghai. "
                    "Improve accessibility and browser performance."
                ),
                final_url=url,
            ),
        }

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )
    monkeypatch.setattr(agent_web, "_async_render_web_references", render)

    response = asyncio.run(
        agent_web._async_search_web("Shanghai React frontend intern"),
    )

    assert response.results[0].source_kind == "fetched_page"
    assert "Build React and TypeScript interfaces" in response.results[0].excerpt


def test_dynamic_renderer_uses_playwright_managed_chromium(monkeypatch) -> None:
    launch_options: dict[str, object] = {}
    cleanup = []

    class Proxy:
        async def start(self) -> str:
            return "socks5://127.0.0.1:1080"

        async def close(self) -> None:
            cleanup.append("proxy")

    class Chromium:
        async def launch(self, **options: object):
            launch_options.update(options)
            raise agent_web.PlaywrightError("stop after launch")

    class Playwright:
        chromium = Chromium()

        async def stop(self) -> None:
            cleanup.append("playwright")

    class PlaywrightContext:
        async def start(self):
            return Playwright()

    monkeypatch.setattr(
        agent_web,
        "async_playwright",
        lambda: PlaywrightContext(),
    )

    monkeypatch.setattr(agent_web, "PublicWebProxy", Proxy)

    rendered = asyncio.run(
        agent_web._async_render_web_references(
            [("https://jobs.example/positions/7", "frontend", "Frontend")],
        ),
    )

    assert rendered == {}
    assert launch_options == {
        "headless": True,
        "proxy": {"server": "socks5://127.0.0.1:1080", "bypass": "<-loopback>"},
        "args": [
            "--disable-quic",
            "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
        ],
    }
    assert cleanup == ["playwright", "proxy"]


def test_dynamic_renderer_handles_unavailable_proxy(monkeypatch) -> None:
    class Proxy:
        async def start(self) -> str:
            raise OSError("Loopback unavailable")

    monkeypatch.setattr(agent_web, "PublicWebProxy", Proxy)
    rendered = asyncio.run(
        agent_web._async_render_web_references(
            [("https://jobs.example/positions/7", "frontend", "Frontend")],
        ),
    )
    assert rendered == {}


def test_dynamic_renderer_waits_for_relevant_job_content() -> None:
    url = "https://jobs.example/positions/7"
    body = "Home Jobs Sign in recruiting assistant"

    class Locator:
        async def inner_text(self, *, timeout: int) -> str:
            assert timeout == 1_000
            return body

        async def all_text_contents(self) -> list[str]:
            return []

    class Response:
        status = 200

    class Page:
        url = "https://jobs.example/positions/7"

        async def route(self, _pattern: str, _handler: object) -> None:
            return None

        async def goto(
            self,
            requested_url: str,
            *,
            wait_until: str,
            timeout: int,
        ) -> Response:
            assert requested_url == url
            assert wait_until == "domcontentloaded"
            assert timeout == 6_000
            return Response()

        async def wait_for_function(self, _expression: str, *, timeout: int) -> None:
            nonlocal body
            if timeout < 3_000:
                raise agent_web.PlaywrightTimeoutError("job content is not ready")
            body = (
                "Frontend Intern\nResponsibilities\n"
                "Build React and TypeScript interfaces for the recruiting product.\n"
                "Improve accessibility and browser performance."
            )

        async def title(self) -> str:
            return "Frontend Intern"

        def locator(self, _selector: str) -> Locator:
            return Locator()

        async def close(self) -> None:
            return None

    class Context:
        async def new_page(self) -> Page:
            return Page()

    class Browser:
        async def context(self) -> Context:
            return Context()

    rendered = asyncio.run(
        agent_web._async_render_web_references(
            [(url, "React TypeScript frontend", "Frontend Intern")],
            Browser(),  # type: ignore[arg-type]
        ),
    )

    assert rendered[url].excerpt.startswith("Build React and TypeScript")


def test_web_browser_reuses_one_lazy_context_for_the_turn(monkeypatch) -> None:
    calls = {
        "start": 0,
        "launch": 0,
        "new_context": 0,
        "close": 0,
        "stop": 0,
        "proxy_start": 0,
        "proxy_close": 0,
    }

    class Proxy:
        async def start(self) -> str:
            calls["proxy_start"] += 1
            return "socks5://127.0.0.1:1080"

        async def close(self) -> None:
            calls["proxy_close"] += 1

    class Context:
        async def close(self) -> None:
            calls["close"] += 1

    context = Context()

    class Browser:
        async def new_context(self, **_options: object) -> Context:
            calls["new_context"] += 1
            return context

        async def close(self) -> None:
            return None

    class Chromium:
        async def launch(self, **_options: object) -> Browser:
            assert _options["proxy"] == {
                "server": "socks5://127.0.0.1:1080",
                "bypass": "<-loopback>",
            }
            calls["launch"] += 1
            return Browser()

    class Playwright:
        chromium = Chromium()

        async def stop(self) -> None:
            calls["stop"] += 1

    class PlaywrightContext:
        async def start(self) -> Playwright:
            calls["start"] += 1
            return Playwright()

    monkeypatch.setattr(agent_web, "async_playwright", lambda: PlaywrightContext())
    monkeypatch.setattr(agent_web, "PublicWebProxy", Proxy)

    async def scenario() -> None:
        browser = agent_web.WebBrowser()
        assert await browser.context() is context
        assert await browser.context() is context
        await browser.close()

    asyncio.run(scenario())

    assert calls == {
        "start": 1,
        "launch": 1,
        "new_context": 1,
        "close": 1,
        "stop": 1,
        "proxy_start": 1,
        "proxy_close": 1,
    }


def test_web_fetch_rejects_login_and_closed_position_pages() -> None:
    for body in (
        (
            "找工作 在线职位及时沟通 APP扫码登录 验证码登录/注册 "
            "首次验证通过即注册账号 我要找工作 我要招聘 用户协议 隐私政策"
        ),
        (
            "首页 职位 校招答疑 登录 该职位已下线 查看工作机会 "
            "公司介绍 联系我们 隐私政策 用户协议"
        ),
    ):
        reference = agent_web._web_reference_from_response(
            "https://jobs.example/positions/7",
            f"<html><body><main><p>{body}</p></main></body></html>".encode(),
            "text/html; charset=utf-8",
            "utf-8",
            relevance_query="React frontend intern",
            reference_title="Frontend Intern",
        )

        assert reference is None


def test_search_does_not_promote_an_unrelated_landing_page() -> None:
    discovered = agent_web.WebSearchResult(
        url="https://jobs.example/positions/7",
        title="Frontend Intern - Product Engineering",
        excerpt=(
            "Build React and TypeScript interfaces, improve accessibility, "
            "and collaborate with product engineers in Shanghai."
        ),
    )
    login_page = agent_web.WebReference(
        title="Sign in",
        excerpt=(
            "Find jobs, talk to recruiters, scan the app code, read the user "
            "agreement and privacy policy, then sign in or register."
        ),
        final_url="https://jobs.example/sign-in",
    )

    assert not agent_web._reference_matches_result(discovered, login_page)


def test_search_does_not_promote_a_matching_title_with_footer_only_text() -> None:
    discovered = agent_web.WebSearchResult(
        url="https://jobs.example/positions/7",
        title="Frontend Intern",
        excerpt="Build React and TypeScript interfaces for a recruiting product.",
    )
    footer_only = agent_web.WebReference(
        title="Frontend Intern",
        excerpt="Copyright 2015-2026 Example Intern. Contact us and legal notice.",
        final_url="https://jobs.example/positions/7",
    )

    assert not agent_web._reference_matches_result(discovered, footer_only)


def test_search_does_not_promote_a_job_redirected_to_the_site_homepage() -> None:
    discovered = agent_web.WebSearchResult(
        url="https://jobs.example/positions/react-frontend-7",
        title="React Frontend Engineer",
        excerpt="Build React and TypeScript interfaces for a recruiting product.",
    )
    keyword_rich_homepage = agent_web.WebReference(
        title="Example Jobs",
        excerpt=(
            "Find React frontend engineer jobs, TypeScript roles, and other "
            "current recruiting opportunities."
        ),
        final_url="https://jobs.example/",
    )

    assert not agent_web._reference_matches_result(
        discovered,
        keyword_rich_homepage,
    )


def test_web_search_reports_duckduckgo_challenge_as_rate_limited(
    monkeypatch,
) -> None:
    real_client = httpx.AsyncClient

    class PublicPeer:
        def get_extra_info(self, name: str):
            return ("93.184.216.34", 443) if name == "server_addr" else None

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            202,
            content=b'<form id="challenge-form">CAPTCHA</form>',
            headers={"content-type": "text/html; charset=utf-8"},
            extensions={"network_stream": PublicPeer()},
        ),
    )
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )

    response = asyncio.run(agent_web._async_search_web("frontend intern"))

    assert response == agent_web.WebSearchResponse(error_reason="rate_limited")


def test_web_search_promotes_only_the_target_number_of_read_references(
    monkeypatch,
) -> None:
    real_client = httpx.AsyncClient
    search_html = b"""
        <a class="result__a" href="https://one.example/jobs/1">Role one</a>
        <a class="result__snippet">Discovery snippet one.</a>
        <a class="result__a" href="https://two.example/jobs/2">Role two</a>
        <a class="result__snippet">Discovery snippet two.</a>
        <a class="result__a" href="https://three.example/jobs/3">Role three</a>
        <a class="result__snippet">Discovery snippet three.</a>
    """

    class PublicPeer:
        def get_extra_info(self, name: str):
            return ("93.184.216.34", 443) if name == "server_addr" else None

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=search_html,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions={"network_stream": PublicPeer()},
        ),
    )

    async def read_static(
        _client: httpx.AsyncClient,
        url: str,
        _query: str,
        title: str,
    ) -> agent_web.WebReference:
        return agent_web.WebReference(
            title=title,
            excerpt=(
                f"{title}. Discovery snippet for a frontend intern role with "
                "responsibilities and requirements."
            ),
            final_url=url,
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )
    monkeypatch.setattr(agent_web, "_async_fetch_with_client", read_static)

    response = asyncio.run(agent_web._async_search_web("frontend intern"))

    assert [result.source_kind for result in response.results[:3]] == [
        "fetched_page",
        "fetched_page",
        "search_snippet",
    ]
    assert response.results[2].excerpt == "Discovery snippet three."


def test_web_search_keeps_discovery_results_when_one_page_read_fails(
    monkeypatch,
) -> None:
    real_client = httpx.AsyncClient
    search_html = b"""
        <a class="result__a" href="https://slow.example/jobs/7">Slow role</a>
        <a class="result__snippet">Frontend internship discovery text.</a>
        <a class="result__a" href="https://careers.example/jobs/8">React role</a>
        <a class="result__snippet">React TypeScript frontend internship.</a>
    """
    job_html = b"""
        <html><head><title>React role</title></head><body><main>
          <p>Build React and TypeScript frontend interfaces for job seekers.</p>
          <p>Improve accessibility, tests, and browser performance.</p>
        </main></body></html>
    """

    class PublicPeer:
        def get_extra_info(self, name: str):
            return ("93.184.216.34", 443) if name == "server_addr" else None

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.host == "html.duckduckgo.com":
            body = search_html
        elif request.url.host == "slow.example":
            raise httpx.ReadTimeout("page timed out", request=request)
        else:
            body = job_html
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions={"network_stream": PublicPeer()},
        )

    async def no_browser_results(
        _requests: list[tuple[str, str, str]],
        _browser: agent_web.WebBrowser | None,
    ):
        return {}

    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )
    monkeypatch.setattr(
        agent_web,
        "_async_render_web_references",
        no_browser_results,
    )

    response = asyncio.run(agent_web._async_search_web("React frontend intern"))

    assert response.error_reason == ""
    assert [result.source_kind for result in response.results] == [
        "search_snippet",
        "fetched_page",
    ]


def test_web_search_keeps_static_references_when_browser_fallback_times_out(
    monkeypatch,
) -> None:
    real_client = httpx.AsyncClient
    first_url = "https://careers.example/jobs/7"
    second_url = "https://careers.example/jobs/8"
    search_html = f"""
        <a class="result__a" href="{first_url}">React Frontend Role</a>
        <a class="result__snippet">React TypeScript frontend responsibilities.</a>
        <a class="result__a" href="{second_url}">Frontend Internship</a>
        <a class="result__snippet">Frontend internship requirements.</a>
    """.encode()

    class PublicPeer:
        def get_extra_info(self, name: str):
            return ("93.184.216.34", 443) if name == "server_addr" else None

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=search_html,
            headers={"content-type": "text/html; charset=utf-8"},
            extensions={"network_stream": PublicPeer()},
        ),
    )

    async def read_static(
        _client: httpx.AsyncClient,
        url: str,
        _query: str,
        _title: str,
    ) -> agent_web.WebReference | None:
        if url != first_url:
            return None
        return agent_web.WebReference(
            title="React Frontend Role",
            excerpt="Build React and TypeScript frontend interfaces.",
            final_url=url,
            passages=(
                agent_web.WebPassage(
                    section="Responsibilities",
                    text="Build React and TypeScript frontend interfaces.",
                ),
            ),
        )

    async def slow_browser(
        _requests: list[tuple[str, str, str]],
        _browser: agent_web.WebBrowser | None,
    ) -> dict[str, agent_web.WebReference]:
        await asyncio.sleep(1)
        return {}

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )
    monkeypatch.setattr(agent_web, "_async_fetch_with_client", read_static)
    monkeypatch.setattr(agent_web, "_async_render_web_references", slow_browser)
    monkeypatch.setattr(agent_web, "SEARCH_TIMEOUT_SECONDS", 0.1)

    response = asyncio.run(agent_web._async_search_web("React frontend role"))

    assert response.error_reason == ""
    assert [result.source_kind for result in response.results] == [
        "fetched_page",
        "search_snippet",
    ]


def test_web_fetch_revalidates_redirect_before_following_it(monkeypatch) -> None:
    real_client = httpx.AsyncClient
    requested_urls: list[str] = []

    class PublicPeer:
        def get_extra_info(self, name: str):
            return ("93.184.216.34", 443) if name == "server_addr" else None

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    def redirect(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "http://127.0.0.1/private"},
            extensions={"network_stream": PublicPeer()},
        )

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    transport = httpx.MockTransport(redirect)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )

    reference = asyncio.run(
        agent_web._async_fetch_web_reference("https://careers.example/start"),
    )

    assert reference is None
    assert requested_urls == ["https://careers.example/start"]


def test_web_network_allows_tun_fake_ip_only_after_public_hostname_resolution(
    monkeypatch,
) -> None:
    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.157", port)),
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    assert safe_web_target_addresses(
        "https://html.duckduckgo.com/html/",
    ) == ("198.18.0.157",)
    assert (
        safe_web_target_addresses(
            "https://198.18.0.157/private",
        )
        is None
    )


def test_web_fetch_renders_a_dynamic_page_when_static_html_has_no_passage(
    monkeypatch,
) -> None:
    real_client = httpx.AsyncClient
    url = "https://jobs.example/positions/7"

    class PublicPeer:
        def get_extra_info(self, name: str):
            return ("93.184.216.34", 443) if name == "server_addr" else None

    def fake_getaddrinfo(
        _host: str,
        port: int,
        *_args: object,
        **_kwargs: object,
    ) -> list[tuple[int, int, int, str, tuple[str, int]]]:
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
        ]

    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            content=b"<html><body><div id='app'></div></body></html>",
            headers={"content-type": "text/html; charset=utf-8"},
            extensions={"network_stream": PublicPeer()},
        ),
    )

    async def render(
        requests: list[tuple[str, str, str]],
        _browser: agent_web.WebBrowser | None,
    ):
        assert requests == [(url, "React frontend requirements", "Frontend Intern")]
        return {
            url: agent_web.WebReference(
                title="Frontend Intern",
                excerpt=(
                    "Build React interfaces and improve browser performance. "
                    "Write tested and accessible TypeScript code."
                ),
                final_url=url,
            ),
        }

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(
        agent_web.httpx,
        "AsyncClient",
        lambda **_kwargs: real_client(transport=transport),
    )
    monkeypatch.setattr(agent_web, "_async_render_web_references", render)

    reference = asyncio.run(
        agent_web._async_fetch_web_reference(
            url,
            "React frontend requirements",
            "Frontend Intern",
        ),
    )

    assert reference is not None
    assert "accessible TypeScript code" in reference.excerpt


def test_rendered_visible_text_is_reduced_to_a_relevant_passage() -> None:
    reference = agent_web._web_reference_from_visible_text(
        "https://jobs.example/positions/7",
        "Frontend Intern",
        """
        Home
        Products
        About us
        Frontend Intern
        Responsibilities
        Build React interfaces for the recruiting product.
        Improve accessibility and browser performance.
        Requirements
        Write tested and maintainable TypeScript code.
        Privacy
        Terms
        """,
        relevance_query="React TypeScript frontend requirements",
        reference_title="Frontend Intern",
    )

    assert reference is not None
    assert "Build React interfaces" in reference.excerpt
    assert "maintainable TypeScript code" in reference.excerpt
    assert "Home Products About us" not in reference.excerpt
    passage_text = " ".join(passage.text for passage in reference.passages)
    assert "Build React interfaces" in passage_text
    assert "maintainable TypeScript code" in passage_text


def test_rendered_job_page_excerpt_starts_with_job_content_not_site_chrome() -> None:
    reference = agent_web._web_reference_from_visible_text(
        "https://jobs.example/positions/7",
        "Frontend Intern",
        """
        Campus Jobs Intern TV Career Wiki Employer Portal
        Sign in or register
        Frontend Intern
        12:26:09 refreshed, 200-300 per day, Shanghai
        Job description
        Responsibilities
        Build and maintain React interfaces for the core frontend system.
        Develop reusable React components and TypeScript modules.
        Requirements
        Understand JavaScript, browser APIs, testing, and web performance.
        """,
        relevance_query="React TypeScript frontend intern",
        reference_title="Frontend Intern",
    )

    assert reference is not None
    assert reference.excerpt.startswith("Build and maintain React interfaces")
    assert "Sign in or register" not in reference.excerpt
    assert "12:26:09 refreshed" not in reference.excerpt
    assert "Understand JavaScript" in reference.excerpt


def test_rendered_search_result_rejects_footer_only_text() -> None:
    reference = agent_web._web_reference_from_visible_text(
        "https://jobs.example/positions/7",
        "Frontend Intern - Example Intern",
        "Copyright 2015-2026 Example Intern. Contact us and legal notice.",
        relevance_query="React TypeScript frontend intern 2026",
        reference_title="Frontend Intern",
    )

    assert reference is None


async def _invoke(
    adapter: WebToolAdapter,
    tool_call: LlmToolCall,
) -> AgentToolInvocation:
    return await adapter.invoke(tool_call, AgentRuntimeContext())


@pytest.mark.parametrize(
    "url",
    (
        "http://localhost/private",
        "http://127.0.0.1/private",
        "http://10.0.0.1/private",
        "http://169.254.169.254/latest/meta-data",
        "http://100.100.100.200/latest/meta-data",
        "http://198.18.0.157/fake-ip",
        "http://224.0.0.1/multicast",
        "http://0.0.0.0/unspecified",
        "http://240.0.0.1/reserved",
        "http://[::1]/private",
        "http://metadata.google.internal/computeMetadata/v1",
        "file:///etc/passwd",
        "https://user:password@example.com/private",
    ),
)
def test_fetch_rejects_non_public_urls_before_network(url: str) -> None:
    reference = asyncio.run(agent_web._async_fetch_web_reference(url))

    assert reference is None


def test_web_fetch_allows_any_public_url_selected_by_the_model(monkeypatch) -> None:
    adapter = _web_adapter(prompt="请优化目标岗位简历")
    url = "https://careers.example/jobs/123"

    async def fake_fetch(
        requested_url: str,
        relevance_query: str,
        reference_title: str,
        _browser: agent_web.WebBrowser,
    ) -> agent_web.WebReference:
        assert requested_url == url
        assert relevance_query == "请优化目标岗位简历"
        assert reference_title == ""
        return agent_web.WebReference(
            title="Official careers page",
            excerpt="Current public role information.",
            final_url=requested_url,
        )

    monkeypatch.setattr(
        agent_web,
        "_async_fetch_web_reference",
        fake_fetch,
    )

    tool = asyncio.run(
        _invoke(
            adapter,
            _web_tool_call(
                "web_fetch",
                {"url": url},
            ),
        ),
    )

    assert tool.state == "output-available"


def test_web_fetch_reuses_a_verified_source_from_conversation_history(
    monkeypatch,
) -> None:
    source_url = "https://careers.example/jobs/frontend-intern"
    adapter = _web_adapter(
        prompt="继续按刚才找到的岗位修改。",
        messages=[
            {
                "id": "assistant-with-source",
                "role": "assistant",
                "text": "已找到岗位页面。",
                "response": {
                    "sources": [
                        {
                            "id": "source-job",
                            "title": "Frontend Intern",
                            "sourceType": "web",
                            "url": source_url,
                        },
                    ],
                },
            },
        ],
    )

    async def fake_fetch(
        requested_url: str,
        relevance_query: str,
        reference_title: str,
        _browser: agent_web.WebBrowser,
    ) -> agent_web.WebReference:
        assert requested_url == source_url
        assert "刚才找到的岗位" in relevance_query
        assert reference_title == "Frontend Intern"
        return agent_web.WebReference(
            title=reference_title,
            excerpt="Build React interfaces with TypeScript.",
            final_url=requested_url,
        )

    monkeypatch.setattr(agent_web, "_async_fetch_web_reference", fake_fetch)

    tool = asyncio.run(
        _invoke(
            adapter,
            _web_tool_call("web_fetch", {"url": source_url}),
        ),
    )

    assert tool.state == "output-available"


def test_web_search_sanitizes_query_and_reuses_result_context_for_fetch(
    monkeypatch,
) -> None:
    adapter = _web_adapter(
        prompt="请搜索前端实习岗位，邮箱 xiaoming@example.com",
        resume={"basic": {"name": "王小明"}, "sections": []},
        hidden_terms=("王小明",),
    )
    result_url = "https://careers.example/jobs/frontend-intern"
    safe_query = "[redacted_identity_0] [redacted_email] 前端实习 JD"
    seen_queries: list[tuple[str, str | None, tuple[str, ...]]] = []

    async def fake_search(
        query: str,
        time_range: str | None,
        include_domains: tuple[str, ...],
        _browser: agent_web.WebBrowser,
    ) -> agent_web.WebSearchResponse:
        seen_queries.append((query, time_range, include_domains))
        return agent_web.WebSearchResponse(
            results=(
                agent_web.WebSearchResult(
                    url=result_url,
                    title="Frontend Intern",
                    excerpt="React and TypeScript internship responsibilities.",
                    published_date="2026-08-02",
                    source_kind="fetched_page",
                    passages=(
                        agent_web.WebPassage(
                            section="Responsibilities",
                            text=("React and TypeScript internship responsibilities."),
                        ),
                    ),
                ),
                agent_web.WebSearchResult(
                    url="https://careers.example/jobs/undated",
                    title="Undated Frontend Role",
                    excerpt="No publication date was supplied by the provider.",
                ),
            ),
        )

    async def fake_fetch(*_args: object) -> agent_web.WebReference:
        raise AssertionError("web_fetch must reuse the page already read by search")

    monkeypatch.setattr(agent_web, "_async_search_web", fake_search)
    monkeypatch.setattr(agent_web, "_async_fetch_web_reference", fake_fetch)

    search_tool = asyncio.run(
        _invoke(
            adapter,
            _web_tool_call(
                "web_search",
                {
                    "query": "王小明 xiaoming@example.com 前端实习 JD",
                    "timeRange": "month",
                    "includeDomains": ["careers.example"],
                },
            ),
        ),
    )
    fetch_tool = asyncio.run(
        _invoke(
            adapter,
            _web_tool_call("web_fetch", {"url": result_url}),
        ),
    )

    assert seen_queries == [(safe_query, "month", ("careers.example",))]
    assert search_tool.input == {
        "query": safe_query,
        "timeRange": "month",
        "includeDomains": ["careers.example"],
    }
    assert search_tool.state == "output-available"
    assert search_tool.output
    search_result = search_tool.output["references"][0]
    assert search_result["url"] == result_url
    assert search_result["sourceId"].startswith("source-web-")
    assert search_result["publishedDate"] == "2026-08-02"
    assert "publishedDate" not in search_tool.output["candidates"][0]
    assert "sourceId" not in search_tool.output["candidates"][0]
    search_sources = adapter.sources((search_tool,))
    assert [source.url for source in search_sources] == [result_url]
    assert fetch_tool.state == "output-available"
    assert fetch_tool.output["references"][0]["passages"] == [
        {
            "section": "Responsibilities",
            "text": "React and TypeScript internship responsibilities.",
        },
    ]


def test_web_search_observation_distributes_reference_passage_budget(
    monkeypatch,
) -> None:
    adapter = _web_adapter(prompt="搜索前端岗位要求")
    urls = [f"https://careers.example/jobs/{index}" for index in range(6)]

    async def fake_search(
        _query: str,
        _time_range: str | None,
        _include_domains: tuple[str, ...],
        _browser: agent_web.WebBrowser,
    ) -> agent_web.WebSearchResponse:
        return agent_web.WebSearchResponse(
            results=tuple(
                agent_web.WebSearchResult(
                    url=url,
                    title=f"Frontend Role {index}",
                    excerpt=f"Frontend role {index} responsibilities and requirements.",
                    source_kind=("fetched_page" if index < 2 else "search_snippet"),
                    passages=(
                        tuple(
                            agent_web.WebPassage(
                                section=(
                                    "S" * 5_000
                                    if index == 0 and passage_index == 0
                                    else f"Section {passage_index}"
                                ),
                                text=f"Reference {index} passage {passage_index}.",
                            )
                            for passage_index in range(4)
                        )
                        if index != 4
                        else ()
                    ),
                )
                for index, url in enumerate(urls)
            ),
        )

    monkeypatch.setattr(agent_web, "_async_search_web", fake_search)

    search_tool = asyncio.run(
        _invoke(
            adapter,
            _web_tool_call("web_search", {"query": "frontend requirements"}),
        ),
    )
    assert search_tool.output
    references = search_tool.output["references"]
    candidates = search_tool.output["candidates"]
    passage_counts = [len(reference["passages"]) for reference in references]
    assert [reference["url"] for reference in references] == urls[:2]
    assert [candidate["url"] for candidate in candidates] == urls[2:5]
    assert all(count >= 1 for count in passage_counts)
    assert sum(passage_counts) <= 8
    assert all(
        len(passage["section"]) <= 160
        for reference in references
        for passage in reference["passages"]
    )


@pytest.mark.parametrize(
    ("prompt", "expected_query"),
    [
        ("请搜索上海的前端实习岗位。", "上海 [redacted_identity_0] 前端实习"),
        ("请搜索王小明的前端实习岗位。", "[redacted_identity_1] 王小明 前端实习"),
    ],
)
def test_web_search_keeps_hidden_terms_explicitly_entered_in_current_prompt(
    monkeypatch, prompt, expected_query,
) -> None:
    adapter = _web_adapter(
        prompt=prompt,
        hidden_terms=("王小明", "上海"),
    )
    seen_queries: list[str] = []

    async def fake_search(
        query: str,
        _time_range: str | None,
        _include_domains: tuple[str, ...],
        _browser: agent_web.WebBrowser,
    ) -> agent_web.WebSearchResponse:
        seen_queries.append(query)
        return agent_web.WebSearchResponse()

    monkeypatch.setattr(agent_web, "_async_search_web", fake_search)

    tool = asyncio.run(
        _invoke(
            adapter,
            _web_tool_call(
                "web_search",
                {"query": "上海 王小明 前端实习"},
            ),
        ),
    )

    assert tool.state == "output-available"
    assert seen_queries == [expected_query]


def test_web_search_drops_results_whose_url_would_leak_hidden_terms(
    monkeypatch,
) -> None:
    adapter = _web_adapter(
        prompt="搜索目标岗位",
        resume={"basic": {"name": "王小明"}, "sections": []},
        hidden_terms=("王小明",),
    )

    async def fake_search(
        _query: str,
        _time_range: str | None,
        _include_domains: tuple[str, ...],
        _browser: agent_web.WebBrowser,
    ) -> agent_web.WebSearchResponse:
        return agent_web.WebSearchResponse(
            results=(
                agent_web.WebSearchResult(
                    url="https://example.com/people/王小明",
                    title="Potential match",
                    excerpt="Public profile",
                ),
            ),
        )

    monkeypatch.setattr(agent_web, "_async_search_web", fake_search)

    tool = asyncio.run(
        _invoke(
            adapter,
            _web_tool_call("web_search", {"query": "王小明 前端"}),
        ),
    )

    assert tool.state == "output-available"
    assert tool.output == {"references": [], "candidates": []}


def test_web_search_drops_sensitive_include_domains_before_provider(
    monkeypatch,
) -> None:
    adapter = _web_adapter(
        prompt="搜索目标岗位",
        hidden_terms=("王小明",),
    )
    seen_domains: list[tuple[str, ...]] = []

    async def fake_search(
        _query: str,
        _time_range: str | None,
        include_domains: tuple[str, ...],
        _browser: agent_web.WebBrowser,
    ) -> agent_web.WebSearchResponse:
        seen_domains.append(include_domains)
        return agent_web.WebSearchResponse()

    monkeypatch.setattr(agent_web, "_async_search_web", fake_search)

    tool = asyncio.run(
        _invoke(
            adapter,
            _web_tool_call(
                "web_search",
                {
                    "query": "前端实习",
                    "includeDomains": [
                        "王小明.example",
                        "https://invalid.example/jobs",
                        "careers.example",
                    ],
                },
            ),
        ),
    )

    assert seen_domains == [("careers.example",)]
    assert tool.input == {
        "query": "前端实习",
        "includeDomains": ["careers.example"],
    }


def test_failed_web_search_does_not_block_a_known_public_url(monkeypatch) -> None:
    adapter = _web_adapter(prompt="搜索目标岗位")
    result_url = "https://careers.example/jobs/frontend-intern"

    async def fake_search(
        _query: str,
        _time_range: str | None,
        _include_domains: tuple[str, ...],
        _browser: agent_web.WebBrowser,
    ) -> agent_web.WebSearchResponse:
        return agent_web.WebSearchResponse(
            error_reason="rate_limited",
        )

    async def fake_fetch(
        requested_url: str,
        relevance_query: str,
        reference_title: str,
        _browser: agent_web.WebBrowser,
    ) -> agent_web.WebReference:
        assert requested_url == result_url
        assert relevance_query == "搜索目标岗位"
        assert reference_title == ""
        return agent_web.WebReference(
            title="Frontend Intern",
            excerpt="Current public frontend internship requirements.",
            final_url=result_url,
        )

    monkeypatch.setattr(agent_web, "_async_search_web", fake_search)
    monkeypatch.setattr(
        agent_web,
        "_async_fetch_web_reference",
        fake_fetch,
    )

    search_tool = asyncio.run(
        _invoke(
            adapter,
            _web_tool_call("web_search", {"query": "前端实习 JD"}),
        ),
    )
    fetch_tool = asyncio.run(
        _invoke(
            adapter,
            _web_tool_call("web_fetch", {"url": result_url}),
        ),
    )

    assert search_tool.state == "output-error"
    assert search_tool.output == {"reason": "rate_limited"}
    assert fetch_tool.state == "output-available"


def test_web_fetch_allows_url_from_current_user_prompt(monkeypatch) -> None:
    url = "https://portfolio.example/people/王小明"
    adapter = _web_adapter(
        prompt=f"请查看 {url}。",
        hidden_terms=("王小明",),
    )

    async def fake_fetch(
        requested_url: str,
        *_context: str,
    ) -> agent_web.WebReference:
        assert requested_url == url
        return agent_web.WebReference(
            title="Search project",
            excerpt="Implemented a public search project with measurable outcomes.",
            final_url=url,
            passages=(
                agent_web.WebPassage(
                    section="Search project",
                    text=(
                        "Implemented a public search project with measurable outcomes."
                    ),
                ),
            ),
        )

    monkeypatch.setattr(agent_web, "_async_fetch_web_reference", fake_fetch)

    tool = asyncio.run(
        _invoke(
            adapter,
            _web_tool_call("web_fetch", {"url": url}),
        ),
    )

    assert tool.state == "output-available"
    assert tool.output
    result = tool.output["references"][0]
    assert result["url"] == url
    assert re.fullmatch(r"source-web-[0-9a-f]{16}", result["sourceId"])


def test_web_fetch_uses_a_provider_public_final_url(monkeypatch) -> None:
    original_url = "https://careers.example/jobs/latest"
    final_url = "https://jobs.example-ats.com/frontend-intern"
    adapter = _web_adapter(prompt=f"请查看 {original_url}。")

    async def fake_fetch(
        requested_url: str,
        *_context: str,
    ) -> agent_web.WebReference:
        assert requested_url == original_url
        return agent_web.WebReference(
            title="Frontend Intern",
            excerpt="Frontend internship responsibilities and requirements.",
            final_url=final_url,
            passages=(
                agent_web.WebPassage(
                    section="Frontend Intern",
                    text="Frontend internship responsibilities and requirements.",
                ),
            ),
        )

    monkeypatch.setattr(agent_web, "_async_fetch_web_reference", fake_fetch)

    tool = asyncio.run(
        _invoke(
            adapter,
            _web_tool_call(
                "web_fetch",
                {"url": original_url},
                call_id="fetch-original",
            ),
        ),
    )
    assert tool.state == "output-available"
    assert tool.output
    assert tool.output["references"][0]["url"] == final_url


def test_web_fetch_does_not_send_a_sensitive_model_url_to_provider(
    monkeypatch,
) -> None:
    adapter = _web_adapter(
        prompt="查看目标页面",
        hidden_terms=("王小明",),
    )

    async def fail_if_called(*_args: object) -> object:
        raise AssertionError("A sensitive URL reached the provider.")

    monkeypatch.setattr(agent_web, "_async_fetch_web_reference", fail_if_called)

    tool = asyncio.run(
        _invoke(
            adapter,
            _web_tool_call(
                "web_fetch",
                {"url": "https://example.com/people/王小明"},
            ),
        ),
    )

    assert tool.state == "output-error"
    assert tool.output == {"reason": "invalid_url"}
