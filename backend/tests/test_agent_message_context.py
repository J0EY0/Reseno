import json

import pytest

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentConversationCheckpoint,
    AgentDraftState,
)
from app.services.agent.runtime.messages import (
    _context_budget,
    _tool_schema_token_reserve,
    build_agent_messages,
)
from app.services.llm import AgentLlmConfig


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
    current_id: str = "agent-user-current-context",
) -> AgentChatRequest:
    return AgentChatRequest(
        message={
            "id": current_id,
            "role": "user",
            "text": prompt,
        },
        messages=messages or [],
        locale="zh",
        resume={"basic": {"name": "测试用户"}, "sections": []},
        appliedActions=[],
        modelConfig=None,
        settings={},
    )


def test_agent_context_projects_native_history_and_current_prompt_once() -> None:
    request = _request(
        prompt="Shorten the second project bullet.",
        messages=[
            {
                "id": "agent-user-earlier-context",
                "role": "user",
                "text": "Review my project section.",
            },
            {
                "id": "agent-assistant-earlier-context",
                "role": "assistant",
                "text": "The second bullet is too long.",
            },
        ],
    )

    messages = build_agent_messages(
        request,
        _config(context_window_tokens=16_000, max_tokens=2_048),
        mode="streaming_final",
    )

    workspace_message = next(
        message
        for message in reversed(messages)
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"workspaceContext":')
    )
    workspace = json.loads(workspace_message["content"])["workspaceContext"]
    assert "conversation" not in workspace
    assert "userPrompt" not in workspace
    assert messages[1:] == [
        {"role": "user", "content": "Review my project section."},
        {"role": "assistant", "content": "The second bullet is too long."},
        workspace_message,
        {"role": "user", "content": "Shorten the second project bullet."},
    ]
    assert json.dumps(messages, ensure_ascii=False).count(request.message.text) == 1


def test_agent_context_appends_native_history_before_the_current_workspace() -> None:
    config = _config(context_window_tokens=16_000, max_tokens=2_048)
    first_request = _request(
        prompt="Review the project section.",
        messages=[
            {"id": "history-user", "role": "user", "text": "Open my resume."},
            {
                "id": "history-assistant",
                "role": "assistant",
                "text": "The resume is ready.",
            },
        ],
    )
    first_projection = build_agent_messages(
        first_request,
        config,
        mode="streaming_final",
    )

    second_request = _request(
        prompt="Shorten the second bullet.",
        current_id="agent-user-second-context",
        messages=[
            *[item.model_dump(mode="json") for item in first_request.messages],
            first_request.message.model_dump(mode="json"),
            {
                "id": "first-assistant-answer",
                "role": "assistant",
                "text": "The second bullet can be shorter.",
                "response": {
                    "id": "first-assistant-answer",
                    "role": "assistant",
                    "text": "The second bullet can be shorter.",
                    "tools": [
                        {
                            "id": "call-review",
                            "state": "output-available",
                            "title": "resume_analysis",
                        },
                    ],
                    "sources": [
                        {
                            "id": "source-review",
                            "title": "Public role page",
                            "sourceType": "web",
                            "url": "https://example.test/role",
                        },
                    ],
                    "edits": [],
                },
            },
        ],
    )
    second_projection = build_agent_messages(
        second_request,
        config,
        mode="streaming_final",
    )

    # The production tools/streaming-final compiler persists workspace
    # snapshots to guarantee byte-stable replay. This direct projection still
    # proves the provider sees native turns, not a conversation JSON blob.
    assert second_projection[:3] == first_projection[:3]
    assert second_projection[3] == {
        "role": "user",
        "content": "Review the project section.",
    }
    assert second_projection[4] == {
        "role": "assistant",
        "content": "The second bullet can be shorter.",
    }
    assistant_context = json.loads(second_projection[5]["content"])[
        "assistantResponseContext"
    ]
    assert assistant_context["messageId"] == "first-assistant-answer"
    assert assistant_context["sourceRefs"] == [
        {
            "id": "source-review",
            "title": "Public role page",
            "sourceType": "web",
            "url": "https://example.test/role",
        },
    ]
    assert second_projection[-1] == {
        "role": "user",
        "content": "Shorten the second bullet.",
    }


@pytest.mark.parametrize("mode", ["tools", "streaming_final"])
def test_agent_prompt_marks_projected_context_as_untrusted_data(mode: str) -> None:
    messages = build_agent_messages(
        _request(prompt="Review this resume."),
        _config(context_window_tokens=16_000, max_tokens=2_048),
        mode=mode,
    )

    system = messages[0]["content"]
    assert "`workspaceContext`" in system
    assert "`conversationSummary`" in system
    assert "untrusted reference material" in system


