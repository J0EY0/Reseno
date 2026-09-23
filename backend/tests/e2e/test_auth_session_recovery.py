"""Authentication recovery while the mounted editor retains local work."""

from __future__ import annotations

import os

import pytest
from playwright.sync_api import Browser, Page, Route, expect

from tests.e2e.browser_support import authenticated_context, browser_session

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _open_custom_template(page: Page, frontend_url: str) -> str:
    page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
    page.get_by_role("button", name="创建副本", exact=True).click()
    page.wait_for_url(f"{frontend_url}/template/template-*")
    return page.url.rsplit("/", maxsplit=1)[-1]


def _expire_save(route: Route) -> None:
    if route.request.method != "PUT":
        route.continue_()
        return
    response = route.fetch(
        headers={
            **route.request.headers,
            "authorization": "Bearer invalid-session-recovery-token",
        }
    )
    assert response.status == 401
    payload = response.json()
    assert payload["code"] == 40001
    assert payload["message"] == "UNAUTHORIZED_REQUEST"
    assert payload["data"]["reason"] == "invalid_or_expired_token"
    route.fulfill(response=response)


@pytest.mark.parametrize(
    ("document_kind", "recovery", "trigger"),
    [
        ("resume", "dialog-login", "shortcut"),
        ("resume", "other-tab", "button"),
        ("template", "dialog-login", "shortcut"),
        ("template", "dialog-login", "button"),
    ],
)
def test_expired_session_preserves_workspace_input(
    browser: Browser,
    workspace_servers: tuple[str, str],
    document_kind: str,
    recovery: str,
    trigger: str,
) -> None:
    frontend_url, _ = workspace_servers
    compact_dialog = document_kind == "template" and trigger == "shortcut"
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 900},
        reduced_motion="reduce",
    )
    context.set_extra_http_headers({})
    page = context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    def supply_model(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["modelConfigs"] = [
            {
                "id": "session-recovery-model",
                "provider": "openai",
                "nickname": "Session recovery model",
                "model": "test-model",
                "supportsTools": True,
            }
        ]
        payload["data"]["agentSettings"]["defaultModelConfigId"] = (
            "session-recovery-model"
        )
        route.fulfill(response=response, json=payload)

    try:
        if document_kind == "resume":
            created = page.request.post(
                f"{frontend_url}/api/resumes",
                headers={"Authorization": f"Bearer {browser_session['accessToken']}"},
                data={"documentLocale": "zh", "title": f"Session recovery {recovery}"},
            )
            assert created.ok
            document_id = created.json()["data"]["resume"]["id"]
            page.route("**/api/workspace/pages/resume-editor", supply_model)
            page.goto(f"{frontend_url}/resume/{document_id}", wait_until="networkidle")
            api_path = f"/api/resumes/{document_id}"
            pattern = f"**{api_path}?*"
        else:
            document_id = _open_custom_template(page, frontend_url)
            api_path = f"/api/templates/{document_id}"
            pattern = f"**{api_path}"
        other_page = None
        if recovery == "other-tab":
            other_page = context.new_page()
            other_page.route(
                "**/session-recovery-tab",
                lambda route: route.fulfill(
                    content_type="text/html", body="<html></html>"
                ),
            )
            other_page.goto(f"{frontend_url}/session-recovery-tab")
            page.bring_to_front()

        prompt = None
        if document_kind == "resume":
            page.get_by_role(
                "button", name="基本信息: 展开或收起模块", exact=True
            ).click()
            name = page.get_by_role("textbox", name="姓名", exact=True)
            name.fill("Unsaved session recovery name")
            prompt = page.get_by_role("textbox", name="你想了解什么？", exact=True)
            prompt.fill("Keep this unsent Agent prompt.")
        else:
            page.get_by_role("button", name="修改模板信息", exact=True).click()
            metadata = page.get_by_role("dialog", name="修改模板信息", exact=True)
            metadata.get_by_label("模板名称", exact=True).fill(
                "Unsaved session recovery name"
            )
            metadata.get_by_role("button", name="保存", exact=True).click()
            name = page.get_by_role(
                "heading", name="Unsaved session recovery name", exact=True
            )
            expect(name).to_have_text("Unsaved session recovery name")
        editor_node = name.element_handle()
        composer_node = prompt.element_handle() if prompt is not None else None
        assert editor_node is not None
        original_url = page.url
        if compact_dialog:
            expect(page.get_by_text("已创建自定义模板", exact=True)).to_be_visible()
        page.route(pattern, _expire_save)
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and api_path in response.url
                and response.status == 401
            )
        ):
            if trigger == "shortcut":
                page.keyboard.press("ControlOrMeta+s")
            else:
                page.get_by_role("button", name="保存状态", exact=True).click()

        dialog = page.get_by_role("dialog", name="登录已过期", exact=True)
        expect(dialog).to_be_visible()
        expect(page).to_have_url(original_url)
        assert editor_node.evaluate("node => node.isConnected")
        assert editor_node.inner_text() == "Unsaved session recovery name"
        if composer_node is not None:
            assert composer_node.evaluate("node => node.isConnected")
            assert composer_node.input_value() == "Keep this unsent Agent prompt."

        if compact_dialog:
            expect(page.locator("[data-sonner-toast]")).to_have_count(0, timeout=1_000)
            page.set_viewport_size({"width": 390, "height": 400})
            bounds = dialog.bounding_box()
            assert bounds is not None
            assert bounds["y"] >= 0, bounds
            assert bounds["y"] + bounds["height"] <= 400, bounds
        if recovery == "dialog-login":
            dialog.get_by_label("用户名", exact=True).fill("e2e-owner")
            dialog.get_by_label("密码", exact=True).fill("E2ePassword2026")
            login_button = dialog.get_by_role("button", name="登录", exact=True)
            if compact_dialog:
                dialog.get_by_role(
                    "link", name="在新标签页登录", exact=True
                ).scroll_into_view_if_needed()
                assert dialog.evaluate("element => element.scrollTop > 0")
                login_button.scroll_into_view_if_needed()
                page.screenshot(path="/tmp/reseno-auth-session-compact.png")
            login_button.click()
        else:
            assert other_page is not None
            response = other_page.request.post(
                f"{frontend_url}/api/auth/login",
                data={"username": "e2e-owner", "password": "E2ePassword2026"},
            )
            assert response.ok
            session = response.json()["data"]
            other_page.evaluate(
                "session => localStorage.setItem("
                "'reseno-auth-session', JSON.stringify(session))",
                session,
            )
        expect(dialog).not_to_be_visible()
        expect(page).to_have_url(original_url)
        assert name.evaluate("(node, original) => node === original", editor_node)
        expect(name).to_have_text("Unsaved session recovery name")
        if prompt is not None:
            assert prompt.evaluate(
                "(node, original) => node === original", composer_node
            )
            expect(prompt).to_have_value("Keep this unsent Agent prompt.")

        page.unroute(pattern, _expire_save)
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and api_path in response.url
                and response.status == 200
            )
        ):
            page.keyboard.press("ControlOrMeta+s")
        current_token = page.evaluate(
            "JSON.parse(localStorage.getItem('reseno-auth-session')).accessToken"
        )
        read_path = api_path if document_kind == "resume" else "/api/templates"
        saved = page.request.get(
            f"{frontend_url}{read_path}",
            headers={"Authorization": f"Bearer {current_token}"},
        )
        assert saved.ok
        payload = saved.json()["data"]
        saved_name = (
            payload["resume"]["resume"]["basic"]["name"]
            if document_kind == "resume"
            else next(
                template["name"]
                for template in payload["templates"]
                if template["id"] == document_id
            )
        )
        assert saved_name == "Unsaved session recovery name"
        if prompt is not None:
            expect(prompt).to_have_value("Keep this unsent Agent prompt.")
        assert page_errors == []
    finally:
        context.close()


