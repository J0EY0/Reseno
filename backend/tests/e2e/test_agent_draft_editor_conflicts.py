import os
from copy import deepcopy
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.browser_support import authenticated_context
from tests.e2e.test_preview_edit_transactions import _create_experience_resume

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1", reason="set RUN_BROWSER_E2E=1"
    ),
]


def _seed_work_draft(
    page: Page,
    frontend_url: str,
    *,
    include_unchanged_company: bool = False,
    include_summary: bool = False,
    include_headline: bool = False,
) -> str:
    baseline = _create_experience_resume(page, frontend_url, 1)
    resume_id = baseline["id"]
    session_url = f"{frontend_url}/api/agent/resumes/{resume_id}/session"
    session = page.request.get(session_url).json()["data"]
    patch = {"position": "Agent Position"}
    if include_unchanged_company:
        patch["company"] = "Company 0"
    edits: list[dict[str, Any]] = [
        {
            "id": f"edit-work-{resume_id}",
            "title": "更新工作",
            "target": "experience.experience-0",
            "reason": "调整工作职位",
            "operation": {
                "type": "update_item",
                "sectionId": "experience",
                "itemId": "experience-0",
                "patch": patch,
            },
            "status": "executed",
        }
    ]
    if include_summary:
        edits.append(
            {
                "id": f"edit-summary-{resume_id}",
                "title": "更新个人总结",
                "target": "basic.summary",
                "reason": "调整个人总结",
                "operation": {
                    "type": "replace_field",
                    "path": "basic.summary",
                    "value": "Agent Summary",
                },
                "status": "executed",
            }
        )
    if include_headline:
        edits.append(
            {
                "id": f"edit-headline-{resume_id}",
                "title": "更新职业标题",
                "target": "basic.headline",
                "reason": "调整职业标题",
                "operation": {
                    "type": "replace_field",
                    "path": "basic.headline",
                    "value": "Agent Headline",
                },
                "status": "executed",
            }
        )
    response = {
        "id": f"draft-work-{resume_id}",
        "role": "assistant",
        "text": "草稿等待确认",
        "edits": edits,
        "draft": {
            "baseResume": baseline["resume"],
            "reviewItems": [
                {
                    "id": f"review-{edit['id']}",
                    "editIds": [edit["id"]],
                    "status": "pending",
                }
                for edit in edits
            ],
        },
        "transactionState": "committed",
    }
    seeded = page.request.put(
        session_url,
        data={
            "locale": "zh",
            "revision": session["revision"],
            "messages": [
                {
                    "id": response["id"],
                    "role": "assistant",
                    "text": response["text"],
                    "createdAt": "2026-09-08T00:00:00.000Z",
                    "response": response,
                }
            ],
        },
    )
    assert seeded.ok
    return resume_id


def _open_work_editor(page: Page) -> None:
    page.get_by_role("button", name="Experience: 展开或收起模块", exact=True).click()
    page.get_by_role("button", name="展开或收起条目 1", exact=True).click()


def _saved_resume(page: Page, frontend_url: str, resume_id: str) -> dict[str, Any]:
    return page.request.get(f"{frontend_url}/api/resumes/{resume_id}").json()["data"][
        "resume"
    ]["resume"]


def _save_resume(page: Page, frontend_url: str, resume_id: str) -> dict[str, Any]:
    with page.expect_response(
        lambda response: (
            response.request.method == "PUT"
            and response.url.split("?")[0] == f"{frontend_url}/api/resumes/{resume_id}"
        )
    ):
        page.keyboard.press("ControlOrMeta+s")
    return _saved_resume(page, frontend_url, resume_id)


