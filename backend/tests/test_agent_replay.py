from app.schemas.agent import AgentChatRequest
from app.services.agent import WebReference
from app.services.agent.policy import capability_policy_for_request
from app.services.agent.tools import registry as tool_registry
from tests.agent_replay import AgentReplayScenario, ReplayToolCall, run_agent_replay


def test_replay_explain_draft_success() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="explain_draft_success",
            request=AgentChatRequest(
                prompt="解释刚才的草稿改了什么",
                locale="zh",
                resume={"basic": {}, "sections": []},
                draftState={
                    "id": "draft-current",
                    "status": "pending",
                    "resume": {"basic": {}, "sections": []},
                    "editCount": 1,
                    "edits": [
                        {
                            "id": "edit-summary",
                            "title": "优化简介",
                            "target": "basic.summary",
                            "replacement": "新的简介",
                        },
                    ],
                    "diffs": [],
                },
            ),
            tool_calls=[ReplayToolCall("draft_diff_summary")],
        ),
    )

    assert result.tools[0].state == "output-available"
    assert result.runner.edits == []


def test_replay_suggest_only_blocks_draft() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="suggest_only_blocks_draft",
            request=AgentChatRequest(
                prompt="优化个人简介",
                locale="zh",
                resume={"basic": {"summary": "已有简介"}, "sections": []},
                settings={"confirmationMode": "suggestOnly"},
            ),
            tool_calls=[
                ReplayToolCall(
                    "edit_execute",
                    {
                        "edits": [
                            {
                                "title": "优化简介",
                                "target": "basic.summary",
                                "operation": {
                                    "type": "replace_field",
                                    "path": "basic.summary",
                                    "value": "新的简介",
                                },
                            },
                        ],
                    },
                ),
            ],
        ),
    )

    assert result.tools[0].state == "output-error"
    assert result.observations[0]["output"]["blocked"] is True
    assert result.runner.draft_resume["basic"]["summary"] == "已有简介"


def test_replay_pii_write_blocked() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="pii_hidden_and_write_blocked",
            request=AgentChatRequest(
                prompt="优化联系方式",
                locale="zh",
                resume={
                    "basic": {
                        "email": "xiaoming@example.com",
                        "phone": "13800138000",
                    },
                    "sections": [],
                },
            ),
            tool_calls=[
                ReplayToolCall(
                    "edit_execute",
                    {
                        "edits": [
                            {
                                "title": "更新邮箱",
                                "target": "basic.email",
                                "operation": {
                                    "type": "replace_field",
                                    "path": "basic.email",
                                    "value": "new@example.com",
                                },
                            },
                        ],
                    },
                ),
            ],
        ),
    )

    assert result.tools[0].state == "output-error"
    assert result.runner.edits == []


def test_replay_explain_draft_no_pending_blocks_diff_tool() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="explain_draft_no_pending",
            request=AgentChatRequest(
                prompt="解释刚才的草稿",
                locale="zh",
                resume={"basic": {}, "sections": []},
            ),
            tool_calls=[ReplayToolCall("draft_diff_summary")],
        ),
    )

    assert result.tools[0].state == "output-error"
    assert result.observations[0]["output"]["blocked"] is True


def test_replay_rewrite_project_with_lookup() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="rewrite_project_with_lookup",
            request=AgentChatRequest(
                prompt="缩短 ResuMate 项目描述",
                locale="zh",
                resume={
                    "basic": {},
                    "sections": [
                        {
                            "id": "project",
                            "kind": "project",
                            "items": [
                                {
                                    "id": "project-1",
                                    "title": "ResuMate",
                                    "description": "支持多轮 Agent 简历草稿编辑。",
                                },
                            ],
                        },
                    ],
                },
            ),
            tool_calls=[
                ReplayToolCall("resume_lookup", {"query": "ResuMate"}),
                ReplayToolCall(
                    "edit_execute",
                    {
                        "edits": [
                            {
                                "title": "缩短项目描述",
                                "target": "sections.project.items.project-1",
                                "operation": {
                                    "type": "update_item",
                                    "sectionId": "project",
                                    "itemId": "project-1",
                                    "patch": {"description": "AI 简历草稿编辑器。"},
                                },
                            },
                        ],
                    },
                ),
            ],
        ),
    )

    assert result.tools[0].title == "resume_lookup"
    assert result.tools[1].state == "output-available"
    assert result.runner.edits


