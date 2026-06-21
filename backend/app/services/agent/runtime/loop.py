import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.schemas.agent import (
    AgentChatRequest,
    AgentResumeEditSuggestion,
    AgentToolInvocation,
)
from app.services.llm_client import (
    AgentLlmConfig,
    LlmToolCall,
    LlmToolCallResponse,
    async_complete_chat_tool_call,
    complete_chat_tool_call,
)

from ..compat import get_agent_api
from ..editing import _react_max_iterations
from ..executor import AgentPlanExecutor
from ..policy import capability_policy_for_request
from ..tools import (
    AgentToolRunner,
    agent_tool_schemas_for_names,
    running_model_tool,
)
from .context import AgentRuntimeContext
from .messages import build_agent_messages


@dataclass(frozen=True)
class AgentToolLoopEvent:
    """A user-visible state change produced by one ReAct tool loop."""

    kind: str
    text: str | None = None
    tools: list[AgentToolInvocation] | None = None
    edits: list[AgentResumeEditSuggestion] | None = None
    runner: "AgentToolRunner | None" = None
    terminal: bool = False


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


async def _async_tool_call_response(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    runtime: AgentRuntimeContext,
    tool_schemas: list[dict[str, Any]],
) -> LlmToolCallResponse:
    """Return a tool-call response, preserving tests that monkeypatch sync calls."""

    agent_api = get_agent_api()
    sync_tool_call = agent_api.complete_chat_tool_call
    if sync_tool_call is not complete_chat_tool_call:
        return await runtime.run_sync(
            sync_tool_call,
            config,
            messages,
            tool_schemas,
            timeout_seconds=config.timeout_seconds,
        )

    return await runtime.run_async(
        async_complete_chat_tool_call,
        config,
        messages,
        tool_schemas,
        timeout_seconds=config.timeout_seconds,
    )


async def async_iter_agent_tool_call_loop(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    runtime: AgentRuntimeContext | None = None,
) -> AsyncIterator[AgentToolLoopEvent]:
    """Yield tool-loop state as each async model-selected action executes."""

    runtime = runtime or AgentRuntimeContext()
    executor = AgentPlanExecutor(request)
    runner = AgentToolRunner(executor)
    messages = build_agent_messages(request, config, mode="tools")
    max_iterations = _react_max_iterations(request)
    policy = capability_policy_for_request(request)
    tool_schemas = agent_tool_schemas_for_names(policy.allowed_tools)

    for _ in range(max_iterations):
        await runtime.checkpoint()
        response = await _async_tool_call_response(
            config,
            messages,
            runtime,
            tool_schemas,
        )
        if not response.tool_calls:
            if response.content:
                runner.terminal_text = response.content
                runner.finished = True
                yield AgentToolLoopEvent(
                    kind="text",
                    text=response.content,
                    terminal=True,
                )
                break
            break

        tool_calls = response.tool_calls
        if response.content:
            yield AgentToolLoopEvent(kind="text", text=response.content)
        messages.append(
            _tool_call_assistant_message(
                response.content,
                tool_calls,
                response.reasoning,
            ),
        )
        tool_messages: list[dict[str, Any]] = []
        has_executed_edits = False
        for tool_call in tool_calls:
            await runtime.checkpoint()
            if tool_call.name != "finish":
                yield AgentToolLoopEvent(
                    kind="tools",
                    tools=[
                        *runner.tools,
                        running_model_tool(tool_call),
                    ],
                )
            tool, result = await runner.run(tool_call, runtime)
            if tool_call.name != "finish":
                yield AgentToolLoopEvent(kind="tools", tools=runner.tools)
            if tool_call.name == "edit_execute" and runner.edits:
                has_executed_edits = True
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                },
            )
        if has_executed_edits:
            yield AgentToolLoopEvent(kind="edits", edits=runner.edits)
        messages.extend(tool_messages)
        if runner.finished:
            break

    yield AgentToolLoopEvent(kind="done", runner=runner)
