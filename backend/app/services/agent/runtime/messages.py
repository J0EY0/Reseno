import json
from dataclasses import dataclass
from typing import Any, Literal, cast

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentResumeEditSuggestion,
    AgentTurnWorkspaceSnapshots,
)
from app.services.llm import (
    AgentLlmConfig,
    LlmRequestError,
    supports_native_attachment,
)
from app.services.llm.common import request_max_output_tokens
from app.services.llm.types import (
    LlmAssistantInputMessage,
    LlmContent,
    LlmContentPart,
    LlmInputMessage,
    LlmUserMessage,
)
from app.services.resume_document_contract import ITEM_STRING_FIELDS_BY_KIND

from ..attachments import (
    AgentAttachmentError,
    attachment_content_part,
    current_request_attachments,
    load_agent_attachment,
)
from ..executor import (
    _agent_file_context,
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
    STREAMING_FINAL_RESPONSE_PROMPT,
    SYSTEM_PROMPT,
)
from ..request_context import active_resume
from ..target_context import target_context_from_request
from ..tools.registry import agent_tool_schemas_for_names

AgentMessageMode = Literal["tools", "streaming_final"]
CONTEXT_COMPRESSION_RATIO = 0.85
CONTEXT_CHECKPOINT_TARGET_RATIO = 0.70
CONTEXT_SAFETY_MARGIN_RATIO = 0.01
MIN_CONTEXT_SAFETY_MARGIN_TOKENS = 256
DEFAULT_ATTACHMENT_CONTEXT_TOKEN_BUDGET = 32_000
# Native media is opaque at this provider-neutral layer. Image billing varies
# by resize/tile policy, so 4K is a conservative high-detail reserve without
# treating transport bytes as text. Documents reuse the existing 32K complete-
# document budget. Both values are intentionally fixed and additive.
NATIVE_IMAGE_TOKEN_RESERVE = 4_096
NATIVE_FILE_TOKEN_RESERVE = DEFAULT_ATTACHMENT_CONTEXT_TOKEN_BUDGET


@dataclass(frozen=True)
class _ContextBudget:
    """One shared context budget for compression and final validation."""

    input_tokens: int
    trigger_tokens: int
    output_reserve_tokens: int
    tool_schema_tokens: int
    safety_margin_tokens: int


@dataclass(frozen=True)
class _ConversationProjection:
    """Conversation state projected behind the public message-builder seam."""

    exact_messages: list[LlmInputMessage]
    summary: str | None
    state: dict[str, Any]


@dataclass(frozen=True)
class AgentPromptLimits:
    """Provider-independent input limits used by the compaction orchestrator."""

    input_tokens: int
    trigger_tokens: int
    target_tokens: int


def build_agent_messages(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    mode: AgentMessageMode,
    draft: AgentChatMessage | None = None,
    force_attachment_text: bool = False,
) -> list[LlmInputMessage]:
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
    messages: list[LlmInputMessage] = [
        {
            "role": "system",
            "content": system_content,
        },
    ]

    tool_schema_tokens = _tool_schema_token_reserve(request, config, mode=mode)
    hidden_terms = _request_hidden_terms(request)
    context_files, binary_parts = _current_attachment_payload(
        request,
        config,
        force_attachment_text=force_attachment_text,
        tool_schema_tokens=tool_schema_tokens,
        hidden_terms=hidden_terms,
    )
    workspace = _workspace_context(
        request,
        draft=draft,
        hidden_terms=hidden_terms,
    )
    current_prompt = _sanitized_text(
        _current_prompt(request),
        hidden_terms=hidden_terms,
    )
    projection = _conversation_projection(
        request,
        config=config,
        mode=mode,
        tool_schema_tokens=tool_schema_tokens,
        hidden_terms=hidden_terms,
    )
    sanitized_state = sanitize_agent_value(
        projection.state,
        hidden_terms=hidden_terms,
    )
    workspace["conversationState"] = (
        sanitized_state if isinstance(sanitized_state, dict) else {}
    )

    if projection.summary is not None:
        messages.append(
            {
                "role": "user",
                "content": _json_message(
                    "conversationSummary",
                    projection.summary,
                ),
            },
        )
    messages.extend(projection.exact_messages)

    # Workspace is a per-turn compiler event. Putting its immutable snapshot
    # immediately before the matching native user turn lets the next request
    # replay this request byte-for-byte even when the live resume or draft has
    # since changed. It remains user-role data, never a trusted instruction.
    generated_workspace = _json_message("workspaceContext", workspace)
    messages.append(
        {
            "role": "user",
            "content": _active_workspace_content(
                request,
                mode=mode,
                generated=generated_workspace,
            ),
        },
    )

    # Only the current turn may carry extracted text or original bytes. The
    # persisted transcript deliberately replays the user's plain prompt on the
    # next turn instead of retaining sensitive attachment payloads forever.
    messages.append(
        {
            "role": "user",
            "content": _current_turn_content(
                current_prompt,
                context_files=context_files,
                binary_parts=binary_parts,
            ),
        },
    )
    return messages


