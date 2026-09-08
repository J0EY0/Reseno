from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from .errors import LlmRequestError
from .types import AgentLlmConfig, LlmContent, LlmInputMessage, LlmPrompt

# Keep input-estimation safety separate from the product's history-compaction
# headroom. The former protects one concrete provider request; the latter only
# decides when old conversation turns should be summarized.
MIN_INPUT_ESTIMATION_SAFETY_TOKENS = 256
MAX_INPUT_ESTIMATION_SAFETY_TOKENS = 4_096
INPUT_ESTIMATION_SAFETY_RATIO = 0.01
CONTEXT_COMPACTION_HEADROOM_TOKENS = 16_384
MIN_CONTEXT_INPUT_TOKENS = 4_096

# Base64 is transport encoding rather than model-visible text. Native media is
# therefore represented by a stable conservative reserve instead of counting
# every encoded byte as a token.
NATIVE_IMAGE_TOKEN_RESERVE = 4_096
NATIVE_FILE_TOKEN_RESERVE = 32_000

# Anthropic Messages requires max_tokens. Adaptive thinking and visible output
# share this allowance, so its Auto fallback must remain large enough for both.
ANTHROPIC_MANDATORY_AUTO_OUTPUT_TOKENS = 16_000


def resolve_request_output_budget(
    config: AgentLlmConfig,
    prompt: LlmPrompt,
    tools: list[dict[str, Any]] | None = None,
) -> AgentLlmConfig:
    """Return a request-scoped config with one dynamically safe output limit.

    ``max_tokens`` remains the persisted user override and
    ``model_max_output_tokens`` remains discovered capability metadata. Only the
    transient ``request_max_output_tokens`` is projected by provider adapters.
    Keeping those meanings separate prevents Auto from overwriting either user
    intent or the model's advertised maximum during a multi-step tool loop.
    """

    override = _positive_int(config.max_tokens)
    capability = _positive_int(config.model_max_output_tokens)
    desired = override
    if desired is not None and capability is not None:
        # Capabilities can shrink after a provider refresh while an older user
        # override remains stored. Never let stale configuration cross the
        # current model's documented hard limit.
        desired = min(desired, capability)
    elif desired is None and _anthropic_requires_output_limit(config):
        # Anthropic requires an explicit output allowance. Its discovered
        # maximum is a hard capability rather than a useful Auto target, so use
        # the bounded product default and only let capability metadata lower it.
        desired = ANTHROPIC_MANDATORY_AUTO_OUTPUT_TOKENS
        if capability is not None:
            desired = min(desired, capability)
    elif desired is None and config.provider_kind != "cloud":
        # Local/custom runtimes describe one shared input+output context. Keep
        # their discovered output ceiling in the same calculation that will
        # clamp it against this request's remaining context below.
        desired = capability

    input_ceiling = _positive_int(config.context_window_tokens)
    shared_context = shared_context_tokens(config)
    if input_ceiling is not None or shared_context is not None:
        estimated_input = estimate_prompt_tokens(prompt) + estimate_tools_tokens(tools)
        if (
            config.provider_kind == "cloud"
            and input_ceiling is not None
            and estimated_input
            > input_ceiling - input_estimation_safety_tokens(input_ceiling)
        ):
            raise LlmRequestError(
                "The current prompt and tools exceed the selected model's input "
                "context after the runtime estimation safety margin.",
            )
        if shared_context is not None:
            available_output = (
                shared_context
                - estimated_input
                - input_estimation_safety_tokens(shared_context)
            )
            if available_output < 1:
                raise LlmRequestError(
                    "The current prompt and tools exceed the selected model's "
                    "shared context after the runtime estimation safety margin.",
                )
            if desired is not None:
                desired = min(desired, available_output)
            elif config.provider_kind != "cloud":
                desired = available_output

    # Cloud providers which permit omission retain their native Auto behavior.
    # A discovered maximum is a capability ceiling, not a request-size choice.
    # We must neither project that maximum nor invent a smaller generic limit.
    if desired is None:
        return replace(config, request_max_output_tokens=None)

    return replace(config, request_max_output_tokens=desired)


def shared_context_tokens(config: AgentLlmConfig) -> int | None:
    """Return the known combined input/output ceiling for this deployment."""

    return _positive_int(
        config.shared_context_window_tokens
        if config.provider_kind == "cloud"
        else config.context_window_tokens
    )


