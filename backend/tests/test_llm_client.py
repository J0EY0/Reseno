from types import SimpleNamespace
from typing import Any

from app.services import llm_client
from app.services.llm_client import (
    AgentLlmConfig,
    complete_chat,
    complete_chat_stream,
    complete_chat_tool_call,
)


class FakeOpenAI:
    """Small SDK double used to verify request assembly without network calls."""

    init_kwargs: dict[str, Any] = {}
    create_params: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        FakeOpenAI.init_kwargs = kwargs
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(create=self.create_completion),
        )

    def create_completion(self, **kwargs: Any) -> object:
        """Record chat completion params and return one text choice."""

        FakeOpenAI.create_params = kwargs
        if kwargs.get("stream"):
            return iter(
                [
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(reasoning_content="think "),
                            ),
                        ],
                    ),
                    SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                delta=SimpleNamespace(content="streamed"),
                            ),
                        ],
                    ),
                ],
            )

        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="  SDK response  "),
                ),
            ],
        )


def test_complete_chat_uses_openai_sdk_base_url_root(monkeypatch) -> None:
    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)
    config = AgentLlmConfig(
        client_id="llm-test",
        name="Test Model",
        provider="openai",
        model="gpt-test",
        base_url="https://api.example.test/v1/chat/completions",
        api_key="sk-test-secret",
        temperature=0.3,
        top_p=0.8,
        max_tokens=256,
        timeout_seconds=12,
    )

    result = complete_chat(config, [{"role": "user", "content": "hello"}])

    assert result == "SDK response"
    assert FakeOpenAI.init_kwargs["api_key"] == "sk-test-secret"
    assert FakeOpenAI.init_kwargs["base_url"] == "https://api.example.test/v1"
    assert FakeOpenAI.init_kwargs["timeout"] == 12
    assert FakeOpenAI.create_params == {
        "model": "gpt-test",
        "messages": [{"role": "user", "content": "hello"}],
        "temperature": 0.3,
        "top_p": 0.8,
        "stream": False,
        "max_tokens": 256,
    }


def test_openai_base_url_accepts_provider_root() -> None:
    assert (
        llm_client._openai_base_url("https://api.deepseek.com")
        == "https://api.deepseek.com"
    )


def test_complete_chat_stream_yields_visible_text_only(monkeypatch) -> None:
    monkeypatch.setattr(llm_client, "OpenAI", FakeOpenAI)
    config = AgentLlmConfig(
        client_id="llm-test",
        name="Test Model",
        provider="openai",
        model="gpt-test",
        base_url="https://api.example.test/v1",
        api_key="sk-test-secret",
        temperature=0.3,
        top_p=0.8,
        max_tokens=None,
        timeout_seconds=12,
    )

    chunks = list(complete_chat_stream(config, [{"role": "user", "content": "hi"}]))

    assert [(chunk.kind, chunk.delta) for chunk in chunks] == [("text", "streamed")]
    assert FakeOpenAI.create_params["stream"] is True


