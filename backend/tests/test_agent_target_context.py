import asyncio
import time

import pytest

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
    AgentSource,
    AgentTimelinePart,
)
from app.services.agent import TargetReference, WebSearchReference, WebSearchResult
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.materials import extract_resume_materials
from app.services.agent.policy import AgentTaskIntent, capability_policy_for_request
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.runtime.streaming import _merge_llm_response
from app.services.agent.target_context import exact_job_description_from_prompt
from app.services.agent.tools.runner import AgentToolRunner
from app.services.llm import LlmToolCall


def _executor(
    *,
    prompt: str,
    messages: list[AgentConversationItem] | None = None,
) -> AgentPlanExecutor:
    return AgentPlanExecutor(
        AgentChatRequest(
            message=AgentConversationItem(
                id=f"turn-target-context-{prompt}",
                role="user",
                text=prompt,
            ),
            messages=messages or [],
            locale="zh",
            resume={
                "basic": {"headline": "前端工程师"},
                "sections": [],
            },
        ),
    )


def _remembered_target_context(
    context: dict[str, object],
) -> AgentConversationItem:
    return AgentConversationItem(
        id="assistant-remembered-target-context",
        role="assistant",
        text="目标上下文已更新。",
        response={
            "id": "assistant-remembered-target-context",
            "role": "assistant",
            "text": "目标上下文已更新。",
            "targetContext": context,
        },
    )


def _target_context_call(
    *,
    mode: str,
    context: dict[str, object],
) -> LlmToolCall:
    return LlmToolCall(
        id=f"call-target-context-{mode}",
        name="update_target_context",
        arguments={"mode": mode, "context": context},
        raw_arguments="{}",
    )


