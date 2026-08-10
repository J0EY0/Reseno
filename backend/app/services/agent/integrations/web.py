import asyncio
import ipaddress
import re
import socket
from collections.abc import AsyncIterable, Iterable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
from typing import Literal
from urllib.parse import (
    parse_qs,
    parse_qsl,
    quote_plus,
    unquote,
    urlencode,
    urljoin,
    urlparse,
    urlsplit,
    urlunsplit,
)
from xml.etree.ElementTree import ParseError, fromstring

import httpx

from ..parsing_patterns import agent_patterns

URL_PATTERN = re.compile(r"https?://[^\s)>\"]+")
WEB_USER_AGENT = "Mozilla/5.0 (compatible; ResuMate/1.0)"
WEB_ACCEPT_LANGUAGE = "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7"
FETCH_MAX_BYTES = 220_000
SEARCH_MAX_BYTES = 240_000
SearchResponseFormat = Literal["html", "rss"]
SEARCH_PROVIDERS: tuple[tuple[str, SearchResponseFormat], ...] = (
    ("https://html.duckduckgo.com/html/?q={query}", "html"),
    ("https://www.bing.com/search?format=rss&q={query}", "rss"),
)
MAX_WEB_SEARCH_QUERIES = 5
MAX_WEB_SEARCH_RESULTS = 10
WEB_SEARCH_MAX_CONCURRENCY = 3
WEB_SEARCH_OPERATION_TIMEOUT_SECONDS = 12.0
MAX_WEB_REDIRECTS = 5
TEXTUAL_APPLICATION_MEDIA_TYPES = frozenset(
    {
        "application/json",
        "application/ld+json",
        "application/xhtml+xml",
        "application/xml",
    },
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
SEARCH_AGGREGATOR_HOST_SUFFIXES = (
    "glassdoor.com",
    "indeed.com",
    "linkedin.com",
    "monster.com",
    "ziprecruiter.com",
)
OFFICIAL_CAREER_HOST_PREFIXES = ("careers.", "jobs.")
OFFICIAL_CAREER_PATH_SEGMENTS = frozenset(
    {"career", "careers", "job", "jobs", "join-us", "openings", "positions"},
)
SEARCH_RESULT_YEAR_PATTERN = re.compile(r"(?<!\d)(20\d{2})(?!\d)")


@dataclass(frozen=True)
class WebReference:
    """Text plus non-sensitive provenance from a fetched webpage."""

    title: str
    excerpt: str
    final_url: str = ""
    status_code: int | None = None
    fetched_at: str = ""
    content_sha256: str = ""
    excerpt_start: int = 0
    excerpt_end: int = 0
    excerpt_section: str = ""


@dataclass(frozen=True)
class WebSearchResult:
    """One search result, with an explicit distinction between snippet and page text."""

    title: str
    url: str
    excerpt: str
    source_kind: Literal["fetched_page", "search_snippet"] = "search_snippet"
    final_url: str = ""
    status_code: int | None = None
    fetched_at: str = ""
    content_sha256: str = ""
    excerpt_start: int = 0
    excerpt_end: int = 0
    excerpt_section: str = ""


@dataclass(frozen=True)
class WebSearchReference:
    """Aggregated web search context across one or more queries."""

    query: str
    results: tuple[WebSearchResult, ...]
    query_count: int
    result_count: int
    error: str | None = None
    timed_out: bool = False
    partial: bool = False

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


@dataclass(frozen=True)
class _AsyncQuerySearchState:
    """Completed search-link state recorded before page fetches finish."""

    results: tuple[WebSearchResult, ...]
    result_count: int
    error: str | None


@dataclass(frozen=True)
class _SearchCandidate:
    """A canonical result plus the query/rank signals used for fair selection."""

    result: WebSearchResult
    query_index: int
    result_index: int
    sequence: int


@dataclass(frozen=True)
class _PageTextBlock:
    """One visible semantic block with enough structure for excerpt selection."""

    text: str
    tag: str
    section: str
    in_main: bool
    in_article: bool
    in_chrome: bool


@dataclass(frozen=True)
class _SelectedExcerpt:
    """A normalized excerpt and its character range inside the selected page scope."""

    text: str
    start: int
    end: int
    section: str


class _RelevantWebUrl(str):
    """A URL carrying ranking hints while preserving the one-argument fetch seam."""

    relevance_query: str
    reference_title: str

    def __new__(
        cls,
        url: str,
        *,
        relevance_query: str,
        reference_title: str,
    ) -> "_RelevantWebUrl":
        instance = super().__new__(cls, url)
        instance.relevance_query = relevance_query
        instance.reference_title = reference_title
        return instance


def _relevant_web_url(
    url: str,
    *,
    relevance_query: str,
    reference_title: str,
) -> str:
    """Attach excerpt-ranking context without changing replaceable fetch call shapes."""

    return _RelevantWebUrl(
        url,
        relevance_query=relevance_query,
        reference_title=reference_title,
    )


def _canonical_web_url(url: str) -> str:
    """Normalize a public result URL and remove non-semantic tracking fields."""

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

    if ":" in hostname:
        hostname = f"[{hostname}]"
    default_port = 443 if scheme == "https" else 80
    netloc = hostname if port in {None, default_port} else f"{hostname}:{port}"

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
        return _canonical_web_url(candidate)

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
    """Extract visible semantic blocks while retaining coarse page structure."""

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
        },
    )
    _BOUNDARY_TAGS = frozenset({"div", "section", "table", "tr"})
    _CHROME_TAGS = frozenset({"aside", "footer", "header", "nav"})

    def __init__(self) -> None:
        super().__init__()
        self._ignored_depth = 0
        self._in_title = False
        self._main_depth = 0
        self._article_depth = 0
        self._chrome_depth = 0
        self._block_tag = ""
        self._block_parts: list[str] = []
        self._block_in_main = False
        self._block_in_article = False
        self._block_in_chrome = False
        self._current_section = ""
        self.title_parts: list[str] = []
        self.blocks: list[_PageTextBlock] = []

    @property
    def text_parts(self) -> list[str]:
        """Preserve the previous visible-text view for internal compatibility."""

        return [block.text for block in self.blocks]

    def _start_block(self, tag: str) -> None:
        self._flush_block()
        self._block_tag = tag
        self._block_in_main = self._main_depth > 0
        self._block_in_article = self._article_depth > 0
        self._block_in_chrome = self._chrome_depth > 0

    def _flush_block(self) -> None:
        text = _compact_text(" ".join(self._block_parts), limit=20_000)
        if text:
            block = _PageTextBlock(
                text=text,
                tag=self._block_tag or "text",
                section=self._current_section,
                in_main=self._block_in_main,
                in_article=self._block_in_article,
                in_chrome=self._block_in_chrome,
            )
            self.blocks.append(block)
            if block.tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                self._current_section = block.text

        self._block_tag = ""
        self._block_parts = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        """Track elements that should not contribute visible text."""

        normalized_tag = tag.lower()
        if normalized_tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
            return
        if normalized_tag == "title":
            self._in_title = True
            return
        if self._ignored_depth:
            return

        if normalized_tag == "main":
            self._flush_block()
            self._main_depth += 1
        elif normalized_tag == "article":
            self._flush_block()
            self._article_depth += 1
        elif normalized_tag in self._CHROME_TAGS:
            self._flush_block()
            self._chrome_depth += 1

        if normalized_tag in self._BLOCK_TAGS:
            self._start_block(normalized_tag)
        elif normalized_tag in self._BOUNDARY_TAGS:
            self._flush_block()

    def handle_endtag(self, tag: str) -> None:
        """Close ignored and title elements."""

        normalized_tag = tag.lower()
        if normalized_tag in {"script", "style", "noscript"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if normalized_tag == "title":
            self._in_title = False
            return
        if self._ignored_depth:
            return

        if (
            normalized_tag in self._BLOCK_TAGS
            or normalized_tag in self._BOUNDARY_TAGS
            or normalized_tag in {"main", "article"}
            or normalized_tag in self._CHROME_TAGS
        ):
            self._flush_block()

        if normalized_tag == "main":
            self._main_depth = max(0, self._main_depth - 1)
        elif normalized_tag == "article":
            self._article_depth = max(0, self._article_depth - 1)
        elif normalized_tag in self._CHROME_TAGS:
            self._chrome_depth = max(0, self._chrome_depth - 1)

    def handle_data(self, data: str) -> None:
        """Collect visible text and page title fragments."""

        text = data.strip()
        if not text:
            return

        if self._in_title:
            self.title_parts.append(text)
            return

        if self._ignored_depth == 0:
            if not self._block_parts:
                self._block_in_main = self._main_depth > 0
                self._block_in_article = self._article_depth > 0
                self._block_in_chrome = self._chrome_depth > 0
            self._block_parts.append(text)

    def close(self) -> None:
        """Flush trailing text after HTMLParser completes."""

        super().close()
        self._flush_block()


def _compact_text(value: str, limit: int = 700) -> str:
    """Collapse whitespace and trim text for prompts and citations."""

    return re.sub(r"\s+", " ", unescape(value)).strip()[:limit]


def _relevance_terms(*values: str) -> frozenset[str]:
    """Build language-agnostic terms without maintaining a domain keyword list."""

    terms: set[str] = set()
    for value in values:
        normalized = unescape(value).casefold()
        terms.update(
            match.group(0)
            for match in re.finditer(r"[a-z0-9][a-z0-9.+#-]{1,}", normalized)
        )
        for sequence in re.findall(r"[\u3400-\u9fff]+", normalized):
            if len(sequence) == 1:
                terms.add(sequence)
                continue
            terms.update(
                sequence[index : index + 2] for index in range(len(sequence) - 1)
            )
    return frozenset(terms)


def _preferred_page_blocks(blocks: list[_PageTextBlock]) -> list[_PageTextBlock]:
    """Prefer semantic document regions, falling back only when they are absent."""

    for candidates in (
        [block for block in blocks if block.in_article],
        [block for block in blocks if block.in_main],
        [block for block in blocks if not block.in_chrome],
        blocks,
    ):
        if _is_useful_web_excerpt(" ".join(block.text for block in candidates)):
            return candidates
    return []


def _block_relevance_score(
    block: _PageTextBlock,
    terms: frozenset[str],
) -> int:
    if not terms:
        return 0

    text = block.text.casefold()
    section = block.section.casefold()
    text_matches = sum(1 for term in terms if term in text)
    section_matches = sum(1 for term in terms if term in section)
    heading_bonus = 1 if block.tag.startswith("h") and text_matches else 0
    return text_matches * 3 + section_matches * 2 + heading_bonus


def _select_page_excerpt(
    blocks: list[_PageTextBlock],
    *,
    relevance_query: str,
    reference_title: str,
    page_title: str,
    limit: int = 700,
) -> _SelectedExcerpt | None:
    """Select a contiguous relevant window and expose its normalized char range."""

    candidates = _preferred_page_blocks(blocks)
    if not candidates:
        return None

    terms = _relevance_terms(relevance_query, reference_title, page_title)
    scores = [_block_relevance_score(block, terms) for block in candidates]
    best_index = max(range(len(candidates)), key=scores.__getitem__) if scores else 0

    start_index = best_index
    end_index = best_index
    selected_length = len(candidates[best_index].text)
    if best_index > 0 and candidates[best_index - 1].tag.startswith("h"):
        heading_length = len(candidates[best_index - 1].text) + 1
        if selected_length + heading_length <= limit:
            start_index -= 1
            selected_length += heading_length

    # Keep the excerpt contiguous so start/end remain directly explainable.
    while end_index + 1 < len(candidates):
        next_length = len(candidates[end_index + 1].text) + 1
        if selected_length + next_length > limit:
            break
        end_index += 1
        selected_length += next_length

    while start_index > 0:
        previous_length = len(candidates[start_index - 1].text) + 1
        if selected_length + previous_length > limit:
            break
        start_index -= 1
        selected_length += previous_length

    offsets: list[int] = []
    offset = 0
    for block in candidates:
        offsets.append(offset)
        offset += len(block.text) + 1

    excerpt = _compact_text(
        " ".join(block.text for block in candidates[start_index : end_index + 1]),
        limit=limit,
    )
    excerpt_start = offsets[start_index]
    selected_block = candidates[best_index]
    section = (
        selected_block.text
        if selected_block.tag.startswith("h")
        else selected_block.section
    )
    return _SelectedExcerpt(
        text=excerpt,
        start=excerpt_start,
        end=excerpt_start + len(excerpt),
        section=section,
    )


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


def _is_tun_fake_ip_address(value: str) -> bool:
    """Recognize the RFC 2544 range used by Clash-compatible fake-IP DNS."""

    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return address.version == 4 and address in TUN_FAKE_IP_NETWORK


def _is_safe_resolved_address(value: str) -> bool:
    """Allow public peers and a DNS-only TUN fake-IP transport address."""

    return _is_public_ip_address(value) or _is_tun_fake_ip_address(value)


def _safe_web_target_addresses(url: str) -> frozenset[str] | None:
    """Resolve a URL into peer addresses approved for this exact request."""

    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").rstrip(".").lower()
        # Reading ``port`` also rejects malformed or out-of-range port values.
        _ = parsed.port
    except ValueError:
        return None

    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or hostname == "localhost"
        or hostname.endswith(".localhost")
        or hostname in BLOCKED_WEB_HOSTS
    ):
        return None

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
            return None

        resolved_addresses = frozenset(
            str(sockaddr[0]) for *_, sockaddr in address_info
        )
        if not resolved_addresses or not all(
            _is_safe_resolved_address(address) for address in resolved_addresses
        ):
            return None
        return resolved_addresses

    if not _is_public_ip_address(hostname):
        return None
    return frozenset({hostname})


