from __future__ import annotations

import json
from dataclasses import replace

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentConversationCheckpoint,
)
from app.services.llm import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmRequestError,
    LlmTimeoutError,
    async_complete_chat,
    async_stream_chat,
)
from app.services.llm.common import request_max_output_tokens
from app.services.llm.types import LlmInputMessage

from ..prompts import COMPACTION_PROMPT
from .context import AgentRuntimeContext
from .messages import (
    AgentMessageMode,
    agent_checkpoint_message_count,
    agent_compaction_boundaries,
    agent_compaction_events,
    agent_prompt_limits,
    build_agent_messages,
    estimate_agent_messages_tokens,
    freeze_agent_workspace_snapshot,
    sanitize_agent_compaction_text,
)

MAX_COMPACTION_OUTPUT_TOKENS = 1_200
COMPACTION_SAFETY_MARGIN_TOKENS = 256


async def prepare_agent_messages(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    runtime: AgentRuntimeContext,
    *,
    mode: AgentMessageMode,
    draft: AgentChatMessage | None = None,
    force_attachment_text: bool = False,
) -> list[LlmInputMessage]:
    """Prepare one provider prompt, compacting old native turns when needed.

    ``build_agent_messages`` is deliberately pure: it projects only the
    checkpoint already present on the request. This async orchestration layer
    owns the optional compiler call and commits a new in-memory checkpoint only
    after the generated summary is valid and the rebuilt main prompt fits.
    Consequently cancellation, timeout, truncation, or any failed candidate
    leaves both the loaded and active durable boundary unchanged.
    """

    messages = build_agent_messages(
        request,
        config,
        mode=mode,
        draft=draft,
        force_attachment_text=force_attachment_text,
    )
    limits = agent_prompt_limits(request, config, mode=mode)
    if limits is None:
        return _freeze_and_return(request, messages, mode=mode)

    estimated_tokens = estimate_agent_messages_tokens(messages)
    if estimated_tokens <= limits.trigger_tokens:
        return _freeze_and_return(request, messages, mode=mode)

    original_checkpoint = request._active_conversation_checkpoint
    candidate_checkpoint = original_checkpoint
    start_count = agent_checkpoint_message_count(request)

    while estimated_tokens > limits.target_tokens:
        boundaries = agent_compaction_boundaries(
            request,
            after_count=start_count,
        )
        if not boundaries:
            if estimated_tokens <= limits.input_tokens:
                break
            raise _context_window_error()

        boundary_count, boundary_id = _select_boundary(
            request,
            config,
            mode=mode,
            draft=draft,
            force_attachment_text=force_attachment_text,
            boundaries=boundaries,
            previous_summary=(
                candidate_checkpoint.summary
                if candidate_checkpoint is not None
                else None
            ),
            target_tokens=limits.target_tokens,
        )
        summary_messages = _compaction_messages(
            request,
            previous_summary=(
                candidate_checkpoint.summary
                if candidate_checkpoint is not None
                else None
            ),
            start_count=start_count,
            end_count=boundary_count,
        )
        summary_messages, boundary_count, boundary_id = _fit_summary_request(
            request,
            config,
            previous_summary=(
                candidate_checkpoint.summary
                if candidate_checkpoint is not None
                else None
            ),
            start_count=start_count,
            desired_count=boundary_count,
            desired_id=boundary_id,
            boundaries=boundaries,
            messages=summary_messages,
        )
        summary = await _complete_compaction_summary(
            config,
            summary_messages,
            runtime,
        )
        summary = sanitize_agent_compaction_text(request, summary).strip()
        if not summary:
            raise LlmRequestError(
                "Model provider returned an empty conversation summary.",
            )

        candidate_checkpoint = AgentConversationCheckpoint(
            throughMessageId=boundary_id,
            summary=summary,
        )
        candidate_request = _request_with_checkpoint(request, candidate_checkpoint)
        candidate_messages = build_agent_messages(
            candidate_request,
            config,
            mode=mode,
            draft=draft,
            force_attachment_text=force_attachment_text,
        )
        estimated_tokens = estimate_agent_messages_tokens(candidate_messages)
        start_count = boundary_count
        messages = candidate_messages

        if estimated_tokens <= limits.target_tokens:
            break
        if not agent_compaction_boundaries(request, after_count=start_count):
            if estimated_tokens > limits.input_tokens:
                raise _context_window_error()
            break

    if estimated_tokens > limits.input_tokens:
        raise _context_window_error()

    # This is the only mutation in the compaction path. The durable writer will
    # persist it atomically with a successful assistant message; a later main
    # provider failure therefore still cannot create a checkpoint in SQLite.
    if candidate_checkpoint is not original_checkpoint:
        request._active_conversation_checkpoint = candidate_checkpoint
    return _freeze_and_return(request, messages, mode=mode)


def _freeze_and_return(
    request: AgentChatRequest,
    messages: list[LlmInputMessage],
    *,
    mode: AgentMessageMode,
) -> list[LlmInputMessage]:
    freeze_agent_workspace_snapshot(request, messages, mode=mode)
    return messages


