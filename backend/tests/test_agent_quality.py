import pytest

from app.schemas.agent import AgentResumeEditSuggestion
from app.services.agent.quality import blocking_quality_issues, draft_quality_issues


def _summary_edit() -> AgentResumeEditSuggestion:
    return AgentResumeEditSuggestion(
        id="edit-summary",
        title="Refine summary",
        target="basic.summary",
        reason="Keep the quality check on the public draft validation path.",
        operation={
            "type": "replace_field",
            "path": "basic.summary",
            "value": "Updated summary",
        },
    )


def _resume_with_items(*items: dict[str, object]) -> dict[str, object]:
    return {
        "basic": {"summary": "Updated summary"},
        "sections": [
            {
                "id": "work",
                "kind": "work",
                "items": list(items),
            },
        ],
    }


def test_full_resume_quality_blocks_invalid_period_format() -> None:
    resume = _resume_with_items(
        {
            "id": "work-1",
            "title": "Software Engineer",
            "period": "2024.13 - 2025.02",
        },
    )

    issues = draft_quality_issues(resume, [_summary_edit()])

    assert {issue["code"] for issue in blocking_quality_issues(issues)} == {
        "invalid_item_period",
    }


def test_full_resume_quality_blocks_inverted_period_range() -> None:
    resume = _resume_with_items(
        {
            "id": "work-1",
            "title": "Software Engineer",
            "period": "2025.02 - 2024.01",
        },
    )

    issues = draft_quality_issues(resume, [_summary_edit()])

    assert {issue["code"] for issue in blocking_quality_issues(issues)} == {
        "inverted_item_period",
    }


def test_full_resume_quality_blocks_non_reverse_chronological_items() -> None:
    resume = _resume_with_items(
        {
            "id": "work-older",
            "title": "Earlier Role",
            "period": "2021.01 - 2022.03",
        },
        {
            "id": "work-newer",
            "title": "Recent Role",
            "period": "2023.04 - Present",
        },
    )

    issues = draft_quality_issues(resume, [_summary_edit()])

    assert {issue["code"] for issue in blocking_quality_issues(issues)} == {
        "resume_items_not_reverse_chronological",
    }


@pytest.mark.parametrize(
    "period",
    [
        "2024.01 - Present",
        "2024.01–2025.02",
        "01/2024 - 03/2025",
        "Jan 2024 - March 2025",
        "Sep. 2024 - Mar. 2025",
        "2024年1月至今",
        "Spring 2024 - Present",
    ],
)
def test_full_resume_quality_accepts_common_unambiguous_period_formats(
    period: str,
) -> None:
    resume = _resume_with_items(
        {
            "id": "work-1",
            "title": "Software Engineer",
            "period": period,
        },
    )

    issues = draft_quality_issues(resume, [_summary_edit()])

    assert not {
        "invalid_item_period",
        "inverted_item_period",
    }.intersection(issue["code"] for issue in issues)


def test_full_resume_quality_warns_about_cross_section_semantic_duplicates() -> None:
    resume = {
        "basic": {"summary": "Updated summary"},
        "sections": [
            {
                "id": "work",
                "kind": "work",
                "items": [
                    {
                        "id": "work-1",
                        "title": "Engineer",
                        "highlights": [
                            "Built an automated resume review workflow that reduced "
                            "review time by 30 percent.",
                        ],
                    },
                ],
            },
            {
                "id": "project",
                "kind": "project",
                "items": [
                    {
                        "id": "project-1",
                        "title": "Resume assistant",
                        "highlights": [
                            "Developed an automated resume review workflow, reducing "
                            "review time by 30 percent.",
                        ],
                    },
                ],
            },
        ],
    }

    issues = draft_quality_issues(resume, [_summary_edit()])
    duplicate_issues = [
        issue
        for issue in issues
        if issue["code"] == "semantically_duplicate_resume_content"
    ]

    assert len(duplicate_issues) == 1
    assert duplicate_issues[0]["severity"] == "warning"
    assert duplicate_issues[0]["target"].startswith("sections.project")
    assert duplicate_issues[0]["duplicateOf"].startswith("sections.work")
    assert blocking_quality_issues(duplicate_issues) == []


def test_full_resume_quality_warns_about_same_section_semantic_duplicates() -> None:
    resume = _resume_with_items(
        {
            "id": "work-1",
            "highlights": [
                "Built a customer support dashboard that reduced response time by "
                "35 percent.",
            ],
        },
        {
            "id": "work-2",
            "highlights": [
                "Developed a customer support dashboard, reducing response time by "
                "35 percent.",
            ],
        },
    )

    issues = draft_quality_issues(resume, [_summary_edit()])

    assert (
        sum(
            issue["code"] == "semantically_duplicate_resume_content" for issue in issues
        )
        == 1
    )


