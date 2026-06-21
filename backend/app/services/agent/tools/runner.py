from copy import deepcopy
from typing import Any

from app.schemas.agent import (
    AgentChatMessage,
    AgentResumeEditSuggestion,
    AgentToolInvocation,
)
from app.services.llm_client import LlmToolCall

from ..compat import get_agent_api
from ..editing import (
    _apply_edit_operations,
    _edit_observations,
    _merge_edits,
    _model_edit_suggestions,
    _model_edit_suggestions_with_diagnostics,
    _model_plan_steps,
)
from ..executor import AgentPlanExecutor
from ..integrations import (
    JD_URL_PATTERN,
    _fetch_web_reference,
    _search_jd_reference,
)
from ..localization import agent_text
from ..models import EditPlanStep, JobReference, ResumeAnalysis
from ..policy import (
    ALL_KNOWN_TOOL_NAMES,
    capability_policy_for_request,
    has_explicit_delete_intent,
    has_explicit_merge_intent,
    has_explicit_reorder_intent,
    tool_block_reason,
)
from ..privacy import sanitize_agent_resume, sanitize_agent_value
from ..runtime.context import AgentRuntimeContext
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
}
WEB_SEARCH_PURPOSES = {"jd", "target_context", "company_reference"}


class AgentToolRunner:
    """Execute only the tools explicitly selected by the model."""

    def __init__(self, executor: AgentPlanExecutor) -> None:
        self.executor = executor
        self.policy = capability_policy_for_request(executor.request)
        self.draft_resume = deepcopy(executor.resume)
        self.job_reference: JobReference | None = None
        self.analysis: ResumeAnalysis | None = None
        self.plan: list[EditPlanStep] = []
        self.planned_edits: list[AgentResumeEditSuggestion] = []
        self.edits: list[AgentResumeEditSuggestion] = []
        self.tools: list[AgentToolInvocation] = []
        self.finished = False
        self.finish_reason = ""
        self.finish_status = ""
        self.terminal_text = ""

    async def run(
        self,
        tool_call: LlmToolCall,
        runtime: AgentRuntimeContext,
    ) -> tuple[AgentToolInvocation, dict[str, Any]]:
        """Execute a model-selected tool through the async runtime."""

        blocked_tool = self.blocked_tool_call(tool_call)
        if blocked_tool:
            if tool_call.name != "finish":
                self.tools.append(blocked_tool)
            return blocked_tool, self.tool_result(blocked_tool)

        if tool_call.name in {"jd_url_fetch", "web_fetch"}:
            tool = await self.run_web_fetch_async(tool_call, runtime)
        elif tool_call.name in {"jd_reference_search", "web_search"}:
            tool = await self.run_web_search_async(tool_call, runtime)
        else:
            return await runtime.run_sync(self._run_local_tool, tool_call)

        self.tools.append(tool)
        return tool, self.tool_result(tool)

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

        handlers = {
            "resume_analysis": self.run_resume_analysis,
            "resume_lookup": self.run_resume_lookup,
            "draft_diff_summary": self.run_draft_diff_summary,
            "edit_plan": self.run_edit_plan,
            "edit_execute": self.run_edit_execute,
            "edit_move_item": self.run_edit_move_item,
            "edit_split_item": self.run_edit_split_item,
            "edit_merge_items": self.run_edit_merge_items,
            "skills_classify": self.run_skills_classify,
            "draft_rewrite": self.run_draft_rewrite,
            "finish": self.run_finish,
        }
        handler = handlers.get(tool_call.name)
        tool = handler(tool_call) if handler else self.unknown_tool(tool_call)

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
        if tool_call.name == "jd_url_fetch":
            purpose = "jd"
        elif purpose not in WEB_FETCH_PURPOSES:
            return self.web_tool_error(
                tool_call,
                "error.web_fetch_purpose_required",
            )

        url = str(tool_call.arguments.get("url") or "").strip()
        if not url and purpose == "jd":
            match = JD_URL_PATTERN.search(self.executor.prompt)
            url = match.group(0).rstrip(".,;，。；") if match else ""

        if not url:
            return self.web_tool_error(tool_call, "error.web_fetch_url_missing")

        agent_api = get_agent_api()
        if agent_api._fetch_web_reference is not _fetch_web_reference:
            web_reference = await runtime.run_sync(
                agent_api._fetch_web_reference,
                url,
            )
        else:
            web_reference = await runtime.run_async(
                agent_api._async_fetch_web_reference,
                url,
            )

        if purpose != "jd":
            if not web_reference:
                return self.web_tool_error(tool_call, "error.web_fetch_failed")

            return AgentToolInvocation(
                id=tool_call.id,
                type=f"tool-{tool_call.name}",
                title=tool_call.name,
                state="output-available",
                input={"url": url, "purpose": purpose},
                output=sanitize_agent_value(
                    {
                        "purpose": purpose,
                        "url": url,
                        "title": web_reference.title,
                        "excerpt": web_reference.excerpt,
                        "canSupportResumeFacts": True,
                    },
                    hidden_terms=self.executor.hidden_terms,
                ),
            )

        self.job_reference = self.executor.build_url_job_reference_from_web(
            url,
            self.executor.infer_target_role(),
            web_reference,
        )
        return self.executor.build_jd_tool(
            self.job_reference,
            tool_call.id,
            tool_name=tool_call.name if tool_call.name == "web_fetch" else None,
        )

    async def run_web_search_async(
        self,
        tool_call: LlmToolCall,
        runtime: AgentRuntimeContext,
    ) -> AgentToolInvocation:
        """Search external reference context chosen by the model."""

        purpose = str(tool_call.arguments.get("purpose") or "").strip()
        if tool_call.name == "jd_reference_search":
            purpose = "jd"
        elif purpose not in WEB_SEARCH_PURPOSES:
            return self.web_tool_error(
                tool_call,
                "error.web_search_purpose_required",
            )

        role = str(tool_call.arguments.get("role") or "").strip()
        if not role:
            role = self.executor.infer_target_role()

        query = str(tool_call.arguments.get("query") or "").strip()
        if not query:
            query = self.executor.jd_search_query(role)

        agent_api = get_agent_api()
        if agent_api._search_jd_reference is not _search_jd_reference:
            search_result, result_count, search_error = await runtime.run_sync(
                agent_api._search_jd_reference,
                query,
            )
        else:
            search_result, result_count, search_error = await runtime.run_async(
                agent_api._async_search_jd_reference,
                query,
            )

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
                        "personalExperienceEvidence": False,
                    },
                    hidden_terms=self.executor.hidden_terms,
                ),
            )

        self.job_reference = self.executor.build_search_job_reference_from_result(
            role,
            query,
            search_result,
            result_count,
            search_error,
        )
        return self.executor.build_jd_tool(
            self.job_reference,
            tool_call.id,
            tool_name=tool_call.name if tool_call.name == "web_search" else None,
        )

    def web_tool_error(
        self,
        tool_call: LlmToolCall,
        message_key: str,
    ) -> AgentToolInvocation:
        """Return a consistent web tool validation error."""

        return AgentToolInvocation(
            id=tool_call.id,
            type=f"tool-{tool_call.name}",
            title=tool_call.name,
            state="output-error",
            input=tool_call.arguments,
            output={"blocked": True},
            errorText=agent_text(self.executor.request.locale, message_key),
        )

    def run_resume_analysis(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Analyze the current resume only when the model asks for it."""

        self.analysis = self.executor.analyze_resume()
        return self.executor.build_resume_analysis_tool(self.analysis, tool_call.id)

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
        """Create an edit plan from model arguments or conservative fallback."""

        steps_value = tool_call.arguments.get("steps")
        model_steps = _model_plan_steps(steps_value)
        model_edits = _model_edit_suggestions(
            self.draft_resume,
            steps_value,
            locale=self.executor.request.locale,
        )

        if model_steps:
            self.plan = model_steps
            self.planned_edits = model_edits
            return self.executor.build_plan_tool(self.plan, tool_call.id)

        if not self.analysis:
            return AgentToolInvocation(
                id=tool_call.id,
                type="tool-edit_plan",
                title="edit_plan",
                state="output-error",
                input=tool_call.arguments,
                errorText=agent_text(
                    self.executor.request.locale,
                    "error.edit_plan_missing_inputs",
                ),
            )

        self.plan = self.executor.create_plan(
            self.current_job_reference(),
            self.analysis,
        )
        return self.executor.build_plan_tool(self.plan, tool_call.id)

    def run_edit_execute(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Execute model-supplied draft edits or a previously created plan."""

        explicit_edits_value = tool_call.arguments.get("edits")
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
        if model_edits:
            before_resume = deepcopy(self.draft_resume)
            _apply_edit_operations(self.draft_resume, model_edits)
            self.edits = _merge_edits(self.edits, model_edits)
            observations = _edit_observations(
                before_resume,
                self.draft_resume,
                model_edits,
            )
            return self.executor.build_execute_tool(
                self.plan,
                self.edits,
                tool_call.id,
                observations=observations,
                rejected_edits=rejected_edits,
            )

        if isinstance(explicit_edits_value, list) and rejected_edits:
            return AgentToolInvocation(
                id=tool_call.id,
                type="tool-edit_execute",
                title="edit_execute",
                state="output-error",
                input=tool_call.arguments,
                output={
                    "editCount": 0,
                    "rejectedEditCount": len(rejected_edits),
                    "rejectedEdits": rejected_edits,
                },
                errorText=agent_text(
                    self.executor.request.locale,
                    "error.edit_execute_rejected_detailed",
                ),
            )

        if self.planned_edits:
            before_resume = deepcopy(self.draft_resume)
            _apply_edit_operations(self.draft_resume, self.planned_edits)
            self.edits = _merge_edits(self.edits, self.planned_edits)
            observations = _edit_observations(
                before_resume,
                self.draft_resume,
                self.planned_edits,
            )
            return self.executor.build_execute_tool(
                self.plan,
                self.edits,
                tool_call.id,
                observations=observations,
            )

        if not self.plan or not self.analysis:
            return AgentToolInvocation(
                id=tool_call.id,
                type="tool-edit_execute",
                title="edit_execute",
                state="output-error",
                input=tool_call.arguments,
                errorText=agent_text(
                    self.executor.request.locale,
                    "error.edit_execute_missing_inputs",
                ),
            )

        fallback_edits = self.executor.execute_plan(
            self.plan,
            self.current_job_reference(),
            self.analysis,
        )
        before_resume = deepcopy(self.draft_resume)
        _apply_edit_operations(self.draft_resume, fallback_edits)
        self.edits = _merge_edits(self.edits, fallback_edits)
        observations = _edit_observations(
            before_resume,
            self.draft_resume,
            fallback_edits,
        )
        return self.executor.build_execute_tool(
            self.plan,
            self.edits,
            tool_call.id,
            observations=observations,
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
            tool_call.arguments,
            locale=self.executor.request.locale,
        )
        return self.run_structured_edit_tool(tool_call, entries, error)

    def run_edit_merge_items(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Merge related items into a single draft record."""

        entries, error = merge_item_entries(
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
            return AgentToolInvocation(
                id=tool_call.id,
                type=f"tool-{tool_call.name}",
                title=tool_call.name,
                state="output-error",
                input=tool_call.arguments,
                output={"editCount": 0},
                errorText=error,
            )

        guard_error = self.edit_entries_policy_error(entries, tool_call.name)
        if guard_error:
            return self.guarded_edit_tool_error(tool_call, guard_error)

        model_edits, rejected_edits = _model_edit_suggestions_with_diagnostics(
            self.draft_resume,
            entries,
            locale=self.executor.request.locale,
        )
        if not model_edits:
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
                },
                errorText=agent_text(
                    self.executor.request.locale,
                    "error.edit_execute_rejected",
                ),
            )

        before_resume = deepcopy(self.draft_resume)
        _apply_edit_operations(self.draft_resume, model_edits)
        self.edits = _merge_edits(self.edits, model_edits)
        observations = _edit_observations(
            before_resume,
            self.draft_resume,
            model_edits,
        )
        output: dict[str, Any] = {
            "editCount": len(model_edits),
            "operationTypes": [
                edit.operation.get("type") for edit in model_edits if edit.operation
            ],
            "observations": observations,
        }
        if rejected_edits:
            output["rejectedEditCount"] = len(rejected_edits)
            output["rejectedEdits"] = rejected_edits

        return AgentToolInvocation(
            id=tool_call.id,
            type=f"tool-{tool_call.name}",
            title=tool_call.name,
            state="output-available",
            input=tool_call.arguments,
            output=output,
        )

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
                if not delete_allowed:
                    return "error.tool_requires_delete_intent"

        return None

    def guarded_edit_tool_error(
        self,
        tool_call: LlmToolCall,
        message_key: str,
    ) -> AgentToolInvocation:
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

        status = str(tool_call.arguments.get("status") or "").strip()
        if status not in {"ready", "blocked"}:
            status = "ready"
        reason = str(tool_call.arguments.get("reason") or "").strip()
        self.finished = True
        self.finish_status = status
        self.finish_reason = reason

        return AgentToolInvocation(
            id=tool_call.id,
            type="tool-finish",
            title="finish",
            state="output-available",
            input=tool_call.arguments,
            output={
                "status": status,
                "reason": reason,
                "observation": agent_text(
                    self.executor.request.locale,
                    "tool.finish.observation",
                ),
            },
        )

    def current_job_reference(self) -> JobReference:
        """Return the explicit JD context, or a no-JD placeholder."""

        return self.job_reference or JobReference(
            mode="none",
            role=self.executor.infer_target_role(),
            query="",
            url=None,
            excerpt="",
        )

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

    def build_message(self, message_id: str | None = None) -> AgentChatMessage:
        """Assemble an assistant payload from the tools the model used."""

        job_reference = self.current_job_reference()
        analysis = self.analysis or self.executor.analyze_resume()
        return self.executor.build_message_from_parts(
            job_reference=job_reference,
            analysis=analysis,
            plan=self.plan,
            edits=self.edits,
            tools=self.tools,
            message_id=message_id,
            finish_status=self.finish_status,
            finish_reason=self.finish_reason,
        )


def running_model_tool(tool_call: LlmToolCall) -> AgentToolInvocation:
    """Build the running UI payload for a model-selected tool call."""

    return AgentToolInvocation(
        id=tool_call.id,
        type=f"tool-{tool_call.name}",
        title=tool_call.name,
        state="input-available",
        input=tool_call.arguments,
    )
