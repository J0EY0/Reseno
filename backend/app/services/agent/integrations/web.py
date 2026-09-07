from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import socket
from collections.abc import AsyncIterable
from dataclasses import dataclass
from datetime import date, datetime
from html import unescape
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import (
    parse_qs,
    parse_qsl,
    unquote,
    urlencode,
    urljoin,
    urlsplit,
    urlunsplit,
)

import httpx
from playwright.async_api import (
    Browser,
    BrowserContext,
    Playwright,
    Route,
    async_playwright,
)
from playwright.async_api import (
    Error as PlaywrightError,
)
from playwright.async_api import (
    TimeoutError as PlaywrightTimeoutError,
)

SEARCH_MAX_RESULTS = 5
SEARCH_DISCOVERY_RESULTS = SEARCH_MAX_RESULTS * 2
SEARCH_RESULTS_PER_SOURCE = 2
SEARCH_READ_RESULTS = SEARCH_MAX_RESULTS
SEARCH_TARGET_REFERENCES = 2
SEARCH_BROWSER_READ_RESULTS = 2
SEARCH_TIMEOUT_SECONDS = 12.0
FETCH_TIMEOUT_SECONDS = 10.0
PAGE_HTTP_TIMEOUT_SECONDS = 3.0
DYNAMIC_CONTENT_TIMEOUT_MS = 4_000
DUCKDUCKGO_SEARCH_URL = "https://html.duckduckgo.com/html/"
WEB_USER_AGENT = "Mozilla/5.0 (compatible; Reseno/1.0)"
WEB_ACCEPT_LANGUAGE = "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"
FETCH_EXCERPT_MAX_CHARS = 2_400
PAGE_PASSAGE_MAX_CHARS = 700
WEB_REFERENCE_MAX_PASSAGES = 4
MIN_USEFUL_EXCERPT_CHARS = 40
FETCH_MAX_BYTES = 1_000_000
SEARCH_MAX_BYTES = 300_000
MAX_WEB_REDIRECTS = 5
TIME_RANGE_VALUES = {"day": "d", "week": "w", "month": "m", "year": "y"}
DUCKDUCKGO_CHALLENGE_MARKERS = (
    b"anomaly-modal",
    b"challenge-form",
    b"captcha",
    b"bots use duckduckgo",
)
BLOCKED_WEB_HOSTS = frozenset(
    {
        "instance-data.ec2.internal",
        "metadata.azure.internal",
        "metadata.google",
        "metadata.google.internal",
    },
)
TUN_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")
BLOCKED_EXCERPT_MARKERS = (
    "enable javascript",
    "please enable javascript",
    "access denied",
    "captcha",
    "position is no longer available",
    "sign in to continue",
    "验证码登录/注册",
    "职位已下线",
    "正在加载中",
    "安全验证",
)
TRACKING_QUERY_PARAMETERS = frozenset(
    {
        "_hsenc",
        "_hsmi",
        "fbclid",
        "gclid",
        "mc_cid",
        "mc_eid",
        "msclkid",
    },
)


@dataclass(frozen=True)
class WebPassage:
    """One bounded piece of readable page content."""

    section: str
    text: str


@dataclass(frozen=True)
class WebReference:
    """Relevant text extracted from one public page."""

    title: str
    excerpt: str
    final_url: str = ""
    published_date: str = ""
    valid_through: str = ""
    passages: tuple[WebPassage, ...] = ()


@dataclass(frozen=True)
class WebSearchResult:
    """One normalized public result returned by the search provider."""

    url: str
    title: str
    excerpt: str
    published_date: str = ""
    valid_through: str = ""
    source_kind: Literal["fetched_page", "search_snippet"] = "search_snippet"
    passages: tuple[WebPassage, ...] = ()


@dataclass(frozen=True)
class WebSearchResponse:
    """Provider-neutral search results or one safe operational failure."""

    results: tuple[WebSearchResult, ...] = ()
    error_reason: str = ""


@dataclass(frozen=True)
class _PageTextBlock:
    text: str
    tag: str
    section: str
    in_main: bool
    in_article: bool
    in_chrome: bool


@dataclass(frozen=True)
class _BoundedWebResponse:
    raw: bytes
    content_type: str
    charset: str
    final_url: str
    status_code: int


