from __future__ import annotations

from app.schemas.agent import AgentChatRequest, AgentConversationCheckpoint
from app.services.llm import AgentLlmConfig, LlmRequestError
from app.services.llm.types import LlmPrompt

from .context import (
    AgentContextWindowError,
    AgentConversationState,
    AgentRuntimeContext,
)
from .messages import (
    CHECKPOINT_CONTEXT_TOKEN_BUDGET,
    AgentPromptCompiler,
    agent_checkpoint_message_count,
    agent_compaction_boundaries,
    agent_prompt_limits,
    estimate_agent_messages_tokens,
)


async def prepare_agent_prompt(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    runtime: AgentRuntimeContext,
) -> LlmPrompt:
    """Build one bounded prompt without making a second model request."""

    await runtime.checkpoint()
    checkpoint = runtime.conversation_state.active_checkpoint
    prompt, next_checkpoint = await runtime.run_sync(
        _compile_agent_prompt,
        request,
        config,
        checkpoint.model_copy(deep=True) if checkpoint is not None else None,
    )
    runtime.conversation_state.active_checkpoint = next_checkpoint
    return prompt


def _compile_agent_prompt(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    checkpoint: AgentConversationCheckpoint | None,
) -> tuple[LlmPrompt, AgentConversationCheckpoint | None]:
    state = AgentConversationState(active_checkpoint=checkpoint)
    checkpoint_count = agent_checkpoint_message_count(
        request,
        state.active_checkpoint,
    )
    compiler = AgentPromptCompiler(
        request, config, history_start_count=checkpoint_count
    )
    prompt, checkpoint = _prompt_at_boundary(
        request,
        state=state,
        compiler=compiler,
        boundary_count=checkpoint_count,
    )
    limits = agent_prompt_limits(request, config)
    estimated_tokens = estimate_agent_messages_tokens(prompt.messages)
    compaction_triggered = (
        limits is not None and estimated_tokens > limits.trigger_tokens
    )

    if limits is not None and compaction_triggered:
        boundaries = agent_compaction_boundaries(
            request,
            after_count=checkpoint_count,
        )
        if boundaries:
            evaluated: dict[
                int,
                tuple[LlmPrompt, AgentConversationCheckpoint | None, int],
            ] = {}

            def candidate_at(
                index: int,
            ) -> tuple[LlmPrompt, AgentConversationCheckpoint | None, int]:
                if index not in evaluated:
                    boundary_count, _message_id = boundaries[index]
                    candidate_prompt, candidate_checkpoint = _prompt_at_boundary(
                        request,
                        state=state,
                        compiler=compiler,
                        boundary_count=boundary_count,
                    )
                    evaluated[index] = (
                        candidate_prompt,
                        candidate_checkpoint,
                        estimate_agent_messages_tokens(candidate_prompt.messages),
                    )
                return evaluated[index]

            # The newest cut is the smallest possible exact tail. Test it first
            # so an uncompressible current workspace fails without rebuilding
            # every older candidate. Otherwise find the earliest cut that reaches
            # the target, preserving as much exact recent history as possible.
            last_index = len(boundaries) - 1
            latest = candidate_at(last_index)
            if latest[2] > limits.target_tokens:
                prompt, checkpoint, estimated_tokens = latest
            else:
                low = 0
                high = last_index
                while low < high:
                    middle = (low + high) // 2
                    if candidate_at(middle)[2] <= limits.target_tokens:
                        high = middle
                    else:
                        low = middle + 1
                prompt, checkpoint, estimated_tokens = candidate_at(low)

    if (
        limits is not None
        and compaction_triggered
        and estimated_tokens > limits.target_tokens
    ):
        # Ordinary compaction keeps the latest historical user turn exact. That
        # preserves provider cache locality and conversational detail, but one
        # unusually large turn can still miss the target and leave no useful
        # headroom for tools. A rollover is the final, lossier cut: fold the
        # complete persisted history into the checkpoint while keeping the
        # current request and workspace exact.
        history_count = len(request.messages)
        if history_count > 0:
            checkpoint_token_budget = CHECKPOINT_CONTEXT_TOKEN_BUDGET
            handoff_prompt, handoff_checkpoint = _prompt_at_boundary(
                request,
                state=state,
                compiler=compiler,
                boundary_count=history_count,
                rebuild_checkpoint=True,
                checkpoint_token_budget=checkpoint_token_budget,
            )
            handoff_tokens = estimate_agent_messages_tokens(handoff_prompt.messages)
            if handoff_tokens > limits.target_tokens:
                checkpoint_token_budget = max(
                    1,
                    checkpoint_token_budget - (handoff_tokens - limits.target_tokens),
                )
                handoff_prompt, handoff_checkpoint = _prompt_at_boundary(
                    request,
                    state=state,
                    compiler=compiler,
                    boundary_count=history_count,
                    rebuild_checkpoint=True,
                    checkpoint_token_budget=checkpoint_token_budget,
                )
                handoff_tokens = estimate_agent_messages_tokens(
                    handoff_prompt.messages,
                )
            if handoff_tokens > limits.target_tokens and checkpoint_token_budget > 1:
                checkpoint_token_budget = 1
                handoff_prompt, handoff_checkpoint = _prompt_at_boundary(
                    request,
                    state=state,
                    compiler=compiler,
                    boundary_count=history_count,
                    rebuild_checkpoint=True,
                    checkpoint_token_budget=checkpoint_token_budget,
                )
                handoff_tokens = estimate_agent_messages_tokens(
                    handoff_prompt.messages,
                )
            prompt = handoff_prompt
            checkpoint = handoff_checkpoint
            estimated_tokens = handoff_tokens

    if limits is not None and estimated_tokens > limits.input_tokens:
        raise _context_window_error()

    return prompt, checkpoint


