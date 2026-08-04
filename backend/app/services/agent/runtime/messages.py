import json
from dataclasses import dataclass
from typing import Any, Literal

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentConversationItem,
    AgentResumeEditSuggestion,
)
from app.services.llm import (
    AgentLlmConfig,
    LlmRequestError,
    supports_native_attachment,
)
from app.services.llm.common import request_max_output_tokens
from app.services.resume_document_contract import ITEM_STRING_FIELDS_BY_KIND

from ..attachments import (
    AgentAttachmentError,
    attachment_content_part,
    current_request_attachments,
    load_agent_attachment,
)
from ..executor import (
    _active_resume,
    _agent_file_context,
    _conversation_depth,
    _current_prompt,
)
from ..localization import agent_text
from ..policy import capability_policy_for_request
from ..preferences import (
    execution_profile_for_request,
    execution_profile_prompt,
)
from ..privacy import resume_hidden_terms, sanitize_agent_resume, sanitize_agent_value
from ..prompts import (
    CORE_POLICY_PROMPT,
    EDIT_OPERATION_GUIDE,
    FINAL_RESPONSE_PROMPT,
    STREAMING_FINAL_RESPONSE_PROMPT,
    SYSTEM_PROMPT,
)
from ..tools.registry import agent_tool_schemas_for_names

AgentMessageMode = Literal["tools", "final", "streaming_final"]
CONTEXT_COMPRESSION_RATIO = 0.85
CONTEXT_SAFETY_MARGIN_RATIO = 0.01
MIN_CONTEXT_SAFETY_MARGIN_TOKENS = 256
DEFAULT_ATTACHMENT_CONTEXT_TOKEN_BUDGET = 32_000
RECENT_EXACT_MESSAGE_COUNT = 4
ROLLING_MEMORY_KEYS = (
    "userGoals",
    "factsAndMaterials",
    "constraints",
    "acceptedDecisions",
    "rejectedDecisions",
    "pendingQuestions",
    "sourceReferences",
)
ROLLING_MEMORY_TRIM_ORDER = (
    "factsAndMaterials",
    "sourceReferences",
    "pendingQuestions",
    "acceptedDecisions",
    "rejectedDecisions",
    "constraints",
    "userGoals",
)
GOAL_PREFIXES = (
    "目标",
    "目的",
    "申请",
    "希望",
    "想要",
    "goal",
    "objective",
    "target",
    "apply",
)
FACT_PREFIXES = (
    "材料",
    "事实",
    "背景",
    "经历",
    "证据",
    "material",
    "fact",
    "evidence",
    "experience",
)
CONSTRAINT_PREFIXES = (
    "约束",
    "要求",
    "必须",
    "只能",
    "不要",
    "不得",
    "constraint",
    "requirement",
    "must",
    "only",
    "do not",
    "don't",
)
ACCEPTED_DECISION_PREFIXES = (
    "已确认",
    "确认保留",
    "同意",
    "接受",
    "accepted",
    "approved",
    "confirmed",
)
REJECTED_DECISION_PREFIXES = (
    "已拒绝",
    "拒绝",
    "不接受",
    "rejected",
    "declined",
)
PENDING_QUESTION_PREFIXES = (
    "待确认",
    "需要确认",
    "待补充",
    "pending",
    "open question",
    "needs confirmation",
)


@dataclass(frozen=True)
class _ContextBudget:
    """One shared context budget for compression and final validation."""

    input_tokens: int
    trigger_tokens: int
    output_reserve_tokens: int
    tool_schema_tokens: int
    safety_margin_tokens: int


def build_agent_messages(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    mode: AgentMessageMode,
    draft: AgentChatMessage | None = None,
    force_attachment_text: bool = False,
) -> list[dict[str, Any]]:
    """Build model messages with current-request attachments only.

    Original bytes are included only when the selected adapter explicitly
    supports their media type. Otherwise the same original is lazily extracted
    into complete text; extraction never truncates silently.
    """

    profile = execution_profile_for_request(request)
    system_content = "\n\n".join(
        [
            *_system_parts(mode),
            execution_profile_prompt(profile),
        ],
    )
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": system_content,
        },
    ]

    tool_schema_tokens = _tool_schema_token_reserve(request, config, mode=mode)
    context_files, binary_parts = _current_attachment_payload(
        request,
        config,
        force_attachment_text=force_attachment_text,
        tool_schema_tokens=tool_schema_tokens,
    )
    payload_text = json.dumps(
        _agent_payload(
            request,
            config=config,
            draft=draft,
            system_content=system_content,
            context_files=context_files,
            tool_schema_tokens=tool_schema_tokens,
        ),
        ensure_ascii=False,
    )
    # Keep one provider-neutral binary shape inside the Agent runtime. Adapters
    # own the final wire format and never infer support from provider aliases.
    user_content: str | list[dict[str, str]] = payload_text
    if binary_parts:
        user_content = [{"type": "text", "text": payload_text}, *binary_parts]

    messages.append({"role": "user", "content": user_content})
    return messages


