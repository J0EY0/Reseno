from cryptography.fernet import Fernet, InvalidToken
from fastapi import HTTPException, status

from app.config import get_settings


def _get_fernet() -> Fernet:
    """Build a Fernet helper from the configured master key."""

    return Fernet(get_settings().master_key.encode("ascii"))


def encrypt_api_key(api_key: str) -> str:
    """Encrypt a plaintext model API key for SQLite storage."""

    value = api_key.strip()
    if not value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="MODEL_CONFIG_API_KEY_REQUIRED",
        )

    return _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_api_key(encrypted_api_key: str) -> str:
    """Decrypt a stored model API key for request-time use only."""

    try:
        return _get_fernet().decrypt(encrypted_api_key.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Unable to decrypt API key with RESENO_MASTER_KEY.") from exc


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
