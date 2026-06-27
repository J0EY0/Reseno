from __future__ import annotations

from sqlite3 import Connection
from typing import Any

from app.services.llm_secrets import decrypt_api_key

from .common import DEFAULT_OPENAI_BASE_URL, REQUEST_TIMEOUT_SECONDS
from .types import AgentLlmConfig


def resolve_agent_llm_config(
    conn: Connection,
    model_config_data: dict[str, Any] | None,
) -> AgentLlmConfig | None:
    """Load the selected enabled model config and decrypt its API key."""

    client_id = ""
    if model_config_data:
        raw_client_id = model_config_data.get("id") or model_config_data.get(
            "client_id",
        )
        client_id = str(raw_client_id or "").strip()

    if client_id:
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
                supports_tools,
                supports_streaming,
                thinking_enabled
            FROM llm_configs
            WHERE client_id = ? AND enabled = 1
            """,
            (client_id,),
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
                supports_tools,
                supports_streaming,
                thinking_enabled
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

    return AgentLlmConfig(
        client_id=row["client_id"],
        name=row["name"],
        provider=row["provider"],
        provider_kind=row["provider_kind"],
        api_family=row["api_family"],
        model=row["model"],
        base_url=row["base_url"] or DEFAULT_OPENAI_BASE_URL,
        api_key=api_key,
        temperature=(
            float(row["temperature"]) if row["temperature"] is not None else None
        ),
        top_p=float(row["top_p"]) if row["top_p"] is not None else None,
        max_tokens=row["max_tokens"],
        timeout_seconds=int(row["timeout_seconds"] or REQUEST_TIMEOUT_SECONDS),
        context_window_tokens=row["context_window_tokens"],
        supports_image=bool(row["supports_image"]),
        supports_thinking=bool(row["supports_thinking"]),
        supports_tools=bool(row["supports_tools"]),
        supports_streaming=bool(row["supports_streaming"]),
        thinking_enabled=bool(row["thinking_enabled"]),
    )