def _has_safe_connected_peer(
    response: httpx.Response,
    resolved_addresses: frozenset[str],
) -> bool:
    """Verify the peer, binding non-public fake-IP use to the DNS preflight."""

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

    if not isinstance(peer_address, str):
        return False
    if _is_public_ip_address(peer_address):
        return True
    return peer_address in resolved_addresses and _is_tun_fake_ip_address(peer_address)


def _web_reference_from_response(
    url: str,
    raw: bytes,
    content_type: str,
    charset: str,
    *,
    status_code: int,
    fetched_at: str,
    content_sha256: str,
    relevance_query: str = "",
    reference_title: str = "",
) -> WebReference | None:
    """Parse fetched response bytes into a web reference."""

    media_type = content_type.partition(";")[0].strip().lower()
    is_textual = (
        media_type.startswith("text/")
        or media_type in TEXTUAL_APPLICATION_MEDIA_TYPES
        or media_type.endswith(("+json", "+xml"))
    )
    # Binary formats require a format-aware parser. Decoding arbitrary bytes
    # with the advertised charset can manufacture plausible but invalid text.
    if not is_textual:
        return None

    decoded = raw.decode(charset, errors="replace")
    if media_type not in {"application/xhtml+xml", "text/html"}:
        excerpt = _compact_text(decoded)
        return (
            WebReference(
                title=url,
                excerpt=excerpt,
                final_url=url,
                status_code=status_code,
                fetched_at=fetched_at,
                content_sha256=content_sha256,
                excerpt_start=0,
                excerpt_end=len(excerpt),
            )
            if _is_useful_web_excerpt(excerpt)
            else None
        )

    parser = PageTextParser()
    parser.feed(decoded)
    parser.close()
    title = _compact_text(" ".join(parser.title_parts), limit=120)
    selected = _select_page_excerpt(
        parser.blocks,
        relevance_query=relevance_query,
        reference_title=reference_title,
        page_title=title,
    )
    if selected is None or not _is_useful_web_excerpt(selected.text):
        return None

    return WebReference(
        title=title or url,
        excerpt=selected.text,
        final_url=url,
        status_code=status_code,
        fetched_at=fetched_at,
        content_sha256=content_sha256,
        excerpt_start=selected.start,
        excerpt_end=selected.end,
        excerpt_section=selected.section,
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
        resolved_addresses = _safe_web_target_addresses(current_url)
        if resolved_addresses is None:
            return None

        with client.stream("GET", current_url) as response:
            if not _has_safe_connected_peer(response, resolved_addresses):
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
        resolved_addresses = await asyncio.to_thread(
            _safe_web_target_addresses,
            current_url,
        )
        if resolved_addresses is None:
            return None

        async with client.stream("GET", current_url) as response:
            if not _has_safe_connected_peer(response, resolved_addresses):
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


def _fetch_web_reference(
    url: str,
    timeout: float = 4.0,
    *,
    relevance_query: str = "",
    reference_title: str = "",
) -> WebReference | None:
    """Fetch a URL and return visible text that can be cited."""

    if isinstance(url, _RelevantWebUrl):
        relevance_query = relevance_query or url.relevance_query
        reference_title = reference_title or url.reference_title
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
        relevance_query=relevance_query,
        reference_title=reference_title,
    )


