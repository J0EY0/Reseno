import json

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.services.agent.contracts import EDIT_EXECUTE_SCHEMA
from app.services.agent.draft import DraftEditEngine
from app.services.agent.privacy import (
    HIDDEN_BASIC_VALUE,
    sanitize_agent_resume,
    sanitize_agent_text,
)


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


def test_web_refresh_timestamp_is_not_redacted_as_a_phone_number() -> None:
    sanitized = sanitize_agent_text(
        "前端实习生 2026-08-20 16:26:09 刷新，联系电话 +86 138 0000 0000。",
    )

    assert "2026-08-20 16:26:09" in sanitized
    assert "[redacted_phone]" in sanitized


def test_web_source_url_numeric_path_is_not_redacted_as_phone_number() -> None:
    url = "https://zhuanlan.zhihu.com/p/1234567890123456789"

    assert sanitize_agent_text(url) == url


def test_western_name_is_redacted_across_filename_separator() -> None:
    for filename, expected in (
        ("John_Smith_CV.pdf", "[redacted_name]_CV.pdf"),
        ("JOHN-SMITH-CV.pdf", "[redacted_name]-CV.pdf"),
        ("john.smith.CV.pdf", "[redacted_name].CV.pdf"),
    ):
        assert sanitize_agent_text(filename, hidden_terms=("John Smith",)) == expected


def test_western_name_separator_matching_respects_token_boundaries() -> None:
    filename = "NotJohn_Smithson_CV.pdf"

    assert sanitize_agent_text(filename, hidden_terms=("John Smith",)) == filename


def test_single_token_western_hidden_term_keeps_exact_boundary_semantics() -> None:
    filename = "John_CV.pdf"

    assert sanitize_agent_text(filename, hidden_terms=("John",)) == filename


def test_cjk_hidden_term_keeps_literal_replacement_semantics() -> None:
    assert (
        sanitize_agent_text(
            "王小明_简历.pdf",
            hidden_terms=("王小明",),
        )
        == "[redacted_name]_简历.pdf"
    )


def test_draft_engine_rejects_location_changes() -> None:
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
    engine = DraftEditEngine.open(request)
    batch = engine.execute(
        [
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
    )

    assert batch.accepted is False
    assert engine.edits == ()
    assert batch.draft_resume["basic"]["location"] == "Beijing"


def test_agent_write_contract_does_not_offer_hidden_location_writes() -> None:
    serialized_schema = json.dumps(EDIT_EXECUTE_SCHEMA, ensure_ascii=False)

    assert "basic.location" not in serialized_schema