def compaction_headroom_tokens(config: AgentLlmConfig) -> int:
    """Return the independent headroom used to trigger history compaction.

    Auto reserves 16K even when a model advertises a much larger output. That
    leaves the model's full capability available at request time without making
    a 64K/128K capability force premature history loss. A user override may
    deliberately change the reserve, while known model/context ceilings keep it
    valid for small models.
    """

    # This is a product planning allowance, not the request's hard output cap.
    # Larger user/model limits must not make history disappear earlier; smaller
    # limits can safely narrow the reserve because the request cannot exceed them.
    ceilings = [CONTEXT_COMPACTION_HEADROOM_TOKENS]
    if override := _positive_int(config.max_tokens):
        ceilings.append(override)
    if capability := _positive_int(config.model_max_output_tokens):
        ceilings.append(capability)
    reserve = min(ceilings)

    context_window = _positive_int(config.context_window_tokens)
    if context_window is not None:
        # Small contexts cannot afford the ordinary 16K history reserve. Clamp
        # it only after preserving both the exact transport safety amount that
        # request resolution deducts and a useful minimum prompt region. This
        # prevents the planner from accepting a prompt that dispatch must reject.
        reserve = min(
            reserve,
            max(
                1,
                context_window
                - input_estimation_safety_tokens(context_window)
                - MIN_CONTEXT_INPUT_TOKENS,
            ),
        )
    return reserve


def input_estimation_safety_tokens(context_ceiling: int) -> int:
    """Reserve bounded estimation error without disabling small contexts.

    A flat 4K margin consumes an entire 4K local model before the real prompt
    is considered. One percent scales with the selected context, while the
    256/4096 bounds keep both tiny and million-token windows predictable. The
    planner, compiler, and dispatch resolver all call this function so a prompt
    accepted by one layer cannot fail another layer because of different math.
    """

    return min(
        MAX_INPUT_ESTIMATION_SAFETY_TOKENS,
        max(
            MIN_INPUT_ESTIMATION_SAFETY_TOKENS,
            int(context_ceiling * INPUT_ESTIMATION_SAFETY_RATIO),
        ),
    )


def request_output_tokens(config: AgentLlmConfig) -> int | None:
    """Return the already-resolved provider projection, if one is available."""

    return _positive_int(config.request_max_output_tokens)


def anthropic_request_output_tokens(config: AgentLlmConfig) -> int:
    """Return Anthropic's mandatory field without reintroducing a 4K default."""

    return (
        request_output_tokens(config)
        or _positive_int(config.max_tokens)
        or _positive_int(config.model_max_output_tokens)
        or ANTHROPIC_MANDATORY_AUTO_OUTPUT_TOKENS
    )


def estimate_prompt_tokens(prompt: LlmPrompt) -> int:
    """Estimate neutral prompt tokens without counting base64 transport bytes."""

    estimated_messages: list[dict[str, Any]] = []
    media_tokens = 0
    for message in prompt.messages:
        projected, message_media_tokens = _message_without_media_bytes(message)
        estimated_messages.append(projected)
        media_tokens += message_media_tokens
    return _estimated_json_tokens(estimated_messages) + media_tokens


def estimate_tools_tokens(tools: list[dict[str, Any]] | None) -> int:
    """Estimate only tool definitions attached to the same provider request."""

    return _estimated_json_tokens(tools) if tools else 0


def _message_without_media_bytes(
    message: LlmInputMessage,
) -> tuple[dict[str, Any], int]:
    content: LlmContent | None = message.get("content")
    if not isinstance(content, list):
        return dict(message), 0

    media_tokens = 0
    estimated_parts: list[dict[str, Any]] = []
    for part in content:
        if part["type"] == "image":
            estimated_parts.append(
                {key: value for key, value in part.items() if key != "data"},
            )
            media_tokens += NATIVE_IMAGE_TOKEN_RESERVE
        elif part["type"] == "file":
            estimated_parts.append(
                {key: value for key, value in part.items() if key != "data"},
            )
            media_tokens += NATIVE_FILE_TOKEN_RESERVE
        else:
            estimated_parts.append(dict(part))
    return {**message, "content": estimated_parts}, media_tokens


def _estimated_json_tokens(value: Any) -> int:
    return _estimated_tokens(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
    )


def _estimated_tokens(text: str) -> int:
    ascii_count = sum(1 for char in text if ord(char) < 128)
    return max(1, (ascii_count + 3) // 4 + len(text) - ascii_count)


def _positive_int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def _anthropic_requires_output_limit(config: AgentLlmConfig) -> bool:
    return config.api_family == "anthropic_messages"
