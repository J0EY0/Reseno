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
    assert "hide internal schema keys, record IDs/field paths" in AGENT_PROMPT


def test_agent_prompt_delegates_source_rendering_to_the_response_ui() -> None:
    assert "The response UI appends collected public sources once" in AGENT_PROMPT
    assert "manual sources section" in AGENT_PROMPT


def test_agent_prompt_treats_field_normalization_as_editing_judgment() -> None:
    assert "Normalize misplaced employer, title/location" in AGENT_PROMPT
    assert "without loss" in AGENT_PROMPT
    assert "keep each grounded fact once per item" in AGENT_PROMPT
    assert "Richness is coverage without repetition or new claims" in AGENT_PROMPT


def test_agent_prompt_keeps_the_edit_surface_and_project_facts_focused() -> None:
    assert "Use smallest edit surface" in AGENT_PROMPT
    assert "skip adjacent cleanup" in AGENT_PROMPT
    assert "requested counts limit rewrites, not requested normalization" in (
        AGENT_PROMPT
    )
    assert "description holds identity/scope" in AGENT_PROMPT
    assert "`techStack` normalized technology names" in AGENT_PROMPT
    assert "highlights distinct action/method contributions" in AGENT_PROMPT
    assert "Foreground action/method" in AGENT_PROMPT
    assert "only supported results/deliverables/constraints" in AGENT_PROMPT
    assert "Tie components/APIs/state/mechanisms to that contribution" in AGENT_PROMPT
    assert "Infer neither audience nor missing highlights" in AGENT_PROMPT
    assert "Public sources and application goals guide emphasis" in AGENT_PROMPT
    assert "not candidate/project facts, audience, or purpose" in AGENT_PROMPT


def test_agent_prompt_collects_and_preserves_material_facts_before_rewriting() -> None:
    assert "identity, action, method, deliverable, and result" in AGENT_PROMPT
    assert "Current-resume wording, including qualifiers" in AGENT_PROMPT
    assert "never weaken it unless the user disputes it" in AGENT_PROMPT
    assert "proof limits only new claims" in AGENT_PROMPT
    assert "Reorganize facts only within the same item by field meaning" in AGENT_PROMPT


def test_agent_prompt_requests_material_technical_evidence() -> None:
    assert "Technical labels do not prove contribution/action–method facts" in (
        AGENT_PROMPT
    )
    assert "If this blocks rewriting" in AGENT_PROMPT
    assert "ask one neutral contribution/method question" in AGENT_PROMPT
    assert "including role only in scope" in AGENT_PROMPT
    assert "Normalization cannot invent facts" in AGENT_PROMPT
    assert "Do not ask project type, launch/link, or code size" in AGENT_PROMPT
    assert "or results" not in AGENT_PROMPT


def test_agent_prompt_keeps_outcome_questions_optional_and_evidence_bound() -> None:
    assert "explicit enrichment/STAR" in AGENT_PROMPT
    assert "outcome/deliverable question is optional" in AGENT_PROMPT
    assert "missing verifiable evidence blocks rewriting" in AGENT_PROMPT
    assert "Offer no numbers or answers" in AGENT_PROMPT


def test_agent_prompt_preserves_technical_semantics_and_field_meaning() -> None:
    assert "Preserve technical terms and mechanism semantics" in AGENT_PROMPT
    assert "nearby concepts are not interchangeable" in AGENT_PROMPT


def test_agent_prompt_uses_current_target_research_without_a_workflow() -> None:
    assert "Research targets only when needed" in AGENT_PROMPT
    assert "Use tools when useful; no fixed order" in AGENT_PROMPT
    assert "Run independent reads together" in AGENT_PROMPT
    assert "await before dependent edits" in AGENT_PROMPT
    assert "fewest sufficient readable primary references" in AGENT_PROMPT
    assert "Search `references` are already read" in AGENT_PROMPT
    assert "never fetch their URLs" in AGENT_PROMPT
    assert "Stop when evidence is sufficient" in AGENT_PROMPT
    assert "Fetch candidates before use" in AGENT_PROMPT
    assert "preferred page is unreadable" in AGENT_PROMPT
    assert "instead of repeating equivalent searches" in AGENT_PROMPT
    assert "For edit requests, continue to `edit_execute`" in AGENT_PROMPT
    assert "advice/diagnosis stays text-only" in AGENT_PROMPT
    assert (
        "Match claims to source authority/recency; continue to `edit_execute`"
        not in AGENT_PROMPT
    )
    assert "repair only material in-scope gaps" in AGENT_PROMPT