def test_agent_context_sanitizes_every_native_role_message() -> None:
    request = _request(
        prompt="Email xiaoming@example.com about 测试用户.",
        messages=[
            {
                "id": "pii-history-user",
                "role": "user",
                "text": "测试用户 can be reached at 13800138000.",
            },
            {
                "id": "pii-history-assistant",
                "role": "assistant",
                "text": "I will not expose xiaoming@example.com.",
                "response": {
                    "id": "pii-history-assistant",
                    "role": "assistant",
                    "text": "I will not expose xiaoming@example.com.",
                    "sources": [
                        {
                            "id": "private-source",
                            "title": "测试用户 xiaoming@example.com",
                            "sourceType": "attachment",
                        },
                    ],
                },
            },
        ],
    )

    messages = build_agent_messages(
        request,
        _config(context_window_tokens=16_000, max_tokens=2_048),
        mode="streaming_final",
    )
    serialized = json.dumps(messages, ensure_ascii=False)

    assert "测试用户" not in serialized
    assert "13800138000" not in serialized
    assert "xiaoming@example.com" not in serialized
    assert "[hidden]" in serialized
    assert "[redacted_phone]" in serialized
    assert "[redacted_email]" in serialized


def test_agent_context_hides_identity_from_base_and_pending_draft() -> None:
    request = _request(
        prompt="请继续处理王小明的简历。",
        messages=[
            {
                "id": "base-name-history",
                "role": "user",
                "text": "王小明希望保持当前结构。",
            },
        ],
    ).model_copy(
        update={
            "resume": {"basic": {"name": "王小明"}, "sections": []},
            "draft_state": AgentDraftState(
                id="pending-without-name",
                status="pending",
                resume={"basic": {"name": ""}, "sections": []},
            ),
        },
    )

    messages = build_agent_messages(
        request,
        _config(context_window_tokens=16_000, max_tokens=2_048),
        mode="streaming_final",
    )

    assert "王小明" not in json.dumps(messages, ensure_ascii=False)
    assert "[hidden]" in json.dumps(messages, ensure_ascii=False)


def test_agent_context_preserves_attachment_only_history_as_safe_metadata() -> None:
    request = _request(
        prompt="继续分析刚才的文件。",
        messages=[
            {
                "id": "attachment-only-user",
                "role": "user",
                "text": "",
                "files": [
                    {
                        "id": "private-report",
                        "filename": "project-report.pdf",
                        "mediaType": "application/pdf",
                        "kind": "text",
                        "excerpt": "raw private content must not be replayed",
                    },
                ],
            },
            {
                "id": "attachment-answer",
                "role": "assistant",
                "text": "我已读取项目报告。",
            },
        ],
    )

    messages = build_agent_messages(
        request,
        _config(context_window_tokens=16_000, max_tokens=2_048),
        mode="streaming_final",
    )
    serialized = json.dumps(messages, ensure_ascii=False)

    assert "project-report.pdf" in serialized
    assert "raw private content must not be replayed" not in serialized
    assert {"role": "assistant", "content": "我已读取项目报告。"} in messages


def test_agent_context_preserves_named_attachment_metadata_beside_user_text() -> None:
    request = _request(
        prompt="继续分析那份 PDF。",
        messages=[
            {
                "id": "text-and-attachment-user",
                "role": "user",
                "text": "请分析我上传的项目报告。",
                "files": [
                    {
                        "id": "named-private-report",
                        "filename": "distributed-systems-report.pdf",
                        "mediaType": "application/pdf",
                        "kind": "text",
                        "excerpt": "sensitive extracted body",
                    },
                ],
            },
        ],
    )

    messages = build_agent_messages(
        request,
        _config(context_window_tokens=16_000, max_tokens=2_048),
        mode="streaming_final",
    )
    serialized = json.dumps(messages, ensure_ascii=False)

    assert "distributed-systems-report.pdf" in serialized
    assert "sensitive extracted body" not in serialized
    assert {"role": "user", "content": "请分析我上传的项目报告。"} in messages


