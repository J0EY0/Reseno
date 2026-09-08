"""Manual model settings retain their values and validation across folding."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import Browser, Locator, Page, expect

from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _open_manual_model(page: Page, url: str, provider: str) -> Locator:
    page.route(
        "**/api/model-providers/discover-models",
        lambda route: route.fulfill(
            json={"code": 0, "message": "OK", "data": {"models": [], "source": "cache"}}
        ),
    )
    page.goto(f"{url}/models", wait_until="networkidle")
    page.locator('[data-slot="dialog-trigger"]').first.click()
    page.locator("#model-provider").click()
    page.get_by_role("option").filter(has_text=provider).click()
    dialog = page.locator('[data-slot="dialog-content"]')
    expect(dialog.locator("#model-name")).to_be_visible()
    expect(dialog.locator("#model-output-settings")).to_have_attribute(
        "aria-expanded", "false"
    )
    expect(dialog.locator("#model-context-window")).to_be_hidden()
    return dialog


def _expect_inside_form(field: Locator) -> None:
    expect(field).to_be_visible()
    assert field.evaluate(
        """element => {
          const viewport = element.closest('form').querySelector(
            ':scope > [data-slot="field-group"]'
          ).getBoundingClientRect();
          const rect = element.getBoundingClientRect();
          return rect.top >= viewport.top - 1 && rect.bottom <= viewport.bottom + 1;
        }"""
    )


def _expand_and_record(page: Page, dialog: Locator, reduced_motion: str) -> None:
    page.evaluate(
        """() => {
          window.__advancedFrames = [];
          window.__recordAdvanced = true;
          const record = () => {
            const dialog = document.querySelector('[data-slot="dialog-content"]');
            const content = document.querySelector('#model-output-settings-content');
            const rect = dialog.getBoundingClientRect();
            window.__advancedFrames.push({
              top: rect.top, height: rect.height,
              opacity: Number(getComputedStyle(dialog).opacity),
              contentHeight: content?.getBoundingClientRect().height ?? 0,
              innerOpacity: content?.firstElementChild
                ? Number(getComputedStyle(content.firstElementChild).opacity) : null,
              overflow: dialog.scrollWidth - dialog.clientWidth,
            });
            if (window.__recordAdvanced) requestAnimationFrame(record);
          };
          requestAnimationFrame(record);
        }"""
    )
    dialog.locator("#model-output-settings").click()
    expect(dialog.locator("#model-context-window")).to_be_visible()
    page.wait_for_timeout(450)
    frames = page.evaluate(
        "() => { window.__recordAdvanced = false; return window.__advancedFrames; }"
    )
    assert len(frames) > 5
    assert max(frame["top"] for frame in frames) - min(
        frame["top"] for frame in frames
    ) < 1
    assert max(frame["height"] for frame in frames) - min(
        frame["height"] for frame in frames
    ) < 1
    assert min(frame["opacity"] for frame in frames) > 0.99
    assert max(frame["overflow"] for frame in frames) <= 1
    if reduced_motion == "reduce":
        assert dialog.locator(".model-output-settings-content-inner").evaluate(
            "element => getComputedStyle(element).animationName"
        ) == "none"
    else:
        heights = [
            frame["contentHeight"] for frame in frames if frame["contentHeight"] > 1
        ]
        assert len(heights) > 5
        assert max(heights) - min(heights) < 1
        opacities = {
            round(frame["innerOpacity"], 2)
            for frame in frames
            if frame["innerOpacity"] is not None and 0 < frame["innerOpacity"] < 1
        }
        assert len(opacities) > 3
    assert dialog.locator(".model-output-settings-content-inner").evaluate(
        """element => [
          getComputedStyle(element).opacity, getComputedStyle(element).transform
        ]"""
    ) == ["1", "none"]


@pytest.mark.parametrize(
    ("provider", "viewport", "reduced_motion"),
    [
        ("Ollama", {"width": 1280, "height": 700}, "no-preference"),
        ("Ollama", {"width": 390, "height": 620}, "reduce"),
        ("Custom", {"width": 390, "height": 620}, "reduce"),
    ],
    ids=["local-desktop-motion", "local-narrow-reduced", "custom-narrow-reduced"],
)
def test_manual_advanced_settings_preserve_values_and_reveal_errors(
    browser: Browser,
    workspace_servers: tuple[str, str],
    tmp_path: Path,
    provider: str,
    viewport: dict[str, int],
    reduced_motion: str,
) -> None:
    url, _ = workspace_servers
    context = authenticated_context(
        browser, locale="en-US", viewport=viewport, reduced_motion=reduced_motion
    )
    page = context.new_page()
    nickname = f"Fold-{uuid4().hex[:8]}"
    try:
        dialog = _open_manual_model(page, url, provider)
        dialog.locator("#model-name").fill("manual-model")
        dialog.locator("#model-nickname").fill(nickname)
        dialog.locator("#model-api-key").fill("test-advanced-settings")
        dialog.locator("#model-api-url").fill("http://127.0.0.1:9/v1")
        dialog.locator("#model-supports-thinking").check()
        page.wait_for_timeout(250)
        page.screenshot(path=str(tmp_path / "collapsed.png"))
        _expand_and_record(page, dialog, reduced_motion)
        if provider == "Custom":
            expect(dialog.locator("#model-temperature")).to_have_count(0)
            expect(dialog.locator("#model-top-p")).to_have_count(0)
        context_input = dialog.locator("#model-context-window")
        max_input = dialog.locator("#model-max-tokens")
        toggle = dialog.locator("#model-output-settings")
        submit = dialog.locator('button[type="submit"]')
        expect(context_input).to_have_value("32768")
        expect(max_input).to_have_value("")
        expect(dialog.locator("#model-thinking-mode")).to_be_visible()
        context_input.fill("64000")
        max_input.fill("4096")
        toggle.click()
        expect(context_input).to_be_hidden()
        toggle.click()
        expect(context_input).to_have_value("64000")
        expect(max_input).to_have_value("4096")
        page.wait_for_timeout(400)
        page.screenshot(path=str(tmp_path / "expanded.png"))

        context_input.fill("0")
        max_input.fill("0")
        toggle.click()
        submit.click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(context_input).to_have_attribute("aria-invalid", "true")
        expect(context_input).to_be_focused()
        page.wait_for_timeout(450)
        _expect_inside_form(dialog.locator("#model-context-window-error"))
        page.screenshot(path=str(tmp_path / "context-error.png"))
        context_input.fill("64000")
        expect(context_input).to_be_focused()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(max_input).to_have_attribute("aria-invalid", "true")
        max_input.fill("4096")
        expect(toggle).to_have_attribute("aria-expanded", "true")

        max_input.fill("0")
        toggle.click()
        submit.click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(max_input).to_be_focused()
        page.wait_for_timeout(450)
        _expect_inside_form(dialog.locator("#model-max-tokens-error"))
        page.screenshot(path=str(tmp_path / "max-error.png"))
        max_input.fill("4096")
        expect(toggle).to_have_attribute("aria-expanded", "true")
        toggle.click()
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/api/model-configs")
        ) as saved:
            submit.click()
        assert saved.value.ok, saved.value.text()
        expect(dialog).to_be_hidden()
        records = page.request.get(f"{url}/api/workspace/pages/models").json()["data"][
            "modelConfigs"
        ]
        record = next(item for item in records if item["nickname"] == nickname)
        assert record["contextWindowTokens"] == 64000
        assert record["maxTokens"] == 4096
        assert record["supportsThinking"] is True
        row = page.get_by_role("row").filter(has_text=nickname)
        row.get_by_role("button", name="Actions", exact=True).click()
        page.get_by_role("menuitem", name="Edit", exact=True).click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(context_input).to_have_value("64000")
        expect(max_input).to_have_value("4096")
        print(f"Advanced settings browser artifacts: {tmp_path}")
    finally:
        context.close()


def test_other_local_providers_start_with_advanced_settings_collapsed(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    url, _ = workspace_servers
    context = authenticated_context(browser, locale="en-US")
    page = context.new_page()
    try:
        dialog = _open_manual_model(page, url, "vLLM")
        for provider in ("vLLM", "SGLang"):
            if provider == "SGLang":
                dialog.locator("#model-provider").click()
                page.get_by_role("option").filter(has_text=provider).click()
            toggle = dialog.locator("#model-output-settings")
            expect(toggle).to_have_attribute("aria-expanded", "false")
            toggle.focus()
            toggle.press("Space")
            expect(dialog.locator("#model-context-window")).to_have_value("32768")
            expect(dialog.locator("#model-max-tokens")).to_have_value("")
            expect(dialog.locator("#model-temperature")).to_have_value("")
            expect(dialog.locator("#model-top-p")).to_have_value("")
            toggle.press("Enter")
            expect(dialog.locator("#model-context-window")).to_be_hidden()
    finally:
        context.close()


@pytest.mark.parametrize(
    ("provider", "viewport", "reduced_motion"),
    [
        ("Ollama", {"width": 1280, "height": 700}, "no-preference"),
        ("Custom", {"width": 390, "height": 620}, "reduce"),
    ],
    ids=["local-desktop", "custom-narrow"],
)
def test_catalog_context_lookup_preserves_settings_and_saves(
    browser: Browser,
    workspace_servers: tuple[str, str],
    tmp_path: Path,
    provider: str,
    viewport: dict[str, int],
    reduced_motion: str,
) -> None:
    url, _ = workspace_servers
    locale = "zh-CN" if provider == "Custom" else "en-US"
    context = authenticated_context(
        browser, locale=locale, viewport=viewport, reduced_motion=reduced_motion
    )
    page = context.new_page()
    nickname = f"Catalog-{uuid4().hex[:8]}"
    try:
        dialog = _open_manual_model(
            page, url, "自定义" if locale == "zh-CN" else provider
        )
        dialog.locator("#model-output-settings").click()
        button = dialog.get_by_role(
            "button",
            name="自动获取" if locale == "zh-CN" else "Autofill",
            exact=True,
        )
        expect(button).to_be_disabled()
        model = dialog.locator("#model-name")
        model.fill("Qwen/Qwen3-32B")
        dialog.locator("#model-nickname").fill(nickname)
        dialog.locator("#model-api-key").fill("test-catalog-context")
        dialog.locator("#model-api-url").fill("http://127.0.0.1:9/v1")
        dialog.locator("#model-supports-thinking").check()
        context_input = dialog.locator("#model-context-window")
        max_input = dialog.locator("#model-max-tokens")
        context_input.fill("64000")
        max_input.fill("4096")
        button.focus()
        with page.expect_response("**/api/model-providers/context-window") as lookup:
            button.press("Enter")
        assert lookup.value.ok, lookup.value.text()
        result = lookup.value.json()["data"]
        assert result["status"] == "found"
        assert result["contextWindowTokens"] == 131072
        expected_context = str(result["contextWindowTokens"])
        expect(context_input).to_have_value(expected_context)
        expect(dialog.locator("#model-supports-image")).not_to_be_checked()
        expect(dialog.locator("#model-supports-thinking")).to_be_checked()
        expect(dialog.locator("#model-supports-tools")).to_be_checked()
        expect(dialog.locator("#model-thinking-mode")).to_be_checked()
        expect(max_input).to_have_value("4096")
        row = context_input.locator('xpath=ancestor::*[@data-slot="field"][1]')
        assert row.evaluate("element => element.scrollWidth <= element.clientWidth + 1")
        dialog.locator('form > [data-slot="field-group"]').evaluate(
            "element => element.scrollTop = element.scrollHeight"
        )
        page.wait_for_timeout(250)
        page.screenshot(path=str(tmp_path / "catalog-context.png"))

        for status in ("not_found", "ambiguous", "failure"):
            def respond(route, _request, status=status):
                route.fulfill(
                    status=503 if status == "failure" else 200,
                    json={
                        "code": 503 if status == "failure" else 0,
                        "message": "Unavailable" if status == "failure" else "OK",
                        "data": {
                            "status": status,
                            "contextWindowTokens": None,
                            "matchedModel": None,
                            "source": None,
                        },
                    },
                )

            page.route("**/api/model-providers/context-window", respond)
            with page.expect_response("**/api/model-providers/context-window"):
                button.click()
            expect(button).to_be_enabled()
            page.wait_for_timeout(100)
            expect(context_input).to_have_value(expected_context)
            expect(max_input).to_have_value("4096")
            expect(dialog.locator("#model-context-catalog-status")).to_be_visible()
            page.unroute("**/api/model-providers/context-window", respond)

        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/api/model-configs")
        ) as saved:
            dialog.locator('button[type="submit"]').click()
        assert saved.value.ok, saved.value.text()
        records = page.request.get(f"{url}/api/workspace/pages/models").json()["data"][
            "modelConfigs"
        ]
        record = next(item for item in records if item["nickname"] == nickname)
        assert record["contextWindowTokens"] == int(expected_context)
        assert record["model"] == "Qwen/Qwen3-32B"
        assert record["maxTokens"] == 4096
        assert record["supportsImage"] is False
        assert record["supportsThinking"] is True
        assert record["supportsTools"] is True
        print(f"Catalog context browser artifact: {tmp_path / 'catalog-context.png'}")
    finally:
        context.close()


def test_catalog_context_lookup_ignores_changed_form_during_request(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    url, _ = workspace_servers
    context = authenticated_context(browser, locale="en-US")
    page = context.new_page()
    pending = []
    try:
        dialog = _open_manual_model(page, url, "Custom")
        dialog.locator("#model-output-settings").click()
        model = dialog.locator("#model-name")
        context_input = dialog.locator("#model-context-window")
        model.fill("first-model")
        context_input.fill("64000")
        page.route(
            "**/api/model-providers/context-window", lambda route: pending.append(route)
        )
        for changed_field in ("model", "context", "provider"):
            button = dialog.get_by_role("button", name="Autofill", exact=True)
            with page.expect_request("**/api/model-providers/context-window"):
                button.click()
            assert pending
            expect(button).to_be_disabled()
            if changed_field == "model":
                model.fill("second-model")
            elif changed_field == "context":
                context_input.fill("48000")
            else:
                dialog.locator("#model-provider").click()
                page.get_by_role("option").filter(has_text="Ollama").click()
                if dialog.locator("#model-output-settings").get_attribute(
                    "aria-expanded"
                ) == "false":
                    dialog.locator("#model-output-settings").click()
            expected_context = context_input.input_value()
            pending.pop().fulfill(
                json={
                    "code": 0,
                    "message": "OK",
                    "data": {
                        "status": "found",
                        "contextWindowTokens": 999999,
                        "matchedModel": "first-model",
                        "source": "litellm",
                    },
                }
            )
            page.wait_for_timeout(200)
            expect(context_input).to_have_value(expected_context)
            if changed_field == "model":
                expect(model).to_have_value("second-model")
    finally:
        for route in pending:
            route.abort()
        context.close()


@pytest.mark.parametrize(
    ("provider", "viewport", "reduced_motion", "locale"),
    [
        ("Ollama", {"width": 1280, "height": 700}, "no-preference", "en-US"),
        ("SGLang", {"width": 390, "height": 620}, "reduce", "zh-CN"),
    ],
    ids=["ollama-desktop", "sglang-narrow"],
)
def test_local_sampling_settings_save_zero_clear_and_reveal_errors(
    browser: Browser,
    workspace_servers: tuple[str, str],
    tmp_path: Path,
    provider: str,
    viewport: dict[str, int],
    reduced_motion: str,
    locale: str,
) -> None:
    url, _ = workspace_servers
    context = authenticated_context(
        browser, locale=locale, viewport=viewport, reduced_motion=reduced_motion
    )
    page = context.new_page()
    nickname = f"Sampling-{uuid4().hex[:8]}"
    inference_requests = []
    page.on(
        "request",
        lambda request: inference_requests.append(request.url)
        if "/chat/completions" in request.url or request.url.endswith("/responses")
        else None,
    )
    try:
        dialog = _open_manual_model(page, url, provider)
        dialog.locator("#model-name").fill("local-sampling-model")
        dialog.locator("#model-nickname").fill(nickname)
        dialog.locator("#model-api-url").fill("http://127.0.0.1:9/v1")
        _expand_and_record(page, dialog, reduced_motion)
        temperature = dialog.locator("#model-temperature")
        top_p = dialog.locator("#model-top-p")
        toggle = dialog.locator("#model-output-settings")
        submit = dialog.locator('button[type="submit"]')
        for field in (temperature, top_p):
            expect(field).to_have_value("")
            assert field.get_attribute("placeholder") is None
        temperature.fill("0")
        top_p.fill("0.75")
        toggle.click()
        expect(temperature).to_be_hidden()
        toggle.click()
        expect(temperature).to_have_value("0")
        expect(top_p).to_have_value("0.75")
        page.wait_for_timeout(350)
        dialog.locator('form > [data-slot="field-group"]').evaluate(
            "element => element.scrollTop = element.scrollHeight"
        )
        assert dialog.evaluate(
            "element => element.scrollWidth <= element.clientWidth + 1"
        )
        page.screenshot(path=str(tmp_path / "sampling-expanded.png"))

        temperature.fill("-1")
        top_p.fill("2")
        toggle.click()
        submit.click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(temperature).to_have_attribute("aria-invalid", "true")
        expect(temperature).to_be_focused()
        page.wait_for_timeout(450)
        _expect_inside_form(dialog.locator("#model-temperature-error"))
        temperature.fill("0")
        expect(temperature).to_be_focused()
        expect(top_p).to_have_attribute("aria-invalid", "true")
        top_p.fill("0.75")
        expect(toggle).to_have_attribute("aria-expanded", "true")
        top_p.fill("2")
        toggle.click()
        submit.click()
        expect(top_p).to_be_focused()
        page.wait_for_timeout(450)
        _expect_inside_form(dialog.locator("#model-top-p-error"))
        page.screenshot(path=str(tmp_path / "sampling-error.png"))
        top_p.fill("0.75")
        toggle.click()
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/api/model-configs")
        ) as saved:
            submit.click()
        assert saved.value.ok, saved.value.text()
        expect(dialog).to_be_hidden()
        records = page.request.get(f"{url}/api/workspace/pages/models").json()["data"][
            "modelConfigs"
        ]
        record = next(item for item in records if item["nickname"] == nickname)
        assert record["temperature"] == 0
        assert record["topP"] == 0.75
        row = page.get_by_role("row").filter(has_text=nickname)
        row.get_by_role(
            "button", name="操作" if locale == "zh-CN" else "Actions", exact=True
        ).click()
        page.get_by_role(
            "menuitem", name="修改" if locale == "zh-CN" else "Edit", exact=True
        ).click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(temperature).to_have_value("0")
        expect(top_p).to_have_value("0.75")
        temperature.fill("1.234")
        top_p.fill("0.8765")
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/api/model-configs")
            and response.request.post_data_json.get("id") == record["id"]
        ) as precision_saved:
            submit.click()
        assert precision_saved.value.ok, precision_saved.value.text()
        expect(dialog).to_be_hidden()
        page.reload(wait_until="networkidle")
        row.get_by_role(
            "button", name="操作" if locale == "zh-CN" else "Actions", exact=True
        ).click()
        page.get_by_role(
            "menuitem", name="修改" if locale == "zh-CN" else "Edit", exact=True
        ).click()
        expect(temperature).to_have_value("1.234")
        expect(top_p).to_have_value("0.8765")
        temperature.fill("")
        top_p.fill("")
        expect(toggle).to_have_attribute("aria-expanded", "true")
        with page.expect_response(
            lambda response: response.request.method == "POST"
            and response.url.endswith("/api/model-configs")
            and response.request.post_data_json.get("id") == record["id"]
        ) as cleared:
            submit.click()
        assert cleared.value.ok, cleared.value.text()
        expect(dialog).to_be_hidden()
        records = page.request.get(f"{url}/api/workspace/pages/models").json()["data"][
            "modelConfigs"
        ]
        record = next(item for item in records if item["nickname"] == nickname)
        assert record["temperature"] is None
        assert record["topP"] is None
        assert inference_requests == []
        print(f"Local sampling browser artifacts: {tmp_path}")
    finally:
        context.close()