class WebBrowser:
    """One lazy Chromium context reused by a single Agent turn."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._approved_targets: dict[str, bool] = {}

    async def context(self) -> BrowserContext:
        if self._context is not None:
            return self._context
        async with self._lock:
            if self._context is None:
                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(headless=True)
                self._context = await self._browser.new_context(
                    ignore_https_errors=False,
                )
        return self._context

    async def close(self) -> None:
        if self._context is not None:
            await self._context.close()
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()
        self._context = None
        self._browser = None
        self._playwright = None


def _canonical_web_url(url: str) -> str:
    """Normalize one HTTP(S) URL and remove common tracking fields."""

    try:
        parsed = urlsplit(url.strip())
        hostname = (parsed.hostname or "").rstrip(".").casefold()
        port = parsed.port
    except ValueError:
        return ""

    scheme = parsed.scheme.casefold()
    if (
        scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""

    displayed_host = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if scheme == "https" else 80
    netloc = (
        displayed_host if port in {None, default_port} else f"{displayed_host}:{port}"
    )
    query_fields = [
        (name, value)
        for name, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not name.casefold().startswith("utm_")
        and name.casefold() not in TRACKING_QUERY_PARAMETERS
    ]
    query_fields.sort(key=lambda item: (item[0].casefold(), item[1]))
    return urlunsplit(
        (
            scheme,
            netloc,
            parsed.path,
            urlencode(query_fields, doseq=True),
            "",
        ),
    )


def _is_public_reference_url(url: str) -> bool:
    """Reject obvious private targets before sending a URL to the extractor."""

    canonical = _canonical_web_url(url)
    if not canonical:
        return False
    hostname = (urlsplit(canonical).hostname or "").casefold()
    if (
        hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname in BLOCKED_WEB_HOSTS
    ):
        return False

    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return True
    return address.is_global and not address.is_multicast


def _safe_web_target_addresses(url: str) -> frozenset[str] | None:
    """Resolve one outbound target and reject private-network destinations."""

    canonical = _canonical_web_url(url)
    if not canonical:
        return None
    parsed = urlsplit(canonical)
    hostname = (parsed.hostname or "").casefold()
    if not _is_public_reference_url(canonical):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            address_info = socket.getaddrinfo(
                hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
                type=socket.SOCK_STREAM,
            )
        except (OSError, UnicodeError):
            return None
        addresses = frozenset(str(sockaddr[0]) for *_, sockaddr in address_info)
        if not addresses or not all(
            _is_safe_resolved_address(value) for value in addresses
        ):
            return None
        return addresses
    return frozenset({str(address)}) if address.is_global else None


def _is_safe_resolved_address(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.is_global or (
        address.version == 4 and address in TUN_FAKE_IP_NETWORK
    )


def _has_safe_connected_peer(
    response: httpx.Response,
    resolved_addresses: frozenset[str],
) -> bool:
    stream = response.extensions.get("network_stream")
    get_extra_info = getattr(stream, "get_extra_info", None)
    if not callable(get_extra_info):
        return False
    try:
        server_address = get_extra_info("server_addr")
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    peer = server_address[0] if isinstance(server_address, tuple) else server_address
    if not isinstance(peer, str):
        return False
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return address.is_global or (
        peer in resolved_addresses
        and address.version == 4
        and address in TUN_FAKE_IP_NETWORK
    )


async def _async_read_limited_bytes(
    chunks: AsyncIterable[bytes],
    limit: int,
) -> bytes:
    captured = bytearray()
    async for chunk in chunks:
        remaining = limit - len(captured)
        if remaining <= 0:
            break
        captured.extend(chunk[:remaining])
    return bytes(captured)


async def _async_get_bounded_web_response(
    client: httpx.AsyncClient,
    url: str,
    byte_limit: int,
    *,
    method: str = "GET",
    data: dict[str, str] | None = None,
) -> _BoundedWebResponse | None:
    current_url = url
    for redirect_count in range(MAX_WEB_REDIRECTS + 1):
        resolved_addresses = await asyncio.to_thread(
            _safe_web_target_addresses,
            current_url,
        )
        if resolved_addresses is None:
            return None
        async with client.stream(method, current_url, data=data) as response:
            if not _has_safe_connected_peer(response, resolved_addresses):
                return None
            if response.is_redirect:
                location = response.headers.get("location")
                if not location or redirect_count >= MAX_WEB_REDIRECTS:
                    return None
                current_url = urljoin(str(response.url), location)
                method = "GET"
                data = None
                continue
            raw = await _async_read_limited_bytes(response.aiter_bytes(), byte_limit)
            return _BoundedWebResponse(
                raw=raw,
                content_type=response.headers.get("content-type", ""),
                charset=response.encoding or "utf-8",
                final_url=_canonical_web_url(str(response.url)),
                status_code=response.status_code,
            )
    return None


def _compact_text(value: str, limit: int | None = 700) -> str:
    """Collapse whitespace and optionally bound model-visible text."""

    text = re.sub(r"\s+", " ", unescape(value)).strip()
    return text if limit is None else text[:limit]


def _duckduckgo_result_url(href: str) -> str:
    candidate = href.strip()
    if candidate.startswith("//"):
        candidate = f"https:{candidate}"
    parsed = urlsplit(candidate)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        redirected = parse_qs(parsed.query).get("uddg", [""])[0]
        candidate = unquote(redirected)
    return _canonical_web_url(candidate)


class _DuckDuckGoResultParser(HTMLParser):
    """Read organic results from DuckDuckGo's non-JavaScript page."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[WebSearchResult] = []
        self._url = ""
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []
        self._capture_title = False
        self._capture_snippet = False
        self._published_date = ""

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {name: value or "" for name, value in attrs}
        classes = attributes.get("class", "").split()
        if tag == "a" and "result__a" in classes:
            self._url = _duckduckgo_result_url(attributes.get("href", ""))
            self._title_parts = []
            self._snippet_parts = []
            self._published_date = ""
            self._capture_title = bool(self._url)
        elif "result__snippet" in classes:
            self._snippet_parts = []
            self._capture_snippet = bool(self.results)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_title:
            title = _compact_text(" ".join(self._title_parts), 120)
            if title and self._url:
                self.results.append(
                    WebSearchResult(
                        url=self._url,
                        title=title,
                        excerpt="",
                    ),
                )
            self._capture_title = False
            return
        if tag == "a" and self._capture_snippet:
            excerpt = _compact_text(" ".join(self._snippet_parts))
            if excerpt and self.results:
                result = self.results[-1]
                self.results[-1] = WebSearchResult(
                    url=result.url,
                    title=result.title,
                    excerpt=excerpt,
                    published_date=result.published_date or self._published_date,
                )
            self._capture_snippet = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._capture_title:
            self._title_parts.append(text)
        elif self._capture_snippet:
            self._snippet_parts.append(text)
        elif self.results and re.fullmatch(r"20\d{2}-\d{2}-\d{2}T\S+", text):
            result = self.results[-1]
            self._published_date = text
            self.results[-1] = WebSearchResult(
                url=result.url,
                title=result.title,
                excerpt=result.excerpt,
                published_date=text,
            )


