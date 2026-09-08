from __future__ import annotations

from sqlite3 import Connection

from app.services.llm_secrets import decrypt_api_key
from app.services.model_discovery_cache import get_cached_provider_model
from app.services.model_metadata import resolve_model_metadata
from app.services.model_providers import resolve_model_provider_base_url
from app.services.thinking import ThinkingControl, can_project_thinking_off

from .common import DEFAULT_OPENAI_BASE_URL, REQUEST_TIMEOUT_SECONDS
from .errors import LlmThinkingModeUnsupportedError
from .types import AgentLlmConfig


def resolve_agent_llm_config(
    conn: Connection,
    selected_model_config_id: str | None,
) -> AgentLlmConfig | None:
    """Load the selected enabled model config and decrypt its API key."""

    model_config_id = (selected_model_config_id or "").strip()

    if model_config_id:
        row = conn.execute(
            """
            SELECT
                client_id,
                name,
                provider,
                provider_kind,
                api_family,
                model,
                base_url,
                encrypted_api_key,
                temperature,
                top_p,
                max_tokens,
                context_window_tokens,
                timeout_seconds,
                supports_image,
                supports_thinking,
                thinking_mode,
                can_disable_thinking,
                supports_tools,
                supports_streaming
            FROM llm_configs
            WHERE client_id = ? AND enabled = 1
            """,
            (model_config_id,),
        ).fetchone()
    else:
        row = conn.execute(
            """
            SELECT
                client_id,
                name,
                provider,
                provider_kind,
                api_family,
                model,
                base_url,
                encrypted_api_key,
                temperature,
                top_p,
                max_tokens,
                context_window_tokens,
                timeout_seconds,
                supports_image,
                supports_thinking,
                thinking_mode,
                can_disable_thinking,
                supports_tools,
                supports_streaming
            FROM llm_configs
            WHERE enabled = 1
            ORDER BY is_default DESC, created_at DESC, id DESC
            LIMIT 1
            """,
        ).fetchone()

    if row is None:
        return None

    encrypted_api_key = row["encrypted_api_key"]
    api_key = decrypt_api_key(encrypted_api_key) if encrypted_api_key else ""
    resolved_base_url = resolve_model_provider_base_url(
        row["provider"],
        row["provider_kind"],
        row["base_url"] or DEFAULT_OPENAI_BASE_URL,
    )

    discovered = get_cached_provider_model(row["provider"], row["model"])
    model_max_output_tokens = (
        discovered.max_output_tokens if discovered is not None else None
    )
    metadata = resolve_model_metadata(row["provider"], row["model"])
    if model_max_output_tokens is None:
        # Provider discovery is freshest and already normalized; the local
        # supplemental metadata cache is a limit fallback for configs loaded
        # before (or without) discovery.
        model_max_output_tokens = (
            metadata.max_output_tokens if metadata is not None else None
        )
    shared_context_window_tokens = None
    if row["provider_kind"] == "cloud":
        if discovered is not None:
            shared_context_window_tokens = discovered.shared_context_window_tokens
            if (
                shared_context_window_tokens is None
                and row["provider"] == "anthropic"
                and discovered.metadata_source in {"provider", "litellm"}
            ):
                shared_context_window_tokens = discovered.context_window_tokens
        if shared_context_window_tokens is None and metadata is not None:
            shared_context_window_tokens = metadata.shared_context_window_tokens

    thinking_control: ThinkingControl = "none"
    if row["thinking_mode"] == "off":
        # Persistence accepts Off only when discovery proved both a model-level
        # disable capability and a matching Adapter wire projection. Resolve it
        # to one explicit runtime action; never treat an omitted reasoning
        # parameter, a low effort, or a missing cache entry as equivalent.
        if not bool(row["can_disable_thinking"]) or not can_project_thinking_off(
            provider=row["provider"],
            provider_kind=row["provider_kind"],
            api_family=row["api_family"],
            base_url=resolved_base_url,
            model=row["model"],
        ):
            raise LlmThinkingModeUnsupportedError(
                "Thinking Off is unavailable for this model configuration.",
            )
        thinking_control = "native_off"
    elif row["provider_kind"] == "cloud":
        # A cloud config's persisted boolean is presentation data and may have
        # been written by an older heuristic. Runtime behavior trusts only the
        # current, versioned discovery snapshot.
        if discovered is not None:
            thinking_control = discovered.thinking_control
    elif bool(row["supports_thinking"]):
        # Custom and Ollama deployments own their model defaults; a checked
        # capability therefore means "leave the provider default alone". vLLM
        # and SGLang expose a verified explicit Auto control instead.
        thinking_control = (
            "native_auto"
            if row["provider_kind"] == "local" and row["provider"] in {"vllm", "sglang"}
            else "provider_default"
        )

    return AgentLlmConfig(
        client_id=row["client_id"],
        name=row["name"],
        provider=row["provider"],
        provider_kind=row["provider_kind"],
        api_family=row["api_family"],
        model=row["model"],
        base_url=resolved_base_url,
        api_key=api_key,
        temperature=(
            float(row["temperature"]) if row["temperature"] is not None else None
        ),
        top_p=float(row["top_p"]) if row["top_p"] is not None else None,
        max_tokens=row["max_tokens"],
        timeout_seconds=int(row["timeout_seconds"] or REQUEST_TIMEOUT_SECONDS),
        context_window_tokens=row["context_window_tokens"],
        model_max_output_tokens=model_max_output_tokens,
        shared_context_window_tokens=shared_context_window_tokens,
        supports_image=bool(row["supports_image"]),
        thinking_control=thinking_control,
        supports_tools=bool(row["supports_tools"]),
        supports_streaming=bool(row["supports_streaming"]),
        use_native_web_search=_use_native_web_search(
            provider=str(row["provider"]),
            provider_kind=str(row["provider_kind"]),
            api_family=str(row["api_family"]),
            model=str(row["model"]),
            model_supports_web_search=(
                metadata.supports_web_search is True if metadata is not None else False
            ),
        ),
    )


def _use_native_web_search(
    *,
    provider: str,
    provider_kind: str,
    api_family: str,
    model: str,
    model_supports_web_search: bool,
) -> bool:
    """Select one hosted-search protocol before the Agent loop starts."""

    if provider_kind != "cloud" or not model_supports_web_search:
        return False
    if provider == "openai" and api_family == "openai_responses":
        return True
    if provider == "anthropic" and api_family == "anthropic_messages":
        return True
    if provider == "google" and api_family == "google_gemini":
        # Gemini currently combines built-in and custom tools only on the
        # Gemini 3 family. Older searchable models use the local web tools so
        # edit_execute remains available in the same model turn.
        return model.strip().removeprefix("models/").startswith("gemini-3")
    return False
