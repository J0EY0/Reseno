from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthSetupStatusResponse(BaseModel):
    """Owner setup and GitHub sign-in availability."""

    model_config = ConfigDict(populate_by_name=True)

    setup_required: bool = Field(alias="setupRequired")
    github_login_available: bool = Field(alias="githubLoginAvailable")


class AuthSetupRequest(BaseModel):
    """Owner credentials submitted during one-time setup."""

    username: str
    password: str
    confirm_password: str = Field(alias="confirmPassword")


class AuthLoginRequest(BaseModel):
    """Credentials submitted to the login endpoint."""

    username: str
    password: str


class AuthLoginResponse(BaseModel):
    """Access token details returned after successful login."""

    model_config = ConfigDict(populate_by_name=True)

    username: str
    access_token: str = Field(alias="accessToken")
    expires_at: str = Field(alias="expiresAt")
    token_type: str = Field(default="bearer", alias="tokenType")


class AuthPasswordUpdateRequest(BaseModel):
    """Password change request submitted from settings."""

    current_password: str = Field(alias="currentPassword")
    new_password: str = Field(alias="newPassword")
    confirm_password: str = Field(alias="confirmPassword")


class AuthPasswordUpdateResponse(BaseModel):
    """Password change result returned after the stored hash is updated."""

    username: str
    updated: bool = True


class OAuthProviderConfiguration(BaseModel):
    provider: Literal["github"]
    configured: bool


class OAuthIdentityResponse(BaseModel):
    provider: Literal["github"]
    label: str
    created_at: str = Field(alias="createdAt")


class OAuthIdentitiesResponse(BaseModel):
    identities: list[OAuthIdentityResponse]
    providers: list[OAuthProviderConfiguration]


class OAuthStartResponse(BaseModel):
    authorization_url: str = Field(alias="authorizationUrl")


class OAuthCompleteRequest(BaseModel):
    code: str = Field(min_length=1, max_length=128)


class OAuthCompleteResponse(BaseModel):
    provider: Literal["github"]
    intent: Literal["login", "bind"]
    auth: AuthLoginResponse | None


class OAuthDeleteResponse(BaseModel):
    deleted: bool = True


class OAuthSetupRequest(BaseModel):
    public_base_url: str = Field(alias="publicBaseUrl", min_length=1, max_length=2048)


class OAuthSetupResponse(BaseModel):
    registration_url: str = Field(alias="registrationUrl")
    manifest: dict[str, object]