def test_openai_responses_adapter_flattens_tools(monkeypatch) -> None:
    class FakeResponses:
        create_params: dict[str, Any] = {}

        def create(self, **kwargs: Any) -> object:
            FakeResponses.create_params = kwargs
            return SimpleNamespace(
                output_text="",
                output=[
                    {
                        "type": "function_call",
                        "call_id": "call-1",
                        "name": "edit_execute",
                        "arguments": '{"edits":[]}',
                    },
                ],
            )

    class FakeResponsesOpenAI:
        def __init__(self, **_: Any) -> None:
            self.responses = FakeResponses()

    monkeypatch.setattr(llm_client, "OpenAI", FakeResponsesOpenAI)
    config = AgentLlmConfig(
        client_id="llm-test",
        name="Test Model",
        provider="openai",
        model="gpt-test",
        base_url="https://api.openai.com/v1",
        api_key="sk-test-secret",
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=12,
        api_family="openai_responses",
        supports_thinking=True,
        thinking_enabled=True,
    )

    response = complete_chat_tool_call(
        config,
        [
            {"role": "system", "content": "system text"},
            {"role": "user", "content": "hello"},
        ],
        [
            {
                "type": "function",
                "function": {
                    "name": "edit_execute",
                    "description": "Execute edits",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ],
    )

    assert response.tool_calls[0].id == "call-1"
    assert response.tool_calls[0].arguments == {"edits": []}
    assert FakeResponses.create_params["instructions"] == "system text"
    assert FakeResponses.create_params["input"] == [
        {"role": "user", "content": "hello"},
    ]
    assert FakeResponses.create_params["tools"] == [
        {
            "type": "function",
            "name": "edit_execute",
            "description": "Execute edits",
            "parameters": {"type": "object", "properties": {}},
            "strict": False,
        },
    ]
    assert FakeResponses.create_params["reasoning"] == {"effort": "medium"}


def test_anthropic_adapter_maps_tool_schema_and_calls(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post_json(url: str, **kwargs: Any) -> dict[str, Any]:
        captured["url"] = url
        captured.update(kwargs)
        return {
            "content": [
                {"type": "text", "text": "checking"},
                {
                    "type": "tool_use",
                    "id": "toolu-1",
                    "name": "resume_lookup",
                    "input": {"query": "project"},
                },
            ],
        }

    monkeypatch.setattr(llm_client, "_post_json", fake_post_json)
    config = AgentLlmConfig(
        client_id="llm-test",
        name="Claude",
        provider="anthropic",
        model="claude-test",
        base_url="https://api.anthropic.com/v1",
        api_key="sk-ant-secret",
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=12,
        api_family="anthropic_messages",
    )

    response = complete_chat_tool_call(
        config,
        [
            {"role": "system", "content": "system text"},
            {"role": "user", "content": "hello"},
        ],
        [
            {
                "type": "function",
                "function": {
                    "name": "resume_lookup",
                    "description": "Lookup resume",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ],
    )

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-secret"
    assert captured["payload"]["system"] == "system text"
    assert captured["payload"]["messages"] == [
        {"role": "user", "content": "hello"},
    ]
    assert captured["payload"]["tools"] == [
        {
            "name": "resume_lookup",
            "description": "Lookup resume",
            "input_schema": {"type": "object", "properties": {}},
        },
    ]
    assert response.content == "checking"
    assert response.tool_calls[0].id == "toolu-1"
    assert response.tool_calls[0].arguments == {"query": "project"}


def test_gemini_adapter_builds_stateless_interaction(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_post_json(url: str, **kwargs: Any) -> dict[str, Any]:
        captured["url"] = url
        captured.update(kwargs)
        return {
            "steps": [
                {
                    "type": "function_call",
                    "id": "fc-1",
                    "name": "resume_lookup",
                    "arguments": {"query": "skills"},
                },
            ],
        }

    monkeypatch.setattr(llm_client, "_post_json", fake_post_json)
    config = AgentLlmConfig(
        client_id="llm-test",
        name="Gemini",
        provider="google",
        model="gemini-test",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="sk-gemini-secret",
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=12,
        api_family="google_gemini",
    )

    response = complete_chat_tool_call(
        config,
        [
            {"role": "system", "content": "system text"},
            {"role": "user", "content": "hello"},
        ],
        [
            {
                "type": "function",
                "function": {
                    "name": "resume_lookup",
                    "description": "Lookup resume",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ],
    )

    assert captured["url"] == (
        "https://generativelanguage.googleapis.com/v1beta/interactions"
    )
    assert captured["headers"]["x-goog-api-key"] == "sk-gemini-secret"
    assert captured["payload"]["store"] is False
    assert captured["payload"]["input"] == [
        {
            "type": "user_input",
            "content": [
                {
                    "type": "text",
                    "text": "System instructions:\nsystem text\n\nUser input:\nhello",
                },
            ],
        },
    ]
    assert captured["payload"]["tools"][0]["name"] == "resume_lookup"
    assert response.tool_calls[0].id == "fc-1"
    assert response.tool_calls[0].arguments == {"query": "skills"}
    assert response.provider_steps == [
        {
            "type": "function_call",
            "id": "fc-1",
            "name": "resume_lookup",
            "arguments": {"query": "skills"},
        },
    ]


def test_gemini_payload_replays_provider_steps_before_tool_result() -> None:
    config = AgentLlmConfig(
        client_id="llm-test",
        name="Gemini",
        provider="google",
        model="gemini-test",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        api_key="sk-gemini-secret",
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=12,
        api_family="google_gemini",
    )

    payload = llm_client._gemini_payload(
        config,
        [
            {"role": "user", "content": "hello"},
            {
                "role": "assistant",
                "content": None,
                "provider_steps": [
                    {
                        "type": "thought",
                        "text": "Need resume context.",
                    },
                    {
                        "type": "function_call",
                        "id": "fc-1",
                        "name": "resume_lookup",
                        "arguments": {"query": "skills"},
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "fc-1",
                "content": '{"matches":["Python"]}',
            },
        ],
    )

    assert payload["input"] == [
        {
            "type": "user_input",
            "content": [{"type": "text", "text": "hello"}],
        },
        {
            "type": "thought",
            "text": "Need resume context.",
        },
        {
            "type": "function_call",
            "id": "fc-1",
            "name": "resume_lookup",
            "arguments": {"query": "skills"},
        },
        {
            "type": "function_result",
            "name": "resume_lookup",
            "call_id": "fc-1",
            "result": [{"type": "text", "text": '{"matches":["Python"]}'}],
        },
    ]
