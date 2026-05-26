import os
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status

from app.config import MASTER_KEY_ENV_NAME, get_settings

SENSITIVE_MODEL_KEYS = {
    "apiKey",
    "api_key",
    "apiKeyEnvName",
    "api_key_env_name",
    "encryptedApiKey",
    "encrypted_api_key",
    "secretKey",
    "secret_key",
    "accessToken",
    "access_token",
    "refreshToken",
    "refresh_token",
    "authorization",
    "authorizationHeader",
    "authorization_header",
}


def _get_fernet() -> Fernet:
    """Build a Fernet helper from the configured master key."""

    get_settings()
    master_key = os.getenv(MASTER_KEY_ENV_NAME)
    if not master_key:
        raise RuntimeError(f"Missing {MASTER_KEY_ENV_NAME}.")

    return Fernet(master_key.encode("ascii"))


def encrypt_api_key(api_key: str) -> str:
    """Encrypt a plaintext model API key for SQLite storage."""

    value = api_key.strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API key is required.",
        )

    return _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_api_key(encrypted_api_key: str) -> str:
    """Decrypt a stored model API key for request-time use only."""

    try:
        return _get_fernet().decrypt(encrypted_api_key.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError(
            "Unable to decrypt API key with RESUMATE_MASTER_KEY."
        ) from exc


def mask_api_key(api_key: str) -> str:
    """Return a fixed-length preview that does not expose key length."""

    value = api_key.strip()
    if len(value) < 6:
        return "****"

    return f"{value[:6]}****"


def mask_encrypted_api_key(encrypted_api_key: str | None) -> str:
    """Decrypt and mask an encrypted key for safe API responses."""

    if not encrypted_api_key:
        return ""

    return mask_api_key(decrypt_api_key(encrypted_api_key))


def extract_plain_api_key(config: dict[str, Any]) -> str | None:
    """Read a plaintext API key from incoming client config data."""

    api_key = config.get("apiKey") or config.get("api_key")
    return api_key.strip() if isinstance(api_key, str) and api_key.strip() else None


def sanitize_model_config(config: dict[str, Any]) -> dict[str, Any]:
    """Remove secret-bearing fields from one model config object."""

    return {
        key: value for key, value in config.items() if key not in SENSITIVE_MODEL_KEYS
    }


def sanitize_workspace_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Remove model secrets and LLM config snapshots before SQLite persistence."""

    sanitized = dict(payload)
    changed = False

    for key in ("modelConfigs", "modelConfig"):
        if key in sanitized:
            sanitized.pop(key)
            changed = True

    return sanitized, changed
