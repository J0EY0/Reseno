import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.schemas.agent import AgentChatRequest

from .attachments import AgentAttachmentError, current_request_attachments
from .intent_patterns import matches_intent_pattern
from .materials import extract_resume_materials
from .tools.registry import (
    ALL_KNOWN_TOOL_NAMES,
    CONTROL_TOOL_NAMES,
    DRAFT_WRITE_TOOL_NAMES,
    LOCAL_READ_TOOL_NAMES,
    WEB_FETCH_TOOL_NAMES,
    WEB_SEARCH_TOOL_NAMES,
    WRITE_TOOL_NAMES,
)


class AgentTaskIntent(StrEnum):
    ANSWER_ADVICE = "answer_advice"
    EXPLAIN_DRAFT = "explain_draft"
    RESEARCH_ROLE = "research_role"
    DIAGNOSE_JD_GAP = "diagnose_jd_gap"
    EDIT_RESUME = "edit_resume"
    REWRITE_DRAFT = "rewrite_draft"
    ANALYZE_RESUME = "analyze_resume"
    MATCH_JD = "match_jd"


class AgentCapabilityMode(StrEnum):
    READ_ONLY = "read_only"
    CAN_DRAFT = "can_draft"
    CAN_REWRITE_DRAFT = "can_rewrite_draft"
    CLARIFY_ONLY = "clarify_only"


@dataclass(frozen=True)
class AgentCapabilityPolicy:
    intent: AgentTaskIntent
    mode: AgentCapabilityMode
    allowed_tools: frozenset[str]
    reason: str = ""


def capability_policy_for_request(
    request: AgentChatRequest,
) -> AgentCapabilityPolicy:
    """Return the tool capability boundary for this agent turn."""

    intent = infer_agent_task_intent(request)
    prompt = _current_prompt(request).lower()
    if _confirmation_mode(request) == "suggestOnly":
        return AgentCapabilityPolicy(
            intent=intent,
            mode=AgentCapabilityMode.READ_ONLY,
            allowed_tools=_read_tools_for_request(request, intent),
            reason="suggest_only",
        )

    if intent == AgentTaskIntent.EXPLAIN_DRAFT:
        if _has_pending_draft(request):
            return AgentCapabilityPolicy(
                intent=intent,
                mode=AgentCapabilityMode.READ_ONLY,
                allowed_tools=frozenset({"draft_diff_summary"}) | CONTROL_TOOL_NAMES,
            )
        return AgentCapabilityPolicy(
            intent=intent,
            mode=AgentCapabilityMode.CLARIFY_ONLY,
            allowed_tools=CONTROL_TOOL_NAMES,
            reason="pending_draft",
        )

    if intent == AgentTaskIntent.REWRITE_DRAFT:
        if _has_pending_draft(request):
            return AgentCapabilityPolicy(
                intent=intent,
                mode=AgentCapabilityMode.CAN_REWRITE_DRAFT,
                allowed_tools=_read_tools_for_request(request, intent)
                | frozenset({"draft_rewrite", "edit_execute"}),
            )
        return AgentCapabilityPolicy(
            intent=intent,
            mode=AgentCapabilityMode.CLARIFY_ONLY,
            allowed_tools=CONTROL_TOOL_NAMES,
            reason="pending_draft",
        )

    if intent in {
        AgentTaskIntent.ANSWER_ADVICE,
        AgentTaskIntent.ANALYZE_RESUME,
        AgentTaskIntent.RESEARCH_ROLE,
        AgentTaskIntent.DIAGNOSE_JD_GAP,
    }:
        return AgentCapabilityPolicy(
            intent=intent,
            mode=AgentCapabilityMode.READ_ONLY,
            allowed_tools=_read_tools_for_request(request, intent),
        )

    if intent == AgentTaskIntent.EDIT_RESUME and _needs_material_followup(
        request,
        prompt,
    ):
        return AgentCapabilityPolicy(
            intent=intent,
            mode=AgentCapabilityMode.CLARIFY_ONLY,
            allowed_tools=CONTROL_TOOL_NAMES,
            reason="source_material",
        )

    return AgentCapabilityPolicy(
        intent=intent,
        mode=AgentCapabilityMode.CAN_DRAFT,
        allowed_tools=_read_tools_for_request(request, intent) | DRAFT_WRITE_TOOL_NAMES,
    )


def infer_agent_task_intent(request: AgentChatRequest) -> AgentTaskIntent:
    """Infer a coarse backend intent from the current turn."""

    prompt = _current_prompt(request).lower()
    if not prompt:
        return AgentTaskIntent.ANSWER_ADVICE

    if _matches_intent(prompt, "explain_draft"):
        return AgentTaskIntent.EXPLAIN_DRAFT

    if _has_pending_draft(request) and (
        _matches_intent(prompt, "draft_reference")
        or _matches_intent(prompt, "draft_revision")
    ):
        return AgentTaskIntent.REWRITE_DRAFT

    if _matches_intent(prompt, "previous_draft_reference") or (
        _matches_intent(prompt, "draft_reference")
        and _matches_intent(prompt, "draft_revision")
    ):
        return AgentTaskIntent.REWRITE_DRAFT

    if (
        _matches_intent(prompt, "jd_gap_diagnosis")
        and _has_target_context(request, prompt)
        and not _matches_intent(prompt, "edit_resume")
    ):
        return AgentTaskIntent.DIAGNOSE_JD_GAP

    if _matches_intent(prompt, "role_research") and not _matches_intent(
        prompt,
        "edit_resume",
    ):
        return AgentTaskIntent.RESEARCH_ROLE

    if _matches_intent(prompt, "job_request"):
        return AgentTaskIntent.MATCH_JD

    if _matches_intent(prompt, "analyze_resume"):
        return AgentTaskIntent.ANALYZE_RESUME

    if _matches_intent(prompt, "edit_resume"):
        return AgentTaskIntent.EDIT_RESUME

    return AgentTaskIntent.ANSWER_ADVICE


