import json
from dataclasses import replace
from datetime import date

import pytest

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationCheckpoint,
    AgentDraftState,
)
from app.schemas.agent_settings import normalize_agent_settings
from app.services.agent.evidence import historical_prompt_evidence_ref
from app.services.agent.preferences import prepare_agent_request
from app.services.agent.runtime.messages import (
    AgentPromptCompiler,
    _context_budget,
    _tool_schema_token_reserve,
    agent_prompt_limits,
    estimate_agent_messages_tokens,
    fit_agent_model_turn_prompt,
)
from app.services.llm import AgentLlmConfig, LlmRequestError
from app.services.llm.output_budget import (
    estimate_prompt_tokens,
    input_estimation_safety_tokens,
    resolve_request_output_budget,
)
from app.services.llm.types import LlmPrompt


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
        modelConfig=None,
    )


def _ascii_prompt_at_or_below(token_limit: int) -> LlmPrompt:
    """Build a deterministic text prompt immediately below an estimated limit."""

    low = 0
    high = token_limit * 4
    while low < high:
        middle = (low + high + 1) // 2
        candidate = LlmPrompt(
            messages=[{"role": "user", "content": "x" * middle}],
        )
        if estimate_prompt_tokens(candidate) <= token_limit:
            low = middle
        else:
            high = middle - 1
    return LlmPrompt(messages=[{"role": "user", "content": "x" * low}])


def _checkpoint_context(events: list[dict[str, object]]) -> dict[str, object]:
    return {"trust": "untrusted_history_data", "events": events}


def test_agent_system_prompt_includes_current_date_for_time_sensitive_search() -> None:
    messages = (
        AgentPromptCompiler(
            _request(prompt="查找当前岗位。"),
            _config(context_window_tokens=16000, max_tokens=2048),
        )
        .build()
        .messages
    )

    assert messages[0]["role"] == "system"
    assert f"Current date: {date.today().isoformat()}." in messages[0]["content"]


def test_agent_context_projects_exact_history_and_current_prompt_once() -> None:
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

    messages = (
        AgentPromptCompiler(
            request, _config(context_window_tokens=16000, max_tokens=2048)
        )
        .build()
        .messages
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
        {
            "role": "user",
            "content": json.dumps(
                {
                    "historicalUserEvidence": {
                        "appliesToPreviousUserMessage": True,
                        "evidenceRef": historical_prompt_evidence_ref(
                            "agent-user-earlier-context",
                        ),
                    },
                },
                separators=(",", ":"),
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "assistantResponseContext": {
                        "text": "The second bullet is too long.",
                        "messageId": "agent-assistant-earlier-context",
                    },
                },
                separators=(",", ":"),
            ),
        },
        workspace_message,
        {"role": "user", "content": "Shorten the second project bullet."},
    ]
    assert json.dumps(messages, ensure_ascii=False).count(request.message.text) == 1


def test_agent_context_labels_only_historical_user_messages_as_evidence() -> None:
    messages = (
        AgentPromptCompiler(
            _request(
                prompt="Use the verified project fact from earlier.",
                messages=[
                    {
                        "id": "history-user-project-fact",
                        "role": "user",
                        "text": "Project fact: I used TypeScript.",
                    },
                    {
                        "id": "history-assistant-project-claim",
                        "role": "assistant",
                        "text": "You led the project.",
                    },
                ],
            ),
            _config(context_window_tokens=16000, max_tokens=2048),
        )
        .build()
        .messages
    )

    assert messages[1] == {
        "role": "user",
        "content": "Project fact: I used TypeScript.",
    }
    historical_user_evidence = json.loads(str(messages[2]["content"]))[
        "historicalUserEvidence"
    ]
    assert historical_user_evidence == {
        "appliesToPreviousUserMessage": True,
        "evidenceRef": historical_prompt_evidence_ref(
            "history-user-project-fact",
        ),
    }
    assert historical_prompt_evidence_ref(
        "history-assistant-project-claim",
    ) not in json.dumps(
        messages,
        ensure_ascii=False,
    )


