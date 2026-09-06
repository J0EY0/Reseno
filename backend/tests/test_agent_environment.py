import asyncio
import json

import pytest

from app.schemas.agent import (
    AgentChatRequest,
    AgentConversationItem,
    AgentToolInvocation,
)
from app.schemas.agent_settings import normalize_agent_settings
from app.services.agent.adapters.web import WebToolAdapter
from app.services.agent.environment import ResumeToolEnvironment
from app.services.agent.integrations import web as agent_web
from app.services.agent.preferences import prepare_agent_request
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.llm import LlmRequestError, LlmToolCall


def _request(prompt: str) -> AgentChatRequest:
    return AgentChatRequest(
        message=AgentConversationItem(
            id="turn-environment",
            role="user",
            text=prompt,
        ),
        resume={
            "schemaVersion": 2,
            "basic": {
                "name": "",
                "headline": "前端工程师",
                "phone": "",
                "email": "",
                "location": "",
                "avatar": "",
                "summary": "前端工程师",
                "customFields": [],
            },
            "sections": [
                {
                    "id": "skills",
                    "kind": "simple_list",
                    "title": "技能",
                    "items": [{"id": "skills-1", "content": "Python, React"}],
                },
                {
                    "id": "projects",
                    "kind": "project",
                    "title": "项目经历",
                    "items": [
                        {
                            "id": "project-1",
                            "name": "ResuMate",
                            "role": "",
                            "techStack": [],
                            "period": "",
                            "url": "",
                            "description": "开发简历编辑器。",
                            "highlights": [],
                        },
                    ],
                },
            ],
        },
    )


def _tool_names(environment: ResumeToolEnvironment) -> set[str]:
    return {
        str(schema.get("function", {}).get("name") or "")
        for schema in environment.tool_schemas
    }


def _request_with_historical_attachment(
    *,
    attachment_id: str = "11111111111141118111111111111111",
    kind: str = "text",
    current: bool = False,
) -> AgentChatRequest:
    request = _request("Use the earlier attachment to improve the project.")
    attachment = {
        "id": attachment_id,
        "filename": "project-notes.txt",
        "mediaType": "text/plain",
        "kind": kind,
    }
    request.resume_id = "resumeattachmentread"
    request.expected_revision = "1"
    if current:
        request.message.files = [attachment]
    else:
        request.messages = [
            AgentConversationItem(
                id="historical-attachment-turn",
                role="user",
                text="These are my verified project notes.",
                files=[attachment],
            ),
        ]
    return request


def _summary_edit_call(
    call_id: str = "call-summary-edit",
    *,
    value: str = "聚焦复杂前端系统的工程师。",
) -> LlmToolCall:
    arguments = {
        "edits": [
            {
                "evidenceRefs": ["prompt:current"],
                "operation": {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": value,
                },
            },
        ],
    }
    return LlmToolCall(
        id=call_id,
        name="edit_execute",
        arguments=arguments,
        raw_arguments=json.dumps(arguments, ensure_ascii=False),
    )


def _web_call(call_id: str) -> LlmToolCall:
    return LlmToolCall(
        id=call_id,
        name="web_search",
        arguments={"query": "frontend internship"},
        raw_arguments='{"query":"frontend internship"}',
    )


@pytest.mark.parametrize(
    "prompt",
    [
        "只改腾讯实习的两条 bullet。",
        "腾讯实习的两条 bullet 表达更有说服力一些。",
        "把技能分类，并优化项目经历。",
        "合并两个重复项目，并重写个人总结。",
    ],
)
def test_general_edit_tool_is_available_for_local_and_compound_edits(
    prompt: str,
) -> None:
    environment = ResumeToolEnvironment.open(_request(prompt))

    assert _tool_names(environment) == {
        "edit_execute",
        "web_search",
        "web_fetch",
    }


def test_attachment_read_is_disclosed_only_for_historical_text_material() -> None:
    historical_text = ResumeToolEnvironment.open(
        _request_with_historical_attachment(),
    )
    historical_image = ResumeToolEnvironment.open(
        _request_with_historical_attachment(kind="image"),
    )
    current_text = ResumeToolEnvironment.open(
        _request_with_historical_attachment(current=True),
    )

    assert "attachment_read" in _tool_names(historical_text)
    assert "attachment_read" not in _tool_names(historical_image)
    assert "attachment_read" not in _tool_names(current_text)


