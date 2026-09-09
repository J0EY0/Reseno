"""Template drafts remain recoverable until an explicit save or discard."""

from __future__ import annotations

import os
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Page, expect

from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _rename_template(page: Page, name: str) -> None:
    page.get_by_role("button", name="修改模板信息", exact=True).click()
    dialog = page.get_by_role("dialog", name="修改模板信息", exact=True)
    dialog.get_by_label("模板名称", exact=True).fill(name)
    dialog.get_by_role("button", name="保存", exact=True).click()
    expect(page.locator('[data-slot="template-editor-title"]')).to_have_text(name)


def _template(page: Page, frontend_url: str, template_id: str) -> dict:
    response = page.request.get(f"{frontend_url}/api/templates")
    assert response.ok
    return next(
        item
        for item in response.json()["data"]["templates"]
        if item["id"] == template_id
    )


@pytest.mark.parametrize("reload_after_autosave", [False, True])
@pytest.mark.parametrize("explicit_save_first", [False, True])
def test_template_autosave_preserves_explicit_save_for_discard(
    browser: Browser,
    workspace_servers: tuple[str, str],
    reload_after_autosave: bool,
    explicit_save_first: bool,
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 900}
    )
    page = context.new_page()
    template_id: str | None = None
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role("button", name="创建可编辑副本", exact=True).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = page.url.rsplit("/", maxsplit=1)[-1]
        template_path = f"/api/templates/{template_id}"
        if explicit_save_first:
            _rename_template(page, "Explicit template checkpoint")
            with page.expect_response(
                lambda response: (
                    response.request.method == "PUT"
                    and urlparse(response.url).path == template_path
                )
            ) as saved:
                page.keyboard.press("Control+S")
            assert saved.value.ok
        baseline = _template(page, frontend_url, template_id)
        page.clock.install()
        _rename_template(page, "Automatically saved template draft")
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == template_path
            )
        ) as autosaved:
            page.clock.fast_forward(5_000)
        assert autosaved.value.ok
        assert _template(page, frontend_url, template_id)["name"] == (
            "Automatically saved template draft"
        )
        if reload_after_autosave:
            page.once("dialog", lambda dialog: dialog.accept())
            page.reload(wait_until="networkidle")
            expect(page.locator('[data-slot="template-editor-title"]')).to_have_text(
                "Automatically saved template draft"
            )
        page.get_by_role("button", name="返回模板列表", exact=True).click()
        leave = page.get_by_role("dialog", name="有未保存的更改", exact=True)
        expect(leave).to_be_visible()
        leave.get_by_role("button", name="放弃更改", exact=True).click()
        page.wait_for_url(f"{frontend_url}/templates")
        restored = _template(page, frontend_url, template_id)
        assert {
            key: value for key, value in restored.items() if key != "updatedAt"
        } == {key: value for key, value in baseline.items() if key != "updatedAt"}
        page.goto(f"{frontend_url}/template/{template_id}", wait_until="networkidle")
        expect(page.locator('[data-slot="template-editor-title"]')).to_have_text(
            baseline["name"]
        )
        page.get_by_role("button", name="返回模板列表", exact=True).click()
        page.wait_for_url(f"{frontend_url}/templates")
        assert errors == []
    finally:
        if template_id:
            response = page.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if response.ok:
                page.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


