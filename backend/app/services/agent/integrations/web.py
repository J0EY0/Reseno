import asyncio
import ipaddress
import re
import socket
from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse

import httpx

from ..parsing_patterns import agent_patterns

URL_PATTERN = re.compile(r"https?://[^\s)>\"]+")
WEB_USER_AGENT = "Mozilla/5.0 (compatible; ResuMate/1.0)"
WEB_ACCEPT_LANGUAGE = "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"
FETCH_MAX_BYTES = 220_000
SEARCH_MAX_BYTES = 240_000
SEARCH_ENDPOINTS = (
    "https://html.duckduckgo.com/html/?q={query}",
    "https://duckduckgo.com/html/?q={query}",
)
MAX_WEB_SEARCH_QUERIES = 5
MAX_WEB_SEARCH_RESULTS = 10
MAX_WEB_REDIRECTS = 5
BLOCKED_WEB_HOSTS = frozenset(
    {
        "instance-data.ec2.internal",
        "metadata.azure.internal",
        "metadata.google",
        "metadata.google.internal",
    },
)


@dataclass(frozen=True)
class WebReference:
    """Text plus non-sensitive provenance from a fetched webpage."""

    title: str
    excerpt: str
    final_url: str = ""
    status_code: int | None = None
    fetched_at: str = ""
    content_sha256: str = ""


@dataclass(frozen=True)
class WebSearchResult:
    """One web search result that can be fetched as JD context."""

    title: str
    url: str
    excerpt: str
    final_url: str = ""
    status_code: int | None = None
    fetched_at: str = ""
    content_sha256: str = ""


@dataclass(frozen=True)
class WebSearchReference:
    """Aggregated web search context across one or more queries."""

    query: str
    results: tuple[WebSearchResult, ...]
    query_count: int
    result_count: int
    error: str | None = None

    @property
    def primary(self) -> WebSearchResult | None:
        return self.results[0] if self.results else None

    @property
    def excerpt(self) -> str:
        return _compact_text(" ".join(result.excerpt for result in self.results))


@dataclass(frozen=True)
class _BoundedWebResponse:
    """Security-checked response bytes plus non-sensitive provenance metadata."""

    raw: bytes
    content_type: str
    charset: str
    final_url: str
    status_code: int
    fetched_at: str
    content_sha256: str


def _search_result_url(href: str | None) -> str:
    """Return a real result URL from a search engine link."""

    if not href:
        return ""

    candidate = href.strip()
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"

    parsed = urlparse(candidate)
    if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
        redirected = parse_qs(parsed.query).get("uddg", [""])[0]
        candidate = unquote(redirected)
        parsed = urlparse(candidate)

    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return candidate

    return ""


