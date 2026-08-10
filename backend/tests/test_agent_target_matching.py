import pytest

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
    AgentTargetContext,
)
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.target_matching import match_resume_to_target


def _resume_with_skills(*skills: str) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "basic": {
            "name": "Candidate",
            "headline": "Frontend Engineer",
            "phone": "",
            "email": "",
            "location": "",
            "avatar": "",
            "summary": "",
            "customFields": [],
        },
        "sections": [
            {
                "id": "projects",
                "kind": "project",
                "title": "Projects",
                "items": [
                    {
                        "id": "project-1",
                        "name": "ResuMate",
                        "role": "Maintainer",
                        "techStack": list(skills),
                        "period": "",
                        "url": "",
                        "description": "",
                        "highlights": [],
                    }
                ],
            }
        ],
    }


def test_unicode_separated_target_skills_match_explicit_resume_skills() -> None:
    result = match_resume_to_target(
        _resume_with_skills("React", "TypeScript", "Node.js", "Tailwind CSS"),
        AgentTargetContext(
            mustHaveSkills=[
                "React、TypeScript、Node.js、Tailwind CSS",
            ],
        ),
    )

    assert result.matched == ("react", "typescript", "node.js", "tailwind css")
    assert result.missing == ()
    assert result.score == 100


def test_common_skill_aliases_share_one_canonical_keyword() -> None:
    result = match_resume_to_target(
        _resume_with_skills("TypeScript", "Node.js"),
        AgentTargetContext(mustHaveSkills=["TS", "NodeJS"]),
    )

    assert result.matched == ("typescript", "node.js")
    assert result.missing == ()
    assert result.score == 100


def test_short_technical_keywords_and_ci_cd_are_preserved() -> None:
    result = match_resume_to_target(
        _resume_with_skills("Go", "C#", "AI", "ML", "UI", "UX", "QA", "CI/CD"),
        AgentTargetContext(
            mustHaveSkills=["Go、C#、AI、ML、UI、UX、QA、CI/CD"],
        ),
    )

    assert result.matched == ("go", "c#", "ai", "ml", "ui", "ux", "qa", "ci/cd")
    assert result.missing == ()
    assert result.score == 100


def test_long_explicit_chinese_requirement_matches_identical_resume_text() -> None:
    result = match_resume_to_target(
        _resume_with_skills("大规模前端微服务架构"),
        AgentTargetContext(mustHaveSkills=["大规模前端微服务架构"]),
    )

    assert result.matched == ("大规模前端微服务架构",)
    assert result.missing == ()
    assert result.score == 100


@pytest.mark.parametrize("target_skill", ("性能优化", "大型分布式架构"))
def test_chinese_target_skill_matches_complete_resume_substring(
    target_skill: str,
) -> None:
    result = match_resume_to_target(
        _resume_with_skills("负责大型分布式架构和高并发系统性能优化"),
        AgentTargetContext(mustHaveSkills=[target_skill]),
    )

    assert result.matched == (target_skill,)
    assert result.missing == ()
    assert result.score == 100


def test_chinese_target_skill_rejects_partial_character_overlap() -> None:
    result = match_resume_to_target(
        _resume_with_skills("负责优化流程"),
        AgentTargetContext(mustHaveSkills=["性能优化"]),
    )

    assert result.matched == ()
    assert result.missing == ("性能优化",)
    assert result.score == 0


def test_natural_chinese_job_description_extracts_requirement_phrases() -> None:
    result = match_resume_to_target(
        _resume_with_skills("负责大型分布式架构和高并发系统性能优化"),
        AgentTargetContext(
            description="任职要求：熟悉性能优化，具备大型分布式架构经验。",
        ),
    )

    assert result.matched == ("性能优化", "大型分布式架构")
    assert result.missing == ()
    assert result.score == 100


def test_structured_requirements_are_not_duplicated_by_natural_description() -> None:
    result = match_resume_to_target(
        _resume_with_skills("负责大型分布式架构和高并发系统性能优化"),
        AgentTargetContext(
            requirements=["性能优化", "大型分布式架构"],
            description="任职要求：熟悉性能优化，具备大型分布式架构经验。",
        ),
    )

    assert result.matched == ("性能优化", "大型分布式架构")
    assert result.missing == ()
    assert result.score == 100


def test_natural_chinese_requirement_rejects_partial_character_overlap() -> None:
    result = match_resume_to_target(
        _resume_with_skills("负责优化流程"),
        AgentTargetContext(description="任职要求：熟悉性能优化。"),
    )

    assert result.matched == ()
    assert result.missing == ("性能优化",)
    assert result.score == 0


