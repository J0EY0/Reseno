import secrets
from sqlite3 import Connection, Row
from typing import Any

from app.db.connection import connect
from app.schemas.model_configs import ModelConfigResponse, ModelConfigUpsertRequest
from app.services.llm_secrets import (
    decrypt_api_key,
    encrypt_api_key,
    extract_plain_api_key,
    mask_api_key,
    mask_encrypted_api_key,
)
from app.services.model_discovery_cache import get_cached_provider_model
from app.services.model_providers import (
    DiscoveredModel,
    enrich_selected_model,
    get_model_provider,
    resolve_model_provider_base_url,
)

MODEL_CONFIG_ID_ALPHABET = (
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
)
MODEL_CONFIG_ID_LENGTH = 16
SUPPORTED_API_FAMILIES = {
    "openai_responses",
    "openai_compatible_chat",
    "anthropic_messages",
    "google_gemini",
}
SUPPORTED_PROVIDER_KINDS = {"cloud", "local", "custom"}


def _row_to_response(row: Row) -> ModelConfigResponse:
    """Convert an llm_configs row into the frontend response shape."""

    preview = row["api_key_preview"] or mask_encrypted_api_key(row["encrypted_api_key"])
    provider = get_model_provider(row["provider"])

    return ModelConfigResponse(
        id=row["client_id"],
        provider=row["provider"],
        providerLabel=provider.label if provider is not None else row["provider"],
        iconProvider=(
            provider.icon_provider if provider is not None else row["provider"]
        ),
        apiFamily=row["api_family"],
        providerKind=row["provider_kind"],
        nickname=row["name"],
        apiKeyPreview=preview,
        model=row["model"],
        apiUrl=resolve_model_provider_base_url(
            row["provider"],
            row["provider_kind"],
            row["base_url"] or "",
        ),
        temperature=row["temperature"],
        topP=row["top_p"],
        maxTokens=row["max_tokens"],
        contextWindowTokens=row["context_window_tokens"],
        supportsImage=bool(row["supports_image"]),
        supportsThinking=bool(row["supports_thinking"]),
        supportsTools=bool(row["supports_tools"]),
        supportsStreaming=bool(row["supports_streaming"]),
        thinkingEnabled=bool(row["thinking_enabled"]),
    )