def test_read_historical_attachment_becomes_implicit_edit_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material = "I used Kafka and improved throughput by 45%.\n" + "context " * 4_000
    monkeypatch.setattr(
        "app.services.agent.adapters.attachments.attachment_text",
        lambda _session_id, _file: material,
    )
    blocking_calls: list[str] = []

    class RecordingRuntime(AgentRuntimeContext):
        async def run_sync(
            self,
            func,
            *args,
            timeout_seconds=None,
        ):
            del timeout_seconds
            blocking_calls.append(func.__name__)
            return func(*args)

    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(
            _request_with_historical_attachment(),
        )
        attachment_id = "11111111111141118111111111111111"
        runtime = RecordingRuntime()

        read_effect = await environment.invoke(
            LlmToolCall(
                id="call-attachment-read",
                name="attachment_read",
                arguments={"attachmentId": attachment_id},
                raw_arguments=json.dumps({"attachmentId": attachment_id}),
            ),
            runtime,
        )
        edit_arguments = {
            "edits": [
                {
                    "operation": {
                        "type": "update_item",
                        "sectionId": "projects",
                        "itemId": "project-1",
                        "patch": {
                            "techStack": ["Kafka"],
                            "highlights": ["Improved throughput by 45%."],
                        },
                    },
                },
            ],
        }
        edit_effect = await environment.invoke(
            LlmToolCall(
                id="call-edit-from-attachment",
                name="edit_execute",
                arguments=edit_arguments,
                raw_arguments=json.dumps(edit_arguments),
            ),
            runtime,
        )

        assert read_effect.invocation.state == "output-available"
        assert read_effect.invocation.output["attachmentId"] == attachment_id
        assert len(read_effect.invocation.output["excerpt"]) <= 16_000
        assert read_effect.invocation.output["nextOffset"] == 16_000
        assert edit_effect.invocation.state == "output-available"
        assert f"attachment:{attachment_id}" in (edit_effect.edits[-1].evidence_refs)
        assert blocking_calls == ["<lambda>"]

    asyncio.run(scenario())


def test_attachment_read_cannot_escape_the_request_history_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reads = 0

    def unexpected_read(_session_id: str, _file: dict[str, object]) -> str:
        nonlocal reads
        reads += 1
        return "must not be read"

    monkeypatch.setattr(
        "app.services.agent.adapters.attachments.attachment_text",
        unexpected_read,
    )

    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(
            _request_with_historical_attachment(),
        )
        effect = await environment.invoke(
            LlmToolCall(
                id="call-attachment-outside-history",
                name="attachment_read",
                arguments={
                    "attachmentId": "22222222222242228222222222222222",
                },
                raw_arguments=('{"attachmentId":"22222222222242228222222222222222"}'),
            ),
            AgentRuntimeContext(),
        )

        assert effect.invocation.state == "output-error"
        assert reads == 0

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "prompt",
    [
        "不要修改，只分析这份简历。",
        "不要联网，根据现有材料给我建议。",
        "不要修改，也不要联网，只做本地诊断。",
    ],
)
def test_natural_language_constraints_do_not_change_environment_capabilities(
    prompt: str,
) -> None:
    baseline = ResumeToolEnvironment.open(_request("分析并按需优化这份简历。"))
    environment = ResumeToolEnvironment.open(_request(prompt))
    baseline_names = _tool_names(baseline)
    tool_names = _tool_names(environment)

    assert baseline_names == {"edit_execute", "web_search", "web_fetch"}
    assert tool_names == baseline_names


def test_structured_suggest_only_removes_the_write_tool() -> None:
    request = prepare_agent_request(
        _request("按需优化这份简历。"),
        normalize_agent_settings({"confirmationMode": "suggestOnly"}),
    )

    environment = ResumeToolEnvironment.open(request)
    tool_names = _tool_names(environment)

    assert tool_names == {"web_search", "web_fetch"}

    result = environment.close(completed=True)
    assert not hasattr(result, "target_context")


def test_structured_suggest_only_also_blocks_an_injected_write_call() -> None:
    async def scenario() -> None:
        request = prepare_agent_request(
            _request("按需优化这份简历。"),
            normalize_agent_settings({"confirmationMode": "suggestOnly"}),
        )
        environment = ResumeToolEnvironment.open(request)

        effect = await environment.invoke(
            _summary_edit_call(),
            AgentRuntimeContext(),
        )
        result = environment.close(completed=True)

        assert effect.invocation.state == "output-error"
        assert effect.invocation.output == {"blocked": True}
        assert effect.edits == ()
        assert result.transaction_state == "none"

    asyncio.run(scenario())


