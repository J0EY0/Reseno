from sqlite3 import Connection, Row
from typing import Any

from app.schemas.model_configs import ModelConfigResponse, ModelConfigUpsertRequest
from app.services.llm_secrets import (
    decrypt_api_key,
    encrypt_api_key,
    extract_plain_api_key,
    mask_api_key,
    mask_encrypted_api_key,
)
from app.services.model_metadata import resolve_model_metadata


def _row_to_response(row: Row) -> ModelConfigResponse:
    """Convert an llm_configs row into the frontend response shape."""

    preview = row["api_key_preview"] or mask_encrypted_api_key(row["encrypted_api_key"])

    return ModelConfigResponse(
        id=row["client_id"],
        provider=row["provider"],
        nickname=row["name"],
        apiKeyPreview=preview,
        model=row["model"],
        apiUrl=row["base_url"] or "",
        temperature=row["temperature"],
        topP=row["top_p"],
        maxTokens=row["max_tokens"],
        contextWindowTokens=row["context_window_tokens"],
        systemPrompt=row["system_prompt"] or "",
    )


def list_llm_configs(conn: Connection) -> list[ModelConfigResponse]:
    """List enabled model configs without exposing stored API keys."""

    rows = conn.execute(
        """
        SELECT
            client_id,
            name,
            provider,
            model,
            base_url,
            encrypted_api_key,
            api_key_preview,
            temperature,
            top_p,
            max_tokens,
            context_window_tokens,
            system_prompt
        FROM llm_configs
        WHERE enabled = 1
        ORDER BY updated_at DESC, id DESC
        """,
    ).fetchall()

    return [_row_to_response(row) for row in rows]


def _build_upsert_values(
    item: dict[str, Any],
    existing: Row | None,
) -> tuple[Any, ...]:
    """Normalize incoming config data into SQL upsert values."""

    client_id = str(item.get("id") or item.get("client_id") or "").strip()
    provider = str(item.get("provider") or "").strip()
    model = str(item.get("model") or "").strip()
    name = str(item.get("nickname") or item.get("name") or model).strip()
    base_url = str(item.get("apiUrl") or item.get("base_url") or "").strip()
    api_key = extract_plain_api_key(item)
    encrypted_api_key = existing["encrypted_api_key"] if existing else None
    api_key_preview = existing["api_key_preview"] if existing else ""

    if api_key:
        if existing and _existing_api_key_matches(existing, api_key):
            encrypted_api_key = existing["encrypted_api_key"]
            api_key_preview = existing["api_key_preview"]
        else:
            encrypted_api_key = encrypt_api_key(api_key)
            api_key_preview = mask_api_key(api_key)

    temperature = item.get("temperature")
    top_p = item.get("topP") if "topP" in item else item.get("top_p")
    max_tokens = (
        item.get("maxTokens") if "maxTokens" in item else item.get("max_tokens")
    )
    metadata = resolve_model_metadata(provider, model)
    context_window_tokens = (
        metadata.context_window_tokens
        if metadata is not None
        else _existing_context_window_tokens(existing, provider, model)
    )
    max_output_tokens = metadata.max_output_tokens if metadata is not None else None
    system_prompt = str(item.get("systemPrompt") or item.get("system_prompt") or "")
    return (
        client_id,
        name or model,
        provider,
        model,
        base_url or None,
        encrypted_api_key,
        api_key_preview,
        float(temperature) if isinstance(temperature, (int, float)) else 0.7,
        float(top_p) if isinstance(top_p, (int, float)) else 1.0,
        _normalize_max_tokens(max_tokens, max_output_tokens),
        context_window_tokens,
        system_prompt,
        0,
    )


def _existing_context_window_tokens(
    existing: Row | None,
    provider: str,
    model: str,
) -> int | None:
    if existing is None:
        return None

    if existing["provider"] != provider or existing["model"] != model:
        return None

    value = existing["context_window_tokens"]
    return value if isinstance(value, int) and value > 0 else None


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


