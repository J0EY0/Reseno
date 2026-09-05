from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_core import PydanticCustomError

from app.agent_locales import AgentLocale
from app.schemas.agent_settings import AgentExecutionProfile
from app.schemas.resumes import (
    RESUME_ID_PATTERN,
    ResumeDetailResponse,
    is_valid_resume_id,
)

AgentDraftDecisionStatus = Literal["applied", "discarded"]
AgentDraftReviewItemStatus = Literal["pending", "applied", "discarded"]
AgentTransactionState = Literal["none", "provisional", "committed", "rolled_back"]
AgentRunStatus = Literal["active", "completed", "cancelled", "failed"]
AgentTurnExecutionStatus = Literal["running", "succeeded", "failed", "cancelled"]
AgentTurnErrorCode = Literal[
    "AGENT_PROVIDER_AUTH_ERROR",
    "AGENT_PROVIDER_ERROR",
    "AGENT_PROVIDER_TIMEOUT",
    "AGENT_INTERNAL_ERROR",
    "AGENT_RUN_CANCELLED",
    "AGENT_EDIT_TRANSACTION_INCOMPLETE",
]
AgentToolState = Literal[
    "input-streaming",
    "input-available",
    "output-available",
    "output-error",
    "approval-requested",
    "approval-responded",
    "output-denied",
]


class AgentAttachmentResponse(BaseModel):
    """Backend-owned attachment reference safe to persist in chat history."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    filename: str
    media_type: str = Field(alias="mediaType")
    kind: Literal["text", "image"]


class AgentConversationItem(BaseModel):
    """One user or assistant message in an Agent conversation."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    role: Literal["user", "assistant"]
    text: str
    files: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str | None = Field(default=None, alias="createdAt")
    response: dict[str, Any] | None = None


class AgentDraftReviewItem(BaseModel):
    """One independently resolvable group of ordered resume edits."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str = Field(min_length=1)
    edit_ids: list[str] = Field(alias="editIds", min_length=1)
    status: AgentDraftReviewItemStatus = "pending"

    @model_validator(mode="after")
    def require_canonical_ids(self) -> "AgentDraftReviewItem":
        if self.id != self.id.strip() or any(
            not edit_id.strip() or edit_id != edit_id.strip()
            for edit_id in self.edit_ids
        ):
            raise PydanticCustomError(
                "agent_draft_review_item_id_invalid",
                "Review item and edit ids must be canonical non-empty strings.",
            )
        if len(self.edit_ids) != len(set(self.edit_ids)):
            raise PydanticCustomError(
                "agent_draft_review_item_edit_ids_duplicate",
                "A review item cannot contain duplicate edit ids.",
            )
        return self


def _validate_review_item_collection(
    review_items: list[AgentDraftReviewItem],
) -> None:
    item_ids = [item.id for item in review_items]
    edit_ids = [edit_id for item in review_items for edit_id in item.edit_ids]
    if len(item_ids) != len(set(item_ids)) or len(edit_ids) != len(set(edit_ids)):
        raise PydanticCustomError(
            "agent_draft_review_items_overlap",
            "Review item ids must be unique and each edit must belong to one item.",
        )


class AgentDraftState(BaseModel):
    """Current frontend draft state carried into the agent loop."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    id: str
    source_message_id: str | None = Field(default=None, alias="sourceMessageId")
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    resume: dict[str, Any] = Field(default_factory=dict)
    pending_count: int = Field(alias="pendingCount", ge=1)
    review_items: list[AgentDraftReviewItem] = Field(
        alias="reviewItems",
        min_length=1,
    )
    edits: list[dict[str, Any]] = Field(default_factory=list)
    diffs: list[dict[str, Any]] = Field(default_factory=list)
    transaction_state: AgentTransactionState | None = Field(
        default=None,
        alias="transactionState",
    )

    @model_validator(mode="after")
    def require_consistent_pending_items(self) -> "AgentDraftState":
        _validate_review_item_collection(self.review_items)
        pending_count = sum(
            item.status == "pending" for item in self.review_items
        )
        if pending_count != self.pending_count:
            raise PydanticCustomError(
                "agent_draft_pending_count_invalid",
                "pendingCount must match the unresolved review item count.",
            )
        return self


class AgentCommittedDraft(BaseModel):
    """Durable review state bound to one committed assistant response."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    base_resume: dict[str, Any] = Field(alias="baseResume")
    review_items: list[AgentDraftReviewItem] = Field(
        alias="reviewItems",
        min_length=1,
    )

    @model_validator(mode="after")
    def require_distinct_review_items(self) -> "AgentCommittedDraft":
        _validate_review_item_collection(self.review_items)
        return self


class AgentConversationCheckpoint(BaseModel):
    """Durable bounded context through one authoritative product message.

    The exact tail is deliberately not persisted here. It is always rebuilt
    from SQLite after ``through_message_id`` so the conversation has one
    authoritative transcript instead of a checkpoint-owned duplicate.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    through_message_id: str = Field(alias="throughMessageId", min_length=1)
    summary: dict[str, Any] = Field(min_length=1)


