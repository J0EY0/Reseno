import json

from app.schemas.agent import AgentChatRequest
from app.schemas.agent_settings import normalize_agent_settings
from app.services.agent import WebReference
from app.services.agent.attachments import store_agent_attachment
from app.services.agent.policy import capability_policy_for_request
from app.services.agent.preferences import prepare_agent_request
from app.services.agent.runtime.events import AgentRunEvent
from app.services.agent.tools import registry as tool_registry
from tests.agent_replay import AgentReplayScenario, ReplayToolCall, run_agent_replay


def _v2_basic(**overrides: object) -> dict[str, object]:
    """Return the exact Resume V2 basic shape required by edit validation."""
    basic: dict[str, object] = {
        "name": "",
        "headline": "",
        "phone": "",
        "email": "",
        "location": "",
        "avatar": "",
        "summary": "",
        "customFields": [],
    }
    basic.update(overrides)
    return basic


def _v2_project_item(
    *,
    name: str = "ResuMate",
    description: str = "",
    highlights: list[str] | None = None,
) -> dict[str, object]:
    """Keep project fixtures on the canonical semantic item fields."""
    return {
        "id": "project-1",
        "name": name,
        "role": "",
        "techStack": [],
        "period": "",
        "url": "",
        "description": description,
        "highlights": list(highlights or []),
    }


def event_types(events: list[AgentRunEvent]) -> list[str]:
    return [event.type for event in events]


def events_of_type(
    events: list[AgentRunEvent],
    event_type: str,
) -> list[AgentRunEvent]:
    return [event for event in events if event.type == event_type]


def test_replay_explain_draft_success() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="explain_draft_success",
            request=AgentChatRequest(
                prompt="解释刚才的草稿改了什么",
                locale="zh",
                resume={"schemaVersion": 2, "basic": {}, "sections": []},
                draftState={
                    "id": "draft-current",
                    "status": "pending",
                    "resume": {"schemaVersion": 2, "basic": {}, "sections": []},
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
    assert event_types(result.events) == [
        "run_start",
        "turn_start",
        "tool_start",
        "tool_done",
        "run_done",
    ]
    assert result.events[-1].outcome == "success"


def test_replay_draft_diff_summary_includes_reference_map() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="draft_diff_reference_map",
            request=AgentChatRequest(
                prompt="解释刚才第二条修改",
                locale="zh",
                resume={"schemaVersion": 2, "basic": {}, "sections": []},
                draftState={
                    "id": "draft-current",
                    "status": "pending",
                    "resume": {"schemaVersion": 2, "basic": {}, "sections": []},
                    "editCount": 2,
                    "edits": [
                        {
                            "id": "edit-summary",
                            "title": "优化简介",
                            "target": "basic.summary",
                            "replacement": "新的简介",
                            "operation": {"type": "replace_field"},
                            "status": "executed",
                        },
                        {
                            "id": "edit-project",
                            "title": "优化项目",
                            "target": "sections.project.items.project-1",
                            "replacement": "新的项目表述",
                            "operation": {"type": "update_item"},
                            "status": "executed",
                        },
                    ],
                    "diffs": [
                        {
                            "id": "diff-summary",
                            "operationId": "edit-summary",
                            "path": "basic.summary",
                            "label": "简介",
                            "after": "新的简介",
                        },
                        {
                            "id": "diff-project",
                            "operationId": "edit-project",
                            "path": "sections.project.items.project-1",
                            "label": "项目",
                            "after": "新的项目表述",
                        },
                    ],
                },
            ),
            tool_calls=[ReplayToolCall("draft_diff_summary")],
        ),
    )

    output = result.observations[0]["output"]

    assert output["edits"][1]["index"] == 2
    assert output["referenceMap"][1] == {
        "index": 2,
        "editId": "edit-project",
        "target": "sections.project.items.project-1",
        "operationType": "update_item",
    }
    assert output["diffs"][1]["operationId"] == "edit-project"
    assert output["diffs"][1]["path"] == "sections.project.items.project-1"