def has_native_current_request_attachments(
    request: AgentChatRequest,
    config: AgentLlmConfig,
) -> bool:
    """Return whether this request would send at least one original file."""

    files = _safe_current_request_attachments(request)
    if not files:
        return False
    session_id = _attachment_session_id(request)
    for file in files:
        attachment = load_agent_attachment(session_id, file)
        if (
            attachment is not None
            and attachment.kind != "image"
            and supports_native_attachment(config, attachment.media_type)
        ):
            return True
    return False


def is_native_attachment_unsupported(error: LlmRequestError) -> bool:
    """Classify only explicit client-side native attachment rejection.

    A fallback is intentionally excluded for auth, throttling, timeouts, and
    provider/server failures. Those errors need to remain visible as-is.
    """

    if error.status_code not in {400, 415}:
        return False

    message = str(error).lower()
    subject_markers = (
        "attachment",
        "document",
        "file_data",
        "input_file",
        "application/pdf",
        "media type",
        "mime",
        "pdf",
    )
    rejection_markers = (
        "unsupported",
        "not supported",
        "not allowed",
        "invalid content",
        "invalid media",
        "invalid type",
        "unknown type",
        "unrecognized",
    )
    return any(marker in message for marker in subject_markers) and any(
        marker in message for marker in rejection_markers
    )


def _current_attachment_payload(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    force_attachment_text: bool,
    tool_schema_tokens: int,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    files = _safe_current_request_attachments(request)
    if not files:
        return [], []

    session_id = _attachment_session_id(request)
    hidden_terms = resume_hidden_terms(_active_resume(request))
    text_files: list[dict[str, Any]] = []
    binary_parts: list[dict[str, str]] = []

    try:
        for file in files:
            attachment = load_agent_attachment(session_id, file)
            if attachment is None:
                raise AgentAttachmentError(
                    "The attachment is no longer available.",
                )

            if attachment.kind == "image":
                if not config.supports_image:
                    raise AgentAttachmentError(
                        "The selected model does not support image input.",
                    )
                binary_parts.append(attachment_content_part(session_id, file))
                continue

            if not force_attachment_text and supports_native_attachment(
                config, attachment.media_type
            ):
                binary_parts.append(attachment_content_part(session_id, file))
                continue

            text_files.append(file)

        text_context = _agent_file_context(
            session_id,
            text_files,
            hidden_terms=hidden_terms,
        )
        return (
            _fit_attachment_context(
                text_context,
                token_budget=_attachment_context_token_budget(
                    request,
                    config,
                    tool_schema_tokens=tool_schema_tokens,
                ),
            ),
            binary_parts,
        )
    except AgentAttachmentError as exc:
        raise LlmRequestError(str(exc)) from exc


def _safe_current_request_attachments(
    request: AgentChatRequest,
) -> list[dict[str, Any]]:
    try:
        return current_request_attachments(request)
    except AgentAttachmentError as exc:
        raise LlmRequestError(str(exc)) from exc


def _attachment_session_id(request: AgentChatRequest) -> str:
    session_id = (request.resume_id or "").strip()
    if not session_id:
        raise LlmRequestError(
            "Attachments require an active Agent resume session.",
        )
    return session_id


def _system_parts(
    mode: AgentMessageMode,
) -> list[str]:
    if mode == "tools":
        return [SYSTEM_PROMPT, EDIT_OPERATION_GUIDE]
    if mode == "final":
        return [CORE_POLICY_PROMPT, FINAL_RESPONSE_PROMPT]
    return [CORE_POLICY_PROMPT, STREAMING_FINAL_RESPONSE_PROMPT]


def _agent_payload(
    request: AgentChatRequest,
    *,
    config: AgentLlmConfig,
    draft: AgentChatMessage | None = None,
    system_content: str,
    context_files: list[dict[str, Any]],
    tool_schema_tokens: int,
) -> dict[str, Any]:
    active_resume = _active_resume(request)
    hidden_terms = resume_hidden_terms(active_resume)
    payload = {
        "responseLanguage": _locale_name(request),
        "userPrompt": _current_prompt(request),
        "jobBrief": request.job_brief,
        "files": context_files,
        "keywordMatch": request.keyword_match,
        "resume": sanitize_agent_resume(active_resume, hidden_terms=hidden_terms),
        "conversationDepth": _conversation_depth(request),
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
                "toolContext": _visible_tool_context(draft.tools),
            },
        )

    conversation_payload = _conversation_payload(
        request,
        config=config,
        base_payload=payload,
        system_content=system_content,
        tool_schema_tokens=tool_schema_tokens,
    )
    payload["conversation"] = conversation_payload["conversation"]
    payload["conversationContext"] = conversation_payload["conversationContext"]

    sanitized_payload = sanitize_agent_value(payload, hidden_terms=hidden_terms)
    return sanitized_payload if isinstance(sanitized_payload, dict) else {}


