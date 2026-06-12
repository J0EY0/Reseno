import json
from collections.abc import AsyncIterator, Callable, Iterator
from dataclasses import dataclass
from typing import Any

import anyio

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
from ..tools import AGENT_TOOL_SCHEMAS, AgentToolRunner, running_model_tool
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


def run_agent_tool_call_loop(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    on_tools: Callable[[list[AgentToolInvocation]], None] | None = None,
) -> AgentToolRunner:
    """Let the model choose tools, execute them, and return used-tool state."""

    runner: AgentToolRunner | None = None
    for event in iter_agent_tool_call_loop(request, config):
        if event.kind == "tools" and on_tools:
            on_tools(event.tools or [])
        if event.kind == "done":
            runner = event.runner

    if runner is None:
        raise RuntimeError("Agent tool loop finished without a runner.")

    return runner


def iter_agent_tool_call_loop(
    request: AgentChatRequest,
    config: AgentLlmConfig,
) -> Iterator[AgentToolLoopEvent]:
    """Yield tool-loop state as each model-selected action executes."""

    executor = AgentPlanExecutor(request)
    runner = AgentToolRunner(executor)
    messages = build_agent_messages(request, config, mode="tools")
    max_iterations = _react_max_iterations(request)

    for _ in range(max_iterations):
        response = get_agent_api().complete_chat_tool_call(
            config,
            messages,
            AGENT_TOOL_SCHEMAS,
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
            if tool_call.name != "finish":
                yield AgentToolLoopEvent(
                    kind="tools",
                    tools=[
                        *runner.tools,
                        running_model_tool(tool_call),
                    ],
                )
            tool, result = runner.run(tool_call)
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


async def _async_tool_call_response(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
) -> LlmToolCallResponse:
    """Return a tool-call response, preserving tests that monkeypatch sync calls."""

    agent_api = get_agent_api()
    sync_tool_call = agent_api.complete_chat_tool_call
    if sync_tool_call is not complete_chat_tool_call:
        return await anyio.to_thread.run_sync(
            sync_tool_call,
            config,
            messages,
            AGENT_TOOL_SCHEMAS,
        )

    return await async_complete_chat_tool_call(config, messages, AGENT_TOOL_SCHEMAS)


async def async_iter_agent_tool_call_loop(
    request: AgentChatRequest,
    config: AgentLlmConfig,
) -> AsyncIterator[AgentToolLoopEvent]:
    """Yield tool-loop state as each async model-selected action executes."""

    executor = AgentPlanExecutor(request)
    runner = AgentToolRunner(executor)
    messages = build_agent_messages(request, config, mode="tools")
    max_iterations = _react_max_iterations(request)

    for _ in range(max_iterations):
        response = await _async_tool_call_response(config, messages)
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
            if tool_call.name != "finish":
                yield AgentToolLoopEvent(
                    kind="tools",
                    tools=[
                        *runner.tools,
                        running_model_tool(tool_call),
                    ],
                )
            tool, result = runner.run(tool_call)
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
