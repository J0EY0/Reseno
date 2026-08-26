import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentCommittedDraft,
    AgentResumeEditSuggestion,
    AgentToolInvocation,
    AgentTransactionState,
)
from app.services.llm import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmRequestError,
    LlmStreamEvent,
    LlmToolCall,
    async_complete_chat,
    async_stream_chat,
    async_stream_tool_call,
)
from app.services.llm.types import (
    LlmAssistantInputMessage,
    LlmInputToolCall,
    LlmPrompt,
    LlmToolMessage,
)
from app.services.llm.validation import validation_error_observation

from ..environment import EnvironmentResult, ResumeToolEnvironment
from ..localization import agent_text
from .compaction import prepare_agent_prompt
from .context import AgentRuntimeContext, agent_llm_request_context
from .messages import fit_agent_model_turn_prompt


@dataclass(frozen=True)
class AgentTurnResult:
    """One loop-owned terminal result assembled from model and tool state."""

    message: AgentChatMessage | None
    tools: tuple[AgentToolInvocation, ...]
    edits: tuple[AgentResumeEditSuggestion, ...]
    transaction_state: AgentTransactionState
    terminal_text: str


class AgentModelTurnLimitError(LlmRequestError):
    """The model kept requesting actions until the bounded loop expired."""

    def __init__(self, result: AgentTurnResult) -> None:
        super().__init__(result.terminal_text)
        self.result = result


@dataclass(frozen=True)
class AgentToolLoopTextDelta:
    """One streamed text fragment from the current model turn."""

    text: str


@dataclass(frozen=True)
class AgentToolLoopTerminalText:
    """The model's authoritative natural-language completion."""

    text: str


@dataclass(frozen=True)
class AgentToolLoopTools:
    """One running or completed tool-state update."""

    tools: list[AgentToolInvocation]


@dataclass(frozen=True)
class AgentToolLoopEdits:
    """The current edit set and its transaction state."""

    edits: list[AgentResumeEditSuggestion]
    transaction_state: AgentTransactionState


@dataclass(frozen=True)
class AgentToolLoopCompleted:
    """A naturally completed loop with its closed environment result."""

    result: AgentTurnResult


type AgentToolLoopEvent = (
    AgentToolLoopTextDelta
    | AgentToolLoopTerminalText
    | AgentToolLoopTools
    | AgentToolLoopEdits
    | AgentToolLoopCompleted
)


def _running_model_tool(tool_call: LlmToolCall) -> AgentToolInvocation:
    """Build the loop-owned running UI event for a model-selected tool call."""

    return AgentToolInvocation(
        id=tool_call.id,
        type=f"tool-{tool_call.name}",
        title=tool_call.name,
        state="input-available",
        input=tool_call.arguments,
    )


def _turn_result(
    environment: EnvironmentResult,
    *,
    terminal_text: str,
) -> AgentTurnResult:
    """Combine loop-owned completion data with the closed environment state."""

    message = None
    if (
        environment.tools
        or environment.sources
        or environment.edits
        or environment.transaction_state == "rolled_back"
    ):
        message = AgentChatMessage(
            id=f"agent-msg-{uuid4().hex[:12]}",
            role="assistant",
            tone="success" if environment.edits else "default",
            text=terminal_text,
            tools=list(environment.tools),
            sources=list(environment.sources),
            edits=list(environment.edits),
            draft=(
                AgentCommittedDraft(baseResume=environment.base_resume)
                if environment.transaction_state == "committed" and environment.edits
                else None
            ),
            transactionState=environment.transaction_state,
        )
    return AgentTurnResult(
        message=message,
        tools=environment.tools,
        edits=environment.edits,
        transaction_state=environment.transaction_state,
        terminal_text=terminal_text,
    )


def _tool_call_assistant_message(
    content: str,
    tool_calls: list[LlmToolCall],
    reasoning: str = "",
    provider_state: dict[str, Any] | None = None,
) -> LlmAssistantInputMessage:
    """Serialize a model tool-call choice back into chat history."""

    serialized_calls = [
        LlmInputToolCall(
            id=tool_call.id,
            type="function",
            function={
                "name": tool_call.name,
                "arguments": tool_call.raw_arguments,
            },
        )
        for tool_call in tool_calls
    ]
    message = LlmAssistantInputMessage(
        role="assistant",
        content=content or None,
        tool_calls=serialized_calls,
    )
    if reasoning:
        message["reasoning_content"] = reasoning
    if provider_state:
        message["provider_state"] = provider_state

    return message


def _tool_result_message(tool_call_id: str, result: dict[str, Any]) -> LlmToolMessage:
    """Serialize one complete observation at the neutral transcript boundary."""

    return LlmToolMessage(
        role="tool",
        tool_call_id=tool_call_id,
        content=json.dumps(result, ensure_ascii=False),
    )