def _conversation_payload(
    request: AgentChatRequest,
    *,
    config: AgentLlmConfig,
    base_payload: dict[str, Any],
    system_content: str,
    tool_schema_tokens: int,
) -> dict[str, Any]:
    conversation = _conversation_with_current_prompt(request)
    conversation_messages = [
        item for item in conversation if _conversation_item_text(item)
    ]
    exact_messages = _conversation_entries(conversation_messages)
    context_budget = _context_budget(
        request,
        config,
        tool_schema_tokens=tool_schema_tokens,
    )
    budget_tokens = context_budget.input_tokens if context_budget else None
    compression_trigger_tokens = (
        context_budget.trigger_tokens if context_budget else None
    )
    state_token_budget = _state_token_budget(budget_tokens)
    latest_draft = _latest_draft_state(
        conversation_messages,
        token_budget=state_token_budget,
    )
    current_draft = _current_draft_state(
        request,
        token_budget=state_token_budget,
    )
    last_assistant_state = _last_assistant_state(
        conversation_messages,
        token_budget=state_token_budget,
    )
    base_tokens = _estimated_tokens(system_content) + _estimated_json_tokens(
        base_payload,
    )
    context = _conversation_context(
        request,
        total_messages=len(exact_messages),
        exact_messages=exact_messages,
        compressed_messages=[],
        current_draft=current_draft,
        latest_draft=latest_draft,
        last_assistant_state=last_assistant_state,
        context_budget=context_budget,
        estimated_tokens=base_tokens,
        compressed=False,
    )
    estimated_tokens = base_tokens + _estimated_json_tokens(
        {
            "conversation": exact_messages,
            "conversationContext": context,
        },
    )

    if (
        budget_tokens is None
        or compression_trigger_tokens is None
        or estimated_tokens <= compression_trigger_tokens
    ):
        context["compression"]["estimatedInputTokens"] = estimated_tokens
        return {
            "conversation": exact_messages,
            "conversationContext": context,
        }

    # The early return above narrows both scalar limits, but type checkers do
    # not infer that they originated from the same optional budget object.
    assert context_budget is not None
    return _compressed_conversation_payload(
        request,
        base_tokens=base_tokens,
        budget_tokens=budget_tokens,
        context_budget=context_budget,
        exact_messages=exact_messages,
        latest_draft=latest_draft,
        current_draft=current_draft,
        last_assistant_state=last_assistant_state,
        source_conversation=conversation_messages,
    )