def _list_llm_configs(conn: Connection) -> list[ModelConfigResponse]:
    """List enabled model configs without exposing stored API keys."""

    rows = conn.execute(
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
            api_key_preview,
            temperature,
            top_p,
            max_tokens,
            context_window_tokens,
            supports_image,
            supports_thinking,
            supports_tools,
            supports_streaming,
            thinking_enabled
        FROM llm_configs
        WHERE enabled = 1
        ORDER BY is_default DESC, created_at DESC, id DESC
        """,
    ).fetchall()

    return [_row_to_response(row) for row in rows]


def list_llm_configs() -> list[ModelConfigResponse]:
    """Load enabled model configs without exposing the persistence seam."""

    with connect() as conn:
        return _list_llm_configs(conn)


def generate_model_config_id() -> str:
    """Generate a backend-owned model config id."""

    suffix = "".join(
        secrets.choice(MODEL_CONFIG_ID_ALPHABET) for _ in range(MODEL_CONFIG_ID_LENGTH)
    )
    return f"llm-{suffix}"


def _allocate_llm_config_id(conn: Connection) -> str:
    """Generate a model config id that does not currently exist."""

    for _ in range(20):
        client_id = generate_model_config_id()
        row = conn.execute(
            "SELECT 1 FROM llm_configs WHERE client_id = ?",
            (client_id,),
        ).fetchone()
        if row is None:
            return client_id

    raise RuntimeError("Failed to allocate a model config id.")


def _build_upsert_values(
    item: dict[str, Any],
    existing: Row | None,
) -> tuple[Any, ...]:
    """Normalize incoming config data into SQL upsert values."""

    client_id = str(item.get("id") or item.get("client_id") or "").strip()
    provider = str(item.get("provider") or "").strip()
    provider_kind = str(
        item.get("providerKind") or item.get("provider_kind") or "",
    ).strip()
    api_family = str(item.get("apiFamily") or item.get("api_family") or "").strip()
    model = str(item.get("model") or "").strip()
    name = str(item.get("nickname") or item.get("name") or model).strip()
    base_url = resolve_model_provider_base_url(
        provider,
        provider_kind,
        str(item.get("apiUrl") or item.get("base_url") or ""),
    )
    api_key = extract_plain_api_key(item)
    encrypted_api_key = None
    api_key_preview = ""

    if api_key:
        if existing and _existing_api_key_matches(existing, api_key):
            encrypted_api_key = existing["encrypted_api_key"]
            api_key_preview = existing["api_key_preview"]
        else:
            encrypted_api_key = encrypt_api_key(api_key)
            api_key_preview = mask_api_key(api_key)
    elif (
        existing is not None
        and provider_kind == "cloud"
        and existing["provider"] == provider
        and existing["api_family"] == api_family
    ):
        encrypted_api_key = existing["encrypted_api_key"]
        api_key_preview = existing["api_key_preview"]

    _validate_requested_config(
        provider=provider,
        provider_kind=provider_kind,
        api_family=api_family,
        model=model,
    )
    metadata = _selected_model_metadata(
        item=item,
        existing=existing,
        provider=provider,
        provider_kind=provider_kind,
        api_family=api_family,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    supports_image = _supports_image_value(
        item=item,
        provider_kind=provider_kind,
        metadata=metadata,
    )
    supports_thinking = _supports_thinking_value(
        item=item,
        provider_kind=provider_kind,
        metadata=metadata,
    )
    supports_tools = _supports_tools_value(
        item=item,
        provider_kind=provider_kind,
        metadata=metadata,
    )
    supports_streaming = _supports_streaming_value(
        item=item,
        provider_kind=provider_kind,
        metadata=metadata,
    )
    thinking_enabled = _thinking_enabled_value(
        item=item,
        supports_thinking=supports_thinking,
    )

    return (
        client_id,
        name or model,
        provider,
        provider_kind,
        api_family,
        model,
        base_url or None,
        encrypted_api_key,
        api_key_preview,
        (
            None
            if provider_kind == "cloud"
            else _optional_float(_raw_value(item, "temperature"))
        ),
        (
            None
            if provider_kind == "cloud"
            else _optional_float(_raw_value(item, "topP"))
        ),
        _normalize_max_tokens(
            None if provider_kind == "cloud" else _raw_value(item, "maxTokens"),
            metadata.max_output_tokens,
        ),
        metadata.context_window_tokens,
        int(supports_image),
        int(supports_thinking),
        int(supports_tools),
        int(supports_streaming),
        int(thinking_enabled),
        0,
    )


def _validate_requested_config(
    *,
    provider: str,
    provider_kind: str,
    api_family: str,
    model: str,
) -> None:
    if (
        not provider
        or not model
        or provider_kind not in SUPPORTED_PROVIDER_KINDS
        or api_family not in SUPPORTED_API_FAMILIES
    ):
        raise ValueError("MODEL_CONFIG_INVALID_PROVIDER")

    if provider_kind == "local" and api_family != "openai_compatible_chat":
        raise ValueError("MODEL_CONFIG_INVALID_PROVIDER")


def _selected_model_metadata(
    *,
    item: dict[str, Any],
    existing: Row | None,
    provider: str,
    provider_kind: str,
    api_family: str,
    model: str,
    base_url: str,
    api_key: str | None,
) -> DiscoveredModel:
    if provider_kind == "cloud":
        return _validated_cloud_model_metadata(
            existing=existing,
            provider=provider,
            api_family=api_family,
            model=model,
            base_url=base_url,
            api_key=api_key,
        )

    context_window_tokens = _positive_int(_raw_value(item, "contextWindowTokens"))
    raw_model = (
        {"context_window": context_window_tokens}
        if context_window_tokens is not None
        else {}
    )
    return enrich_selected_model(
        provider_id=provider,
        model_id=model,
        raw_model=raw_model,
    )


def _validated_cloud_model_metadata(
    *,
    existing: Row | None,
    provider: str,
    api_family: str,
    model: str,
    base_url: str,
    api_key: str | None,
) -> DiscoveredModel:
    if (
        existing is not None
        and not api_key
        and existing["provider"] == provider
        and existing["api_family"] == api_family
        and existing["model"] == model
        and (existing["base_url"] or "") == (base_url or "")
    ):
        return DiscoveredModel(
            id=model,
            label=model,
            context_window_tokens=int(existing["context_window_tokens"]),
            max_output_tokens=None,
            supports_image=bool(existing["supports_image"]),
            supports_thinking=bool(existing["supports_thinking"]),
            supports_tools=bool(existing["supports_tools"]),
            supports_streaming=bool(existing["supports_streaming"]),
            metadata_source="saved",
        )

    provider_manifest = get_model_provider(provider)
    if provider_manifest is None or provider_manifest.kind != "cloud":
        raise ValueError("MODEL_CONFIG_INVALID_PROVIDER")
    if provider_manifest.api_family != api_family:
        raise ValueError("MODEL_CONFIG_INVALID_PROVIDER")

    discovered = get_cached_provider_model(provider, model)
    if discovered is not None:
        return discovered

    raise ValueError("MODEL_CONFIG_MODEL_NOT_DISCOVERED")


def _supports_image_value(
    *,
    item: dict[str, Any],
    provider_kind: str,
    metadata: DiscoveredModel,
) -> bool:
    if provider_kind == "cloud":
        return metadata.supports_image
    return bool(_raw_value(item, "supportsImage") or False)


def _supports_thinking_value(
    *,
    item: dict[str, Any],
    provider_kind: str,
    metadata: DiscoveredModel,
) -> bool:
    if provider_kind == "cloud":
        return metadata.supports_thinking
    return bool(_raw_value(item, "supportsThinking") or False)


def _thinking_enabled_value(
    *,
    item: dict[str, Any],
    supports_thinking: bool,
) -> bool:
    if not supports_thinking:
        return False

    value = _raw_value(item, "thinkingEnabled")
    return True if value is None else bool(value)


def _supports_tools_value(
    *,
    item: dict[str, Any],
    provider_kind: str,
    metadata: DiscoveredModel,
) -> bool:
    """Return whether this config can run the agent's tool-selection loop."""

    if provider_kind != "cloud":
        value = _raw_value(item, "supportsTools")
        return bool(value) if value is not None else metadata.supports_tools

    return metadata.supports_tools


def _supports_streaming_value(
    *,
    item: dict[str, Any],
    provider_kind: str,
    metadata: DiscoveredModel,
) -> bool:
    """Return whether this config can stream final assistant text."""

    if provider_kind != "cloud":
        value = _raw_value(item, "supportsStreaming")
        return bool(value) if value is not None else metadata.supports_streaming

    return metadata.supports_streaming


def _raw_value(item: dict[str, Any], camel_key: str) -> Any:
    snake_key = _camel_to_snake(camel_key)
    return item.get(camel_key) if camel_key in item else item.get(snake_key)


def _camel_to_snake(value: str) -> str:
    result = []
    for char in value:
        if char.isupper():
            result.append("_")
            result.append(char.lower())
        else:
            result.append(char)
    return "".join(result).lstrip("_")


def _optional_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _positive_int(value: Any) -> int | None:
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.isdigit() and int(value) > 0:
        return int(value)
    return None


def _normalize_max_tokens(value: Any, max_output_tokens: int | None) -> int | None:
    if not isinstance(value, int) or value <= 0:
        return None

    if max_output_tokens is None:
        return value

    return min(value, max_output_tokens)


def _existing_api_key_matches(existing: Row, api_key: str) -> bool:
    """Return whether the incoming plaintext key matches stored ciphertext."""

    encrypted_api_key = existing["encrypted_api_key"]
    if not encrypted_api_key:
        return False

    try:
        return decrypt_api_key(encrypted_api_key) == api_key.strip()
    except RuntimeError:
        return False


def _same_nullable_float(left: Any, right: Any) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return float(left) == float(right)


def _is_same_upsert_values(existing: Row, values: tuple[Any, ...]) -> bool:
    """Return true when an upsert would not change the stored config row."""

    (
        client_id,
        name,
        provider,
        provider_kind,
        api_family,
        model,
        base_url,
        encrypted_api_key,
        api_key_preview,
        temperature,
        top_p,
        max_tokens,
        context_window_tokens,
        supports_image,
        supports_thinking,
        supports_tools,
        supports_streaming,
        thinking_enabled,
        is_default,
    ) = values

    return (
        existing["enabled"] == 1
        and existing["client_id"] == client_id
        and existing["name"] == name
        and existing["provider"] == provider
        and existing["provider_kind"] == provider_kind
        and existing["api_family"] == api_family
        and existing["model"] == model
        and existing["base_url"] == base_url
        and (
            encrypted_api_key is None
            or existing["encrypted_api_key"] == encrypted_api_key
        )
        and (not api_key_preview or existing["api_key_preview"] == api_key_preview)
        and _same_nullable_float(existing["temperature"], temperature)
        and _same_nullable_float(existing["top_p"], top_p)
        and existing["max_tokens"] == max_tokens
        and existing["context_window_tokens"] == context_window_tokens
        and int(existing["supports_image"]) == int(supports_image)
        and int(existing["supports_thinking"]) == int(supports_thinking)
        and int(existing["supports_tools"]) == int(supports_tools)
        and int(existing["supports_streaming"]) == int(supports_streaming)
        and int(existing["thinking_enabled"]) == int(thinking_enabled)
        and int(existing["is_default"]) == int(is_default)
    )


def _select_llm_config(conn: Connection, client_id: str) -> Row | None:
    """Load one model config row with all fields needed for comparison."""

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
            api_key_preview,
            temperature,
            top_p,
            max_tokens,
            context_window_tokens,
            supports_image,
            supports_thinking,
            supports_tools,
            supports_streaming,
            thinking_enabled,
            enabled,
            is_default
        FROM llm_configs
        WHERE client_id = ?
        """,
        (client_id,),
    ).fetchone()
    return row if isinstance(row, Row) else None


def upsert_llm_config(
    conn: Connection,
    request: ModelConfigUpsertRequest,
) -> ModelConfigResponse:
    """Create or update one model config from a validated API request."""

    return upsert_llm_config_dict(
        conn,
        request.model_dump(by_alias=True),
    )


def upsert_llm_config_dict(
    conn: Connection,
    item: dict[str, Any],
) -> ModelConfigResponse:
    """Create or update one model config from a raw workspace payload item."""

    requested_client_id = str(
        item.get("id") or item.get("client_id") or "",
    ).strip()
    existing = (
        _select_llm_config(conn, requested_client_id) if requested_client_id else None
    )
    client_id = (
        requested_client_id if existing is not None else _allocate_llm_config_id(conn)
    )
    item = {
        **item,
        "id": client_id,
        "client_id": client_id,
    }
    values = _build_upsert_values(item, existing)

    if existing is not None and _is_same_upsert_values(existing, values):
        conn.execute("BEGIN IMMEDIATE")
        try:
            current = _select_llm_config(conn, client_id)
            if current is None:
                raise RuntimeError("Failed to reload saved model config.")
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        return _row_to_response(current)

    conn.execute(
        """
        INSERT INTO llm_configs (
            client_id,
            name,
            provider,
            provider_kind,
            api_family,
            model,
            base_url,
            encrypted_api_key,
            api_key_preview,
            temperature,
            top_p,
            max_tokens,
            context_window_tokens,
            supports_image,
            supports_thinking,
            supports_tools,
            supports_streaming,
            thinking_enabled,
            is_default
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            name = excluded.name,
            provider = excluded.provider,
            provider_kind = excluded.provider_kind,
            api_family = excluded.api_family,
            model = excluded.model,
            base_url = excluded.base_url,
            encrypted_api_key = CASE
                WHEN excluded.encrypted_api_key IS NOT NULL
                    THEN excluded.encrypted_api_key
                WHEN llm_configs.provider = excluded.provider
                    AND llm_configs.api_family = excluded.api_family
                    AND COALESCE(llm_configs.base_url, '') =
                        COALESCE(excluded.base_url, '')
                    THEN llm_configs.encrypted_api_key
                ELSE NULL
            END,
            api_key_preview = CASE
                WHEN excluded.encrypted_api_key IS NOT NULL
                    THEN excluded.api_key_preview
                WHEN llm_configs.provider = excluded.provider
                    AND llm_configs.api_family = excluded.api_family
                    AND COALESCE(llm_configs.base_url, '') =
                        COALESCE(excluded.base_url, '')
                    THEN llm_configs.api_key_preview
                ELSE ''
            END,
            temperature = excluded.temperature,
            top_p = excluded.top_p,
            max_tokens = excluded.max_tokens,
            context_window_tokens = excluded.context_window_tokens,
            supports_image = excluded.supports_image,
            supports_thinking = excluded.supports_thinking,
            supports_tools = excluded.supports_tools,
            supports_streaming = excluded.supports_streaming,
            thinking_enabled = excluded.thinking_enabled,
            enabled = 1,
            is_default = excluded.is_default,
            updated_at = CURRENT_TIMESTAMP
        """,
        values,
    )

    row = _select_llm_config(conn, client_id)
    if row is None:
        raise RuntimeError("Failed to load saved model config.")

    return _row_to_response(row)


def delete_llm_config(conn: Connection, client_id: str) -> bool:
    """Soft-delete a model config by disabling it."""

    cursor = conn.execute(
        """
        UPDATE llm_configs
        SET
            enabled = 0,
            is_default = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE client_id = ?
        """,
        (client_id,),
    )

    return cursor.rowcount > 0
