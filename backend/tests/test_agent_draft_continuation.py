from contextlib import closing
from copy import deepcopy

from app.db.connection import connect
from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentConversationItem,
    AgentDraftState,
)
from app.services import agent_sessions, resumes
from app.services.agent.draft import DraftEditEngine, DraftTransaction
from app.services.agent.editing.operations import _apply_edit_operations
from tests.test_agent_turn_protocol import (
    _accept_turn,
    _ensure_active_resume,
    _persist_successful_turn,
    _resume_save_payload,
)


def _edit(edit_id, path, value):
    return {
        "id": edit_id,
        "title": edit_id,
        "target": path,
        "reason": "User request",
        "status": "executed",
        "operation": {"type": "replace_field", "path": path, "value": value},
    }


def _continue_request(conn, resume_id, formal, session, *, turn_id):
    response = session.messages[-1].response
    active = deepcopy(formal)
    pending_ids = {
        edit_id
        for item in response.draft.review_items
        if item.status == "pending"
        for edit_id in item.edit_ids
    }
    _apply_edit_operations(active, [e for e in response.edits if e.id in pending_ids])
    request = AgentChatRequest(
        resumeId=resume_id,
        expectedRevision=session.revision,
        message=AgentConversationItem(id=turn_id, role="user", text="继续优化职位"),
        resume=formal,
        draftState=AgentDraftState(
            id=f"draft-{response.id}",
            sourceMessageId=response.id,
            resume=active,
            pendingCount=sum(
                i.status == "pending" for i in response.draft.review_items
            ),
            reviewItems=response.draft.review_items,
        ),
    )
    return _accept_turn(conn, request)


def test_partial_decisions_advance_only_applied_base_across_turns(client):
    resume_id = "draftcontinuation"
    _ensure_active_resume(resume_id)
    original = resumes.save_resume(resume_id, _resume_save_payload(headline="Engineer"))
    base = original["resume"]["resume"]
    initial_edits = [
        _edit("headline", "basic.headline", "Senior Engineer"),
        _edit("summary", "basic.summary", "Builds reliable software."),
        {
            "id": "section",
            "title": "Projects",
            "target": "sections.discarded-projects",
            "reason": "User request",
            "status": "executed",
            "operation": {
                "type": "insert_section",
                "section": {
                    "id": "discarded-projects",
                    "kind": "project",
                    "title": "Projects",
                    "items": [],
                },
            },
        },
    ]
    with closing(connect()) as conn:
        prepared = _accept_turn(
            conn,
            AgentChatRequest(
                resumeId=resume_id,
                expectedRevision=agent_sessions.load_agent_session(
                    conn, resume_id
                ).revision,
                message=AgentConversationItem(
                    id="first", role="user", text="优化职位和简介"
                ),
                resume=base,
            ),
        )
        _persist_successful_turn(
            conn,
            prepared,
            AgentChatMessage(
                id="draft-first",
                role="assistant",
                text="Draft",
                edits=initial_edits,
                transactionState="committed",
            ),
        )
        session = agent_sessions.load_agent_session(conn, resume_id)
        original_response = session.messages[-1].response.model_dump(by_alias=True)
        session = agent_sessions.update_agent_draft_decision(
            conn,
            resume_id,
            message_id="draft-first",
            review_item_ids=["agent-review-section"],
            status="discarded",
            revision=session.revision,
        )
        formal = deepcopy(base)
        formal["basic"]["headline"] = "Senior Engineer"
        session, saved = agent_sessions.apply_agent_draft_decision(
            conn,
            resume_id,
            message_id="draft-first",
            review_item_ids=["agent-review-headline"],
            resume=formal,
            revision=session.revision,
            expected_version_id=original["versionId"],
        )
        expected_base = deepcopy(formal)
        for number, headline in enumerate(
            ("Staff Engineer", "Principal Engineer"), start=2
        ):
            prepared = _continue_request(
                conn, resume_id, formal, session, turn_id=f"turn-{number}"
            )
            transaction = DraftTransaction.from_request(prepared.request)
            assert transaction.base_resume == expected_base
            assert [e.id for e in transaction.prior_edits] == ["summary"]
            assert transaction.base_resume["sections"] == []
            engine = DraftEditEngine.open(prepared.request, transaction)
            batch = engine.execute(
                [
                    {
                        "operation": {
                            "type": "replace_field",
                            "path": "basic.headline",
                            "value": headline,
                        }
                    }
                ]
            )
            assert batch.accepted
            turn = engine.finalize(True)
            replay = turn.base_resume
            _apply_edit_operations(replay, turn.edits)
            assert replay == turn.draft_resume
            _persist_successful_turn(
                conn,
                prepared,
                AgentChatMessage(
                    id=f"draft-{number}",
                    role="assistant",
                    text="Draft",
                    edits=list(batch.edits),
                    transactionState="committed",
                ),
            )
            session = agent_sessions.load_agent_session(conn, resume_id)
            formal = deepcopy(formal)
            formal["basic"]["headline"] = headline
            new_review_id = f"agent-review-{batch.edits[0].id}"
            session, saved = agent_sessions.apply_agent_draft_decision(
                conn,
                resume_id,
                message_id=f"draft-{number}",
                review_item_ids=[new_review_id],
                resume=formal,
                revision=session.revision,
                expected_version_id=saved["versionId"],
            )
            expected_base = deepcopy(formal)
        stored_first = next(
            m for m in session.messages if m.id == "draft-first"
        ).response
        assert (
            stored_first.draft.base_resume
            == original_response["draft"]["baseResume"]
            == base
        )