def _compressed_conversation_payload(
    request: AgentChatRequest,
    *,
    base_tokens: int,
    budget_tokens: int,
    context_budget: _ContextBudget,
    exact_messages: list[dict[str, str]],
    latest_draft: dict[str, Any] | None,
    current_draft: dict[str, Any] | None,
    last_assistant_state: dict[str, Any] | None,
    source_conversation: list[Any],
) -> dict[str, Any]:
    exact_count = min(RECENT_EXACT_MESSAGE_COUNT, len(exact_messages))
    exact_remaining = exact_messages[-exact_count:] if exact_count else []
    older_conversation = (
        source_conversation[:-exact_count] if exact_count else list(source_conversation)
    )
    rolling_memory, represented_message_count = _build_rolling_memory(
        older_conversation,
    )
    context = _conversation_context(
        request,
        total_messages=len(exact_messages),
        exact_messages=exact_remaining,
        compressed_messages=[],
        compressed_message_count=represented_message_count,
        rolling_memory=rolling_memory,
        current_draft=current_draft,
        latest_draft=latest_draft,
        last_assistant_state=last_assistant_state,
        context_budget=context_budget,
        estimated_tokens=base_tokens,
        compressed=True,
    )
    estimated_tokens = base_tokens + _estimated_json_tokens(
        {
            "conversation": exact_remaining,
            "conversationContext": context,
        },
    )

    # Memory entries are semantic units. When space is tight, remove only
    # duplicate/older units from a category; never keep a misleading text
    # prefix. One value per populated category is protected.
    while estimated_tokens > budget_tokens and _drop_oldest_redundant_memory_item(
        rolling_memory
    ):
        context = _conversation_context(
            request,
            total_messages=len(exact_messages),
            exact_messages=exact_remaining,
            compressed_messages=[],
            compressed_message_count=represented_message_count,
            rolling_memory=rolling_memory,
            current_draft=current_draft,
            latest_draft=latest_draft,
            last_assistant_state=last_assistant_state,
            context_budget=context_budget,
            estimated_tokens=base_tokens,
            compressed=True,
        )
        estimated_tokens = base_tokens + _estimated_json_tokens(
            {
                "conversation": exact_remaining,
                "conversationContext": context,
            },
        )

    context["compression"]["estimatedInputTokens"] = estimated_tokens
    if estimated_tokens <= budget_tokens:
        return {
            "conversation": exact_remaining,
            "conversationContext": context,
        }

    # The latest exact window and one value in every populated memory category
    # are correctness boundaries. If they do not fit, fail before the provider
    # call rather than silently dropping recent turns or semantic state.
    raise LlmRequestError(
        "The current resume and conversation state exceed the selected "
        "model context window. Start a new conversation or choose a model "
        "with a larger context window.",
    )


def _conversation_context(
    request: AgentChatRequest,
    *,
    total_messages: int,
    exact_messages: list[dict[str, str]],
    compressed_messages: list[dict[str, Any]],
    compressed_message_count: int | None = None,
    rolling_memory: dict[str, list[Any]] | None = None,
    current_draft: dict[str, Any] | None,
    latest_draft: dict[str, Any] | None,
    last_assistant_state: dict[str, Any] | None,
    context_budget: _ContextBudget | None,
    estimated_tokens: int,
    compressed: bool,
) -> dict[str, Any]:
    represented_count = (
        compressed_message_count
        if compressed_message_count is not None
        else len(compressed_messages)
    )
    return {
        "totalMessages": total_messages,
        "exactMessageCount": len(exact_messages),
        "compressedMessageCount": represented_count,
        "omittedMessageCount": max(
            0,
            total_messages - len(exact_messages) - represented_count,
        ),
        # Kept for clients from the previous payload shape. New compression
        # state lives in rollingMemory and never contains truncated prose.
        "olderSummary": compressed_messages,
        "rollingMemory": rolling_memory or _empty_rolling_memory(),
        "currentDraft": current_draft,
        "activeDraft": _active_draft_state(current_draft, latest_draft),
        "latestDraft": latest_draft,
        "lastAssistantState": last_assistant_state,
        "appliedActions": request.applied_actions,
        "compression": {
            "applied": compressed,
            "triggerRatio": CONTEXT_COMPRESSION_RATIO,
            "triggerInputTokens": (
                context_budget.trigger_tokens if context_budget else None
            ),
            "inputBudgetTokens": (
                context_budget.input_tokens if context_budget else None
            ),
            "outputReserveTokens": (
                context_budget.output_reserve_tokens if context_budget else 0
            ),
            "toolSchemaTokens": (
                context_budget.tool_schema_tokens if context_budget else 0
            ),
            "safetyMarginTokens": (
                context_budget.safety_margin_tokens if context_budget else 0
            ),
            "estimatedInputTokens": estimated_tokens,
        },
    }


def _conversation_with_current_prompt(
    request: AgentChatRequest,
) -> list[AgentConversationItem]:
    conversation = list(request.messages or request.conversation)
    prompt = _current_prompt(request)

    if prompt and not any(
        _conversation_item_role(item) == "user"
        and _conversation_item_text(item) == prompt
        for item in conversation
    ):
        conversation.append(
            AgentConversationItem(role="user", text=prompt),
        )

    return conversation


def _conversation_entries(conversation: list[Any]) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for item in conversation:
        text = _conversation_item_text(item)
        if text:
            entries.append(
                {
                    "role": _conversation_item_role(item),
                    "content": text,
                },
            )

    return entries


def _empty_rolling_memory() -> dict[str, list[Any]]:
    return {key: [] for key in ROLLING_MEMORY_KEYS}