@pytest.mark.parametrize(
    "edit",
    [
        "different_section",
        "same_item_other_field",
        "unchanged_patch_field",
    ],
)
def test_editor_changes_preserve_nonconflicting_agent_review(
    browser: Browser,
    workspace_servers: tuple[str, str],
    edit: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1800, "height": 1000},
        reduced_motion="reduce",
    )
    page = context.new_page()
    try:
        resume_id = _seed_work_draft(
            page,
            frontend_url,
            include_unchanged_company=edit == "unchanged_patch_field",
        )
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        preview = page.locator('[data-export-root="resume-page"]:visible').first
        dock = page.locator('[data-slot="agent-draft-review-dock"]')
        expect(preview.get_by_text("Agent Position", exact=True)).to_be_visible()
        expect(dock).to_be_visible()
        if edit == "different_section":
            page.get_by_role(
                "button", name="基本信息: 展开或收起模块", exact=True
            ).click()
            page.get_by_role("textbox", name="姓名", exact=True).fill("Manual Person")
        else:
            _open_work_editor(page)
            page.get_by_role("textbox", name="公司 / 组织", exact=True).fill(
                "Manual Company"
            )
        expect(preview.get_by_text("Agent Position", exact=True)).to_be_visible()
        expect(dock).to_be_visible()
        saved = _save_resume(page, frontend_url, resume_id)
        assert saved["sections"][0]["items"][0]["position"] == "Engineer"
        if edit == "different_section":
            assert saved["basic"]["name"] == "Manual Person"
        else:
            assert saved["sections"][0]["items"][0]["company"] == "Manual Company"
        page.reload(wait_until="networkidle")
        expect(preview.get_by_text("Agent Position", exact=True)).to_be_visible()
        expect(dock).to_be_visible()
        expect(page.get_by_text("整批修改未应用", exact=True)).to_have_count(0)
        page.get_by_role("button", name="应用剩余全部", exact=True).click()
        expect(page.get_by_text("已应用 1 项，已放弃 0 项", exact=True)).to_be_visible()
        applied = _saved_resume(page, frontend_url, resume_id)
        assert applied["sections"][0]["items"][0]["position"] == "Agent Position"
        if edit == "different_section":
            assert applied["basic"]["name"] == "Manual Person"
        else:
            assert applied["sections"][0]["items"][0]["company"] == "Manual Company"
    finally:
        context.close()


def _review_statuses(page: Page, frontend_url: str, resume_id: str) -> dict[str, str]:
    session = page.request.get(
        f"{frontend_url}/api/agent/resumes/{resume_id}/session"
    ).json()["data"]
    return {
        item["id"]: item["status"]
        for item in session["messages"][-1]["response"]["draft"]["reviewItems"]
    }


def _edit_work_and_person(page: Page, *, edit_summary: bool = False) -> None:
    _open_work_editor(page)
    page.get_by_role("textbox", name="职位 / 角色", exact=True).fill("Manual Position")
    page.get_by_role("textbox", name="公司 / 组织", exact=True).fill("Manual Company")
    page.get_by_role("button", name="基本信息: 展开或收起模块", exact=True).click()
    page.get_by_role("textbox", name="姓名", exact=True).fill("Manual Person")
    if edit_summary:
        page.get_by_role("textbox", name="个人总结", exact=True).fill("Manual Summary")