def _json_message(name: str, value: Any) -> str:
    return json.dumps({name: value}, ensure_ascii=False, separators=(",", ":"))


def _active_workspace_content(
    request: AgentChatRequest,
    *,
    mode: AgentMessageMode,
    generated: str,
) -> str:
    snapshots = request._active_workspace_snapshots
    if snapshots is None:
        return generated
    if snapshots.turn_message_id != request.message.id:
        raise LlmRequestError(
            "The active workspace snapshot belongs to another user turn.",
        )
    frozen = snapshots.tools if mode == "tools" else snapshots.streaming_final
    return frozen or generated


def freeze_agent_workspace_snapshot(
    request: AgentChatRequest,
    messages: list[LlmInputMessage],
    *,
    mode: AgentMessageMode,
) -> None:
    """Freeze the canonical current workspace after prompt preparation.

    Provider retries and native-file fallback must see the same compiler event
    that the first request saw. The bundle remains request-private and is only
    written to SQLite later, atomically with a successful assistant response.
    """

    if len(messages) < 2 or messages[-2]["role"] != "user":
        raise LlmRequestError("The Agent workspace snapshot is missing.")
    content = messages[-2]["content"]
    if not isinstance(content, str) or not content.startswith('{"workspaceContext":'):
        raise LlmRequestError("The Agent workspace snapshot is invalid.")

    turn_message_id = request.message.id
    assert turn_message_id is not None
    existing = request._active_workspace_snapshots
    if existing is not None and existing.turn_message_id != turn_message_id:
        raise LlmRequestError(
            "The active workspace snapshot belongs to another user turn.",
        )
    tools = existing.tools if existing is not None else None
    streaming_final = existing.streaming_final if existing is not None else None
    frozen = tools if mode == "tools" else streaming_final
    if frozen is not None and frozen != content:
        raise LlmRequestError("The Agent workspace snapshot changed during retry.")
    if mode == "tools":
        tools = content
    else:
        streaming_final = content
    request._active_workspace_snapshots = AgentTurnWorkspaceSnapshots(
        turnMessageId=turn_message_id,
        tools=tools,
        streamingFinal=streaming_final,
    )


def _current_turn_content(
    prompt: str,
    *,
    context_files: list[dict[str, Any]],
    binary_parts: list[LlmContentPart],
) -> LlmContent:
    if not context_files and not binary_parts:
        return prompt

    parts: list[LlmContentPart] = [{"type": "text", "text": prompt}]
    if context_files:
        # A separator is part of the second text block because adapters are
        # allowed to concatenate neutral text parts without adding whitespace.
        parts.append(
            {
                "type": "text",
                "text": "\n\n" + _json_message("currentRequestFiles", context_files),
            },
        )
    return [*parts, *binary_parts]


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
    hidden_terms: tuple[str, ...],
) -> tuple[list[dict[str, str]], list[LlmContentPart]]:
    files = _safe_current_request_attachments(request)
    if not files:
        return [], []

    session_id = _attachment_session_id(request)
    text_files: list[dict[str, Any]] = []
    binary_parts: list[LlmContentPart] = []

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
                binary_parts.append(
                    cast(
                        LlmContentPart,
                        attachment_content_part(
                            session_id,
                            file,
                            hidden_terms=hidden_terms,
                        ),
                    ),
                )
                continue

            if not force_attachment_text and supports_native_attachment(
                config, attachment.media_type
            ):
                binary_parts.append(
                    cast(
                        LlmContentPart,
                        attachment_content_part(
                            session_id,
                            file,
                            hidden_terms=hidden_terms,
                        ),
                    ),
                )
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
    return [CORE_POLICY_PROMPT, STREAMING_FINAL_RESPONSE_PROMPT]


