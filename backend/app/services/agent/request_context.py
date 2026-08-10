from typing import Any

from app.schemas.agent import AgentChatRequest, AgentResumeEditSuggestion


def active_resume(request: AgentChatRequest) -> dict[str, Any]:
    """Return the candidate snapshot the model and tools edit this turn."""

    draft_state = request.draft_state
    if draft_state and draft_state.status == "pending" and draft_state.resume:
        return draft_state.resume
    return request.resume


def _pending_transaction_response(
    request: AgentChatRequest,
) -> dict[str, Any] | None:
    draft_state = request.draft_state
    if not draft_state or draft_state.status != "pending":
        return None

    source_message_id = draft_state.source_message_id
    if not source_message_id:
        return None

    for message in reversed(request.messages):
        if message.id != source_message_id or message.role != "assistant":
            continue
        response = message.response
        draft = response.get("draft") if response else None
        if isinstance(draft, dict) and draft.get("status") == "pending":
            return response
        return None

    return None


def transaction_base_resume(request: AgentChatRequest) -> dict[str, Any]:
    """Return the immutable base for the active draft transaction."""

    response = _pending_transaction_response(request)
    draft = response.get("draft") if response else None
    if isinstance(draft, dict):
        base_resume = draft.get("baseResume")
        if isinstance(base_resume, dict):
            return base_resume

    return request.resume


def accumulated_transaction_edits(
    request: AgentChatRequest,
    edits: list[AgentResumeEditSuggestion],
) -> list[AgentResumeEditSuggestion]:
    """Add the pending transaction's edits exactly once to a new batch."""

    if not edits:
        return []

    response = _pending_transaction_response(request)
    raw_prior_edits = response.get("edits") if response else None
    if not isinstance(raw_prior_edits, list) or not raw_prior_edits:
        return list(edits)

    prior_edits = [
        AgentResumeEditSuggestion.model_validate(edit) for edit in raw_prior_edits
    ]
    if edits[: len(prior_edits)] == prior_edits:
        return list(edits)
    return [*prior_edits, *edits]