def test_compacted_fact_keeps_a_copyable_original_user_evidence_ref() -> None:
    evidence_ref = historical_prompt_evidence_ref("compacted-project-fact")
    request = _request(
        prompt="Use the retained project fact.",
        messages=[
            {
                "id": "compacted-project-fact",
                "role": "user",
                "text": "Project fact: I used TypeScript.",
            },
            {
                "id": "compacted-project-ack",
                "role": "assistant",
                "text": "Fact recorded.",
            },
        ],
    )
    checkpoint = AgentConversationCheckpoint(
        throughMessageId="compacted-project-ack",
        summary=_checkpoint_context(
            [
                {
                    "role": "user",
                    "text": "Project fact: I used TypeScript.",
                    "evidenceRef": evidence_ref,
                },
            ],
        ),
    )
    messages = (
        AgentPromptCompiler(
            request, _config(context_window_tokens=16000, max_tokens=2048)
        )
        .build(checkpoint=checkpoint)
        .messages
    )
    serialized = json.dumps(messages, ensure_ascii=False)

    assert evidence_ref in serialized
    assert serialized.count("Project fact: I used TypeScript.") == 1
    assert not any(
        message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"historicalUserEvidence":')
        for message in messages
    )
    assert "conversationCheckpoint" in serialized


def test_agent_context_appends_exact_history_before_the_current_workspace() -> None:
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
    first_projection = AgentPromptCompiler(first_request, config).build().messages

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
                            "title": "resume_lookup",
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
    second_projection = AgentPromptCompiler(second_request, config).build().messages

    # The production tools/streaming-final compiler persists workspace
    # snapshots to guarantee byte-stable replay. This direct projection still
    # proves the provider sees exact product events, not one lossy conversation
    # blob.
    assert second_projection[:4] == first_projection[:4]
    assert second_projection[4] == {
        "role": "user",
        "content": "Review the project section.",
    }
    assistant_context = json.loads(second_projection[6]["content"])[
        "assistantResponseContext"
    ]
    assert assistant_context["messageId"] == "first-assistant-answer"
    assert assistant_context["text"] == "The second bullet can be shorter."
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


def test_projected_context_is_not_placed_in_the_system_message() -> None:
    messages = (
        AgentPromptCompiler(
            _request(prompt="Review this resume."),
            _config(context_window_tokens=16000, max_tokens=2048),
        )
        .build()
        .messages
    )

    assert messages[0]["role"] == "system"
    assert '"workspaceContext"' not in messages[0]["content"]
    assert any(
        message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"workspaceContext":')
        for message in messages[1:]
    )


def test_agent_context_sanitizes_every_exact_history_message() -> None:
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

    messages = (
        AgentPromptCompiler(
            request, _config(context_window_tokens=16000, max_tokens=2048)
        )
        .build()
        .messages
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
                resume={"basic": {"name": ""}, "sections": []},
                pendingCount=1,
                reviewItems=[
                    {
                        "id": "agent-review-private-draft",
                        "editIds": ["edit-private-draft"],
                        "status": "pending",
                    },
                ],
            ),
        },
    )

    messages = (
        AgentPromptCompiler(
            request, _config(context_window_tokens=16000, max_tokens=2048)
        )
        .build()
        .messages
    )

    serialized = json.dumps(messages, ensure_ascii=False)
    assert "王小明" not in serialized
    assert "[redacted_name]" in serialized


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

    messages = (
        AgentPromptCompiler(
            request, _config(context_window_tokens=16000, max_tokens=2048)
        )
        .build()
        .messages
    )
    serialized = json.dumps(messages, ensure_ascii=False)

    assert "project-report.pdf" in serialized
    assert "raw private content must not be replayed" not in serialized
    historical_metadata = next(
        json.loads(str(message["content"]))["historicalAttachments"]
        for message in messages
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"historicalAttachments":')
    )
    assert historical_metadata == [
        {
            "id": "private-report",
            "filename": "project-report.pdf",
            "kind": "text",
        },
    ]
    assistant_context = next(
        json.loads(str(message["content"]))["assistantResponseContext"]
        for message in messages
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"assistantResponseContext":')
    )
    assert assistant_context["text"] == "我已读取项目报告。"


