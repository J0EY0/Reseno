from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import Any

import pytest

from app.services.agent.tools.registry import AGENT_TOOL_SCHEMAS
from app.services.llm.adapters import (
    anthropic_messages,
    google_gemini,
    openai_chat,
    openai_responses,
)
from app.services.llm.tool_schema import portable_tool_schema
from app.services.llm.types import AgentLlmConfig

SchemaBuilder = Callable[
    [AgentLlmConfig, list[dict[str, Any]]],
    dict[str, Any],
]

UNSUPPORTED_PROVIDER_KEYWORDS = {
    "oneOf",
    "anyOf",
    "minProperties",
    "maxProperties",
    "const",
}


def _config() -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="schema-test",
        name="Schema Test",
        provider="openai",
        model="test-model",
        base_url="https://api.example.test/v1",
        api_key="sk-test",
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=10,
    )


def _canonical_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "edit_execute",
                "description": "Apply one canonical resume edit.",
                "parameters": {
                    "type": "object",
                    "description": "Strict edit input.",
                    "properties": {
                        "operation": {
                            "type": "string",
                            "description": "Edit operation.",
                            "enum": ["insert", "update"],
                        },
                        "payload": {
                            "oneOf": [
                                {
                                    "type": "object",
                                    "properties": {
                                        "mode": {"const": "insert"},
                                        "title": {
                                            "type": "string",
                                            "description": "Inserted title.",
                                        },
                                    },
                                    "required": ["mode", "title"],
                                    "minProperties": 2,
                                },
                                {
                                    "type": "object",
                                    "properties": {
                                        "mode": {"const": "update"},
                                        "patch": {
                                            "type": "object",
                                            "properties": {
                                                "title": {"type": "string"},
                                            },
                                            "minProperties": 1,
                                        },
                                    },
                                    "required": ["mode", "patch"],
                                },
                            ],
                        },
                        "selector": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "name": {"type": "string"},
                            },
                            "anyOf": [
                                {"required": ["id"]},
                                {"required": ["name"]},
                            ],
                        },
                    },
                    "required": ["operation", "payload"],
                    "minProperties": 2,
                    "additionalProperties": False,
                },
            },
        },
    ]


def _openai_chat_schema(
    config: AgentLlmConfig,
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    params = openai_chat._tool_completion_params(
        config,
        [{"role": "user", "content": "edit"}],
        tools,
    )
    return params["tools"][0]["function"]["parameters"]


def _openai_responses_schema(
    config: AgentLlmConfig,
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    params = openai_responses.responses_params(
        config,
        [{"role": "user", "content": "edit"}],
        tools=tools,
    )
    return params["tools"][0]["parameters"]


def _anthropic_schema(
    config: AgentLlmConfig,
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = anthropic_messages._payload(
        config,
        [{"role": "user", "content": "edit"}],
        tools,
    )
    return payload["tools"][0]["input_schema"]


def _gemini_schema(
    config: AgentLlmConfig,
    tools: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = google_gemini.gemini_payload(
        config,
        [{"role": "user", "content": "edit"}],
        tools,
    )
    return payload["tools"][0]["parameters"]


@pytest.mark.parametrize(
    "builder",
    [
        pytest.param(_openai_chat_schema, id="openai-chat"),
        pytest.param(_openai_responses_schema, id="openai-responses"),
        pytest.param(_anthropic_schema, id="anthropic"),
        pytest.param(_gemini_schema, id="gemini"),
    ],
)
def test_provider_tool_schemas_use_non_mutating_portable_projection(
    builder: SchemaBuilder,
) -> None:
    canonical_tools = _canonical_tools()
    original_tools = deepcopy(canonical_tools)

    schema = builder(_config(), canonical_tools)

    assert canonical_tools == original_tools
    assert not (_schema_keywords(schema) & UNSUPPORTED_PROVIDER_KEYWORDS)
    assert schema["type"] == "object"
    assert schema["description"] == "Strict edit input."
    assert schema["required"] == ["operation", "payload"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["operation"] == {
        "type": "string",
        "description": "Edit operation.",
        "enum": ["insert", "update"],
    }

    payload = schema["properties"]["payload"]
    assert payload["type"] == "object"
    assert payload["required"] == ["mode"]
    assert payload["properties"]["mode"]["enum"] == ["insert", "update"]
    assert payload["properties"]["title"]["description"] == "Inserted title."
    assert payload["properties"]["patch"]["type"] == "object"
    # The canonical alias rule remains strict locally. Providers receive the
    # shared fields but not a union keyword that some APIs reject.
    assert "required" not in schema["properties"]["selector"]


@pytest.mark.parametrize(
    "builder",
    [
        pytest.param(_openai_chat_schema, id="openai-chat"),
        pytest.param(_openai_responses_schema, id="openai-responses"),
        pytest.param(_anthropic_schema, id="anthropic"),
        pytest.param(_gemini_schema, id="gemini"),
    ],
)
def test_current_agent_tool_schemas_are_portable_for_every_provider(
    builder: SchemaBuilder,
) -> None:
    canonical_tools = deepcopy(AGENT_TOOL_SCHEMAS)
    original_tools = deepcopy(canonical_tools)

    for tool in canonical_tools:
        schema = builder(_config(), [tool])
        assert not (_schema_keywords(schema) & UNSUPPORTED_PROVIDER_KEYWORDS)
        assert schema["type"] == "object"
        assert isinstance(schema.get("properties"), dict)

    assert canonical_tools == original_tools


def test_gemini_declares_every_current_tool_with_complete_parameters() -> None:
    canonical_tools = deepcopy(AGENT_TOOL_SCHEMAS)

    payload = google_gemini.gemini_payload(
        _config(),
        [{"role": "user", "content": "edit"}],
        canonical_tools,
    )

    assert payload["tools"] == [
        {
            "type": "function",
            "name": tool["function"]["name"],
            "description": tool["function"]["description"],
            "parameters": portable_tool_schema(
                tool["function"]["parameters"],
            ),
        }
        for tool in canonical_tools
    ]


def _schema_keywords(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key for child in value.values() for key in _schema_keywords(child)
        }
    if isinstance(value, list):
        return {key for child in value for key in _schema_keywords(child)}
    return set()
