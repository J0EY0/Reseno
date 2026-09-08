import json
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

from app.schemas.agent import AgentChatRequest, AgentConversationCheckpoint
from app.services.llm import (
    AgentLlmConfig,
    LlmRequestError,
    supports_native_attachment,
)
from app.services.llm.output_budget import (
    MIN_CONTEXT_INPUT_TOKENS,
    compaction_headroom_tokens,
    estimate_prompt_tokens,
    input_estimation_safety_tokens,
    shared_context_tokens,
)
from app.services.llm.types import (
    LlmContent,
    LlmContentPart,
    LlmInputMessage,
    LlmPrompt,
    LlmUserMessage,
)

from ..attachments import (
    AgentAttachmentError,
    attachment_content_part,
    attachment_text,
    current_request_attachments,
    load_agent_attachment,
)
from ..contracts import agent_tool_specs_for_request
from ..draft import DraftTransaction
from ..evidence import historical_prompt_evidence_ref
from ..localization import agent_text
from ..preferences import (
    execution_profile_for_request,
    execution_profile_prompt,
)
from ..privacy import (
    resume_hidden_terms,
    sanitize_agent_resume,
    sanitize_agent_text,
    sanitize_agent_value,
)
from ..prompt import AGENT_PROMPT
from .context import AgentContextWindowError

CONTEXT_COMPRESSION_RATIO = 0.85
CONTEXT_CHECKPOINT_TARGET_RATIO = 0.70
LATEST_TOOL_CONTENT_CHARS = 800
DEFAULT_ATTACHMENT_CONTEXT_TOKEN_BUDGET = 32_000
CHECKPOINT_CONTEXT_TOKEN_BUDGET = 1_200
CHECKPOINT_EVENT_TEXT_TOKEN_BUDGET = 192


def _current_prompt(request: AgentChatRequest) -> str:
    return request.message.text.strip()