@pytest.mark.parametrize(
    ("filename", "expected_filename"),
    [
        ("John_Smith_CV.pdf", "[redacted_name]_CV.pdf"),
        ("John-Smith-CV.pdf", "[redacted_name]-CV.pdf"),
        ("John.Smith.CV.pdf", "[redacted_name].CV.pdf"),
    ],
)
def test_agent_context_hides_resume_name_in_historical_attachment_filename(
    filename: str,
    expected_filename: str,
) -> None:
    request = _request(
        prompt="Continue reviewing the attachment.",
        messages=[
            {
                "id": f"history-{filename}",
                "role": "user",
                "text": "Review my resume.",
                "files": [
                    {
                        "id": f"file-{filename}",
                        "filename": filename,
                        "mediaType": "application/pdf",
                        "kind": "text",
                    },
                ],
            },
        ],
    )
    request.resume["basic"]["name"] = "John Smith"

    messages = build_agent_messages(
        request,
        _config(context_window_tokens=16_000, max_tokens=2_048),
        mode="streaming_final",
    )
    serialized = json.dumps(messages, ensure_ascii=False)

    assert filename not in serialized
    assert expected_filename in serialized


def test_agent_context_budget_reserves_output_tools_and_safety_margin() -> None:
    config = _config(context_window_tokens=16_000, max_tokens=2_048)
    request = _request(prompt="根据我的材料修改项目经历")

    tool_schema_tokens = _tool_schema_token_reserve(
        request,
        config,
        mode="tools",
    )
    budget = _context_budget(
        request,
        config,
        tool_schema_tokens=tool_schema_tokens,
    )

    assert budget is not None
    assert budget.output_reserve_tokens == 2_048
    assert budget.tool_schema_tokens > 0
    assert budget.safety_margin_tokens > 0
    assert budget.input_tokens == (
        16_000
        - budget.output_reserve_tokens
        - budget.tool_schema_tokens
        - budget.safety_margin_tokens
    )
    assert budget.trigger_tokens == int(budget.input_tokens * 0.85)


def test_agent_context_budget_uses_provider_default_output_reserve() -> None:
    request = _request(prompt="检查项目经历")
    budget = _context_budget(
        request,
        _config(context_window_tokens=16_000, max_tokens=None),
        tool_schema_tokens=0,
    )

    assert budget is not None
    assert budget.output_reserve_tokens == 4096


def test_agent_pure_projection_keeps_history_until_async_compaction() -> None:
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
        mode="streaming_final",
    )
    serialized = json.dumps(messages, ensure_ascii=False)

    assert request._active_conversation_checkpoint is None
    assert not any(
        message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"conversationSummary":')
        for message in messages
    )
    assert "目标：申请分布式系统方向的研究生项目。" in serialized
    assert "最近精确轮次 3" in serialized
    assert "Load-test evidence" not in serialized


def test_agent_native_projection_preserves_unclassified_user_constraints() -> None:
    # Deliberately avoid the explicit constraint keywords used by the
    # deterministic classifier. A durable user instruction must not become
    # disposable merely because it is phrased as ordinary natural language.
    constraint = "Write every answer in British English."
    history: list[dict[str, object]] = [
        {"id": "goal", "role": "user", "text": "Help tailor my resume."},
        {"id": "ack", "role": "assistant", "text": "I can help with that."},
        {"id": "natural-constraint", "role": "user", "text": constraint},
        {"id": "constraint-ack", "role": "assistant", "text": "Understood."},
    ]
    history.extend(
        {
            "id": f"constraint-filler-{index}",
            "role": "assistant" if index % 2 else "user",
            "text": (
                f"Older assistant discussion {index}: " + ("context filler. " * 90)
                if index % 2
                else "Repeated user filler used only to trigger compression."
            ),
        }
        for index in range(12)
    )

    messages = build_agent_messages(
        _request(prompt="Continue.", messages=history),
        _config(context_window_tokens=5_000, max_tokens=512),
        mode="streaming_final",
    )
    assert constraint in json.dumps(messages, ensure_ascii=False)


def test_agent_native_projection_preserves_assistant_proposals() -> None:
    proposal = "Option two keeps the Redis migration bullet."
    history: list[dict[str, object]] = [
        {
            "id": "proposal-user",
            "role": "user",
            "text": "Give me two ways to shorten the project section.",
        },
        {
            "id": "proposal-assistant",
            "role": "assistant",
            "text": f"Option one removes that detail. {proposal}",
        },
    ]
    for index in range(6):
        history.extend(
            [
                {
                    "id": f"proposal-filler-user-{index}",
                    "role": "user",
                    "text": "Continue reviewing the same project.",
                },
                {
                    "id": f"proposal-filler-assistant-{index}",
                    "role": "assistant",
                    "text": "Repeated assistant context. " * 70,
                },
            ],
        )

    messages = build_agent_messages(
        _request(prompt="Use option two.", messages=history),
        _config(context_window_tokens=5_000, max_tokens=512),
        mode="streaming_final",
    )
    assert proposal in json.dumps(messages, ensure_ascii=False)