def _build_rolling_memory(
    conversation: list[Any],
) -> tuple[dict[str, list[Any]], int]:
    """Extract stable long-term state without another nondeterministic LLM call."""

    memory = _empty_rolling_memory()
    represented_ids: set[int] = set()
    fallback_goal: tuple[int, str] | None = None

    for index, item in enumerate(conversation):
        text = _conversation_item_text(item)
        role = _conversation_item_role(item)
        represented = False

        if role == "user" and text:
            if fallback_goal is None:
                fallback_goal = (index, text)
            category = _user_memory_category(text)
            if category:
                represented = _append_unique(memory[category], text) or represented
        elif role == "assistant" and _is_pending_question(text):
            represented = (
                _append_unique(memory["pendingQuestions"], text) or represented
            )

        for filename in _conversation_item_filenames(item):
            represented = (
                _append_unique(memory["factsAndMaterials"], filename) or represented
            )

        for source in _conversation_source_references(item):
            represented = (
                _append_unique(memory["sourceReferences"], source) or represented
            )

        if represented:
            represented_ids.add(index)

    # A conversation may predate explicit labels. Preserve its first user
    # request as the best deterministic goal fallback instead of discarding it.
    if not memory["userGoals"] and fallback_goal is not None:
        index, text = fallback_goal
        _append_unique(memory["userGoals"], text)
        represented_ids.add(index)

    return memory, len(represented_ids)


def _user_memory_category(text: str) -> str | None:
    normalized = text.strip().casefold()
    for category, prefixes in (
        ("acceptedDecisions", ACCEPTED_DECISION_PREFIXES),
        ("rejectedDecisions", REJECTED_DECISION_PREFIXES),
        ("constraints", CONSTRAINT_PREFIXES),
        ("userGoals", GOAL_PREFIXES),
        ("factsAndMaterials", FACT_PREFIXES),
    ):
        if normalized.startswith(prefixes):
            return category
    return None


def _is_pending_question(text: str) -> bool:
    normalized = text.strip().casefold()
    return bool(normalized) and (
        normalized.startswith(PENDING_QUESTION_PREFIXES)
        or normalized.endswith(("?", "？"))
    )


def _append_unique(items: list[Any], value: Any) -> bool:
    if value in items:
        return False
    items.append(value)
    return True


def _conversation_item_filenames(item: Any) -> list[str]:
    files = item.get("files") if isinstance(item, dict) else getattr(item, "files", [])
    if not isinstance(files, list):
        return []

    filenames: list[str] = []
    for file in files:
        value = (
            file.get("filename")
            if isinstance(file, dict)
            else getattr(file, "filename", None)
        )
        if isinstance(value, str) and value.strip():
            _append_unique(filenames, value.strip())
    return filenames


def _conversation_source_references(item: Any) -> list[dict[str, str]]:
    response = _conversation_item_response(item)
    sources = response.get("sources") if response else None
    if not isinstance(sources, list):
        return []

    references: list[dict[str, str]] = []
    for source in sources:
        if not isinstance(source, dict):
            continue
        reference = {
            key: value.strip()
            for key in ("id", "title", "sourceType", "url", "excerpt")
            for value in [source.get(key)]
            if isinstance(value, str) and value.strip()
        }
        if reference:
            _append_unique(references, reference)
    return references


def _drop_oldest_redundant_memory_item(
    memory: dict[str, list[Any]],
) -> bool:
    for key in ROLLING_MEMORY_TRIM_ORDER:
        items = memory[key]
        if len(items) > 1:
            items.pop(0)
            return True
    return False


def _latest_draft_state(
    conversation: list[Any],
    *,
    token_budget: int | None,
) -> dict[str, Any] | None:
    for item in reversed(conversation):
        response = _conversation_item_response(item)
        if response is None:
            continue

        edits = _compact_response_edits(
            response.get("edits"),
            token_budget=token_budget,
        )
        if not edits:
            continue

        return {
            "messageId": _conversation_item_id(item),
            "text": _truncate_to_tokens(
                _string_value(response.get("text")) or _conversation_item_text(item),
                token_budget,
            ),
            "editCount": len(response.get("edits") or []),
            "edits": edits,
            "actions": _string_list(response.get("actions")),
        }

    return None


def _current_draft_state(
    request: AgentChatRequest,
    *,
    token_budget: int | None,
) -> dict[str, Any] | None:
    draft = request.draft_state
    if draft is None:
        return None

    return {
        "id": draft.id,
        "status": draft.status,
        "sourceMessageId": draft.source_message_id,
        "createdAt": draft.created_at,
        "updatedAt": draft.updated_at,
        "editCount": draft.edit_count,
        "edits": _compact_response_edits(
            draft.edits,
            token_budget=token_budget,
        ),
        "diffs": _compact_draft_diffs(
            draft.diffs,
            token_budget=token_budget,
        ),
        "resumeOutline": _compact_resume_outline(draft.resume),
    }


