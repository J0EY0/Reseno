import asyncio
from dataclasses import dataclass, field
from typing import Any

from app.schemas.agent import AgentChatRequest, AgentToolInvocation
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.tools import AgentToolRunner
from app.services.llm_client import LlmToolCall


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


def run_agent_replay(scenario: AgentReplayScenario) -> AgentReplayResult:
    """Replay a deterministic tool-call sequence against the local runner."""

    runner = AgentToolRunner(AgentPlanExecutor(scenario.request))
    tools: list[AgentToolInvocation] = []
    observations: list[dict[str, Any]] = []
    for index, replay_call in enumerate(scenario.tool_calls, start=1):
        tool_call = _llm_tool_call(replay_call, index)
        if replay_call.name in {
            "web_fetch",
            "web_search",
            "jd_url_fetch",
            "jd_reference_search",
        }:
            tool, observation = asyncio.run(
                runner.run(tool_call, AgentRuntimeContext()),
            )
        else:
            tool, observation = runner._run_local_tool(tool_call)
        tools.append(tool)
        observations.append(observation)

    return AgentReplayResult(runner=runner, tools=tools, observations=observations)


def _llm_tool_call(replay_call: ReplayToolCall, index: int) -> LlmToolCall:
    call_id = replay_call.call_id or f"call-{index}"
    return LlmToolCall(
        id=call_id,
        name=replay_call.name,
        arguments=replay_call.arguments,
        raw_arguments="{}",
    )