class AgentModelSelection(BaseModel):
    """ID-only model-config reference accepted from the Agent client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_canonical_id(self) -> "AgentModelSelection":
        """Reject blank or padded ids instead of resolving them as defaults."""

        if not self.id.strip() or self.id != self.id.strip():
            raise PydanticCustomError(
                "agent_model_config_id_invalid",
                "modelConfig.id must be non-empty and contain no surrounding "
                "whitespace.",
            )
        return self


class AgentChatRequest(BaseModel):
    """A singular current user turn plus prior-only conversation history."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    resume_id: str | None = Field(
        default=None,
        alias="resumeId",
        json_schema_extra={"pattern": RESUME_ID_PATTERN.pattern},
    )
    expected_revision: str | None = Field(
        default=None,
        alias="expectedRevision",
        min_length=1,
    )
    message: AgentConversationItem
    messages: list[AgentConversationItem] = Field(default_factory=list)
    locale: AgentLocale = "zh"
    resume: dict[str, Any] = Field(default_factory=dict)
    draft_state: AgentDraftState | None = Field(default=None, alias="draftState")
    model_selection: AgentModelSelection | None = Field(
        default=None,
        alias="modelConfig",
    )
    execution_profile: AgentExecutionProfile | None = Field(
        default=None,
        exclude=True,
        repr=False,
    )
    stream: bool = True

    @model_validator(mode="after")
    def require_revision_for_persisted_session(self) -> "AgentChatRequest":
        """Require optimistic ownership whenever chat targets a resume session."""

        if self.resume_id is not None and not is_valid_resume_id(self.resume_id):
            raise PydanticCustomError(
                "agent_resume_id_invalid",
                "resumeId must contain only ASCII letters and numbers.",
            )
        if self.resume_id is not None and self.expected_revision is None:
            raise PydanticCustomError(
                "agent_session_revision_required",
                "expectedRevision is required when resumeId is provided.",
            )
        return self

    @model_validator(mode="after")
    def require_canonical_current_message(self) -> "AgentChatRequest":
        """Keep the current turn singular, identifiable, and user-authored."""

        if self.message.role != "user":
            raise PydanticCustomError(
                "agent_current_message_role_invalid",
                "message.role must be user.",
            )

        message_id = self.message.id
        if not message_id or message_id != message_id.strip():
            raise PydanticCustomError(
                "agent_current_message_id_invalid",
                "message.id must be non-empty and contain no surrounding whitespace.",
            )

        if not self.message.text.strip() and not self.message.files:
            raise PydanticCustomError(
                "agent_current_message_content_required",
                "message must contain text or at least one file.",
            )

        if self.message.response is not None:
            raise PydanticCustomError(
                "agent_current_message_response_forbidden",
                "A user message cannot contain an assistant response.",
            )

        if any(message.id == message_id for message in self.messages):
            raise PydanticCustomError(
                "agent_current_message_in_history",
                "messages must contain only turns before message.",
            )

        return self


class AgentModelSnapshot(BaseModel):
    """Non-secret model identity captured when an Agent run is accepted."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid", frozen=True)

    config_id: str = Field(alias="configId", min_length=1)
    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)


class AgentRunResponse(BaseModel):
    """Public state for one in-process Agent run."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    resume_id: str | None = Field(default=None, alias="resumeId")
    base_resume: dict[str, Any] = Field(default_factory=dict, alias="baseResume")
    status: AgentRunStatus
    execution_state: AgentTurnExecutionStatus = Field(alias="executionState")
    error_code: AgentTurnErrorCode | None = Field(default=None, alias="errorCode")
    last_event_id: int = Field(default=0, alias="lastEventId")


class AgentSource(BaseModel):
    """One source used to generate an agent response."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    source_type: Literal["attachment", "web"] = Field(
        alias="sourceType",
    )
    url: str | None = None
    excerpt: str | None = None


class AgentToolInvocation(BaseModel):
    """One tool invocation returned with an agent response."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    type: str
    title: str
    state: AgentToolState
    input: dict[str, Any] | list[Any] | str | int | float | bool | None = None
    output: dict[str, Any] | list[Any] | str | int | float | bool | None = None
    error_text: str | None = Field(default=None, alias="errorText")
    started_at: str | None = Field(default=None, alias="startedAt")
    completed_at: str | None = Field(default=None, alias="completedAt")


class AgentResumeEditSuggestion(BaseModel):
    """One suggested resume edit returned by the agent."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    target: str
    reason: str
    replacement: str | None = None
    operation: dict[str, Any] | None = None
    evidence_refs: list[str] = Field(default_factory=list, alias="evidenceRefs")
    status: Literal["planned", "executed", "rejected"] = "planned"
    diffs: list[dict[str, Any]] = Field(default_factory=list)


class AgentTimelinePart(BaseModel):
    """One ordered visible part in an assistant response timeline."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    type: Literal["text", "tool_group"]
    text: str = ""
    tool_ids: list[str] = Field(default_factory=list, alias="toolIds")


