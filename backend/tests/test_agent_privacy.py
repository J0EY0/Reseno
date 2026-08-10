import asyncio
import json

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services.agent.executor import AgentPlanExecutor
from app.services.agent.privacy import (
    HIDDEN_BASIC_VALUE,
    sanitize_agent_resume,
    sanitize_agent_text,
)
from app.services.agent.prompts import EDIT_OPERATION_GUIDE
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.tools.runner import AgentToolRunner
from app.services.llm import LlmToolCall


def test_resume_location_is_hidden_from_every_model_visible_field() -> None:
    location = "北京市朝阳区望京"
    sanitized = sanitize_agent_resume(
        {
            "basic": {
                "name": "王小明",
                "location": location,
                "summary": f"现居{location}，负责后端平台研发。",
            },
            "sections": [
                {
                    "id": "experience",
                    "kind": "experience",
                    "items": [
                        {
                            "id": "experience-1",
                            "description": f"在{location}负责服务治理。",
                        },
                    ],
                },
            ],
        },
    )

    assert location not in json.dumps(sanitized, ensure_ascii=False)
    assert sanitized["basic"]["location"] == HIDDEN_BASIC_VALUE
    assert sanitized["basicFieldStatus"]["location"] == "present"


def test_resume_date_ranges_are_not_redacted_as_phone_numbers() -> None:
    sanitized = sanitize_agent_resume(
        {
            "basic": {
                "summary": (
                    "学习时间为 2019.09 - 2023.06，联系电话 +86 138 0000 0000。"
                ),
            },
            "sections": [
                {
                    "id": "experience",
                    "kind": "experience",
                    "items": [
                        {
                            "id": "experience-1",
                            "period": "2022.07 - 2022.09",
                        },
                    ],
                },
            ],
        },
    )

    assert "2019.09 - 2023.06" in sanitized["basic"]["summary"]
    assert "[redacted_phone]" in sanitized["basic"]["summary"]
    assert sanitized["sections"][0]["items"][0]["period"] == ("2022.07 - 2022.09")


def test_web_source_url_numeric_path_is_not_redacted_as_phone_number() -> None:
    url = "https://zhuanlan.zhihu.com/p/1234567890123456789"

    assert sanitize_agent_text(url) == url


def test_agent_write_tool_rejects_location_changes() -> None:
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-agent-privacy-location",
            role="user",
            text="优化这份简历，但不要修改个人信息",
        ),
        resume={
            "schemaVersion": 2,
            "basic": {
                "name": "",
                "headline": "Backend Engineer",
                "phone": "",
                "email": "",
                "location": "Beijing",
                "avatar": "",
                "summary": "Builds reliable services.",
                "customFields": [],
            },
            "sections": [],
        },
    )
    runner = AgentToolRunner(AgentPlanExecutor(request))
    tool_call = LlmToolCall(
        id="call-location",
        name="edit_execute",
        arguments={
            "edits": [
                {
                    "title": "Change location",
                    "target": "basic.location",
                    "operation": {
                        "type": "replace_field",
                        "path": "basic.location",
                        "value": "Shanghai",
                    },
                },
            ],
        },
        raw_arguments="{}",
    )

    tool, _ = asyncio.run(runner.run(tool_call, AgentRuntimeContext()))

    assert tool.state == "output-error"
    assert runner.edits == []
    assert runner.draft_resume["basic"]["location"] == "Beijing"


def test_agent_prompt_does_not_offer_hidden_location_writes() -> None:
    assert "basic.location" not in EDIT_OPERATION_GUIDE
