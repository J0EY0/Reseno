import json
import re
from collections import OrderedDict
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from app.schemas.agent import (
    AgentChatMessage,
    AgentFinishMissing,
    AgentResumeEditSuggestion,
    AgentToolInvocation,
    AgentTransactionState,
)
from app.services.llm import LlmRequestError, LlmToolCall
from app.services.resume_document_contract import (
    ResumeDocumentContractError,
    validate_resume_document,
)

from ..attachments import AgentAttachmentError, current_request_attachments
from ..compat import get_agent_api
from ..edit_authorization import (
    derive_edit_authorization,
    unauthorized_edit_issues,
    unauthorized_plan_issues,
)
from ..editing import (
    _apply_edit_operations,
    _edit_observations,
    _merge_edits,
    _model_edit_suggestions_with_diagnostics,
    _model_plan_steps,
)
from ..evidence import ground_edit_evidence
from ..executor import AgentPlanExecutor
from ..integrations import (
    URL_PATTERN,
    WebReference,
    WebSearchReference,
    WebSearchResult,
    _fetch_web_reference,
    _search_web_reference,
    _search_web_reference_summary,
)
from ..integrations.web import _relevant_web_url
from ..localization import agent_text
from ..materials import DEFAULT_MATERIAL_CANDIDATES, extract_resume_materials
from ..models import (
    FINISH_MISSING_SET,
    EditPlanStep,
    ResumeAnalysis,
    TargetOpportunityKind,
    TargetReference,
)
from ..policy import (
    capability_policy_for_request,
    has_explicit_delete_intent,
    has_explicit_merge_intent,
    has_explicit_reorder_intent,
    tool_block_reason,
)
from ..privacy import sanitize_agent_resume, sanitize_agent_text, sanitize_agent_value
from ..quality import (
    blocking_quality_issues,
    draft_quality_issues,
    normalization_loss_issues,
)
from ..runtime.context import AgentRuntimeContext
from ..target_context import (
    clears_target_context,
    exact_job_description_from_prompt,
    prompt_declares_partial_job_description,
    rejects_target_context_update,
    target_context_update_is_grounded,
    update_target_context,
)
from .registry import ALL_KNOWN_TOOL_NAMES, agent_tool_spec
from .structured import (
    classify_skills_entries,
    draft_diff_summary,
    lookup_resume,
    merge_item_entries,
    move_item_entries,
    split_item_entries,
)

WEB_FETCH_PURPOSES = {
    "jd",
    "project_reference",
    "portfolio_reference",
    "company_reference",
    "target_context",
}
WEB_SEARCH_PURPOSES = {"jd", "target_context", "company_reference"}
MAX_WEB_SEARCH_QUERY_COUNT = 5
MAX_WEB_SEARCH_RESULT_COUNT = 10
MAX_WEB_SEARCH_QUERY_LENGTH = 160
MAX_WEB_SEARCH_CACHE_ENTRIES = 32
_LOCAL_TOOL_STABLE_REFERENCES = ("executor", "policy")
_OUTBOUND_REDACTION_MARKERS = (
    "[redacted_email]",
    "[redacted_phone]",
    "[redacted_name]",
)

_OUTBOUND_EMAIL_PATTERN = re.compile(
    r"(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"
    r"(?![A-Z0-9.-])",
    flags=re.IGNORECASE,
)
_OUTBOUND_PHONE_PATTERN = re.compile(
    r"(?<![A-Z0-9@])(?:\+?\d[\d\s().-]{5,}\d)(?![A-Z0-9@])",
    flags=re.IGNORECASE,
)
_YEAR_RANGE_PATTERN = re.compile(
    r"(?:19|20)\d{2}\s*[-/]\s*(?:19|20)\d{2}",
)


def _sanitize_outbound_search_query(
    value: str,
    *,
    hidden_terms: tuple[str, ...] = (),
) -> str:
    """Remove common direct identifiers before a query crosses the network."""

    # Reuse the model privacy boundary so identity terms are handled
    # consistently, then remove its markers instead of leaking them to search.
    sanitized = sanitize_agent_text(value, hidden_terms=hidden_terms)
    for marker in _OUTBOUND_REDACTION_MARKERS:
        sanitized = sanitized.replace(f"+{marker}", " ")
        sanitized = sanitized.replace(marker, " ")
    without_email = _OUTBOUND_EMAIL_PATTERN.sub(" ", sanitized)

    def remove_phone(match: re.Match[str]) -> str:
        candidate = match.group(0).strip()
        if _YEAR_RANGE_PATTERN.fullmatch(candidate):
            return candidate
        return " " if len(re.sub(r"\D", "", candidate)) >= 7 else candidate

    without_phone = _OUTBOUND_PHONE_PATTERN.sub(remove_phone, without_email)
    return " ".join(without_phone.split()).strip()[:MAX_WEB_SEARCH_QUERY_LENGTH]