def _workspace_context(
    request: AgentChatRequest,
    *,
    draft: AgentChatMessage | None = None,
    hidden_terms: tuple[str, ...],
) -> dict[str, Any]:
    resume = active_resume(request)
    target_context = (
        draft.target_context
        if draft is not None and draft.target_context is not None
        else target_context_from_request(request)
    )
    workspace: dict[str, Any] = {
        "responseLanguage": _locale_name(request),
        "targetContext": target_context.model_dump(mode="json", by_alias=True)
        if target_context is not None
        else None,
        "resume": sanitize_agent_resume(resume, hidden_terms=hidden_terms),
    }

    if draft is not None:
        workspace.update(
            {
                # Only public HTTP(S) references participate in the inline
                # citation protocol. User attachments and remembered target
                # context remain available through their dedicated current
                # request envelopes, but must never be persisted/replayed as
                # citation excerpts merely because AgentSource permits one.
                "citationSources": [
                    source.model_dump(mode="json", by_alias=True)
                    for source in draft.sources
                    if source.source_type == "web"
                    and isinstance(source.url, str)
                    and source.url.strip().lower().startswith(("http://", "https://"))
                ],
                "draftStatusText": draft.text,
                "draftEditCount": len(draft.edits),
                "draftEdits": _visible_edit_summaries(draft.edits),
                "toolContext": _visible_tool_context(draft.tools),
            },
        )

    sanitized_workspace = sanitize_agent_value(workspace, hidden_terms=hidden_terms)
    return sanitized_workspace if isinstance(sanitized_workspace, dict) else {}


def _request_hidden_terms(request: AgentChatRequest) -> tuple[str, ...]:
    """Hide identity known by either the saved resume or pending candidate.

    A pending draft can legitimately clear or replace a personal field. The
    saved value must still remain a hidden term for history, attachments, and
    the current prompt; otherwise choosing the draft as the active snapshot
    would accidentally reveal the value that was present in the base resume.
    """

    return tuple(
        dict.fromkeys(
            (
                *resume_hidden_terms(request.resume),
                *resume_hidden_terms(active_resume(request)),
            ),
        ),
    )


def _conversation_projection(
    request: AgentChatRequest,
    *,
    config: AgentLlmConfig,
    mode: AgentMessageMode,
    tool_schema_tokens: int,
    hidden_terms: tuple[str, ...],
) -> _ConversationProjection:
    # A persisted checkpoint replaces exactly one authoritative history
    # prefix. The remaining product messages stay native and ordered, which is
    # what lets a later request reuse the previous provider prompt prefix.
    conversation = list(request.messages)
    checkpoint = request._active_conversation_checkpoint
    checkpoint_count = (
        _checkpoint_message_count(conversation, checkpoint.through_message_id)
        if checkpoint is not None
        else 0
    )
    exact_messages = _conversation_entries(
        conversation[checkpoint_count:],
        hidden_terms=hidden_terms,
        workspace_snapshots=request._historical_workspace_snapshots,
        mode=mode,
    )
    context_budget = _context_budget(
        request,
        config,
        tool_schema_tokens=tool_schema_tokens,
    )
    state_token_budget = _state_token_budget(
        context_budget.input_tokens if context_budget is not None else None,
    )
    current_draft = _current_draft_state(
        request,
        token_budget=state_token_budget,
    )
    state = _conversation_state(
        request,
        current_draft=current_draft,
    )
    summary = (
        _sanitized_text(checkpoint.summary, hidden_terms=hidden_terms)
        if checkpoint is not None
        else None
    )
    if checkpoint is not None and not summary:
        raise LlmRequestError("The stored conversation checkpoint is empty.")
    return _ConversationProjection(
        exact_messages=exact_messages,
        summary=summary,
        state=state,
    )


def _conversation_state(
    request: AgentChatRequest,
    *,
    current_draft: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "currentDraft": current_draft,
        "appliedActions": request.applied_actions,
    }


def _checkpoint_message_count(
    source_conversation: list[Any],
    through_message_id: str,
) -> int:
    for index, item in enumerate(source_conversation):
        if _conversation_item_id(item) == through_message_id:
            return index + 1
    raise LlmRequestError(
        "The stored conversation checkpoint does not match the authoritative "
        "conversation history.",
    )


def agent_checkpoint_message_count(request: AgentChatRequest) -> int:
    """Resolve the active summary boundary against authoritative history."""

    checkpoint = request._active_conversation_checkpoint
    if checkpoint is None:
        return 0
    return _checkpoint_message_count(
        list(request.messages),
        checkpoint.through_message_id,
    )