def test_replay_suggest_only_blocks_draft() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="suggest_only_blocks_draft",
            request=prepare_agent_request(
                AgentChatRequest(
                    prompt="优化个人简介",
                    locale="zh",
                    resume={
                        "schemaVersion": 2,
                        "basic": {"summary": "已有简介"},
                        "sections": [],
                    },
                ),
                normalize_agent_settings({"confirmationMode": "suggestOnly"}),
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
    tool_done = events_of_type(result.events, "tool_done")[0]
    assert tool_done.outcome == "blocked"
    assert result.events[-1].outcome == "error"


def test_replay_pii_write_blocked() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="pii_hidden_and_write_blocked",
            request=AgentChatRequest(
                prompt="优化联系方式",
                locale="zh",
                resume={
                    "schemaVersion": 2,
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


def test_replay_external_evidence_rejects_entire_edit_batch() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="external_evidence_rejects_batch",
            request=AgentChatRequest(
                prompt="优化个人简介",
                locale="zh",
                resume={
                    "schemaVersion": 2,
                    "basic": _v2_basic(summary="已有简介"),
                    "sections": [],
                },
            ),
            tool_calls=[
                ReplayToolCall(
                    "edit_execute",
                    {
                        "edits": [
                            {
                                "title": "优化简介",
                                "target": "basic.summary",
                                "evidenceRefs": ["web:https://example.com/profile"],
                                "operation": {
                                    "type": "replace_field",
                                    "path": "basic.summary",
                                    "value": "未经用户材料支持的新简介",
                                },
                            },
                        ],
                    },
                ),
            ],
        ),
    )

    output = result.observations[0]["output"]

    assert result.tools[0].state == "output-error"
    assert output["fullBatchRequired"] is True
    assert output["rejectedEdits"][0]["qualityIssue"]["code"] == "invalid_edit_evidence"
    assert result.runner.edits == []
    assert result.runner.draft_resume["basic"]["summary"] == "已有简介"


def test_replay_explain_draft_no_pending_blocks_diff_tool() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="explain_draft_no_pending",
            request=AgentChatRequest(
                prompt="解释刚才的草稿",
                locale="zh",
                resume={"schemaVersion": 2, "basic": {}, "sections": []},
            ),
            tool_calls=[ReplayToolCall("draft_diff_summary")],
        ),
    )

    assert result.tools[0].state == "output-error"
    assert result.observations[0]["output"]["blocked"] is True


def test_replay_finish_blocked_records_missing_context() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="finish_blocked_missing_context",
            request=AgentChatRequest(
                prompt="解释刚才的草稿",
                locale="zh",
                resume={"schemaVersion": 2, "basic": {}, "sections": []},
            ),
            tool_calls=[
                ReplayToolCall(
                    "finish",
                    {
                        "status": "blocked",
                        "reason": "需要先有待确认草稿。",
                        "missing": [
                            "pending_draft",
                            "source_material",
                            "target_role",
                            "user_evidence",
                            "unknown_value",
                        ],
                    },
                ),
            ],
        ),
    )

    message = result.runner.build_message(message_id="agent-msg-test")

    assert result.tools[0].state == "output-available"
    assert result.observations[0]["output"]["missing"] == [
        "pending_draft",
        "source_material",
        "target_role",
        "user_evidence",
    ]
    assert result.runner.finish_missing == [
        "pending_draft",
        "source_material",
        "target_role",
        "user_evidence",
    ]
    assert message.finish_missing == [
        "pending_draft",
        "source_material",
        "target_role",
        "user_evidence",
    ]
    assert event_types(result.events) == [
        "run_start",
        "turn_start",
        "tool_start",
        "tool_done",
        "finish",
        "run_done",
    ]
    assert result.events[-2].status == "blocked"
    assert result.events[-2].missing == (
        "pending_draft",
        "source_material",
        "target_role",
        "user_evidence",
    )
    assert result.events[-1].outcome == "blocked"