class AgentToolRunner:
    """Execute only the tools explicitly selected by the model."""

    def __init__(self, executor: AgentPlanExecutor) -> None:
        self.executor = executor
        self.policy = capability_policy_for_request(executor.request)
        self.session_target_context = executor.target_context
        self.base_resume = deepcopy(executor.resume)
        self.draft_resume = deepcopy(self.base_resume)
        self.edit_authorization = derive_edit_authorization(
            executor.request,
            self.base_resume,
        )
        self.target_reference: TargetReference | None = None
        self.analysis: ResumeAnalysis | None = None
        self.plan: list[EditPlanStep] = []
        self.edits: list[AgentResumeEditSuggestion] = []
        self.tools: list[AgentToolInvocation] = []
        self.finished = False
        self.finish_reason = ""
        self.finish_status = ""
        self.finish_missing: list[AgentFinishMissing] = []
        self.terminal_text = ""
        self.edit_revision = 0
        self.semantic_retry_pending = False
        self.failed_batch_fingerprint = ""
        self._semantic_error_fingerprints: set[str] = set()
        self.transaction_failed = False
        self.transaction_committed = False
        # Set only after an explicit provider rejection causes the single
        # current-request original-file fallback to extracted text.
        self.native_attachment_text_fallback_used = False
        self._tool_call_results: dict[
            str,
            tuple[str, AgentToolInvocation, dict[str, Any]],
        ] = {}
        self._web_search_cache: OrderedDict[
            tuple[tuple[str, ...], int, str],
            WebSearchReference,
        ] = OrderedDict()
        # URL provenance is a separate boundary from SSRF validation: only
        # user-supplied context and this turn's search results may be fetched.
        self.authorized_web_fetch_urls: set[str] = set()
        self.remember_authorized_web_urls(
            *self.web_urls_in_text(executor.prompt),
            *self.web_urls_in_text(executor.target_brief),
        )

    @staticmethod
    def canonical_web_url(value: str) -> str:
        """Normalize a URL for exact provenance comparisons, not URL rewriting."""

        candidate = value.strip().rstrip(".,;:!?，。；：！？]}'】》")
        try:
            parsed = urlsplit(candidate)
        except ValueError:
            return ""
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
            return ""

        path = parsed.path or "/"
        if path != "/":
            path = path.rstrip("/")
        return urlunsplit(
            (
                parsed.scheme.casefold(),
                parsed.netloc.casefold(),
                path,
                parsed.query,
                "",
            ),
        )

    @classmethod
    def web_urls_in_text(cls, value: str) -> tuple[str, ...]:
        """Extract canonical URLs from user-controlled text fields."""

        urls: list[str] = []
        for match in URL_PATTERN.finditer(value):
            normalized = cls.canonical_web_url(match.group(0))
            if normalized:
                urls.append(normalized)
        return tuple(urls)

    def remember_authorized_web_urls(self, *urls: str) -> None:
        """Record URLs whose origin is trusted for this runner invocation."""

        for url in urls:
            normalized = self.canonical_web_url(url)
            if normalized:
                self.authorized_web_fetch_urls.add(normalized)

    def remember_web_search_result(self, result: WebSearchResult) -> None:
        """Authorize only URLs actually returned by the current search turn."""

        self.remember_authorized_web_urls(result.url, result.final_url)

    def web_search_cache_key(
        self,
        queries: list[str],
        max_results: int,
    ) -> tuple[tuple[str, ...], int, str]:
        """Return the request identity used only within this Agent run."""

        normalized_queries = tuple(
            " ".join(query.split()).casefold() for query in queries
        )
        locale = " ".join(self.executor.request.locale.split()).casefold()
        return normalized_queries, max_results, locale

    def cached_web_search(
        self,
        queries: list[str],
        max_results: int,
    ) -> WebSearchReference | None:
        """Return one reusable result and refresh its bounded LRU position."""

        key = self.web_search_cache_key(queries, max_results)
        cached = self._web_search_cache.get(key)
        if cached is None:
            return None

        self._web_search_cache.move_to_end(key)
        return WebSearchReference(
            query=queries[0] if queries else cached.query,
            results=cached.results,
            query_count=len(queries),
            result_count=cached.result_count,
            error=cached.error,
            timed_out=cached.timed_out,
            partial=cached.partial,
        )

    def cache_web_search(
        self,
        queries: list[str],
        max_results: int,
        summary: WebSearchReference,
    ) -> None:
        """Cache complete success or an explicitly useful partial success."""

        complete_success = (
            summary.primary is not None
            and summary.error is None
            and not summary.timed_out
            and not summary.partial
        )
        reusable_partial = (
            summary.primary is not None and summary.error is None and summary.partial
        )
        if not complete_success and not reusable_partial:
            return

        key = self.web_search_cache_key(queries, max_results)
        self._web_search_cache[key] = summary
        self._web_search_cache.move_to_end(key)
        while len(self._web_search_cache) > MAX_WEB_SEARCH_CACHE_ENTRIES:
            self._web_search_cache.popitem(last=False)

    def is_authorized_web_fetch_url(self, url: str) -> bool:
        normalized = self.canonical_web_url(url)
        return bool(normalized) and normalized in self.authorized_web_fetch_urls

    @staticmethod
    def web_excerpt_boundary(
        result: WebReference | WebSearchResult | None,
    ) -> dict[str, Any] | None:
        """Return the normalized source range selected by the fetch parser."""

        start = getattr(result, "excerpt_start", None)
        end = getattr(result, "excerpt_end", None)
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            return None

        boundary: dict[str, Any] = {"start": start, "end": end}
        section = getattr(result, "excerpt_section", "")
        if isinstance(section, str) and section:
            boundary["section"] = section
        return boundary

    async def run(
        self,
        tool_call: LlmToolCall,
        runtime: AgentRuntimeContext,
    ) -> tuple[AgentToolInvocation, dict[str, Any]]:
        """Execute a model-selected tool through the async runtime."""

        cached = self._cached_tool_call_result(tool_call)
        if cached is not None:
            return cached
        started_at = self._tool_timestamp()

        blocked_tool = self.blocked_tool_call(tool_call)
        if blocked_tool:
            if tool_call.name != "finish":
                self.tools.append(blocked_tool)
            return self._remember_tool_call_result(
                tool_call,
                blocked_tool,
                self.tool_result(blocked_tool),
                started_at,
            )

        spec = agent_tool_spec(tool_call.name)
        if spec is None:
            tool = self.unknown_tool(tool_call)
            self.tools.append(tool)
            return self._remember_tool_call_result(
                tool_call,
                tool,
                self.tool_result(tool),
                started_at,
            )

        if spec.execution == "sync":
            initial_state = self._local_tool_state_snapshot()
            tool, result, final_state = await runtime.run_sync(
                self._run_local_tool_isolated,
                tool_call,
                initial_state,
            )
            # No await may occur between this final cancellation gate and the
            # one-step state swap into the live runner.
            await runtime.checkpoint()
            self._commit_local_tool_state(final_state)
            return self._remember_tool_call_result(
                tool_call,
                tool,
                result,
                started_at,
            )

        handler = getattr(self, spec.handler_name)
        tool = await handler(tool_call, runtime)
        self.tools.append(tool)
        return self._remember_tool_call_result(
            tool_call,
            tool,
            self.tool_result(tool),
            started_at,
        )

    @staticmethod
    def _tool_timestamp() -> str:
        """Return a stable UTC timestamp for public tool observations."""

        return (
            datetime.now(UTC)
            .isoformat(timespec="milliseconds")
            .replace(
                "+00:00",
                "Z",
            )
        )

    @staticmethod
    def _tool_call_fingerprint(tool_call: LlmToolCall) -> str:
        """Return the provider-independent identity of one tool request."""

        return json.dumps(
            {"name": tool_call.name, "arguments": tool_call.arguments},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _cached_tool_call_result(
        self,
        tool_call: LlmToolCall,
    ) -> tuple[AgentToolInvocation, dict[str, Any]] | None:
        """Replay an identical completed call and reject conflicting reuse."""

        if not tool_call.id.strip():
            self.fail_transaction()
            raise LlmRequestError("Model tool call id must be non-empty.")

        cached = self._tool_call_results.get(tool_call.id)
        if cached is None:
            return None

        fingerprint, tool, result = cached
        if fingerprint != self._tool_call_fingerprint(tool_call):
            self.fail_transaction()
            raise LlmRequestError(
                "Model reused a tool call id with different arguments.",
            )
        if self.semantic_retry_pending:
            self.fail_transaction()
        return deepcopy(tool), deepcopy(result)

    def _remember_tool_call_result(
        self,
        tool_call: LlmToolCall,
        tool: AgentToolInvocation,
        result: dict[str, Any],
        started_at: str,
    ) -> tuple[AgentToolInvocation, dict[str, Any]]:
        """Record one completed invocation for safe provider retries."""

        completed_tool = tool.model_copy(
            update={
                "started_at": started_at,
                "completed_at": self._tool_timestamp(),
            },
        )
        for index in range(len(self.tools) - 1, -1, -1):
            candidate = self.tools[index]
            if candidate.id == tool.id and candidate.title == tool.title:
                self.tools[index] = completed_tool
                break
        self._tool_call_results[tool_call.id] = (
            self._tool_call_fingerprint(tool_call),
            deepcopy(completed_tool),
            deepcopy(result),
        )
        return completed_tool, result

    def _local_tool_state_snapshot(self) -> dict[str, Any]:
        """Copy every run-scoped field that a local tool may mutate."""

        return deepcopy(vars(self))

    def _run_local_tool_isolated(
        self,
        tool_call: LlmToolCall,
        initial_state: dict[str, Any],
    ) -> tuple[AgentToolInvocation, dict[str, Any], dict[str, Any]]:
        """Execute one local tool against a detached runner snapshot."""

        isolated = object.__new__(type(self))
        isolated.__dict__ = initial_state
        tool, result = isolated._run_local_tool(tool_call)
        return tool, result, isolated._local_tool_state_snapshot()

    def _commit_local_tool_state(self, state: dict[str, Any]) -> None:
        """Atomically replace live run state after cancellation checks pass."""

        stable_references = {
            name: vars(self)[name] for name in _LOCAL_TOOL_STABLE_REFERENCES
        }
        self.__dict__ = {**state, **stable_references}
        self.executor.set_target_context(self.session_target_context)

    def _run_local_tool(
        self,
        tool_call: LlmToolCall,
    ) -> tuple[AgentToolInvocation, dict[str, Any]]:
        """Run a CPU/local-memory tool without network I/O."""

        blocked_tool = self.blocked_tool_call(tool_call)
        if blocked_tool:
            if tool_call.name != "finish":
                self.tools.append(blocked_tool)
            return blocked_tool, self.tool_result(blocked_tool)

        spec = agent_tool_spec(tool_call.name)
        if spec is None or spec.execution != "sync":
            tool = self.unknown_tool(tool_call)
        else:
            handler = getattr(self, spec.handler_name)
            tool = handler(tool_call)

        if tool_call.name != "finish":
            self.tools.append(tool)
        return tool, self.tool_result(tool)

    def blocked_tool_call(self, tool_call: LlmToolCall) -> AgentToolInvocation | None:
        """Return a policy error for known tools outside this turn's capability."""

        if tool_call.name not in ALL_KNOWN_TOOL_NAMES:
            return None

        reason_key = tool_block_reason(self.policy, tool_call.name)
        if not reason_key:
            return None

        return AgentToolInvocation(
            id=tool_call.id,
            type=f"tool-{tool_call.name}",
            title=tool_call.name,
            state="output-error",
            input=tool_call.arguments,
            output={"blocked": True},
            errorText=agent_text(self.executor.request.locale, reason_key),
        )

    def unknown_tool(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Return a model-observable error for unsupported tool names."""

        return AgentToolInvocation(
            id=tool_call.id,
            type=f"tool-{tool_call.name}",
            title=tool_call.name,
            state="output-error",
            input=tool_call.arguments,
            errorText=agent_text(
                self.executor.request.locale,
                "error.unknown_tool",
                name=tool_call.name,
            ),
        )

    async def run_web_fetch_async(
        self,
        tool_call: LlmToolCall,
        runtime: AgentRuntimeContext,
    ) -> AgentToolInvocation:
        """Fetch a user-provided URL for an explicit reference purpose."""

        purpose = str(tool_call.arguments.get("purpose") or "").strip()
        if purpose not in WEB_FETCH_PURPOSES:
            return self.web_tool_error(
                tool_call,
                "error.web_fetch_purpose_required",
            )

        url = str(tool_call.arguments.get("url") or "").strip()
        if not url and purpose == "jd":
            match = URL_PATTERN.search(self.executor.prompt)
            url = match.group(0).rstrip(".,;，。；") if match else ""

        if not url:
            return self.web_tool_error(tool_call, "error.web_fetch_url_missing")

        if not self.is_authorized_web_fetch_url(url):
            return self.web_tool_error(
                tool_call,
                "error.web_fetch_failed",
                reason="url_not_authorized",
            )

        target, kind, exact_job_description = self.target_context(
            tool_call,
            purpose,
        )
        agent_api = get_agent_api()
        if agent_api._fetch_web_reference is not _fetch_web_reference:
            web_reference = await runtime.run_sync(
                agent_api._fetch_web_reference,
                url,
            )
        else:
            relevance_query = " ".join(
                part
                for part in (target, self.executor.target_brief, self.executor.prompt)
                if part
            )

            async def fetch_reference() -> WebReference | None:
                return await agent_api._async_fetch_web_reference(
                    _relevant_web_url(
                        url,
                        relevance_query=relevance_query,
                        reference_title=target,
                    ),
                )

            web_reference = await runtime.run_async(
                fetch_reference,
            )

        source_url = (
            str(getattr(web_reference, "final_url", "") or url)
            if web_reference
            else url
        )
        excerpt_boundary = self.web_excerpt_boundary(web_reference)

        if purpose != "jd":
            if not web_reference:
                return self.web_tool_error(tool_call, "error.web_fetch_failed")

            if purpose == "target_context":
                self.target_reference = (
                    self.executor.build_url_target_reference_from_web(
                        source_url,
                        target,
                        web_reference,
                        kind=kind,
                        exact_job_description=False,
                    )
                )

            # Candidate-owned project and portfolio pages can support supplied
            # resume material. Other public pages describe only the target.
            can_support_resume_facts = purpose in {
                "project_reference",
                "portfolio_reference",
            }
            return AgentToolInvocation(
                id=tool_call.id,
                type=f"tool-{tool_call.name}",
                title=tool_call.name,
                state="output-available",
                input={"url": url, "purpose": purpose},
                output=sanitize_agent_value(
                    {
                        "purpose": purpose,
                        "url": source_url,
                        "title": web_reference.title,
                        "excerpt": web_reference.excerpt,
                        "excerptBoundary": excerpt_boundary,
                        "canSupportResumeFacts": can_support_resume_facts,
                        "personalExperienceEvidence": can_support_resume_facts,
                    },
                    hidden_terms=self.executor.hidden_terms,
                ),
            )

        self.target_reference = self.executor.build_url_target_reference_from_web(
            source_url,
            target,
            web_reference,
            kind=kind,
            exact_job_description=exact_job_description,
        )
        tool = self.executor.build_target_reference_tool(
            self.target_reference,
            tool_call.id,
            tool_name=tool_call.name,
        )
        if isinstance(tool.output, dict) and excerpt_boundary:
            tool.output["excerptBoundary"] = excerpt_boundary
        return tool

    async def run_web_search_async(
        self,
        tool_call: LlmToolCall,
        runtime: AgentRuntimeContext,
    ) -> AgentToolInvocation:
        """Search external reference context chosen by the model."""

        purpose = str(tool_call.arguments.get("purpose") or "").strip()
        if purpose not in WEB_SEARCH_PURPOSES:
            return self.web_tool_error(
                tool_call,
                "error.web_search_purpose_required",
            )

        target, kind, exact_job_description = self.target_context(
            tool_call,
            purpose,
        )

        queries = self.web_search_queries(
            tool_call,
            target,
            kind=kind,
            exact_job_description=exact_job_description,
        )
        if not queries:
            return self.web_tool_error(
                tool_call,
                "error.web_search_failed",
                reason="safe_query_required",
            )

        query = queries[0]
        has_queries_argument = isinstance(tool_call.arguments.get("queries"), list)
        max_results = self.web_search_max_results(
            tool_call,
            default=MAX_WEB_SEARCH_RESULT_COUNT if has_queries_argument else 1,
        )
        await runtime.checkpoint()

        if len(queries) > 1 or has_queries_argument or max_results > 1:
            return await self.run_web_search_summary_async(
                tool_call,
                runtime,
                target=target,
                kind=kind,
                exact_job_description=exact_job_description,
                purpose=purpose,
                queries=queries,
                max_results=max_results,
            )

        summary = self.cached_web_search(queries, max_results)
        if summary is None:
            agent_api = get_agent_api()
            if agent_api._search_web_reference is not _search_web_reference:
                search_result, result_count, search_error = await runtime.run_sync(
                    agent_api._search_web_reference,
                    query,
                )
            else:
                search_result, result_count, search_error = await runtime.run_async(
                    agent_api._async_search_web_reference,
                    query,
                )

            summary = WebSearchReference(
                query=query,
                results=(search_result,) if search_result else (),
                query_count=1,
                result_count=result_count,
                error=search_error,
            )
            self.cache_web_search(queries, max_results, summary)
        else:
            search_result = summary.primary
            result_count = summary.result_count
            search_error = summary.error

        if search_result:
            self.remember_web_search_result(search_result)
        excerpt_boundary = self.web_excerpt_boundary(search_result)

        if purpose != "jd":
            if search_error or not search_result:
                return AgentToolInvocation(
                    id=tool_call.id,
                    type=f"tool-{tool_call.name}",
                    title=tool_call.name,
                    state="output-error",
                    input={
                        "query": query,
                        "purpose": purpose,
                        "language": self.executor.request.locale,
                    },
                    output={"resultCount": result_count},
                    errorText=search_error
                    or agent_text(
                        self.executor.request.locale,
                        "error.web_search_failed",
                    ),
                )

            if purpose == "target_context":
                self.target_reference = (
                    self.executor.build_search_target_reference_from_result(
                        target,
                        query,
                        search_result,
                        result_count,
                        search_error,
                        kind=kind,
                        exact_job_description=False,
                    )
                )
            return AgentToolInvocation(
                id=tool_call.id,
                type=f"tool-{tool_call.name}",
                title=tool_call.name,
                state="output-available",
                input={
                    "query": query,
                    "purpose": purpose,
                    "language": self.executor.request.locale,
                },
                output=sanitize_agent_value(
                    {
                        "purpose": purpose,
                        "query": query,
                        "resultCount": result_count,
                        "url": search_result.url,
                        "title": search_result.title,
                        "excerpt": search_result.excerpt,
                        "excerptBoundary": excerpt_boundary,
                        "personalExperienceEvidence": False,
                    },
                    hidden_terms=self.executor.hidden_terms,
                ),
            )

        self.target_reference = self.executor.build_search_target_reference_from_result(
            target,
            query,
            search_result,
            result_count,
            search_error,
            kind=kind,
            exact_job_description=exact_job_description,
        )
        tool = self.executor.build_target_reference_tool(
            self.target_reference,
            tool_call.id,
            tool_name=tool_call.name,
        )
        if isinstance(tool.output, dict) and excerpt_boundary:
            tool.output["excerptBoundary"] = excerpt_boundary
        return tool

    def target_context(
        self,
        tool_call: LlmToolCall,
        purpose: str,
    ) -> tuple[str, TargetOpportunityKind, bool]:
        """Normalize legacy tool arguments into target-opportunity context."""

        exact_job_description = purpose == "jd"
        # `role` remains accepted because it is part of the existing tool protocol.
        supplied_target = str(
            tool_call.arguments.get("target") or tool_call.arguments.get("role") or "",
        ).strip()
        query = str(tool_call.arguments.get("query") or "").strip()
        context = supplied_target or query
        kind: TargetOpportunityKind = (
            "employment"
            if exact_job_description
            else self.executor.infer_target_kind(context)
        )
        target = supplied_target or self.executor.infer_target(kind)
        return target, kind, exact_job_description

    def web_search_queries(
        self,
        tool_call: LlmToolCall,
        target: str,
        *,
        kind: TargetOpportunityKind | None = None,
        exact_job_description: bool = False,
    ) -> list[str]:
        """Return deduplicated search queries for one web_search invocation."""

        resolved_kind = kind or self.executor.infer_target_kind(target)
        raw_values: list[str] = []
        query = str(tool_call.arguments.get("query") or "").strip()
        if query:
            raw_values.append(query)

        queries = tool_call.arguments.get("queries")
        if isinstance(queries, list):
            raw_values.extend(value for value in queries if isinstance(value, str))

        normalized: list[str] = []
        seen: set[str] = set()
        for value in raw_values:
            # This is the outbound privacy boundary. Never substitute the full
            # user prompt when the model omits a query.
            compacted = _sanitize_outbound_search_query(
                value,
                hidden_terms=self.executor.hidden_terms,
            )
            key = compacted.casefold()
            if not compacted or key in seen:
                continue

            normalized.append(compacted)
            seen.add(key)
            if len(normalized) >= MAX_WEB_SEARCH_QUERY_COUNT:
                break

        if normalized:
            return normalized

        supplied_target = str(
            tool_call.arguments.get("target") or tool_call.arguments.get("role") or "",
        ).strip()
        # Conversation target context is structured and privacy-sanitized; the
        # full prompt is never a safe outbound fallback.
        fallback_target = supplied_target or (
            target if self.executor.target_brief else ""
        )
        safe_target = _sanitize_outbound_search_query(
            fallback_target,
            hidden_terms=self.executor.hidden_terms,
        )
        if not safe_target:
            return []

        fallback_query = self.executor.target_search_query(
            safe_target,
            resolved_kind,
            exact_job_description=exact_job_description,
        )
        sanitized_fallback = _sanitize_outbound_search_query(
            fallback_query,
            hidden_terms=self.executor.hidden_terms,
        )
        return [sanitized_fallback] if sanitized_fallback else []

    def web_search_max_results(self, tool_call: LlmToolCall, *, default: int) -> int:
        """Return the bounded maxResults value for aggregated web_search."""

        value = tool_call.arguments.get("maxResults")
        if not isinstance(value, int) or isinstance(value, bool):
            return default

        return min(max(value, 1), MAX_WEB_SEARCH_RESULT_COUNT)

    async def run_web_search_summary_async(
        self,
        tool_call: LlmToolCall,
        runtime: AgentRuntimeContext,
        *,
        target: str,
        kind: TargetOpportunityKind,
        exact_job_description: bool,
        purpose: str,
        queries: list[str],
        max_results: int,
    ) -> AgentToolInvocation:
        """Search multiple query variants as one model-visible tool call."""

        await runtime.checkpoint()
        summary = self.cached_web_search(queries, max_results)
        if summary is None:
            agent_api = get_agent_api()
            if (
                agent_api._search_web_reference_summary
                is not _search_web_reference_summary
            ):
                summary = await runtime.run_sync(
                    agent_api._search_web_reference_summary,
                    queries,
                    max_results,
                )
            else:
                summary = await runtime.run_async(
                    agent_api._async_search_web_reference_summary,
                    queries,
                    max_results,
                )
            self.cache_web_search(queries, max_results, summary)

        for result in summary.results:
            self.remember_web_search_result(result)

        if purpose != "jd":
            if summary.primary and not summary.error:
                if purpose == "target_context":
                    self.target_reference = (
                        self.executor.build_search_target_reference_from_result(
                            target,
                            summary.query,
                            self.web_search_summary_primary_result(summary),
                            summary.result_count,
                            summary.error,
                            kind=kind,
                            exact_job_description=False,
                            search_results=summary.results,
                        )
                    )
            return self.web_search_summary_tool(
                tool_call,
                purpose,
                queries,
                max_results,
                summary,
            )

        search_result = self.web_search_summary_primary_result(summary)
        self.target_reference = self.executor.build_search_target_reference_from_result(
            target,
            summary.query,
            search_result,
            summary.result_count,
            summary.error,
            kind=kind,
            exact_job_description=exact_job_description,
            search_results=summary.results,
        )
        tool = self.executor.build_target_reference_tool(
            self.target_reference,
            tool_call.id,
            tool_name=tool_call.name,
        )
        tool.input = {
            "query": summary.query,
            "queries": queries,
            "maxResults": max_results,
            "purpose": purpose,
            "language": self.executor.request.locale,
        }
        if isinstance(tool.output, dict):
            tool.output["queryCount"] = summary.query_count
            tool.output["maxResults"] = max_results
            tool.output["timedOut"] = summary.timed_out
            tool.output["partial"] = summary.partial
            excerpt_boundary = self.web_excerpt_boundary(search_result)
            if excerpt_boundary:
                tool.output["excerptBoundary"] = excerpt_boundary
        return tool

    def web_search_summary_tool(
        self,
        tool_call: LlmToolCall,
        purpose: str,
        queries: list[str],
        max_results: int,
        summary: WebSearchReference,
    ) -> AgentToolInvocation:
        """Return a model-visible tool result for non-JD multi-search context."""

        input_payload = {
            "query": summary.query,
            "queries": queries,
            "maxResults": max_results,
            "purpose": purpose,
            "language": self.executor.request.locale,
        }
        if summary.error or not summary.primary:
            return AgentToolInvocation(
                id=tool_call.id,
                type=f"tool-{tool_call.name}",
                title=tool_call.name,
                state="output-error",
                input=input_payload,
                output={
                    "queryCount": summary.query_count,
                    "resultCount": summary.result_count,
                    "timedOut": summary.timed_out,
                    "partial": summary.partial,
                },
                errorText=summary.error
                or agent_text(
                    self.executor.request.locale,
                    "error.web_search_failed",
                ),
            )

        results = []
        for result in summary.results:
            item: dict[str, Any] = {
                "url": result.url,
                "title": result.title,
                "excerpt": result.excerpt,
                "sourceKind": result.source_kind,
            }
            excerpt_boundary = self.web_excerpt_boundary(result)
            if excerpt_boundary:
                item["excerptBoundary"] = excerpt_boundary
            results.append(item)
        primary = summary.primary
        primary_boundary = self.web_excerpt_boundary(primary)
        return AgentToolInvocation(
            id=tool_call.id,
            type=f"tool-{tool_call.name}",
            title=tool_call.name,
            state="output-available",
            input=input_payload,
            output=sanitize_agent_value(
                {
                    "purpose": purpose,
                    "query": summary.query,
                    "queries": queries,
                    "queryCount": summary.query_count,
                    "maxResults": max_results,
                    "resultCount": summary.result_count,
                    "timedOut": summary.timed_out,
                    "partial": summary.partial,
                    "results": results,
                    "url": primary.url,
                    "title": primary.title,
                    # Keep the legacy top-level source fields internally
                    # consistent; the full evidence set lives in `results`.
                    "excerpt": primary.excerpt,
                    "excerptBoundary": primary_boundary,
                    "personalExperienceEvidence": False,
                },
                hidden_terms=self.executor.hidden_terms,
            ),
        )

    def web_search_summary_primary_result(
        self,
        summary: WebSearchReference,
    ) -> WebSearchResult | None:
        """Return the primary result without borrowing other sources' text."""

        return summary.primary

    def web_tool_error(
        self,
        tool_call: LlmToolCall,
        message_key: str,
        *,
        reason: str | None = None,
    ) -> AgentToolInvocation:
        """Return a consistent web tool validation error."""

        output: dict[str, Any] = {"blocked": True}
        if reason:
            output["reason"] = reason
        return AgentToolInvocation(
            id=tool_call.id,
            type=f"tool-{tool_call.name}",
            title=tool_call.name,
            state="output-error",
            input=tool_call.arguments,
            output=output,
            errorText=agent_text(self.executor.request.locale, message_key),
        )

    def run_resume_analysis(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Analyze the current resume only when the model asks for it."""

        self.analysis = self.executor.analyze_resume(self.draft_resume)
        return self.executor.build_resume_analysis_tool(self.analysis, tool_call.id)

    def run_update_target_context(
        self,
        tool_call: LlmToolCall,
    ) -> AgentToolInvocation:
        """Apply one prompt-derived target update to conversation-owned state."""

        mode = str(tool_call.arguments.get("mode") or "").strip()
        patch = tool_call.arguments.get("context")
        if mode not in {"merge", "replace", "clear"} or not isinstance(patch, dict):
            return AgentToolInvocation(
                id=tool_call.id,
                type="tool-update_target_context",
                title="update_target_context",
                state="output-error",
                input=tool_call.arguments,
                output={"blocked": True},
                errorText="Invalid target context update.",
            )

        try:
            assert self.executor.request.message.id is not None
            extracted_description = exact_job_description_from_prompt(
                self.executor.prompt,
            )
            if (
                mode != "clear"
                and extracted_description
                and not prompt_declares_partial_job_description(
                    self.executor.prompt,
                )
            ):
                patch = {
                    **patch,
                    "responsibilities": [],
                    "mustHaveSkills": [],
                    "niceToHaveSkills": [],
                    "requirements": [],
                    "description": extracted_description,
                    "exactJobDescription": True,
                }
            if mode == "clear":
                if not clears_target_context(self.executor.prompt):
                    raise ValueError(
                        "Target context clear is not authorized by this prompt.",
                    )
            elif rejects_target_context_update(
                self.executor.prompt,
            ) or not target_context_update_is_grounded(
                self.session_target_context,
                patch,
                mode=cast(Any, mode),
                prompt=self.executor.prompt,
            ):
                raise ValueError(
                    "Target context update is not grounded in this prompt.",
                )
            self.session_target_context = update_target_context(
                self.session_target_context,
                patch,
                mode=cast(Any, mode),
                source_message_id=self.executor.request.message.id,
            )
        except ValueError as exc:
            return AgentToolInvocation(
                id=tool_call.id,
                type="tool-update_target_context",
                title="update_target_context",
                state="output-error",
                input=tool_call.arguments,
                output={"blocked": True},
                errorText=str(exc),
            )

        self.target_reference = None
        self.analysis = None
        return AgentToolInvocation(
            id=tool_call.id,
            type="tool-update_target_context",
            title="update_target_context",
            state="output-available",
            input=tool_call.arguments,
            output={
                "mode": mode,
                "targetContext": self.session_target_context.model_dump(
                    mode="json",
                    by_alias=True,
                ),
            },
        )

    def run_material_extract(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Extract candidate resume facts from user-provided materials."""

        max_items = tool_call.arguments.get("maxItems")
        if not isinstance(max_items, int) or isinstance(max_items, bool):
            max_items = DEFAULT_MATERIAL_CANDIDATES

        try:
            output = extract_resume_materials(
                session_id=(self.executor.request.resume_id or "").strip(),
                prompt=self.executor.prompt,
                target_context=self.executor.target_brief,
                files=current_request_attachments(self.executor.request),
                target_reference=self.current_target_reference(),
                focus=str(tool_call.arguments.get("focus") or "all").strip(),
                max_items=max_items,
                hidden_terms=self.executor.hidden_terms,
            )
        except AgentAttachmentError as exc:
            raise LlmRequestError(str(exc)) from exc
        return AgentToolInvocation(
            id=tool_call.id,
            type="tool-material_extract",
            title="material_extract",
            state="output-available",
            input=tool_call.arguments,
            output=sanitize_agent_value(
                output,
                hidden_terms=self.executor.hidden_terms,
            ),
        )

    def run_resume_lookup(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Locate targeted resume sections/items for smaller edits."""

        return AgentToolInvocation(
            id=tool_call.id,
            type="tool-resume_lookup",
            title="resume_lookup",
            state="output-available",
            input=tool_call.arguments,
            output=lookup_resume(
                sanitize_agent_resume(
                    self.draft_resume,
                    hidden_terms=self.executor.hidden_terms,
                ),
                tool_call.arguments,
            ),
        )

    def run_draft_diff_summary(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Expose current draft edits/diffs for follow-up requests."""

        return AgentToolInvocation(
            id=tool_call.id,
            type="tool-draft_diff_summary",
            title="draft_diff_summary",
            state="output-available",
            input=tool_call.arguments,
            output=sanitize_agent_value(
                draft_diff_summary(self.executor.request.draft_state, self.edits),
                hidden_terms=self.executor.hidden_terms,
            ),
        )

    def run_edit_plan(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Validate and cache one explicit, prompt-scoped edit plan."""

        steps_value = tool_call.arguments.get("steps")
        if not isinstance(steps_value, list) or not steps_value:
            return self.semantic_edit_error(
                tool_call,
                entries=steps_value if isinstance(steps_value, list) else [],
                rejected_edits=[
                    {
                        "index": 1,
                        "reason": agent_text(
                            self.executor.request.locale,
                            "error.edit_plan_missing_inputs",
                        ),
                    },
                ],
                message_key="error.edit_plan_missing_inputs",
            )

        action_mismatches = [
            {
                "index": index,
                "reason": agent_text(
                    self.executor.request.locale,
                    "error.edit_plan_action_mismatch",
                ),
            }
            for index, step in enumerate(steps_value, start=1)
            if isinstance(step, dict)
            and isinstance(step.get("operation"), dict)
            and str(step.get("action") or "").strip()
            != str(step["operation"].get("type") or "").strip()
        ]
        if action_mismatches:
            return self.semantic_edit_error(
                tool_call,
                entries=steps_value,
                rejected_edits=action_mismatches,
                message_key="error.edit_execute_rejected_detailed",
            )

        model_steps = _model_plan_steps(steps_value)
        model_edits, rejected_edits = _model_edit_suggestions_with_diagnostics(
            self.draft_resume,
            steps_value,
            locale=self.executor.request.locale,
            allow_missing_operations=True,
        )
        if isinstance(steps_value, list) and rejected_edits:
            # Plans and direct execution share one atomic contract: never cache
            # a valid subset when any explicitly supplied operation is invalid.
            return self.semantic_edit_error(
                tool_call,
                entries=steps_value,
                rejected_edits=rejected_edits,
                message_key="error.edit_execute_rejected_detailed",
            )

        scope_issues = [
            *unauthorized_edit_issues(
                self.edit_authorization,
                self.draft_resume,
                model_edits,
            ),
            *unauthorized_plan_issues(
                self.edit_authorization,
                self.draft_resume,
                steps_value,
            ),
        ]
        if scope_issues:
            return self.semantic_edit_error(
                tool_call,
                entries=steps_value,
                rejected_edits=scope_issues,
                message_key="error.edit_execute_rejected_detailed",
            )

        if not model_steps:
            return self.semantic_edit_error(
                tool_call,
                entries=steps_value,
                rejected_edits=[
                    {
                        "index": 1,
                        "reason": agent_text(
                            self.executor.request.locale,
                            "error.edit_plan_missing_inputs",
                        ),
                    },
                ],
                message_key="error.edit_plan_missing_inputs",
            )

        plan_changed = model_steps != self.plan
        self.plan = model_steps
        if plan_changed:
            self.mark_semantic_progress()
        return self.executor.build_plan_tool(self.plan, tool_call.id)

    def run_edit_execute(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Execute one explicit batch of prompt-scoped draft edits."""

        explicit_edits_value = tool_call.arguments.get("edits")
        if not isinstance(explicit_edits_value, list) or not explicit_edits_value:
            return self.semantic_edit_error(
                tool_call,
                entries=(
                    explicit_edits_value
                    if isinstance(explicit_edits_value, list)
                    else []
                ),
                rejected_edits=[
                    {
                        "index": 1,
                        "reason": agent_text(
                            self.executor.request.locale,
                            "error.edit_execute_missing_inputs",
                        ),
                    },
                ],
                message_key="error.edit_execute_missing_inputs",
            )

        guard_error = self.edit_entries_policy_error(
            explicit_edits_value,
            tool_call.name,
        )
        if guard_error:
            return self.guarded_edit_tool_error(tool_call, guard_error)

        model_edits, rejected_edits = _model_edit_suggestions_with_diagnostics(
            self.draft_resume,
            explicit_edits_value,
            locale=self.executor.request.locale,
        )
        if isinstance(explicit_edits_value, list) and rejected_edits:
            return self.semantic_edit_error(
                tool_call,
                entries=explicit_edits_value,
                rejected_edits=rejected_edits,
                message_key="error.edit_execute_rejected_detailed",
            )

        if model_edits:
            error_tool, observations, quality_issues = self.stage_edit_batch(
                tool_call,
                model_edits,
                entries=explicit_edits_value,
            )
            if error_tool is not None:
                return error_tool
            return self.executor.build_execute_tool(
                self.plan,
                self.edits,
                tool_call.id,
                observations=observations,
                quality_issues=quality_issues,
            )

        if isinstance(explicit_edits_value, list):
            return self.semantic_edit_error(
                tool_call,
                entries=explicit_edits_value,
                rejected_edits=[
                    {
                        "index": 1,
                        "reason": agent_text(
                            self.executor.request.locale,
                            "error.edit_execute_rejected",
                        ),
                    },
                ],
                message_key="error.edit_execute_rejected",
            )

    def run_edit_move_item(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Move one existing item using validated draft operations."""

        entries, error = move_item_entries(
            self.draft_resume,
            tool_call.arguments,
            locale=self.executor.request.locale,
        )
        return self.run_structured_edit_tool(tool_call, entries, error)

    def run_edit_split_item(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Split one item into two draft records."""

        entries, error = split_item_entries(
            self.draft_resume,
            tool_call.arguments,
            locale=self.executor.request.locale,
        )
        return self.run_structured_edit_tool(tool_call, entries, error)

    def run_edit_merge_items(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Merge related items into a single draft record."""

        entries, error = merge_item_entries(
            self.draft_resume,
            tool_call.arguments,
            locale=self.executor.request.locale,
        )
        return self.run_structured_edit_tool(tool_call, entries, error)

    def run_skills_classify(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Create or replace grouped skill items."""

        entries, error = classify_skills_entries(
            self.draft_resume,
            tool_call.arguments,
            locale=self.executor.request.locale,
        )
        return self.run_structured_edit_tool(tool_call, entries, error)

    def run_draft_rewrite(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Apply follow-up edits against the current draft resume."""

        edits = tool_call.arguments.get("edits")
        entries = edits if isinstance(edits, list) else []
        error = (
            None
            if entries
            else agent_text(
                self.executor.request.locale,
                "error.draft_rewrite_missing_edits",
            )
        )
        return self.run_structured_edit_tool(tool_call, entries, error)

    def run_structured_edit_tool(
        self,
        tool_call: LlmToolCall,
        entries: list[dict[str, Any]],
        error: str | None,
    ) -> AgentToolInvocation:
        """Apply tool-specific edit entries through the shared validator."""

        if error:
            return self.semantic_edit_error(
                tool_call,
                entries=entries or tool_call.arguments,
                rejected_edits=[{"index": 1, "reason": error}],
                error_text=error,
            )

        guard_error = self.edit_entries_policy_error(entries, tool_call.name)
        if guard_error:
            return self.guarded_edit_tool_error(tool_call, guard_error)

        model_edits, rejected_edits = _model_edit_suggestions_with_diagnostics(
            self.draft_resume,
            entries,
            locale=self.executor.request.locale,
        )
        if rejected_edits or not model_edits:
            return self.semantic_edit_error(
                tool_call,
                entries=entries,
                rejected_edits=rejected_edits,
                message_key="error.edit_execute_rejected",
            )

        error_tool, observations, quality_issues = self.stage_edit_batch(
            tool_call,
            model_edits,
            entries=entries,
        )
        if error_tool is not None:
            return error_tool
        output: dict[str, Any] = {
            "editCount": len(model_edits),
            "operationTypes": [
                edit.operation.get("type") for edit in model_edits if edit.operation
            ],
            "observations": observations,
            "qualityIssueCount": len(quality_issues),
            "qualityIssues": quality_issues,
        }
        return AgentToolInvocation(
            id=tool_call.id,
            type=f"tool-{tool_call.name}",
            title=tool_call.name,
            state="output-available",
            input=tool_call.arguments,
            output=output,
        )

    def stage_edit_batch(
        self,
        tool_call: LlmToolCall,
        model_edits: list[AgentResumeEditSuggestion],
        *,
        entries: object,
    ) -> tuple[
        AgentToolInvocation | None,
        list[dict[str, Any]],
        list[dict[str, Any]],
    ]:
        """Validate a candidate resume before publishing any provisional edits.

        Subjective style findings remain advisory. Deterministic structural
        failures reject the complete batch and enter the existing one-retry
        transaction path.
        """

        before_resume = deepcopy(self.draft_resume)
        scope_issues = unauthorized_edit_issues(
            self.edit_authorization,
            before_resume,
            model_edits,
        )
        if scope_issues:
            return (
                self.semantic_edit_error(
                    tool_call,
                    entries=entries,
                    rejected_edits=scope_issues,
                    message_key="error.edit_execute_rejected_detailed",
                ),
                [],
                [],
            )

        model_edits, evidence_issues = ground_edit_evidence(
            before_resume,
            self.executor.request,
            model_edits,
        )
        candidate_resume = deepcopy(self.draft_resume)
        _apply_edit_operations(candidate_resume, model_edits)
        try:
            validate_resume_document(candidate_resume)
        except ResumeDocumentContractError as exc:
            return (
                self.semantic_edit_error(
                    tool_call,
                    entries=entries,
                    rejected_edits=[
                        {
                            "index": 1,
                            "reason": f"{exc.code} at {exc.path}.",
                        },
                    ],
                    message_key="error.edit_execute_rejected_detailed",
                ),
                [],
                [],
            )
        quality_issues = [
            *evidence_issues,
            *normalization_loss_issues(before_resume, entries, model_edits),
            *draft_quality_issues(
                candidate_resume,
                model_edits,
                target_context=self.quality_target_context(),
            ),
        ]
        blocking_issues = blocking_quality_issues(quality_issues)
        if blocking_issues:
            rejected_edits = [
                {
                    "index": int(issue.get("operationIndex") or 1),
                    "reason": (
                        "Draft quality check failed: "
                        f"{issue.get('code', 'unknown_quality_issue')}."
                    ),
                    "qualityIssue": issue,
                }
                for issue in blocking_issues
            ]
            return (
                self.semantic_edit_error(
                    tool_call,
                    entries=entries,
                    rejected_edits=rejected_edits,
                    message_key="error.edit_execute_rejected_detailed",
                ),
                [],
                quality_issues,
            )

        observations, diffs_by_edit = _edit_observations(
            before_resume,
            model_edits,
            locale=self.executor.request.locale,
        )
        edits_with_diffs: list[AgentResumeEditSuggestion] = []
        for edit, edit_diffs in zip(model_edits, diffs_by_edit, strict=True):
            edits_with_diffs.append(
                edit.model_copy(
                    update={"diffs": edit_diffs},
                ),
            )
        self.draft_resume = candidate_resume
        self.edits = _merge_edits(self.edits, edits_with_diffs)
        self.mark_edit_batch_succeeded()
        return None, observations, quality_issues

    def semantic_edit_error(
        self,
        tool_call: LlmToolCall,
        *,
        entries: object,
        rejected_edits: list[dict[str, Any]],
        message_key: str | None = None,
        error_text: str | None = None,
    ) -> AgentToolInvocation:
        """Reject one batch and track its failure within the current progress state."""

        fingerprint = json.dumps(
            {"tool": tool_call.name, "entries": entries},
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        semantic_fingerprint = self.semantic_error_fingerprint(
            tool_call.name,
            rejected_edits,
            message_key=message_key,
            error_text=error_text,
        )
        retry_exhausted = semantic_fingerprint in self._semantic_error_fingerprints
        same_batch = (
            self.semantic_retry_pending and fingerprint == self.failed_batch_fingerprint
        )
        if retry_exhausted:
            self.fail_transaction()
        else:
            self.semantic_retry_pending = True
            self.failed_batch_fingerprint = fingerprint
            self._semantic_error_fingerprints.add(semantic_fingerprint)

        return AgentToolInvocation(
            id=tool_call.id,
            type=f"tool-{tool_call.name}",
            title=tool_call.name,
            state="output-error",
            input=tool_call.arguments,
            output={
                "editCount": 0,
                "rejectedEditCount": len(rejected_edits),
                "rejectedEdits": rejected_edits,
                "retryable": not retry_exhausted,
                "retryExhausted": retry_exhausted,
                "sameBatch": same_batch,
                "fullBatchRequired": True,
            },
            errorText=error_text
            or agent_text(
                self.executor.request.locale,
                message_key or "error.edit_execute_rejected",
            ),
        )

    @staticmethod
    def semantic_error_fingerprint(
        tool_name: str,
        rejected_edits: list[dict[str, Any]],
        *,
        message_key: str | None,
        error_text: str | None,
    ) -> str:
        """Identify one semantic failure without volatile attempted values."""

        issues: list[dict[str, str]] = []
        for rejected_edit in rejected_edits:
            quality_issue = rejected_edit.get("qualityIssue")
            if isinstance(quality_issue, dict):
                issue = {
                    key: str(quality_issue.get(key) or "").strip()
                    for key in ("code", "scope", "target")
                    if str(quality_issue.get(key) or "").strip()
                }
            else:
                reason = str(rejected_edit.get("reason") or "").strip()
                issue = {"reason": reason} if reason else {}
            issues.append(issue)

        return json.dumps(
            {
                "tool": tool_name,
                "error": error_text or message_key or "error.edit_execute_rejected",
                "issues": sorted(
                    issues,
                    key=lambda issue: json.dumps(
                        issue,
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def mark_edit_batch_succeeded(self) -> None:
        """Publish a new provisional revision after an atomic batch succeeds."""

        self.mark_semantic_progress()
        self.edit_revision += 1

    def mark_semantic_progress(self) -> None:
        """Start a new repair state after a changed plan or atomic draft update."""

        self.semantic_retry_pending = False
        self.failed_batch_fingerprint = ""
        self._semantic_error_fingerprints.clear()

    def fail_transaction(self) -> None:
        """Roll back every edit staged during the current Agent turn."""

        had_edits = bool(self.edits)
        self.draft_resume = deepcopy(self.base_resume)
        self.edits = []
        self.semantic_retry_pending = False
        self.failed_batch_fingerprint = ""
        self._semantic_error_fingerprints.clear()
        self.transaction_failed = True
        self.transaction_committed = False
        self.finished = True
        if had_edits:
            self.edit_revision += 1

    def finalize_turn(self) -> None:
        """Commit staged edits only after the complete tool loop succeeds."""

        if self.transaction_failed:
            return
        if self.semantic_retry_pending:
            self.fail_transaction()
            return
        self.transaction_committed = bool(self.edits)

    @property
    def transaction_state(self) -> AgentTransactionState:
        if self.transaction_failed:
            return "rolled_back"
        if self.transaction_committed:
            return "committed"
        if self.edits:
            return "provisional"
        return "none"

    def edit_entries_policy_error(
        self,
        entries: object,
        tool_name: str,
    ) -> str | None:
        """Return a guard error key for implicit destructive/reorder edits."""

        if not isinstance(entries, list):
            return None

        prompt = self.executor.prompt
        delete_allowed = has_explicit_delete_intent(prompt)
        reorder_allowed = has_explicit_reorder_intent(prompt)
        merge_allowed = has_explicit_merge_intent(prompt)
        if tool_name == "edit_move_item" and not reorder_allowed:
            return "error.tool_requires_reorder_intent"

        for entry in entries:
            operation = entry.get("operation") if isinstance(entry, dict) else None
            if not isinstance(operation, dict):
                continue

            operation_type = str(operation.get("type") or "")
            if operation_type in {"reorder_sections", "reorder_items"}:
                if not reorder_allowed:
                    return "error.tool_requires_reorder_intent"
            if operation_type in {"delete_section", "delete_item"}:
                if tool_name == "edit_move_item" and reorder_allowed:
                    continue
                if tool_name == "edit_merge_items" and merge_allowed:
                    continue
                if tool_name == "skills_classify":
                    continue
                if not delete_allowed:
                    return "error.tool_requires_delete_intent"

        return None

    def guarded_edit_tool_error(
        self,
        tool_call: LlmToolCall,
        message_key: str,
    ) -> AgentToolInvocation:
        # A policy failure cannot be repaired by changing edit JSON. If it occurs
        # during the one allowed repair attempt, the turn must roll back.
        if self.semantic_retry_pending:
            self.fail_transaction()
        return AgentToolInvocation(
            id=tool_call.id,
            type=f"tool-{tool_call.name}",
            title=tool_call.name,
            state="output-error",
            input=tool_call.arguments,
            output={"blocked": True},
            errorText=agent_text(self.executor.request.locale, message_key),
        )

    def run_finish(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Record the model's explicit ReAct finish action without showing it."""

        if self.semantic_retry_pending:
            self.fail_transaction()
            return AgentToolInvocation(
                id=tool_call.id,
                type="tool-finish",
                title="finish",
                state="output-error",
                input=tool_call.arguments,
                output={"status": "rolled_back"},
                errorText=agent_text(
                    self.executor.request.locale,
                    "error.edit_repair_required",
                ),
            )

        status = str(tool_call.arguments.get("status") or "").strip()
        if status not in {"ready", "blocked"}:
            # Tool schemas normally reject this earlier. Keep the runtime
            # boundary fail-closed so malformed provider output can never
            # commit edits as a successful transaction.
            self.fail_transaction()
            return AgentToolInvocation(
                id=tool_call.id,
                type="tool-finish",
                title="finish",
                state="output-error",
                input=tool_call.arguments,
                output={"status": "rolled_back"},
                errorText=agent_text(
                    self.executor.request.locale,
                    "error.finish_invalid_status",
                ),
            )
        reason = str(tool_call.arguments.get("reason") or "").strip()
        missing = self.finish_missing_values(tool_call.arguments.get("missing"))
        if status != "blocked":
            missing = []
        self.finished = True
        self.finish_status = status
        self.finish_reason = reason
        self.finish_missing = missing
        if status == "blocked":
            # A blocked turn may explain what is missing, but it must never
            # publish edits produced before the model discovered that blocker.
            if self.edits:
                self.fail_transaction()

        return AgentToolInvocation(
            id=tool_call.id,
            type="tool-finish",
            title="finish",
            state="output-available",
            input=tool_call.arguments,
            output={
                "status": status,
                "reason": reason,
                "missing": missing,
                "transactionState": self.transaction_state,
                "observation": agent_text(
                    self.executor.request.locale,
                    "tool.finish.observation",
                ),
            },
        )

    def current_target_reference(self) -> TargetReference:
        """Return resolved target context, or the request-derived placeholder."""

        return self.target_reference or self.executor.target_reference_from_request()

    def quality_target_context(self) -> str | None:
        """Return explicit target requirements, never inferred public evidence."""

        reference = self.current_target_reference()
        if reference.mode == "none":
            return None
        return reference.excerpt or reference.source_excerpt or None

    def tool_result(self, tool: AgentToolInvocation) -> dict[str, Any]:
        """Return compact JSON sent back to the model after tool execution."""

        return {
            "title": tool.title,
            "state": tool.state,
            "input": sanitize_agent_value(
                tool.input,
                hidden_terms=self.executor.hidden_terms,
            ),
            "output": sanitize_agent_value(
                tool.output,
                hidden_terms=self.executor.hidden_terms,
            ),
            "errorText": sanitize_agent_value(
                tool.error_text,
                hidden_terms=self.executor.hidden_terms,
            ),
        }

    def non_edit_tool_failure_text(self, tool: AgentToolInvocation) -> str:
        """Return a truthful terminal message for a failed non-edit action."""

        spec = agent_tool_spec(tool.title)
        if spec is None or tool.state != "output-error":
            return ""

        if spec.mode == "read":
            if tool.title == "web_search":
                output = tool.output if isinstance(tool.output, dict) else {}
                message_key = (
                    "response.research_timeout"
                    if output.get("timedOut") is True
                    else "response.research_failed"
                )
                return agent_text(self.executor.request.locale, message_key)

            return agent_text(
                self.executor.request.locale,
                "response.read_tool_failed",
            )

        if tool.title == "update_target_context":
            return agent_text(
                self.executor.request.locale,
                "response.target_context_update_failed",
            )

        return ""

    def build_message(self, message_id: str | None = None) -> AgentChatMessage:
        """Assemble an assistant payload from the tools the model used."""

        target_reference = self.current_target_reference()
        self.analysis = self.executor.analyze_resume(self.draft_resume)
        analysis = self.analysis
        message = self.executor.build_message_from_parts(
            target_reference=target_reference,
            analysis=analysis,
            plan=self.plan,
            edits=self.edits,
            tools=self.tools,
            message_id=message_id,
            finish_status=self.finish_status,
            finish_reason=self.finish_reason,
            finish_missing=self.finish_missing,
        )
        message = message.model_copy(
            update={"target_context": self.session_target_context},
        )
        if self.transaction_failed:
            if self.finish_status == "blocked":
                # Preserve the model's structured blocked response while
                # exposing that its provisional edits were discarded.
                return message.model_copy(
                    update={
                        "edits": [],
                        "transaction_state": "rolled_back",
                    },
                )
            # A model may explain why its repair attempt cannot continue. Keep
            # that actionable reason while still returning a rolled-back turn.
            rollback_text = self.terminal_text.strip() or agent_text(
                self.executor.request.locale,
                "response.edit_transaction_failed",
            )
            return message.model_copy(
                update={
                    "tone": "default",
                    "text": sanitize_agent_text(
                        rollback_text,
                        hidden_terms=self.executor.hidden_terms,
                    ),
                    "edits": [],
                    "quick_replies": [],
                    "actions": [],
                    "transaction_state": "rolled_back",
                },
            )
        read_failure_text = next(
            (
                text
                for tool in reversed(self.tools)
                if (text := self.non_edit_tool_failure_text(tool))
            ),
            "",
        )
        if read_failure_text and not self.edits:
            return message.model_copy(
                update={
                    "tone": "default",
                    "text": read_failure_text,
                    "quick_replies": [],
                    "actions": [],
                    "transaction_state": "none",
                },
            )
        return message.model_copy(
            update={"transaction_state": self.transaction_state},
        )

    def finish_missing_values(self, value: object) -> list[AgentFinishMissing]:
        """Return valid structured blocked-reason hints from finish arguments."""

        raw_values = value if isinstance(value, list) else []
        missing: list[AgentFinishMissing] = []
        for item in raw_values:
            if not isinstance(item, str):
                continue
            normalized = item.strip()
            if normalized in FINISH_MISSING_SET and normalized not in missing:
                missing.append(cast(AgentFinishMissing, normalized))

        return missing


def running_model_tool(tool_call: LlmToolCall) -> AgentToolInvocation:
    """Build the running UI payload for a model-selected tool call."""

    return AgentToolInvocation(
        id=tool_call.id,
        type=f"tool-{tool_call.name}",
        title=tool_call.name,
        state="input-available",
        input=tool_call.arguments,
    )
