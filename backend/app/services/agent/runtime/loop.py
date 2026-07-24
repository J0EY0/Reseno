import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

from app.schemas.agent import (
    AgentChatRequest,
    AgentResumeEditSuggestion,
    AgentToolInvocation,
    AgentTransactionState,
)
from app.services.llm import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmRequestError,
    LlmToolCall,
    async_complete_tool_call,
)
from app.services.llm.validation import validation_error_observation

from ..editing import _react_max_iterations
from ..executor import AgentPlanExecutor
from ..policy import capability_policy_for_request
from ..tools.registry import agent_tool_schemas_for_names
from ..tools.runner import AgentToolRunner, running_model_tool
from .context import AgentRuntimeContext
from .messages import (
    build_agent_messages,
    has_native_current_request_attachments,
    is_native_attachment_unsupported,
)


@dataclass(frozen=True)
class AgentToolLoopEvent:
    """A user-visible state change produced by one ReAct tool loop."""

    kind: str
    text: str | None = None
    tools: list[AgentToolInvocation] | None = None
    edits: list[AgentResumeEditSuggestion] | None = None
    transaction_state: AgentTransactionState = "none"
    runner: "AgentToolRunner | None" = None
    terminal: bool = False


def _tool_call_assistant_message(
    content: str,
    tool_calls: list[LlmToolCall],
    reasoning: str = "",
    provider_state: dict[str, Any] | None = None,
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
    if provider_state:
        message["provider_state"] = provider_state

    return message


async def _async_tool_call_response(
    config: AgentLlmConfig,
    messages: list[dict[str, Any]],
    runtime: AgentRuntimeContext,
    tool_schemas: list[dict[str, Any]],
) -> LlmAssistantMessage:
    """Return a validated tool-call response through the async LLM runtime."""

    return await runtime.run_async(
        async_complete_tool_call,
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
    if not config.supports_tools:
        # Tool support controls only the agent action loop. Models without it
        # can still answer the user through the final chat-completion stream.
        return

    executor = AgentPlanExecutor(request)
    runner = AgentToolRunner(executor)
    messages = build_agent_messages(request, config, mode="tools")
    max_iterations = _react_max_iterations(request)
    policy = capability_policy_for_request(request)
    tool_schemas = agent_tool_schemas_for_names(policy.allowed_tools)
    schema_retry_used = False
    rollback_emitted = False
    provider_response_received = False
    native_fallback_available = has_native_current_request_attachments(
        request,
        config,
    )

    for _ in range(max_iterations):
        await runtime.checkpoint()
        try:
            response = await _async_tool_call_response(
                config,
                messages,
                runtime,
                tool_schemas,
            )
        except LlmRequestError as exc:
            if (
                provider_response_received
                or not native_fallback_available
                or runner.native_attachment_text_fallback_used
                or not is_native_attachment_unsupported(exc)
            ):
                raise

            # Retry exactly once and only before the provider has accepted any
            # part of this turn. This avoids replaying completed tools.
            runner.native_attachment_text_fallback_used = True
            messages = build_agent_messages(
                request,
                config,
                mode="tools",
                force_attachment_text=True,
            )
            response = await _async_tool_call_response(
                config,
                messages,
                runtime,
                tool_schemas,
            )

        provider_response_received = True
        if response.stop_reason == "length":
            raise LlmRequestError(
                "Model output was truncated. Increase max output tokens or use "
                "a model with a larger output budget.",
            )
        if response.validation_errors:
            if schema_retry_used:
                raise LlmRequestError(
                    "Model tool arguments failed validation after retry.",
                )

            schema_retry_used = True
            invalid_tool_calls = [
                error.tool_call for error in response.validation_errors
            ]
            messages.append(
                _tool_call_assistant_message(
                    response.content,
                    invalid_tool_calls,
                    response.reasoning,
                    response.provider_state,
                ),
            )
            messages.extend(
                {
                    "role": "tool",
                    "tool_call_id": error.tool_call.id,
                    "content": json.dumps(
                        validation_error_observation(error),
                        ensure_ascii=False,
                    ),
                }
                for error in response.validation_errors
            )
            continue

        schema_retry_used = False
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
                response.provider_state,
            ),
        )
        tool_messages: list[dict[str, Any]] = []
        revision_before_tools = runner.edit_revision
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
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                },
            )
            if runner.transaction_failed:
                break
        if runner.transaction_failed:
            rollback_emitted = True
            yield AgentToolLoopEvent(
                kind="edits",
                edits=[],
                transaction_state="rolled_back",
            )
        elif runner.edit_revision != revision_before_tools and runner.edits:
            yield AgentToolLoopEvent(
                kind="edits",
                edits=runner.edits,
                transaction_state="provisional",
            )
        messages.extend(tool_messages)
        if runner.finished:
            break

    revision_before_finalize = runner.edit_revision
    runner.finalize_turn()
    if (
        runner.transaction_failed
        and not rollback_emitted
        and runner.edit_revision != revision_before_finalize
    ):
        yield AgentToolLoopEvent(
            kind="edits",
            edits=[],
            transaction_state="rolled_back",
        )
    yield AgentToolLoopEvent(kind="done", runner=runner)
