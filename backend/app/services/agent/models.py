from dataclasses import dataclass

from app.schemas.agent import AgentToolState


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