def tool_block_reason(policy: AgentCapabilityPolicy, tool_name: str) -> str:
    """Return a localization key for a blocked known tool, or empty string."""

    if tool_name not in ALL_KNOWN_TOOL_NAMES or tool_name in policy.allowed_tools:
        return ""

    if policy.reason == "suggest_only" and tool_name in WRITE_TOOL_NAMES:
        return "error.tool_blocked_suggest_only"

    if policy.reason == "pending_draft":
        return "error.tool_requires_pending_draft"

    if policy.mode == AgentCapabilityMode.READ_ONLY and tool_name in WRITE_TOOL_NAMES:
        return "error.tool_blocked_read_only"

    if policy.mode == AgentCapabilityMode.CLARIFY_ONLY:
        return "error.tool_blocked_clarify_only"

    return "error.tool_blocked_by_policy"


def has_explicit_delete_intent(prompt: str) -> bool:
    return _matches_intent(prompt, "delete_intent")


def has_explicit_reorder_intent(prompt: str) -> bool:
    return _matches_intent(prompt, "reorder_intent")


def has_explicit_merge_intent(prompt: str) -> bool:
    return _matches_intent(prompt, "merge_intent")


def _read_tools_for_request(
    request: AgentChatRequest,
    intent: AgentTaskIntent,
) -> frozenset[str]:
    tools = set(LOCAL_READ_TOOL_NAMES | CONTROL_TOOL_NAMES)
    if intent in {AgentTaskIntent.MATCH_JD, AgentTaskIntent.DIAGNOSE_JD_GAP}:
        tools.update(WEB_FETCH_TOOL_NAMES)
        tools.update(WEB_SEARCH_TOOL_NAMES)
    elif intent == AgentTaskIntent.RESEARCH_ROLE:
        tools.update(WEB_SEARCH_TOOL_NAMES)
        if _prompt_has_url(request):
            tools.update(WEB_FETCH_TOOL_NAMES)
    elif _prompt_has_url(request):
        tools.update(WEB_FETCH_TOOL_NAMES)
    return frozenset(tools)


def _current_prompt(request: AgentChatRequest) -> str:
    if request.message and request.message.text.strip():
        return request.message.text.strip()
    if request.prompt.strip():
        return request.prompt.strip()
    for message in reversed(request.messages or request.conversation):
        if message.role == "user" and message.text.strip():
            return message.text.strip()
    return ""


def _has_pending_draft(request: AgentChatRequest) -> bool:
    draft = request.draft_state
    return bool(draft and draft.status == "pending" and draft.resume)


def _prompt_has_url(request: AgentChatRequest) -> bool:
    return _matches(_current_prompt(request), r"https?://")


def _has_target_context(request: AgentChatRequest, prompt: str) -> bool:
    return bool(
        request.job_brief.strip()
        or _prompt_has_url(request)
        or _matches_intent(prompt, "job_request")
        or _matches_intent(prompt, "role_research"),
    )


def _needs_material_followup(request: AgentChatRequest, prompt: str) -> bool:
    return (
        _matches_intent(prompt, "material_generation_request")
        and not _has_resume_item_evidence(request)
        and not _has_user_resume_material(request)
    )


def _has_user_resume_material(request: AgentChatRequest) -> bool:
    try:
        materials = extract_resume_materials(
            session_id=(request.resume_id or "").strip(),
            prompt=_current_prompt(request),
            job_brief="",
            files=current_request_attachments(request),
            focus="resume_facts",
            max_items=1,
        )
    except AgentAttachmentError:
        # Message construction owns the user-visible attachment error. Policy
        # inference must not turn a storage failure into an unrelated 500.
        return False
    usage = materials.get("usage")
    return isinstance(usage, dict) and usage.get("canSupportResumeFacts") is True


def _has_resume_item_evidence(request: AgentChatRequest) -> bool:
    resume = _policy_resume(request)
    sections = resume.get("sections") if isinstance(resume, dict) else None
    if not isinstance(sections, list):
        return False

    return any(_section_has_item_evidence(section) for section in sections)


def _section_has_item_evidence(section: object) -> bool:
    if not isinstance(section, dict):
        return False
    items = section.get("items")
    if not isinstance(items, list):
        return False
    return any(_item_has_content(item) for item in items)


def _item_has_content(item: object) -> bool:
    if not isinstance(item, dict):
        return False
    for key in ("title", "subtitle", "meta", "period", "description"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return True
    highlights = item.get("highlights")
    return isinstance(highlights, list) and any(
        isinstance(value, str) and value.strip() for value in highlights
    )


def _policy_resume(request: AgentChatRequest) -> dict[str, Any]:
    draft = request.draft_state
    if draft and draft.status == "pending" and draft.resume:
        return draft.resume
    return request.resume


def _confirmation_mode(request: AgentChatRequest) -> str:
    value = request.settings.get("confirmationMode")
    return value if value in {"always", "suggestOnly"} else "always"


def _matches_intent(prompt: str, pattern_name: str) -> bool:
    return matches_intent_pattern(prompt, pattern_name)


def _matches(value: str, pattern: str) -> bool:
    return bool(re.search(pattern, value, flags=re.IGNORECASE))