def _active_draft_state(
    current_draft: dict[str, Any] | None,
    latest_draft: dict[str, Any] | None,
) -> dict[str, Any] | None:
    return current_draft or latest_draft


def _last_assistant_state(
    conversation: list[Any],
    *,
    token_budget: int | None,
) -> dict[str, Any] | None:
    for item in reversed(conversation):
        if _conversation_item_role(item) != "assistant":
            continue

        response = _conversation_item_response(item)
        state = _assistant_response_state(response) if response else {}
        state.update(
            {
                "messageId": _conversation_item_id(item),
                "text": _truncate_to_tokens(
                    _conversation_item_text(item),
                    token_budget,
                ),
            },
        )
        return state

    return None


def _assistant_response_state(response: dict[str, Any]) -> dict[str, Any]:
    edits = response.get("edits")
    tools = response.get("tools")
    sources = response.get("sources")

    source_refs = [
        {
            key: source[key]
            for key in ("id", "title", "url")
            if isinstance(source.get(key), str) and source[key].strip()
        }
        for source in (sources if isinstance(sources, list) else [])[:4]
        if isinstance(source, dict)
    ]

    return {
        "editCount": len(edits) if isinstance(edits, list) else 0,
        "editTitles": [
            title
            for edit in (edits if isinstance(edits, list) else [])
            if isinstance(edit, dict)
            for title in [_string_value(edit.get("title"))]
            if title
        ],
        "toolCount": len(tools) if isinstance(tools, list) else 0,
        "sourceCount": len(sources) if isinstance(sources, list) else 0,
        # Preserve compact citation identity across compression so later turns
        # can distinguish grounded evidence from unsupported recollection.
        "sourceRefs": [source for source in source_refs if source],
    }


def _compact_response_edits(
    value: Any,
    *,
    token_budget: int | None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    edits: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        operation = item.get("operation")
        edit: dict[str, Any] = {}
        for key in ("id", "title", "target", "reason", "status"):
            text = _string_value(item.get(key))
            if text:
                edit[key] = text
        if isinstance(operation, dict):
            operation_type = _string_value(operation.get("type"))
            if operation_type:
                edit["operationType"] = operation_type
            section_id = _string_value(operation.get("sectionId"))
            if section_id:
                edit["sectionId"] = section_id
            item_id = _string_value(operation.get("itemId"))
            if item_id:
                edit["itemId"] = item_id
        if edit:
            candidate = [*edits, edit]
            if (
                token_budget is not None
                and edits
                and _estimated_json_tokens(candidate) > token_budget
            ):
                break
            edits.append(edit)

    return edits


def _compact_draft_diffs(
    value: Any,
    *,
    token_budget: int | None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    diffs: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        diff: dict[str, Any] = {}
        for key in (
            "id",
            "operationId",
            "path",
            "kind",
            "label",
            "sectionId",
            "itemId",
        ):
            text = _string_value(item.get(key))
            if text:
                diff[key] = text

        before = _compact_unknown_value(item.get("before"), token_budget)
        after = _compact_unknown_value(item.get("after"), token_budget)
        if before:
            diff["before"] = before
        if after:
            diff["after"] = after

        if diff:
            candidate = [*diffs, diff]
            if (
                token_budget is not None
                and diffs
                and _estimated_json_tokens(candidate) > token_budget
            ):
                break
            diffs.append(diff)

    return diffs


def _compact_unknown_value(value: Any, token_budget: int | None) -> str:
    if value is None:
        return ""

    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    return _truncate_to_tokens(text.strip(), token_budget)


def _compact_resume_outline(resume: Any) -> dict[str, Any]:
    if not isinstance(resume, dict):
        return {}

    basic = resume.get("basic")
    basic_data = basic if isinstance(basic, dict) else {}
    sections_value = resume.get("sections")
    sections = sections_value if isinstance(sections_value, list) else []

    return {
        "schemaVersion": resume.get("schemaVersion"),
        "basic": {
            "headline": _string_value(basic_data.get("headline")),
            "hasSummary": bool(_string_value(basic_data.get("summary"))),
        },
        "basicFieldStatus": sanitize_agent_resume(resume).get("basicFieldStatus", {}),
        "sectionCount": len(sections),
        "sections": [_compact_section_outline(section) for section in sections],
    }


def _compact_section_outline(section: Any) -> dict[str, Any]:
    if not isinstance(section, dict):
        return {}

    items = section.get("items")
    item_list = items if isinstance(items, list) else []
    kind = _string_value(section.get("kind"))

    return {
        "id": _string_value(section.get("id")),
        "kind": kind,
        "title": _string_value(section.get("title")),
        "itemCount": len(item_list),
        "items": [
            _compact_item_outline(item, section_kind=kind)
            for item in item_list[:3]
        ],
    }


def _compact_item_outline(
    item: Any,
    *,
    section_kind: str,
) -> dict[str, str]:
    if not isinstance(item, dict):
        return {}

    outline = {"id": _string_value(item.get("id"))}
    visible_field_count = 0
    for field in ITEM_STRING_FIELDS_BY_KIND.get(section_kind, ()):
        value = _string_value(item.get(field))
        if not value:
            continue
        compact_value = " ".join(value.split())
        outline[field] = (
            compact_value
            if len(compact_value) <= 160
            else f"{compact_value[:157]}..."
        )
        visible_field_count += 1
        if visible_field_count >= 3:
            break
    return outline


def _conversation_item_role(item: Any) -> str:
    if isinstance(item, dict):
        role = item.get("role")
    else:
        role = getattr(item, "role", "")

    return role if role in {"user", "assistant"} else "user"


def _conversation_item_text(item: Any) -> str:
    if isinstance(item, dict):
        text = item.get("text")
    else:
        text = getattr(item, "text", "")

    return text.strip() if isinstance(text, str) else ""


def _conversation_item_id(item: Any) -> str | None:
    if isinstance(item, dict):
        value = item.get("id")
    else:
        value = getattr(item, "id", None)

    return value if isinstance(value, str) else None


def _conversation_item_response(item: Any) -> dict[str, Any] | None:
    if isinstance(item, dict):
        response = item.get("response")
    else:
        response = getattr(item, "response", None)

    return response if isinstance(response, dict) else None


def _string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str) and item.strip()]


