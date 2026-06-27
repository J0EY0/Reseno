import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.schemas.agent import AgentChatRequest, AgentToolInvocation
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.runtime.events import (
    AgentRunEvent,
    agent_operation_types,
    agent_quality_issue_count,
    agent_rejected_edit_count,
    agent_run_outcome,
    agent_tool_outcome,
)
from app.services.agent.tools.runner import AgentToolRunner
from app.services.llm import LlmToolCall


@dataclass(frozen=True)
class ReplayToolCall:
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""


@dataclass(frozen=True)
class AgentReplayScenario:
    name: str
    request: AgentChatRequest
    tool_calls: list[ReplayToolCall]


@dataclass
class AgentReplayResult:
    runner: AgentToolRunner
    tools: list[AgentToolInvocation]
    observations: list[dict[str, Any]]
    events: list[AgentRunEvent]


def run_agent_replay(scenario: AgentReplayScenario) -> AgentReplayResult:
    """Replay a deterministic tool-call sequence against the local runner."""

    runner = AgentToolRunner(AgentPlanExecutor(scenario.request))
    tools: list[AgentToolInvocation] = []
    observations: list[dict[str, Any]] = []
    events: list[AgentRunEvent] = [
        AgentRunEvent(type="run_start"),
        AgentRunEvent(type="turn_start"),
    ]
    for index, replay_call in enumerate(scenario.tool_calls, start=1):
        tool_call = _llm_tool_call(replay_call, index)
        before_edit_count = len(runner.edits)
        events.append(
            AgentRunEvent(
                type="tool_start",
                tool_name=tool_call.name,
                tool_call_id=tool_call.id,
            ),
        )
        if replay_call.name in {
            "web_fetch",
            "web_search",
        }:
            tool, observation = asyncio.run(
                runner.run(tool_call, AgentRuntimeContext()),
            )
        else:
            tool, observation = runner._run_local_tool(tool_call)
        tools.append(tool)
        observations.append(observation)
        new_edits = runner.edits[before_edit_count:]
        events.append(
            AgentRunEvent(
                type="tool_done",
                tool_name=tool_call.name,
                tool_call_id=tool_call.id,
                state=tool.state,
                outcome=agent_tool_outcome(tool),
                edit_count=len(new_edits),
                rejected_edit_count=agent_rejected_edit_count(tool),
                quality_issue_count=agent_quality_issue_count(tool),
                operation_types=agent_operation_types(new_edits),
            ),
        )
        if len(runner.edits) > before_edit_count:
            events.append(
                AgentRunEvent(
                    type="edits_ready",
                    edit_count=len(runner.edits),
                    operation_types=agent_operation_types(runner.edits),
                ),
            )
        if runner.finished:
            events.append(
                AgentRunEvent(
                    type="finish",
                    status=runner.finish_status,
                    missing=tuple(runner.finish_missing),
                ),
            )
            break

    events.append(
        AgentRunEvent(
            type="run_done",
            outcome=agent_run_outcome(
                events,
                finish_status=runner.finish_status,
                edit_count=len(runner.edits),
            ),
            status=runner.finish_status,
            missing=tuple(runner.finish_missing),
            edit_count=len(runner.edits),
            operation_types=agent_operation_types(runner.edits),
        ),
    )

    return AgentReplayResult(
        runner=runner,
        tools=tools,
        observations=observations,
        events=events,
    )


def _llm_tool_call(replay_call: ReplayToolCall, index: int) -> LlmToolCall:
    call_id = replay_call.call_id or f"call-{index}"
    return LlmToolCall(
        id=call_id,
        name=replay_call.name,
        arguments=replay_call.arguments,
        raw_arguments="{}",
    )