async def _async_fetch_web_reference(
    url: str,
    timeout: float = 4.0,
    *,
    relevance_query: str = "",
    reference_title: str = "",
) -> WebReference | None:
    """Fetch a URL with an async HTTP client and return visible citation text."""

    if isinstance(url, _RelevantWebUrl):
        relevance_query = relevance_query or url.relevance_query
        reference_title = reference_title or url.reference_title
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
        relevance_query=relevance_query,
        reference_title=reference_title,
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
        for search_url, response_format in _search_requests(query):
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

            results, parse_error = _parse_provider_search_results(
                fetched.raw,
                fetched.charset,
                response_format,
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
        for search_url, response_format in _search_requests(query):
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

            results, parse_error = _parse_provider_search_results(
                fetched.raw,
                fetched.charset,
                response_format,
            )
            if results:
                return results, None
            last_error = parse_error

    return [], last_error or "Web search returned no usable result links."


def _search_requests(
    query: str,
) -> tuple[tuple[str, SearchResponseFormat], ...]:
    encoded_query = quote_plus(query)
    return tuple(
        (endpoint.format(query=encoded_query), response_format)
        for endpoint, response_format in SEARCH_PROVIDERS
    )


def _parse_provider_search_results(
    raw: bytes,
    charset: str,
    response_format: SearchResponseFormat,
) -> tuple[list[WebSearchResult], str | None]:
    if response_format == "rss":
        return _parse_rss_search_results(raw, charset)
    return _parse_search_results(raw, charset)


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


def _parse_rss_search_results(
    raw: bytes,
    charset: str,
) -> tuple[list[WebSearchResult], str | None]:
    """Parse a bounded RSS search response into canonical organic links."""

    try:
        root = fromstring(raw.decode(charset, errors="replace"))
    except (ParseError, ValueError):
        return [], "Web search returned malformed RSS."

    results: list[WebSearchResult] = []
    seen_urls: set[str] = set()
    for item in root.findall(".//item"):
        title = _compact_text(item.findtext("title", default=""), limit=120)
        url = _search_result_url(item.findtext("link", default=""))
        if not title or not url or url in seen_urls:
            continue

        description = item.findtext("description", default="")
        parser = PageTextParser()
        parser.feed(description)
        parser.close()
        excerpt = _compact_text(" ".join(parser.text_parts) or description)
        seen_urls.add(url)
        results.append(
            WebSearchResult(
                title=title,
                url=url,
                excerpt=excerpt,
            ),
        )
        if len(results) >= 5:
            break

    if not results:
        return [], "Web search returned no usable result links."
    return results, None


def _search_web_reference(query: str) -> tuple[WebSearchResult | None, int, str | None]:
    """Search for a reference page and fetch the first readable result page."""

    results, error = _search_web_results(query)
    if error:
        return None, 0, error

    snippet_fallback: WebSearchResult | None = None
    for result in results:
        web_reference = _fetch_web_reference(
            _relevant_web_url(
                result.url,
                relevance_query=query,
                reference_title=result.title,
            ),
        )
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

        web_reference = _fetch_web_reference(
            _relevant_web_url(
                result.url,
                relevance_query=query,
                reference_title=result.title,
            ),
        )
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
        web_reference = await _async_fetch_web_reference(
            _relevant_web_url(
                result.url,
                relevance_query=query,
                reference_title=result.title,
            ),
        )
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

    semaphore = asyncio.Semaphore(WEB_SEARCH_MAX_CONCURRENCY)

    async def fetch(result: WebSearchResult) -> WebReference | None:
        async with semaphore:
            return await _async_fetch_web_reference(
                _relevant_web_url(
                    result.url,
                    relevance_query=query,
                    reference_title=result.title,
                ),
            )

    # ``gather`` preserves input order while allowing bounded page fetches.
    fetched_references: list[WebReference | None] = list(
        await asyncio.gather(
            *(fetch(result) for result in results[:max_results]),
        ),
    )

    references: list[WebSearchResult] = []
    for result, web_reference in zip(
        results[:max_results],
        fetched_references,
        strict=True,
    ):
        if web_reference:
            references.append(_web_search_result_from_reference(result, web_reference))
            continue

        snippet_fallback = _search_snippet_fallback(result)
        if snippet_fallback:
            references.append(snippet_fallback)

    if references:
        return references, len(results), None

    return [], len(results), "Search returned links, but no readable page text."


async def _async_search_results_limited(
    query: str,
    semaphore: asyncio.Semaphore,
) -> tuple[list[WebSearchResult], str | None]:
    async with semaphore:
        return await _async_search_web_results(query)


async def _async_fetch_reference_limited(
    result: WebSearchResult,
    semaphore: asyncio.Semaphore,
    relevance_query: str,
) -> WebReference | None:
    async with semaphore:
        return await _async_fetch_web_reference(
            _relevant_web_url(
                result.url,
                relevance_query=relevance_query,
                reference_title=result.title,
            ),
        )


async def _cancel_tasks(tasks: Iterable[asyncio.Task[object]]) -> None:
    task_list = list(tasks)
    for task in task_list:
        task.cancel()
    if task_list:
        # Consume only cancellations initiated by this scheduler during timeout
        # cleanup. Cancellation of the parent operation is re-raised by callers.
        await asyncio.gather(*task_list, return_exceptions=True)


def _canonicalized_search_result(
    result: WebSearchResult,
) -> WebSearchResult | None:
    url = _canonical_web_url(result.url)
    if not url:
        return None

    final_url = _canonical_web_url(result.final_url) if result.final_url else ""
    return replace(result, url=url, final_url=final_url)


def _search_result_domain(result: WebSearchResult) -> str:
    hostname = (urlparse(result.url).hostname or "").casefold()
    return hostname.removeprefix("www.")


def _is_host_suffix(hostname: str, suffix: str) -> bool:
    return hostname == suffix or hostname.endswith(f".{suffix}")


def _is_official_career_result(result: WebSearchResult) -> bool:
    parsed = urlparse(result.url)
    hostname = (parsed.hostname or "").casefold().removeprefix("www.")
    if any(
        _is_host_suffix(hostname, suffix) for suffix in SEARCH_AGGREGATOR_HOST_SUFFIXES
    ):
        return False

    path_segments = {
        segment.casefold() for segment in parsed.path.split("/") if segment
    }
    return hostname.startswith(OFFICIAL_CAREER_HOST_PREFIXES) or bool(
        path_segments & OFFICIAL_CAREER_PATH_SEGMENTS,
    )


def _search_result_freshness_year(result: WebSearchResult) -> int:
    current_year = datetime.now(UTC).year
    years = {
        int(value)
        for value in SEARCH_RESULT_YEAR_PATTERN.findall(
            f"{result.title} {result.url} {result.excerpt}",
        )
    }
    plausible_years = {
        year for year in years if current_year - 5 <= year <= current_year + 1
    }
    return max(plausible_years, default=0)


def _select_search_candidates(
    query_states: dict[int, _AsyncQuerySearchState],
    query_count: int,
    result_limit: int,
) -> list[WebSearchResult]:
    """Select canonical results with query/domain diversity and stable quality."""

    candidates: list[_SearchCandidate] = []
    seen_urls: set[str] = set()
    max_query_results = max(
        (len(state.results) for state in query_states.values()),
        default=0,
    )
    sequence = 0
    for result_index in range(max_query_results):
        for query_index in range(query_count):
            state = query_states.get(query_index)
            if state is None or result_index >= len(state.results):
                continue

            result = _canonicalized_search_result(state.results[result_index])
            if result is None or result.url in seen_urls:
                continue

            seen_urls.add(result.url)
            candidates.append(
                _SearchCandidate(
                    result=result,
                    query_index=query_index,
                    result_index=result_index,
                    sequence=sequence,
                ),
            )
            sequence += 1

    selected: list[WebSearchResult] = []
    represented_queries: set[int] = set()
    represented_domains: set[str] = set()
    while candidates and len(selected) < result_limit:
        candidate = max(
            candidates,
            key=lambda item: (
                item.query_index not in represented_queries,
                _search_result_domain(item.result) not in represented_domains,
                _is_official_career_result(item.result),
                _search_result_freshness_year(item.result),
                -item.result_index,
                -item.sequence,
            ),
        )
        candidates.remove(candidate)
        selected.append(candidate.result)
        represented_queries.add(candidate.query_index)
        represented_domains.add(_search_result_domain(candidate.result))

    return selected


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
            canonical_result = _canonicalized_search_result(result)
            if canonical_result is None or canonical_result.url in seen_urls:
                continue

            seen_urls.add(canonical_result.url)
            results.append(canonical_result)

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
    operation_timeout: float = WEB_SEARCH_OPERATION_TIMEOUT_SECONDS,
) -> WebSearchReference:
    """Search query variants within one fair, bounded, cancellation-safe operation."""

    normalized_queries = _normalized_search_queries(queries)
    result_limit = _normalized_max_search_results(max_results)
    if not normalized_queries:
        return WebSearchReference(
            query="",
            results=(),
            query_count=0,
            result_count=0,
            error="Web search received no usable queries.",
        )

    loop = asyncio.get_running_loop()
    timeout_budget = max(operation_timeout, 0.0)
    operation_deadline = loop.time() + timeout_budget
    semaphore = asyncio.Semaphore(WEB_SEARCH_MAX_CONCURRENCY)
    query_states: dict[int, _AsyncQuerySearchState] = {}

    async def search_query(query_index: int, query: str) -> None:
        query_results, error = await _async_search_results_limited(query, semaphore)
        # Record search links immediately so a total timeout can still return
        # useful snippet evidence from work that completed before cancellation.
        query_states[query_index] = _AsyncQuerySearchState(
            results=tuple(query_results),
            result_count=len(query_results),
            error=error,
        )

    query_tasks = [
        asyncio.create_task(search_query(index, query))
        for index, query in enumerate(normalized_queries)
    ]
    try:
        completed_queries, pending_queries = await asyncio.wait(
            query_tasks,
            # Reserve half of the total deadline for page retrieval. A slow
            # search variant must not consume the entire evidence operation.
            timeout=timeout_budget / 2,
        )
        search_timed_out = bool(pending_queries)
        if pending_queries:
            await _cancel_tasks(pending_queries)
    except asyncio.CancelledError:
        await _cancel_tasks(query_tasks)
        raise

    # Surface unexpected worker cancellation/errors instead of silently
    # converting them into an empty or partial search result.
    for task in completed_queries:
        task.result()

    total_result_count = 0
    last_error: str | None = None
    for query_index in range(len(normalized_queries)):
        state = query_states.get(query_index)
        if state is None:
            continue

        total_result_count += state.result_count
        if state.error:
            last_error = state.error

    # Select before fetching so the page budget is global rather than
    # ``query_count * max_results``. Query coverage wins first, followed by
    # source-domain diversity, official-career signals, freshness, and rank.
    selected_results = _select_search_candidates(
        query_states,
        len(normalized_queries),
        result_limit,
    )

    page_states: dict[int, WebReference | None] = {}
    relevance_query = " ".join(normalized_queries)

    async def fetch_and_record(index: int, result: WebSearchResult) -> None:
        page_states[index] = await _async_fetch_reference_limited(
            result,
            semaphore,
            relevance_query,
        )

    fetch_tasks = [
        asyncio.create_task(fetch_and_record(index, result))
        for index, result in enumerate(selected_results)
    ]
    fetch_timed_out = False
    if fetch_tasks:
        try:
            completed_fetches, pending_fetches = await asyncio.wait(
                fetch_tasks,
                timeout=max(operation_deadline - loop.time(), 0.0),
            )
            fetch_timed_out = bool(pending_fetches)
            if pending_fetches:
                await _cancel_tasks(pending_fetches)
        except asyncio.CancelledError:
            await _cancel_tasks(fetch_tasks)
            raise

        for task in completed_fetches:
            task.result()

    results: list[WebSearchResult] = []
    seen_result_urls: set[str] = set()
    for index, result in enumerate(selected_results):
        web_reference = page_states.get(index)
        candidate = (
            _web_search_result_from_reference(result, web_reference)
            if web_reference
            else _search_snippet_fallback(result)
        )
        canonical_candidate = (
            _canonicalized_search_result(candidate) if candidate is not None else None
        )
        if (
            canonical_candidate is not None
            and canonical_candidate.url not in seen_result_urls
        ):
            seen_result_urls.add(canonical_candidate.url)
            results.append(canonical_candidate)

    timed_out = search_timed_out or fetch_timed_out

    if timed_out and not results:
        last_error = "Web search exceeded its operation time budget."
    elif not results and last_error is None:
        last_error = "Search returned links, but no readable page text."

    return WebSearchReference(
        query=normalized_queries[0] if normalized_queries else "",
        results=tuple(results),
        query_count=len(normalized_queries),
        result_count=total_result_count,
        error=None if results else last_error,
        timed_out=timed_out,
        partial=timed_out and bool(results),
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
        excerpt_start=web_reference.excerpt_start,
        excerpt_end=web_reference.excerpt_end,
        excerpt_section=web_reference.excerpt_section,
        source_kind="fetched_page",
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
        excerpt_start=0,
        excerpt_end=len(excerpt),
        source_kind="search_snippet",
    )
