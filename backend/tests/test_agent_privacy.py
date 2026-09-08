import json
from contextlib import closing
from copy import deepcopy

import pytest

from app.db.connection import connect
from app.schemas.agent import AgentChatMessage, AgentChatRequest, AgentConversationItem
from app.services import agent_sessions, resumes
from app.services.agent.contracts import EDIT_EXECUTE_SCHEMA
from app.services.agent.draft import DraftEditEngine
from app.services.agent.privacy import (
    HIDDEN_BASIC_VALUE,
    sanitize_agent_resume,
    sanitize_agent_text,
)
from tests.test_agent_draft_engine import _request
from tests.test_agent_turn_protocol import (
    _accept_turn,
    _ensure_active_resume,
    _persist_successful_turn,
    _resume_save_payload,
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
        ("John_Smith_CV.pdf", "[redacted_identity_0]_CV.pdf"),
        ("JOHN-SMITH-CV.pdf", "[redacted_identity_0]-CV.pdf"),
        ("john.smith.CV.pdf", "[redacted_identity_0].CV.pdf"),
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
        == "[redacted_identity_0]_简历.pdf"
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


def test_redacted_identity_rewrite_round_trips_through_confirmed_apply(client):
    request = _request("润色简介，保持学校、公司和经历事实。")
    request.resume["basic"].update(
        name="王小明",
        location="上海",
        summary="王小明毕业于上海交通大学，在上海电气从事软件开发。",
    )
    resume_id = "privacyroundtrip"
    _ensure_active_resume(resume_id)
    payload = _resume_save_payload(headline="Engineer")
    payload["resume"] = request.resume
    original = resumes.save_resume(resume_id, payload)
    with closing(connect()) as conn:
        request = request.model_copy(
            update={
                "resume_id": resume_id,
                "expected_revision": agent_sessions.load_agent_session(
                    conn, resume_id
                ).revision,
            }
        )
        prepared = _accept_turn(conn, request)
        visible = sanitize_agent_resume(request.resume)
        model_rewrite = visible["basic"]["summary"].replace("从事", "专注")
        assert "王小明" not in model_rewrite and "上海" not in model_rewrite
        engine = DraftEditEngine.open(prepared.request)
        batch = engine.execute(
            [
                {
                    "operation": {
                        "type": "replace_field",
                        "path": "basic.summary",
                        "value": model_rewrite,
                    }
                }
            ]
        )
        assert batch.accepted
        turn = engine.finalize(True)
        assert (
            turn.draft_resume["basic"]["summary"]
            == "王小明毕业于上海交通大学，在上海电气专注软件开发。"
        )
        assert resumes.load_resume(resume_id)["resume"]["resume"] == request.resume
        _persist_successful_turn(
            conn,
            prepared,
            AgentChatMessage(
                id="privacy-draft",
                role="assistant",
                text="Draft",
                transactionState="committed",
                edits=list(batch.edits),
            ),
        )
        session = agent_sessions.load_agent_session(conn, resume_id)
        agent_sessions.apply_agent_draft_decision(
            conn,
            resume_id,
            message_id="privacy-draft",
            review_item_ids=[
                i.id for i in session.messages[-1].response.draft.review_items
            ],
            resume=turn.draft_resume,
            revision=session.revision,
            expected_version_id=original["versionId"],
        )
    formal = resumes.load_resume(resume_id)["resume"]["resume"]
    assert (
        formal["basic"]["summary"]
        == "王小明毕业于上海交通大学，在上海电气专注软件开发。"
    )
    assert "[redacted" not in json.dumps(formal, ensure_ascii=False)


@pytest.mark.parametrize(
    "marker",
    [
        "[hidden]",
        "[redacted_name]",
        "[redacted_email]",
        "[redacted_phone]",
        "[redacted_identity_8]",
        "[redacted_identity_invalid]",
    ],
)
def test_unresolvable_privacy_markers_reject_the_entire_batch(marker):
    request = _request("优化简介和项目说明")
    request.resume["basic"].update(name="王小明", location="上海")
    engine = DraftEditEngine.open(request)
    prior = engine.execute(
        [
            {
                "operation": {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "Previously accepted summary.",
                }
            },
        ]
    )
    assert prior.accepted
    before = deepcopy(engine.draft_resume)
    batch = engine.execute(
        [
            {
                "operation": {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "Builds reliable software.",
                }
            },
            {
                "operation": {
                    "type": "update_item",
                    "sectionId": "project",
                    "itemId": "target-project",
                    "patch": {"highlights": [f"Contributed with {marker}."]},
                }
            },
        ]
    )
    assert not batch.accepted
    assert engine.edits == prior.edits
    assert engine.draft_resume == before
    assert engine.finalize(True).draft_resume == before


def test_identical_name_and_location_share_one_restorable_slot():
    request = _request("精简个人简介")
    request.resume["basic"].update(
        name="上海", location="上海", summary="上海，负责软件开发。"
    )
    visible = sanitize_agent_resume(request.resume)
    assert visible["basic"]["summary"] == "[redacted_identity_0]，负责软件开发。"
    engine = DraftEditEngine.open(request)
    result = engine.execute(
        [
            {
                "operation": {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "[redacted_identity_0]，专注软件开发。",
                }
            }
        ]
    )
    assert result.accepted
    assert result.draft_resume["basic"]["summary"] == "上海，专注软件开发。"