def _is_same_upsert_values(existing: Row, values: tuple[Any, ...]) -> bool:
    """Return true when an upsert would not change the stored config row."""

    (
        client_id,
        name,
        provider,
        model,
        base_url,
        encrypted_api_key,
        api_key_preview,
        temperature,
        top_p,
        max_tokens,
        context_window_tokens,
        system_prompt,
        is_default,
    ) = values

    return (
        existing["enabled"] == 1
        and existing["client_id"] == client_id
        and existing["name"] == name
        and existing["provider"] == provider
        and existing["model"] == model
        and existing["base_url"] == base_url
        and existing["encrypted_api_key"] == encrypted_api_key
        and existing["api_key_preview"] == api_key_preview
        and float(existing["temperature"]) == float(temperature)
        and float(existing["top_p"]) == float(top_p)
        and existing["max_tokens"] == max_tokens
        and existing["context_window_tokens"] == context_window_tokens
        and existing["system_prompt"] == system_prompt
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
            model,
            base_url,
            encrypted_api_key,
            api_key_preview,
            temperature,
            top_p,
            max_tokens,
            context_window_tokens,
            system_prompt,
            enabled,
            is_default
        FROM llm_configs
        WHERE client_id = ?
        """,
        (client_id,),
    ).fetchone()
    return row if isinstance(row, Row) else None


def _merge_legacy_row_for_client_id(
    conn: Connection,
    item: dict[str, Any],
    client_id: str,
) -> None:
    """Attach a legacy generated row to the stable frontend client id."""

    provider = str(item.get("provider") or "").strip()
    model = str(item.get("model") or "").strip()
    name = str(item.get("nickname") or item.get("name") or model).strip()

    if not provider or not model:
        return

    legacy = conn.execute(
        """
        SELECT client_id
        FROM llm_configs
        WHERE
            client_id LIKE 'llm-db-%'
            AND provider = ?
            AND model = ?
            AND name = ?
        ORDER BY id ASC
        LIMIT 1
        """,
        (provider, model, name or model),
    ).fetchone()
    if legacy is None:
        return

    conn.execute(
        """
        UPDATE llm_configs
        SET
            client_id = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE client_id = ?
        """,
        (client_id, legacy["client_id"]),
    )


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

    client_id = str(item.get("id") or item.get("client_id") or "").strip()
    if not client_id:
        raise ValueError("Model config id is required.")

    existing = _select_llm_config(conn, client_id)
    if existing is None:
        _merge_legacy_row_for_client_id(conn, item, client_id)
        existing = _select_llm_config(conn, client_id)
    values = _build_upsert_values(item, existing)

    if existing is not None and _is_same_upsert_values(existing, values):
        return _row_to_response(existing)

    conn.execute(
        """
        INSERT INTO llm_configs (
            client_id,
            name,
            provider,
            model,
            base_url,
            encrypted_api_key,
            api_key_preview,
            temperature,
            top_p,
            max_tokens,
            context_window_tokens,
            system_prompt,
            is_default
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(client_id) DO UPDATE SET
            name = excluded.name,
            provider = excluded.provider,
            model = excluded.model,
            base_url = excluded.base_url,
            encrypted_api_key = COALESCE(
                excluded.encrypted_api_key,
                llm_configs.encrypted_api_key
            ),
            api_key_preview = COALESCE(
                NULLIF(excluded.api_key_preview, ''),
                llm_configs.api_key_preview
            ),
            temperature = excluded.temperature,
            top_p = excluded.top_p,
            max_tokens = excluded.max_tokens,
            context_window_tokens = excluded.context_window_tokens,
            system_prompt = excluded.system_prompt,
            enabled = 1,
            is_default = excluded.is_default,
            updated_at = CURRENT_TIMESTAMP
        """,
        values,
    )

    row = conn.execute(
        """
        SELECT
            client_id,
            name,
            provider,
            model,
            base_url,
            encrypted_api_key,
            api_key_preview,
            temperature,
            top_p,
            max_tokens,
            context_window_tokens,
            system_prompt
        FROM llm_configs
        WHERE client_id = ?
        """,
        (client_id,),
    ).fetchone()

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


def sync_llm_configs(
    conn: Connection,
    configs: list[Any],
    *,
    disable_missing: bool = False,
) -> None:
    """Mirror frontend model settings into llm_configs without storing plaintext."""

    active_client_ids: list[str] = []
    for item in configs:
        if isinstance(item, dict):
            client_id = str(item.get("id") or item.get("client_id") or "").strip()
            if client_id:
                active_client_ids.append(client_id)
            upsert_llm_config_dict(conn, item)

    if not disable_missing:
        return

    if not active_client_ids:
        conn.execute(
            """
            UPDATE llm_configs
            SET
                enabled = 0,
                is_default = 0,
                updated_at = CURRENT_TIMESTAMP
            """,
        )
        return

    placeholders = ",".join("?" for _ in active_client_ids)
    conn.execute(
        f"""
        UPDATE llm_configs
        SET
            enabled = 0,
            is_default = 0,
            updated_at = CURRENT_TIMESTAMP
        WHERE client_id NOT IN ({placeholders})
        """,
        active_client_ids,
    )