@pytest.mark.parametrize(
    ("resolution", "motion", "save_first", "single"),
    [
        ("use-original", "no-preference", True, False),
        ("keep-manual", "reduce", False, True),
        ("discard", "no-preference", True, False),
    ],
)
def test_draft_resolution_distinguishes_original_manual_merge_and_discard(
    browser: Browser,
    workspace_servers: tuple[str, str],
    resolution: str,
    motion: str,
    save_first: bool,
    single: bool,
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1800, "height": 1000},
        reduced_motion=motion,
    )
    page = context.new_page()
    try:
        resume_id = _seed_work_draft(
            page,
            frontend_url,
            include_unchanged_company=True,
            include_summary=True,
        )
        base = _saved_resume(page, frontend_url, resume_id)
        manual = deepcopy(base)
        manual["sections"][0]["items"][0].update(
            position="Manual Position",
            company="Manual Company",
        )
        manual["basic"]["name"] = "Manual Person"
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        _edit_work_and_person(page)
        preview = page.locator('[data-export-root="resume-page"]:visible').first
        expect(preview.get_by_text("Manual Position", exact=True)).to_be_visible()
        expect(preview.get_by_text("Agent Summary", exact=True)).to_be_visible()
        if save_first:
            assert _save_resume(page, frontend_url, resume_id) == manual
            page.reload(wait_until="networkidle")
        if single:
            page.get_by_role("button", name="逐项查看", exact=True).click()
        expect(page.get_by_text("整批修改未应用", exact=True)).to_have_count(0)
        page.get_by_role("button", name="处理草稿冲突", exact=True).click()
        comparison = page.locator('[data-slot="agent-draft-conflict-comparison"]')
        expect(comparison.get_by_text("Agent Position", exact=True)).to_be_visible()
        apply = comparison.get_by_role("button", name="应用原建议", exact=True)
        keep = comparison.get_by_role("button", name="保留手动修改", exact=True)
        expect(apply).to_be_enabled()
        expect(keep).to_be_enabled()
        footer = comparison.locator('[data-slot="agent-draft-conflict-actions"]')
        expect(
            footer.get_by_text("处理全部 2 项待确认修改", exact=True)
        ).to_be_visible()
        expect(footer.get_by_role("button")).to_have_count(2)
        pending = _review_statuses(page, frontend_url, resume_id)
        assert len(pending) == 2 and set(pending.values()) == {"pending"}
        before = _saved_resume(page, frontend_url, resume_id)
        page.keyboard.press("Escape")
        expect(comparison).to_have_count(0)
        assert _review_statuses(page, frontend_url, resume_id) == pending
        assert _saved_resume(page, frontend_url, resume_id) == before
        if resolution != "discard":
            page.get_by_role("button", name="处理草稿冲突", exact=True).click()
        with page.expect_response(
            lambda response: (
                response.request.method == "PATCH"
                and f"/messages/draft-work-{resume_id}/draft" in response.url
            )
        ) as decided:
            if resolution == "discard":
                page.get_by_role("button", name="放弃剩余全部", exact=True).click()
            else:
                (apply if resolution == "use-original" else keep).click()
        assert decided.value.ok
        assert set(decided.value.request.post_data_json["reviewItemIds"]) == set(
            pending
        )
        expected = deepcopy(base if resolution == "use-original" else manual)
        if resolution == "use-original":
            expected["sections"][0]["items"][0]["position"] = "Agent Position"
        if resolution != "discard":
            expected["basic"]["summary"] = "Agent Summary"
        expected_status = "discarded" if resolution == "discard" else "applied"
        assert _review_statuses(page, frontend_url, resume_id) == {
            key: expected_status for key in pending
        }
        assert _saved_resume(page, frontend_url, resume_id) == expected
        expect(page.locator('[data-slot="agent-draft-review-dock"]')).to_have_count(0)
        page.reload(wait_until="networkidle")
        assert _saved_resume(page, frontend_url, resume_id) == expected
        expect(page.locator('[data-slot="agent-draft-review-dock"]')).to_have_count(0)
        expect(
            preview.get_by_text(
                expected["sections"][0]["items"][0]["position"],
                exact=True,
            )
        ).to_be_visible()
        if resolution != "discard":
            expect(preview.get_by_text("Agent Summary", exact=True)).to_be_visible()
    finally:
        context.close()