def _context_budget(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    tool_schema_tokens: int,
) -> _ContextBudget | None:
    window_tokens = _context_window_tokens(request, config)
    if window_tokens is None:
        return None

    # Adapters apply a default output cap when max_tokens is unset. Reuse that
    # exact value so context planning cannot silently spend the output reserve.
    output_reserve_tokens = max(0, request_max_output_tokens(config))
    safety_margin_tokens = max(
        MIN_CONTEXT_SAFETY_MARGIN_TOKENS,
        int(window_tokens * CONTEXT_SAFETY_MARGIN_RATIO),
    )
    input_tokens = (
        window_tokens
        - output_reserve_tokens
        - tool_schema_tokens
        - safety_margin_tokens
    )
    if input_tokens <= 0:
        raise LlmRequestError(
            "The selected model context window is too small after reserving "
            "output, tool definitions, and runtime safety margin.",
        )

    return _ContextBudget(
        input_tokens=input_tokens,
        trigger_tokens=max(1, int(input_tokens * CONTEXT_COMPRESSION_RATIO)),
        output_reserve_tokens=output_reserve_tokens,
        tool_schema_tokens=tool_schema_tokens,
        safety_margin_tokens=safety_margin_tokens,
    )


def _context_input_budget_tokens(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    tool_schema_tokens: int = 0,
) -> int | None:
    budget = _context_budget(
        request,
        config,
        tool_schema_tokens=tool_schema_tokens,
    )
    return budget.input_tokens if budget else None