def test_auth_setup_failure_centers_retry_action(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.route("**/api/auth/setup", lambda route: route.abort())

    try:
        page.goto(frontend_url, wait_until="networkidle")
        header = page.locator('[data-slot="card-header"]')
        retry = page.get_by_role("button", name="重试", exact=True)
        expect(
            page.get_by_role("heading", name="初始化状态加载失败", exact=True)
        ).to_be_visible()
        expect(retry).to_be_visible()

        header_box = header.bounding_box()
        retry_box = retry.bounding_box()
        assert header_box is not None
        assert retry_box is not None
        assert retry_box["x"] + retry_box["width"] / 2 == pytest.approx(
            header_box["x"] + header_box["width"] / 2,
            abs=1,
        )
    finally:
        context.close()


@pytest.mark.parametrize("unsupported", ["insecure-context", "missing-locks"])
def test_unsupported_auth_environment_explains_access_requirements(
    browser: Browser,
    workspace_servers: tuple[str, str],
    unsupported: str,
) -> None:
    frontend_url, resume_id = workspace_servers
    context = authenticated_context(browser, locale="zh-CN")
    context.add_init_script(
        "Object.defineProperty(window, 'isSecureContext', {value: false});"
        if unsupported == "insecure-context"
        else "Object.defineProperty(navigator, 'locks', {value: undefined});"
    )
    context.set_extra_http_headers({})
    page = context.new_page()
    page.clock.install()
    refresh_requests: list[str] = []
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    page.on(
        "request",
        lambda request: (
            refresh_requests.append(request.url)
            if request.url.endswith("/api/auth/refresh")
            else None
        ),
    )
    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        expect(
            page.get_by_role("heading", name="当前访问方式不受支持", exact=True)
        ).to_be_visible()
        if unsupported == "insecure-context":
            expect(page.get_by_text("HTTPS", exact=False)).to_be_visible()
            expect(page.get_by_text("localhost", exact=False)).to_be_visible()
        else:
            expect(page.get_by_text("请更新浏览器后重试", exact=False)).to_be_visible()
        page.clock.fast_forward(4 * 60 * 60 * 1_000)
        assert refresh_requests == []
        assert page_errors == []
    finally:
        context.close()


@pytest.mark.parametrize("document_kind", ["resume", "template"])
def test_reauthentication_restarts_autosave_without_another_edit(
    browser: Browser,
    workspace_servers: tuple[str, str],
    document_kind: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 900},
        reduced_motion="reduce",
    )
    context.set_extra_http_headers({})
    page = context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    try:
        if document_kind == "resume":
            created = page.request.post(
                f"{frontend_url}/api/resumes",
                headers={"Authorization": f"Bearer {browser_session['accessToken']}"},
                data={"documentLocale": "zh", "title": "Delayed reauthentication"},
            )
            assert created.ok
            document_id = created.json()["data"]["resume"]["id"]
            page.goto(f"{frontend_url}/resume/{document_id}", wait_until="networkidle")
            page.get_by_role(
                "button", name="基本信息: 展开或收起模块", exact=True
            ).click()
            field = page.get_by_role("textbox", name="姓名", exact=True)
            api_path = f"/api/resumes/{document_id}"
            pattern = f"**{api_path}?*"
        else:
            document_id = _open_custom_template(page, frontend_url)
            page.get_by_role("button", name="修改模板信息", exact=True).click()
            field = page.get_by_label("模板名称", exact=True)
            api_path = f"/api/templates/{document_id}"
            pattern = f"**{api_path}"
        previous_token = page.evaluate(
            "JSON.parse(localStorage.getItem('reseno-auth-session')).accessToken"
        )
        expect(field).to_be_visible()
        expect(field).to_be_editable()
        page.clock.install()
        page.route(pattern, _expire_save)
        field.fill("Automatically saved after reauthentication")
        if document_kind == "template":
            page.get_by_role("dialog", name="修改模板信息", exact=True).get_by_role(
                "button", name="保存", exact=True
            ).click()
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and api_path in response.url
                and response.status == 401
            )
        ):
            page.clock.fast_forward(5_000)
        dialog = page.get_by_role("dialog", name="登录已过期", exact=True)
        expect(dialog).to_be_visible()
        original_url = page.url
        for elapsed_ms in (2_000, 5_000, 60_000):
            page.clock.fast_forward(elapsed_ms)
            expect(dialog).to_be_visible()
        page.unroute(pattern, _expire_save)
        dialog.get_by_label("用户名", exact=True).fill("e2e-owner")
        dialog.get_by_label("密码", exact=True).fill("E2ePassword2026")
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and api_path in response.url
                and response.status == 200
            ),
            timeout=10_000,
        ) as autosaved:
            dialog.get_by_role("button", name="登录", exact=True).click()
            expect(dialog).not_to_be_visible()
            page.clock.fast_forward(5_000)
        expect(page).to_have_url(original_url)
        current_token = page.evaluate(
            "JSON.parse(localStorage.getItem('reseno-auth-session')).accessToken"
        )
        assert current_token != previous_token
        assert autosaved.value.request.headers["authorization"] == (
            f"Bearer {current_token}"
        )
        read_path = api_path if document_kind == "resume" else "/api/templates"
        saved = page.request.get(
            f"{frontend_url}{read_path}",
            headers={"Authorization": f"Bearer {current_token}"},
        )
        assert saved.ok
        payload = saved.json()["data"]
        saved_name = (
            payload["resume"]["resume"]["basic"]["name"]
            if document_kind == "resume"
            else next(
                template["name"]
                for template in payload["templates"]
                if template["id"] == document_id
            )
        )
        assert saved_name == "Automatically saved after reauthentication"
        assert page_errors == []
    finally:
        context.close()
