from dataclasses import dataclass

from app.schemas.agent import AgentToolState

PLAN_INTENT_ENUM = [
    "rewrite_summary",
    "rewrite_item",
    "insert_item",
    "insert_section",
    "move_item",
    "split_item",
    "merge_items",
    "classify_skills",
    "delete_item",
    "delete_section",
    "reorder_items",
    "reorder_sections",
]
PLAN_INTENT_SET = set(PLAN_INTENT_ENUM)

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


@dataclass(frozen=True)
class JobReference:
    """Resolved JD context used by the agent plan."""

    mode: str
    role: str
    query: str
    url: str | None
    excerpt: str
    source_title: str = ""
    source_excerpt: str = ""
    tool_state: AgentToolState = "output-available"
    tool_error: str | None = None
    result_count: int = 0


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
