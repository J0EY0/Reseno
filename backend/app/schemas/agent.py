from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.agent_locales import AgentLocale

AgentAction = Literal["summary", "bullet", "keywords", "plan", "execute"]
AgentTransactionState = Literal["none", "provisional", "committed", "rolled_back"]
AgentRunStatus = Literal["active", "completed", "cancelled", "failed"]
AgentFinishMissing = Literal[
    "pending_draft",
    "url_purpose",
    "resume_target",
    "draft_edit_target",
    "source_material",
    "target_role",
    "user_evidence",
    "explicit_delete_intent",
    "explicit_reorder_intent",
    "model_config",
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
    """One prior message in an agent conversation."""

    model_config = ConfigDict(populate_by_name=True)

    id: str | None = None
    role: Literal["user", "assistant"]
    text: str
    files: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str | None = Field(default=None, alias="createdAt")
    response: dict[str, Any] | None = None


class AgentDraftState(BaseModel):
    """Current frontend draft state carried into the agent loop."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    status: Literal["pending", "applied", "discarded"] = "pending"
    source_message_id: str | None = Field(default=None, alias="sourceMessageId")
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")
    resume: dict[str, Any] = Field(default_factory=dict)
    edit_count: int = Field(default=0, alias="editCount")
    edits: list[dict[str, Any]] = Field(default_factory=list)
    diffs: list[dict[str, Any]] = Field(default_factory=list)


class AgentChatRequest(BaseModel):
    """Request body for generating an agent resume-editing response."""

    model_config = ConfigDict(populate_by_name=True)

    resume_id: str | None = Field(default=None, alias="resumeId")
    prompt: str = ""
    message: AgentConversationItem | None = None
    messages: list[AgentConversationItem] = Field(default_factory=list)
    conversation: list[AgentConversationItem] = Field(default_factory=list)
    files: list[dict[str, Any]] = Field(default_factory=list)
    locale: AgentLocale = "zh"
    resume: dict[str, Any] = Field(default_factory=dict)
    job_brief: str = Field(default="", alias="jobBrief")
    keyword_match: dict[str, Any] = Field(default_factory=dict, alias="keywordMatch")
    applied_actions: list[str] = Field(default_factory=list, alias="appliedActions")
    draft_state: AgentDraftState | None = Field(default=None, alias="draftState")
    model_config_data: dict[str, Any] | None = Field(default=None, alias="modelConfig")
    settings: dict[str, Any] = Field(default_factory=dict)
    stream: bool = True


class AgentRunResponse(BaseModel):
    """Public state for one in-process Agent run."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    resume_id: str | None = Field(default=None, alias="resumeId")
    base_resume: dict[str, Any] = Field(default_factory=dict, alias="baseResume")
    status: AgentRunStatus
    last_event_id: int = Field(default=0, alias="lastEventId")


class AgentKnowledgeItem(BaseModel):
    """One knowledge item returned with an agent response."""

    title: str
    detail: str


class AgentSource(BaseModel):
    """One source used to generate an agent response."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    source_type: Literal[
        "resume",
        "jobBrief",
        "attachment",
        "web",
        "system",
    ] = Field(alias="sourceType")
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

    id: str
    title: str
    target: str
    reason: str
    replacement: str | None = None
    operation: dict[str, Any] | None = None
    status: Literal["planned", "executed", "rejected"] = "planned"


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
    reasoning: str = ""
    updates: list[str] = Field(default_factory=list)
    timeline: list[AgentTimelinePart] = Field(default_factory=list)
    plan: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    knowledge: list[AgentKnowledgeItem] = Field(default_factory=list)
    tools: list[AgentToolInvocation] = Field(default_factory=list)
    sources: list[AgentSource] = Field(default_factory=list)
    edits: list[AgentResumeEditSuggestion] = Field(default_factory=list)
    transaction_state: AgentTransactionState = Field(
        default="none",
        alias="transactionState",
    )
    finish_missing: list[AgentFinishMissing] = Field(
        default_factory=list,
        alias="finishMissing",
    )
    quick_replies: list[str] = Field(default_factory=list, alias="quickReplies")
    actions: list[AgentAction] = Field(default_factory=list)


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


class AgentSessionResponse(BaseModel):
    """Response body for a persisted Agent conversation."""

    resume_id: str = Field(alias="resumeId")
    revision: str
    messages: list[AgentStoredMessage] = Field(default_factory=list)


class AgentSessionReplaceRequest(BaseModel):
    """Request body for replacing one resume's persisted Agent conversation."""

    locale: AgentLocale = "zh"
    revision: str | None = None
    messages: list[AgentConversationItem] = Field(default_factory=list)
