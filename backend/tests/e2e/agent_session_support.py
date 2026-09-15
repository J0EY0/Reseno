from __future__ import annotations

import json
from typing import Any

from playwright.sync_api import Page


def seed_pending_agent_draft(
    page: Page,
    frontend_url: str,
    *,
    headline: str | None = None,
    message_id: str,
    summary: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    create_response = page.request.post(
        f"{frontend_url}/api/resumes",
        data={"documentLocale": "zh"},
    )
    assert create_response.ok
    resume_id = str(create_response.json()["data"]["resume"]["id"])
    detail = page.request.get(f"{frontend_url}/api/resumes/{resume_id}").json()["data"]
    base_resume = detail["resume"]["resume"]
    candidate_resume = json.loads(json.dumps(base_resume))
    candidate_resume["basic"]["summary"] = summary
    edits = [
        {
            "id": f"edit-{message_id}",
            "title": "改写个人总结",
            "target": "basic.summary",
            "reason": "验证待确认草稿只能由当前页面确认。",
            "operation": {
                "type": "replace_field",
                "path": "basic.summary",
                "value": summary,
            },
            "status": "executed",
        }
    ]
    review_items = [
        {
            "id": f"agent-review-edit-{message_id}",
            "editIds": [f"edit-{message_id}"],
            "status": "pending",
        }
    ]
    if headline is not None:
        headline_edit_id = f"edit-{message_id}-headline"
        candidate_resume["basic"]["headline"] = headline
        edits.append(
            {
                "id": headline_edit_id,
                "title": "改写职业标题",
                "target": "basic.headline",
                "reason": "验证逐项审阅与独立决策。",
                "operation": {
                    "type": "replace_field",
                    "path": "basic.headline",
                    "value": headline,
                },
                "status": "executed",
            }
        )
        review_items.append(
            {
                "id": f"agent-review-{headline_edit_id}",
                "editIds": [headline_edit_id],
                "status": "pending",
            }
        )
    session = page.request.get(
        f"{frontend_url}/api/agent/resumes/{resume_id}/session"
    ).json()["data"]
    seed_response = page.request.put(
        f"{frontend_url}/api/agent/resumes/{resume_id}/session",
        data={
            "locale": "zh",
            "revision": session["revision"],
            "messages": [
                {
                    "id": message_id,
                    "role": "assistant",
                    "text": "草稿等待确认。",
                    "createdAt": "2026-08-10T00:00:00.000Z",
                    "response": {
                        "id": message_id,
                        "role": "assistant",
                        "text": "草稿等待确认。",
                        "edits": edits,
                        "draft": {
                            "baseResume": base_resume,
                            "reviewItems": review_items,
                        },
                        "transactionState": "committed",
                    },
                }
            ],
        },
    )
    assert seed_response.ok
    return resume_id, detail, candidate_resume
