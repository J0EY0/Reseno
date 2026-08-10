import json

import pytest

from app.schemas.agent import AgentChatRequest
from app.services.agent.runtime.messages import build_agent_messages
from app.services.llm import AgentLlmConfig, LlmRequestError


def _config(
    *,
    context_window_tokens: int,
    max_tokens: int | None,
) -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="llm-context-test",
        name="Context Test Model",
        provider="openai",
        model="context-test",
        base_url="https://example.test/v1",
        api_key="sk-test",
        temperature=0.4,
        top_p=0.9,
        max_tokens=max_tokens,
        timeout_seconds=60,
        context_window_tokens=context_window_tokens,
    )


def _request(
    *,
    prompt: str,
    messages: list[dict[str, object]] | None = None,
) -> AgentChatRequest:
    return AgentChatRequest(
        message={
            "id": "agent-user-current-context",
            "role": "user",
            "text": prompt,
        },
        messages=messages or [],
        locale="zh",
        resume={"basic": {"name": "测试用户"}, "sections": []},
        jobBrief="",
        keywordMatch={"matched": [], "missing": [], "score": 0},
        appliedActions=[],
        modelConfig=None,
        settings={},
    )


def test_agent_context_keeps_repeated_text_as_a_distinct_current_turn() -> None:
    request = _request(
        prompt="Repeat this request.",
        messages=[
            {
                "id": "agent-user-earlier-context",
                "role": "user",
                "text": "Repeat this request.",
            },
        ],
    )

    messages = build_agent_messages(
        request,
        _config(context_window_tokens=16_000, max_tokens=2_048),
        mode="final",
    )
    payload = json.loads(messages[1]["content"])

    assert [item["content"] for item in payload["conversation"]] == [
        "Repeat this request.",
        "Repeat this request.",
    ]


def test_agent_context_budget_reserves_output_tools_and_safety_margin() -> None:
    config = _config(context_window_tokens=16_000, max_tokens=2_048)
    request = _request(prompt="根据我的材料修改项目经历")

    messages = build_agent_messages(request, config, mode="tools")
    payload = json.loads(messages[1]["content"])
    compression = payload["conversationContext"]["compression"]

    assert compression["outputReserveTokens"] == 2_048
    assert compression["toolSchemaTokens"] > 0
    assert compression["safetyMarginTokens"] > 0
    assert compression["inputBudgetTokens"] == (
        16_000
        - compression["outputReserveTokens"]
        - compression["toolSchemaTokens"]
        - compression["safetyMarginTokens"]
    )
    assert compression["triggerInputTokens"] == int(
        compression["inputBudgetTokens"] * compression["triggerRatio"],
    )


def test_agent_context_budget_uses_provider_default_output_reserve() -> None:
    request = _request(prompt="检查项目经历")

    messages = build_agent_messages(
        request,
        _config(context_window_tokens=16_000, max_tokens=None),
        mode="final",
    )
    payload = json.loads(messages[1]["content"])

    assert payload["conversationContext"]["compression"]["outputReserveTokens"] == 4096


def test_agent_compression_builds_structured_memory_and_keeps_recent_turns() -> None:
    old_messages: list[dict[str, object]] = [
        {
            "id": "goal",
            "role": "user",
            "text": "目标：申请分布式系统方向的研究生项目。",
        },
        {
            "id": "material",
            "role": "user",
            "text": "材料：我负责过高并发任务调度项目，并有压测记录。",
            "files": [
                {
                    "id": "project-report",
                    "filename": "project-report.pdf",
                    "mediaType": "application/pdf",
                    "kind": "text",
                },
            ],
        },
        {
            "id": "constraint",
            "role": "user",
            "text": "约束：不要虚构指标，只能使用材料里已经确认的事实。",
        },
        {
            "id": "accepted",
            "role": "user",
            "text": "已确认：保留项目中的故障恢复经历。",
        },
        {
            "id": "rejected",
            "role": "user",
            "text": "已拒绝：不要把课程作业描述成商业项目。",
        },
        {
            "id": "question",
            "role": "assistant",
            "text": "待确认：压测记录是否可以公开？",
            "response": {
                "id": "question",
                "role": "assistant",
                "text": "待确认：压测记录是否可以公开？",
                "sources": [
                    {
                        "id": "project-report",
                        "title": "Project report",
                        "sourceType": "attachment",
                        "excerpt": "Load-test evidence",
                    },
                ],
            },
        },
    ]
    old_messages.extend(
        {
            "id": f"filler-{index}",
            "role": "assistant" if index % 2 else "user",
            "text": f"较早的讨论 {index}：" + ("用于触发上下文压缩。" * 45),
        }
        for index in range(10)
    )
    recent_messages = [
        {
            "id": f"recent-{index}",
            "role": "assistant" if index % 2 else "user",
            "text": f"最近精确轮次 {index}",
        }
        for index in range(4)
    ]
    conversation = [*old_messages, *recent_messages]
    request = _request(
        prompt="最近精确轮次 2",
        messages=conversation,
    )

    messages = build_agent_messages(
        request,
        _config(context_window_tokens=6_000, max_tokens=512),
        mode="final",
    )
    payload = json.loads(messages[1]["content"])
    context = payload["conversationContext"]
    memory = context["rollingMemory"]

    assert context["compression"]["applied"] is True
    assert [item["content"] for item in payload["conversation"]] == [
        *[item["text"] for item in recent_messages[1:]],
        request.message.text,
    ]
    assert memory["userGoals"] == ["目标：申请分布式系统方向的研究生项目。"]
    assert memory["factsAndMaterials"] == [
        "材料：我负责过高并发任务调度项目，并有压测记录。",
        "project-report.pdf",
    ]
    assert memory["constraints"] == [
        "约束：不要虚构指标，只能使用材料里已经确认的事实。",
    ]
    assert memory["acceptedDecisions"] == [
        "已确认：保留项目中的故障恢复经历。",
    ]
    assert memory["rejectedDecisions"] == [
        "已拒绝：不要把课程作业描述成商业项目。",
    ]
    assert memory["pendingQuestions"] == ["待确认：压测记录是否可以公开？"]
    assert memory["sourceReferences"] == [
        {
            "id": "project-report",
            "title": "Project report",
            "sourceType": "attachment",
            "excerpt": "Load-test evidence",
        },
    ]


def test_agent_compression_never_drops_the_recent_exact_window() -> None:
    recent_messages = [
        {
            "id": f"recent-{index}",
            "role": "assistant" if index % 2 else "user",
            "text": f"最近精确轮次 {index}：" + ("必须完整保留。" * 180),
        }
        for index in range(4)
    ]
    request = _request(
        prompt=recent_messages[-1]["text"],
        messages=recent_messages,
    )

    with pytest.raises(LlmRequestError, match="context window"):
        build_agent_messages(
            request,
            _config(context_window_tokens=6_000, max_tokens=512),
            mode="final",
        )
