import os
from copy import deepcopy

import pytest
from playwright.sync_api import Browser, expect

from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentCommittedDraft,
    AgentConversationItem,
    AgentDraftState,
)
from app.services.agent.draft import DraftEditEngine
from app.services.agent.draft.review import build_draft_review_items
from app.services.agent.editing.operations import _apply_edit_operations
from tests.e2e.browser_support import authenticated_context
from tests.e2e.test_workspace_route_network import _seed_pending_agent_draft

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1", reason="set RUN_BROWSER_E2E=1"
    ),
]


def test_partially_applied_followup_previews_and_saves_without_hiding_real_conflicts(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1440, "height": 900}
    )
    page = context.new_page()
    try:
        source_id = "partial-source"
        summary = "专注可靠软件与清晰的系统设计。"
        resume_id, original, _ = _seed_pending_agent_draft(
            page,
            frontend_url,
            message_id=source_id,
            headline="高级工程师",
            summary=summary,
        )
        session_url = f"{frontend_url}/api/agent/resumes/{resume_id}/session"
        session = page.request.get(session_url).json()["data"]
        formal = deepcopy(original["resume"]["resume"])
        formal["basic"]["headline"] = "高级工程师"
        applied = page.request.patch(
            f"{session_url}/messages/{source_id}/draft",
            data={
                "revision": session["revision"],
                "status": "applied",
                "reviewItemIds": [f"agent-review-edit-{source_id}-headline"],
                "resume": formal,
                "expectedVersionId": original["versionId"],
            },
        )
        assert applied.ok
        session = applied.json()["data"]["session"]
        source = session["messages"][-1]["response"]
        active = deepcopy(formal)
        pending_ids = {
            edit_id
            for item in source["draft"]["reviewItems"]
            if item["status"] == "pending"
            for edit_id in item["editIds"]
        }
        pending_edits = [
            edit
            for edit in AgentChatMessage.model_validate(source).edits
            if edit.id in pending_ids
        ]
        _apply_edit_operations(active, pending_edits)
        request = AgentChatRequest(
            message=AgentConversationItem(
                id="followup", role="user", text="将职位改为资深工程师"
            ),
            resume=formal,
            messages=[
                AgentConversationItem.model_validate(message)
                for message in session["messages"]
            ],
            draftState=AgentDraftState(
                id="partial-draft",
                sourceMessageId=source_id,
                resume=active,
                pendingCount=1,
                reviewItems=source["draft"]["reviewItems"],
            ),
        )
        engine = DraftEditEngine.open(request)
        batch = engine.execute(
            [
                {
                    "operation": {
                        "type": "replace_field",
                        "path": "basic.headline",
                        "value": "资深工程师",
                    }
                }
            ]
        )
        assert batch.accepted
        turn = engine.finalize(True)
        message = AgentChatMessage(
            id="continued-draft",
            role="assistant",
            text="新的修改等待确认。",
            edits=list(turn.edits),
            transactionState="committed",
            draft=AgentCommittedDraft(
                baseResume=turn.base_resume,
                reviewItems=build_draft_review_items(turn.edits),
            ),
        )
        for item in source["draft"]["reviewItems"]:
            if item["status"] == "pending":
                item["status"] = "superseded"
        seeded = page.request.put(
            session_url,
            data={
                "locale": "zh",
                "revision": session["revision"],
                "messages": [
                    *session["messages"],
                    {
                        "id": message.id,
                        "role": "assistant",
                        "text": message.text,
                        "response": message.model_dump(mode="json", by_alias=True),
                    },
                ],
            },
        )
        assert seeded.ok
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role("button", name="展开 AI 助手", exact=True).click()
        expect(page.get_by_text("2 项待确认", exact=True)).to_be_visible()
        source_receipt = page.locator(
            '[data-slot="agent-draft-resolution-receipt"]'
        ).filter(has_text="已被后续建议替代")
        expect(source_receipt).to_have_text("已应用 1 项 · 1 项已被后续建议替代")
        preview = page.locator('[data-export-root="resume-page"]:visible').first
        expect(preview.get_by_text("资深工程师", exact=True)).to_be_visible()
        assert (
            page.request.get(f"{frontend_url}/api/resumes/{resume_id}").json()["data"][
                "resume"
            ]["resume"]["basic"]["headline"]
            == "高级工程师"
        )
        external = deepcopy(formal)
        external["basic"]["summary"] = "用户在另一标签页独立修改了简介。"
        conflicts = page.evaluate(
            """async data => {
            const { projectAgentDraftReview } =
                await import('/src/lib/agent-draft-review.ts');
            return projectAgentDraftReview(data).errors;
        }""",
            {
                "baseResume": turn.base_resume,
                "currentResume": external,
                "edits": [e.model_dump(mode="json", by_alias=True) for e in turn.edits],
                "reviewItems": [
                    i.model_dump(mode="json", by_alias=True)
                    for i in message.draft.review_items
                ],
            },
        )
        assert len(conflicts) == 1 and conflicts[0]["reason"] == "conflict"
        page.get_by_role("button", name="应用剩余全部", exact=True).click()
        expect(page.get_by_text("已应用 2 项，已放弃 0 项", exact=True)).to_be_visible()
        saved = page.request.get(f"{frontend_url}/api/resumes/{resume_id}").json()[
            "data"
        ]
        assert saved["resume"]["resume"]["basic"]["headline"] == "资深工程师"
        assert saved["resume"]["resume"]["basic"]["summary"] == summary
        expect(source_receipt).to_have_text("已应用 1 项 · 1 项已被后续建议替代")
        session_after = page.request.get(session_url).json()["data"]
        previous = next(
            item["response"]
            for item in session_after["messages"]
            if item["id"] == source_id
        )
        assert [item["status"] for item in previous["draft"]["reviewItems"]] == [
            "superseded",
            "applied",
        ]
    finally:
        context.close()