def test_full_resume_quality_does_not_compare_fields_inside_one_item() -> None:
    claim = (
        "Built an automated resume review workflow that reduced review time "
        "by 30 percent."
    )
    resume = _resume_with_items(
        {
            "id": "work-1",
            "description": claim,
            "highlights": [claim],
        },
    )

    issues = draft_quality_issues(resume, [_summary_edit()])

    assert not any(
        issue["code"] == "semantically_duplicate_resume_content" for issue in issues
    )


def test_full_resume_quality_warns_about_mixed_substantive_languages() -> None:
    resume = {
        "basic": {"summary": "Updated summary"},
        "sections": [
            {
                "id": "work",
                "items": [
                    {
                        "id": "work-1",
                        "highlights": [
                            "Built a reliable release workflow and reduced deployment "
                            "failures across the engineering organization.",
                        ],
                    },
                ],
            },
            {
                "id": "project",
                "items": [
                    {
                        "id": "project-1",
                        "highlights": [
                            "设计并交付自动化评审流程，显著缩短团队处理反馈的时间。",
                        ],
                    },
                ],
            },
        ],
    }

    issues = draft_quality_issues(resume, [_summary_edit()])
    language_issues = [
        issue for issue in issues if issue["code"] == "mixed_resume_languages"
    ]

    assert language_issues == [
        {
            "code": "mixed_resume_languages",
            "severity": "warning",
            "target": "resume",
            "scope": "resume",
            "languageCounts": {"en": 1, "zh": 1},
        },
    ]
    assert blocking_quality_issues(language_issues) == []


def test_full_resume_quality_warns_about_present_tense_in_ended_role() -> None:
    resume = _resume_with_items(
        {
            "id": "work-1",
            "title": "Software Engineer",
            "period": "2021.01 - 2022.03",
            "highlights": [
                "Built a deployment workflow that reduced release failures.",
                "Manage cross-functional delivery for critical customer launches.",
            ],
        },
    )

    issues = draft_quality_issues(resume, [_summary_edit()])
    tense_issues = [
        issue for issue in issues if issue["code"] == "inconsistent_item_tense"
    ]

    assert len(tense_issues) == 1
    assert tense_issues[0]["severity"] == "warning"
    assert tense_issues[0]["target"] == "sections.work.items.work-1.highlights"
    assert tense_issues[0]["indexes"] == [1]
    assert blocking_quality_issues(tense_issues) == []


def test_full_resume_quality_allows_present_tense_in_current_role() -> None:
    resume = _resume_with_items(
        {
            "id": "work-1",
            "title": "Software Engineer",
            "period": "2023.04 - Present",
            "highlights": [
                "Manage cross-functional delivery for critical customer launches.",
            ],
        },
    )

    issues = draft_quality_issues(resume, [_summary_edit()])

    assert not any(issue["code"] == "inconsistent_item_tense" for issue in issues)


def test_target_coverage_runs_only_with_explicit_target_context() -> None:
    resume = _resume_with_items(
        {
            "id": "work-1",
            "title": "Backend Engineer",
            "highlights": [
                "Built Python APIs and improved service reliability.",
            ],
        },
    )

    without_target = draft_quality_issues(resume, [_summary_edit()])
    with_target = draft_quality_issues(
        resume,
        [_summary_edit()],
        target_context={
            "requirements": [
                "Python",
                "Kubernetes",
                "distributed systems",
            ],
        },
    )
    coverage_issues = [
        issue
        for issue in with_target
        if issue["code"] == "target_requirements_not_covered"
    ]

    assert not any(
        issue["code"] == "target_requirements_not_covered" for issue in without_target
    )
    assert coverage_issues == [
        {
            "code": "target_requirements_not_covered",
            "severity": "warning",
            "target": "resume",
            "scope": "target",
            "requirementCount": 3,
            "coveredCount": 1,
            "missingRequirementIndexes": [1, 2],
        },
    ]
    assert blocking_quality_issues(coverage_issues) == []


def test_target_coverage_does_not_warn_when_requirements_are_covered() -> None:
    resume = _resume_with_items(
        {
            "id": "work-1",
            "title": "Backend Engineer",
            "highlights": [
                "Built Python services for distributed systems deployed on Kubernetes.",
            ],
        },
    )

    issues = draft_quality_issues(
        resume,
        [_summary_edit()],
        target_context={
            "requirements": [
                "Python",
                "Kubernetes",
                "distributed systems",
            ],
        },
    )

    assert not any(
        issue["code"] == "target_requirements_not_covered" for issue in issues
    )


def test_target_coverage_does_not_match_english_requirement_inside_word() -> None:
    resume = _resume_with_items(
        {
            "id": "work-1",
            "title": "Backend Engineer",
            "highlights": ["Built Pythonic service abstractions."],
        },
    )

    issues = draft_quality_issues(
        resume,
        [_summary_edit()],
        target_context={"requirements": ["Python"]},
    )

    coverage_issue = next(
        issue for issue in issues if issue["code"] == "target_requirements_not_covered"
    )
    assert coverage_issue["missingRequirementIndexes"] == [0]
