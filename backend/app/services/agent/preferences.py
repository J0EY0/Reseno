from app.agent_locales import AgentLocale
from app.schemas.agent import AgentChatRequest
from app.schemas.agent_settings import (
    AgentExecutionProfile,
    AgentResponseLanguage,
    AgentSettings,
)

_RESPONSE_LOCALES: dict[AgentResponseLanguage, AgentLocale] = {
    AgentResponseLanguage.ZH: "zh",
    AgentResponseLanguage.EN: "en",
}


def resolve_agent_execution_profile(
    settings: AgentSettings,
    request_locale: AgentLocale,
) -> AgentExecutionProfile:
    """Resolve persisted preferences into the effective settings for one turn."""

    response_locale = _RESPONSE_LOCALES.get(
        settings.response_language,
        request_locale,
    )
    return AgentExecutionProfile(
        response_locale=response_locale,
        behavior_mode=settings.behavior_mode,
        confirmation_mode=settings.confirmation_mode,
    )


def prepare_agent_request(
    request: AgentChatRequest,
    settings: AgentSettings,
) -> AgentChatRequest:
    """Capture backend-owned preferences before an Agent run starts.

    The returned request carries an immutable execution profile. Later settings
    changes are intentionally observed only when the next request is prepared.
    """

    profile = resolve_agent_execution_profile(settings, request.locale)
    return request.model_copy(
        update={
            "locale": profile.response_locale,
            "execution_profile": profile,
        },
    )


def execution_profile_for_request(
    request: AgentChatRequest,
) -> AgentExecutionProfile:
    """Return the frozen profile, with defaults for direct internal callers."""

    if request.execution_profile is not None:
        return request.execution_profile
    return resolve_agent_execution_profile(AgentSettings(), request.locale)