def _prompt_at_boundary(
    request: AgentChatRequest,
    *,
    state: AgentConversationState,
    compiler: AgentPromptCompiler,
    boundary_count: int,
    rebuild_checkpoint: bool = False,
    checkpoint_token_budget: int = CHECKPOINT_CONTEXT_TOKEN_BUDGET,
) -> tuple[LlmPrompt, AgentConversationCheckpoint | None]:
    checkpoint = _checkpoint_at_boundary(
        request,
        boundary_count,
        state=state,
        compiler=compiler,
        rebuild_checkpoint=rebuild_checkpoint,
        checkpoint_token_budget=checkpoint_token_budget,
    )
    return (
        compiler.build(checkpoint),
        checkpoint,
    )


def _checkpoint_at_boundary(
    request: AgentChatRequest,
    boundary_count: int,
    *,
    state: AgentConversationState,
    compiler: AgentPromptCompiler,
    rebuild_checkpoint: bool = False,
    checkpoint_token_budget: int = CHECKPOINT_CONTEXT_TOKEN_BUDGET,
) -> AgentConversationCheckpoint | None:
    if boundary_count <= 0:
        return None

    history = list(request.messages)
    message_id = _message_id(history[boundary_count - 1])
    if not message_id:
        raise LlmRequestError("The conversation checkpoint boundary is invalid.")
    active = state.active_checkpoint
    if (
        not rebuild_checkpoint
        and active is not None
        and active.through_message_id == message_id
    ):
        return active
    return AgentConversationCheckpoint(
        throughMessageId=message_id,
        summary=compiler.checkpoint_summary(boundary_count, checkpoint_token_budget),
    )


def _message_id(item: object) -> str | None:
    value = item.get("id") if isinstance(item, dict) else getattr(item, "id", None)
    return value if isinstance(value, str) and value else None


def _context_window_error() -> AgentContextWindowError:
    return AgentContextWindowError(
        "The current resume, attachments, and request exceed the selected model "
        "context window. Shorten the current input or choose a model with a "
        "larger context window.",
    )