def test_replay_rewrite_project_with_lookup() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="rewrite_project_with_lookup",
            request=AgentChatRequest(
                prompt="缩短 ResuMate 项目描述",
                locale="zh",
                resume={
                    "schemaVersion": 2,
                    "basic": _v2_basic(),
                    "sections": [
                        {
                            "id": "project",
                            "kind": "project",
                            "title": "项目经历",
                            "items": [
                                _v2_project_item(
                                    description="支持多轮 Agent 简历草稿编辑。",
                                ),
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
    edit_tool_done = events_of_type(result.events, "tool_done")[1]
    edits_ready = events_of_type(result.events, "edits_ready")[0]
    assert edit_tool_done.edit_count == 1
    assert edit_tool_done.operation_types == ("update_item",)
    assert edits_ready.edit_count == 1
    assert edits_ready.operation_types == ("update_item",)
    assert result.events[-1].outcome == "success"


def test_replay_reports_draft_quality_issues_without_raw_content() -> None:
    long_highlight = (
        "Improved resume editing workflow with measurable product impact. " * 4
    )

    result = run_agent_replay(
        AgentReplayScenario(
            name="quality_issue_long_highlight",
            request=AgentChatRequest(
                prompt="优化项目经历",
                locale="zh",
                resume={
                    "schemaVersion": 2,
                    "basic": _v2_basic(),
                    "sections": [
                        {
                            "id": "project",
                            "kind": "project",
                            "title": "项目经历",
                            "items": [
                                _v2_project_item(description="AI 简历编辑器。"),
                            ],
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
                                "title": "补充项目成果",
                                "target": "sections.project.items.project-1",
                                "operation": {
                                    "type": "update_item",
                                    "sectionId": "project",
                                    "itemId": "project-1",
                                    "patch": {"highlights": [long_highlight]},
                                },
                            },
                        ],
                    },
                ),
            ],
        ),
    )

    output = result.observations[0]["output"]
    issues = output["qualityIssues"]
    encoded_issues = json.dumps(issues)

    assert output["qualityIssueCount"] == 1
    assert issues[0]["code"] == "long_highlight"
    assert issues[0]["target"] == "sections.project.items.project-1"
    assert issues[0]["field"] == "highlights"
    assert long_highlight.strip() not in encoded_issues
    assert events_of_type(result.events, "tool_done")[0].quality_issue_count == 1


def test_replay_reports_style_quality_issues() -> None:
    long_summary = "Frontend engineer building AI resume editing workflows. " * 8
    highlights = [f"Built validated workflow improvement {index}" for index in range(6)]

    result = run_agent_replay(
        AgentReplayScenario(
            name="quality_issue_style_constraints",
            request=AgentChatRequest(
                prompt="优化简介和项目经历",
                locale="zh",
                resume={
                    "schemaVersion": 2,
                    "basic": _v2_basic(summary="已有简介。"),
                    "sections": [
                        {
                            "id": "project",
                            "kind": "project",
                            "title": "项目经历",
                            "items": [_v2_project_item()],
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
                                "title": "扩展简介",
                                "target": "basic.summary",
                                "operation": {
                                    "type": "replace_field",
                                    "path": "basic.summary",
                                    "value": long_summary,
                                },
                            },
                            {
                                "title": "补充项目要点",
                                "target": "sections.project.items.project-1",
                                "operation": {
                                    "type": "update_item",
                                    "sectionId": "project",
                                    "itemId": "project-1",
                                    "patch": {"highlights": highlights},
                                },
                            },
                        ],
                    },
                ),
            ],
        ),
    )

    output = result.observations[0]["output"]
    issues = output["qualityIssues"]
    issue_codes = {issue["code"] for issue in issues}
    encoded_issues = json.dumps(issues)

    assert output["qualityIssueCount"] == 2
    assert issue_codes == {"long_summary", "too_many_highlights"}
    assert long_summary.strip() not in encoded_issues
    assert events_of_type(result.events, "tool_done")[0].quality_issue_count == 2


def test_replay_quality_checks_only_touched_item_fields() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="quality_ignores_preexisting_highlight_count",
            request=AgentChatRequest(
                prompt="修改项目标题并生成草稿",
                locale="zh",
                resume={
                    "schemaVersion": 2,
                    "basic": _v2_basic(),
                    "sections": [
                        {
                            "id": "project",
                            "kind": "project",
                            "title": "项目经历",
                            "items": [
                                _v2_project_item(
                                    highlights=[
                                        f"Existing highlight {index}"
                                        for index in range(6)
                                    ],
                                ),
                            ],
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
                                "title": "更新项目标题",
                                "target": "sections.project.items.project-1",
                                "operation": {
                                    "type": "update_item",
                                    "sectionId": "project",
                                    "itemId": "project-1",
                                    "patch": {"name": "ResuMate AI Resume Editor"},
                                },
                            },
                        ],
                    },
                ),
            ],
        ),
    )

    output = result.observations[0]["output"]

    assert output["qualityIssueCount"] == 0
    assert output["qualityIssues"] == []


