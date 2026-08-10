from pydantic import BaseModel, ConfigDict, Field


class AuthSetupStatusResponse(BaseModel):
    """Whether the instance still needs its owner account."""

    model_config = ConfigDict(populate_by_name=True)

    setup_required: bool = Field(alias="setupRequired")


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
