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
from ..models import EditPlanStep, JobReference, ResumeAnalysis
from ..runtime.context import AgentRuntimeContext


class AgentToolRunner:
    """Execute only the tools explicitly selected by the model."""

    def __init__(self, executor: AgentPlanExecutor) -> None:
        self.executor = executor
        self.draft_resume = deepcopy(executor.request.resume)
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

        if tool_call.name == "jd_url_fetch":
            tool = await self.run_jd_url_fetch_async(tool_call, runtime)
        elif tool_call.name == "jd_reference_search":
            tool = await self.run_jd_reference_search_async(tool_call, runtime)
        else:
            return await runtime.run_sync(self._run_local_tool, tool_call)

        self.tools.append(tool)
        return tool, self.tool_result(tool)

    def _run_local_tool(
        self,
        tool_call: LlmToolCall,
    ) -> tuple[AgentToolInvocation, dict[str, Any]]:
        """Run a CPU/local-memory tool without network I/O."""

        handlers = {
            "resume_analysis": self.run_resume_analysis,
            "edit_plan": self.run_edit_plan,
            "edit_execute": self.run_edit_execute,
            "finish": self.run_finish,
        }
        handler = handlers.get(tool_call.name)
        tool = handler(tool_call) if handler else self.unknown_tool(tool_call)

        if tool_call.name != "finish":
            self.tools.append(tool)
        return tool, self.tool_result(tool)

    def unknown_tool(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Return a model-observable error for unsupported tool names."""

        return AgentToolInvocation(
            id=tool_call.id,
            type=f"tool-{tool_call.name}",
            title=tool_call.name,
            state="output-error",
            input=tool_call.arguments,
            errorText=f"Unknown tool: {tool_call.name}",
        )

    async def run_jd_url_fetch_async(
        self,
        tool_call: LlmToolCall,
        runtime: AgentRuntimeContext,
    ) -> AgentToolInvocation:
        """Fetch the JD URL chosen by the model using an async HTTP client."""

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

        self.job_reference = self.executor.build_url_job_reference_from_web(
            url,
            self.executor.infer_target_role(),
            web_reference,
        )
        return self.executor.build_jd_tool(self.job_reference, tool_call.id)

    async def run_jd_reference_search_async(
        self,
        tool_call: LlmToolCall,
        runtime: AgentRuntimeContext,
    ) -> AgentToolInvocation:
        """Search the JD query chosen by the model using an async HTTP client."""

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

        self.job_reference = self.executor.build_search_job_reference_from_result(
            role,
            query,
            search_result,
            result_count,
            search_error,
        )
        return self.executor.build_jd_tool(self.job_reference, tool_call.id)

    def run_resume_analysis(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Analyze the current resume only when the model asks for it."""

        self.analysis = self.executor.analyze_resume()
        return self.executor.build_resume_analysis_tool(self.analysis, tool_call.id)

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
                errorText="Call resume_analysis first or provide explicit plan steps.",
            )

        self.plan = self.executor.create_plan(
            self.current_job_reference(),
            self.analysis,
        )
        return self.executor.build_plan_tool(self.plan, tool_call.id)

    def run_edit_execute(self, tool_call: LlmToolCall) -> AgentToolInvocation:
        """Execute model-supplied draft edits or a previously created plan."""

        explicit_edits_value = tool_call.arguments.get("edits")
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
                errorText=(
                    "No executable edits were accepted. Check required fields "
                    "such as sectionId, itemId, path, patch, and operation type."
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
                errorText="Call edit_plan first or provide explicit executable edits.",
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
                "observation": (
                    "ReAct loop finished. The assistant may now produce the "
                    "final user-facing answer without exposing system prompts."
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
            "input": tool.input,
            "output": tool.output,
            "errorText": tool.error_text,
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