def test_replay_material_extract_sanitizes_attachment_candidates() -> None:
    session_id = "material-extract-attachment"
    attachment = store_agent_attachment(
        session_id=session_id,
        filename="王小明-project.txt",
        media_type="text/plain",
        payload=(
            "项目名称: ResuMate\n"
            "王小明 邮箱 xiaoming@example.com 电话 13800138000\n"
            "技术栈: React TypeScript Python\n"
            "成果: 构建 AI 简历编辑流程"
        ).encode(),
    ).model_dump(mode="json", by_alias=True)

    result = run_agent_replay(
        AgentReplayScenario(
            name="material_extract_attachment",
            request=AgentChatRequest(
                prompt="根据附件补充项目经历",
                locale="zh",
                files=[attachment],
                resume={
                    "schemaVersion": 2,
                    "basic": {"name": "王小明"},
                    "sections": [],
                },
                resume_id=session_id,
            ),
            tool_calls=[
                ReplayToolCall(
                    "material_extract",
                    {"focus": "resume_facts", "maxItems": 4},
                ),
            ],
        ),
    )

    output = result.observations[0]["output"]
    encoded_output = json.dumps(output, ensure_ascii=False)
    candidate_sections = {
        section
        for candidate in output["candidates"]
        for section in candidate["suggestedSections"]
    }

    assert result.tools[0].title == "material_extract"
    assert output["candidateCount"] >= 2
    assert "project" in candidate_sections
    assert "simple_list" in candidate_sections
    assert "王小明" not in encoded_output
    assert "xiaoming@example.com" not in encoded_output
    assert "13800138000" not in encoded_output
    assert "[redacted_name]" in encoded_output
    assert "[redacted_email]" in encoded_output
    assert "[redacted_phone]" in encoded_output


def test_replay_material_extract_does_not_treat_short_prompt_as_material() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="material_extract_short_prompt",
            request=AgentChatRequest(
                prompt="根据附件补充项目经历",
                locale="zh",
                resume={
                    "schemaVersion": 2,
                    "basic": {},
                    "sections": [
                        {
                            "id": "project",
                            "kind": "project",
                            "title": "项目经历",
                            "items": [
                                _v2_project_item(
                                    name="已有项目",
                                    description="已有简历事实。",
                                ),
                            ],
                        },
                    ],
                },
            ),
            tool_calls=[
                ReplayToolCall(
                    "material_extract",
                    {"focus": "resume_facts", "maxItems": 4},
                ),
            ],
        ),
    )

    output = result.observations[0]["output"]

    assert output["sourceCount"] == 0
    assert output["candidateCount"] == 0
    assert output["usage"]["canSupportResumeFacts"] is False