def test_recent_assistant_prose_is_context_not_a_behavior_example() -> None:
    stale_claim = "预览区会先显示临时草稿，确认后才会正式修改。"
    messages = (
        AgentPromptCompiler(
            _request(
                prompt="现在请改写腾讯实习经历。",
                messages=[
                    {
                        "id": "previous-edit-request",
                        "role": "user",
                        "text": "改写腾讯实习经历。",
                    },
                    {
                        "id": "previous-false-completion",
                        "role": "assistant",
                        "text": stale_claim,
                        "response": {
                            "id": "previous-false-completion",
                            "role": "assistant",
                            "text": stale_claim,
                            "tools": [],
                            "edits": [],
                        },
                    },
                ],
            ),
            _config(context_window_tokens=16000, max_tokens=2048),
        )
        .build()
        .messages
    )

    assert not any(message["role"] == "assistant" for message in messages)
    context = next(
        json.loads(str(message["content"]))["assistantResponseContext"]
        for message in messages
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"assistantResponseContext":')
    )
    assert context == {
        "text": stale_claim,
        "messageId": "previous-false-completion",
    }


def test_each_model_turn_compacts_old_web_excerpts_without_moving_prefix() -> None:
    request = _request(prompt="Research the target role.")
    config = _config(context_window_tokens=32_000, max_tokens=2_048)
    prompt = AgentPromptCompiler(request, config).build()
    prefix_counts = prompt.stable_prefix_message_counts
    old_excerpt = "old evidence " * 12_000
    latest_excerpt = "latest evidence must remain exact"

    for call_id, excerpt in (
        ("old-fetch", old_excerpt),
        ("latest-fetch", latest_excerpt),
    ):
        prompt.messages.extend(
            [
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": "web_fetch",
                                "arguments": json.dumps(
                                    {"url": f"https://example.test/{call_id}"},
                                ),
                            },
                        },
                    ],
                },
                {
                    "role": "tool",
                    "tool_call_id": call_id,
                    "content": json.dumps(
                        {
                            "state": "output-available",
                            "output": {
                                "data": {
                                    "results": [
                                        {
                                            "sourceId": f"source-{call_id}",
                                            "title": f"Result {call_id}",
                                            "url": f"https://example.test/{call_id}",
                                            "sourceKind": "fetched_page",
                                            "excerpt": excerpt,
                                            "excerptBoundary": {
                                                "start": 0,
                                                "end": len(excerpt),
                                            },
                                        },
                                    ],
                                },
                            },
                        },
                    ),
                },
            ],
        )

    limits = agent_prompt_limits(request, config)
    assert limits is not None
    assert estimate_agent_messages_tokens(prompt.messages) > limits.input_tokens

    fitted = fit_agent_model_turn_prompt(request, config, prompt)

    assert fitted.stable_prefix_message_counts == prefix_counts
    assert fitted.messages[: prefix_counts[-1]] == prompt.messages[: prefix_counts[-1]]
    old_result = json.loads(str(fitted.messages[-3]["content"]))
    latest_result = json.loads(str(fitted.messages[-1]["content"]))
    assert "excerpt" not in old_result["output"]["data"]["results"][0]
    assert latest_result["output"]["data"]["results"][0]["excerpt"] == (latest_excerpt)
    assert estimate_agent_messages_tokens(fitted.messages) <= limits.trigger_tokens


