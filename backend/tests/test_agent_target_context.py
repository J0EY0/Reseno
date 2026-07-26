import pytest

from app.schemas.agent import AgentChatRequest
from app.services.agent import JobReference, TargetReference
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.materials import extract_resume_materials


def _executor(*, prompt: str, job_brief: str = "") -> AgentPlanExecutor:
    return AgentPlanExecutor(
        AgentChatRequest(
            prompt=prompt,
            jobBrief=job_brief,
            locale="zh",
            resume={
                "basic": {"headline": "前端工程师"},
                "sections": [],
            },
        ),
    )


def test_legacy_job_brief_remains_an_exact_jd_reference() -> None:
    executor = _executor(
        prompt="根据目标要求优化简历",
        job_brief="任职要求：熟悉 React、TypeScript 和前端性能优化。",
    )

    reference = executor.target_reference_from_request()
    tool = executor.build_target_reference_tool(reference)

    assert JobReference is TargetReference
    assert reference.kind == "employment"
    assert reference.exact_job_description is True
    assert reference.excerpt.startswith("任职要求")
    assert tool.input["purpose"] == "jd"
    assert tool.output["target"] == reference.target
    assert tool.output["role"] == reference.target


@pytest.mark.parametrize(
    ("prompt", "expected_kind", "query_fragment"),
    [
        (
            "查找示例大学计算机硕士项目的课程和研究方向",
            "graduate_study",
            "招生要求",
        ),
        ("查找机器学习实验室的科研机会", "research", "研究机会"),
        ("查找面向本科生的奖学金", "scholarship", "申请条件"),
    ],
)
def test_non_job_opportunities_are_first_class_target_context(
    prompt: str,
    expected_kind: str,
    query_fragment: str,
) -> None:
    executor = _executor(prompt=prompt)

    reference = executor.target_reference_from_request()
    query = executor.target_search_query(reference.target, reference.kind)

    assert reference.kind == expected_kind
    assert reference.exact_job_description is False
    assert query_fragment in query
    assert " JD " not in query


def test_material_extraction_labels_target_context_without_job_only_wording() -> None:
    reference = TargetReference(
        mode="provided",
        kind="graduate_study",
        target="计算机硕士项目",
        query="",
        url=None,
        excerpt="招生要求：提交研究计划，并说明与项目方向的匹配度。",
    )

    result = extract_resume_materials(
        session_id="session-target-context",
        prompt="分析目标项目",
        job_brief="",
        files=[],
        target_reference=reference,
        focus="target_context",
    )

    assert result["candidateCount"] == 1
    candidate = result["candidates"][0]
    assert candidate["title"] == "Target opportunity context"
    assert candidate["sourceType"] == "jobBrief"
    assert candidate["opportunityType"] == "graduate_study"
    assert candidate["referenceOnly"] is True
