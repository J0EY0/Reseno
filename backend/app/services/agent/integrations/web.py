import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

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


@dataclass(frozen=True)
class WebReference:
    """Text extracted from a fetched webpage."""

    title: str
    excerpt: str


@dataclass(frozen=True)
class WebSearchResult:
    """One web search result that can be fetched as JD context."""

    title: str
    url: str
    excerpt: str


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


def _web_reference_from_response(
    url: str,
    raw: bytes,
    content_type: str,
    charset: str,
) -> WebReference | None:
    """Parse fetched response bytes into a web reference."""

    decoded = raw.decode(charset, errors="replace")
    if "html" not in content_type.lower():
        excerpt = _compact_text(decoded)
        return (
            WebReference(title=url, excerpt=excerpt)
            if _is_useful_web_excerpt(excerpt)
            else None
        )

    parser = PageTextParser()
    parser.feed(decoded)
    title = _compact_text(" ".join(parser.title_parts), limit=120)
    excerpt = _compact_text(" ".join(parser.text_parts))
    if not _is_useful_web_excerpt(excerpt):
        return None

    return WebReference(title=title or url, excerpt=excerpt)


def _fetch_web_reference(url: str, timeout: float = 4.0) -> WebReference | None:
    """Fetch a URL and return visible text that can be cited."""

    try:
        with httpx.Client(
            headers=_web_headers("text/html,text/plain;q=0.9,*/*;q=0.8"),
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return None

    return _web_reference_from_response(
        url,
        response.content[:FETCH_MAX_BYTES],
        response.headers.get("content-type", ""),
        response.encoding or "utf-8",
    )


async def _async_fetch_web_reference(
    url: str,
    timeout: float = 4.0,
) -> WebReference | None:
    """Fetch a URL with an async HTTP client and return visible citation text."""

    try:
        async with httpx.AsyncClient(
            headers=_web_headers("text/html,text/plain;q=0.9,*/*;q=0.8"),
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
    except (httpx.HTTPError, ValueError):
        return None

    raw = response.content[:FETCH_MAX_BYTES]
    return _web_reference_from_response(
        url,
        raw,
        response.headers.get("content-type", ""),
        response.encoding or "utf-8",
    )


def _search_web_results(
    query: str,
    timeout: float = 6.0,
) -> tuple[list[WebSearchResult], str | None]:
    """Search the web for reference pages and return organic result links."""

    last_error: str | None = None
    with httpx.Client(
        headers=_web_headers("text/html,*/*;q=0.8"),
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        for search_url in _search_urls(query):
            try:
                response = client.get(search_url)
                response.raise_for_status()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = f"Web search request failed: {exc}"
                continue

            results, parse_error = _parse_search_results(
                response.content[:SEARCH_MAX_BYTES],
                response.encoding or "utf-8",
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
        follow_redirects=True,
        timeout=timeout,
    ) as client:
        for search_url in _search_urls(query):
            try:
                response = await client.get(search_url)
                response.raise_for_status()
            except (httpx.HTTPError, ValueError) as exc:
                last_error = f"Web search request failed: {exc}"
                continue

            results, parse_error = _parse_search_results(
                response.content[:SEARCH_MAX_BYTES],
                response.encoding or "utf-8",
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
            WebSearchResult(
                title=web_reference.title or result.title,
                url=result.url,
                excerpt=web_reference.excerpt,
            ),
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
            WebSearchResult(
                title=web_reference.title or result.title,
                url=result.url,
                excerpt=web_reference.excerpt,
            ),
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
    return WebSearchResult(
        title=web_reference.title or result.title,
        url=result.url,
        excerpt=web_reference.excerpt,
    )


def _search_snippet_fallback(result: WebSearchResult) -> WebSearchResult | None:
    excerpt = _compact_text(result.excerpt)
    if not _is_useful_search_snippet(excerpt):
        return None

    return WebSearchResult(
        title=result.title,
        url=result.url,
        excerpt=excerpt,
    )
