from copy import deepcopy
from typing import Any

from app.schemas.agent import (
    AgentChatMessage,
    AgentResumeEditSuggestion,
    AgentToolInvocation,
)
from app.services.llm_client import LlmToolCall

from ..editing import (
    _apply_edit_operations,
    _edit_observations,
    _merge_edits,
    _model_edit_suggestions,
    _model_plan_steps,
)
from ..executor import AgentPlanExecutor
from ..integrations import JD_URL_PATTERN
from ..models import EditPlanStep, JobReference, ResumeAnalysis


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

    def run(self, tool_call: LlmToolCall) -> tuple[AgentToolInvocation, dict[str, Any]]:
        """Execute a model-selected tool and return its tool-message payload."""

        handlers = {
            "jd_url_fetch": self.run_jd_url_fetch,
            "jd_reference_search": self.run_jd_reference_search,
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

        model_edits = _model_edit_suggestions(
            self.draft_resume,
            tool_call.arguments.get("edits"),
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
