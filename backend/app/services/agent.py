import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from sqlite3 import Connection
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen
from uuid import uuid4

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentKnowledgeItem,
    AgentResumeEditSuggestion,
    AgentSource,
    AgentToolInvocation,
)
from app.services.llm_client import (
    AgentLlmConfig,
    LlmRequestError,
    LlmToolCall,
    complete_chat,
    complete_chat_stream,
    complete_chat_tool_call,
    resolve_agent_llm_config,
)

JD_URL_PATTERN = re.compile(r"https?://[^\s)>\"]+")

SYSTEM_PROMPTS = {
    "zh": (
        "你是 ResuMate 的 plan_execute 简历修改 Agent。必须先分析当前简历、"
        "JD 来源和关键词差距，再给出修改计划，最后只输出可被前端执行的结构化"
        "修改操作。不要直接生成整份新简历。若用户提供 JD URL，直接把该 URL "
        "作为 JD 来源；若没有提供 JD URL，就根据用户语言、目标岗位和简历标题"
        "构造 JD 搜索查询，并把搜索结果作为参考。所有修改都作用于临时 JSON "
        "草稿，等待用户预览、撤回或应用。"
    ),
    "en": (
        "You are ResuMate's plan_execute resume editing agent. First analyze "
        "the current resume, JD source, and keyword gaps; then create an edit "
        "plan; finally return structured edit operations that the frontend can "
        "execute. Do not generate a complete replacement resume. If the user "
        "provides a JD URL, use that URL directly. If no JD URL is provided, "
        "build a JD search query from the response language, target role, and "
        "resume headline, and use that as the reference. All edits must target "
        "a temporary JSON draft that the user can preview, discard, or apply."
    ),
}

DIRECT_CHAT_SYSTEM_PROMPTS = {
    "zh": (
        "你是 ResuMate 的简历助理。正常回答用户问题，不要声称调用了工具。"
        "只有当用户明确要求修改简历、分析 JD、调整模块、增删内容或生成可预览"
        "草稿操作时，系统才会切换到工具化 agent 流程。"
    ),
    "en": (
        "You are ResuMate's resume assistant. Answer the user normally and do "
        "not claim that tools were called. The system only switches to the "
        "tool-based agent workflow when the user clearly asks to edit the "
        "resume, analyze a JD, reorder sections, add or remove content, or "
        "produce previewable draft operations."
    ),
}

AGENT_INTENT_KEYWORDS = {
    "zh": (
        "简历",
        "履历",
        "jd",
        "岗位",
        "职位",
        "职责",
        "要求",
        "优化",
        "修改",
        "调整",
        "新增",
        "增加",
        "删除",
        "移除",
        "排序",
        "顺序",
        "模块",
        "项目",
        "实习",
        "教育",
        "经历",
        "技能",
        "关键词",
        "匹配",
        "预览",
        "草稿",
        "应用",
        "撤回",
        "求职",
        "面试",
    ),
    "en": (
        "resume",
        "cv",
        "jd",
        "job description",
        "role",
        "position",
        "requirement",
        "responsibility",
        "optimize",
        "improve",
        "rewrite",
        "edit",
        "revise",
        "add",
        "remove",
        "delete",
        "reorder",
        "section",
        "project",
        "experience",
        "education",
        "skill",
        "keyword",
        "match",
        "draft",
        "preview",
        "apply",
        "internship",
    ),
}

AGENT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "jd_url_fetch",
            "description": "Fetch and extract text from a user-provided JD URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The job description URL to fetch.",
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "jd_reference_search",
            "description": (
                "Search the web for a target-role JD when the user did not "
                "provide a JD URL."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for the target role JD.",
                    },
                    "role": {
                        "type": "string",
                        "description": "Target role inferred from the user prompt.",
                    },
                    "language": {
                        "type": "string",
                        "enum": ["zh", "en"],
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resume_analysis",
            "description": "Analyze the current structured resume JSON.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_plan",
            "description": "Create an edit plan after JD and resume analysis.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "edit_execute",
            "description": "Execute the approved edit plan against a draft JSON.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
]


@dataclass(frozen=True)
class JobReference:
    """Resolved JD context used by the agent plan."""

    mode: str
    role: str
    query: str
    url: str | None
    excerpt: str
    source_title: str = ""
    source_excerpt: str = ""
    tool_state: str = "output-available"
    tool_error: str | None = None
    result_count: int = 0


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


@dataclass(frozen=True)
class ResumeAnalysis:
    """Small, explicit analysis result for plan generation."""

    title: str
    summary: str
    sections: list[dict[str, object]]
    empty_section_ids: list[str]
    matched_keywords: list[str]
    missing_keywords: list[str]


@dataclass(frozen=True)
class EditPlanStep:
    """One executable step in the plan_execute flow."""

    action: str
    target: str
    reason: str


def _string_list(value: object) -> list[str]:
    """Return only string entries from a possible list."""

    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str)]


def _current_prompt(request: AgentChatRequest) -> str:
    """Return the current user message while keeping the legacy prompt field."""

    if request.message and request.message.text.strip():
        return request.message.text.strip()

    if request.prompt.strip():
        return request.prompt.strip()

    if request.messages:
        last_user = next(
            (
                message.text.strip()
                for message in reversed(request.messages)
                if message.role == "user" and message.text.strip()
            ),
            "",
        )

        if last_user:
            return last_user

    return ""


def _conversation_depth(request: AgentChatRequest) -> int:
    """Return the number of real conversation messages sent by the frontend."""

    if request.messages:
        return len(request.messages)

    return len(request.conversation)


def _compact_text(value: str, limit: int = 700) -> str:
    """Collapse whitespace and trim text for prompts and citations."""

    return re.sub(r"\s+", " ", unescape(value)).strip()[:limit]


def _is_useful_web_excerpt(value: str) -> bool:
    """Return whether fetched page text is useful enough as JD context."""

    text = _compact_text(value, limit=1_000).lower()
    if len(text) < 80:
        return False

    blocked_markers = (
        "正在加载中",
        "enable javascript",
        "please enable javascript",
        "access denied",
        "captcha",
        "安全验证",
    )
    return not any(marker in text for marker in blocked_markers)