def test_each_model_turn_preserves_every_observation_in_the_latest_parallel_batch() -> (
    None
):
    request = _request(prompt="Compare both current sources.")
    config = _config(context_window_tokens=32_000, max_tokens=2_048)
    prompt = AgentPromptCompiler(request, config).build()
    limits = agent_prompt_limits(request, config)
    assert limits is not None

    # Bring the prepared turn close to its compaction trigger, as a real long
    # conversation would be immediately before two bounded fetch results land.
    base_tokens = estimate_agent_messages_tokens(prompt.messages)
    padding_tokens = max(0, limits.trigger_tokens - base_tokens - 800)
    system_content = str(prompt.messages[0]["content"])
    prompt.messages[0]["content"] = system_content + ("x" * padding_tokens * 4)

    excerpts = {
        "fetch-a": "A" * 2_400,
        "fetch-b": "B" * 2_400,
    }
    prompt.messages.append(
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "web_fetch",
                        "arguments": json.dumps(
                            {"url": f"https://example.test/{call_id}"},
                        ),
                    },
                }
                for call_id in excerpts
            ],
        },
    )
    for call_id, excerpt in excerpts.items():
        prompt.messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "content": json.dumps(
                    {
                        "output": {
                            "data": {
                                "results": [
                                    {
                                        "sourceId": f"source-{call_id}",
                                        "url": f"https://example.test/{call_id}",
                                        "excerpt": excerpt,
                                    },
                                ],
                            },
                        },
                    },
                ),
            },
        )

    estimated_tokens = estimate_agent_messages_tokens(prompt.messages)
    assert limits.trigger_tokens < estimated_tokens <= limits.input_tokens

    fitted = fit_agent_model_turn_prompt(request, config, prompt)

    for message, expected_excerpt in zip(
        fitted.messages[-2:],
        excerpts.values(),
        strict=True,
    ):
        result = json.loads(str(message["content"]))
        assert result["output"]["data"]["results"][0]["excerpt"] == (expected_excerpt)


def test_each_model_turn_keeps_a_bounded_latest_jd_excerpt_at_the_hard_limit() -> None:
    request = _request(prompt="Tailor the resume to this current job description.")
    config = _config(context_window_tokens=16_000, max_tokens=2_048)
    prompt = AgentPromptCompiler(request, config).build()
    limits = agent_prompt_limits(request, config)
    assert limits is not None

    base_tokens = estimate_agent_messages_tokens(prompt.messages)
    padding_tokens = max(0, limits.input_tokens - base_tokens - 1_000)
    prompt.messages[0]["content"] = str(prompt.messages[0]["content"]) + (
        "x" * padding_tokens * 4
    )
    excerpt = "React TypeScript accessibility " * 500
    prompt.messages.extend(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "latest-jd",
                        "type": "function",
                        "function": {
                            "name": "web_fetch",
                            "arguments": '{"url":"https://example.test/job"}',
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "latest-jd",
                "content": json.dumps(
                    {
                        "output": {
                            "results": [
                                {
                                    "sourceId": "source-latest-jd",
                                    "title": "Frontend Engineer",
                                    "url": "https://example.test/job",
                                    "sourceKind": "fetched_page",
                                    "publishedDate": "2026-08-20",
                                    "validThrough": "2026-09-20",
                                    "excerpt": excerpt,
                                },
                            ],
                        },
                    },
                ),
            },
        ],
    )

    fitted = fit_agent_model_turn_prompt(request, config, prompt)
    result = json.loads(str(fitted.messages[-1]["content"]))["output"]["results"][0]

    assert result["excerpt"]
    assert len(result["excerpt"]) == 800
    assert result["excerptTruncated"] is True
    assert result["publishedDate"] == "2026-08-20"
    assert result["validThrough"] == "2026-09-20"
    assert estimate_agent_messages_tokens(fitted.messages) <= limits.input_tokens