def test_replay_explicit_web_fetch_project_reference(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.agent._fetch_web_reference",
        lambda _url: WebReference(
            title="Public project page",
            excerpt="Public project reference with architecture and outcomes.",
        ),
    )

    result = run_agent_replay(
        AgentReplayScenario(
            name="explicit_web_fetch_project_reference",
            request=AgentChatRequest(
                prompt="参考这个公开项目链接优化表达：https://example.test/project",
                locale="zh",
                resume={"basic": {}, "sections": []},
            ),
            tool_calls=[
                ReplayToolCall(
                    "web_fetch",
                    {
                        "url": "https://example.test/project",
                        "purpose": "project_reference",
                    },
                ),
            ],
        ),
    )

    assert result.tools[0].title == "web_fetch"
    assert result.tools[0].state == "output-available"
    assert result.observations[0]["output"]["canSupportResumeFacts"] is True


def test_replay_customfield_github_not_auto_fetched() -> None:
    request = AgentChatRequest(
        prompt="优化项目经历",
        locale="zh",
        resume={
            "basic": {
                "customFields": [
                    {
                        "label": "GitHub",
                        "value": "https://github.com/example/project",
                    },
                ],
            },
            "sections": [],
        },
    )

    policy = capability_policy_for_request(request)
    schemas = tool_registry.agent_tool_schemas_for_names(policy.allowed_tools)
    schema_names = {schema["function"]["name"] for schema in schemas}

    assert "web_fetch" not in schema_names


def test_replay_unknown_url_purpose_blocked() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="unknown_url_purpose_blocked",
            request=AgentChatRequest(
                prompt="参考这个链接：https://example.test/page",
                locale="zh",
                resume={"basic": {}, "sections": []},
            ),
            tool_calls=[
                ReplayToolCall(
                    "web_fetch",
                    {"url": "https://example.test/page"},
                ),
            ],
        ),
    )

    assert result.tools[0].state == "output-error"
    assert result.observations[0]["output"]["blocked"] is True


def test_replay_delete_requires_explicit_intent() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="delete_requires_explicit_intent",
            request=AgentChatRequest(
                prompt="优化项目经历",
                locale="zh",
                resume={
                    "basic": {},
                    "sections": [
                        {
                            "id": "project",
                            "kind": "project",
                            "items": [{"id": "project-1", "title": "ResuMate"}],
                        },
                    ],
                },
            ),
            tool_calls=[
                ReplayToolCall(
                    "edit_execute",
                    {
                        "edits": [
                            {
                                "title": "删除项目",
                                "target": "sections.project.items.project-1",
                                "operation": {
                                    "type": "delete_item",
                                    "sectionId": "project",
                                    "itemId": "project-1",
                                },
                            },
                        ],
                    },
                ),
            ],
        ),
    )

    assert result.tools[0].state == "output-error"
    assert result.observations[0]["output"]["blocked"] is True
    assert result.runner.edits == []


def test_replay_draft_rewrite_uses_pending_draft() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="draft_rewrite_uses_pending_draft",
            request=AgentChatRequest(
                prompt="把刚才的草稿再短一点",
                locale="zh",
                resume={"basic": {"summary": "正式简历简介"}, "sections": []},
                draftState={
                    "id": "draft-current",
                    "status": "pending",
                    "resume": {
                        "basic": {"summary": "待确认草稿简介"},
                        "sections": [],
                    },
                    "editCount": 1,
                    "edits": [],
                    "diffs": [],
                },
            ),
            tool_calls=[
                ReplayToolCall(
                    "draft_rewrite",
                    {
                        "edits": [
                            {
                                "title": "缩短草稿简介",
                                "target": "basic.summary",
                                "operation": {
                                    "type": "replace_field",
                                    "path": "basic.summary",
                                    "value": "短简介",
                                },
                            },
                        ],
                    },
                ),
            ],
        ),
    )

    assert result.tools[0].state == "output-available"
    assert result.runner.draft_resume["basic"]["summary"] == "短简介"