@pytest.mark.parametrize("resolution", ["use-original", "keep-manual"])
def test_draft_resolution_handles_manually_deleted_items(
    browser: Browser,
    workspace_servers: tuple[str, str],
    resolution: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1800, "height": 1000},
        reduced_motion="reduce",
    )
    page = context.new_page()
    try:
        resume_id = _seed_work_draft(page, frontend_url, include_summary=True)
        base = _saved_resume(page, frontend_url, resume_id)
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        _open_work_editor(page)
        page.get_by_role("button", name="删除条目 1", exact=True).click()
        _save_resume(page, frontend_url, resume_id)
        page.reload(wait_until="networkidle")
        page.get_by_role("button", name="处理草稿冲突", exact=True).click()
        comparison = page.locator('[data-slot="agent-draft-conflict-comparison"]')
        action = comparison.get_by_role(
            "button",
            name="应用原建议" if resolution == "use-original" else "保留手动修改",
            exact=True,
        )
        expect(action).to_be_enabled()
        action.click()
        expect(page.get_by_text("已应用 2 项，已放弃 0 项", exact=True)).to_be_visible()
        expected = deepcopy(base)
        expected["basic"]["summary"] = "Agent Summary"
        if resolution == "use-original":
            expected["sections"][0]["items"][0]["position"] = "Agent Position"
        else:
            expected["sections"][0]["items"] = []
        assert _saved_resume(page, frontend_url, resume_id) == expected
        page.reload(wait_until="networkidle")
        assert _saved_resume(page, frontend_url, resume_id) == expected
        assert set(_review_statuses(page, frontend_url, resume_id).values()) == {
            "applied"
        }
    finally:
        context.close()


@pytest.mark.parametrize("resolution", ["use-original", "keep-manual"])
def test_draft_resolution_respects_previously_applied_and_discarded_reviews(
    browser: Browser,
    workspace_servers: tuple[str, str],
    resolution: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1800, "height": 1000},
        reduced_motion="reduce",
    )
    page = context.new_page()
    try:
        resume_id = _seed_work_draft(
            page,
            frontend_url,
            include_summary=True,
            include_headline=True,
        )
        base = _saved_resume(page, frontend_url, resume_id)
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role("button", name="逐项查看", exact=True).click()
        page.get_by_role("button", name="应用此项", exact=True).click()
        expect(page.get_by_text("第 1/2 项", exact=True)).to_be_visible()
        page.get_by_role("button", name="下一项修改", exact=True).click()
        expect(page.get_by_text("第 2/2 项", exact=True)).to_be_visible()
        page.get_by_role("button", name="放弃此项", exact=True).click()
        expect(page.get_by_text("第 1/1 项", exact=True)).to_be_visible()
        work_id = f"review-edit-work-{resume_id}"
        summary_id = f"review-edit-summary-{resume_id}"
        headline_id = f"review-edit-headline-{resume_id}"
        assert _review_statuses(page, frontend_url, resume_id) == {
            work_id: "applied",
            summary_id: "pending",
            headline_id: "discarded",
        }
        _edit_work_and_person(page, edit_summary=True)
        manual = _save_resume(page, frontend_url, resume_id)
        page.reload(wait_until="networkidle")
        page.get_by_role("button", name="处理草稿冲突", exact=True).click()
        comparison = page.locator('[data-slot="agent-draft-conflict-comparison"]')
        with page.expect_response(
            lambda response: (
                response.request.method == "PATCH"
                and f"/messages/draft-work-{resume_id}/draft" in response.url
            )
        ) as decided:
            comparison.get_by_role(
                "button",
                name="应用原建议" if resolution == "use-original" else "保留手动修改",
                exact=True,
            ).click()
        assert decided.value.ok
        assert decided.value.request.post_data_json["reviewItemIds"] == [summary_id]
        expected = deepcopy(base if resolution == "use-original" else manual)
        if resolution == "use-original":
            expected["sections"][0]["items"][0]["position"] = "Agent Position"
            expected["basic"]["summary"] = "Agent Summary"
        assert expected["basic"]["headline"] == base["basic"]["headline"]
        assert _saved_resume(page, frontend_url, resume_id) == expected
        assert _review_statuses(page, frontend_url, resume_id) == {
            work_id: "applied",
            summary_id: "applied",
            headline_id: "discarded",
        }
        page.reload(wait_until="networkidle")
        assert _saved_resume(page, frontend_url, resume_id) == expected
        expect(page.locator('[data-slot="agent-draft-review-dock"]')).to_have_count(0)
    finally:
        context.close()