def agent_compaction_boundaries(
    request: AgentChatRequest,
    *,
    after_count: int,
) -> list[tuple[int, str]]:
    """Return advancing cuts whose exact tail begins with a user turn.

    Product histories can contain an assistant-only failure or an attachment
    metadata companion, so parity is not a safe boundary. The next durable
    product message must itself be user-authored; this retains at least the
    latest complete historical user turn and every event after it.
    """

    history = list(request.messages)
    boundaries: list[tuple[int, str]] = []
    for count in range(after_count + 1, len(history)):
        if _conversation_item_role(history[count]) != "user":
            continue
        through_message_id = _conversation_item_id(history[count - 1])
        if through_message_id:
            boundaries.append((count, through_message_id))
    return boundaries


def agent_compaction_events(
    request: AgentChatRequest,
    *,
    start_count: int,
    end_count: int,
) -> list[dict[str, Any]]:
    """Project one ordered history slice into safe summarizer input.

    The compactor receives product-message identity and compact response state,
    but never attachment bytes, extracted excerpts, raw tool I/O, or provider
    continuation state. This is intentionally separate from the provider's
    native exact-tail representation.
    """

    hidden_terms = _request_hidden_terms(request)
    events: list[dict[str, Any]] = []
    for item in list(request.messages)[start_count:end_count]:
        role = _conversation_item_role(item)
        message_id = _conversation_item_id(item)
        event: dict[str, Any] = {
            # This identifier is only descriptive input for the private
            # summarizer, so it must cross the same privacy boundary as text.
            # Checkpoint selection separately keeps the untouched product ID.
            "id": (
                _sanitized_text(message_id, hidden_terms=hidden_terms)
                if message_id is not None
                else None
            ),
            "role": role,
        }
        text = _conversation_item_text(item)
        if text:
            event["text"] = _sanitized_text(text, hidden_terms=hidden_terms)
        filenames = _conversation_item_filenames(item)
        if filenames:
            event["attachments"] = [
                {
                    "filename": _sanitized_text(
                        filename,
                        hidden_terms=hidden_terms,
                    ),
                }
                for filename in filenames
            ]
        if role == "assistant":
            response = _conversation_item_response(item)
            response_state = _assistant_response_state(response) if response else {}
            if response_state:
                event["assistantResponseContext"] = sanitize_agent_value(
                    response_state,
                    hidden_terms=hidden_terms,
                )
        events.append(event)
    return events


def sanitize_agent_compaction_text(
    request: AgentChatRequest,
    text: str,
) -> str:
    """Apply the same identity boundary to a generated checkpoint summary."""

    return _sanitized_text(text, hidden_terms=_request_hidden_terms(request))


def agent_prompt_limits(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
    mode: AgentMessageMode,
) -> AgentPromptLimits | None:
    """Return the main prompt limits without exposing provider cache details."""

    budget = _context_budget(
        request,
        config,
        tool_schema_tokens=_tool_schema_token_reserve(request, config, mode=mode),
    )
    if budget is None:
        return None
    return AgentPromptLimits(
        input_tokens=budget.input_tokens,
        trigger_tokens=budget.trigger_tokens,
        target_tokens=max(
            1,
            int(budget.input_tokens * CONTEXT_CHECKPOINT_TARGET_RATIO),
        ),
    )


def estimate_agent_messages_tokens(messages: list[LlmInputMessage]) -> int:
    """Estimate text plus bounded native-media reserves, never base64 bytes."""

    estimated_messages: list[dict[str, Any]] = []
    media_tokens = 0
    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            estimated_messages.append(cast(dict[str, Any], message))
            continue

        estimated_parts: list[dict[str, Any]] = []
        for part in content:
            part_type = part["type"]
            if part_type in {"image", "file"}:
                # Base64 is a transport encoding, not model-visible text. Keep
                # the media metadata in the ordinary JSON estimate and account
                # for the opaque media through one stable, bounded reserve.
                estimated_parts.append(
                    {key: value for key, value in part.items() if key != "data"},
                )
                media_tokens += (
                    NATIVE_IMAGE_TOKEN_RESERVE
                    if part_type == "image"
                    else NATIVE_FILE_TOKEN_RESERVE
                )
            else:
                estimated_parts.append(cast(dict[str, Any], part))
        estimated_messages.append({**message, "content": estimated_parts})

    return _estimated_json_tokens(estimated_messages) + media_tokens


