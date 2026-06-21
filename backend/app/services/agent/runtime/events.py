from dataclasses import dataclass
from typing import Any

from app.schemas.agent import AgentResumeEditSuggestion, AgentToolInvocation


@dataclass(frozen=True)
class AgentRunEvent:
    """Stable internal event summary for deterministic agent replay."""

    type: str
    tool_name: str = ""
    tool_call_id: str = ""
    state: str = ""
    outcome: str = ""
    status: str = ""
    missing: tuple[str, ...] = ()
    edit_count: int = 0
    rejected_edit_count: int = 0
    quality_issue_count: int = 0
    operation_types: tuple[str, ...] = ()


def agent_tool_outcome(tool: AgentToolInvocation) -> str:
    """Return the replay outcome for one executed tool invocation."""

    if tool.state == "output-available":
        return "success"

    if tool.state == "output-error":
        output = tool.output if isinstance(tool.output, dict) else {}
        return "blocked" if output.get("blocked") is True else "error"

    return "running"


def agent_rejected_edit_count(tool: AgentToolInvocation) -> int:
    """Return the number of rejected edits reported by a tool, if any."""

    output = tool.output if isinstance(tool.output, dict) else {}
    value = output.get("rejectedEditCount")
    return value if isinstance(value, int) and value > 0 else 0


def agent_quality_issue_count(tool: AgentToolInvocation) -> int:
    """Return the number of non-blocking quality issues reported by a tool."""

    output = tool.output if isinstance(tool.output, dict) else {}
    value = output.get("qualityIssueCount")
    return value if isinstance(value, int) and value > 0 else 0


def agent_operation_types(
    edits: list[AgentResumeEditSuggestion],
) -> tuple[str, ...]:
    """Return accepted operation types from actual draft edit suggestions."""

    operation_types: list[str] = []
    for edit in edits:
        operation = edit.operation if isinstance(edit.operation, dict) else {}
        operation_type = operation.get("type")
        if isinstance(operation_type, str) and operation_type:
            operation_types.append(operation_type)

    return tuple(operation_types)


def agent_run_outcome(
    events: list[AgentRunEvent],
    *,
    finish_status: str = "",
    edit_count: int = 0,
) -> str:
    """Return the final deterministic replay outcome."""

    if finish_status == "blocked":
        return "blocked"

    if edit_count > 0:
        return "success"

    if any(
        event.type == "tool_done" and event.outcome in {"blocked", "error"}
        for event in events
    ):
        return "error"

    return "success"


def compact_event_payload(event: AgentRunEvent) -> dict[str, Any]:
    """Return a JSON-friendly event summary for debugging or future fixtures."""

    payload = {
        "type": event.type,
        "toolName": event.tool_name,
        "toolCallId": event.tool_call_id,
        "state": event.state,
        "outcome": event.outcome,
        "status": event.status,
        "missing": list(event.missing),
        "editCount": event.edit_count,
        "rejectedEditCount": event.rejected_edit_count,
        "qualityIssueCount": event.quality_issue_count,
        "operationTypes": list(event.operation_types),
    }
    return {key: value for key, value in payload.items() if value}