def _select_boundary(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    mode: AgentMessageMode,
    draft: AgentChatMessage | None,
    force_attachment_text: bool,
    boundaries: list[tuple[int, str]],
    previous_summary: str | None,
    target_tokens: int,
) -> tuple[int, str]:
    """Keep the largest exact tail that leaves room for a bounded summary."""

    reserve_chars = max(
        len(previous_summary or ""),
        _compaction_output_tokens(config) * 4,
    )
    placeholder = "x" * reserve_chars
    for count, message_id in boundaries:
        checkpoint = AgentConversationCheckpoint(
            throughMessageId=message_id,
            summary=placeholder,
        )
        projected = build_agent_messages(
            _request_with_checkpoint(request, checkpoint),
            config,
            mode=mode,
            draft=draft,
            force_attachment_text=force_attachment_text,
        )
        if estimate_agent_messages_tokens(projected) <= target_tokens:
            return count, message_id
    return boundaries[-1]


def _fit_summary_request(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    previous_summary: str | None,
    start_count: int,
    desired_count: int,
    desired_id: str,
    boundaries: list[tuple[int, str]],
    messages: list[LlmInputMessage],
) -> tuple[list[LlmInputMessage], int, str]:
    """Chunk an oversized compiler input without changing summary semantics."""

    input_limit = _compaction_input_limit(config)
    if input_limit is None or estimate_agent_messages_tokens(messages) <= input_limit:
        return messages, desired_count, desired_id

    fitting: tuple[list[LlmInputMessage], int, str] | None = None
    for count, message_id in boundaries:
        if count > desired_count:
            break
        candidate = _compaction_messages(
            request,
            previous_summary=previous_summary,
            start_count=start_count,
            end_count=count,
        )
        if estimate_agent_messages_tokens(candidate) > input_limit:
            break
        fitting = (candidate, count, message_id)
    if fitting is None:
        raise LlmRequestError(
            "The selected model context window is too small to compact one "
            "complete conversation turn.",
        )
    return fitting


def _compaction_messages(
    request: AgentChatRequest,
    *,
    previous_summary: str | None,
    start_count: int,
    end_count: int,
) -> list[LlmInputMessage]:
    # A checkpoint was sanitized against the identity terms known when it was
    # created. Re-apply the current request boundary before sending it to the
    # private compiler because a later resume version may introduce a new name
    # or replace an identity value that the older checkpoint still contains.
    safe_previous_summary = (
        sanitize_agent_compaction_text(request, previous_summary)
        if previous_summary is not None
        else None
    )
    payload = {
        "previousSummary": safe_previous_summary,
        "conversation": agent_compaction_events(
            request,
            start_count=start_count,
            end_count=end_count,
        ),
    }
    return [
        {"role": "system", "content": COMPACTION_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {"conversationCompactionInput": payload},
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]


async def _complete_compaction_summary(
    config: AgentLlmConfig,
    messages: list[LlmInputMessage],
    runtime: AgentRuntimeContext,
) -> str:
    """Complete a private summary with existing activity timeout semantics."""

    summary_config = replace(
        config,
        max_tokens=_compaction_output_tokens(config),
        thinking_enabled=False,
    )
    for attempt in range(2):
        try:
            await runtime.checkpoint()
            if summary_config.supports_streaming:
                terminal: LlmAssistantMessage | None = None
                async for event in async_stream_chat(
                    summary_config,
                    messages,
                    request_context=None,
                ):
                    await runtime.checkpoint()
                    if terminal is not None:
                        raise LlmRequestError(
                            "Model provider returned events after completion.",
                        )
                    if event.type == "done":
                        terminal = event.message
            else:
                terminal = await async_complete_chat(
                    summary_config,
                    messages,
                    request_context=None,
                )
            await runtime.checkpoint()
            return _validated_summary(terminal)
        except LlmTimeoutError:
            if attempt == 1:
                raise
    raise AssertionError("unreachable")


def _validated_summary(message: LlmAssistantMessage | None) -> str:
    if message is None:
        raise LlmRequestError("Model provider returned an empty response.")
    if message.stop_reason == "length":
        raise LlmRequestError(
            "Model conversation summary was truncated.",
        )
    if message.stop_reason in {"content_filter", "error"}:
        raise LlmRequestError("Model provider could not summarize the conversation.")
    if message.tool_calls or message.validation_errors:
        raise LlmRequestError("Model provider returned tools during compaction.")
    text = message.content.strip()
    if not text:
        raise LlmRequestError("Model provider returned an empty conversation summary.")
    return text


def _request_with_checkpoint(
    request: AgentChatRequest,
    checkpoint: AgentConversationCheckpoint,
) -> AgentChatRequest:
    projected = request.model_copy(deep=False)
    projected._loaded_conversation_checkpoint = request._loaded_conversation_checkpoint
    projected._active_conversation_checkpoint = checkpoint
    return projected


def _compaction_output_tokens(config: AgentLlmConfig) -> int:
    return max(1, min(MAX_COMPACTION_OUTPUT_TOKENS, request_max_output_tokens(config)))


def _compaction_input_limit(config: AgentLlmConfig) -> int | None:
    if config.context_window_tokens is None:
        return None
    return max(
        1,
        config.context_window_tokens
        - _compaction_output_tokens(config)
        - COMPACTION_SAFETY_MARGIN_TOKENS,
    )


def _context_window_error() -> LlmRequestError:
    return LlmRequestError(
        "The current resume and conversation state exceed the selected model "
        "context window. Start a new conversation or choose a model with a "
        "larger context window.",
    )