def _conversation_entries(
    conversation: list[Any],
    *,
    hidden_terms: tuple[str, ...],
    workspace_snapshots: dict[str, AgentTurnWorkspaceSnapshots] | None = None,
    mode: AgentMessageMode = "streaming_final",
) -> list[LlmInputMessage]:
    entries: list[LlmInputMessage] = []
    for item in conversation:
        role = _conversation_item_role(item)
        text = _conversation_item_text(item)
        response = _conversation_item_response(item) if role == "assistant" else None
        response_state = _assistant_response_state(response) if response else {}
        if role == "assistant":
            if text:
                entries.append(
                    LlmAssistantInputMessage(
                        role="assistant",
                        content=_sanitized_text(
                            text,
                            hidden_terms=hidden_terms,
                        ),
                    ),
                )
            if response_state:
                response_state["messageId"] = _conversation_item_id(item)
                entries.append(
                    LlmUserMessage(
                        role="user",
                        content=_sanitized_text(
                            _json_message(
                                "assistantResponseContext",
                                response_state,
                            ),
                            hidden_terms=hidden_terms,
                        ),
                    ),
                )
            continue
        message_id = _conversation_item_id(item)
        snapshot = (
            workspace_snapshots.get(message_id)
            if workspace_snapshots is not None and message_id is not None
            else None
        )
        snapshot_content = (
            snapshot.tools
            if snapshot is not None and mode == "tools"
            else (
                snapshot.streaming_final
                if snapshot is not None and mode == "streaming_final"
                else None
            )
        )
        if snapshot_content:
            entries.append(
                LlmUserMessage(
                    role="user",
                    content=_sanitized_text(
                        snapshot_content,
                        hidden_terms=hidden_terms,
                    ),
                ),
            )
        if text:
            entries.append(
                LlmUserMessage(
                    role="user",
                    content=_sanitized_text(text, hidden_terms=hidden_terms),
                ),
            )
        filenames = _conversation_item_filenames(item)
        if filenames:
            # Historical binary data is never replayed. This adjacent metadata
            # envelope preserves file identity for both attachment-only turns
            # and ordinary text+attachment turns without retaining bytes,
            # extracted excerpts, or provider-specific content blocks.
            entries.append(
                LlmUserMessage(
                    role="user",
                    content=_sanitized_text(
                        _json_message(
                            "historicalAttachments",
                            [{"filename": filename} for filename in filenames],
                        ),
                        hidden_terms=hidden_terms,
                    ),
                ),
            )

    return entries


def _sanitized_text(value: str, *, hidden_terms: tuple[str, ...]) -> str:
    sanitized = sanitize_agent_value(value, hidden_terms=hidden_terms)
    return sanitized if isinstance(sanitized, str) else ""


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


def _compact_source_reference(source: dict[str, Any]) -> dict[str, str]:
    """Keep citation identity across turns without replaying source content."""

    reference = {
        key: value.strip()
        for key in ("id", "title", "sourceType", "filename")
        for value in [source.get(key)]
        if isinstance(value, str) and value.strip()
    }
    source_type = reference.get("sourceType")
    url = source.get("url")
    if (
        source_type == "web"
        and isinstance(url, str)
        and url.strip().lower().startswith(("http://", "https://"))
    ):
        reference["url"] = url.strip()
    return reference


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


def _assistant_response_state(response: dict[str, Any]) -> dict[str, Any]:
    edits = response.get("edits")
    tools = response.get("tools")
    sources = response.get("sources")

    source_refs = [
        reference
        for source in (sources if isinstance(sources, list) else [])
        if isinstance(source, dict)
        for reference in [_compact_source_reference(source)]
        if reference
    ]

    state: dict[str, Any] = {}
    if isinstance(edits, list) and edits:
        state["editCount"] = len(edits)
        state["edits"] = _compact_response_edits(edits, token_budget=None)
    transaction_state = _string_value(response.get("transactionState"))
    if transaction_state:
        state["transactionState"] = transaction_state
    draft = response.get("draft")
    if isinstance(draft, dict):
        draft_status = _string_value(draft.get("status"))
        if draft_status:
            state["draftStatus"] = draft_status
    actions = _string_list(response.get("actions"))
    if actions:
        state["actions"] = actions
    if isinstance(tools, list) and tools:
        state["toolCount"] = len(tools)
    if isinstance(sources, list) and sources:
        state["sourceCount"] = len(sources)
    if source_refs:
        # Preserve compact citation identity across compression so later turns
        # can distinguish grounded evidence from unsupported recollection.
        state["sourceRefs"] = source_refs
    return state


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
            _compact_item_outline(item, section_kind=kind) for item in item_list[:3]
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
            compact_value if len(compact_value) <= 160 else f"{compact_value[:157]}..."
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

    for key in ("timedOut", "partial"):
        value = output.get(key)
        if isinstance(value, bool):
            context[key] = value

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