def _fetch_web_reference(url: str, timeout: float = 4.0) -> WebReference | None:
    """Fetch a URL and return visible text that can be cited."""

    request = Request(
        url,
        headers={
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.8",
            "User-Agent": "ResuMate/1.0 (+https://resumate.local)",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(220_000)
            content_type = response.headers.get("content-type", "")
            charset = response.headers.get_content_charset() or "utf-8"
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None

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


def _search_web_results(
    query: str,
    timeout: float = 6.0,
) -> tuple[list[WebSearchResult], str | None]:
    """Search the web for JD-like pages and return organic result links."""

    search_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    request = Request(
        search_url,
        headers={
            "Accept": "text/html,*/*;q=0.8",
            "User-Agent": "ResuMate/1.0 (+https://resumate.local)",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(240_000)
            charset = response.headers.get_content_charset() or "utf-8"
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        return [], f"JD search request failed: {exc}"

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
        return [], "JD search returned no usable result links."

    return deduped_results, None


def _search_jd_reference(query: str) -> tuple[WebSearchResult | None, int, str | None]:
    """Search for a JD page and fetch the first readable result page."""

    results, error = _search_web_results(query)
    if error:
        return None, 0, error

    for result in results:
        web_reference = _fetch_web_reference(result.url)
        if not web_reference:
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

    return None, len(results), "Search returned links, but no readable JD text."


def _file_content_excerpt(file: dict[str, Any]) -> str:
    """Return text content supplied with a user attachment."""

    content = file.get("content")
    return _compact_text(content) if isinstance(content, str) else ""


def _agent_file_context(files: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Build the text-only attachment context sent to the model."""

    file_context: list[dict[str, str]] = []
    for file in files:
        excerpt = _file_content_excerpt(file)
        if not excerpt:
            continue

        filename = file.get("filename")
        media_type = file.get("mediaType")
        file_context.append(
            {
                "filename": str(filename or "Attachment"),
                "mediaType": str(media_type or ""),
                "excerpt": excerpt,
            },
        )

    return file_context


def _should_use_plan_execute(request: AgentChatRequest) -> bool:
    """Return whether the prompt needs the tool-backed resume agent flow."""

    prompt = _current_prompt(request).lower()
    if not prompt:
        return False

    if request.applied_actions or request.files:
        return True

    if JD_URL_PATTERN.search(prompt):
        return True

    keywords = AGENT_INTENT_KEYWORDS[request.locale]
    return any(keyword in prompt for keyword in keywords)


def _has_item_content(item: object) -> bool:
    """Return whether a resume item contains visible content."""

    if not isinstance(item, dict):
        return False

    for key in ("title", "subtitle", "meta", "period", "description"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return True

    highlights = item.get("highlights")
    return isinstance(highlights, list) and any(
        isinstance(entry, str) and entry.strip() for entry in highlights
    )


def _section_label(section: dict[str, object], locale: str) -> str:
    """Return a readable section label for response text and edit cards."""

    custom_title = section.get("customTitle")
    if isinstance(custom_title, str) and custom_title.strip():
        return custom_title.strip()

    kind = section.get("kind")
    zh_labels = {
        "education": "教育经历",
        "internship": "实习经历",
        "project": "项目经历",
        "other": "其他经历",
        "custom": "自定义模块",
    }
    en_labels = {
        "education": "Education",
        "internship": "Internship",
        "project": "Projects",
        "other": "Other",
        "custom": "Custom Section",
    }
    labels = zh_labels if locale == "zh" else en_labels

    return labels.get(str(kind), "模块" if locale == "zh" else "Section")


class AgentPlanExecutor:
    """Build plan_execute responses for resume draft editing."""

    def __init__(self, request: AgentChatRequest) -> None:
        self.request = request
        self.is_zh = request.locale == "zh"
        self.prompt = _current_prompt(request)

    def build_message(self) -> AgentChatMessage:
        """Run the analysis, planning, and execution phases."""

        job_reference = self.resolve_job_reference()
        analysis = self.analyze_resume()
        plan = self.create_plan(job_reference, analysis)
        edits = self.execute_plan(plan, job_reference, analysis)
        tools = self.build_tools(job_reference, analysis, plan, edits)

        return self.build_message_from_parts(
            job_reference=job_reference,
            analysis=analysis,
            plan=plan,
            edits=edits,
            tools=tools,
        )

    def build_message_from_parts(
        self,
        *,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
        plan: list[EditPlanStep],
        edits: list[AgentResumeEditSuggestion],
        tools: list[AgentToolInvocation],
        message_id: str | None = None,
    ) -> AgentChatMessage:
        """Assemble the final assistant payload from executed tool outputs."""

        sources = self.build_sources(job_reference, analysis)
        knowledge = self.build_knowledge(job_reference, analysis)

        return AgentChatMessage(
            id=message_id or f"agent-msg-{uuid4().hex[:12]}",
            role="assistant",
            tone="success" if edits else "default",
            text=self.build_response_text(job_reference, analysis, plan, edits),
            suggestions=self.build_suggestions(job_reference, analysis),
            knowledge=knowledge,
            tools=tools,
            sources=sources,
            edits=edits,
            quickReplies=self.build_quick_replies(edits),
            actions=self.build_actions(edits),
        )

    def jd_search_query(self, role: str) -> str:
        """Build the deterministic JD search query for the inferred role."""

        if self.is_zh:
            return f"{role} 岗位 JD 职责 任职要求"

        return f"{role} job description responsibilities requirements"

    def resolve_job_reference(self) -> JobReference:
        """Resolve the JD URL or a deterministic JD search reference."""

        combined_context = "\n".join(
            item for item in (self.prompt, self.request.job_brief) if item.strip()
        )
        url_match = JD_URL_PATTERN.search(combined_context)
        role = self.infer_target_role()

        if url_match:
            url = url_match.group(0).rstrip(".,;，。；")
            return self.build_url_job_reference(url, role)

        return self.build_search_job_reference(role, self.jd_search_query(role))

    def build_url_job_reference(self, url: str, role: str) -> JobReference:
        """Fetch a user-selected JD URL and convert it to agent context."""

        web_reference = _fetch_web_reference(url)
        excerpt = (
            web_reference.excerpt
            if web_reference
            else self.request.job_brief.strip()[:260]
            or self.prompt.replace(url, "").strip()[:260]
        )
        return JobReference(
            mode="url",
            role=role,
            query="",
            url=url,
            excerpt=excerpt,
            source_title=web_reference.title if web_reference else "",
            source_excerpt=web_reference.excerpt if web_reference else "",
            tool_state="output-available" if web_reference else "output-error",
            tool_error=None
            if web_reference
            else "JD URL could not be fetched or parsed.",
            result_count=1 if web_reference else 0,
        )

    def build_search_job_reference(self, role: str, query: str) -> JobReference:
        """Search and fetch a JD reference selected by the model."""

        if self.is_zh:
            fallback_excerpt = (
                "未检测到 JD URL。已尝试按目标岗位和中文语境搜索 JD 参考。"
            )
        else:
            fallback_excerpt = (
                "No JD URL was detected. The agent will search a JD reference "
                "from the target role and response language."
            )

        search_result, result_count, search_error = _search_jd_reference(query)
        if search_result:
            excerpt = search_result.excerpt
            source_title = search_result.title
            source_url = search_result.url
            source_excerpt = search_result.excerpt if not search_error else ""
        else:
            excerpt = fallback_excerpt
            source_title = ""
            source_url = None
            source_excerpt = ""

        return JobReference(
            mode="search",
            role=role,
            query=query,
            url=source_url,
            excerpt=excerpt,
            source_title=source_title,
            source_excerpt=source_excerpt,
            tool_state="output-error" if search_error else "output-available",
            tool_error=search_error,
            result_count=result_count,
        )

    def infer_target_role(self) -> str:
        """Infer the target role from JD text, user prompt, or resume headline."""

        context = f"{self.request.job_brief}\n{self.prompt}".strip()
        role_patterns = (
            self.zh_role_patterns() if self.is_zh else self.en_role_patterns()
        )

        for pattern in role_patterns:
            match = re.search(pattern, context, flags=re.IGNORECASE)
            if match:
                role = self.clean_inferred_role(match.group(1))
                if role:
                    return role

        basic = self.request.resume.get("basic")
        if isinstance(basic, dict):
            headline = basic.get("headline")
            if isinstance(headline, str) and headline.strip():
                return headline.strip()[:40]

        return "前端开发工程师" if self.is_zh else "frontend engineer"

    def zh_role_patterns(self) -> list[str]:
        """Return conservative Chinese patterns for explicit target roles."""

        return [
            (
                r"(?:应聘|目标|投递|申请)(?:的)?(?:岗位|职位)?"
                r"(?:是|为|:|：|\s)+([^\n，。,.；;]{2,40})"
            ),
            r"(?:岗位|职位)(?:是|为|:|：|\s)+([^\n，。,.；;]{2,40})",
            r"(?:应聘|投递|申请)([^\n，。,.；;]{2,40}?)(?:岗位|职位)",
        ]

    def en_role_patterns(self) -> list[str]:
        """Return conservative English patterns for explicit target roles."""

        return [
            (
                r"(?:target\s+)?(?:role|position)\s*"
                r"(?:is|as|:|-)?\s+([^\n,.]{2,40})"
            ),
            r"(?:applying|apply)\s+(?:for|to)\s+(?:a|an|the)?\s*([^\n,.]{2,40})",
            (
                r"(frontend|backend|full[- ]?stack|data|machine learning|product)"
                r"\s+engineer"
            ),
        ]

    def clean_inferred_role(self, value: str) -> str:
        """Remove connective words that are not part of the target role."""

        role = value.strip()
        role = re.sub(r"^(?:的)?(?:岗位|职位)?(?:是|为|:|：|\s)+", "", role)
        role = re.sub(r"^(?:role|position)\s+(?:is|as)\s+", "", role, flags=re.I)
        role = re.split(
            r"(?:\s+请|\s+帮我|\s+优化|\s+修改|\s+调整|，|。|,|；|;)",
            role,
            maxsplit=1,
        )[0]
        return role.strip()[:40]

    def analyze_resume(self) -> ResumeAnalysis:
        """Extract only the resume facts needed for planning."""

        basic = self.request.resume.get("basic")
        basic_data = basic if isinstance(basic, dict) else {}
        sections_value = self.request.resume.get("sections")
        sections = sections_value if isinstance(sections_value, list) else []
        normalized_sections: list[dict[str, object]] = []
        empty_section_ids: list[str] = []

        for section in sections:
            if not isinstance(section, dict):
                continue

            section_id = section.get("id")
            if not isinstance(section_id, str) or not section_id:
                continue

            normalized_sections.append(section)
            items = section.get("items")
            visible_items = (
                [item for item in items if _has_item_content(item)]
                if isinstance(items, list)
                else []
            )

            if not visible_items:
                empty_section_ids.append(section_id)

        title = "resume"
        for key in ("name", "headline"):
            value = basic_data.get(key)
            if isinstance(value, str) and value.strip():
                title = value.strip()
                break

        summary_value = basic_data.get("summary")
        summary = summary_value.strip() if isinstance(summary_value, str) else ""

        return ResumeAnalysis(
            title=title,
            summary=summary,
            sections=normalized_sections,
            empty_section_ids=empty_section_ids,
            matched_keywords=_string_list(
                self.request.keyword_match.get("matched"),
            )[:6],
            missing_keywords=_string_list(
                self.request.keyword_match.get("missing"),
            )[:6],
        )

    def create_plan(
        self,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> list[EditPlanStep]:
        """Create readable, conservative plan steps from user intent."""

        prompt = self.prompt.lower()
        wants_add = bool(
            re.search(r"新增|添加|补充|add|insert|create|项目|project", prompt),
        )
        wants_delete = bool(
            re.search(r"删除|移除|去掉|delete|remove", prompt),
        )
        wants_reorder = bool(
            re.search(r"顺序|排序|前置|调整模块|reorder|order|move", prompt),
        )
        wants_summary = bool(
            re.search(r"简介|summary|概述|profile|优化|润色|rewrite", prompt),
        )
        wants_bullet = bool(
            re.search(r"经历|项目|bullet|量化|impact|experience", prompt),
        )
        plan: list[EditPlanStep] = []

        if not self.has_editable_resume_content(analysis):
            return plan

        if wants_summary or not analysis.summary or analysis.missing_keywords:
            reason = (
                "简介需要先对齐目标岗位和 JD 关键词。"
                if self.is_zh
                else "The summary should align with the target role and JD keywords."
            )
            plan.append(EditPlanStep("replace_summary", "basic.summary", reason))

        if wants_bullet and self.find_first_item_section(analysis):
            reason = (
                "最强经历需要更明确地呈现职责、技术和结果。"
                if self.is_zh
                else (
                    "The strongest experience needs clearer responsibility, "
                    "stack, and outcome."
                )
            )
            plan.append(EditPlanStep("update_first_item", "sections.items", reason))

        if wants_add or (wants_bullet and not self.find_project_section(analysis)):
            reason = (
                "根据目标岗位补充一个可验证的项目模块。"
                if self.is_zh
                else "Add a verifiable project section for the target role."
            )
            plan.append(EditPlanStep("insert_project", "sections", reason))

        if wants_reorder and len(analysis.sections) > 1:
            reason = (
                "把更能证明岗位匹配度的模块放在教育信息之前。"
                if self.is_zh
                else "Move stronger role-fit sections ahead of education."
            )
            plan.append(EditPlanStep("reorder_sections", "sections", reason))

        if wants_delete and analysis.empty_section_ids:
            reason = (
                "删除没有可见内容的空模块，减少干扰。"
                if self.is_zh
                else "Remove empty sections so the resume is easier to scan."
            )
            plan.append(EditPlanStep("delete_empty_sections", "sections", reason))

        if not plan:
            reason = (
                "先生成一个低风险的简介草稿，供前端预览。"
                if self.is_zh
                else "Start with a low-risk summary draft for preview."
            )
            plan.append(EditPlanStep("replace_summary", "basic.summary", reason))

        return plan

    def has_editable_resume_content(self, analysis: ResumeAnalysis) -> bool:
        """Return whether the resume has enough facts for executable edits."""

        if analysis.summary:
            return True

        return self.find_first_item_section(analysis) is not None

    def execute_plan(
        self,
        plan: list[EditPlanStep],
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> list[AgentResumeEditSuggestion]:
        """Translate plan steps into frontend-executable draft operations."""

        edits: list[AgentResumeEditSuggestion] = []

        for step in plan:
            if step.action == "replace_summary":
                edits.append(self.build_summary_edit(step, job_reference, analysis))
                continue

            if step.action == "update_first_item":
                edit = self.build_first_item_edit(step, job_reference, analysis)
                if edit:
                    edits.append(edit)
                continue

            if step.action == "insert_project":
                edits.append(self.build_project_section_edit(step, job_reference))
                continue

            if step.action == "reorder_sections":
                edit = self.build_reorder_sections_edit(step, analysis)
                if edit:
                    edits.append(edit)
                continue

            if step.action == "delete_empty_sections":
                edits.extend(self.build_delete_empty_section_edits(step, analysis))

        return edits

    def build_summary_edit(
        self,
        step: EditPlanStep,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> AgentResumeEditSuggestion:
        """Build the summary replacement operation."""

        keywords = analysis.missing_keywords[:3] or analysis.matched_keywords[:3]
        if self.is_zh:
            keyword_text = f"，重点覆盖 {'、'.join(keywords)}" if keywords else ""
            replacement = (
                f"面向{job_reference.role}岗位，具备与业务场景结合的项目推进、"
                f"工程实现和跨模块协作经验{keyword_text}。能够把需求拆解为可落地"
                "方案，并通过清晰的交付结果证明技术能力。"
            )
            title = "生成可预览的个人简介草稿"
        else:
            keyword_text = (
                f" with emphasis on {', '.join(keywords)}" if keywords else ""
            )
            replacement = (
                f"Targeting {job_reference.role} roles, with practical experience "
                f"turning product requirements into maintainable engineering "
                f"solutions{keyword_text}. Known for clear execution, cross-functional "
                "collaboration, and outcome-oriented delivery."
            )
            title = "Create a previewable summary draft"

        return AgentResumeEditSuggestion(
            id=f"edit-{uuid4().hex[:8]}",
            title=title,
            target=step.target,
            reason=step.reason,
            replacement=replacement,
            operation={
                "type": "replace_field",
                "path": "basic.summary",
                "value": replacement,
            },
            status="executed",
        )

    def build_first_item_edit(
        self,
        step: EditPlanStep,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> AgentResumeEditSuggestion | None:
        """Build an update operation for the first meaningful resume item."""

        section = self.find_first_item_section(analysis)
        if not section:
            return None

        items = section.get("items")
        item = (
            next(
                (
                    entry
                    for entry in items
                    if isinstance(entry, dict) and _has_item_content(entry)
                ),
                None,
            )
            if isinstance(items, list)
            else None
        )
        if not isinstance(item, dict) or not isinstance(item.get("id"), str):
            return None

        current_highlights = _string_list(item.get("highlights"))
        if self.is_zh:
            new_highlight = (
                f"围绕{job_reference.role}岗位补充技术取舍、协作边界和可验证结果，"
                "让经历从职责描述升级为能力证明。"
            )
            title = "补强首个经历条目"
        else:
            new_highlight = (
                f"Add role-specific proof for {job_reference.role}: technical "
                "trade-offs, collaboration scope, and measurable outcome."
            )
            title = "Strengthen the first experience item"

        section_id = str(section["id"])
        item_id = str(item["id"])
        return AgentResumeEditSuggestion(
            id=f"edit-{uuid4().hex[:8]}",
            title=title,
            target=f"sections.{section_id}.items.{item_id}",
            reason=step.reason,
            replacement=new_highlight,
            operation={
                "type": "update_item",
                "sectionId": section_id,
                "itemId": item_id,
                "patch": {
                    "highlights": [*current_highlights, new_highlight],
                },
            },
            status="executed",
        )

    def build_project_section_edit(
        self,
        step: EditPlanStep,
        job_reference: JobReference,
    ) -> AgentResumeEditSuggestion:
        """Build an insert operation for a new project section."""

        section_id = f"section-agent-project-{uuid4().hex[:8]}"
        item_id = f"item-agent-project-{uuid4().hex[:8]}"

        if self.is_zh:
            title = "新增项目经历模块"
            section_title = "岗位相关项目"
            project_title = f"{job_reference.role}相关项目"
            description = "用于承接 JD 中要求的核心技能、业务场景和交付结果。"
            highlights = [
                "补充项目背景、技术栈、个人职责和最终结果。",
                "把 JD 关键词自然写入项目描述，避免简单堆词。",
            ]
        else:
            title = "Add a project section"
            section_title = "Role-Fit Projects"
            project_title = f"{job_reference.role} project"
            description = (
                "Use this project to connect JD requirements with concrete "
                "skills, context, and delivery outcomes."
            )
            highlights = [
                "Add project context, stack, personal scope, and final outcome.",
                "Write JD keywords naturally into the project instead of listing them.",
            ]

        section = {
            "id": section_id,
            "kind": "project",
            "layout": "timeline",
            "customTitle": section_title,
            "items": [
                {
                    "id": item_id,
                    "title": project_title,
                    "subtitle": "",
                    "meta": "",
                    "period": "",
                    "description": description,
                    "highlights": highlights,
                },
            ],
        }

        return AgentResumeEditSuggestion(
            id=f"edit-{uuid4().hex[:8]}",
            title=title,
            target="sections",
            reason=step.reason,
            replacement=section_title,
            operation={
                "type": "insert_section",
                "section": section,
                "index": self.find_project_insert_index(),
            },
            status="executed",
        )

    def build_reorder_sections_edit(
        self,
        step: EditPlanStep,
        analysis: ResumeAnalysis,
    ) -> AgentResumeEditSuggestion | None:
        """Build an operation that reorders existing sections."""

        if len(analysis.sections) < 2:
            return None

        priority = {
            "internship": 0,
            "project": 1,
            "custom": 2,
            "other": 3,
            "education": 4,
        }
        ordered_sections = sorted(
            analysis.sections,
            key=lambda section: priority.get(str(section.get("kind")), 9),
        )
        ordered_ids = [
            str(section["id"])
            for section in ordered_sections
            if isinstance(section.get("id"), str)
        ]

        if ordered_ids == [str(section["id"]) for section in analysis.sections]:
            return None

        return AgentResumeEditSuggestion(
            id=f"edit-{uuid4().hex[:8]}",
            title="调整模块顺序" if self.is_zh else "Reorder resume sections",
            target="sections",
            reason=step.reason,
            replacement=", ".join(ordered_ids),
            operation={
                "type": "reorder_sections",
                "sectionIds": ordered_ids,
            },
            status="executed",
        )

    def build_delete_empty_section_edits(
        self,
        step: EditPlanStep,
        analysis: ResumeAnalysis,
    ) -> list[AgentResumeEditSuggestion]:
        """Build delete operations for sections without visible content."""

        edits: list[AgentResumeEditSuggestion] = []
        sections_by_id = {
            str(section["id"]): section
            for section in analysis.sections
            if isinstance(section.get("id"), str)
        }

        for section_id in analysis.empty_section_ids:
            section = sections_by_id.get(section_id)
            if not section:
                continue

            label = _section_label(section, self.request.locale)
            edits.append(
                AgentResumeEditSuggestion(
                    id=f"edit-{uuid4().hex[:8]}",
                    title=(
                        f"删除空模块：{label}"
                        if self.is_zh
                        else f"Delete empty section: {label}"
                    ),
                    target=f"sections.{section_id}",
                    reason=step.reason,
                    replacement=None,
                    operation={
                        "type": "delete_section",
                        "sectionId": section_id,
                    },
                    status="executed",
                ),
            )

        return edits

    def build_tools(
        self,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
        plan: list[EditPlanStep],
        edits: list[AgentResumeEditSuggestion],
        tool_ids: dict[str, str] | None = None,
    ) -> list[AgentToolInvocation]:
        """Return tool call metadata for the plan_execute phases."""

        tool_ids = tool_ids or {}
        tools = [
            self.build_jd_tool(job_reference, tool_ids.get("jd")),
            self.build_resume_analysis_tool(analysis, tool_ids.get("analysis")),
        ]

        tools.append(self.build_plan_tool(plan, tool_ids.get("plan")))

        if plan:
            tools.append(
                self.build_execute_tool(plan, edits, tool_ids.get("execute")),
            )

        return tools

    def build_jd_tool(
        self,
        job_reference: JobReference,
        tool_id: str | None = None,
    ) -> AgentToolInvocation:
        """Return the completed JD fetch/search tool invocation."""

        jd_tool_type = (
            "tool-jd_url_fetch"
            if job_reference.mode == "url"
            else "tool-jd_reference_search"
        )
        jd_input = (
            {"url": job_reference.url}
            if job_reference.mode == "url"
            else {"query": job_reference.query, "language": self.request.locale}
        )
        jd_output = {
            "mode": job_reference.mode,
            "role": job_reference.role,
            "excerpt": job_reference.excerpt,
            "resultCount": job_reference.result_count,
        }
        if job_reference.url:
            jd_output["url"] = job_reference.url

        return AgentToolInvocation(
            id=tool_id or f"tool-{uuid4().hex[:8]}",
            type=jd_tool_type,
            title=(
                "jd_url_fetch"
                if job_reference.mode == "url"
                else "jd_reference_search"
            ),
            state=job_reference.tool_state,
            input=jd_input,
            output=jd_output,
            errorText=job_reference.tool_error,
        )

    def build_resume_analysis_tool(
        self,
        analysis: ResumeAnalysis,
        tool_id: str | None = None,
    ) -> AgentToolInvocation:
        """Return the completed local resume analysis tool invocation."""

        return AgentToolInvocation(
            id=tool_id or f"tool-{uuid4().hex[:8]}",
            type="tool-resume_analysis",
            title="resume_analysis",
            state="output-available",
            input={
                "resumeTitle": analysis.title,
                "sectionCount": len(analysis.sections),
                "conversationDepth": _conversation_depth(self.request),
            },
            output={
                "missingKeywords": analysis.missing_keywords,
                "matchedKeywords": analysis.matched_keywords,
                "emptySectionIds": analysis.empty_section_ids,
            },
        )

    def build_plan_tool(
        self,
        plan: list[EditPlanStep],
        tool_id: str | None = None,
    ) -> AgentToolInvocation:
        """Return the completed edit planning tool invocation."""

        return AgentToolInvocation(
            id=tool_id or f"tool-{uuid4().hex[:8]}",
            type="tool-edit_plan",
            title="edit_plan",
            state="output-available",
            input={"stepCount": len(plan)},
            output=[
                {
                    "action": step.action,
                    "target": step.target,
                    "reason": step.reason,
                }
                for step in plan
            ],
        )

    def build_execute_tool(
        self,
        plan: list[EditPlanStep],
        edits: list[AgentResumeEditSuggestion],
        tool_id: str | None = None,
    ) -> AgentToolInvocation:
        """Return the completed draft edit execution tool invocation."""

        return AgentToolInvocation(
            id=tool_id or f"tool-{uuid4().hex[:8]}",
            type="tool-edit_execute",
            title="edit_execute",
            state="output-available",
            input={"planStepCount": len(plan)},
            output={
                "editCount": len(edits),
                "operationTypes": [
                    edit.operation.get("type") for edit in edits if edit.operation
                ],
            },
        )

    def build_sources(
        self,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> list[AgentSource]:
        """Build citation metadata only from user-visible external content."""

        sources: list[AgentSource] = []

        if job_reference.source_excerpt:
            source_id = (
                "source-jd-url"
                if job_reference.mode == "url"
                else "source-jd-search"
            )
            sources.append(
                AgentSource(
                    id=source_id,
                    title=job_reference.source_title or "Target JD URL",
                    sourceType="web",
                    url=job_reference.url,
                    excerpt=job_reference.source_excerpt,
                ),
            )

        if self.request.job_brief.strip():
            sources.append(
                AgentSource(
                    id="source-job-brief",
                    title="Target job description",
                    sourceType="jobBrief",
                    excerpt=self.request.job_brief.strip()[:220],
                ),
            )

        for index, file in enumerate(self.request.files[:3], start=1):
            excerpt = _file_content_excerpt(file)
            if not excerpt:
                continue

            filename = file.get("filename")
            sources.append(
                AgentSource(
                    id=f"source-attachment-{index}",
                    title=str(filename or f"Attachment {index}"),
                    sourceType="attachment",
                    url=file.get("url") if isinstance(file.get("url"), str) else None,
                    excerpt=excerpt,
                ),
            )

        return sources

    def build_suggestions(
        self,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> list[str]:
        """Build short guidance text next to executable edits."""

        if not self.has_editable_resume_content(analysis):
            return (
                [
                    "当前简历内容太少，本轮不会生成可执行草稿，避免凭空编造经历。",
                    "请先补充真实项目、实习、教育或技能信息，再让 Agent 修改。",
                    f"本轮参考岗位：{job_reference.role}。",
                ]
                if self.is_zh
                else [
                    (
                        "The resume has too little content, so no executable "
                        "draft was generated."
                    ),
                    (
                        "Add real projects, internships, education, or skills "
                        "before editing."
                    ),
                    f"Target role for this pass: {job_reference.role}.",
                ]
            )

        if self.is_zh:
            suggestions = [
                "先在草稿预览中检查高亮区域，再决定应用或撤回。",
                f"本轮参考岗位：{job_reference.role}。",
            ]
            if analysis.missing_keywords:
                suggestions.append(
                    f"优先自然补足：{' / '.join(analysis.missing_keywords[:3])}。",
                )
        else:
            suggestions = [
                "Review highlighted draft areas before applying or discarding.",
                f"Target role for this pass: {job_reference.role}.",
            ]
            if analysis.missing_keywords:
                suggestions.append(
                    (
                        "Work these gaps in naturally: "
                        f"{', '.join(analysis.missing_keywords[:3])}."
                    ),
                )

        return suggestions[:3]

    def build_knowledge(
        self,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
    ) -> list[AgentKnowledgeItem]:
        """Build knowledge preparation entries from role and keyword gaps."""

        terms = analysis.missing_keywords[:3] or analysis.matched_keywords[:2]
        if not terms:
            terms = [job_reference.role]

        detail = (
            "准备成“概念解释 + 项目例子 + 常见追问”的结构。"
            if self.is_zh
            else "Prepare this as definition, project example, and likely follow-ups."
        )

        return [AgentKnowledgeItem(title=term, detail=detail) for term in terms]

    def build_quick_replies(
        self,
        edits: list[AgentResumeEditSuggestion],
    ) -> list[str]:
        """Return quick replies that keep the plan_execute workflow moving."""

        if not edits:
            return (
                ["我先补充真实经历", "粘贴目标 JD", "添加项目经历"]
                if self.is_zh
                else [
                    "I will add real experience first",
                    "Paste the target JD",
                    "Add a project section",
                ]
            )

        if self.is_zh:
            return ["预览这些修改", "调整模块顺序", "删除空模块", "新增项目经历"]

        return [
            "Preview these edits",
            "Reorder sections",
            "Delete empty sections",
            "Add a project section",
        ]

    def build_actions(
        self,
        edits: list[AgentResumeEditSuggestion],
    ) -> list[str]:
        """Return only actions that are valid for the generated response."""

        if edits:
            return ["plan", "execute", "summary", "bullet", "keywords"]

        return ["summary", "keywords"]

    def build_response_text(
        self,
        job_reference: JobReference,
        analysis: ResumeAnalysis,
        plan: list[EditPlanStep],
        edits: list[AgentResumeEditSuggestion],
    ) -> str:
        """Build the assistant message body shown in the conversation."""

        if not edits:
            if self.is_zh:
                return (
                    "我已完成 JD 来源解析和当前简历分析，但当前简历内容不足，"
                    "本轮不会生成可执行修改草稿，避免凭空编造经历。请先补充真实"
                    "项目、实习、教育或技能信息，再让我进行具体修改。"
                )

            return (
                "I resolved the JD context and analyzed the current resume, but "
                "there is not enough resume content to generate executable edits "
                "without inventing experience. Add real projects, internships, "
                "education, or skills before asking me to modify it."
            )

        if self.is_zh:
            jd_line = (
                f"检测到 JD URL：{job_reference.url}"
                if job_reference.url
                else f"未检测到 JD URL，已按岗位生成 JD 搜索查询：{job_reference.query}"
            )
            return (
                "我已按 plan_execute 范式完成本轮处理：先解析 JD 来源，再分析"
                f"当前简历「{analysis.title}」，随后生成 {len(plan)} 个计划步骤和 "
                f"{len(edits)} 个可执行草稿操作。\n\n{jd_line}\n\n"
                "这些操作会先作用到前端临时 JSON 草稿，预览高亮后你可以撤回或应用。"
            )

        jd_line = (
            f"Detected JD URL: {job_reference.url}"
            if job_reference.url
            else (
                f"No JD URL detected. Built this JD search query: {job_reference.query}"
            )
        )
        return (
            "I completed this pass with the plan_execute pattern: resolve JD "
            f"context, analyze the current resume ({analysis.title}), create "
            f"{len(plan)} plan steps, and return {len(edits)} executable draft "
            f"operations.\n\n{jd_line}\n\n"
            "The frontend applies these operations to a temporary JSON draft so "
            "you can review highlights, discard, or apply."
        )

    def find_project_section(
        self, analysis: ResumeAnalysis
    ) -> dict[str, object] | None:
        """Return the first project section, if present."""

        return next(
            (
                section
                for section in analysis.sections
                if section.get("kind") == "project"
            ),
            None,
        )

    def find_first_item_section(
        self,
        analysis: ResumeAnalysis,
    ) -> dict[str, object] | None:
        """Return the first section with at least one visible item."""

        for section in analysis.sections:
            items = section.get("items")
            if isinstance(items, list) and any(
                _has_item_content(item) for item in items
            ):
                return section

        return None

    def find_project_insert_index(self) -> int:
        """Choose a predictable insertion point for generated project sections."""

        sections_value = self.request.resume.get("sections")
        sections = sections_value if isinstance(sections_value, list) else []

        for index, section in enumerate(sections):
            if isinstance(section, dict) and section.get("kind") == "education":
                return index

        return len(sections)


def _parse_json_object(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from a model response when possible."""

    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?", "", value, flags=re.IGNORECASE).strip()
        value = re.sub(r"```$", "", value).strip()

    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None

    return parsed if isinstance(parsed, dict) else None


def _knowledge_items(value: object) -> list[AgentKnowledgeItem]:
    """Convert model-provided knowledge items into schema objects."""

    if not isinstance(value, list):
        return []

    items: list[AgentKnowledgeItem] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        title = item.get("title")
        detail = item.get("detail")
        if isinstance(title, str) and isinstance(detail, str):
            items.append(AgentKnowledgeItem(title=title, detail=detail))

    return items


def _llm_messages(
    request: AgentChatRequest,
    draft: AgentChatMessage,
    config: AgentLlmConfig,
) -> list[dict[str, str]]:
    """Build the provider prompt without exposing any API key material."""

    locale_name = "Chinese" if request.locale == "zh" else "English"
    system_parts = [
        SYSTEM_PROMPTS[request.locale],
        (
            "Return one JSON object only with keys: text, suggestions, "
            "knowledge, quickReplies. Do not include markdown fences. Keep "
            "edits aligned with the provided draft operations; do not generate "
            "a complete new resume."
        ),
    ]
    if config.system_prompt.strip():
        system_parts.append(config.system_prompt.strip())

    user_payload = {
        "responseLanguage": locale_name,
        "userPrompt": _current_prompt(request),
        "jobBrief": request.job_brief,
        "files": _agent_file_context(request.files),
        "keywordMatch": request.keyword_match,
        "resume": request.resume,
        "citationSources": [
            source.model_dump(mode="json", by_alias=True)
            for source in draft.sources
        ],
        "draftPlanText": draft.text,
        "draftTools": [
            tool.model_dump(mode="json", by_alias=True) for tool in draft.tools
        ],
        "draftEdits": [
            edit.model_dump(mode="json", by_alias=True) for edit in draft.edits
        ],
    }

    return [
        {"role": "system", "content": "\n\n".join(system_parts)},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        },
    ]


def _streaming_agent_llm_messages(
    request: AgentChatRequest,
    draft: AgentChatMessage,
    config: AgentLlmConfig,
) -> list[dict[str, str]]:
    """Build a stream-friendly prompt that returns visible text, not JSON."""

    locale_name = "Chinese" if request.locale == "zh" else "English"
    system_parts = [
        SYSTEM_PROMPTS[request.locale],
        (
            "Return natural language only in the requested language. Do not "
            "return JSON. Do not include markdown fences. Explain the analysis "
            "and planned draft changes succinctly. The frontend already has "
            "structured tools and edits, so do not invent extra tool calls."
        ),
    ]
    if config.system_prompt.strip():
        system_parts.append(config.system_prompt.strip())

    user_payload = {
        "responseLanguage": locale_name,
        "userPrompt": _current_prompt(request),
        "jobBrief": request.job_brief,
        "files": _agent_file_context(request.files),
        "keywordMatch": request.keyword_match,
        "resume": request.resume,
        "citationSources": [
            source.model_dump(mode="json", by_alias=True)
            for source in draft.sources
        ],
        "draftPlanText": draft.text,
        "draftTools": [
            tool.model_dump(mode="json", by_alias=True) for tool in draft.tools
        ],
        "draftEdits": [
            edit.model_dump(mode="json", by_alias=True) for edit in draft.edits
        ],
    }

    return [
        {"role": "system", "content": "\n\n".join(system_parts)},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        },
    ]


def _merge_llm_response(
    draft: AgentChatMessage,
    raw_text: str,
) -> AgentChatMessage:
    """Merge real model text with deterministic executable draft operations."""

    parsed = _parse_json_object(raw_text)
    text = raw_text
    suggestions = draft.suggestions
    knowledge = draft.knowledge
    quick_replies = draft.quick_replies

    if parsed:
        parsed_text = parsed.get("text")
        parsed_suggestions = _string_list(parsed.get("suggestions"))
        parsed_quick_replies = _string_list(parsed.get("quickReplies"))
        parsed_knowledge = _knowledge_items(parsed.get("knowledge"))

        if isinstance(parsed_text, str) and parsed_text.strip():
            text = parsed_text.strip()
        if parsed_suggestions:
            suggestions = parsed_suggestions[:4]
        if parsed_quick_replies:
            quick_replies = parsed_quick_replies[:4]
        if parsed_knowledge:
            knowledge = parsed_knowledge[:4]

    return AgentChatMessage(
        id=draft.id,
        role="assistant",
        tone=draft.tone,
        text=text,
        suggestions=suggestions,
        knowledge=knowledge,
        tools=draft.tools,
        sources=draft.sources,
        edits=draft.edits,
        quickReplies=quick_replies,
        actions=draft.actions,
    )


def _direct_llm_messages(
    request: AgentChatRequest,
    config: AgentLlmConfig,
) -> list[dict[str, str]]:
    """Build messages for normal chat that should not call agent tools."""

    locale_name = "Chinese" if request.locale == "zh" else "English"
    system_parts = [DIRECT_CHAT_SYSTEM_PROMPTS[request.locale]]
    if config.system_prompt.strip():
        system_parts.append(config.system_prompt.strip())

    context = {
        "responseLanguage": locale_name,
        "currentResume": request.resume,
        "jobBrief": request.job_brief,
        "keywordMatch": request.keyword_match,
    }
    messages = [
        {"role": "system", "content": "\n\n".join(system_parts)},
        {
            "role": "system",
            "content": (
                "Current editor context JSON:\n"
                f"{json.dumps(context, ensure_ascii=False)}"
            ),
        },
    ]

    conversation = request.messages or request.conversation
    for item in conversation[-8:]:
        text = item.text.strip()
        if text:
            messages.append({"role": item.role, "content": text})

    prompt = _current_prompt(request)
    if prompt and not any(
        message["role"] == "user" and message["content"] == prompt
        for message in messages
    ):
        messages.append({"role": "user", "content": prompt})

    return messages


def _agent_tool_messages(
    request: AgentChatRequest,
    config: AgentLlmConfig,
) -> list[dict[str, Any]]:
    """Build the prompt where the model decides which tools to call."""

    locale_name = "Chinese" if request.locale == "zh" else "English"
    system_parts = [
        SYSTEM_PROMPTS[request.locale],
        (
            "You must decide which provided tools to call. Do not claim a tool "
            "was used unless you called it. Prefer this order when relevant: "
            "jd_url_fetch or jd_reference_search, resume_analysis, edit_plan, "
            "edit_execute. Stop calling tools once you have enough evidence."
        ),
    ]
    if config.system_prompt.strip():
        system_parts.append(config.system_prompt.strip())

    user_payload = {
        "responseLanguage": locale_name,
        "userPrompt": _current_prompt(request),
        "jobBrief": request.job_brief,
        "files": _agent_file_context(request.files),
        "keywordMatch": request.keyword_match,
        "resume": request.resume,
        "conversationDepth": _conversation_depth(request),
    }

    return [
        {"role": "system", "content": "\n\n".join(system_parts)},
        {
            "role": "user",
            "content": json.dumps(user_payload, ensure_ascii=False),
        },
    ]


def _tool_call_assistant_message(
    content: str,
    tool_calls: list[LlmToolCall],
    reasoning: str = "",
) -> dict[str, Any]:
    """Serialize a model tool-call choice back into chat history."""

    message: dict[str, Any] = {
        "role": "assistant",
        "content": content or None,
        "tool_calls": [
            {
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": tool_call.raw_arguments,
                },
            }
            for tool_call in tool_calls
        ],
    }
    if reasoning:
        message["reasoning_content"] = reasoning

    return message


def _direct_llm_response(
    raw_text: str,
    *,
    message_id: str | None = None,
    reasoning: str = "",
) -> AgentChatMessage:
    """Return a plain assistant response with no tool-call metadata."""

    return AgentChatMessage(
        id=message_id or f"agent-msg-{uuid4().hex[:12]}",
        role="assistant",
        tone="default",
        text=raw_text,
        reasoning=reasoning,
        suggestions=[],
        knowledge=[],
        tools=[],
        sources=[],
        edits=[],
        quickReplies=[],
        actions=[],
    )


def _model_setup_message(request: AgentChatRequest) -> AgentChatMessage:
    """Build a direct setup guide when no usable model config exists."""

    is_zh = request.locale == "zh"
    text = (
        "当前还没有可用的大模型配置。请先在「大模型配置」中新增模型、填写 API Key "
        "并设为默认模型，然后再让 Agent 分析或修改简历。"
        if is_zh
        else (
            "No usable model configuration is available yet. Add a model, "
            "enter its API key, and set it as the default model before asking "
            "the agent to analyze or edit the resume."
        )
    )
    quick_replies = ["去配置模型"] if is_zh else ["Configure model"]

    return AgentChatMessage(
        id=f"agent-msg-{uuid4().hex[:12]}",
        role="assistant",
        tone="default",
        text=text,
        suggestions=[],
        knowledge=[],
        tools=[],
        sources=[],
        edits=[],
        quickReplies=quick_replies,
        actions=[],
    )


def _model_error_message(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    error: LlmRequestError,
) -> AgentChatMessage:
    """Build a provider failure message without falling back to mock output."""

    is_zh = request.locale == "zh"
    detail = _llm_error_detail(error)
    text = (
        f"已找到模型配置「{config.name}」，但调用模型失败。请检查 API 地址、"
        "API Key、模型名称和网络连通性后重试。"
        if is_zh
        else (
            f'Model config "{config.name}" was found, but the provider request '
            "failed. Check the API URL, API key, model name, and network access."
        )
    )
    if detail:
        label = "提供方返回" if is_zh else "Provider response"
        text = f"{text}\n\n{label}: {detail}"

    return AgentChatMessage(
        id=f"agent-msg-{uuid4().hex[:12]}",
        role="assistant",
        tone="default",
        text=text,
        suggestions=[],
        knowledge=[],
        tools=[],
        sources=[],
        edits=[],
        quickReplies=[],
        actions=[],
    )


def _llm_error_detail(error: LlmRequestError) -> str:
    """Return a bounded provider error excerpt safe for user-facing messages."""

    detail = str(error).replace("\n", " ").strip()
    if not detail:
        return ""

    return detail[:320]


class AgentToolRunner:
    """Execute only the tools explicitly selected by the model."""

    def __init__(self, executor: AgentPlanExecutor) -> None:
        self.executor = executor
        self.job_reference: JobReference | None = None
        self.analysis: ResumeAnalysis | None = None
        self.plan: list[EditPlanStep] = []
        self.edits: list[AgentResumeEditSuggestion] = []
        self.tools: list[AgentToolInvocation] = []

    def run(self, tool_call: LlmToolCall) -> tuple[AgentToolInvocation, dict[str, Any]]:
        """Execute a model-selected tool and return its tool-message payload."""

        if tool_call.name == "jd_url_fetch":
            tool = self.run_jd_url_fetch(tool_call)
        elif tool_call.name == "jd_reference_search":
            tool = self.run_jd_reference_search(tool_call)
        elif tool_call.name == "resume_analysis":
            tool = self.run_resume_analysis(tool_call)
        elif tool_call.name == "edit_plan":
            tool = self.run_edit_plan(tool_call)
        elif tool_call.name == "edit_execute":
            tool = self.run_edit_execute(tool_call)
        else:
            tool = AgentToolInvocation(
                id=tool_call.id,
                type=f"tool-{tool_call.name}",
                title=tool_call.name,
                state="output-error",
                input=tool_call.arguments,
                errorText=f"Unknown tool: {tool_call.name}",
            )

        self.tools.append(tool)
        return tool, self.tool_result(tool)

    def run_jd_url_fetch(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Fetch the JD URL chosen by the model."""

        url = str(tool_call.arguments.get("url") or "").strip()
        if not url:
            match = JD_URL_PATTERN.search(self.executor.prompt)
            url = match.group(0).rstrip(".,;，。；") if match else ""

        if not url:
            return AgentToolInvocation(
                id=tool_call.id,
                type="tool-jd_url_fetch",
                title="jd_url_fetch",
                state="output-error",
                input=tool_call.arguments,
                errorText="Missing JD URL.",
            )

        self.job_reference = self.executor.build_url_job_reference(
            url,
            self.executor.infer_target_role(),
        )
        return self.executor.build_jd_tool(self.job_reference, tool_call.id)

    def run_jd_reference_search(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Search the JD query chosen by the model."""

        role = str(tool_call.arguments.get("role") or "").strip()
        if not role:
            role = self.executor.infer_target_role()

        query = str(tool_call.arguments.get("query") or "").strip()
        if not query:
            query = self.executor.jd_search_query(role)

        self.job_reference = self.executor.build_search_job_reference(role, query)
        return self.executor.build_jd_tool(self.job_reference, tool_call.id)

    def run_resume_analysis(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Analyze the current resume only when the model asks for it."""

        self.analysis = self.executor.analyze_resume()
        return self.executor.build_resume_analysis_tool(self.analysis, tool_call.id)

    def run_edit_plan(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Create an edit plan if the model already gathered prerequisites."""

        if not self.job_reference or not self.analysis:
            return AgentToolInvocation(
                id=tool_call.id,
                type="tool-edit_plan",
                title="edit_plan",
                state="output-error",
                input=tool_call.arguments,
                errorText="Call a JD tool and resume_analysis before edit_plan.",
            )

        self.plan = self.executor.create_plan(self.job_reference, self.analysis)
        return self.executor.build_plan_tool(self.plan, tool_call.id)

    def run_edit_execute(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Execute draft edits if the model created a non-empty plan."""

        if not self.job_reference or not self.analysis:
            return AgentToolInvocation(
                id=tool_call.id,
                type="tool-edit_execute",
                title="edit_execute",
                state="output-error",
                input=tool_call.arguments,
                errorText="Call JD and resume analysis tools before edit_execute.",
            )

        if not self.plan:
            return AgentToolInvocation(
                id=tool_call.id,
                type="tool-edit_execute",
                title="edit_execute",
                state="output-error",
                input=tool_call.arguments,
                errorText="Call edit_plan before edit_execute.",
            )

        self.edits = self.executor.execute_plan(
            self.plan,
            self.job_reference,
            self.analysis,
        )
        return self.executor.build_execute_tool(self.plan, self.edits, tool_call.id)

    def tool_result(self, tool: AgentToolInvocation) -> dict[str, Any]:
        """Return compact JSON sent back to the model after tool execution."""

        return {
            "title": tool.title,
            "state": tool.state,
            "input": tool.input,
            "output": tool.output,
            "errorText": tool.error_text,
        }

    def build_message(self, message_id: str | None = None) -> AgentChatMessage:
        """Assemble an assistant payload from the tools the model used."""

        job_reference = self.job_reference or JobReference(
            mode="none",
            role=self.executor.infer_target_role(),
            query="",
            url=None,
            excerpt="",
        )
        analysis = self.analysis or ResumeAnalysis(
            title=self.executor.infer_target_role(),
            summary="",
            sections=[],
            empty_section_ids=[],
            matched_keywords=[],
            missing_keywords=[],
        )
        return self.executor.build_message_from_parts(
            job_reference=job_reference,
            analysis=analysis,
            plan=self.plan,
            edits=self.edits,
            tools=self.tools,
            message_id=message_id,
        )


def _running_model_tool(tool_call: LlmToolCall) -> AgentToolInvocation:
    """Build the running UI payload for a model-selected tool call."""

    return AgentToolInvocation(
        id=tool_call.id,
        type=f"tool-{tool_call.name}",
        title=tool_call.name,
        state="input-available",
        input=tool_call.arguments,
    )


def run_agent_tool_call_loop(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    on_tools: Callable[[list[AgentToolInvocation]], None] | None = None,
) -> AgentToolRunner:
    """Let the model choose tools, execute them, and return used-tool state."""

    executor = AgentPlanExecutor(request)
    runner = AgentToolRunner(executor)
    messages = _agent_tool_messages(request, config)

    for _ in range(5):
        response = complete_chat_tool_call(config, messages, AGENT_TOOL_SCHEMAS)
        if not response.tool_calls:
            break

        messages.append(
            _tool_call_assistant_message(
                response.content,
                response.tool_calls,
                response.reasoning,
            ),
        )
        for tool_call in response.tool_calls:
            if on_tools:
                on_tools([*runner.tools, _running_model_tool(tool_call)])
            tool, result = runner.run(tool_call)
            if on_tools:
                on_tools(runner.tools)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                },
            )

    return runner


def build_agent_message(
    request: AgentChatRequest,
    conn: Connection,
) -> AgentChatMessage:
    """Build a real model-backed plan_execute assistant message."""

    config = resolve_agent_llm_config(conn, request.model_config_data)
    if config is None:
        return _model_setup_message(request)

    should_use_plan_execute = _should_use_plan_execute(request)
    try:
        if should_use_plan_execute:
            runner = run_agent_tool_call_loop(request, config)
            draft = runner.build_message() if runner.tools else None
            messages = (
                _llm_messages(request, draft, config)
                if draft
                else _direct_llm_messages(request, config)
            )
        else:
            draft = None
            messages = _direct_llm_messages(request, config)

        raw_response = complete_chat(config, messages)
    except LlmRequestError as exc:
        return _model_error_message(request, config, exc)

    if draft:
        return _merge_llm_response(draft, raw_response)

    return _direct_llm_response(raw_response)


def _sse_event(event_name: str, payload: dict[str, object]) -> str:
    """Serialize one server-sent event frame."""

    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return f"event: {event_name}\ndata: {data}\n\n"


def _message_delta_payload(message: AgentChatMessage) -> dict[str, object]:
    """Return mutable assistant fields for an SSE message_delta event."""

    message_payload = message.model_dump(mode="json", by_alias=True)

    return {
        "text": message_payload["text"],
        "reasoning": message_payload["reasoning"],
        "suggestions": message_payload["suggestions"],
        "knowledge": message_payload["knowledge"],
        "tools": message_payload["tools"],
        "sources": message_payload["sources"],
        "edits": message_payload["edits"],
        "quickReplies": message_payload["quickReplies"],
        "actions": message_payload["actions"],
    }


def _partial_message_delta_payload(**fields: object) -> dict[str, object]:
    """Return a partial SSE patch for fields that changed during streaming."""

    return fields


def _tool_payloads(tools: list[AgentToolInvocation]) -> list[dict[str, object]]:
    """Serialize streamed tool calls using frontend-facing field aliases."""

    return [tool.model_dump(mode="json", by_alias=True) for tool in tools]


def _tool_snapshot_event(tools: list[AgentToolInvocation]) -> str:
    """Return an SSE event containing the currently visible tool list."""

    return _sse_event(
        "tools",
        {
            "type": "tools",
            "message": _partial_message_delta_payload(tools=_tool_payloads(tools)),
        },
    )


def stream_agent_message(message: AgentChatMessage) -> Iterator[str]:
    """Yield a chat message as incremental SSE events."""

    message_payload = message.model_dump(mode="json", by_alias=True)
    text = message.text

    yield _sse_event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message.id,
                "role": message.role,
                "tone": message.tone,
                "text": "",
            },
        },
    )

    chunk_size = 24
    for index in range(0, len(text), chunk_size):
        yield _sse_event(
            "text_delta",
            {
                "type": "text_delta",
                "delta": text[index : index + chunk_size],
            },
        )

    yield _sse_event(
        "message_delta",
        {
            "type": "message_delta",
            "message": _message_delta_payload(message),
        },
    )
    yield _sse_event(
        "message_done", {"type": "message_done", "message": message_payload}
    )


def stream_agent_response(
    request: AgentChatRequest,
    conn: Connection,
    on_complete: Callable[[AgentChatMessage], None] | None = None,
) -> Iterator[str]:
    """Stream an agent response while the provider is still generating text."""

    config = resolve_agent_llm_config(conn, request.model_config_data)
    if config is None:
        message = _model_setup_message(request)
        yield from stream_agent_message(message)
        on_complete_message(on_complete, message)
        return

    should_use_plan_execute = _should_use_plan_execute(request)
    executor = AgentPlanExecutor(request) if should_use_plan_execute else None
    draft: AgentChatMessage | None = None
    message_id = f"agent-msg-{uuid4().hex[:12]}"

    yield _sse_event(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": message_id,
                "role": "assistant",
                "tone": "default",
                "text": "",
                "reasoning": "",
            },
        },
    )

    raw_parts: list[str] = []
    reasoning_parts: list[str] = []

    try:
        if executor:
            runner = AgentToolRunner(executor)
            tool_messages = _agent_tool_messages(request, config)
            for _ in range(5):
                tool_response = complete_chat_tool_call(
                    config,
                    tool_messages,
                    AGENT_TOOL_SCHEMAS,
                )
                if not tool_response.tool_calls:
                    break

                tool_messages.append(
                    _tool_call_assistant_message(
                        tool_response.content,
                        tool_response.tool_calls,
                        tool_response.reasoning,
                    ),
                )
                for tool_call in tool_response.tool_calls:
                    yield _tool_snapshot_event(
                        [*runner.tools, _running_model_tool(tool_call)],
                    )
                    tool, result = runner.run(tool_call)
                    yield _tool_snapshot_event(runner.tools)
                    tool_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": json.dumps(result, ensure_ascii=False),
                        },
                    )

            if runner.tools:
                draft = runner.build_message(message_id=message_id)

        messages = (
            _streaming_agent_llm_messages(request, draft, config)
            if draft
            else _direct_llm_messages(request, config)
        )
        for delta in complete_chat_stream(config, messages):
            if delta.kind == "reasoning":
                reasoning_parts.append(delta.delta)
                yield _sse_event(
                    "reasoning_delta",
                    {
                        "type": "reasoning_delta",
                        "delta": delta.delta,
                    },
                )
                continue

            raw_parts.append(delta.delta)
            yield _sse_event(
                "text_delta",
                {
                    "type": "text_delta",
                    "delta": delta.delta,
                },
            )

        raw_response = "".join(raw_parts).strip()
        if not raw_response:
            raise LlmRequestError("Model provider returned an empty response.")
    except LlmRequestError as exc:
        message = _model_error_message(request, config, exc)
        yield _sse_event(
            "message_delta",
            {
                "type": "message_delta",
                "message": _message_delta_payload(message),
            },
        )
        yield _sse_event(
            "message_done",
            {
                "type": "message_done",
                "message": message.model_dump(mode="json", by_alias=True),
            },
        )
        on_complete_message(on_complete, message)
        return

    reasoning = "".join(reasoning_parts).strip()
    message = (
        draft.model_copy(update={"text": raw_response})
        if draft
        else _direct_llm_response(
            raw_response,
            message_id=message_id,
            reasoning=reasoning,
        )
    )
    if draft and reasoning:
        message = message.model_copy(update={"reasoning": reasoning})

    yield _sse_event(
        "message_delta",
        {
            "type": "message_delta",
            "message": _message_delta_payload(message),
        },
    )
    yield _sse_event(
        "message_done",
        {
            "type": "message_done",
            "message": message.model_dump(mode="json", by_alias=True),
        },
    )
    on_complete_message(on_complete, message)


def on_complete_message(
    callback: Callable[[AgentChatMessage], None] | None,
    message: AgentChatMessage,
) -> None:
    """Call the streaming completion hook when the router needs persistence."""

    if callback:
        callback(message)
