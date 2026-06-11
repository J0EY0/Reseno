import json
from typing import Any, Literal

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentResumeEditSuggestion,
)
from app.services.llm_client import AgentLlmConfig

from ..executor import (
    _agent_file_context,
    _conversation_depth,
    _current_prompt,
)
from ..prompts import (
    EDIT_OPERATION_GUIDES,
    FINAL_RESPONSE_PROMPTS,
    STREAMING_FINAL_RESPONSE_PROMPTS,
    SYSTEM_PROMPTS,
)

AgentMessageMode = Literal["tools", "final", "streaming_final"]


def build_agent_messages(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    mode: AgentMessageMode,
    draft: AgentChatMessage | None = None,
) -> list[dict[str, Any]]:
    """Build model messages for tool selection or final responses."""

    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": "\n\n".join(_system_parts(request, config, mode)),
        },
    ]

    messages.append(
        {
            "role": "user",
            "content": json.dumps(
                _agent_payload(request, draft=draft),
                ensure_ascii=False,
            ),
        },
    )
    return messages


def _system_parts(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    mode: AgentMessageMode,
) -> list[str]:
    parts = [SYSTEM_PROMPTS[request.locale]]

    if mode == "tools":
        parts.append(EDIT_OPERATION_GUIDES[request.locale])
    elif mode == "final":
        parts.append(FINAL_RESPONSE_PROMPTS[request.locale])
    elif mode == "streaming_final":
        parts.append(STREAMING_FINAL_RESPONSE_PROMPTS[request.locale])

    if config.system_prompt.strip():
        parts.append(config.system_prompt.strip())

    return parts


def _agent_payload(
    request: AgentChatRequest,
    *,
    draft: AgentChatMessage | None = None,
) -> dict[str, Any]:
    payload = {
        "responseLanguage": _locale_name(request),
        "userPrompt": _current_prompt(request),
        "jobBrief": request.job_brief,
        "files": _agent_file_context(request.files),
        "keywordMatch": request.keyword_match,
        "resume": request.resume,
        "conversationDepth": _conversation_depth(request),
        "conversation": _conversation_messages(request),
    }

    if draft is not None:
        payload.update(
            {
                "citationSources": [
                    source.model_dump(mode="json", by_alias=True)
                    for source in draft.sources
                ],
                "draftStatusText": draft.text,
                "draftEditCount": len(draft.edits),
                "draftEdits": _visible_edit_summaries(draft.edits),
            },
        )

    return payload


def _conversation_messages(request: AgentChatRequest) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    conversation = request.messages or request.conversation
    for item in conversation[-8:]:
        text = item.text.strip()
        if text:
            messages.append({"role": item.role, "content": text})

    prompt = _current_prompt(request)
    if prompt and not any(
        message["role"] == "user" and message["content"] == prompt
        for message in messages
    ):
        messages.append({"role": "user", "content": prompt})

    return messages


def _visible_edit_summaries(
    edits: list[AgentResumeEditSuggestion],
) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for edit in edits:
        summary: dict[str, str] = {}
        if edit.title.strip():
            summary["title"] = edit.title.strip()
        if edit.reason.strip():
            summary["reason"] = edit.reason.strip()
        if summary:
            summaries.append(summary)

    return summaries


def _locale_name(request: AgentChatRequest) -> str:
    return "Chinese" if request.locale == "zh" else "English"