def test_prompt_can_establish_target_context_for_the_current_turn() -> None:
    executor = _executor(prompt="我要投杭州的 AI 前端，重点关注 React 和 AI Agent")
    runner = AgentToolRunner(executor)

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="replace",
                context={
                    "kind": "employment",
                    "target": "AI 前端工程师",
                    "locations": ["杭州"],
                    "mustHaveSkills": ["React", "AI Agent"],
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-available"
    assert tool.output == {
        "mode": "replace",
        "targetContext": {
            "cleared": False,
            "kind": "employment",
            "target": "AI 前端工程师",
            "locations": ["杭州"],
            "seniority": "",
            "responsibilities": [],
            "mustHaveSkills": ["React", "AI Agent"],
            "niceToHaveSkills": [],
            "requirements": [],
            "description": "",
            "exactJobDescription": False,
            "sourceMessageIds": [executor.request.message.id],
        },
    }
    reference = runner.current_target_reference()
    assert reference.mode == "provided"
    assert reference.target == "AI 前端工程师"
    assert "React" in reference.excerpt
    assert runner.build_message().target_context == runner.session_target_context


def test_final_response_merge_preserves_target_context_memory() -> None:
    executor = _executor(prompt="我要投杭州的 AI 前端，重点关注 React")
    runner = AgentToolRunner(executor)
    asyncio.run(
        runner.run(
            _target_context_call(
                mode="replace",
                context={
                    "kind": "employment",
                    "target": "AI 前端工程师",
                    "locations": ["杭州"],
                    "mustHaveSkills": ["React"],
                },
            ),
            AgentRuntimeContext(),
        ),
    )
    draft = runner.build_message("assistant-target-context-stream")

    merged = _merge_llm_response(
        draft,
        '{"text":"已按当前目标完成分析。"}',
    )

    assert merged.text == "已按当前目标完成分析。"
    assert merged.target_context == runner.session_target_context
    assert (
        merged.model_dump(mode="json", by_alias=True)["targetContext"]["target"]
        == "AI 前端工程师"
    )


def test_final_response_merge_keeps_only_known_web_citation_ids() -> None:
    executor = _executor(prompt="研究 AI 前端岗位")
    draft = executor.build_message_from_parts(
        target_reference=executor.target_reference_from_request(),
        analysis=executor.analyze_resume(),
        plan=[],
        edits=[],
        tools=[],
    ).model_copy(
        update={
            "sources": [
                AgentSource(
                    id="source-jd-search",
                    title="Role A",
                    sourceType="web",
                    url="https://example.test/a",
                ),
                AgentSource(
                    id="source-target-context",
                    title="Target context",
                    sourceType="targetContext",
                ),
            ],
        },
    )

    merged = _merge_llm_response(
        draft,
        (
            '<citation source_ids="source-jd-search,source-target-context,'
            'source-invented">React is required</citation>.'
        ),
    )

    assert merged.text == "React is required."


def test_final_response_merge_removes_unverifiable_citation_markup() -> None:
    executor = _executor(prompt="研究 AI 前端岗位")
    draft = executor.build_message_from_parts(
        target_reference=executor.target_reference_from_request(),
        analysis=executor.analyze_resume(),
        plan=[],
        edits=[],
        tools=[],
    )

    merged = _merge_llm_response(
        draft,
        '<citation source_ids="source-invented">Unsupported claim</citation>.',
    )

    assert merged.text == "Unsupported claim."


def test_final_response_merge_sanitizes_timeline_citation_markup() -> None:
    executor = _executor(prompt="研究 AI 前端岗位")
    draft = executor.build_message_from_parts(
        target_reference=executor.target_reference_from_request(),
        analysis=executor.analyze_resume(),
        plan=[],
        edits=[],
        tools=[],
    ).model_copy(
        update={
            "sources": [
                AgentSource(
                    id="source-jd-search",
                    title="Role A",
                    sourceType="web",
                    url="https://example.test/a",
                ),
            ],
            "timeline": [
                AgentTimelinePart(
                    id="timeline-final",
                    type="text",
                    text=('<citation source_ids="source-jd-search">React is required'),
                ),
            ],
        },
    )

    merged = _merge_llm_response(
        draft,
        '<citation source_ids="source-jd-search">React is required',
    )

    assert merged.text == "React is required"
    assert merged.timeline[0].text == "React is required"


def test_final_response_merge_rejects_nested_citation_markup() -> None:
    executor = _executor(prompt="研究 AI 前端岗位")
    draft = executor.build_message_from_parts(
        target_reference=executor.target_reference_from_request(),
        analysis=executor.analyze_resume(),
        plan=[],
        edits=[],
        tools=[],
    ).model_copy(
        update={
            "sources": [
                AgentSource(
                    id="source-a",
                    title="Role A",
                    sourceType="web",
                    url="https://example.test/a",
                ),
                AgentSource(
                    id="source-b",
                    title="Role B",
                    sourceType="web",
                    url="https://example.test/b",
                ),
            ],
        },
    )

    merged = _merge_llm_response(
        draft,
        (
            '<citation source_ids="source-a">A outer; '
            '<citation source_ids="source-b">B inner</citation> tail</citation>.'
        ),
    )

    assert merged.text == "A outer; B inner tail."


def test_final_response_merge_rejects_more_than_three_sources_per_claim() -> None:
    executor = _executor(prompt="研究 AI 前端岗位")
    draft = executor.build_message_from_parts(
        target_reference=executor.target_reference_from_request(),
        analysis=executor.analyze_resume(),
        plan=[],
        edits=[],
        tools=[],
    ).model_copy(
        update={
            "sources": [
                AgentSource(
                    id=f"source-{suffix}",
                    title=f"Role {suffix}",
                    sourceType="web",
                    url=f"https://example.test/{suffix}",
                )
                for suffix in ("a", "b", "c", "d")
            ],
        },
    )

    merged = _merge_llm_response(
        draft,
        (
            '<citation source_ids="source-a,source-b,source-c,source-d">'
            "Only one source supports this claim</citation>."
        ),
    )

    assert merged.text == "Only one source supports this claim."


def test_citation_sanitizer_handles_many_unclosed_tags_in_linear_time() -> None:
    executor = _executor(prompt="研究 AI 前端岗位")
    draft = executor.build_message_from_parts(
        target_reference=executor.target_reference_from_request(),
        analysis=executor.analyze_resume(),
        plan=[],
        edits=[],
        tools=[],
    )
    raw_text = ('<citation source_ids="source-a">claim ' * 5_000) + "tail"

    started_at = time.perf_counter()
    merged = _merge_llm_response(draft, raw_text)
    elapsed = time.perf_counter() - started_at

    assert "<citation" not in merged.text
    assert merged.text.endswith("tail")
    assert elapsed < 1.0


def test_prompt_can_incrementally_update_remembered_target_context() -> None:
    first = _executor(
        prompt="我要投杭州的 AI 前端，重点关注 React、AI Agent 和 Node.js",
    )
    first_runner = AgentToolRunner(first)
    asyncio.run(
        first_runner.run(
            _target_context_call(
                mode="replace",
                context={
                    "kind": "employment",
                    "target": "AI 前端工程师",
                    "locations": ["杭州"],
                    "mustHaveSkills": ["React", "AI Agent", "Node.js"],
                },
            ),
            AgentRuntimeContext(),
        ),
    )
    first_message = first_runner.build_message("assistant-target-context-1")
    second = _executor(
        prompt="地点改成上海，Node 不是必须",
        messages=[
            AgentConversationItem(
                id=first_message.id,
                role="assistant",
                text=first_message.text,
                response=first_message.model_dump(mode="json", by_alias=True),
            ),
        ],
    )
    second_runner = AgentToolRunner(second)

    asyncio.run(
        second_runner.run(
            _target_context_call(
                mode="merge",
                context={
                    "locations": ["上海"],
                    "mustHaveSkills": ["React", "AI Agent"],
                    "niceToHaveSkills": ["Node.js"],
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    context = second_runner.session_target_context
    assert context is not None
    assert context.target == "AI 前端工程师"
    assert context.locations == ["上海"]
    assert context.must_have_skills == ["React", "AI Agent"]
    assert context.nice_to_have_skills == ["Node.js"]
    assert context.source_message_ids == [
        first.request.message.id,
        second.request.message.id,
    ]


def test_prompt_can_replace_remembered_target_without_stale_fields() -> None:
    first = _executor(prompt="我要投杭州的 AI 前端")
    first_runner = AgentToolRunner(first)
    asyncio.run(
        first_runner.run(
            _target_context_call(
                mode="replace",
                context={
                    "kind": "employment",
                    "target": "AI 前端工程师",
                    "locations": ["杭州"],
                    "mustHaveSkills": ["React"],
                },
            ),
            AgentRuntimeContext(),
        ),
    )
    first_message = first_runner.build_message("assistant-target-context-old")
    second = _executor(
        prompt="换成北京的 Python 后端岗位",
        messages=[
            AgentConversationItem(
                id=first_message.id,
                role="assistant",
                text=first_message.text,
                response=first_message.model_dump(mode="json", by_alias=True),
            ),
        ],
    )
    second_runner = AgentToolRunner(second)

    asyncio.run(
        second_runner.run(
            _target_context_call(
                mode="replace",
                context={
                    "kind": "employment",
                    "target": "Python 后端工程师",
                    "locations": ["北京"],
                    "mustHaveSkills": ["Python"],
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    context = second_runner.session_target_context
    assert context is not None
    assert context.target == "Python 后端工程师"
    assert context.locations == ["北京"]
    assert context.must_have_skills == ["Python"]
    assert context.nice_to_have_skills == []
    assert context.source_message_ids == [second.request.message.id]


def test_negated_search_instruction_cannot_overwrite_remembered_target() -> None:
    remembered = _remembered_target_context(
        {
            "kind": "employment",
            "target": "AI 前端工程师",
            "locations": ["杭州"],
            "mustHaveSkills": ["React"],
            "sourceMessageIds": ["turn-original-target"],
        },
    )
    executor = _executor(
        prompt="不要检索岗位，只分析当前简历",
        messages=[remembered],
    )
    runner = AgentToolRunner(executor)

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="replace",
                context={"kind": "employment", "target": "岗位"},
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-error"
    assert runner.session_target_context is not None
    assert runner.session_target_context.target == "AI 前端工程师"
    assert runner.session_target_context.source_message_ids == [
        "turn-original-target",
    ]


def test_ordinary_reuse_instruction_cannot_mutate_remembered_target() -> None:
    remembered = _remembered_target_context(
        {
            "kind": "employment",
            "target": "AI 前端工程师",
            "mustHaveSkills": ["React"],
            "sourceMessageIds": ["turn-original-target"],
        },
    )
    executor = _executor(
        prompt="按照刚才的目标只改项目经历",
        messages=[remembered],
    )
    runner = AgentToolRunner(executor)

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="merge",
                context={
                    "target": "AI 前端工程师",
                    "mustHaveSkills": ["React"],
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-error"
    assert runner.session_target_context is not None
    assert runner.session_target_context.source_message_ids == [
        "turn-original-target",
    ]


def test_target_gap_followup_reuses_memory_without_becoming_a_draft_revision() -> None:
    remembered = _remembered_target_context(
        {
            "kind": "employment",
            "target": "AI 前端工程师",
            "mustHaveSkills": ["React"],
            "sourceMessageIds": ["turn-original-target"],
        },
    )
    executor = _executor(
        prompt="沿用刚才的目标，只说明最关键的三个差距，不修改简历",
        messages=[remembered],
    )

    assert capability_policy_for_request(executor.request).intent == (
        AgentTaskIntent.DIAGNOSE_JD_GAP
    )

    runner = AgentToolRunner(executor)
    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="merge",
                context={
                    "target": "AI 前端工程师",
                    "mustHaveSkills": ["React"],
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-error"
    assert runner.session_target_context is not None
    assert runner.session_target_context.source_message_ids == [
        "turn-original-target",
    ]


def test_unmentioned_target_change_cannot_pollute_remembered_context() -> None:
    remembered = _remembered_target_context(
        {
            "kind": "employment",
            "target": "AI 前端工程师",
            "mustHaveSkills": ["React"],
            "sourceMessageIds": ["turn-original-target"],
        },
    )
    executor = _executor(
        prompt="沿用当前目标，只分析差距，不修改简历",
        messages=[remembered],
    )
    runner = AgentToolRunner(executor)

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="replace",
                context={
                    "kind": "employment",
                    "target": "Python 后端工程师",
                    "mustHaveSkills": ["Python"],
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-error"
    assert runner.session_target_context is not None
    assert runner.session_target_context.target == "AI 前端工程师"
    assert runner.session_target_context.source_message_ids == [
        "turn-original-target",
    ]


def test_partial_location_change_cannot_replace_and_clear_remembered_target() -> None:
    remembered = _remembered_target_context(
        {
            "kind": "employment",
            "target": "AI 前端工程师",
            "locations": ["杭州"],
            "mustHaveSkills": ["React"],
            "description": "负责 React 应用开发。",
            "sourceMessageIds": ["turn-original-target"],
        },
    )
    runner = AgentToolRunner(
        _executor(prompt="地点改成上海", messages=[remembered]),
    )

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="replace",
                context={"locations": ["上海"]},
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-error"
    assert runner.session_target_context is not None
    assert runner.session_target_context.target == "AI 前端工程师"
    assert runner.session_target_context.locations == ["杭州"]
    assert runner.session_target_context.must_have_skills == ["React"]


def test_incidental_chinese_overlap_cannot_ground_a_different_target() -> None:
    runner = AgentToolRunner(_executor(prompt="我要投杭州前端岗位"))

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="replace",
                context={
                    "kind": "employment",
                    "target": "杭州人工智能平台架构负责人",
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-error"
    assert runner.session_target_context is None


def test_exact_jd_flag_requires_an_actual_description_in_the_prompt() -> None:
    runner = AgentToolRunner(_executor(prompt="我要投杭州前端岗位"))

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="replace",
                context={
                    "kind": "employment",
                    "target": "杭州前端工程师",
                    "exactJobDescription": True,
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-error"
    assert runner.session_target_context is None


def test_complete_jd_in_prompt_can_establish_exact_target_context() -> None:
    description = (
        "职责：使用 React 和 TypeScript 开发产品。"
        "任职要求：熟悉 Node.js、Tailwind CSS 和可访问性。"
    )
    executor = _executor(prompt=f"目标是 AI 前端工程师。{description}")
    runner = AgentToolRunner(executor)

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="replace",
                context={
                    "kind": "employment",
                    "target": "AI 前端工程师",
                    "description": description,
                    "exactJobDescription": True,
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-available"
    assert runner.session_target_context is not None
    assert runner.session_target_context.description == description
    assert runner.session_target_context.exact_job_description is True


def test_complete_jd_uses_exact_prompt_block_when_model_paraphrases() -> None:
    prompt = (
        "目标是 AI 前端工程师。"
        "岗位职责：使用 React、TypeScript、Node.js；"
        "任职要求：Tailwind CSS、shadcn/ui、Jest、Vitest、GitHub Actions、"
        "WCAG accessibility、LLM prompt engineering。"
        "只分析匹配，不修改简历。"
    )
    runner = AgentToolRunner(_executor(prompt=prompt))

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="replace",
                context={
                    "kind": "employment",
                    "target": "AI 前端工程师",
                    "responsibilities": ["使用 React 开发前端"],
                    "mustHaveSkills": ["React", "TypeScript", "Node.js"],
                    "description": (
                        "AI 前端工程师岗位。岗位职责：使用 React、TypeScript、"
                        "Node.js；任职要求：Tailwind CSS、shadcn/ui、Jest、Vitest、"
                        "GitHub Actions、WCAG accessibility、LLM prompt engineering。"
                        "用户要求只做匹配分析，不修改简历。"
                    ),
                    "exactJobDescription": False,
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-available"
    assert runner.session_target_context is not None
    assert runner.session_target_context.description == (
        "岗位职责：使用 React、TypeScript、Node.js；"
        "任职要求：Tailwind CSS、shadcn/ui、Jest、Vitest、GitHub Actions、"
        "WCAG accessibility、LLM prompt engineering。"
    )
    assert runner.session_target_context.exact_job_description is True
    assert runner.session_target_context.responsibilities == []
    assert runner.session_target_context.must_have_skills == []


def test_explicitly_partial_jd_is_not_promoted_to_exact_context() -> None:
    prompt = (
        "目标是 AI 前端工程师。以下只是目标方向，不是完整 JD。"
        "任职要求：需要 React、TypeScript、Node.js、Tailwind CSS 和可访问性。"
        "只分析通用匹配。"
    )
    runner = AgentToolRunner(_executor(prompt=prompt))

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="replace",
                context={
                    "kind": "employment",
                    "target": "AI 前端工程师",
                    "mustHaveSkills": [
                        "React",
                        "TypeScript",
                        "Node.js",
                        "Tailwind CSS",
                        "可访问性",
                    ],
                    "exactJobDescription": False,
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-available"
    assert runner.session_target_context is not None
    assert runner.session_target_context.exact_job_description is False
    assert runner.session_target_context.must_have_skills == [
        "React",
        "TypeScript",
        "Node.js",
        "Tailwind CSS",
        "可访问性",
    ]


def test_exact_jd_memory_strips_resume_edit_instructions_from_prompt() -> None:
    prompt = (
        "请根据下面 JD 优化项目经历，不要修改基础信息。"
        "目标是杭州前端工程师。"
        "任职要求：熟悉 React 和 TypeScript，负责前端性能优化。"
    )
    runner = AgentToolRunner(_executor(prompt=prompt))

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="replace",
                context={
                    "kind": "employment",
                    "target": "杭州前端工程师",
                    "description": prompt,
                    "exactJobDescription": True,
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-available"
    assert runner.session_target_context is not None
    assert runner.session_target_context.description == (
        "任职要求：熟悉 React 和 TypeScript，负责前端性能优化。"
    )


@pytest.mark.parametrize(
    "prompt",
    [
        "我要求你只改项目经历，不要修改基础信息。目标是杭州前端工程师。",
        "请按我的要求优化简历：只改项目和技能，不要改其他内容。",
    ],
)
def test_ordinary_edit_instructions_are_not_an_exact_jd(prompt: str) -> None:
    assert exact_job_description_from_prompt(prompt) == ""


def test_exact_jd_accepts_structured_headings_on_their_own_lines() -> None:
    prompt = (
        "目标是前端工程师\n"
        "岗位职责\n"
        "1. 负责 React 应用开发\n"
        "任职要求\n"
        "1. 熟悉 TypeScript"
    )

    assert exact_job_description_from_prompt(prompt) == (
        "岗位职责\n1. 负责 React 应用开发\n任职要求\n1. 熟悉 TypeScript"
    )


def test_prompt_can_clear_remembered_target_and_stop_history_fallback() -> None:
    remembered = _remembered_target_context(
        {
            "kind": "employment",
            "target": "AI 前端工程师",
            "description": (
                "任职要求：熟练 React 和 TypeScript，负责可访问性与前端工程质量。"
            ),
            "exactJobDescription": True,
            "sourceMessageIds": ["turn-original-target"],
        },
    )
    executor = _executor(
        prompt="清除之前的岗位目标，先做通用简历优化",
        messages=[remembered],
    )
    runner = AgentToolRunner(executor)

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(mode="clear", context={}),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-available"
    assert runner.session_target_context is not None
    assert runner.session_target_context.cleared is True
    cleared_message = runner.build_message("assistant-target-cleared")
    follow_up = _executor(
        prompt="只分析当前简历的通用问题",
        messages=[
            remembered,
            AgentConversationItem(
                id=cleared_message.id,
                role="assistant",
                text=cleared_message.text,
                response=cleared_message.model_dump(mode="json", by_alias=True),
            ),
        ],
    )

    assert follow_up.target_context is None
    assert follow_up.target_match.score is None
    assert follow_up.target_match.matched == ()
    assert follow_up.target_match.missing == ()


def test_negated_clear_instruction_cannot_erase_remembered_target() -> None:
    remembered = _remembered_target_context(
        {
            "kind": "employment",
            "target": "AI 前端工程师",
            "sourceMessageIds": ["turn-original-target"],
        },
    )
    runner = AgentToolRunner(
        _executor(prompt="不要清除当前岗位目标", messages=[remembered]),
    )

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(mode="clear", context={}),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-error"
    assert runner.session_target_context is not None
    assert runner.session_target_context.target == "AI 前端工程师"


def test_adding_one_skill_cannot_silently_remove_an_existing_requirement() -> None:
    remembered = _remembered_target_context(
        {
            "kind": "employment",
            "target": "AI 前端工程师",
            "mustHaveSkills": ["React", "Node.js"],
            "sourceMessageIds": ["turn-original-target"],
        },
    )
    runner = AgentToolRunner(
        _executor(prompt="再加上 TypeScript 要求", messages=[remembered]),
    )

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="merge",
                context={"mustHaveSkills": ["React", "TypeScript"]},
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-error"
    assert runner.session_target_context is not None
    assert runner.session_target_context.must_have_skills == ["React", "Node.js"]


def test_exact_jd_memory_cannot_be_downgraded_without_user_instruction() -> None:
    remembered = _remembered_target_context(
        {
            "kind": "employment",
            "target": "AI 前端工程师",
            "mustHaveSkills": ["React"],
            "description": (
                "任职要求：熟练 React 和 TypeScript，负责可访问性与前端工程质量。"
            ),
            "exactJobDescription": True,
            "sourceMessageIds": ["turn-original-target"],
        },
    )
    runner = AgentToolRunner(
        _executor(prompt="再加上 TypeScript 要求", messages=[remembered]),
    )

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="merge",
                context={
                    "mustHaveSkills": ["React", "TypeScript"],
                    "exactJobDescription": False,
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-error"
    assert runner.session_target_context is not None
    assert runner.session_target_context.exact_job_description is True


def test_unmentioned_seniority_cannot_be_added_to_a_target_title() -> None:
    runner = AgentToolRunner(_executor(prompt="我要投杭州前端岗位"))

    tool, _ = asyncio.run(
        runner.run(
            _target_context_call(
                mode="replace",
                context={
                    "kind": "employment",
                    "target": "杭州前端资深工程师",
                },
            ),
            AgentRuntimeContext(),
        ),
    )

    assert tool.state == "output-error"
    assert runner.session_target_context is None


def test_remembered_exact_description_is_the_current_jd_reference() -> None:
    executor = _executor(
        prompt="根据目标要求优化简历",
        messages=[
            _remembered_target_context(
                {
                    "kind": "employment",
                    "target": "前端工程师",
                    "description": "任职要求：熟悉 React、TypeScript 和前端性能优化。",
                    "exactJobDescription": True,
                },
            ),
        ],
    )

    reference = executor.target_reference_from_request()
    tool = executor.build_target_reference_tool(reference)

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
        target_context="",
        files=[],
        target_reference=reference,
        focus="target_context",
    )

    assert result["candidateCount"] == 1
    candidate = result["candidates"][0]
    assert candidate["title"] == "Target opportunity context"
    assert candidate["sourceType"] == "targetContext"
    assert candidate["opportunityType"] == "graduate_study"
    assert candidate["referenceOnly"] is True


def test_multi_search_sources_keep_each_excerpt_with_its_real_url() -> None:
    executor = _executor(prompt="根据目标岗位优化简历")
    first = WebSearchResult(
        title="Example role",
        url="https://example.test/role",
        excerpt="Role-specific requirements.",
    )
    second = WebSearchResult(
        title="Example team",
        url="https://example.test/team",
        excerpt="Team-specific context.",
    )
    duplicate = WebSearchResult(
        title="Duplicate role result",
        url=first.url,
        excerpt="A duplicate excerpt must not create a second source.",
    )
    summary = WebSearchReference(
        query="example frontend role",
        results=(first, second, duplicate),
        query_count=2,
        result_count=3,
    )
    runner = AgentToolRunner(executor)

    primary = runner.web_search_summary_primary_result(summary)
    reference = executor.build_search_target_reference_from_result(
        "Frontend engineer",
        summary.query,
        primary,
        summary.result_count,
        summary.error,
        kind="employment",
        exact_job_description=True,
        search_results=summary.results,
    )
    sources = executor.build_sources(reference, executor.analyze_resume())
    tool = executor.build_target_reference_tool(reference)

    assert primary == first
    assert [
        (source.url, source.excerpt)
        for source in sources
        if source.source_type == "web"
    ] == [
        (first.url, first.excerpt),
        (second.url, second.excerpt),
    ]
    assert tool.output["url"] == first.url
    assert tool.output["title"] == first.title
    assert tool.output["excerpt"] == first.excerpt
    assert reference.excerpt == f"{first.excerpt} {second.excerpt}"
    assert tool.output["results"] == [
        {
            "url": first.url,
            "title": first.title,
            "excerpt": first.excerpt,
        },
        {
            "url": second.url,
            "title": second.title,
            "excerpt": second.excerpt,
        },
    ]
