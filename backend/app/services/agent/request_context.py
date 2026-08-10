from typing import Any

from app.schemas.agent import AgentChatRequest


def active_resume(request: AgentChatRequest) -> dict[str, Any]:
    """Return the one resume snapshot every part of this turn must use."""

    draft_state = request.draft_state
    if draft_state and draft_state.status == "pending" and draft_state.resume:
        return draft_state.resume
    return request.resume