class SearchResultParser(HTMLParser):
    """Extract organic results from DuckDuckGo's lightweight HTML page."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[WebSearchResult] = []
        self._result_url = ""
        self._title_parts: list[str] = []
        self._in_title = False
        self._snippet_parts: list[str] = []
        self._in_snippet = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """Track result titles and snippets in the search HTML."""

        attrs_dict = {key: value or "" for key, value in attrs}
        class_name = attrs_dict.get("class", "")
        if tag.lower() == "a" and "result__a" in class_name:
            result_url = _search_result_url(attrs_dict.get("href"))
            if result_url:
                self._result_url = result_url
                self._title_parts = []
                self._in_title = True
            return

        if "result__snippet" in class_name:
            self._snippet_parts = []
            self._in_snippet = True

    def handle_endtag(self, tag: str) -> None:
        """Finalize the current title or snippet capture."""

        if tag.lower() == "a" and self._in_title:
            title = " ".join(self._title_parts).strip()
            if title and self._result_url:
                self.results.append(
                    WebSearchResult(
                        title=title,
                        url=self._result_url,
                        excerpt="",
                    ),
                )
            self._result_url = ""
            self._title_parts = []
            self._in_title = False
            return

        if self._in_snippet and tag.lower() in {"a", "td", "div"}:
            excerpt = " ".join(self._snippet_parts).strip()
            if excerpt and self.results and not self.results[-1].excerpt:
                result = self.results[-1]
                self.results[-1] = WebSearchResult(
                    title=result.title,
                    url=result.url,
                    excerpt=excerpt,
                )
            self._snippet_parts = []
            self._in_snippet = False

    def handle_data(self, data: str) -> None:
        """Collect text for the current search result field."""

        text = data.strip()
        if not text:
            return

        if self._in_title:
            self._title_parts.append(text)
        elif self._in_snippet:
            self._snippet_parts.append(text)


class PageTextParser(HTMLParser):
    """Extract title and visible text from a small HTML document."""

    def __init__(self) -> None:
        super().__init__()
        self._ignored_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.text_parts: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """Track elements that should not contribute visible text."""

        normalized_tag = tag.lower()
        if normalized_tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
        if normalized_tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        """Close ignored and title elements."""

        normalized_tag = tag.lower()
        if normalized_tag in {"script", "style", "noscript"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
        if normalized_tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        """Collect visible text and page title fragments."""

        text = data.strip()
        if not text:
            return

        if self._in_title:
            self.title_parts.append(text)
            return

        if self._ignored_depth == 0:
            self.text_parts.append(text)


def _compact_text(value: str, limit: int = 700) -> str:
    """Collapse whitespace and trim text for prompts and citations."""

    return re.sub(r"\s+", " ", unescape(value)).strip()[:limit]


def _is_useful_web_excerpt(value: str) -> bool:
    """Return whether fetched page text is useful enough as reference context."""

    text = _compact_text(value, limit=1_000).lower()
    if len(text) < 80:
        return False

    blocked_markers = agent_patterns("web.blocked_excerpt_markers")
    return not any(marker in text for marker in blocked_markers)


def _is_useful_search_snippet(value: str) -> bool:
    """Return whether a search-result snippet is useful as fallback context."""

    text = _compact_text(value, limit=1_000).lower()
    if len(text) < 50:
        return False

    blocked_markers = agent_patterns("web.blocked_excerpt_markers")
    return not any(marker in text for marker in blocked_markers)


def _web_headers(accept: str) -> dict[str, str]:
    """Return headers shared by sync and async web requests."""

    return {
        "Accept": accept,
        "Accept-Language": WEB_ACCEPT_LANGUAGE,
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "User-Agent": WEB_USER_AGENT,
    }


def _is_public_ip_address(value: str) -> bool:
    """Return whether an IP literal is safe for an outbound web request."""

    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False

    # ``is_global`` also excludes shared carrier-grade NAT space such as
    # 100.64.0.0/10, which some cloud platforms use for metadata services.
    return address.is_global and not address.is_multicast


def _is_allowed_web_url(url: str) -> bool:
    """Resolve and reject any target that is not entirely on the public internet."""

    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").rstrip(".").lower()
        # Reading ``port`` also rejects malformed or out-of-range port values.
        _ = parsed.port
    except ValueError:
        return False

    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname in BLOCKED_WEB_HOSTS
    ):
        return False

    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        try:
            address_info = socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except (OSError, UnicodeError):
            return False

        resolved_addresses = {sockaddr[0] for *_, sockaddr in address_info}
        return bool(resolved_addresses) and all(
            _is_public_ip_address(address) for address in resolved_addresses
        )

    return _is_public_ip_address(hostname)


def _has_public_connected_peer(response: httpx.Response) -> bool:
    """Fail closed unless httpcore reports a public address for the actual peer."""

    network_stream = response.extensions.get("network_stream")
    get_extra_info = getattr(network_stream, "get_extra_info", None)
    if not callable(get_extra_info):
        return False

    try:
        server_addr = get_extra_info("server_addr")
    except (OSError, RuntimeError, TypeError, ValueError):
        return False

    if isinstance(server_addr, tuple) and server_addr:
        peer_address = server_addr[0]
    else:
        peer_address = server_addr

    return isinstance(peer_address, str) and _is_public_ip_address(peer_address)


def _web_reference_from_response(
    url: str,
    raw: bytes,
    content_type: str,
    charset: str,
    *,
    status_code: int,
    fetched_at: str,
    content_sha256: str,
) -> WebReference | None:
    """Parse fetched response bytes into a web reference."""

    decoded = raw.decode(charset, errors="replace")
    if "html" not in content_type.lower():
        excerpt = _compact_text(decoded)
        return (
            WebReference(
                title=url,
                excerpt=excerpt,
                final_url=url,
                status_code=status_code,
                fetched_at=fetched_at,
                content_sha256=content_sha256,
            )
            if _is_useful_web_excerpt(excerpt)
            else None
        )

    parser = PageTextParser()
    parser.feed(decoded)
    title = _compact_text(" ".join(parser.title_parts), limit=120)
    excerpt = _compact_text(" ".join(parser.text_parts))
    if not _is_useful_web_excerpt(excerpt):
        return None

    return WebReference(
        title=title or url,
        excerpt=excerpt,
        final_url=url,
        status_code=status_code,
        fetched_at=fetched_at,
        content_sha256=content_sha256,
    )


def _utc_timestamp() -> str:
    """Return an unambiguous UTC timestamp for fetched evidence metadata."""

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _read_limited_bytes(chunks: Iterable[bytes], limit: int) -> bytes:
    """Read at most ``limit`` decoded response bytes without buffering the rest."""

    captured = bytearray()
    for chunk in chunks:
        remaining = limit - len(captured)
        if remaining <= 0:
            break
        captured.extend(chunk[:remaining])
        if len(captured) >= limit:
            break
    return bytes(captured)


async def _async_read_limited_bytes(
    chunks: AsyncIterable[bytes],
    limit: int,
) -> bytes:
    """Async counterpart to ``_read_limited_bytes``."""

    captured = bytearray()
    async for chunk in chunks:
        remaining = limit - len(captured)
        if remaining <= 0:
            break
        captured.extend(chunk[:remaining])
        if len(captured) >= limit:
            break
    return bytes(captured)


def _get_bounded_web_response(
    client: httpx.Client,
    url: str,
    byte_limit: int,
) -> _BoundedWebResponse | None:
    """GET a public URL while validating every redirect and bounding its body."""

    current_url = url
    for redirect_count in range(MAX_WEB_REDIRECTS + 1):
        if not _is_allowed_web_url(current_url):
            return None

        with client.stream("GET", current_url) as response:
            if not _has_public_connected_peer(response):
                return None

            if response.is_redirect:
                location = response.headers.get("location")
                if not location or redirect_count >= MAX_WEB_REDIRECTS:
                    return None
                current_url = urljoin(str(response.url), location)
                continue

            response.raise_for_status()
            raw = _read_limited_bytes(response.iter_bytes(), byte_limit)
            return _BoundedWebResponse(
                raw=raw,
                content_type=response.headers.get("content-type", ""),
                charset=response.encoding or "utf-8",
                final_url=str(response.url),
                status_code=response.status_code,
                fetched_at=_utc_timestamp(),
                content_sha256=sha256(raw).hexdigest(),
            )

    return None


async def _async_get_bounded_web_response(
    client: httpx.AsyncClient,
    url: str,
    byte_limit: int,
) -> _BoundedWebResponse | None:
    """Async counterpart to ``_get_bounded_web_response``."""

    current_url = url
    for redirect_count in range(MAX_WEB_REDIRECTS + 1):
        # DNS resolution uses the blocking socket API, so keep it off the
        # event loop while retaining the same validation as the sync path.
        if not await asyncio.to_thread(_is_allowed_web_url, current_url):
            return None

        async with client.stream("GET", current_url) as response:
            if not _has_public_connected_peer(response):
                return None

            if response.is_redirect:
                location = response.headers.get("location")
                if not location or redirect_count >= MAX_WEB_REDIRECTS:
                    return None
                current_url = urljoin(str(response.url), location)
                continue

            response.raise_for_status()
            raw = await _async_read_limited_bytes(
                response.aiter_bytes(),
                byte_limit,
            )
            return _BoundedWebResponse(
                raw=raw,
                content_type=response.headers.get("content-type", ""),
                charset=response.encoding or "utf-8",
                final_url=str(response.url),
                status_code=response.status_code,
                fetched_at=_utc_timestamp(),
                content_sha256=sha256(raw).hexdigest(),
            )

    return None


def _fetch_web_reference(url: str, timeout: float = 4.0) -> WebReference | None:
    """Fetch a URL and return visible text that can be cited."""

    try:
        with httpx.Client(
            headers=_web_headers("text/html,text/plain;q=0.9,*/*;q=0.8"),
            follow_redirects=False,
            timeout=timeout,
            trust_env=False,
        ) as client:
            fetched = _get_bounded_web_response(client, url, FETCH_MAX_BYTES)
    except (httpx.HTTPError, ValueError):
        return None

    if fetched is None:
        return None

    return _web_reference_from_response(
        fetched.final_url,
        fetched.raw,
        fetched.content_type,
        fetched.charset,
        status_code=fetched.status_code,
        fetched_at=fetched.fetched_at,
        content_sha256=fetched.content_sha256,
    )


async def _async_fetch_web_reference(
    url: str,
    timeout: float = 4.0,
) -> WebReference | None:
    """Fetch a URL with an async HTTP client and return visible citation text."""

    try:
        async with httpx.AsyncClient(
            headers=_web_headers("text/html,text/plain;q=0.9,*/*;q=0.8"),
            follow_redirects=False,
            timeout=timeout,
            trust_env=False,
        ) as client:
            fetched = await _async_get_bounded_web_response(
                client,
                url,
                FETCH_MAX_BYTES,
            )
    except (httpx.HTTPError, ValueError):
        return None

    if fetched is None:
        return None

    return _web_reference_from_response(
        fetched.final_url,
        fetched.raw,
        fetched.content_type,
        fetched.charset,
        status_code=fetched.status_code,
        fetched_at=fetched.fetched_at,
        content_sha256=fetched.content_sha256,
    )


def _search_web_results(
    query: str,
    timeout: float = 6.0,
) -> tuple[list[WebSearchResult], str | None]:
    """Search the web for reference pages and return organic result links."""

    last_error: str | None = None
    with httpx.Client(
        headers=_web_headers("text/html,*/*;q=0.8"),
        follow_redirects=False,
        timeout=timeout,
        trust_env=False,
    ) as client:
        for search_url in _search_urls(query):
            try:
                fetched = _get_bounded_web_response(
                    client,
                    search_url,
                    SEARCH_MAX_BYTES,
                )
            except (httpx.HTTPError, ValueError) as exc:
                last_error = f"Web search request failed: {exc}"
                continue
            if fetched is None:
                last_error = "Web search target was blocked or redirected unsafely."
                continue

            results, parse_error = _parse_search_results(
                fetched.raw,
                fetched.charset,
            )
            if results:
                return results, None
            last_error = parse_error

    return [], last_error or "Web search returned no usable result links."


async def _async_search_web_results(
    query: str,
    timeout: float = 6.0,
) -> tuple[list[WebSearchResult], str | None]:
    """Search the web for reference pages using an async HTTP client."""

    last_error: str | None = None
    async with httpx.AsyncClient(
        headers=_web_headers("text/html,*/*;q=0.8"),
        follow_redirects=False,
        timeout=timeout,
        trust_env=False,
    ) as client:
        for search_url in _search_urls(query):
            try:
                fetched = await _async_get_bounded_web_response(
                    client,
                    search_url,
                    SEARCH_MAX_BYTES,
                )
            except (httpx.HTTPError, ValueError) as exc:
                last_error = f"Web search request failed: {exc}"
                continue
            if fetched is None:
                last_error = "Web search target was blocked or redirected unsafely."
                continue

            results, parse_error = _parse_search_results(
                fetched.raw,
                fetched.charset,
            )
            if results:
                return results, None
            last_error = parse_error

    return [], last_error or "Web search returned no usable result links."


def _search_urls(query: str) -> tuple[str, ...]:
    encoded_query = quote_plus(query)
    return tuple(endpoint.format(query=encoded_query) for endpoint in SEARCH_ENDPOINTS)


def _parse_search_results(
    raw: bytes,
    charset: str,
) -> tuple[list[WebSearchResult], str | None]:
    """Parse search result HTML into deduplicated organic links."""

    parser = SearchResultParser()
    parser.feed(raw.decode(charset, errors="replace"))

    deduped_results: list[WebSearchResult] = []
    seen_urls: set[str] = set()
    for result in parser.results:
        if result.url in seen_urls:
            continue

        seen_urls.add(result.url)
        deduped_results.append(
            WebSearchResult(
                title=_compact_text(result.title, limit=120),
                url=result.url,
                excerpt=_compact_text(result.excerpt),
            ),
        )
        if len(deduped_results) >= 5:
            break

    if not deduped_results:
        return [], "Web search returned no usable result links."

    return deduped_results, None


def _search_web_reference(query: str) -> tuple[WebSearchResult | None, int, str | None]:
    """Search for a reference page and fetch the first readable result page."""

    results, error = _search_web_results(query)
    if error:
        return None, 0, error

    snippet_fallback: WebSearchResult | None = None
    for result in results:
        web_reference = _fetch_web_reference(result.url)
        if not web_reference:
            snippet_fallback = snippet_fallback or _search_snippet_fallback(result)
            continue

        return (
            _web_search_result_from_reference(result, web_reference),
            len(results),
            None,
        )

    if snippet_fallback:
        return snippet_fallback, len(results), None

    return None, len(results), "Search returned links, but no readable page text."


def _search_web_reference_results(
    query: str,
    max_results: int,
) -> tuple[list[WebSearchResult], int, str | None]:
    """Search for reference pages and return multiple readable/snippet results."""

    results, error = _search_web_results(query)
    if error:
        return [], 0, error

    references: list[WebSearchResult] = []
    for result in results:
        if len(references) >= max_results:
            break

        web_reference = _fetch_web_reference(result.url)
        if web_reference:
            references.append(_web_search_result_from_reference(result, web_reference))
            continue

        snippet_fallback = _search_snippet_fallback(result)
        if snippet_fallback:
            references.append(snippet_fallback)

    if references:
        return references, len(results), None

    return [], len(results), "Search returned links, but no readable page text."


async def _async_search_web_reference(
    query: str,
) -> tuple[WebSearchResult | None, int, str | None]:
    """Search for a reference page and fetch the first readable result page async."""

    results, error = await _async_search_web_results(query)
    if error:
        return None, 0, error

    snippet_fallback: WebSearchResult | None = None
    for result in results:
        web_reference = await _async_fetch_web_reference(result.url)
        if not web_reference:
            snippet_fallback = snippet_fallback or _search_snippet_fallback(result)
            continue

        return (
            _web_search_result_from_reference(result, web_reference),
            len(results),
            None,
        )

    if snippet_fallback:
        return snippet_fallback, len(results), None

    return None, len(results), "Search returned links, but no readable page text."


async def _async_search_web_reference_results(
    query: str,
    max_results: int,
) -> tuple[list[WebSearchResult], int, str | None]:
    """Search for multiple readable/snippet reference pages async."""

    results, error = await _async_search_web_results(query)
    if error:
        return [], 0, error

    references: list[WebSearchResult] = []
    for result in results:
        if len(references) >= max_results:
            break

        web_reference = await _async_fetch_web_reference(result.url)
        if web_reference:
            references.append(_web_search_result_from_reference(result, web_reference))
            continue

        snippet_fallback = _search_snippet_fallback(result)
        if snippet_fallback:
            references.append(snippet_fallback)

    if references:
        return references, len(results), None

    return [], len(results), "Search returned links, but no readable page text."


def _search_web_reference_summary(
    queries: list[str],
    max_results: int = MAX_WEB_SEARCH_RESULTS,
) -> WebSearchReference:
    """Search multiple query variants and return deduplicated reference context."""

    normalized_queries = _normalized_search_queries(queries)
    result_limit = _normalized_max_search_results(max_results)
    results: list[WebSearchResult] = []
    seen_urls: set[str] = set()
    total_result_count = 0
    last_error: str | None = None

    for query in normalized_queries:
        remaining = result_limit - len(results)
        if remaining <= 0:
            break

        query_results, result_count, error = _search_web_reference_results(
            query,
            remaining,
        )
        total_result_count += result_count
        if error:
            last_error = error
        for result in query_results:
            if result.url in seen_urls:
                continue

            seen_urls.add(result.url)
            results.append(result)

    return WebSearchReference(
        query=normalized_queries[0] if normalized_queries else "",
        results=tuple(results),
        query_count=len(normalized_queries),
        result_count=total_result_count,
        error=None if results else last_error,
    )


async def _async_search_web_reference_summary(
    queries: list[str],
    max_results: int = MAX_WEB_SEARCH_RESULTS,
) -> WebSearchReference:
    """Search multiple query variants async and return deduplicated context."""

    normalized_queries = _normalized_search_queries(queries)
    result_limit = _normalized_max_search_results(max_results)
    results: list[WebSearchResult] = []
    seen_urls: set[str] = set()
    total_result_count = 0
    last_error: str | None = None

    for query in normalized_queries:
        remaining = result_limit - len(results)
        if remaining <= 0:
            break

        query_results, result_count, error = await _async_search_web_reference_results(
            query,
            remaining,
        )
        total_result_count += result_count
        if error:
            last_error = error
        for result in query_results:
            if result.url in seen_urls:
                continue

            seen_urls.add(result.url)
            results.append(result)

    return WebSearchReference(
        query=normalized_queries[0] if normalized_queries else "",
        results=tuple(results),
        query_count=len(normalized_queries),
        result_count=total_result_count,
        error=None if results else last_error,
    )


def _normalized_search_queries(queries: list[str]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for query in queries:
        compacted = _compact_text(query, limit=160)
        key = compacted.casefold()
        if not compacted or key in seen:
            continue

        normalized.append(compacted)
        seen.add(key)
        if len(normalized) >= MAX_WEB_SEARCH_QUERIES:
            break

    return tuple(normalized)


def _normalized_max_search_results(max_results: int) -> int:
    return min(max(max_results, 1), MAX_WEB_SEARCH_RESULTS)


def _web_search_result_from_reference(
    result: WebSearchResult,
    web_reference: WebReference,
) -> WebSearchResult:
    final_url = web_reference.final_url or result.url
    return WebSearchResult(
        title=web_reference.title or result.title,
        url=final_url,
        excerpt=web_reference.excerpt,
        final_url=final_url,
        status_code=web_reference.status_code,
        fetched_at=web_reference.fetched_at,
        content_sha256=web_reference.content_sha256,
    )


def _search_snippet_fallback(result: WebSearchResult) -> WebSearchResult | None:
    excerpt = _compact_text(result.excerpt)
    if not _is_useful_search_snippet(excerpt):
        return None

    return WebSearchResult(
        title=result.title,
        url=result.url,
        excerpt=excerpt,
        final_url=result.final_url,
        status_code=result.status_code,
        fetched_at=result.fetched_at,
        content_sha256=result.content_sha256,
    )
