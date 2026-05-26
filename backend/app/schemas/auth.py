from pydantic import BaseModel, ConfigDict, Field


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
    """Password change result returned after .env is updated."""

    username: str
    updated: bool = True