def _parse_duckduckgo_results(raw: bytes, charset: str) -> list[WebSearchResult]:
    parser = _DuckDuckGoResultParser()
    parser.feed(raw.decode(charset, errors="replace"))

    results: list[WebSearchResult] = []
    seen_urls: set[str] = set()
    for result in parser.results:
        if result.url in seen_urls or not _is_public_reference_url(result.url):
            continue
        seen_urls.add(result.url)
        results.append(result)
        if len(results) >= SEARCH_DISCOVERY_RESULTS:
            break
    return results


def _select_search_results(
    results: list[WebSearchResult],
    *,
    limit: int = SEARCH_MAX_RESULTS,
    per_source: int = SEARCH_RESULTS_PER_SOURCE,
) -> list[WebSearchResult]:
    """Keep result order while avoiding one source crowding out the result set."""

    selected: list[WebSearchResult] = []
    deferred: list[WebSearchResult] = []
    counts_by_source: dict[tuple[str, str], int] = {}
    for result in results:
        parsed = urlsplit(result.url)
        hostname = (parsed.hostname or "").casefold()
        tenant = parsed.path.strip("/").partition("/")[0].casefold()
        source = (hostname, tenant)
        if hostname and counts_by_source.get(source, 0) >= per_source:
            deferred.append(result)
            continue
        selected.append(result)
        if hostname:
            counts_by_source[source] = counts_by_source.get(source, 0) + 1
        if len(selected) == limit:
            return selected

    selected.extend(deferred[: limit - len(selected)])
    return selected