def test_search_snippets_are_candidates_not_environment_sources(monkeypatch) -> None:
    async def fake_search(
        _query: str,
        _time_range: str | None,
        _include_domains: tuple[str, ...],
        _browser: agent_web.WebBrowser,
    ) -> agent_web.WebSearchResponse:
        return agent_web.WebSearchResponse(
            results=(
                agent_web.WebSearchResult(
                    url="https://careers.example/jobs/7",
                    title="Frontend Intern",
                    excerpt="Build accessible React and TypeScript interfaces.",
                    source_kind="fetched_page",
                    passages=(
                        agent_web.WebPassage(
                            section="Responsibilities",
                            text=("Build accessible React and TypeScript interfaces."),
                        ),
                    ),
                ),
                agent_web.WebSearchResult(
                    url="https://jobs.example/search-result",
                    title="Frontend internship listing",
                    excerpt="Search-provider summary that has not been read.",
                ),
            ),
        )

    monkeypatch.setattr(agent_web, "_async_search_web", fake_search)

    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(_request("查找前端实习岗位。"))
        try:
            effect = await environment.invoke(
                _web_call("call-search-sources"),
                AgentRuntimeContext(),
            )
            result = environment.close(completed=True)
        finally:
            await environment.aclose()

        output = effect.invocation.output
        assert isinstance(output, dict)
        references = output["references"]
        candidates = output["candidates"]
        assert references[0]["sourceId"].startswith("source-web-")
        assert references[0]["passages"] == [
            {
                "section": "Responsibilities",
                "text": "Build accessible React and TypeScript interfaces.",
            },
        ]
        assert "sourceId" not in candidates[0]
        assert [source.url for source in result.sources] == [
            "https://careers.example/jobs/7",
        ]

    asyncio.run(scenario())


def test_successful_edit_observation_contains_only_execution_facts() -> None:
    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(
            _request(
                "候选人事实：我聚焦复杂前端系统。请据此把简介改得更聚焦。",
            ),
        )

        effect = await environment.invoke(
            _summary_edit_call(),
            AgentRuntimeContext(),
        )

        assert effect.invocation.state == "output-available"
        assert set(effect.invocation.output) == {"editCount", "observations"}
        assert effect.invocation.output["editCount"] == 1
        assert effect.invocation.output["observations"][0]["before"] == "前端工程师"
        assert effect.invocation.output["observations"][0]["after"] == (
            "聚焦复杂前端系统的工程师。"
        )
        assert effect.observation == {
            "title": "edit_execute",
            "state": "output-available",
            "output": {
                "status": "accepted",
                "editCount": 1,
            },
            "errorText": None,
        }
        assert effect.edits[-1].title == "更新个人简介"
        assert effect.edits_changed is True

    asyncio.run(scenario())


def test_successful_edit_observation_counts_only_the_current_call() -> None:
    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(
            _request("请分两步继续优化个人简介。"),
        )

        first = await environment.invoke(
            _summary_edit_call("call-summary-first"),
            AgentRuntimeContext(),
        )
        second = await environment.invoke(
            _summary_edit_call(
                "call-summary-second",
                value="专注复杂前端系统与工程质量。",
            ),
            AgentRuntimeContext(),
        )
        result = environment.close(completed=True)

        assert first.invocation.output["editCount"] == 1
        assert len(first.invocation.output["observations"]) == 1
        assert second.invocation.output["editCount"] == 1
        assert len(second.invocation.output["observations"]) == 1
        assert len(result.edits) == 2
        assert result.transaction_state == "committed"

    asyncio.run(scenario())


def test_project_insert_omits_empty_fields_and_returns_a_canonical_edit() -> None:
    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(
            _request(
                "新增课程日程管理工具项目：2025.03 - 2025.05 使用 React、"
                "TypeScript 做前端开发，实现课程日程的创建、编辑和筛选，"
                "亮点是创建、编辑和筛选课程日程。",
            ),
        )
        arguments = {
            "edits": [
                {
                    "evidenceRefs": ["prompt:current"],
                    "operation": {
                        "type": "insert_item",
                        "sectionId": "projects",
                        "item": {
                            "id": "project-course-schedule",
                            "name": "课程日程管理工具",
                            "role": "前端开发",
                            "techStack": ["React", "TypeScript"],
                            "period": "2025.03 - 2025.05",
                            "description": "实现课程日程的创建、编辑和筛选。",
                            "highlights": ["创建与编辑课程日程", "筛选课程日程"],
                        },
                    },
                },
            ],
        }

        effect = await environment.invoke(
            LlmToolCall(
                id="call-incomplete-project",
                name="edit_execute",
                arguments=arguments,
                raw_arguments=json.dumps(arguments, ensure_ascii=False),
            ),
            AgentRuntimeContext(),
        )

        assert effect.invocation.state == "output-available"
        assert effect.invocation.output["editCount"] == 1
        assert effect.edits[-1].title == "新增项目"
        assert effect.edits[-1].operation is not None
        assert effect.edits[-1].operation["item"]["url"] == ""

    asyncio.run(scenario())