def test_agent_context_keeps_structured_assistant_state_without_visible_text() -> None:
    request = _request(
        prompt="继续刚才的修改。",
        messages=[
            {
                "id": "silent-structured-response",
                "role": "assistant",
                "text": "",
                "response": {
                    "id": "silent-structured-response",
                    "role": "assistant",
                    "text": "",
                    "actions": ["execute"],
                    "transactionState": "committed",
                    "draft": {
                        "baseResume": {"basic": {}, "sections": []},
                        "status": "discarded",
                    },
                    "edits": [
                        {
                            "id": "silent-edit",
                            "title": "更新简介",
                            "target": "basic.summary",
                            "reason": "按用户要求精简。",
                            "status": "executed",
                            "operation": {
                                "type": "replace_field",
                                "path": "basic.summary",
                                "value": "精简后的简介",
                            },
                        },
                    ],
                    "sources": [
                        *[
                            {
                                "id": f"silent-source-{index}",
                                "title": f"Role page {index}",
                                "sourceType": "web",
                                "url": f"https://example.test/role/{index}",
                            }
                            for index in range(1, 7)
                        ],
                    ],
                },
            },
        ],
    )

    messages = build_agent_messages(
        request,
        _config(context_window_tokens=16_000, max_tokens=2_048),
        mode="streaming_final",
    )
    contexts = [
        json.loads(message["content"])["assistantResponseContext"]
        for message in messages
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"assistantResponseContext":')
    ]

    assert contexts[0]["messageId"] == "silent-structured-response"
    assert contexts[0]["edits"][0]["id"] == "silent-edit"
    assert contexts[0]["transactionState"] == "committed"
    assert contexts[0]["draftStatus"] == "discarded"
    assert [source["id"] for source in contexts[0]["sourceRefs"]] == [
        f"silent-source-{index}" for index in range(1, 7)
    ]


def test_final_workspace_never_replays_attachment_source_excerpts() -> None:
    draft = AgentChatMessage(
        id="assistant-source-privacy",
        role="assistant",
        text="Grounded result.",
        sources=[
            {
                "id": "source-private-file",
                "title": "Private evidence.pdf",
                "sourceType": "attachment",
                "excerpt": "private attachment evidence must remain current-turn only",
            },
            {
                "id": "source-public-role",
                "title": "Public role page",
                "sourceType": "web",
                "url": "https://example.test/role",
                "excerpt": "Public React requirement",
            },
        ],
    )

    messages = build_agent_messages(
        _request(prompt="Summarize the evidence."),
        _config(context_window_tokens=16_000, max_tokens=2_048),
        mode="streaming_final",
        draft=draft,
    )
    workspace_message = next(
        message
        for message in reversed(messages)
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"workspaceContext":')
    )
    workspace = json.loads(workspace_message["content"])["workspaceContext"]

    assert [source["id"] for source in workspace["citationSources"]] == [
        "source-public-role",
    ]
    assert "private attachment evidence" not in json.dumps(messages)
    assert workspace["citationSources"][0]["excerpt"] == "Public React requirement"


def test_agent_compressed_history_keeps_summary_and_exact_tail_stable() -> None:
    config = _config(context_window_tokens=6_000, max_tokens=512)
    history = [
        {
            "id": f"checkpoint-history-{index}",
            "role": "assistant" if index % 2 else "user",
            "text": (
                f"助手历史轮次 {index}：" + ("用于触发结构化压缩。" * 90)
                if index % 2
                else "用于压缩测试的重复用户上下文。"
            ),
        }
        for index in range(12)
    ]
    first_request = _request(
        prompt="检查当前项目。",
        messages=history,
    )
    checkpoint = AgentConversationCheckpoint(
        throughMessageId="checkpoint-history-5",
        summary="Goal: inspect the resume project section.",
    )
    first_request._loaded_conversation_checkpoint = checkpoint
    first_request._active_conversation_checkpoint = checkpoint
    first_projection = build_agent_messages(
        first_request,
        config,
        mode="streaming_final",
    )
    summary_message = next(
        message
        for message in first_projection
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"conversationSummary":')
    )
    agent_summary = json.loads(summary_message["content"])
    assert "conversationSummary" in agent_summary

    second_request = _request(
        prompt="继续检查技能部分。",
        current_id="checkpoint-second-user",
        messages=[
            *history,
            first_request.message.model_dump(mode="json"),
            {
                "id": "checkpoint-first-assistant",
                "role": "assistant",
                "text": "项目部分已检查。",
            },
        ],
    )
    # A new HTTP turn receives the last durable checkpoint from the
    # authoritative session loader. Reusing that exact boundary is what keeps
    # the preceding provider payload cacheable instead of rebuilding a moving
    # last-N window on every request.
    second_request._loaded_conversation_checkpoint = checkpoint
    second_request._active_conversation_checkpoint = checkpoint
    second_projection = build_agent_messages(
        second_request,
        config,
        mode="streaming_final",
    )

    # The persisted summary and native exact tail remain byte-stable. Full
    # tools/final-stream prompt prefix replay is covered by the workspace
    # snapshot tests, because this pure ``final`` mode does not persist one.
    stable_prefix_length = len(first_projection) - 2
    assert (
        second_projection[:stable_prefix_length]
        == first_projection[:stable_prefix_length]
    )
    assert second_projection[stable_prefix_length] == {
        "role": "user",
        "content": "检查当前项目。",
    }
    assert second_projection[stable_prefix_length + 1] == {
        "role": "assistant",
        "content": "项目部分已检查。",
    }
    assert second_projection[-1] == {
        "role": "user",
        "content": "继续检查技能部分。",
    }