def _agent_file_context(
    session_id: str,
    files: list[dict[str, Any]],
    *,
    hidden_terms: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    file_context: list[dict[str, str]] = []
    for file in files:
        content = attachment_text(session_id, file)
        if not content:
            continue
        filename = file.get("filename")
        media_type = file.get("mediaType")
        file_context.append(
            {
                "filename": sanitize_agent_text(
                    str(filename or "Attachment"),
                    hidden_terms=hidden_terms,
                ),
                "mediaType": str(media_type or ""),
                "excerpt": sanitize_agent_text(
                    content,
                    hidden_terms=hidden_terms,
                ).strip(),
            },
        )
    return file_context


@dataclass(frozen=True)
class _ContextBudget:
    """One shared context budget for compression and final validation."""

    input_tokens: int
    trigger_tokens: int
    compaction_headroom_tokens: int
    tool_schema_tokens: int
    safety_margin_tokens: int


@dataclass(frozen=True)
class _ConversationEntries:
    """Exact history envelopes and stable product-event prefix counts."""

    messages: list[LlmInputMessage]
    stable_prefix_message_counts: tuple[int, ...]
    source_message_counts: tuple[int, ...]


@dataclass(frozen=True)
class AgentPromptLimits:
    """Provider-independent input limits used by the compaction orchestrator."""

    input_tokens: int
    trigger_tokens: int
    target_tokens: int


class AgentPromptCompiler:
    """Prepare immutable turn material once and project exact history boundaries."""

    def __init__(
        self,
        request: AgentChatRequest,
        config: AgentLlmConfig,
        *,
        history_start_count: int = 0,
    ) -> None:
        self._request = request
        self._history_start_count = history_start_count
        tool_schema_tokens = _tool_schema_token_reserve(request, config)
        resume = DraftTransaction.from_request(request).active_resume
        self._hidden_terms = _request_hidden_terms(request, resume)
        context_files, binary_parts = _current_attachment_payload(
            request,
            config,
            tool_schema_tokens=tool_schema_tokens,
            hidden_terms=self._hidden_terms,
        )
        workspace = _workspace_context(request, resume, hidden_terms=self._hidden_terms)
        budget = _context_budget(config, tool_schema_tokens=tool_schema_tokens)
        state = {
            "currentDraft": _current_draft_state(
                request,
                token_budget=_state_token_budget(
                    budget.input_tokens if budget else None
                ),
            )
        }
        workspace["conversationState"] = sanitize_agent_value(
            state,
            hidden_terms=self._hidden_terms,
        )
        self._workspace_content = _json_message("workspaceContext", workspace)
        self._current_content = _current_turn_content(
            _sanitized_text(_current_prompt(request), hidden_terms=self._hidden_terms),
            context_files=context_files,
            binary_parts=binary_parts,
        )
        self._system_content = "\n\n".join(
            [
                AGENT_PROMPT,
                f"Current date: {date.today().isoformat()}.",
                execution_profile_prompt(execution_profile_for_request(request)),
            ]
        )
        self._entries = _conversation_entries(
            request.messages[history_start_count:],
            hidden_terms=self._hidden_terms,
        )
        self._checkpoint_events: list[dict[str, Any] | None] | None = None

    def build(
        self,
        checkpoint: AgentConversationCheckpoint | None = None,
    ) -> LlmPrompt:
        messages: list[LlmInputMessage] = [
            {"role": "system", "content": self._system_content},
        ]
        stable_counts: list[int] = []
        checkpoint_count = agent_checkpoint_message_count(self._request, checkpoint)
        if checkpoint_count < self._history_start_count:
            raise LlmRequestError("The conversation checkpoint boundary is invalid.")
        if checkpoint is not None:
            messages.append(
                {
                    "role": "user",
                    "content": _json_message(
                        "conversationCheckpoint",
                        _checkpoint_context_value(
                            checkpoint.summary,
                            hidden_terms=self._hidden_terms,
                        ),
                    ),
                }
            )
            stable_counts.append(len(messages))
        relative_count = checkpoint_count - self._history_start_count
        offset = (
            self._entries.source_message_counts[relative_count - 1]
            if relative_count
            else 0
        )
        exact_start = len(messages)
        messages.extend(self._entries.messages[offset:])
        stable_counts.extend(
            exact_start + count - offset
            for count in self._entries.stable_prefix_message_counts
            if count > offset
        )
        messages.extend(
            [
                {"role": "user", "content": self._workspace_content},
                {"role": "user", "content": self._current_content},
            ]
        )
        stable_counts.append(len(messages))
        return LlmPrompt(
            messages=messages,
            stable_prefix_message_counts=tuple(stable_counts),
        )

    def checkpoint_summary(self, end_count: int, token_budget: int) -> dict[str, Any]:
        if self._checkpoint_events is None:
            self._checkpoint_events = [
                _bounded_checkpoint_event(event)
                for event in agent_compaction_events(
                    self._request,
                    hidden_terms=self._hidden_terms,
                )
            ]
        return _checkpoint_context(self._checkpoint_events[:end_count], token_budget)


def _json_message(name: str, value: Any) -> str:
    return json.dumps({name: value}, ensure_ascii=False, separators=(",", ":"))


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


def _current_attachment_payload(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    *,
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

            if supports_native_attachment(config, attachment.media_type):
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
                    config, tool_schema_tokens=tool_schema_tokens
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


def _workspace_context(
    request: AgentChatRequest,
    resume: dict[str, Any],
    *,
    hidden_terms: tuple[str, ...],
) -> dict[str, Any]:
    workspace: dict[str, Any] = {
        "responseLanguage": _locale_name(request),
        "resume": sanitize_agent_resume(resume, hidden_terms=hidden_terms),
    }

    sanitized_workspace = sanitize_agent_value(workspace, hidden_terms=hidden_terms)
    return sanitized_workspace if isinstance(sanitized_workspace, dict) else {}


def _request_hidden_terms(
    request: AgentChatRequest,
    resume: dict[str, Any],
) -> tuple[str, ...]:
    """Hide identity known by either the saved resume or pending candidate.

    A pending draft can legitimately clear or replace a personal field. The
    saved value must still remain a hidden term for history, attachments, and
    the current prompt; otherwise choosing the draft as the active snapshot
    would accidentally reveal the value that was present in the base resume.
    """

    return resume_hidden_terms(request.resume, resume)


def _checkpoint_context_value(
    value: dict[str, Any],
    *,
    hidden_terms: tuple[str, ...],
) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        sanitize_agent_value(value, hidden_terms=hidden_terms),
    )


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


def agent_checkpoint_message_count(
    request: AgentChatRequest,
    checkpoint: AgentConversationCheckpoint | None,
) -> int:
    """Resolve the active checkpoint boundary against authoritative history."""

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
    hidden_terms: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Project history into bounded, untrusted checkpoint data."""

    events: list[dict[str, Any]] = []
    for item in request.messages:
        role = _conversation_item_role(item)
        message_id = _conversation_item_id(item)
        event: dict[str, Any] = {
            # This identifier is model-visible checkpoint data, so it must
            # cross the same privacy boundary as text.
            # Checkpoint selection separately keeps the untouched product ID.
            "id": (
                _sanitized_text(message_id, hidden_terms=hidden_terms)
                if message_id is not None
                else None
            ),
            "role": role,
        }
        if role == "user" and message_id is not None:
            event["evidenceRef"] = historical_prompt_evidence_ref(message_id)
        text = _conversation_item_text(item)
        if text:
            event["text"] = _sanitized_text(text, hidden_terms=hidden_terms)
        attachments = _conversation_item_attachment_metadata(item)
        if attachments:
            event["attachments"] = [
                {
                    key: _sanitized_text(
                        value,
                        hidden_terms=hidden_terms,
                    )
                    for key, value in attachment.items()
                }
                for attachment in attachments
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


def _checkpoint_context(
    events: list[dict[str, Any] | None],
    token_budget: int,
) -> dict[str, Any]:
    selected: list[dict[str, Any]] = []
    for bounded in reversed(events):
        if bounded is None:
            continue
        candidate = [bounded, *selected]
        payload = {"trust": "untrusted_history_data", "events": candidate}
        if _estimated_json_tokens(payload) > token_budget:
            continue
        selected = candidate
    return {"trust": "untrusted_history_data", "events": selected}


def _bounded_checkpoint_event(event: dict[str, Any]) -> dict[str, Any] | None:
    role = event.get("role")
    if role == "user":
        evidence_ref = event.get("evidenceRef")
        if not isinstance(evidence_ref, str) or not evidence_ref:
            return None
        bounded: dict[str, Any] = {
            "role": "user",
            "evidenceRef": evidence_ref,
        }
        text = event.get("text")
        if isinstance(text, str) and text:
            bounded["text"] = _truncate_to_tokens(
                text,
                CHECKPOINT_EVENT_TEXT_TOKEN_BUDGET,
            )
        attachments = event.get("attachments")
        if isinstance(attachments, list) and attachments:
            bounded["attachments"] = attachments[:4]
        return bounded

    if role != "assistant":
        return None
    bounded = {
        "role": "assistant",
        "messageId": event.get("id"),
    }
    text = event.get("text")
    if isinstance(text, str) and text:
        bounded["text"] = _truncate_to_tokens(
            text,
            CHECKPOINT_EVENT_TEXT_TOKEN_BUDGET,
        )
    state = event.get("assistantResponseContext")
    if isinstance(state, dict) and state:
        bounded_state = {
            key: value
            for key, value in state.items()
            if key not in {"edits", "sourceRefs"}
        }
        edits = state.get("edits")
        if isinstance(edits, list) and edits:
            bounded_state["edits"] = edits[:4]
        source_refs = state.get("sourceRefs")
        if isinstance(source_refs, list) and source_refs:
            bounded_state["sourceRefs"] = source_refs[:8]
        bounded["assistantResponseContext"] = bounded_state
    return (
        bounded if "text" in bounded or "assistantResponseContext" in bounded else None
    )


def agent_prompt_limits(
    request: AgentChatRequest,
    config: AgentLlmConfig,
) -> AgentPromptLimits | None:
    """Return the main prompt limits without exposing provider cache details."""

    budget = _context_budget(
        config, tool_schema_tokens=_tool_schema_token_reserve(request, config)
    )
    if budget is None:
        return None
    return AgentPromptLimits(
        input_tokens=budget.input_tokens,
        trigger_tokens=budget.trigger_tokens,
        target_tokens=max(
            1,
            int(
                (budget.input_tokens - budget.compaction_headroom_tokens)
                * CONTEXT_CHECKPOINT_TARGET_RATIO
            ),
        ),
    )


def estimate_agent_messages_tokens(messages: list[LlmInputMessage]) -> int:
    """Estimate text plus bounded native-media reserves, never base64 bytes."""

    return estimate_prompt_tokens(LlmPrompt(messages=messages))


def fit_agent_model_turn_prompt(
    request: AgentChatRequest,
    config: AgentLlmConfig,
    prompt: LlmPrompt,
) -> LlmPrompt:
    """Fit an appended tool transcript before one provider request.

    The durable conversation checkpoint is prepared before the loop. During
    the loop, only tool observations are appended, so old web passages are the
    only large disposable payload. Preserve tool-call/result pairing, source
    identity, the latest observation whenever it fits, and every stable prefix
    boundary.
    """

    limits = agent_prompt_limits(request, config)
    if limits is None:
        return prompt

    estimated_tokens = estimate_agent_messages_tokens(prompt.messages)
    if estimated_tokens <= limits.trigger_tokens:
        return prompt

    suffix_start = (
        prompt.stable_prefix_message_counts[-1]
        if prompt.stable_prefix_message_counts
        else 0
    )
    tool_indexes = [
        index
        for index, message in enumerate(prompt.messages[suffix_start:], suffix_start)
        if message["role"] == "tool"
    ]
    if not tool_indexes:
        if estimated_tokens > limits.input_tokens:
            raise _model_turn_context_window_error()
        return prompt

    messages = deepcopy(prompt.messages)
    latest_batch_start = max(
        (
            index
            for index, message in enumerate(messages)
            if index >= suffix_start
            and message["role"] == "assistant"
            and message.get("tool_calls")
        ),
        default=suffix_start,
    )
    earlier_tool_indexes = [
        index for index in tool_indexes if index < latest_batch_start
    ]
    latest_tool_indexes = [
        index for index in tool_indexes if index > latest_batch_start
    ]

    changed = False
    for index in earlier_tool_indexes:
        changed = _compact_tool_result_content(messages[index]) or changed
        if (
            changed
            and estimate_agent_messages_tokens(messages) <= limits.trigger_tokens
        ):
            return LlmPrompt(
                messages=messages,
                stable_prefix_message_counts=prompt.stable_prefix_message_counts,
            )

    estimated_tokens = estimate_agent_messages_tokens(messages)
    for index in latest_tool_indexes:
        if estimated_tokens <= limits.input_tokens:
            break
        changed = (
            _compact_tool_result_content(
                messages[index],
                content_chars=LATEST_TOOL_CONTENT_CHARS,
            )
            or changed
        )
        estimated_tokens = estimate_agent_messages_tokens(messages)
    if estimated_tokens > limits.input_tokens:
        raise _model_turn_context_window_error()
    if not changed:
        return prompt
    return LlmPrompt(
        messages=messages,
        stable_prefix_message_counts=prompt.stable_prefix_message_counts,
    )


def _compact_tool_result_content(
    message: LlmInputMessage,
    *,
    content_chars: int = 0,
) -> bool:
    if message["role"] != "tool":
        return False
    try:
        value = json.loads(message["content"])
    except (TypeError, json.JSONDecodeError):
        return False

    compacted = _compact_tool_result_value(value, content_chars=content_chars)
    if compacted == value:
        return False
    message["content"] = json.dumps(
        compacted,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return True


def _compact_tool_result_value(value: Any, *, content_chars: int) -> Any:
    if isinstance(value, list):
        return [
            _compact_tool_result_value(item, content_chars=content_chars)
            for item in value
        ]
    if not isinstance(value, dict):
        return value
    excerpt = value.get("excerpt")
    if isinstance(value.get("sourceId"), str):
        compacted = {
            key: value[key]
            for key in (
                "sourceId",
                "title",
                "url",
                "sourceKind",
                "publishedDate",
                "validThrough",
            )
            if key in value
        }
    else:
        compacted = {
            key: _compact_tool_result_value(item, content_chars=content_chars)
            for key, item in value.items()
            if key not in {"excerpt", "excerptBoundary"}
        }
    passages = value.get("passages")
    if content_chars > 0 and isinstance(passages, list):
        retained: list[dict[str, Any]] = []
        remaining = content_chars
        for passage in passages:
            if not isinstance(passage, dict):
                continue
            text = passage.get("text")
            if not isinstance(text, str) or not text:
                continue
            if remaining <= 0:
                compacted["passagesTruncated"] = True
                break
            retained.append({**passage, "text": text[:remaining]})
            if len(text) > remaining:
                compacted["passagesTruncated"] = True
            remaining -= len(retained[-1]["text"])
        if retained:
            compacted["passages"] = retained
    if content_chars > 0 and isinstance(excerpt, str) and excerpt:
        compacted["excerpt"] = excerpt[:content_chars]
        if len(excerpt) > content_chars:
            compacted["excerptTruncated"] = True
    return compacted


def _model_turn_context_window_error() -> AgentContextWindowError:
    return AgentContextWindowError(
        "Tool observations exceed the selected model context window. "
        "Narrow the current request or choose a model with a larger context window.",
    )


def _conversation_entries(
    conversation: list[Any],
    *,
    hidden_terms: tuple[str, ...],
) -> _ConversationEntries:
    entries: list[LlmInputMessage] = []
    stable_prefix_message_counts: list[int] = []
    source_message_counts: list[int] = []
    for item in conversation:
        item_entry_count = len(entries)
        role = _conversation_item_role(item)
        text = _conversation_item_text(item)
        response = _conversation_item_response(item) if role == "assistant" else None
        response_state = _assistant_response_state(response) if response else {}
        if role == "assistant":
            assistant_context: dict[str, Any] = {}
            if text:
                assistant_context["text"] = text
            if response_state:
                assistant_context.update(response_state)
            if assistant_context:
                assistant_context["messageId"] = _conversation_item_id(item)
                entries.append(
                    LlmUserMessage(
                        role="user",
                        content=_sanitized_text(
                            _json_message(
                                "assistantResponseContext",
                                assistant_context,
                            ),
                            hidden_terms=hidden_terms,
                        ),
                    ),
                )
            if len(entries) > item_entry_count:
                stable_prefix_message_counts.append(len(entries))
            source_message_counts.append(len(entries))
            continue
        message_id = _conversation_item_id(item)
        if text:
            sanitized_text = _sanitized_text(text, hidden_terms=hidden_terms)
            evidence_ref = (
                historical_prompt_evidence_ref(message_id)
                if message_id is not None
                else None
            )
            entries.append(
                LlmUserMessage(
                    role="user",
                    content=sanitized_text,
                ),
            )
            if evidence_ref is not None:
                # The plain historical turn is byte-identical to the current
                # turn that the provider saw originally. Mark that cacheable
                # boundary before appending new evidence metadata, then bind
                # the opaque reference to the immediately preceding user text.
                stable_prefix_message_counts.append(len(entries))
                entries.append(
                    LlmUserMessage(
                        role="user",
                        content=_json_message(
                            "historicalUserEvidence",
                            {
                                "appliesToPreviousUserMessage": True,
                                "evidenceRef": evidence_ref,
                            },
                        ),
                    ),
                )
        attachments = _conversation_item_attachment_metadata(item)
        if attachments:
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
                            attachments,
                        ),
                        hidden_terms=hidden_terms,
                    ),
                ),
            )
        if len(entries) > item_entry_count:
            stable_prefix_message_counts.append(len(entries))

        source_message_counts.append(len(entries))

    return _ConversationEntries(
        messages=entries,
        stable_prefix_message_counts=tuple(stable_prefix_message_counts),
        source_message_counts=tuple(source_message_counts),
    )


def _sanitized_text(value: str, *, hidden_terms: tuple[str, ...]) -> str:
    sanitized = sanitize_agent_value(value, hidden_terms=hidden_terms)
    return sanitized if isinstance(sanitized, str) else ""


def _conversation_item_attachment_metadata(
    item: Any,
) -> list[dict[str, str]]:
    files = item.get("files") if isinstance(item, dict) else getattr(item, "files", [])
    if not isinstance(files, list):
        return []

    attachments: list[dict[str, str]] = []
    for file in files:
        metadata = {
            key: value.strip()
            for key in ("id", "filename", "kind")
            for value in [
                file.get(key) if isinstance(file, dict) else getattr(file, key, None)
            ]
            if isinstance(value, str) and value.strip()
        }
        if metadata and metadata not in attachments:
            attachments.append(metadata)
    return attachments


def _compact_source_reference(source: dict[str, Any]) -> dict[str, str]:
    """Keep source identity across turns without replaying source content."""

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

    pending_review_items = [
        item for item in draft.review_items if item.status == "pending"
    ]
    pending_edit_ids = {
        edit_id for item in pending_review_items for edit_id in item.edit_ids
    }
    pending_edits = [
        edit
        for edit in draft.edits
        if isinstance(edit, dict) and edit.get("id") in pending_edit_ids
    ]
    pending_diffs = [
        diff
        for diff in draft.diffs
        if isinstance(diff, dict) and diff.get("operationId") in pending_edit_ids
    ]
    state: dict[str, Any] = {
        "id": draft.id,
        "sourceMessageId": draft.source_message_id,
        "pendingCount": len(pending_review_items),
        "edits": [],
        "diffs": [],
    }
    collections = (
        ("edits", _compact_response_edits(pending_edits, token_budget=None)),
        ("diffs", _compact_draft_diffs(pending_diffs)),
    )
    for key, values in collections:
        for value in values:
            candidate = {**state, key: [*state[key], value]}
            if (
                token_budget is not None
                and _estimated_json_tokens(candidate) > token_budget
            ):
                break
            state = candidate
    return state


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
    draft = response.get("draft")
    if isinstance(draft, dict):
        review_items = draft.get("reviewItems")
        review_items = review_items if isinstance(review_items, list) else []
        review_counts = {
            status: sum(
                1
                for item in review_items
                if isinstance(item, dict) and item.get("status") == status
            )
            for status in ("pending", "applied", "discarded", "superseded")
        }
        pending_edit_ids: set[str] = set()
        for item in review_items:
            if not isinstance(item, dict) or item.get("status") != "pending":
                continue
            edit_ids = item.get("editIds")
            if isinstance(edit_ids, list):
                pending_edit_ids.update(
                    edit_id for edit_id in edit_ids if isinstance(edit_id, str)
                )
        pending_edits = [
            edit
            for edit in (edits if isinstance(edits, list) else [])
            if isinstance(edit, dict) and edit.get("id") in pending_edit_ids
        ]
        state["draftReview"] = {
            "pendingCount": review_counts["pending"],
            "appliedCount": review_counts["applied"],
            "discardedCount": review_counts["discarded"],
            "supersededCount": review_counts["superseded"],
        }
        if pending_edits:
            state["pendingEditCount"] = len(pending_edits)
            state["edits"] = _compact_response_edits(
                pending_edits,
                token_budget=None,
            )
    elif isinstance(edits, list) and edits:
        state["editCount"] = len(edits)
        state["edits"] = _compact_response_edits(edits, token_budget=None)
    transaction_state = _string_value(response.get("transactionState"))
    if transaction_state:
        state["transactionState"] = transaction_state
    if isinstance(tools, list) and tools:
        state["toolCount"] = len(tools)
    if isinstance(sources, list) and sources:
        state["sourceCount"] = len(sources)
    if source_refs:
        # Preserve compact source identity across compression so later turns
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

        if diff:
            diffs.append(diff)

    return diffs


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
    config: AgentLlmConfig,
    *,
    tool_schema_tokens: int,
) -> _ContextBudget | None:
    window_tokens = _context_window_tokens(config)
    shared_window = shared_context_tokens(config)
    if shared_window is not None:
        window_tokens = (
            min(window_tokens, shared_window) if window_tokens else shared_window
        )
    if window_tokens is None:
        return None

    # Dispatch and the deterministic context transform use the same bounded
    # estimator reserve. A prepared prompt must remain valid when the concrete
    # provider request is assembled.
    safety_margin_tokens = input_estimation_safety_tokens(window_tokens)
    input_tokens = (
        window_tokens
        - tool_schema_tokens
        - safety_margin_tokens
        - (1 if shared_window is not None else 0)
    )
    if input_tokens <= 0:
        raise AgentContextWindowError(
            "The selected model context window is too small after reserving "
            "tool definitions and runtime input-estimation safety margin.",
        )

    # The 16K value is product headroom for earlier context folding, not provider
    # output context. Preserve it where possible without reducing the hard
    # accepted-input ceiling or leaving less than a useful 4K planning region.
    compaction_headroom = min(
        compaction_headroom_tokens(config),
        max(0, input_tokens - MIN_CONTEXT_INPUT_TOKENS),
    )
    compaction_input_tokens = input_tokens - compaction_headroom

    return _ContextBudget(
        input_tokens=input_tokens,
        trigger_tokens=max(
            1,
            int(compaction_input_tokens * CONTEXT_COMPRESSION_RATIO),
        ),
        compaction_headroom_tokens=compaction_headroom,
        tool_schema_tokens=tool_schema_tokens,
        safety_margin_tokens=safety_margin_tokens,
    )


def _context_input_budget_tokens(
    config: AgentLlmConfig,
    *,
    tool_schema_tokens: int = 0,
) -> int | None:
    budget = _context_budget(config, tool_schema_tokens=tool_schema_tokens)
    return budget.input_tokens if budget else None


def _attachment_context_token_budget(
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
        config, tool_schema_tokens=tool_schema_tokens
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
        raise AgentContextWindowError(
            "The attached document is too large for the selected model context.",
        )
    return files


def _context_window_tokens(config: AgentLlmConfig) -> int | None:
    if config.context_window_tokens and config.context_window_tokens > 0:
        return config.context_window_tokens

    return None


def _tool_schema_token_reserve(
    request: AgentChatRequest,
    config: AgentLlmConfig,
) -> int:
    """Estimate only schemas exposed to the model for this turn."""

    if not config.supports_tools:
        return 0

    schemas = [
        spec.schema
        for spec in agent_tool_specs_for_request(
            request,
            include_web_tools=not config.use_native_web_search,
        )
    ]
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


def _locale_name(request: AgentChatRequest) -> str:
    return agent_text(request.locale, "locale.name")
