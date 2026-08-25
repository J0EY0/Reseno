from app.services.agent.contracts import OPERATION_SCHEMA
from app.services.agent.prompt import AGENT_PROMPT


def _operation_types() -> set[str]:
    return {
        branch["properties"]["type"]["const"] for branch in OPERATION_SCHEMA["oneOf"]
    }


def test_agent_prompt_stays_compact() -> None:
    assert len(AGENT_PROMPT) <= 4_500


def test_agent_prompt_keeps_only_model_visible_protocol_names() -> None:
    assert "workspaceContext" in AGENT_PROMPT
    assert "edit_execute" in AGENT_PROMPT
    assert "<citation" not in AGENT_PROMPT
    assert "source_ids" not in AGENT_PROMPT
    assert "keywordCoverageScore" not in AGENT_PROMPT
    assert all(name not in AGENT_PROMPT for name in _operation_types())


def test_agent_prompt_delegates_source_rendering_to_the_response_ui() -> None:
    assert (
        "The response UI presents collected public sources once at the end of "
        "the answer"
        in AGENT_PROMPT
    )
    assert "manual sources section" in AGENT_PROMPT


def test_agent_prompt_treats_field_normalization_as_editing_judgment() -> None:
    assert "Normalize misplaced employer, title/location" in AGENT_PROMPT
    assert "Normalize losslessly" in AGENT_PROMPT
    assert "retain each grounded fact exactly once within its item" in AGENT_PROMPT
    assert "when replacing fields" in AGENT_PROMPT
    assert "Richness is coverage without repetition or extra claims" in AGENT_PROMPT


def test_agent_prompt_keeps_the_edit_surface_and_project_facts_focused() -> None:
    assert "Choose the smallest edit surface" in AGENT_PROMPT
    assert "normalization is not adjacent cleanup" in AGENT_PROMPT
    assert "requested counts limit rewrites" in AGENT_PROMPT
    assert "description holds grounded identity/scope" in AGENT_PROMPT
    assert "`techStack` grounded normalized technology names" in AGENT_PROMPT
    assert "highlights grounded candidate contributions" in AGENT_PROMPT
    assert "Foreground action/method" in AGENT_PROMPT
    assert "add only supported results/deliverables/constraints" in AGENT_PROMPT
    assert "components/APIs/state/mechanisms only within such a contribution" in (
        AGENT_PROMPT
    )
    assert "Infer no audience" in AGENT_PROMPT
    assert "do not collapse empty highlights" in AGENT_PROMPT
    assert "Public sources and application goals guide emphasis" in AGENT_PROMPT
    assert "not candidate/project facts, audience, or purpose" in AGENT_PROMPT


def test_agent_prompt_collects_and_preserves_material_facts_before_rewriting() -> None:
    assert (
        "identity, action, method, feature/deliverable, and result"
        in AGENT_PROMPT
    )
    assert "Current-resume statements are candidate facts" in AGENT_PROMPT
    assert "never weaken them for lacking external proof" in AGENT_PROMPT
    assert "grounding limits only new claims" in AGENT_PROMPT
    assert "Reorganize facts only within the same item by field meaning" in AGENT_PROMPT


def test_agent_prompt_requests_material_technical_evidence() -> None:
    assert "For technical enrichment" in AGENT_PROMPT
    assert "labels are not contribution or action–method evidence" in AGENT_PROMPT
    assert "missing contribution or method facts materially block it" in (
        AGENT_PROMPT
    )
    assert "do not call `edit_execute`" in AGENT_PROMPT
    assert "ask one compact neutral question only for missing facts" in AGENT_PROMPT
    assert "including role only when in scope" in AGENT_PROMPT
    assert "Draft normalization does not bypass this" in AGENT_PROMPT
    assert "pure normalization remains direct" in AGENT_PROMPT
    assert "Do not propose factual answers or ask for project type" in AGENT_PROMPT
    assert "launch/link, code size, or results" in AGENT_PROMPT
    assert "neutral format guidance is allowed" in AGENT_PROMPT


def test_agent_prompt_preserves_technical_semantics_and_field_meaning() -> None:
    assert "Preserve exact technical terms and mechanism semantics" in AGENT_PROMPT
    assert "nearby concepts are not interchangeable" in AGENT_PROMPT


def test_agent_prompt_uses_current_target_research_without_a_workflow() -> None:
    assert "Research current target facts only when needed" in AGENT_PROMPT
    assert "Use tools only when useful; no fixed order" in AGENT_PROMPT
    assert "repair only a material gap in the requested scope" in AGENT_PROMPT


def test_agent_prompt_stops_research_and_creates_preview_only_drafts() -> None:
    assert "use stable search passages" in AGENT_PROMPT
    assert "fetch only missing detail" in AGENT_PROMPT
    assert "only creates or updates a pending preview" in AGENT_PROMPT
    assert "never applies or saves the formal resume" in AGENT_PROMPT
    assert "Never describe a draft without it" in AGENT_PROMPT


def test_agent_prompt_does_not_infer_results_from_features() -> None:
    assert "Feature/technology labels prove only themselves" in AGENT_PROMPT
    assert "never convert them into ownership, implementation" in AGENT_PROMPT
    assert "unlisted behavior" in AGENT_PROMPT
    assert "move technology occupying the project name to `techStack`" in (
        AGENT_PROMPT
    )


def test_agent_prompt_keeps_simple_rewriting_direct() -> None:
    assert (
        "For standalone grounded extraction, rewriting, normalization, or formatting"
        in AGENT_PROMPT
    )
    assert "Use deeper analysis when research, ambiguity, or trade-offs" in AGENT_PROMPT
    assert "do not append optional discovery questions after a successful draft" in (
        AGENT_PROMPT
    )


def test_agent_prompt_groups_in_scope_skill_lists_by_semantics() -> None:
    assert "For in-scope skill lists" in AGENT_PROMPT
    assert "group by meaning, not punctuation" in AGENT_PROMPT
    assert "keep related labels and qualifications together" in AGENT_PROMPT
    assert "repair clear merges" in AGENT_PROMPT
    assert "fit density to the content and space" in AGENT_PROMPT


def test_agent_prompt_treats_the_personal_summary_as_optional_space() -> None:
    assert "A personal summary is optional, not a default optimization target" in (
        AGENT_PROMPT
    )
    assert (
        "Spend limited page space first on grounded experience and project evidence"
        in AGENT_PROMPT
    )
    assert "Leave an empty summary empty" in AGENT_PROMPT
    assert "remove it when redundant" in AGENT_PROMPT
    assert "do not recap education, employers, projects, or skills" in AGENT_PROMPT


def test_agent_prompt_uses_star_as_grounded_employment_writing_judgment() -> None:
    assert "apply that inventory as invisible STAR/CAR" in AGENT_PROMPT
    assert "foreground concrete action and method" in AGENT_PROMPT
    assert "include supported results, deliverables, quality changes" in (
        AGENT_PROMPT
    )
    assert "Without outcome evidence, stop at action and method" in AGENT_PROMPT
    assert "never invent impact" in AGENT_PROMPT
    assert "Keep independent grounded contributions distinct" in AGENT_PROMPT
    assert "combine facts only when they describe the same contribution" in (
        AGENT_PROMPT
    )
    assert "Richness is coverage without repetition or extra claims" in AGENT_PROMPT
    assert "Never output STAR/CAR labels, templates, or validators" in AGENT_PROMPT
