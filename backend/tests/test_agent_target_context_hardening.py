import pytest

from app.services.agent.target_context import (
    exact_job_description_from_prompt,
    target_context_update_is_grounded,
)


def test_unmentioned_single_cjk_character_is_not_grounded() -> None:
    assert not target_context_update_is_grounded(
        None,
        {
            "kind": "employment",
            "target": "前端工程师",
            "locations": ["沪"],
        },
        mode="replace",
        prompt="目标是前端工程师",
    )


def test_latin_substring_is_not_grounded_as_a_distinct_skill() -> None:
    assert not target_context_update_is_grounded(
        None,
        {
            "kind": "employment",
            "target": "前端工程师",
            "mustHaveSkills": ["Java"],
        },
        mode="replace",
        prompt="目标是前端工程师，要求 JavaScript",
    )


def test_exact_jd_stops_before_semicolon_separated_control_instruction() -> None:
    prompt = (
        "目标是 AI 前端工程师；"
        "岗位职责：使用 React 开发产品；"
        "任职要求：熟悉 TypeScript；"
        "只分析匹配，不修改简历。"
    )

    assert exact_job_description_from_prompt(prompt) == (
        "岗位职责：使用 React 开发产品；任职要求：熟悉 TypeScript"
    )


@pytest.mark.parametrize("heading", ["工作内容", "岗位描述", "职位描述"])
def test_exact_jd_accepts_common_description_headings(heading: str) -> None:
    description = f"{heading}：负责 React 应用开发。任职要求：熟悉 TypeScript。"

    assert exact_job_description_from_prompt(f"目标是前端工程师。{description}") == (
        description
    )


def test_exact_jd_accepts_unpunctuated_heading_with_same_line_content() -> None:
    description = (
        "岗位职责 负责 React 应用开发\n任职要求 熟悉 TypeScript 和前端性能优化"
    )

    assert exact_job_description_from_prompt(f"目标是前端工程师\n{description}") == (
        description
    )


def test_ordinary_requirement_instruction_is_not_an_exact_jd() -> None:
    assert (
        exact_job_description_from_prompt(
            "我要求你只分析当前简历，不要修改任何内容。",
        )
        == ""
    )


@pytest.mark.parametrize(
    ("skill", "prompt_skill"),
    [("Node.js", "Node JS"), ("C#", "C＃"), ("CI/CD", "CI-CD")],
)
def test_punctuated_technical_skill_variants_remain_grounded(
    skill: str,
    prompt_skill: str,
) -> None:
    assert target_context_update_is_grounded(
        None,
        {
            "kind": "employment",
            "target": "前端工程师",
            "mustHaveSkills": [skill],
        },
        mode="replace",
        prompt=f"目标是前端工程师，要求 {prompt_skill}",
    )
