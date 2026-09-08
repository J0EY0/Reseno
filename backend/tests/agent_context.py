from dataclasses import replace

from app.schemas.agent import AgentChatRequest
from app.services.agent.runtime.messages import (
    _tool_schema_token_reserve,
    agent_prompt_limits,
)
from app.services.llm import AgentLlmConfig


def with_message_budget(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    input_tokens: int,
) -> AgentLlmConfig:
    """Keep a fixed message allowance alongside the real request tool schemas."""

    window = input_tokens + _tool_schema_token_reserve(request, config)
    for _ in range(8):
        config = replace(config, context_window_tokens=window)
        limits = agent_prompt_limits(request, config)
        assert limits is not None
        if limits.input_tokens == input_tokens:
            return config
        window += input_tokens - limits.input_tokens
    raise AssertionError("Message budget did not converge to the requested limit.")
