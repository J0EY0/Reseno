from app.services import model_providers


def test_cloud_discovery_keeps_total_context_separate_from_input_limit(
    monkeypatch,
) -> None:
    monkeypatch.setattr(model_providers, "resolve_model_metadata", lambda *_: None)

    discovered = model_providers.enrich_selected_model(
        provider_id="openai",
        model_id="cloud-model",
        raw_model={"context_length": 999_999},
    )

    assert discovered.context_window_tokens == (
        model_providers.DEFAULT_CONTEXT_WINDOW_TOKENS
    )
    assert discovered.metadata_source == "fallback"
    assert discovered.shared_context_window_tokens == 999_999


def test_local_discovery_accepts_total_context_fields(monkeypatch) -> None:
    monkeypatch.setattr(model_providers, "resolve_model_metadata", lambda *_: None)

    discovered = model_providers.enrich_selected_model(
        provider_id="ollama",
        model_id="local-model",
        raw_model={"context_length": 32_768},
    )

    assert discovered.context_window_tokens == 32_768
    assert discovered.shared_context_window_tokens == 32_768
    assert discovered.metadata_source == "provider"


def test_gemini_discovery_accepts_explicit_input_limit(monkeypatch) -> None:
    monkeypatch.setattr(model_providers, "resolve_model_metadata", lambda *_: None)

    discovered = model_providers.enrich_selected_model(
        provider_id="google",
        model_id="gemini-test",
        raw_model={"name": "models/gemini-test", "inputTokenLimit": 1_048_576},
    )

    assert discovered.context_window_tokens == 1_048_576
    assert discovered.shared_context_window_tokens is None
    assert discovered.metadata_source == "provider"


def test_minimax_m3_discovery_reports_its_native_adaptive_thinking(monkeypatch) -> None:
    monkeypatch.setattr(model_providers, "resolve_model_metadata", lambda *_: None)

    discovered = model_providers.enrich_selected_model(
        provider_id="minimax",
        model_id="MiniMax-M3",
        raw_model={"inputTokenLimit": 1_000_000},
    )

    assert discovered.thinking_control == "native_auto"