async def _async_iter_model_response(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    runtime: AgentRuntimeContext,
    tool_schemas: list[dict[str, Any]],
) -> AsyncIterator[LlmStreamEvent]:
    """Stream one normalized model turn, with tools only when supported."""

    await runtime.checkpoint()
    if config.supports_tools:
        stream = async_stream_tool_call(
            config,
            prompt,
            tool_schemas,
            request_context=runtime.llm_request_context,
            on_provider_attempt=runtime.record_llm_attempt,
        )
    elif config.supports_streaming:
        stream = async_stream_chat(
            config,
            prompt,
            request_context=runtime.llm_request_context,
            on_provider_attempt=runtime.record_llm_attempt,
        )
    else:
        response = await async_complete_chat(
            config,
            prompt,
            request_context=runtime.llm_request_context,
            on_provider_attempt=runtime.record_llm_attempt,
        )
        if response.content:
            yield LlmStreamEvent(type="text_delta", delta=response.content)
        runtime.record_llm_response(response)
        await runtime.checkpoint()
        yield LlmStreamEvent(type="done", message=response)
        return

    async for event in stream:
        if event.type == "done" and event.message is not None:
            # Usage and normalized provider state exist only on the terminal
            # event, so record them before the cancellation checkpoint.
            runtime.record_llm_response(event.message)
        await runtime.checkpoint()
        yield event


async def _async_iter_agent_tool_call_loop(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    runtime: AgentRuntimeContext,
    environment: ResumeToolEnvironment,
) -> AsyncIterator[AgentToolLoopEvent]:
    """Run the open model -> tool -> observation loop until natural completion."""

    prompt = await prepare_agent_prompt(
        request,
        config,
        runtime,
    )
    tool_schemas = environment.tool_schemas
    model_turns = 0
    completed = False
    terminal_text = ""

    while model_turns < runtime.max_model_turns:
        await runtime.checkpoint()
        prompt = fit_agent_model_turn_prompt(request, config, prompt)
        response: LlmAssistantMessage | None = None
        async for stream_event in _async_iter_model_response(
            config,
            prompt,
            runtime,
            tool_schemas,
        ):
            if stream_event.type == "text_delta":
                if stream_event.delta:
                    yield AgentToolLoopTextDelta(text=stream_event.delta)
                continue
            if stream_event.type == "done":
                response = stream_event.message
        if response is None:
            raise LlmRequestError(
                "Model provider stream ended before completion.",
            )

        model_turns += 1
        environment.record_sources(response.sources)
        if response.stop_reason == "length":
            raise LlmRequestError(
                "Model output was truncated. Increase max output tokens or use "
                "a model with a larger output budget.",
            )

        if not response.tool_calls:
            if not response.content.strip():
                raise LlmRequestError("Model provider returned an empty response.")
            terminal_text = response.content
            completed = True
            yield AgentToolLoopTerminalText(text=response.content)
            break

        validation_errors = {
            id(error.tool_call): error for error in response.validation_errors
        }
        valid_tool_calls = [
            tool_call
            for tool_call in response.tool_calls
            if id(tool_call) not in validation_errors
        ]
        prompt.messages.append(
            _tool_call_assistant_message(
                response.content,
                response.tool_calls,
                response.reasoning,
                response.provider_state,
            ),
        )
        executable_calls = environment.executable_tool_calls(valid_tool_calls)
        if executable_calls:
            yield AgentToolLoopTools(
                tools=[_running_model_tool(call) for call in executable_calls],
            )

        effects = await environment.invoke_batch(
            valid_tool_calls,
            runtime,
        )
        executable_call_ids = {id(tool_call) for tool_call in executable_calls}
        effects_by_call = {
            id(tool_call): effect
            for tool_call, effect in zip(valid_tool_calls, effects, strict=True)
        }
        tool_messages: list[LlmToolMessage] = []
        for tool_call in response.tool_calls:
            validation_error = validation_errors.get(id(tool_call))
            if validation_error is not None:
                tool_messages.append(
                    _tool_result_message(
                        tool_call.id,
                        validation_error_observation(validation_error),
                    ),
                )
                continue

            effect = effects_by_call[id(tool_call)]
            if id(tool_call) in executable_call_ids:
                yield AgentToolLoopTools(tools=[effect.invocation])
            tool_messages.append(
                _tool_result_message(
                    tool_call.id,
                    effect.observation,
                ),
            )
            if effect.edits_changed:
                yield AgentToolLoopEdits(
                    edits=list(effect.edits),
                    transaction_state=effect.transaction_state,
                )

        prompt.messages.extend(tool_messages)

    if not completed:
        terminal_text = agent_text(request.locale, "response.model_turn_limit")
        environment_result = environment.close(completed=False)
        result = _turn_result(
            environment_result,
            terminal_text=terminal_text,
        )
        if result.transaction_state == "rolled_back":
            yield AgentToolLoopEdits(
                edits=[],
                transaction_state="rolled_back",
            )
        raise AgentModelTurnLimitError(result)

    environment_result = environment.close(completed=True)
    result = _turn_result(
        environment_result,
        terminal_text=terminal_text,
    )
    if result.transaction_state == "rolled_back":
        yield AgentToolLoopEdits(
            edits=[],
            transaction_state="rolled_back",
        )
    yield AgentToolLoopCompleted(result=result)


async def async_iter_agent_tool_call_loop(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    runtime: AgentRuntimeContext | None = None,
) -> AsyncIterator[AgentToolLoopEvent]:
    """Yield one tool loop and roll back unfinished edits on every exit path."""

    runtime = runtime or AgentRuntimeContext()
    runtime = runtime.with_llm_request_context(
        agent_llm_request_context(request, config),
    )
    environment = ResumeToolEnvironment.open(
        request,
        include_web_tools=not config.use_native_web_search,
    )
    try:
        async for event in _async_iter_agent_tool_call_loop(
            request,
            config,
            runtime,
            environment,
        ):
            runtime.record_tool_loop_event(event)
            yield event
    except BaseException:
        environment.close(completed=False)
        raise
    finally:
        await environment.aclose()
