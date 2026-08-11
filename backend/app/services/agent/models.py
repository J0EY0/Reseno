from dataclasses import dataclass
from typing import Literal

from app.schemas.agent import AgentToolState

FINISH_MISSING_ENUM = [
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
FINISH_MISSING_SET = set(FINISH_MISSING_ENUM)

TargetOpportunityKind = Literal[
    "employment",
    "graduate_study",
    "research",
    "scholarship",
    "general",
]


@dataclass(frozen=True)
class TargetReferenceSource:
    """One externally verifiable source and the excerpt taken from it."""

    title: str
    url: str | None
    excerpt: str


@dataclass(frozen=True)
class TargetReference:
    """Resolved target-opportunity context used by the agent plan."""

    mode: str
    kind: TargetOpportunityKind
    target: str
    query: str
    url: str | None
    excerpt: str
    exact_job_description: bool = False
    source_title: str = ""
    source_excerpt: str = ""
    tool_state: AgentToolState = "output-available"
    tool_error: str | None = None
    result_count: int = 0
    # Appended to preserve the positional order of the legacy single-source API.
    sources: tuple[TargetReferenceSource, ...] = ()


@dataclass(frozen=True)
class ResumeAnalysis:
    """Small, explicit analysis result for plan generation."""

    title: str
    summary: str
    sections: list[dict[str, object]]
    empty_section_ids: list[str]
    matched_keywords: list[str]
    missing_keywords: list[str]


@dataclass(frozen=True)
class EditPlanStep:
    """One executable step in a draft-editing flow."""

    action: str
    target: str
    reason: str
    intent: str = ""