class AgentChatMessage(BaseModel):
    """Structured assistant message returned to the frontend."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    role: Literal["assistant"]
    tone: Literal["default", "success"] | None = "default"
    text: str
    timeline: list[AgentTimelinePart] = Field(default_factory=list)
    tools: list[AgentToolInvocation] = Field(default_factory=list)
    sources: list[AgentSource] = Field(default_factory=list)
    edits: list[AgentResumeEditSuggestion] = Field(default_factory=list)
    draft: AgentCommittedDraft | None = None
    transaction_state: AgentTransactionState = Field(
        default="none",
        alias="transactionState",
    )

    @model_validator(mode="after")
    def require_draft_reviews_cover_edits(self) -> "AgentChatMessage":
        if self.draft is None:
            return self

        edit_ids = [edit.id for edit in self.edits]
        edit_positions = {edit_id: index for index, edit_id in enumerate(edit_ids)}
        review_edit_ids = [
            edit_id
            for item in self.draft.review_items
            for edit_id in item.edit_ids
        ]
        if (
            len(edit_positions) != len(edit_ids)
            or set(review_edit_ids) != set(edit_ids)
        ):
            raise PydanticCustomError(
                "agent_draft_review_edit_coverage_invalid",
                "Draft review items must cover every message edit exactly once.",
            )

        item_positions = [
            [edit_positions[edit_id] for edit_id in item.edit_ids]
            for item in self.draft.review_items
        ]
        if any(positions != sorted(positions) for positions in item_positions) or [
            positions[0] for positions in item_positions
        ] != sorted(positions[0] for positions in item_positions):
            raise PydanticCustomError(
                "agent_draft_review_edit_order_invalid",
                "Draft review items must preserve message edit order.",
            )
        return self


class AgentChatResponse(BaseModel):
    """Response body for agent chat requests."""

    message: AgentChatMessage


class AgentStoredMessage(BaseModel):
    """One persisted message loaded back into the frontend Agent panel."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    role: Literal["user", "assistant"]
    text: str
    files: list[dict[str, Any]] = Field(default_factory=list)
    response: AgentChatMessage | None = None
    created_at: str = Field(alias="createdAt")


class AgentTurnExecution(BaseModel):
    """Durable lifecycle state for one accepted user turn execution."""

    model_config = ConfigDict(populate_by_name=True)

    run_id: str = Field(alias="runId")
    turn_id: str = Field(alias="turnId")
    status: AgentTurnExecutionStatus
    error_code: AgentTurnErrorCode | None = Field(default=None, alias="errorCode")
    model_snapshot: AgentModelSnapshot | None = Field(alias="modelSnapshot")
    started_at: str = Field(alias="startedAt")
    completed_at: str | None = Field(default=None, alias="completedAt")


class AgentSessionResponse(BaseModel):
    """Response body for a persisted Agent conversation."""

    resume_id: str = Field(alias="resumeId")
    revision: str
    messages: list[AgentStoredMessage] = Field(default_factory=list)
    executions: list[AgentTurnExecution] = Field(default_factory=list)


class AgentSessionReplaceRequest(BaseModel):
    """Request body for replacing one resume's persisted Agent conversation."""

    locale: AgentLocale = "zh"
    revision: str = Field(min_length=1)
    messages: list[AgentConversationItem] = Field(default_factory=list)


class AgentDraftDecisionRequest(BaseModel):
    """Optimistic decision plus the document committed by an apply."""

    model_config = ConfigDict(extra="forbid", strict=True)

    revision: str = Field(min_length=1)
    status: AgentDraftDecisionStatus
    review_item_ids: list[str] = Field(alias="reviewItemIds", min_length=1)
    resume: dict[str, Any] | None = None
    expected_version_id: str | None = Field(
        default=None,
        alias="expectedVersionId",
        min_length=1,
    )

    @model_validator(mode="after")
    def require_resume_only_for_apply(self) -> "AgentDraftDecisionRequest":
        if self.status == "applied" and (
            self.resume is None or self.expected_version_id is None
        ):
            raise PydanticCustomError(
                "agent_draft_apply_resume_required",
                "resume and expectedVersionId are required when applying a draft.",
            )
        if self.status == "discarded" and (
            self.resume is not None or self.expected_version_id is not None
        ):
            raise PydanticCustomError(
                "agent_draft_discard_resume_forbidden",
                "resume and expectedVersionId are not accepted "
                "when discarding a draft.",
            )
        return self


class AgentDraftDecisionResponse(BaseModel):
    """Authoritative session plus the resume committed by an apply."""

    session: AgentSessionResponse
    resume: ResumeDetailResponse | None = None