def test_agent_loaded_checkpoint_never_reexpands_with_a_larger_model() -> None:
    compact_config = _config(context_window_tokens=6_000, max_tokens=512)
    history = [
        {
            "id": f"stable-boundary-{index}",
            "role": "assistant" if index % 2 else "user",
            "text": (
                f"助手历史轮次 {index}：" + ("用于触发结构化压缩。" * 90)
                if index % 2
                else (
                    "只应存在于已压缩前缀中的最早用户上下文。"
                    if index == 0
                    else "用于稳定边界测试的重复用户上下文。"
                )
            ),
        }
        for index in range(12)
    ]
    first_request = _request(prompt="检查当前项目。", messages=history)
    checkpoint = AgentConversationCheckpoint(
        throughMessageId="stable-boundary-5",
        summary="Goal: inspect the current project section.",
    )
    first_request._loaded_conversation_checkpoint = checkpoint
    first_request._active_conversation_checkpoint = checkpoint
    build_agent_messages(first_request, compact_config, mode="streaming_final")

    next_request = _request(
        prompt="继续检查。",
        current_id="checkpoint-larger-model-user",
        messages=history,
    )
    next_request._loaded_conversation_checkpoint = checkpoint
    next_request._active_conversation_checkpoint = checkpoint
    projection = build_agent_messages(
        next_request,
        _config(context_window_tokens=64_000, max_tokens=4_096),
        mode="streaming_final",
    )

    summary_message = next(
        message
        for message in projection
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"conversationSummary":')
    )
    assert json.loads(summary_message["content"])["conversationSummary"]
    assert next_request._active_conversation_checkpoint == checkpoint
    assert not any(
        message.get("content") == history[0]["text"] for message in projection
    )


def test_agent_pure_projection_never_advances_loaded_checkpoint() -> None:
    config = _config(context_window_tokens=3_250, max_tokens=512)
    history: list[dict[str, object]] = [
        {
            "id": f"headroom-history-{index}",
            "role": "assistant" if index % 2 else "user",
            "text": f"{index}:" + ("x" * 40),
        }
        for index in range(8)
    ]
    request = _request(prompt="initial prompt", messages=history)
    checkpoint = AgentConversationCheckpoint(
        throughMessageId="headroom-history-3",
        summary="Goal: preserve the current resume task.",
    )
    request._loaded_conversation_checkpoint = checkpoint
    request._active_conversation_checkpoint = checkpoint
    build_agent_messages(request, config, mode="streaming_final")
    initial_boundary = checkpoint.through_message_id

    for index in range(1, 6):
        history.extend(
            [
                request.message.model_dump(mode="json"),
                {
                    "id": f"headroom-assistant-{index}",
                    "role": "assistant",
                    "text": "answer-" + ("y" * 40),
                },
            ],
        )
        request = _request(
            prompt="用于 headroom 测试的重复当前请求。",
            current_id=f"headroom-user-{index}",
            messages=history,
        )
        request._loaded_conversation_checkpoint = checkpoint
        request._active_conversation_checkpoint = checkpoint
        build_agent_messages(request, config, mode="streaming_final")
        assert request._active_conversation_checkpoint == checkpoint
        assert request._active_conversation_checkpoint.through_message_id == (
            initial_boundary
        )


def test_agent_pure_projection_never_drops_recent_exact_messages() -> None:
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

    messages = build_agent_messages(
        request,
        _config(context_window_tokens=6_000, max_tokens=512),
        mode="streaming_final",
    )

    for recent in recent_messages:
        assert recent["text"] in json.dumps(messages, ensure_ascii=False)
