from __future__ import annotations

from typing import Literal

# User-owned preference stored with one model configuration. ``auto`` delegates
# the choice to the model's discovered native behavior; ``off`` is accepted only
# when discovery explicitly proves that the provider can disable reasoning.
ThinkingMode = Literal["auto", "off"]

# Provider-neutral runtime action selected from the persisted preference and
# capability snapshot. Adapters consume this value without needing model-name
# tables: ``provider_default`` emits no control, while native modes request a
# provider's verified automatic, explicit-budget, or disabled protocol.
ThinkingControl = Literal[
    "none",
    "provider_default",
    "native_auto",
    "native_budget",
    "native_off",
]


# A model capability alone cannot make Off safe: the active Adapter must also
# know the provider's exact wire shape and endpoint. Keep that transport
# contract in one table shared by discovery, runtime validation, and Adapters
# so a newly added provider cannot advertise Off before it is implemented.
_NATIVE_OFF_TARGETS: dict[tuple[str, str], str] = {
    ("openai", "openai_responses"): "https://api.openai.com/v1",
    ("xai", "openai_responses"): "https://api.x.ai/v1",
    ("anthropic", "anthropic_messages"): "https://api.anthropic.com/v1",
    (
        "qwen",
        "openai_compatible_chat",
    ): "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ("deepseek", "openai_compatible_chat"): "https://api.deepseek.com",
    ("glm", "openai_compatible_chat"): "https://open.bigmodel.cn/api/paas/v4",
    ("minimax", "openai_compatible_chat"): "https://api.minimaxi.com/v1",
}


def available_thinking_modes(
    can_disable_thinking: bool,
) -> tuple[ThinkingMode, ...]:
    """Return the stable UI modes for a verified disable capability.

    ``auto`` is always valid, including for non-reasoning models, because it
    means Reseno will not force a disable protocol. ``off`` appears only when
    the normalized model capability guarantees an explicit provider request.
    """

    return ("auto", "off") if can_disable_thinking else ("auto",)


def can_project_thinking_off(
    *,
    provider: str,
    provider_kind: str,
    api_family: str,
    base_url: str,
    model: str,
) -> bool:
    """Return whether the active Adapter can send a genuine Off request.

    Official cloud endpoints are intentionally exact. OpenAI-compatible
    gateways may ignore or reinterpret vendor extensions, so matching only the
    API family would make the UI promise stronger than the request on the wire.
    MiniMax further limits the documented switch to M3; other MiniMax models
    must remain provider-managed even if a supplemental catalog is over-broad.
    """

    if provider_kind != "cloud":
        return False
    expected_base_url = _NATIVE_OFF_TARGETS.get((provider, api_family))
    normalized_base_url = base_url.strip().rstrip("/")
    if expected_base_url is None or normalized_base_url != expected_base_url:
        return False
    return provider != "minimax" or model.strip().casefold() == "minimax-m3"
