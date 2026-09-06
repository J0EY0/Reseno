import hashlib
import secrets
import time
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from hmac import compare_digest
from typing import Literal, cast

from app.schemas.common import (
    APP_MESSAGE_OAUTH_ALREADY_BOUND,
    APP_MESSAGE_OAUTH_EXCHANGE_EXPIRED,
    APP_MESSAGE_OAUTH_NOT_BOUND,
    APP_MESSAGE_OAUTH_OWNER_CHANGED,
)
from app.services.auth_accounts import OwnerAccount, connect_auth_database

OAuthProvider = Literal["github"]
OAuthIntent = Literal["login", "bind"]
OAUTH_PROVIDERS: tuple[OAuthProvider, ...] = ("github",)
OAUTH_CODE_TTL_SECONDS = 60


class OAuthFlowError(Exception):
    """A public error code for an unsuccessful identity operation."""


@dataclass(frozen=True)
class OAuthIdentity:
    provider: OAuthProvider
    subject: str
    label: str
    created_at: str = ""


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def list_identities() -> list[OAuthIdentity]:
    with closing(connect_auth_database()) as conn:
        rows = conn.execute(
            "SELECT provider, subject, label, created_at FROM auth_identities"
        ).fetchall()
    return [
        OAuthIdentity(
            provider=cast(OAuthProvider, row["provider"]),
            subject=row["subject"],
            label=row["label"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


def get_owner_revision() -> str:
    with closing(connect_auth_database()) as conn:
        row = conn.execute(
            "SELECT auth_revision FROM auth_owner WHERE id = 1"
        ).fetchone()
    if row is None:
        raise OAuthFlowError(APP_MESSAGE_OAUTH_OWNER_CHANGED)
    return str(row["auth_revision"])


def create_oauth_code(
    identity: OAuthIdentity,
    intent: OAuthIntent,
    owner_revision: str,
    browser: str,
) -> str:
    code = secrets.token_urlsafe(32)
    now = int(time.time())
    with closing(connect_auth_database()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM auth_oauth_codes WHERE expires_at <= ?", (now,))
        owner = conn.execute(
            "SELECT auth_revision FROM auth_owner WHERE id = 1"
        ).fetchone()
        if owner is None or not compare_digest(owner["auth_revision"], owner_revision):
            raise OAuthFlowError(APP_MESSAGE_OAUTH_OWNER_CHANGED)
        bound = conn.execute(
            "SELECT subject, revision FROM auth_identities WHERE provider = ?",
            (identity.provider,),
        ).fetchone()
        if intent == "login" and (
            bound is None or not compare_digest(bound["subject"], identity.subject)
        ):
            raise OAuthFlowError(APP_MESSAGE_OAUTH_NOT_BOUND)
        if intent == "bind" and bound is not None:
            raise OAuthFlowError(APP_MESSAGE_OAUTH_ALREADY_BOUND)
        conn.execute(
            """
            INSERT INTO auth_oauth_codes (
                code_hash, browser_hash, provider, subject, label, intent,
                owner_revision, identity_revision, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _hash(code),
                _hash(browser),
                identity.provider,
                identity.subject,
                identity.label,
                intent,
                owner_revision,
                bound["revision"] if bound is not None else None,
                now + OAUTH_CODE_TTL_SECONDS,
            ),
        )
    return code


def consume_oauth_code(
    code: str,
    browser: str,
) -> tuple[OAuthProvider, OAuthIntent, OwnerAccount]:
    error: str | None = None
    result: tuple[OAuthProvider, OAuthIntent, OwnerAccount] | None = None
    now = int(time.time())
    with closing(connect_auth_database()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM auth_oauth_codes WHERE expires_at <= ?", (now,))
        row = conn.execute(
            "SELECT * FROM auth_oauth_codes WHERE code_hash = ? AND browser_hash = ?",
            (_hash(code), _hash(browser)),
        ).fetchone()
        if row is None:
            raise OAuthFlowError(APP_MESSAGE_OAUTH_EXCHANGE_EXPIRED)
        conn.execute("DELETE FROM auth_oauth_codes WHERE code_hash = ?", (_hash(code),))
        owner = conn.execute(
            "SELECT username, auth_revision FROM auth_owner WHERE id = 1"
        ).fetchone()
        bound = conn.execute(
            "SELECT subject, revision FROM auth_identities WHERE provider = ?",
            (row["provider"],),
        ).fetchone()
        if owner is None or not compare_digest(
            owner["auth_revision"], row["owner_revision"]
        ):
            error = APP_MESSAGE_OAUTH_OWNER_CHANGED
        elif row["intent"] == "login" and (
            bound is None or bound["revision"] != row["identity_revision"]
        ):
            error = APP_MESSAGE_OAUTH_NOT_BOUND
        elif row["intent"] == "bind" and bound is not None:
            error = APP_MESSAGE_OAUTH_ALREADY_BOUND
        else:
            if row["intent"] == "bind":
                conn.execute(
                    """
                    INSERT INTO auth_identities (
                        provider, subject, label, revision, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        row["provider"],
                        row["subject"],
                        row["label"],
                        secrets.token_urlsafe(32),
                        datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    ),
                )
            result = (
                cast(OAuthProvider, row["provider"]),
                cast(OAuthIntent, row["intent"]),
                OwnerAccount(owner["username"], owner["auth_revision"]),
            )
    if error is not None:
        raise OAuthFlowError(error)
    assert result is not None
    return result


def delete_identity(provider: OAuthProvider) -> None:
    with closing(connect_auth_database()) as conn, conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM auth_identities WHERE provider = ?", (provider,))
        conn.execute("DELETE FROM auth_oauth_codes WHERE provider = ?", (provider,))
