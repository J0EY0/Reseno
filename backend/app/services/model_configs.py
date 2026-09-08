import secrets
from contextlib import closing
from dataclasses import asdict, dataclass
from sqlite3 import Connection, Row

from app.db.connection import connect
from app.schemas.model_configs import (
    ApiFamily,
    ModelConfigResponse,
    ModelConfigUpsertRequest,
    ProviderKind,
)
from app.services.llm_secrets import (
    decrypt_api_key,
    encrypt_api_key,
    mask_api_key,
    mask_encrypted_api_key,
)
from app.services.model_discovery_cache import get_cached_provider_model
from app.services.model_metadata import is_provider_model, resolve_model_metadata
from app.services.model_providers import (
    DiscoveredModel,
    enrich_selected_model,
    get_model_provider,
    resolve_model_provider_base_url,
)
from app.services.thinking import ThinkingMode, available_thinking_modes

MODEL_CONFIG_ID_ALPHABET = (
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
)
MODEL_CONFIG_ID_LENGTH = 16


class ModelConfigNotFoundError(LookupError):
    """Raised when a requested model config id does not exist."""


@dataclass(frozen=True, kw_only=True)
class _ModelConfigValues:
    client_id: str
    name: str
    provider: str
    provider_kind: ProviderKind
    api_family: ApiFamily
    model: str
    base_url: str | None
    encrypted_api_key: str | None
    api_key_preview: str
    temperature: float | None
    top_p: float | None
    max_tokens: int | None
    context_window_tokens: int
    supports_image: bool
    supports_thinking: bool
    thinking_mode: ThinkingMode
    can_disable_thinking: bool
    supports_tools: bool
    supports_streaming: bool
    is_default: bool = False


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
        thinkingMode=row["thinking_mode"],
        availableThinkingModes=list(
            available_thinking_modes(bool(row["can_disable_thinking"])),
        ),
        supportsTools=bool(row["supports_tools"]),
        supportsStreaming=bool(row["supports_streaming"]),
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
            thinking_mode,
            can_disable_thinking,
            supports_tools,
            supports_streaming
        FROM llm_configs
        WHERE enabled = 1
        ORDER BY is_default DESC, created_at DESC, id DESC
        """,
    ).fetchall()

    return [_row_to_response(row) for row in rows]


def list_llm_configs() -> list[ModelConfigResponse]:
    """Load enabled model configs without exposing the persistence seam."""

    with closing(connect()) as conn:
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
    request: ModelConfigUpsertRequest,
    existing: Row | None,
) -> _ModelConfigValues:
    """Normalize incoming config data into SQL upsert values."""

    client_id = (request.client_id or "").strip()
    provider = request.provider.strip()
    provider_kind = request.provider_kind
    api_family = request.api_family
    model = request.model.strip()
    name = request.nickname.strip() or model
    base_url = resolve_model_provider_base_url(
        provider,
        provider_kind,
        request.api_url,
    )
    api_key = (request.api_key or "").strip() or None
    encrypted_api_key = None
    api_key_preview = ""

    if api_key:
        if existing and _existing_api_key_matches(existing, api_key):
            encrypted_api_key = existing["encrypted_api_key"]
            api_key_preview = existing["api_key_preview"]
        else:
            encrypted_api_key = encrypt_api_key(api_key)
            api_key_preview = mask_api_key(api_key)
    _validate_requested_config(
        provider=provider,
        provider_kind=provider_kind,
        api_family=api_family,
        model=model,
    )
    metadata = _selected_model_metadata(
        request=request,
        existing=existing,
        provider=provider,
        provider_kind=provider_kind,
        api_family=api_family,
        model=model,
        base_url=base_url,
        api_key=api_key,
    )
    is_cloud = provider_kind == "cloud"
    supports_image = metadata.supports_image if is_cloud else request.supports_image
    supports_thinking = (
        metadata.thinking_control != "none" if is_cloud else request.supports_thinking
    )
    can_disable_thinking = (
        provider_kind == "cloud" and "off" in metadata.available_thinking_modes
    )
    thinking_mode = _validated_thinking_mode(
        request.thinking_mode,
        can_disable_thinking=can_disable_thinking,
    )
    supports_tools = metadata.supports_tools if is_cloud else request.supports_tools
    supports_streaming = (
        metadata.supports_streaming if is_cloud else request.supports_streaming
    )

    return _ModelConfigValues(
        client_id=client_id,
        name=name,
        provider=provider,
        provider_kind=provider_kind,
        api_family=api_family,
        model=model,
        base_url=base_url or None,
        encrypted_api_key=encrypted_api_key,
        api_key_preview=api_key_preview,
        temperature=None if is_cloud else request.temperature,
        top_p=None if is_cloud else request.top_p,
        max_tokens=_validated_max_tokens(
            request.max_tokens,
            metadata.max_output_tokens,
        ),
        context_window_tokens=metadata.context_window_tokens,
        supports_image=supports_image,
        supports_thinking=supports_thinking,
        thinking_mode=thinking_mode,
        can_disable_thinking=can_disable_thinking,
        supports_tools=supports_tools,
        supports_streaming=supports_streaming,
    )


def _validate_requested_config(
    *,
    provider: str,
    provider_kind: str,
    api_family: str,
    model: str,
) -> None:
    if not provider or not model:
        raise ValueError("MODEL_CONFIG_INVALID_PROVIDER")

    if provider_kind == "local" and api_family != "openai_compatible_chat":
        raise ValueError("MODEL_CONFIG_INVALID_PROVIDER")


def _selected_model_metadata(
    *,
    request: ModelConfigUpsertRequest,
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

    context_window_tokens = request.context_window_tokens
    raw_model = (
        {"context_window": context_window_tokens}
        if context_window_tokens is not None and context_window_tokens > 0
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
    if not is_provider_model(provider, model):
        raise ValueError("MODEL_CONFIG_MODEL_NOT_DISCOVERED")

    if (
        existing is not None
        and not api_key
        and existing["provider"] == provider
        and existing["api_family"] == api_family
        and existing["model"] == model
        and (existing["base_url"] or "") == (base_url or "")
    ):
        discovered = get_cached_provider_model(provider, model)
        if discovered is not None:
            return discovered

        if provider == "anthropic":
            # Saved Anthropic capability bits from older builds may have come
            # from name heuristics and cannot prove adaptive-thinking support.
            # Reuse only current official discovery data for this provider.
            raise ValueError("MODEL_CONFIG_MODEL_NOT_DISCOVERED")

        # The config row stores the selected model snapshot, not a second copy
        # of the model capability catalog. If provider discovery data is no
        # longer present, consult the already-local supplemental metadata cache
        # so an update cannot bypass a known output ceiling. Token ceilings in
        # that cache still come from LiteLLM; this performs no network I/O.
        litellm_metadata = resolve_model_metadata(provider, model)
        return DiscoveredModel(
            id=model,
            label=model,
            context_window_tokens=int(existing["context_window_tokens"]),
            max_output_tokens=(
                litellm_metadata.max_output_tokens
                if litellm_metadata is not None
                else None
            ),
            supports_image=bool(existing["supports_image"]),
            thinking_control=(
                "provider_default" if bool(existing["supports_thinking"]) else "none"
            ),
            available_thinking_modes=available_thinking_modes(
                bool(existing["can_disable_thinking"]),
            ),
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


def _validated_thinking_mode(
    value: ThinkingMode,
    *,
    can_disable_thinking: bool,
) -> ThinkingMode:
    """Validate the reasoning preference against the selected model capability."""

    if value == "off" and not can_disable_thinking:
        raise ValueError("MODEL_CONFIG_THINKING_MODE_UNSUPPORTED")
    return value


def _validated_max_tokens(
    value: int | None,
    max_output_tokens: int | None,
) -> int | None:
    """Validate an optional output override against the selected model ceiling."""

    if value is None:
        return None
    if max_output_tokens is not None and value > max_output_tokens:
        raise ValueError("MODEL_CONFIG_MAX_TOKENS_EXCEEDS_LIMIT")
    return value


def _existing_api_key_matches(existing: Row, api_key: str) -> bool:
    """Return whether the incoming plaintext key matches stored ciphertext."""

    encrypted_api_key = existing["encrypted_api_key"]
    if not encrypted_api_key:
        return False

    try:
        return decrypt_api_key(encrypted_api_key) == api_key.strip()
    except RuntimeError:
        return False


def _same_nullable_float(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is None and right is None
    return float(left) == float(right)


def _is_same_upsert_values(existing: Row, values: _ModelConfigValues) -> bool:
    """Return true when an upsert would not change the stored config row."""

    return (
        existing["enabled"] == 1
        and existing["client_id"] == values.client_id
        and existing["name"] == values.name
        and existing["provider"] == values.provider
        and existing["provider_kind"] == values.provider_kind
        and existing["api_family"] == values.api_family
        and existing["model"] == values.model
        and existing["base_url"] == values.base_url
        and (
            values.encrypted_api_key is None
            or existing["encrypted_api_key"] == values.encrypted_api_key
        )
        and (
            not values.api_key_preview
            or existing["api_key_preview"] == values.api_key_preview
        )
        and _same_nullable_float(existing["temperature"], values.temperature)
        and _same_nullable_float(existing["top_p"], values.top_p)
        and existing["max_tokens"] == values.max_tokens
        and existing["context_window_tokens"] == values.context_window_tokens
        and bool(existing["supports_image"]) == values.supports_image
        and bool(existing["supports_thinking"]) == values.supports_thinking
        and existing["thinking_mode"] == values.thinking_mode
        and bool(existing["can_disable_thinking"]) == values.can_disable_thinking
        and bool(existing["supports_tools"]) == values.supports_tools
        and bool(existing["supports_streaming"]) == values.supports_streaming
        and bool(existing["is_default"]) == values.is_default
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
            thinking_mode,
            can_disable_thinking,
            supports_tools,
            supports_streaming,
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

    requested_client_id = (request.client_id or "").strip()
    existing = (
        _select_llm_config(conn, requested_client_id) if requested_client_id else None
    )
    client_id = (
        requested_client_id if existing is not None else _allocate_llm_config_id(conn)
    )
    values = _build_upsert_values(
        request.model_copy(update={"client_id": client_id}),
        existing,
    )

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
            thinking_mode,
            can_disable_thinking,
            supports_tools,
            supports_streaming,
            is_default
        )
        VALUES (
            :client_id,
            :name,
            :provider,
            :provider_kind,
            :api_family,
            :model,
            :base_url,
            :encrypted_api_key,
            :api_key_preview,
            :temperature,
            :top_p,
            :max_tokens,
            :context_window_tokens,
            :supports_image,
            :supports_thinking,
            :thinking_mode,
            :can_disable_thinking,
            :supports_tools,
            :supports_streaming,
            :is_default
        )
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
                    AND (
                        (llm_configs.provider_kind = 'cloud'
                            AND excluded.provider_kind = 'cloud')
                        OR COALESCE(llm_configs.base_url, '') =
                            COALESCE(excluded.base_url, '')
                    )
                    THEN llm_configs.encrypted_api_key
                ELSE NULL
            END,
            api_key_preview = CASE
                WHEN excluded.encrypted_api_key IS NOT NULL
                    THEN excluded.api_key_preview
                WHEN llm_configs.provider = excluded.provider
                    AND llm_configs.api_family = excluded.api_family
                    AND (
                        (llm_configs.provider_kind = 'cloud'
                            AND excluded.provider_kind = 'cloud')
                        OR COALESCE(llm_configs.base_url, '') =
                            COALESCE(excluded.base_url, '')
                    )
                    THEN llm_configs.api_key_preview
                ELSE ''
            END,
            temperature = excluded.temperature,
            top_p = excluded.top_p,
            max_tokens = excluded.max_tokens,
            context_window_tokens = excluded.context_window_tokens,
            supports_image = excluded.supports_image,
            supports_thinking = excluded.supports_thinking,
            thinking_mode = excluded.thinking_mode,
            can_disable_thinking = excluded.can_disable_thinking,
            supports_tools = excluded.supports_tools,
            supports_streaming = excluded.supports_streaming,
            enabled = 1,
            is_default = excluded.is_default,
            updated_at = CURRENT_TIMESTAMP
        """,
        asdict(values),
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


def delete_llm_configs(conn: Connection, client_ids: list[str]) -> list[str]:
    """Soft-delete existing model configs atomically in request order."""

    placeholders = ", ".join("?" for _ in client_ids)
    conn.execute("BEGIN IMMEDIATE")
    try:
        rows = conn.execute(
            f"""
            SELECT client_id
            FROM llm_configs
            WHERE client_id IN ({placeholders})
            """,
            client_ids,
        ).fetchall()
        if len(rows) != len(client_ids):
            raise ModelConfigNotFoundError

        conn.execute(
            f"""
            UPDATE llm_configs
            SET
                enabled = 0,
                is_default = 0,
                updated_at = CURRENT_TIMESTAMP
            WHERE client_id IN ({placeholders})
            """,
            client_ids,
        )
        conn.execute("COMMIT")
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise

    return client_ids