def test_superseded_history_is_distinct_from_explicitly_discarded_drafts(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
        reduced_motion="reduce",
    )
    page = context.new_page()
    try:
        source_id = "superseded-source"
        resume_id, original, _ = _seed_pending_agent_draft(
            page,
            frontend_url,
            message_id=source_id,
            summary="旧的待确认建议",
        )
        session_url = f"{frontend_url}/api/agent/resumes/{resume_id}/session"
        session = page.request.get(session_url).json()["data"]
        source = session["messages"][-1]["response"]
        replacement = deepcopy(source)
        replacement["id"] = "replacement-draft"
        replacement["text"] = "后续草稿等待确认"
        replacement["edits"][0].update(id="replacement-edit")
        replacement["edits"][0]["operation"]["value"] = "后续生成的待确认总结"
        replacement["draft"]["reviewItems"] = [
            {
                "id": "review-replacement-edit",
                "editIds": ["replacement-edit"],
                "status": "pending",
            }
        ]
        for item in source["draft"]["reviewItems"]:
            item["status"] = "superseded"
        seeded = page.request.put(
            session_url,
            data={
                "locale": "zh",
                "revision": session["revision"],
                "messages": [
                    *session["messages"],
                    {
                        "id": replacement["id"],
                        "role": "assistant",
                        "text": replacement["text"],
                        "response": replacement,
                    },
                ],
            },
        )
        assert seeded.ok
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role("button", name="展开 AI 助手", exact=True).click()
        receipts = page.locator('[data-slot="agent-draft-resolution-receipt"]')
        superseded = receipts.filter(has_text="已被后续建议替代")
        expect(superseded).to_have_text("已被后续建议替代")
        expect(receipts).to_have_count(1)
        expect(page.get_by_text("1 项待确认", exact=True)).to_be_visible()
        preview = page.locator('[data-export-root="resume-page"]:visible').first
        expect(preview.get_by_text("后续生成的待确认总结", exact=True)).to_be_visible()
        page.get_by_role("button", name="放弃剩余全部", exact=True).click()
        expect(receipts).to_have_count(2)
        expect(superseded).to_have_text("已被后续建议替代")
        discarded = receipts.filter(has_text="已放弃")
        expect(discarded).to_have_text("已应用 0 项，已放弃 1 项")
        page.reload(wait_until="networkidle")
        page.get_by_role("button", name="展开 AI 助手", exact=True).click()
        expect(superseded).to_have_text("已被后续建议替代")
        expect(discarded).to_have_text("已应用 0 项，已放弃 1 项")
        saved = page.request.get(f"{frontend_url}/api/resumes/{resume_id}").json()[
            "data"
        ]["resume"]["resume"]
        assert saved == original["resume"]["resume"]
        messages = page.request.get(session_url).json()["data"]["messages"]
        assert [
            message["response"]["draft"]["reviewItems"][0]["status"]
            for message in messages
        ] == ["superseded", "discarded"]
    finally:
        context.close()
