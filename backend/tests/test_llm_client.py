from types import SimpleNamespace
from typing import Any

from app.services import llm_client
from app.services.llm_client import AgentLlmConfig, complete_chat, complete_chat_stream


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
        system_prompt="",
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


def test_complete_chat_stream_yields_reasoning_and_text(monkeypatch) -> None:
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
        system_prompt="",
    )

    chunks = list(complete_chat_stream(config, [{"role": "user", "content": "hi"}]))

    assert [(chunk.kind, chunk.delta) for chunk in chunks] == [
        ("reasoning", "think "),
        ("text", "streamed"),
    ]
    assert FakeOpenAI.create_params["stream"] is True