def test_each_model_turn_rejects_an_uncompactable_oversized_observation() -> None:
    request = _request(prompt="Inspect the tool result.")
    config = _config(context_window_tokens=16_000, max_tokens=2_048)
    prompt = AgentPromptCompiler(request, config).build()
    prompt.messages.extend(
        [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "opaque-result",
                        "type": "function",
                        "function": {
                            "name": "web_fetch",
                            "arguments": "{}",
                        },
                    },
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "opaque-result",
                "content": json.dumps({"output": {"opaque": "x" * 80_000}}),
            },
        ],
    )

    with pytest.raises(LlmRequestError, match="Tool observations exceed"):
        fit_agent_model_turn_prompt(request, config, prompt)


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

    messages = (
        AgentPromptCompiler(
            request, _config(context_window_tokens=16000, max_tokens=2048)
        )
        .build()
        .messages
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

    messages = (
        AgentPromptCompiler(
            request, _config(context_window_tokens=16000, max_tokens=2048)
        )
        .build()
        .messages
    )
    serialized = json.dumps(messages, ensure_ascii=False)

    assert filename not in serialized
    assert expected_filename in serialized


def test_agent_context_budget_separates_compaction_tools_and_safety_margin() -> None:
    config = _config(context_window_tokens=32_000, max_tokens=2_048)
    request = _request(prompt="根据我的材料修改项目经历")

    tool_schema_tokens = _tool_schema_token_reserve(
        request,
        config,
    )
    budget = _context_budget(config, tool_schema_tokens=tool_schema_tokens)

    assert budget is not None
    assert budget.compaction_headroom_tokens == 2_048
    assert budget.tool_schema_tokens > 0
    assert budget.safety_margin_tokens > 0
    assert budget.input_tokens == (
        32_000 - budget.tool_schema_tokens - budget.safety_margin_tokens - 1
    )
    assert budget.trigger_tokens == int(
        (budget.input_tokens - budget.compaction_headroom_tokens) * 0.85,
    )


def test_tool_schema_reserve_uses_the_canonical_request_catalog() -> None:
    config = _config(context_window_tokens=32_000, max_tokens=2_048)
    request = _request(prompt="按需优化这份简历。")
    suggest_only = prepare_agent_request(
        request,
        normalize_agent_settings({"confirmationMode": "suggestOnly"}),
    )

    all_tools = _tool_schema_token_reserve(request, config)
    read_tools = _tool_schema_token_reserve(suggest_only, config)

    assert 0 < read_tools < all_tools


def test_agent_context_budget_clamps_auto_reserve_for_a_small_context_window() -> None:
    budget = _context_budget(
        _config(context_window_tokens=16000, max_tokens=None), tool_schema_tokens=0
    )

    assert budget is not None
    # Manual custom context is shared. After retaining estimation safety, one
    # provider-output token, and a separate 4K hard-input tail, the remaining
    # room becomes optional compaction headroom.
    assert budget.compaction_headroom_tokens == budget.input_tokens - 4_096
    assert budget.safety_margin_tokens == input_estimation_safety_tokens(16_000)
    assert budget.input_tokens == 16_000 - 256 - 1


def test_planner_accepted_prompt_always_has_room_at_dispatch() -> None:
    config = _config(context_window_tokens=16_000, max_tokens=2_048)
    budget = _context_budget(config, tool_schema_tokens=0)

    assert budget is not None
    prompt = _ascii_prompt_at_or_below(budget.input_tokens)
    assert estimate_prompt_tokens(prompt) <= budget.input_tokens
    assert estimate_prompt_tokens(prompt) >= budget.input_tokens - 1

    resolved = resolve_request_output_budget(config, prompt)

    # Manual custom context is shared; an input accepted at the hard edge still
    # retains a valid (possibly dynamically clamped) output allowance.
    assert resolved.request_max_output_tokens is not None
    assert resolved.request_max_output_tokens >= 1


def test_agent_context_budget_uses_the_provider_independent_auto_reserve() -> None:
    config = replace(
        _config(context_window_tokens=32_000, max_tokens=None),
        provider="anthropic",
        provider_kind="cloud",
        api_family="anthropic_messages",
        base_url="https://api.anthropic.com/v1",
        thinking_control="native_auto",
    )

    budget = _context_budget(config, tool_schema_tokens=0)

    assert budget is not None
    assert budget.compaction_headroom_tokens == 16_384


def test_agent_pure_projection_keeps_history_until_context_preparation() -> None:
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

    messages = (
        AgentPromptCompiler(
            request, _config(context_window_tokens=6000, max_tokens=512)
        )
        .build()
        .messages
    )
    serialized = json.dumps(messages, ensure_ascii=False)

    assert not any(
        message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"conversationCheckpoint":')
        for message in messages
    )
    assert "目标：申请分布式系统方向的研究生项目。" in serialized
    assert "最近精确轮次 3" in serialized
    assert "Load-test evidence" not in serialized


def test_agent_exact_projection_preserves_unclassified_user_constraints() -> None:
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

    messages = (
        AgentPromptCompiler(
            _request(prompt="Continue.", messages=history),
            _config(context_window_tokens=5000, max_tokens=512),
        )
        .build()
        .messages
    )
    assert constraint in json.dumps(messages, ensure_ascii=False)


def test_agent_exact_projection_preserves_assistant_proposals() -> None:
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

    messages = (
        AgentPromptCompiler(
            _request(prompt="Use option two.", messages=history),
            _config(context_window_tokens=5000, max_tokens=512),
        )
        .build()
        .messages
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
                    "transactionState": "committed",
                    "draft": {
                        "baseResume": {"basic": {}, "sections": []},
                        "reviewItems": [
                            {
                                "id": "agent-review-silent-edit",
                                "editIds": ["silent-edit"],
                                "status": "discarded",
                            },
                        ],
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

    messages = (
        AgentPromptCompiler(
            request, _config(context_window_tokens=16000, max_tokens=2048)
        )
        .build()
        .messages
    )
    contexts = [
        json.loads(message["content"])["assistantResponseContext"]
        for message in messages
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"assistantResponseContext":')
    ]

    assert contexts[0]["messageId"] == "silent-structured-response"
    assert contexts[0]["transactionState"] == "committed"
    assert contexts[0]["draftReview"] == {
        "pendingCount": 0,
        "appliedCount": 0,
        "discardedCount": 1,
    }
    assert "edits" not in contexts[0]
    assert [source["id"] for source in contexts[0]["sourceRefs"]] == [
        f"silent-source-{index}" for index in range(1, 7)
    ]


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
        summary=_checkpoint_context([]),
    )
    first_projection = (
        AgentPromptCompiler(first_request, config).build(checkpoint=checkpoint).messages
    )
    summary_message = next(
        message
        for message in first_projection
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"conversationCheckpoint":')
    )
    agent_summary = json.loads(summary_message["content"])
    assert "conversationCheckpoint" in agent_summary

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
    second_projection = (
        AgentPromptCompiler(second_request, config)
        .build(checkpoint=checkpoint)
        .messages
    )

    # The persisted summary and exact tail remain byte-stable. Full
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
    historical_evidence = json.loads(
        str(second_projection[stable_prefix_length + 1]["content"]),
    )["historicalUserEvidence"]
    assert historical_evidence["evidenceRef"] == historical_prompt_evidence_ref(
        "agent-user-current-context",
    )
    assistant_context = json.loads(
        str(second_projection[stable_prefix_length + 2]["content"]),
    )["assistantResponseContext"]
    assert assistant_context["text"] == "项目部分已检查。"
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
        summary=_checkpoint_context([]),
    )
    AgentPromptCompiler(first_request, compact_config).build(checkpoint=checkpoint)

    next_request = _request(
        prompt="继续检查。",
        current_id="checkpoint-larger-model-user",
        messages=history,
    )
    projection = (
        AgentPromptCompiler(
            next_request, _config(context_window_tokens=64000, max_tokens=4096)
        )
        .build(checkpoint=checkpoint)
        .messages
    )

    summary_message = next(
        message
        for message in projection
        if message["role"] == "user"
        and isinstance(message["content"], str)
        and message["content"].startswith('{"conversationCheckpoint":')
    )
    assert json.loads(summary_message["content"])["conversationCheckpoint"]
    assert not any(
        message.get("content") == history[0]["text"] for message in projection
    )


def test_agent_pure_projection_never_advances_loaded_checkpoint() -> None:
    # Keep the same useful prompt headroom after the runtime's mandatory 4K
    # transport safety reserve was made explicit.
    config = _config(context_window_tokens=7_100, max_tokens=512)
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
        summary=_checkpoint_context([]),
    )
    AgentPromptCompiler(request, config).build(checkpoint=checkpoint)
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
        AgentPromptCompiler(request, config).build(checkpoint=checkpoint)
        assert checkpoint.through_message_id == initial_boundary


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

    messages = (
        AgentPromptCompiler(
            request, _config(context_window_tokens=6000, max_tokens=512)
        )
        .build()
        .messages
    )

    for recent in recent_messages:
        assert recent["text"] in json.dumps(messages, ensure_ascii=False)