def test_english_prompt_controls_do_not_become_missing_keywords() -> None:
    result = match_resume_to_target(
        _resume_with_skills("React"),
        AgentTargetContext(
            description=(
                "Please use the following job description to optimize my resume. "
                "Do not modify basic or personal information. Requirements: React."
            ),
        ),
    )

    assert result.matched == ("react",)
    assert result.missing == ()
    assert result.score == 100


@pytest.mark.parametrize(
    "control_text",
    (
        "Do not edit my resume; just tell me what you can do.",
        "Review this job description without changing my resume.",
    ),
)
def test_read_only_english_controls_do_not_dilute_matching(
    control_text: str,
) -> None:
    result = match_resume_to_target(
        _resume_with_skills("React"),
        AgentTargetContext(description=f"{control_text} Requirements: React."),
    )

    assert result.matched == ("react",)
    assert result.missing == ()
    assert result.score == 100


def test_resume_structure_metadata_cannot_satisfy_target_requirements() -> None:
    resume = _resume_with_skills()
    resume["basicFieldStatus"] = {"email": "present"}
    resume["sections"] = [
        {
            "id": "react",
            "kind": "project",
            "title": "Components",
            "items": [],
        },
    ]

    result = match_resume_to_target(
        resume,
        AgentTargetContext(
            mustHaveSkills=["React", "Project", "Components", "Present"],
        ),
    )

    assert result.matched == ()
    assert result.missing == ("react", "project", "component", "present")
    assert result.score == 0


def test_small_word_variants_share_canonical_keywords() -> None:
    result = match_resume_to_target(
        _resume_with_skills("accessibility", "component"),
        AgentTargetContext(mustHaveSkills=["accessible", "components"]),
    )

    assert result.matched == ("accessibility", "component")
    assert result.missing == ()
    assert result.score == 100


def test_description_control_text_does_not_become_a_target_keyword() -> None:
    result = match_resume_to_target(
        _resume_with_skills("React", "TypeScript"),
        AgentTargetContext(
            description=(
                "请根据以下 JD 优化简历，不要修改基础信息。任职要求：React、TypeScript"
            )
        ),
    )

    assert result.matched == ("react", "typescript")
    assert result.missing == ()
    assert result.score == 100


def test_matching_does_not_drop_hard_skills_after_the_twelfth_keyword() -> None:
    result = match_resume_to_target(
        _resume_with_skills("React"),
        AgentTargetContext(
            mustHaveSkills=[
                "Python",
                "Java",
                "Golang",
                "Rust",
                "Kubernetes",
                "Docker",
                "AWS",
                "PostgreSQL",
                "Redis",
                "Kafka",
                "GraphQL",
                "Vue",
                "React",
            ]
        ),
    )

    assert "react" in result.matched
    assert len(result.missing) == 12


def test_requirement_boilerplate_does_not_dilute_explicit_skills() -> None:
    result = match_resume_to_target(
        _resume_with_skills("React", "TypeScript", "Node.js", "Tailwind CSS"),
        AgentTargetContext(
            description=(
                "任职要求：熟悉 React、TypeScript，具备 Node.js 开发经验，"
                "Tailwind CSS 优先"
            )
        ),
    )

    assert result.matched == ("react", "typescript", "node.js", "tailwind css")
    assert result.missing == ()
    assert result.score == 100


def test_resume_analysis_keeps_the_complete_authoritative_match() -> None:
    target_context = AgentTargetContext(
        mustHaveSkills=[
            "Python",
            "Java",
            "Golang",
            "Rust",
            "Kubernetes",
            "Docker",
            "AWS",
            "PostgreSQL",
            "Redis",
            "Kafka",
            "GraphQL",
            "Vue",
            "React",
        ]
    )
    executor = AgentPlanExecutor(
        AgentChatRequest(
            message=AgentConversationItem(
                id="turn-match-complete",
                role="user",
                text="分析目标匹配度",
            ),
            messages=[
                AgentConversationItem(
                    id="assistant-target-context",
                    role="assistant",
                    text="目标已更新",
                    response={
                        "targetContext": target_context.model_dump(
                            mode="json",
                            by_alias=True,
                        )
                    },
                )
            ],
            resume=_resume_with_skills("React"),
        )
    )

    analysis = executor.analyze_resume()

    assert analysis.matched_keywords == ["react"]
    assert len(analysis.missing_keywords) == 12