def test_removed_workflow_tool_is_reported_as_unknown() -> None:
    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(_request("查看项目经历。"))
        effect = await environment.invoke(
            LlmToolCall(
                id="call-removed-resume-lookup",
                name="resume_lookup",
                arguments={},
                raw_arguments="{}",
            ),
            AgentRuntimeContext(),
        )

        assert effect.invocation.state == "output-error"
        assert effect.invocation.title == "resume_lookup"
        assert effect.observation["state"] == "output-error"

    asyncio.run(scenario())


def test_parallel_read_cache_hit_is_returned_without_duplicate_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_web_invoke(
        _adapter: WebToolAdapter,
        tool_call: LlmToolCall,
        _runtime: AgentRuntimeContext,
    ) -> AgentToolInvocation:
        return AgentToolInvocation(
            id=tool_call.id,
            type="tool-web_search",
            title="web_search",
            state="output-available",
            input=tool_call.arguments,
            output={"resultCount": 0, "results": []},
        )

    monkeypatch.setattr(WebToolAdapter, "invoke", fake_web_invoke)

    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(_request("搜索前端实习。"))
        call = _web_call("same-read")

        first = await environment.invoke_batch([call], AgentRuntimeContext())
        replayed = await environment.invoke_batch([call], AgentRuntimeContext())
        result = environment.close(completed=True)

        assert first[0].invocation.id == "same-read"
        assert replayed[0].invocation.id == "same-read"
        assert [tool.id for tool in result.tools] == ["same-read"]

    asyncio.run(scenario())


def test_parallel_read_failure_cancels_and_joins_its_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling_started = asyncio.Event()
    sibling_cancelled = asyncio.Event()

    async def fake_web_invoke(
        _adapter: WebToolAdapter,
        tool_call: LlmToolCall,
        _runtime: AgentRuntimeContext,
    ) -> AgentToolInvocation:
        if tool_call.id == "slow-read":
            sibling_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                sibling_cancelled.set()
                raise
        await sibling_started.wait()
        raise LlmRequestError("read failed")

    monkeypatch.setattr(WebToolAdapter, "invoke", fake_web_invoke)

    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(_request("并行搜索。"))
        with pytest.raises(LlmRequestError, match="read failed"):
            await environment.invoke_batch(
                [_web_call("slow-read"), _web_call("failed-read")],
                AgentRuntimeContext(),
            )
        assert sibling_cancelled.is_set()

    asyncio.run(scenario())


def test_mixed_batch_runs_reads_in_parallel_and_defers_the_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    both_reads_started = asyncio.Event()
    started_reads = 0

    async def fake_web_invoke(
        _adapter: WebToolAdapter,
        tool_call: LlmToolCall,
        _runtime: AgentRuntimeContext,
    ) -> AgentToolInvocation:
        nonlocal started_reads
        started_reads += 1
        if started_reads == 2:
            both_reads_started.set()
        await asyncio.wait_for(both_reads_started.wait(), timeout=1)
        return AgentToolInvocation(
            id=tool_call.id,
            type="tool-web_search",
            title="web_search",
            state="output-available",
            input=tool_call.arguments,
            output={"resultCount": 0, "results": []},
        )

    monkeypatch.setattr(WebToolAdapter, "invoke", fake_web_invoke)

    async def scenario() -> None:
        environment = ResumeToolEnvironment.open(_request("搜索后更新简介。"))
        effects = await environment.invoke_batch(
            [
                _summary_edit_call("write-before-reads"),
                _web_call("first-read"),
                _web_call("second-read"),
            ],
            AgentRuntimeContext(),
        )
        result = environment.close(completed=True)

        assert started_reads == 2
        assert [effect.invocation.id for effect in effects] == [
            "write-before-reads",
            "first-read",
            "second-read",
        ]
        assert effects[0].invocation.output["status"] == "not_executed"
        assert effects[0].invocation.output["editCount"] == 0
        assert effects[0].edits == ()
        assert result.edits == ()
        assert [tool.id for tool in result.tools] == [
            "first-read",
            "second-read",
        ]

    asyncio.run(scenario())