class _PageTextParser(HTMLParser):
    """Collect visible semantic blocks while ignoring page chrome and scripts."""

    _BLOCK_TAGS = frozenset(
        {
            "blockquote",
            "dd",
            "dt",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "li",
            "p",
            "pre",
            "td",
        },
    )
    _BOUNDARY_TAGS = frozenset({"div", "section", "table", "tr"})
    _CHROME_TAGS = frozenset({"aside", "footer", "header", "nav"})

    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.blocks: list[_PageTextBlock] = []
        self._ignored_depth = 0
        self._in_title = False
        self._main_depth = 0
        self._article_depth = 0
        self._chrome_depth = 0
        self._tag = ""
        self._parts: list[str] = []
        self._block_in_main = False
        self._block_in_article = False
        self._block_in_chrome = False
        self._section = ""

    def _start_block(self, tag: str) -> None:
        self._flush_block()
        self._tag = tag
        self._block_in_main = self._main_depth > 0
        self._block_in_article = self._article_depth > 0
        self._block_in_chrome = self._chrome_depth > 0

    def _flush_block(self) -> None:
        text = _compact_text(" ".join(self._parts), 20_000)
        if text:
            block = _PageTextBlock(
                text=text,
                tag=self._tag or "text",
                section=self._section,
                in_main=self._block_in_main,
                in_article=self._block_in_article,
                in_chrome=self._block_in_chrome,
            )
            self.blocks.append(block)
            if block.tag.startswith("h"):
                self._section = block.text
        self._tag = ""
        self._parts = []

    def handle_starttag(
        self,
        tag: str,
        _attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth += 1
            return
        if tag == "title":
            self._in_title = True
            return
        if self._ignored_depth:
            return
        if tag == "main":
            self._flush_block()
            self._main_depth += 1
        elif tag == "article":
            self._flush_block()
            self._article_depth += 1
        elif tag in self._CHROME_TAGS:
            self._flush_block()
            self._chrome_depth += 1
        if tag in self._BLOCK_TAGS:
            self._start_block(tag)
        elif tag in self._BOUNDARY_TAGS:
            self._flush_block()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "noscript", "svg"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if tag == "title":
            self._in_title = False
            return
        if self._ignored_depth:
            return
        if (
            tag in self._BLOCK_TAGS
            or tag in self._BOUNDARY_TAGS
            or tag in {"main", "article"}
            or tag in self._CHROME_TAGS
        ):
            self._flush_block()
        if tag == "main":
            self._main_depth = max(0, self._main_depth - 1)
        elif tag == "article":
            self._article_depth = max(0, self._article_depth - 1)
        elif tag in self._CHROME_TAGS:
            self._chrome_depth = max(0, self._chrome_depth - 1)

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        elif not self._ignored_depth:
            if not self._parts:
                self._block_in_main = self._main_depth > 0
                self._block_in_article = self._article_depth > 0
                self._block_in_chrome = self._chrome_depth > 0
            self._parts.append(text)

    def close(self) -> None:
        super().close()
        self._flush_block()


class _JsonLdParser(HTMLParser):
    """Collect JSON-LD documents embedded in a page."""

    def __init__(self) -> None:
        super().__init__()
        self.documents: list[object] = []
        self._parts: list[str] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() != "script":
            return
        attributes = {name.casefold(): (value or "") for name, value in attrs}
        if attributes.get("type", "").casefold() == "application/ld+json":
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._parts is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() != "script" or self._parts is None:
            return
        raw = "".join(self._parts).strip()
        self._parts = None
        if not raw:
            return
        try:
            self.documents.append(json.loads(raw))
        except json.JSONDecodeError:
            return


def _job_posting(value: object) -> dict[str, object] | None:
    if isinstance(value, list):
        for item in value:
            if posting := _job_posting(item):
                return posting
        return None
    if not isinstance(value, dict):
        return None

    raw_types = value.get("@type")
    types = raw_types if isinstance(raw_types, list) else [raw_types]
    if any(isinstance(item, str) and item.casefold() == "jobposting" for item in types):
        return value
    for item in value.values():
        if posting := _job_posting(item):
            return posting
    return None


def _job_posting_dates(html: str) -> tuple[str, str]:
    parser = _JsonLdParser()
    parser.feed(html)
    for document in parser.documents:
        posting = _job_posting(document)
        if posting is None:
            continue
        published = posting.get("datePosted")
        valid_through = posting.get("validThrough")
        return (
            published.strip() if isinstance(published, str) else "",
            valid_through.strip() if isinstance(valid_through, str) else "",
        )
    return "", ""


def _expired_job_posting(valid_through: str) -> bool:
    if not valid_through:
        return False
    try:
        expires = datetime.fromisoformat(valid_through.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            expires = date.fromisoformat(valid_through)
        except ValueError:
            return False
    return expires < date.today()


def _relevance_terms(*values: str) -> frozenset[str]:
    terms: set[str] = set()
    for value in values:
        normalized = unescape(value).casefold()
        for match in re.finditer(r"[a-z0-9][a-z0-9.+#-]{1,}", normalized):
            token = match.group(0).rstrip(".-")
            if len(token) >= 2:
                terms.add(token)
        for sequence in re.findall(r"[\u3400-\u9fff]+", normalized):
            if len(sequence) == 1:
                terms.add(sequence)
            else:
                terms.update(
                    sequence[index : index + 2] for index in range(len(sequence) - 1)
                )
    return frozenset(terms)


def _content_relevance_terms(
    relevance_query: str,
    *fallbacks: str,
) -> frozenset[str]:
    for value in (relevance_query, *fallbacks):
        terms = frozenset(
            term for term in _relevance_terms(value) if not term.isdecimal()
        )
        if terms:
            return terms
    return frozenset()


def _excerpt_matches_context(
    excerpt: str,
    relevance_query: str,
    reference_title: str,
) -> bool:
    if not reference_title:
        return True
    expected = _content_relevance_terms(relevance_query, reference_title)
    if not expected:
        return True
    observed = _relevance_terms(excerpt)
    required_matches = 2 if len(expected) >= 4 else 1
    return len(expected & observed) >= required_matches


def _preferred_page_blocks(blocks: list[_PageTextBlock]) -> list[_PageTextBlock]:
    for candidates in (
        [block for block in blocks if block.in_article],
        [block for block in blocks if block.in_main],
        [block for block in blocks if not block.in_chrome],
        blocks,
    ):
        if _is_useful_excerpt(" ".join(block.text for block in candidates)):
            return candidates
    return []


def _split_page_passages(
    blocks: list[_PageTextBlock],
) -> list[_PageTextBlock]:
    passages: list[_PageTextBlock] = []
    for block in blocks:
        remaining = block.text
        while len(remaining) > PAGE_PASSAGE_MAX_CHARS:
            minimum = PAGE_PASSAGE_MAX_CHARS // 2
            split_at = max(
                remaining.rfind(separator, minimum, PAGE_PASSAGE_MAX_CHARS)
                for separator in ("。", "！", "？", ". ", "! ", "? ", "; ", "；")
            )
            if split_at < minimum:
                split_at = remaining.rfind(" ", minimum, PAGE_PASSAGE_MAX_CHARS)
            if split_at < minimum:
                split_at = PAGE_PASSAGE_MAX_CHARS
            elif remaining[split_at : split_at + 2] in {". ", "! ", "? ", "; "}:
                split_at += 1
            else:
                split_at += 1
            text = remaining[:split_at].strip()
            if text:
                passages.append(
                    _PageTextBlock(
                        text=text,
                        tag=block.tag,
                        section=block.section,
                        in_main=block.in_main,
                        in_article=block.in_article,
                        in_chrome=block.in_chrome,
                    ),
                )
            remaining = remaining[split_at:].strip()
        if remaining:
            passages.append(
                _PageTextBlock(
                    text=remaining,
                    tag=block.tag,
                    section=block.section,
                    in_main=block.in_main,
                    in_article=block.in_article,
                    in_chrome=block.in_chrome,
                ),
            )
    return passages


def _select_page_excerpt(
    blocks: list[_PageTextBlock],
    *,
    relevance_query: str,
    reference_title: str,
    page_title: str,
) -> str:
    preferred = _preferred_page_blocks(blocks)
    split_long_block = any(
        len(block.text) > PAGE_PASSAGE_MAX_CHARS for block in preferred
    )
    candidates = _split_page_passages(preferred)
    if not candidates:
        return ""
    terms = _content_relevance_terms(
        relevance_query if reference_title else "",
        reference_title,
        page_title,
    )

    def score(block: _PageTextBlock) -> int:
        text = block.text.casefold()
        section = block.section.casefold()
        return sum(3 for term in terms if term in text) + sum(
            2 for term in terms if term in section
        )

    substantial_indexes = [
        index
        for index, candidate in enumerate(candidates)
        if len(candidate.text) >= MIN_USEFUL_EXCERPT_CHARS
    ]
    best_index = max(
        substantial_indexes or range(len(candidates)),
        key=lambda index: (
            score(candidates[index]),
            min(len(candidates[index].text), PAGE_PASSAGE_MAX_CHARS),
        ),
    )
    if split_long_block:
        return _compact_text(candidates[best_index].text, FETCH_EXCERPT_MAX_CHARS)
    return _compact_text(
        " ".join(candidate.text for candidate in candidates[best_index:]),
        FETCH_EXCERPT_MAX_CHARS,
    )


def _select_page_passages(
    blocks: list[_PageTextBlock],
    *,
    relevance_query: str,
    reference_title: str,
    page_title: str,
) -> tuple[WebPassage, ...]:
    preferred = _preferred_page_blocks(blocks)
    split_long_block = any(
        len(block.text) > PAGE_PASSAGE_MAX_CHARS for block in preferred
    )
    candidates = [
        block
        for block in _split_page_passages(preferred)
        if not block.tag.startswith("h") and _is_useful_excerpt(block.text)
    ]
    if not candidates:
        return ()

    terms = _content_relevance_terms(
        relevance_query if reference_title else "",
        reference_title,
        page_title,
    )

    def score(block: _PageTextBlock) -> int:
        text = block.text.casefold()
        section = block.section.casefold()
        return sum(3 for term in terms if term in text) + sum(
            2 for term in terms if term in section
        )

    ranked = sorted(
        range(len(candidates)),
        key=lambda index: (score(candidates[index]), len(candidates[index].text)),
        reverse=True,
    )
    selected: list[int] = []
    selected_sections: set[str] = set()
    for index in ranked:
        block = candidates[index]
        section = block.section.strip().casefold()
        if terms and score(block) == 0:
            continue
        if section and section in selected_sections:
            continue
        selected.append(index)
        if section:
            selected_sections.add(section)
        if len(selected) >= WEB_REFERENCE_MAX_PASSAGES:
            break

    if selected and not split_long_block:
        for index in range(min(selected), len(candidates)):
            if index in selected:
                continue
            selected.append(index)
            if len(selected) >= WEB_REFERENCE_MAX_PASSAGES:
                break

    for index in ranked:
        if index in selected or (terms and score(candidates[index]) == 0):
            continue
        selected.append(index)
        if len(selected) >= WEB_REFERENCE_MAX_PASSAGES:
            break

    if not selected:
        selected.append(ranked[0])
    return tuple(
        WebPassage(
            section=candidates[index].section.strip() or page_title,
            text=candidates[index].text,
        )
        for index in sorted(selected)
    )


def _web_reference_from_response(
    url: str,
    raw: bytes,
    content_type: str,
    charset: str,
    *,
    relevance_query: str = "",
    reference_title: str = "",
) -> WebReference | None:
    media_type = content_type.partition(";")[0].strip().casefold()
    if media_type and not (
        media_type.startswith("text/")
        or media_type.endswith("+json")
        or media_type in {"application/json", "application/ld+json"}
    ):
        return None

    decoded = raw.decode(charset, errors="replace")
    if media_type not in {"", "application/xhtml+xml", "text/html"}:
        excerpt = _compact_text(decoded, FETCH_EXCERPT_MAX_CHARS)
        if not _is_useful_excerpt(excerpt):
            return None
        return WebReference(
            title=reference_title or url,
            excerpt=excerpt,
            final_url=url,
            passages=(WebPassage(section=reference_title or url, text=excerpt),),
        )

    published_date, valid_through = _job_posting_dates(decoded)
    if _expired_job_posting(valid_through):
        return None

    parser = _PageTextParser()
    parser.feed(decoded)
    parser.close()
    title = _compact_text(" ".join(parser.title_parts), 120)
    excerpt = _select_page_excerpt(
        parser.blocks,
        relevance_query=relevance_query,
        reference_title=reference_title,
        page_title=title,
    )
    passages = _select_page_passages(
        parser.blocks,
        relevance_query=relevance_query,
        reference_title=reference_title,
        page_title=title,
    )
    if not _is_useful_excerpt(excerpt) or not _excerpt_matches_context(
        excerpt,
        relevance_query,
        reference_title,
    ):
        return None
    return WebReference(
        title=title or reference_title or url,
        excerpt=excerpt,
        final_url=url,
        published_date=published_date,
        valid_through=valid_through,
        passages=passages,
    )


def _normalized_search_domains(domains: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for value in domains:
        candidate = value.strip().casefold().rstrip(".")
        canonical = _canonical_web_url(f"https://{candidate}")
        hostname = (urlsplit(canonical).hostname or "").casefold()
        if hostname == candidate and hostname not in normalized:
            normalized.append(hostname)
    return tuple(normalized)


def _scoped_search_query(query: str, domains: tuple[str, ...]) -> str:
    if not domains:
        return query
    sites = " OR ".join(f"site:{domain}" for domain in domains)
    return f"{query} ({sites})"


def _matches_search_domains(url: str, domains: tuple[str, ...]) -> bool:
    if not domains:
        return True
    hostname = (urlsplit(url).hostname or "").casefold()
    return any(
        hostname == domain or hostname.endswith(f".{domain}") for domain in domains
    )


def _duckduckgo_region(query: str) -> str:
    return "cn-zh" if re.search(r"[\u3400-\u9fff]", query) else "wt-wt"


async def _async_fetch_with_client(
    client: httpx.AsyncClient,
    url: str,
    relevance_query: str,
    reference_title: str,
) -> WebReference | None:
    fetched = await _async_get_bounded_web_response(client, url, FETCH_MAX_BYTES)
    if fetched is None or not 200 <= fetched.status_code < 300:
        return None
    return _web_reference_from_response(
        fetched.final_url,
        fetched.raw,
        fetched.content_type,
        fetched.charset,
        relevance_query=relevance_query,
        reference_title=reference_title,
    )


async def _async_search_web(
    query: str,
    time_range: str | None = None,
    include_domains: tuple[str, ...] = (),
    browser: WebBrowser | None = None,
) -> WebSearchResponse:
    """Discover public pages with DuckDuckGo and read the top results locally."""

    results: list[WebSearchResult] = []
    domains = _normalized_search_domains(include_domains)
    form = {
        "q": _scoped_search_query(query, domains),
        "kl": _duckduckgo_region(query),
        "kd": "-1",
    }
    if time_range in TIME_RANGE_VALUES:
        form["df"] = TIME_RANGE_VALUES[time_range]
    try:
        async with asyncio.timeout(SEARCH_TIMEOUT_SECONDS):
            async with httpx.AsyncClient(
                headers={
                    "Accept": "text/html,*/*;q=0.8",
                    "Accept-Language": WEB_ACCEPT_LANGUAGE,
                    "User-Agent": WEB_USER_AGENT,
                },
                follow_redirects=False,
                timeout=SEARCH_TIMEOUT_SECONDS,
                trust_env=False,
            ) as client:
                search_page = await _async_get_bounded_web_response(
                    client,
                    DUCKDUCKGO_SEARCH_URL,
                    SEARCH_MAX_BYTES,
                    method="POST",
                    data=form,
                )
                if search_page is None:
                    return WebSearchResponse(error_reason="temporarily_unavailable")
                lowered = search_page.raw.lower()
                if search_page.status_code in {202, 403, 429} or any(
                    marker in lowered for marker in DUCKDUCKGO_CHALLENGE_MARKERS
                ):
                    return WebSearchResponse(error_reason="rate_limited")
                if not 200 <= search_page.status_code < 300:
                    return WebSearchResponse(error_reason="temporarily_unavailable")

                discovered = _select_search_results(
                    [
                        result
                        for result in _parse_duckduckgo_results(
                            search_page.raw,
                            search_page.charset,
                        )
                        if _matches_search_domains(result.url, domains)
                    ],
                )
                results = list(discovered)

                async def read_static(
                    result: WebSearchResult,
                ) -> WebReference | None:
                    try:
                        async with asyncio.timeout(PAGE_HTTP_TIMEOUT_SECONDS):
                            reference = await _async_fetch_with_client(
                                client,
                                result.url,
                                query,
                                result.title,
                            )
                    except (TimeoutError, httpx.HTTPError):
                        return None
                    if reference is None or not _reference_matches_result(
                        result,
                        reference,
                        query,
                    ):
                        return None
                    return reference

                read_candidates = discovered[:SEARCH_READ_RESULTS]
                static_references = await asyncio.gather(
                    *(read_static(result) for result in read_candidates),
                )

                def promote(
                    result: WebSearchResult,
                    reference: WebReference | None,
                ) -> WebSearchResult:
                    if reference is None or not _reference_matches_result(
                        result,
                        reference,
                        query,
                    ):
                        return result
                    return WebSearchResult(
                        url=reference.final_url or result.url,
                        title=result.title,
                        excerpt=reference.excerpt,
                        published_date=(
                            reference.published_date or result.published_date
                        ),
                        valid_through=reference.valid_through,
                        source_kind="fetched_page",
                        passages=reference.passages,
                    )

                def promote_references(
                    references: list[WebReference | None],
                ) -> list[WebSearchResult]:
                    promoted = 0
                    read_results: list[WebSearchResult] = []
                    for result, reference in zip(
                        read_candidates,
                        references,
                        strict=True,
                    ):
                        if promoted >= SEARCH_TARGET_REFERENCES:
                            read_results.append(result)
                            continue
                        resolved = promote(result, reference)
                        read_results.append(resolved)
                        if resolved.source_kind == "fetched_page":
                            promoted += 1
                    return read_results

                read_results = promote_references(static_references)
                results = [*read_results, *discovered[SEARCH_READ_RESULTS:]]

                if (
                    sum(reference is not None for reference in static_references)
                    < SEARCH_TARGET_REFERENCES
                ):
                    render_candidates = _select_search_results(
                        [
                            result
                            for result, reference in zip(
                                read_candidates,
                                static_references,
                                strict=True,
                            )
                            if reference is None
                        ],
                        limit=SEARCH_BROWSER_READ_RESULTS,
                        per_source=1,
                    )
                    render_requests = [
                        (result.url, query, result.title)
                        for result in render_candidates
                    ]
                    rendered_references = await _async_render_web_references(
                        render_requests,
                        browser,
                    )
                    read_results = promote_references(
                        [
                            reference or rendered_references.get(result.url)
                            for result, reference in zip(
                                read_candidates,
                                static_references,
                                strict=True,
                            )
                        ],
                    )
                    results = [*read_results, *discovered[SEARCH_READ_RESULTS:]]
    except TimeoutError:
        if results:
            return WebSearchResponse(results=tuple(results))
        return WebSearchResponse(error_reason="temporarily_unavailable")
    except (httpx.HTTPError, TypeError, ValueError):
        return WebSearchResponse(error_reason="temporarily_unavailable")

    return WebSearchResponse(results=tuple(results))


def _is_useful_excerpt(value: str) -> bool:
    text = _compact_text(value, 1_000).casefold()
    return len(text) >= MIN_USEFUL_EXCERPT_CHARS and not any(
        marker in text for marker in BLOCKED_EXCERPT_MARKERS
    )


def _reference_matches_result(
    result: WebSearchResult,
    reference: WebReference,
    relevance_query: str = "",
) -> bool:
    if not _preserves_specific_page(result.url, reference.final_url):
        return False
    expected = _relevance_terms(result.title, result.excerpt)
    observed = _relevance_terms(reference.title, reference.excerpt)
    content_terms = _content_relevance_terms(
        relevance_query,
        result.excerpt,
        result.title,
    )
    content_matches = len(content_terms & _relevance_terms(reference.excerpt))
    required_content_matches = 2 if len(content_terms) >= 4 else 1
    return (
        bool(expected)
        and len(expected & observed) * 5 >= len(expected)
        and content_matches >= required_content_matches
    )


def _preserves_specific_page(requested_url: str, final_url: str) -> bool:
    """Reject a job-page redirect that collapses to a generic site homepage."""

    requested = urlsplit(_canonical_web_url(requested_url))
    final = urlsplit(_canonical_web_url(final_url))
    requested_is_specific = requested.path.rstrip("/") != "" or bool(
        requested.query,
    )
    final_is_specific = final.path.rstrip("/") != "" or bool(final.query)
    return not requested_is_specific or final_is_specific


def _web_reference_from_visible_text(
    url: str,
    title: str,
    text: str,
    *,
    relevance_query: str,
    reference_title: str,
) -> WebReference | None:
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        line = _compact_text(raw_line, FETCH_EXCERPT_MAX_CHARS)
        key = line.casefold()
        if not line or key in seen:
            continue
        seen.add(key)
        lines.append(line)
    if not lines:
        return None

    terms = _content_relevance_terms(
        relevance_query if reference_title else "",
        reference_title,
        title,
    )
    substantial_indexes = [
        index
        for index, line in enumerate(lines)
        if len(line) >= MIN_USEFUL_EXCERPT_CHARS
    ]
    start = max(
        substantial_indexes or range(len(lines)),
        key=lambda index: (
            sum(1 for term in terms if term in lines[index].casefold()),
            min(len(lines[index]), PAGE_PASSAGE_MAX_CHARS),
        ),
    )
    selected = lines[start:]
    excerpt = _compact_text(" ".join(selected), FETCH_EXCERPT_MAX_CHARS)
    if not _is_useful_excerpt(excerpt) or not _excerpt_matches_context(
        excerpt,
        relevance_query,
        reference_title,
    ):
        return None
    page_title = _compact_text(title, 120) or reference_title or url
    passages = _select_page_passages(
        [
            _PageTextBlock(
                text=line,
                tag="text",
                section=page_title,
                in_main=True,
                in_article=False,
                in_chrome=False,
            )
            for line in selected
        ],
        relevance_query=relevance_query,
        reference_title=reference_title,
        page_title=page_title,
    )
    return WebReference(
        title=page_title,
        excerpt=excerpt,
        final_url=url,
        passages=passages,
    )


async def _async_render_web_references(
    requests: list[tuple[str, str, str]],
    browser: WebBrowser | None = None,
) -> dict[str, WebReference]:
    if not requests:
        return {}

    session = browser or WebBrowser()
    owns_session = browser is None
    try:
        context = await session.context()

        async def render(
            requested_url: str,
            relevance_query: str,
            reference_title: str,
        ) -> tuple[str, WebReference | None]:
            page = await context.new_page()

            async def route_request(route: Route) -> None:
                request = route.request
                if request.resource_type in {"font", "image", "media"}:
                    await route.abort()
                    return
                target = request.url
                scheme = urlsplit(target).scheme.casefold()
                if scheme in {"about", "blob", "data"}:
                    await route.continue_()
                    return
                canonical = _canonical_web_url(target)
                if not canonical:
                    await route.abort()
                    return
                parsed = urlsplit(canonical)
                target_key = f"{parsed.scheme}://{parsed.netloc}"
                approved = session._approved_targets.get(target_key)
                if approved is None:
                    approved = (
                        await asyncio.to_thread(
                            _safe_web_target_addresses,
                            canonical,
                        )
                        is not None
                    )
                    session._approved_targets[target_key] = approved
                if approved:
                    await route.continue_()
                else:
                    await route.abort()

            await page.route("**/*", route_request)
            try:
                response = await page.goto(
                    requested_url,
                    wait_until="domcontentloaded",
                    timeout=6_000,
                )
                if response is not None and response.status >= 400:
                    return requested_url, None
                try:
                    await page.wait_for_function(
                        "document.body && document.body.innerText.length >= 200",
                        timeout=DYNAMIC_CONTENT_TIMEOUT_MS,
                    )
                except PlaywrightTimeoutError:
                    pass
                final_url = _canonical_web_url(page.url)
                if not final_url or not _is_public_reference_url(final_url):
                    return requested_url, None
                title, visible_text, json_ld = await asyncio.gather(
                    page.title(),
                    page.locator("body").inner_text(timeout=1_000),
                    page.locator(
                        'script[type="application/ld+json"]',
                    ).all_text_contents(),
                )
                reference = _web_reference_from_visible_text(
                    final_url,
                    title,
                    visible_text,
                    relevance_query=relevance_query,
                    reference_title=reference_title,
                )
                if reference is None:
                    return requested_url, None
                metadata_html = "".join(
                    f'<script type="application/ld+json">{item}</script>'
                    for item in json_ld
                )
                published_date, valid_through = _job_posting_dates(metadata_html)
                if _expired_job_posting(valid_through):
                    return requested_url, None
                return requested_url, WebReference(
                    title=reference.title,
                    excerpt=reference.excerpt,
                    final_url=reference.final_url,
                    published_date=published_date,
                    valid_through=valid_through,
                    passages=reference.passages,
                )
            except (PlaywrightError, PlaywrightTimeoutError):
                return requested_url, None
            finally:
                await page.close()

        rendered = await asyncio.gather(*(render(*request) for request in requests))
    except (PlaywrightError, PlaywrightTimeoutError):
        return {}
    finally:
        if owns_session:
            await session.close()

    return {
        requested_url: reference
        for requested_url, reference in rendered
        if reference is not None
    }


async def _async_fetch_web_reference(
    url: str,
    relevance_query: str = "",
    reference_title: str = "",
    browser: WebBrowser | None = None,
    *,
    timeout: float = FETCH_TIMEOUT_SECONDS,
) -> WebReference | None:
    """Download one public page and extract query-relevant visible text."""

    requested_url = _canonical_web_url(url)
    if not requested_url or not _is_public_reference_url(requested_url):
        return None

    bounded_timeout = min(max(timeout, 0.1), FETCH_TIMEOUT_SECONDS)
    try:
        async with asyncio.timeout(bounded_timeout):
            async with httpx.AsyncClient(
                headers={
                    "Accept": "text/html,text/plain;q=0.9,*/*;q=0.8",
                    "Accept-Language": WEB_ACCEPT_LANGUAGE,
                    "User-Agent": WEB_USER_AGENT,
                },
                follow_redirects=False,
                timeout=bounded_timeout,
                trust_env=False,
            ) as client:
                try:
                    async with asyncio.timeout(
                        min(PAGE_HTTP_TIMEOUT_SECONDS, bounded_timeout),
                    ):
                        reference = await _async_fetch_with_client(
                            client,
                            requested_url,
                            relevance_query,
                            reference_title,
                        )
                except (TimeoutError, httpx.HTTPError):
                    reference = None
            if reference is None:
                rendered = await _async_render_web_references(
                    [(requested_url, relevance_query, reference_title)],
                    browser,
                )
                reference = rendered.get(requested_url)
    except (
        TimeoutError,
        httpx.HTTPError,
        TypeError,
        ValueError,
    ):
        return None

    if reference is not None and not _preserves_specific_page(
        requested_url,
        reference.final_url,
    ):
        return None
    return reference


__all__ = [
    "FETCH_TIMEOUT_SECONDS",
    "SEARCH_TIMEOUT_SECONDS",
    "WebReference",
    "WebPassage",
    "WebSearchResponse",
    "WebSearchResult",
]
