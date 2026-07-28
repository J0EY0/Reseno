from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.agent_locales import AgentLocale


class AgentResponseLanguage(StrEnum):
    FOLLOW = "follow"
    ZH = "zh"
    EN = "en"


class AgentBehaviorMode(StrEnum):
    BALANCED = "balanced"
    STRICT = "strict"
    AGGRESSIVE = "aggressive"


class AgentConfirmationMode(StrEnum):
    ALWAYS = "always"
    SUGGEST_ONLY = "suggestOnly"


class AgentSettings(BaseModel):
    """Persisted Agent preferences owned and normalized by the backend."""

    model_config = ConfigDict(
        populate_by_name=True,
        extra="ignore",
        frozen=True,
    )

    default_model_id: str = Field(default="", alias="defaultModelId")
    response_language: AgentResponseLanguage = Field(
        default=AgentResponseLanguage.FOLLOW,
        alias="responseLanguage",
    )
    behavior_mode: AgentBehaviorMode = Field(
        default=AgentBehaviorMode.BALANCED,
        alias="behaviorMode",
    )
    confirmation_mode: AgentConfirmationMode = Field(
        default=AgentConfirmationMode.ALWAYS,
        alias="confirmationMode",
    )


class AgentExecutionProfile(BaseModel):
    """Immutable preferences captured at the start of one Agent turn."""

    model_config = ConfigDict(frozen=True)

    response_locale: AgentLocale
    behavior_mode: AgentBehaviorMode
    confirmation_mode: AgentConfirmationMode


def _supported_enum[SettingEnum: StrEnum](
    enum_type: type[SettingEnum],
    value: Any,
    default: SettingEnum,
) -> SettingEnum:
    if not isinstance(value, str):
        return default
    try:
        return enum_type(value)
    except ValueError:
        return default


def normalize_agent_settings(value: Any) -> AgentSettings:
    """Normalize fields independently so one stale value cannot discard the rest."""

    if not isinstance(value, dict):
        return AgentSettings()

    default_model_id = value.get("defaultModelId")
    return AgentSettings(
        defaultModelId=default_model_id if isinstance(default_model_id, str) else "",
        responseLanguage=_supported_enum(
            AgentResponseLanguage,
            value.get("responseLanguage"),
            AgentResponseLanguage.FOLLOW,
        ),
        behaviorMode=_supported_enum(
            AgentBehaviorMode,
            value.get("behaviorMode"),
            AgentBehaviorMode.BALANCED,
        ),
        confirmationMode=_supported_enum(
            AgentConfirmationMode,
            value.get("confirmationMode"),
            AgentConfirmationMode.ALWAYS,
        ),
    )