def test_replay_material_extract_keeps_jd_keywords_reference_only() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="material_extract_jd_reference_only",
            request=AgentChatRequest(
                prompt="根据 JD 分析匹配情况",
                locale="zh",
                jobBrief="任职要求: React TypeScript，负责前端性能优化。",
                resume={"schemaVersion": 2, "basic": {}, "sections": []},
            ),
            tool_calls=[
                ReplayToolCall(
                    "material_extract",
                    {"focus": "jd", "maxItems": 4},
                ),
                ReplayToolCall(
                    "material_extract",
                    {"focus": "resume_facts", "maxItems": 4},
                ),
            ],
        ),
    )

    jd_output = result.observations[0]["output"]
    facts_output = result.observations[1]["output"]

    assert jd_output["candidateCount"] >= 1
    assert all(candidate["referenceOnly"] for candidate in jd_output["candidates"])
    assert jd_output["usage"]["canSupportResumeFacts"] is False
    assert facts_output["candidateCount"] == 0
    assert facts_output["usage"]["canSupportResumeFacts"] is False


def test_replay_resume_analysis_includes_target_fit_summary() -> None:
    result = run_agent_replay(
        AgentReplayScenario(
            name="resume_analysis_target_fit",
            request=AgentChatRequest(
                prompt="目标岗位是前端工程师，分析匹配情况",
                locale="zh",
                resume={
                    "schemaVersion": 2,
                    "basic": {
                        "headline": "前端工程师",
                        "summary": "有 React 项目经验。",
                    },
                    "sections": [
                        {
                            "id": "project",
                            "kind": "project",
                            "title": "项目经历",
                            "items": [
                                _v2_project_item(description="AI 简历编辑器。"),
                            ],
                        },
                    ],
                },
                keywordMatch={
                    "matched": ["React"],
                    "missing": ["TypeScript", "性能优化"],
                    "score": 72,
                },
            ),
            tool_calls=[ReplayToolCall("resume_analysis")],
        ),
    )

    target_fit = result.observations[0]["output"]["targetFit"]

    assert target_fit["hasTargetContext"] is True
    assert target_fit["targetRole"] == "前端工程师"
    assert target_fit["score"] == 72
    assert target_fit["matchedKeywordCount"] == 1
    assert target_fit["missingKeywordCount"] == 2
    assert target_fit["recommendedTargets"] == [
        {
            "target": "basic.summary",
            "reason": "summary_keyword_alignment",
        },
        {
            "target": "sections.project.items.project-1",
            "reason": "experience_keyword_evidence",
        },
    ]
    assert target_fit["warnings"] == ["missing_keywords_require_user_evidence"]


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
                resume={"schemaVersion": 2, "basic": {}, "sections": []},
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
            "schemaVersion": 2,
            "basic": {
                "customFields": [
                    {
                        "id": "github",
                        "type": "url",
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
                resume={"schemaVersion": 2, "basic": {}, "sections": []},
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
                    "schemaVersion": 2,
                    "basic": {},
                    "sections": [
                        {
                            "id": "project",
                            "kind": "project",
                            "title": "项目经历",
                            "items": [_v2_project_item()],
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
                resume={
                    "schemaVersion": 2,
                    "basic": _v2_basic(summary="正式简历简介"),
                    "sections": [],
                },
                draftState={
                    "id": "draft-current",
                    "status": "pending",
                    "resume": {
                        "schemaVersion": 2,
                        "basic": _v2_basic(summary="待确认草稿简介"),
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
    assert event_types(result.events) == [
        "run_start",
        "turn_start",
        "tool_start",
        "tool_done",
        "edits_ready",
        "run_done",
    ]
    assert events_of_type(result.events, "tool_done")[0].operation_types == (
        "replace_field",
    )