def test_continuation_preserves_external_changes_as_merge_conflicts():
    base = _resume_save_payload(headline="Engineer")["resume"]
    formal = deepcopy(base)
    formal["basic"].update(
        headline="Senior Engineer", summary="User changed this independently"
    )
    edits = [
        _edit("headline", "basic.headline", "Senior Engineer"),
        _edit("summary", "basic.summary", "Pending summary"),
    ]
    reviews = [
        {"id": "head-review", "editIds": ["headline"], "status": "applied"},
        {"id": "summary-review", "editIds": ["summary"], "status": "pending"},
    ]
    request = AgentChatRequest(
        message=AgentConversationItem(id="next", role="user", text="继续"),
        resume=formal,
        messages=[
            AgentConversationItem(
                id="prior",
                role="assistant",
                text="Draft",
                response={
                    "draft": {"baseResume": base, "reviewItems": reviews},
                    "edits": edits,
                },
            )
        ],
        draftState=AgentDraftState(
            id="draft",
            sourceMessageId="prior",
            resume=formal,
            pendingCount=1,
            reviewItems=reviews,
        ),
    )
    transaction = DraftTransaction.from_request(request)
    assert transaction.base_resume["basic"]["headline"] == "Senior Engineer"
    assert transaction.base_resume["basic"]["summary"] == ""
    assert (
        transaction.active_resume["basic"]["summary"]
        == "User changed this independently"
    )


def test_continuation_can_edit_a_previously_applied_inserted_section():
    base = _resume_save_payload(headline="Engineer")["resume"]
    section = {"id": "projects", "kind": "project", "title": "项目经历", "items": []}
    formal = deepcopy(base)
    formal["sections"].append(section)
    active = deepcopy(formal)
    active["basic"]["summary"] = "Builds reliable software."
    insertion = {
        "id": "insert-projects",
        "title": "Projects",
        "target": "sections.projects",
        "reason": "User request",
        "status": "executed",
        "operation": {"type": "insert_section", "section": section},
    }
    pending = _edit("summary", "basic.summary", active["basic"]["summary"])
    reviews = [
        {"id": "insert-review", "editIds": [insertion["id"]], "status": "applied"},
        {"id": "summary-review", "editIds": [pending["id"]], "status": "pending"},
    ]
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="followup", role="user", text="将项目经历改名为精选项目"
        ),
        resume=formal,
        messages=[
            AgentConversationItem(
                id="prior",
                role="assistant",
                text="Draft",
                response={
                    "draft": {"baseResume": base, "reviewItems": reviews},
                    "edits": [insertion, pending],
                },
            )
        ],
        draftState=AgentDraftState(
            id="draft",
            sourceMessageId="prior",
            resume=active,
            pendingCount=1,
            reviewItems=reviews,
        ),
    )
    engine = DraftEditEngine.open(request)
    result = engine.execute(
        [
            {
                "operation": {
                    "type": "update_section",
                    "sectionId": "projects",
                    "patch": {"title": "精选项目"},
                }
            }
        ]
    )
    assert result.accepted
    turn = engine.finalize(True)
    replay = turn.base_resume
    _apply_edit_operations(replay, turn.edits)
    assert replay == turn.draft_resume
    assert replay["sections"][0]["title"] == "精选项目"
    assert base["sections"] == []