def _attachment_context_token_budget(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    tool_schema_tokens: int,
) -> int:
    """Reserve at most half of model input context for uploaded material.

    Resume state, instructions, and conversation still need room. When model
    metadata has no context window, the fallback is large enough for a typical
    paper while remaining bounded for compatible endpoints with unknown limits.
    """

    input_budget = _context_input_budget_tokens(
        request,
        config,
        tool_schema_tokens=tool_schema_tokens,
    )
    if input_budget is None:
        return DEFAULT_ATTACHMENT_CONTEXT_TOKEN_BUDGET
    return max(1_024, input_budget // 2)


def _fit_attachment_context(
    files: list[dict[str, str]],
    *,
    token_budget: int,
) -> list[dict[str, str]]:
    """Require complete extracted text to fit; never send a partial document."""

    if _estimated_json_tokens(files) > token_budget:
        raise LlmRequestError(
            "The attached document is too large for the selected model context.",
        )
    return files


def _context_window_tokens(
    request: AgentChatRequest,
    config: AgentLlmConfig,
) -> int | None:
    settings_value = request.settings.get("contextWindowTokens")
    if isinstance(settings_value, int) and settings_value > 0:
        return settings_value
    if isinstance(settings_value, str) and settings_value.isdigit():
        return int(settings_value)

    if config.context_window_tokens and config.context_window_tokens > 0:
        return config.context_window_tokens

    return None


def _tool_schema_token_reserve(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    mode: AgentMessageMode,
) -> int:
    """Estimate only schemas that the same frozen policy exposes this turn."""

    if mode != "tools" or not config.supports_tools:
        return 0

    policy = capability_policy_for_request(request)
    schemas = agent_tool_schemas_for_names(policy.allowed_tools)
    return _estimated_json_tokens(schemas) if schemas else 0


def _state_token_budget(input_budget_tokens: int | None) -> int | None:
    if input_budget_tokens is None:
        return None

    return max(128, input_budget_tokens // 32)


def _estimated_json_tokens(value: Any) -> int:
    return _estimated_tokens(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")),
    )


def _estimated_tokens(text: str) -> int:
    ascii_count = sum(1 for char in text if ord(char) < 128)
    non_ascii_count = len(text) - ascii_count
    return max(1, (ascii_count + 3) // 4 + non_ascii_count)


def _truncate_to_tokens(text: str, token_budget: int | None) -> str:
    if token_budget is None:
        return text

    if _estimated_tokens(text) <= token_budget:
        return text

    if token_budget <= 1:
        return "…"

    low = 0
    high = len(text)
    while low < high:
        mid = (low + high + 1) // 2
        candidate = f"{text[:mid].rstrip()}…"
        if _estimated_tokens(candidate) <= token_budget:
            low = mid
        else:
            high = mid - 1

    return f"{text[:low].rstrip()}…"


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


def _visible_tool_context(tools: list[Any]) -> dict[str, Any]:
    web_searches: list[dict[str, Any]] = []
    resume_analyses: list[dict[str, Any]] = []
    for tool in tools:
        if getattr(tool, "state", "") != "output-available":
            continue

        output = getattr(tool, "output", None)
        if not isinstance(output, dict):
            continue

        title = getattr(tool, "title", "")
        if title == "web_search":
            search_context = _visible_web_search_context(output)
            if search_context:
                web_searches.append(search_context)
        elif title == "resume_analysis":
            analysis_context = _visible_resume_analysis_context(output)
            if analysis_context:
                resume_analyses.append(analysis_context)

    context: dict[str, Any] = {}
    if web_searches:
        context["webSearch"] = web_searches
    if resume_analyses:
        context["resumeAnalysis"] = resume_analyses
    return context


def _visible_web_search_context(output: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key in ("purpose", "query"):
        text = _string_value(output.get(key))
        if text:
            context[key] = text

    queries = _string_list(output.get("queries"))[:5]
    if queries:
        context["queries"] = queries

    results = _visible_web_search_results(output.get("results"))
    if results:
        context["results"] = results
    else:
        single_result = _visible_web_search_result(output)
        if single_result:
            context["results"] = [single_result]

    return context


def _visible_web_search_results(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    results: list[dict[str, str]] = []
    for item in value[:10]:
        result = _visible_web_search_result(item)
        if result:
            results.append(result)

    return results


def _visible_web_search_result(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}

    result: dict[str, str] = {}
    for key in ("title", "url", "excerpt", "sourceKind"):
        text = _string_value(value.get(key))
        if text:
            result[key] = _truncate_to_tokens(text, 180 if key == "excerpt" else 80)

    return result


def _visible_resume_analysis_context(output: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    matched_keywords = _string_list(output.get("matchedKeywords"))[:8]
    missing_keywords = _string_list(output.get("missingKeywords"))[:8]
    empty_section_ids = _string_list(output.get("emptySectionIds"))[:8]

    if matched_keywords:
        context["matchedKeywords"] = matched_keywords
    if missing_keywords:
        context["missingKeywords"] = missing_keywords
    if empty_section_ids:
        context["emptySectionIds"] = empty_section_ids

    target_fit = output.get("targetFit")
    if isinstance(target_fit, dict):
        context["targetFit"] = _visible_target_fit_context(target_fit)

    return context


def _visible_target_fit_context(target_fit: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for key in ("hasTargetContext", "score"):
        value = target_fit.get(key)
        if isinstance(value, (bool, int, float)) and not isinstance(value, str):
            context[key] = value

    target_role = _string_value(target_fit.get("targetRole"))
    if target_role:
        context["targetRole"] = target_role

    for key in ("recommendedTargets", "warnings"):
        value = target_fit.get(key)
        if isinstance(value, list):
            context[key] = value[:6]

    return context


def _locale_name(request: AgentChatRequest) -> str:
    return agent_text(request.locale, "locale.name")