@pytest.mark.parametrize("save_mode", ["autosave", "checkpoint"])
@pytest.mark.parametrize("leave_action", ["discard", "save"])
def test_template_leave_resolves_an_active_save_without_losing_its_checkpoint(
    browser: Browser,
    workspace_servers: tuple[str, str],
    save_mode: str,
    leave_action: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 900},
        reduced_motion="reduce",
    )
    page = context.new_page()
    held = []
    saves = []
    template_id: str | None = None
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role("button", name="创建可编辑副本", exact=True).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = page.url.rsplit("/", maxsplit=1)[-1]
        baseline = _template(page, frontend_url, template_id)
        path = f"/api/templates/{template_id}"

        def hold_first_save(route):
            if route.request.method != "PUT":
                route.continue_()
                return
            saves.append(route.request.post_data_json)
            if len(saves) == 1:
                held.append(route)
            else:
                route.continue_()

        page.route(f"**{path}", hold_first_save)
        page.clock.install()
        _rename_template(page, "Snapshot in flight")
        with page.expect_request(
            lambda request: (
                request.method == "PUT" and urlparse(request.url).path == path
            )
        ):
            if save_mode == "autosave":
                page.clock.fast_forward(5_000)
            else:
                page.keyboard.press("Control+S")
        assert len(held) == 1
        assert saves[0]["saveMode"] == save_mode
        _rename_template(page, "Newer template edit")
        page.get_by_role("button", name="返回模板列表", exact=True).click()
        leave = page.get_by_role("dialog", name="有未保存的更改", exact=True)
        expect(leave).to_be_visible()
        leave.get_by_role(
            "button",
            name="放弃更改" if leave_action == "discard" else "保存并离开",
            exact=True,
        ).click()
        expect(leave).to_be_visible()
        assert page.url == f"{frontend_url}/template/{template_id}"
        held.pop().continue_()
        page.wait_for_url(f"{frontend_url}/templates")
        expected_name = (
            baseline["name"] if leave_action == "discard" else "Newer template edit"
        )
        assert _template(page, frontend_url, template_id)["name"] == expected_name
        detail = page.request.get(f"{frontend_url}{path}").json()["data"]
        assert detail["checkpoint"] is None
        page.clock.fast_forward(60_000)
        assert _template(page, frontend_url, template_id)["name"] == expected_name
        assert errors == []
    finally:
        for route in held:
            route.abort()
        if template_id:
            response = page.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if response.ok:
                page.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


def test_manual_save_confirms_already_autosaved_template(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 900}
    )
    page = context.new_page()
    template_id: str | None = None
    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role("button", name="创建可编辑副本", exact=True).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = page.url.rsplit("/", maxsplit=1)[-1]
        path = f"/api/templates/{template_id}"
        page.clock.install()
        _rename_template(page, "Confirmed autosaved template")
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT" and urlparse(response.url).path == path
            )
        ) as autosaved:
            page.clock.fast_forward(5_000)
        assert autosaved.value.ok
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT" and urlparse(response.url).path == path
            )
        ) as confirmed:
            page.keyboard.press("Control+S")
        assert confirmed.value.ok
        assert confirmed.value.request.post_data_json["saveMode"] == "checkpoint"
        assert confirmed.value.json()["data"]["checkpoint"] is None
        page.get_by_role("button", name="返回模板列表", exact=True).click()
        page.wait_for_url(f"{frontend_url}/templates")
        assert (
            _template(page, frontend_url, template_id)["name"]
            == "Confirmed autosaved template"
        )
    finally:
        if template_id:
            response = page.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if response.ok:
                page.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


def test_template_discard_restores_autosave_when_its_response_is_lost(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 900}
    )
    page = context.new_page()
    template_id: str | None = None
    committed = []
    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role("button", name="创建可编辑副本", exact=True).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = page.url.rsplit("/", maxsplit=1)[-1]
        baseline = _template(page, frontend_url, template_id)
        path = f"/api/templates/{template_id}"

        def lose_save_response(route):
            if route.request.method != "PUT":
                route.continue_()
                return
            response = route.fetch()
            assert response.ok
            committed.append(response.json()["data"])
            route.abort("connectionclosed")

        page.route(f"**{path}", lose_save_response)
        page.clock.install()
        _rename_template(page, "Committed draft with a lost response")
        with page.expect_event(
            "requestfailed",
            predicate=lambda request: (
                request.method == "PUT" and urlparse(request.url).path == path
            ),
        ):
            page.clock.fast_forward(5_000)
        assert len(committed) == 1
        assert committed[0]["checkpoint"] == baseline
        assert committed[0]["template"]["name"] == (
            "Committed draft with a lost response"
        )
        page.get_by_role("button", name="返回模板列表", exact=True).click()
        leave = page.get_by_role("dialog", name="有未保存的更改", exact=True)
        leave.get_by_role("button", name="放弃更改", exact=True).click()
        page.wait_for_url(f"{frontend_url}/templates")
        detail = page.request.get(f"{frontend_url}{path}").json()["data"]
        assert detail["checkpoint"] is None
        assert {
            key: value
            for key, value in detail["template"].items()
            if key != "updatedAt"
        } == {key: value for key, value in baseline.items() if key != "updatedAt"}
        page.clock.fast_forward(60_000)
        assert len(committed) == 1
        page.goto(f"{frontend_url}/template/{template_id}", wait_until="networkidle")
        expect(page.locator('[data-slot="template-editor-title"]')).to_have_text(
            baseline["name"]
        )
        page.get_by_role("button", name="返回模板列表", exact=True).click()
        page.wait_for_url(f"{frontend_url}/templates")
    finally:
        if template_id:
            response = page.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if response.ok:
                page.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()
