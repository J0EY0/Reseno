from pydantic import BaseModel, ConfigDict, Field


class ModelConfigUpsertRequest(BaseModel):
    """Model config data accepted from the frontend settings UI."""

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(alias="id")
    provider: str
    nickname: str = ""
    api_key: str | None = Field(default=None, alias="apiKey")
    model: str
    api_url: str = Field(alias="apiUrl")
    temperature: float = 0.7
    top_p: float = Field(default=1.0, alias="topP")
    max_tokens: int | None = Field(default=None, alias="maxTokens")
    system_prompt: str = Field(default="", alias="systemPrompt")
    is_default: bool = Field(default=False, alias="isDefault")


class ModelConfigResponse(BaseModel):
    """Model config data returned without plaintext API keys."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    provider: str
    nickname: str
    api_key_preview: str = Field(alias="apiKeyPreview")
    model: str
    api_url: str = Field(alias="apiUrl")
    temperature: float
    top_p: float = Field(alias="topP")
    max_tokens: int | None = Field(alias="maxTokens")
    system_prompt: str = Field(alias="systemPrompt")


class ModelConfigsResponse(BaseModel):
    """Collection response for enabled model configs."""

    configs: list[ModelConfigResponse]
