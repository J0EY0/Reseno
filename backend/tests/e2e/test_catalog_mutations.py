"""Catalog mutations retain successful work across delayed and failed requests."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import Browser, Page, Route, expect

from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _template(name: str) -> dict[str, object]:
    presets = json.loads(
        (
            Path(__file__).resolve().parents[2] / "app/services/template_presets.json"
        ).read_text(encoding="utf-8")
    )
    return {
        "preset": "minimal",
        "name": name,
        "description": "",
        **{
            key: presets["minimal"][key] for key in ("layout", "typography", "settings")
        },
    }


def _create_template(page: Page, url: str, name: str) -> dict[str, object]:
    response = page.request.post(
        f"{url}/api/templates", data={"template": _template(name)}
    )
    assert response.ok
    return response.json()["data"]["template"]


def _import_templates(page: Page, names: list[str]) -> None:
    page.locator('input[type="file"]').set_input_files(
        {
            "name": "templates.json",
            "mimeType": "application/json",
            "buffer": json.dumps(
                {
                    "format": "resumate.template",
                    "formatVersion": 1,
                    "templates": [_template(name) for name in names],
                }
            ).encode(),
        }
    )


def _delete_selected_templates(page: Page) -> None:
    page.get_by_role("button", name="批量删除", exact=True).click()
    page.get_by_role("alertdialog").get_by_role(
        "button", name="确认删除", exact=True
    ).click()


@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
def test_model_delete_preserves_creation_completed_while_delete_waits(
    browser: Browser,
    workspace_servers: tuple[str, str],
    reduced_motion: str,
) -> None:
    url, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1280, "height": 900},
        reduced_motion=reduced_motion,
    )
    page = context.new_page()
    prefix = f"Model-{uuid4().hex[:8]}"
    pending: list[Route] = []
    provider = {
        "id": "ollama",
        "label": "Ollama",
        "kind": "local",
        "apiFamily": "openai_compatible_chat",
        "iconProvider": "ollama",
        "defaultBaseUrl": "http://127.0.0.1:9/v1",
        "officialUrl": "",
        "authRequired": False,
        "supportsModelDiscovery": False,
        "supportsCustomCapabilities": False,
        "supportsTools": True,
        "supportsStreaming": True,
    }
    try:
        response = page.request.post(
            f"{url}/api/model-configs",
            data={
                "provider": "ollama",
                "providerKind": "local",
                "apiFamily": "openai_compatible_chat",
                "nickname": prefix + " A",
                "apiKey": "",
                "model": "catalog-model",
                "apiUrl": provider["defaultBaseUrl"],
                "temperature": None,
                "topP": None,
                "maxTokens": 512,
            },
        )
        assert response.ok, response.text()
        model_id = response.json()["data"]["id"]
        page.route(
            "**/api/model-providers",
            lambda route: route.fulfill(
                json={
                    "code": 0,
                    "message": "OK",
                    "data": {"providers": [provider]},
                }
            ),
        )
        page.goto(f"{url}/models", wait_until="networkidle")
        page.route(
            f"**/api/model-configs/{model_id}", lambda route: pending.append(route)
        )
        row = page.get_by_role("row").filter(has_text=prefix + " A")
        row.get_by_role("button", name="操作", exact=True).click()
        page.get_by_role("menuitem", name="删除", exact=True).click()
        with page.expect_request(lambda request: request.method == "DELETE"):
            page.get_by_role("alertdialog").get_by_role(
                "button", name="删除模型"
            ).click()
        assert pending
        page.get_by_role("button", name="新建模型", exact=True).click()
        expect(page.locator("#model-nickname")).to_be_focused()
        page.locator("#model-nickname").fill(prefix + " C")
        page.locator("#model-name").fill("new-catalog-model")
        page.get_by_role("button", name="创建模型", exact=True).click()
        expect(page.get_by_role("row").filter(has_text=prefix + " C")).to_be_visible()
        expect(page.get_by_role("button", name="新建模型", exact=True)).to_be_focused()
        with page.expect_response(lambda response: response.request.method == "DELETE"):
            pending.pop().continue_()
        expect(row).to_have_count(0)
        expect(page.get_by_role("row").filter(has_text=prefix + " C")).to_be_visible()
        records = page.request.get(f"{url}/api/workspace/pages/models").json()["data"][
            "modelConfigs"
        ]
        assert prefix + " C" in {item["nickname"] for item in records}
    finally:
        for route in pending:
            route.abort()
        context.close()


def test_template_import_keeps_successes_and_retries_only_failed_items(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    url, _ = workspace_servers
    context = authenticated_context(browser, locale="zh-CN")
    page = context.new_page()
    prefix = f"Import-{uuid4().hex[:8]}"
    names = [prefix + suffix for suffix in (" A", " B", " C")]
    writes: list[str] = []
    failed_once = False

    def fail_second_import(route: Route) -> None:
        nonlocal failed_once
        name = route.request.post_data_json["template"]["name"]
        writes.append(name)
        if name == names[1] and not failed_once:
            failed_once = True
            route.fulfill(
                status=503, json={"code": "REQUEST_FAILED", "message": "Unavailable"}
            )
        else:
            route.continue_()

    try:
        page.goto(f"{url}/templates?q={prefix}", wait_until="networkidle")
        page.route("**/api/templates", fail_second_import)
        _import_templates(page, names)
        expect(page.get_by_role("link", name=names[0], exact=True)).to_be_visible()
        expect(page.get_by_role("link", name=names[2], exact=True)).to_be_visible()
        expect(page.get_by_role("link", name=names[1], exact=True)).to_have_count(0)
        page.get_by_role("button", name="重试", exact=True).click()
        page.wait_for_url(f"{url}/template/template-*")
        expect(page.locator('[data-slot="template-editor-title"]')).to_have_text(
            names[1]
        )
        assert writes == [*names, names[1]]
        templates = page.request.get(f"{url}/api/workspace/pages/templates").json()[
            "data"
        ]["customTemplates"]
        assert (
            sorted(
                item["name"] for item in templates if item["name"].startswith(prefix)
            )
            == names
        )
    finally:
        context.close()


def test_template_import_retry_actions_all_disappear_after_leaving_gallery(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    url, _ = workspace_servers
    context = authenticated_context(browser, locale="zh-CN")
    page = context.new_page()
    try:
        page.goto(f"{url}/templates", wait_until="networkidle")
        page.route(
            "**/api/templates",
            lambda route: route.fulfill(
                status=503, json={"code": "REQUEST_FAILED", "message": "Unavailable"}
            ),
        )
        for index in range(2):
            _import_templates(page, [f"Failed batch {index}"])
            expect(page.get_by_role("button", name="重试", exact=True)).to_have_count(
                index + 1
            )
        page.locator('a[href="/models"]').click()
        page.wait_for_url(f"{url}/models")
        expect(page.get_by_role("button", name="重试", exact=True)).to_have_count(0)
    finally:
        context.close()


def test_template_delete_keeps_failed_selection_for_retry(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    url, _ = workspace_servers
    context = authenticated_context(browser, locale="zh-CN")
    page = context.new_page()
    prefix = f"Delete-{uuid4().hex[:8]}"
    first = _create_template(page, url, prefix + " A")
    second = _create_template(page, url, prefix + " B")
    attempts = 0

    def fail_once(route: Route) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            route.fulfill(
                status=503, json={"code": "REQUEST_FAILED", "message": "Unavailable"}
            )
        else:
            route.continue_()

    try:
        page.goto(f"{url}/templates?q={prefix}", wait_until="networkidle")
        page.route(f"**/api/templates/{second['id']}/trash", fail_once)
        page.get_by_role("button", name="选择", exact=True).click()
        page.get_by_role("button", name=str(first["name"]), exact=True).click()
        page.get_by_role("button", name=str(second["name"]), exact=True).click()
        _delete_selected_templates(page)
        expect(page.locator(f'[data-gallery-item-id="{first["id"]}"]')).to_have_count(0)
        expect(
            page.get_by_role("button", name=str(second["name"]), exact=True)
        ).to_have_attribute("aria-pressed", "true")
        expect(
            page.get_by_text(
                "已删除 1 个模板，1 个失败，失败项仍保留选中。", exact=True
            )
        ).to_be_visible()
        page.locator(f'[data-gallery-item-id="{second["id"]}"]').get_by_role(
            "button", name="确认删除", exact=True
        ).click()
        page.get_by_role("alertdialog").get_by_role(
            "button", name="确认删除", exact=True
        ).click()
        expect(page.locator(f'[data-gallery-item-id="{second["id"]}"]')).to_have_count(
            0
        )
        assert attempts == 2
    finally:
        context.close()


def test_template_import_merges_concurrent_create_and_delete(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    url, _ = workspace_servers
    context = authenticated_context(
        browser, locale="zh-CN", viewport={"width": 2200, "height": 1600}
    )
    page = context.new_page()
    prefix = f"Overlap-{uuid4().hex[:8]}"
    removed = _create_template(page, url, prefix + " remove")
    pending: list[Route] = []
    try:
        page.goto(f"{url}/templates", wait_until="networkidle")
        page.route("**/api/templates", lambda route: pending.append(route))
        page.get_by_role("button", name="新建", exact=True).click()
        page.wait_for_function("document.querySelector('[aria-busy=true]') !== null")
        _import_templates(page, [prefix + " imported"])
        page.get_by_role("button", name="选择", exact=True).click()
        page.get_by_role("button", name=str(removed["name"]), exact=True).click()
        page.locator(f'[data-gallery-item-id="{removed["id"]}"]').get_by_role(
            "button", name="确认删除", exact=True
        ).click()
        page.get_by_role("alertdialog").get_by_role(
            "button", name="确认删除", exact=True
        ).click()
        expect(page.locator(f'[data-gallery-item-id="{removed["id"]}"]')).to_have_count(
            0
        )
        page.wait_for_function("document.querySelector('input[type=file]').disabled")
        assert len(pending) == 2
        created_response = pending[0].fetch()
        assert created_response.ok
        created = created_response.json()["data"]["template"]
        pending.pop(0).fulfill(response=created_response)
        expect(
            page.get_by_role("button", name=created["name"], exact=True)
        ).to_be_visible()
        pending.pop().continue_()
        page.wait_for_url(f"{url}/template/template-*")
        expect(page.locator('[data-slot="template-editor-title"]')).to_have_text(
            prefix + " imported"
        )
        page.get_by_role("button", name="返回模板列表", exact=True).click()
        page.wait_for_url(f"{url}/templates*")
        page.locator('input[name="template-search"]').fill(str(created["name"]))
        expect(
            page.get_by_role("link", name=created["name"], exact=True)
        ).to_be_visible()
        page.locator('input[name="template-search"]').fill(prefix + " remove")
        expect(page.locator(f'[data-gallery-item-id="{removed["id"]}"]')).to_have_count(
            0
        )
    finally:
        for route in pending:
            route.abort()
        context.close()


@pytest.mark.parametrize("stale_status", [200, 503])
def test_model_discovery_preserves_new_provider_and_its_pending_request(
    browser: Browser,
    workspace_servers: tuple[str, str],
    stale_status: int,
) -> None:
    url, _ = workspace_servers
    context = authenticated_context(browser, locale="zh-CN")
    page = context.new_page()
    pending: dict[str, Route] = {}
    providers = [
        {
            "id": provider,
            "label": label,
            "kind": "cloud",
            "apiFamily": "openai_compatible_chat",
            "iconProvider": provider,
            "defaultBaseUrl": "http://127.0.0.1:9/v1",
            "officialUrl": "",
            "authRequired": False,
            "supportsModelDiscovery": True,
            "supportsCustomCapabilities": False,
            "supportsTools": True,
            "supportsStreaming": True,
        }
        for provider, label in (("openai", "Alpha"), ("deepseek", "Beta"))
    ]

    def discovery_data(name: str) -> dict[str, object]:
        return {
            "code": 0,
            "message": "OK",
            "data": {
                "source": "cache",
                "models": [
                    {
                        "id": name,
                        "label": name,
                        "contextWindowTokens": 32000,
                        "maxOutputTokens": 1024,
                        "supportsImage": False,
                        "supportsThinking": False,
                        "availableThinkingModes": ["auto"],
                        "supportsTools": True,
                        "supportsStreaming": True,
                        "metadataSource": "provider",
                    }
                ],
            },
        }

    def discover(route: Route) -> None:
        data = route.request.post_data_json
        if data.get("refresh"):
            pending[data["provider"]] = route
        else:
            route.fulfill(json=discovery_data(data["provider"] + " cached"))

    try:
        page.route(
            "**/api/model-providers",
            lambda route: route.fulfill(
                json={
                    "code": 0,
                    "message": "OK",
                    "data": {"providers": providers},
                }
            ),
        )
        page.route("**/api/model-providers/discover-models", discover)
        page.goto(f"{url}/models", wait_until="networkidle")
        page.get_by_role("button", name="新建模型", exact=True).click()
        expect(page.locator("#model-select")).to_have_text("openai cached")
        with page.expect_request(
            lambda request: bool(request.post_data_json.get("refresh"))
        ):
            page.locator("#model-discovery").click()
        page.locator("#model-provider").click()
        page.get_by_role("option", name="Beta", exact=False).click()
        expect(page.locator("#model-select")).to_have_text("deepseek cached")
        with page.expect_request(
            lambda request: bool(request.post_data_json.get("refresh"))
        ):
            page.locator("#model-discovery").click()
        stale = pending.pop("openai")
        stale.fulfill(status=stale_status, json=discovery_data("stale model"))
        expect(page.locator("#model-select")).to_have_text("deepseek cached")
        expect(page.locator("#model-discovery")).to_be_disabled()
        pending.pop("deepseek").fulfill(json=discovery_data("current model"))
        expect(page.locator("#model-select")).to_have_text("current model")
        expect(page.locator("#model-discovery")).to_be_enabled()
    finally:
        for route in pending.values():
            route.abort()
        context.close()