def test_agent_prompt_creates_preview_only_drafts() -> None:
    assert "only creates or updates a pending preview" in AGENT_PROMPT
    assert "never applies or saves the formal resume" in AGENT_PROMPT
    assert "Never describe a draft without it" in AGENT_PROMPT
    assert "Batch compound requests" in AGENT_PROMPT
    assert "patch each item's fields together" in AGENT_PROMPT
    assert "repair rejected batches as batches" in AGENT_PROMPT


def test_agent_prompt_does_not_infer_results_from_features() -> None:
    assert "Feature/technology labels prove only themselves" in AGENT_PROMPT
    assert "never convert them into ownership, implementation" in AGENT_PROMPT
    assert "unlisted behavior" in AGENT_PROMPT
    assert (
        "Move technology from a known product-name field to `techStack`" in AGENT_PROMPT
    )


def test_agent_prompt_keeps_simple_rewriting_direct() -> None:
    assert (
        "For resume extraction, rewriting, normalization, formatting, or draft planning"
        in AGENT_PROMPT
    )
    assert "inventory facts and act directly" in AGENT_PROMPT
    assert "Do not turn broad editing into long analysis" in AGENT_PROMPT
    assert "Use deeper analysis only for research or consequential ambiguity" in (
        AGENT_PROMPT
    )
    assert "review/apply/discard" in AGENT_PROMPT
    assert "add no discovery question" in AGENT_PROMPT


def test_agent_prompt_does_not_duplicate_the_structured_edit_diff() -> None:
    assert "Successful edits already have structured UI diffs by field" in AGENT_PROMPT
    assert "Keep replies brief" in AGENT_PROMPT
    assert "result/caveat/needed question" in AGENT_PROMPT
    assert "avoid re-listing fields" in AGENT_PROMPT
    assert "review/apply/discard" in AGENT_PROMPT
    assert "summarize localized field labels" not in AGENT_PROMPT


def test_agent_prompt_groups_in_scope_skill_lists_by_semantics() -> None:
    assert "preserve rich-text list structure" in AGENT_PROMPT
    assert "For in-scope skill lists" in AGENT_PROMPT
    assert "group by meaning, not punctuation" in AGENT_PROMPT
    assert "keep related labels and qualifications together" in AGENT_PROMPT
    assert "repair clear merges" in AGENT_PROMPT
    assert "fit available space" in AGENT_PROMPT


def test_agent_prompt_treats_the_personal_summary_as_optional_space() -> None:
    assert "A personal summary is optional" in AGENT_PROMPT
    assert "do not add/rewrite it unless requested" in AGENT_PROMPT
    assert "In limited space prioritize grounded experience/project evidence" in (
        AGENT_PROMPT
    )
    assert "Leave it empty when empty" in AGENT_PROMPT
    assert "remove it when redundant" in AGENT_PROMPT
    assert "do not recap the resume" in AGENT_PROMPT


def test_agent_prompt_uses_star_as_grounded_employment_writing_judgment() -> None:
    assert "apply that inventory as invisible STAR/CAR" in AGENT_PROMPT
    assert "foreground concrete action and method" in AGENT_PROMPT
    assert "include supported results, deliverables, quality changes" in (AGENT_PROMPT)
    assert "Without outcome evidence, stop at action and method" in AGENT_PROMPT
    assert "never invent impact" in AGENT_PROMPT
    assert "Keep grounded contributions distinct" in AGENT_PROMPT
    assert "combine only facts about the same contribution" in AGENT_PROMPT
    assert "Richness is coverage without repetition or new claims" in AGENT_PROMPT
    assert "Never output STAR/CAR labels/templates/validators" in AGENT_PROMPT
