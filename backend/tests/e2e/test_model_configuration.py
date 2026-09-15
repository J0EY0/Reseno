from __future__ import annotations

import json
import os

import pytest
from playwright.sync_api import Browser, Route, expect
from playwright.sync_api import Error as PlaywrightError

from tests.e2e.browser_support import RouteReady
from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_model_discovery_ignores_stale_provider_refresh(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="en-US",
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()
    held_refresh_routes: list[Route] = []
    refresh_ready = RouteReady()

    def discovery_body(model_id: str, source: str) -> str:
        return json.dumps(
            {
                "code": 0,
                "message": "OK",
                "data": {
                    "models": [
                        {
                            "id": model_id,
                            "label": model_id,
                            "contextWindowTokens": 128000,
                            "maxOutputTokens": 32768,
                            "supportsImage": False,
                            "supportsThinking": False,
                            "supportsTools": True,
                            "supportsStreaming": True,
                            "metadataSource": "test",
                        }
                    ],
                    "source": source,
                },
            }
        )

    def handle_model_discovery(route: Route) -> None:
        payload = route.request.post_data_json
        assert isinstance(payload, dict)
        provider = str(payload["provider"])

        if provider == "openai" and payload.get("refresh") is True:
            held_refresh_routes.append(route)
            refresh_ready.set()
            return

        route.fulfill(
            status=200,
            content_type="application/json",
            body=discovery_body(f"{provider}-latest-model", "cache"),
        )

    page.route(
        "**/api/model-providers/discover-models",
        handle_model_discovery,
    )

    try:
        page.goto(f"{frontend_url}/models", wait_until="networkidle")
        page.locator('[data-slot="dialog-trigger"]').first.click()

        model_trigger = page.locator("#model-select")
        expect(model_trigger).to_contain_text("openai-latest-model")
        page.locator("#model-api-key").fill("sk-race-test")

        refresh_button = page.locator("#model-discovery")
        refresh_button.click()
        expect(refresh_button).to_be_disabled()
        refresh_ready.wait(page)
        assert len(held_refresh_routes) == 1

        provider_trigger = page.locator("#model-provider")
        provider_trigger.click()
        page.get_by_role("option").filter(has_text="Anthropic").click()

        expect(provider_trigger).to_contain_text("Anthropic")
        expect(model_trigger).to_contain_text("anthropic-latest-model")

        held_refresh_routes.pop().fulfill(
            status=200,
            content_type="application/json",
            body=discovery_body("openai-stale-model", "provider"),
        )
        page.wait_for_timeout(200)

        expect(provider_trigger).to_contain_text("Anthropic")
        expect(model_trigger).to_contain_text("anthropic-latest-model")
        expect(model_trigger).not_to_contain_text("openai-stale-model")
    finally:
        for route in held_refresh_routes:
            try:
                route.abort()
            except PlaywrightError:
                pass
        context.close()


def test_model_thinking_mode_tracks_discovered_capability_and_model_switches(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="en-US",
        viewport={"width": 1280, "height": 620},
    )
    page = context.new_page()

    def fulfill_model_discovery(route: Route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "code": 0,
                    "message": "OK",
                    "data": {
                        "models": [
                            {
                                "id": "gpt-thinking-off",
                                "label": "GPT Thinking Off",
                                "contextWindowTokens": 128000,
                                "maxOutputTokens": 32768,
                                "supportsImage": True,
                                "supportsThinking": True,
                                "availableThinkingModes": ["auto", "off"],
                                "supportsTools": True,
                                "supportsStreaming": True,
                                "metadataSource": "test",
                            },
                            {
                                "id": "gpt-thinking-managed",
                                "label": "GPT Thinking Managed",
                                "contextWindowTokens": 128000,
                                "maxOutputTokens": 32768,
                                "supportsImage": True,
                                "supportsThinking": True,
                                "availableThinkingModes": ["auto"],
                                "supportsTools": True,
                                "supportsStreaming": True,
                                "metadataSource": "test",
                            },
                        ],
                        "source": "cache",
                    },
                }
            ),
        )

    page.route("**/api/model-providers/discover-models", fulfill_model_discovery)

    try:
        page.goto(f"{frontend_url}/models", wait_until="networkidle")
        page.locator('[data-slot="dialog-trigger"]').first.click()

        dialog = page.locator('[data-slot="dialog-content"]')
        model_trigger = page.locator("#model-select")
        model_trigger.click()
        page.get_by_role("option").filter(has_text="GPT Thinking Off").click()

        advanced_trigger = page.locator("#model-output-settings")
        advanced_trigger.click()
        expect(advanced_trigger).to_have_attribute("aria-expanded", "true")
        thinking_mode = page.get_by_role("switch", name="Thinking mode")
        expect(thinking_mode).to_have_attribute("data-checked", "")
        expect(thinking_mode).to_be_enabled()
        thinking_mode.click()
        expect(thinking_mode).to_have_attribute("data-unchecked", "")

        dialog_before_switch = dialog.bounding_box()
        assert dialog_before_switch is not None
        model_trigger.click()
        page.get_by_role("option").filter(has_text="GPT Thinking Managed").click()

        expect(thinking_mode).to_have_attribute("data-checked", "")
        expect(thinking_mode).to_be_disabled()

        model_trigger.click()
        page.get_by_role("option").filter(has_text="GPT Thinking Off").click()
        expect(thinking_mode).to_have_attribute("data-checked", "")
        expect(thinking_mode).to_be_enabled()

        dialog_after_switch = dialog.bounding_box()
        assert dialog_after_switch is not None
        for key in ("x", "y", "width", "height"):
            assert abs(dialog_after_switch[key] - dialog_before_switch[key]) <= 1, (
                dialog_before_switch,
                dialog_after_switch,
            )
    finally:
        context.close()


@pytest.mark.parametrize(
    "viewport",
    [
        {"width": 1280, "height": 520},
        {"width": 390, "height": 520},
    ],
    ids=["desktop-short", "mobile-short"],
)
def test_model_config_advanced_settings_keep_dialog_frame_stable_and_visible(
    browser: Browser,
    workspace_servers: tuple[str, str],
    viewport: dict[str, int],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport=viewport,
    )
    page = context.new_page()

    def fulfill_model_discovery(route: Route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "code": 0,
                    "message": "OK",
                    "data": {
                        "models": [
                            {
                                "id": "gpt-ui-motion",
                                "label": "GPT UI Motion",
                                "contextWindowTokens": 128000,
                                "maxOutputTokens": 32768,
                                "supportsImage": True,
                                "supportsThinking": True,
                                "availableThinkingModes": ["auto", "off"],
                                "supportsTools": True,
                                "supportsStreaming": True,
                                "metadataSource": "test",
                            }
                        ],
                        "source": "cache",
                    },
                }
            ),
        )

    page.route("**/api/model-providers/discover-models", fulfill_model_discovery)

    try:
        page.goto(f"{frontend_url}/models", wait_until="networkidle")
        page.locator('[data-slot="dialog-trigger"]').first.click()

        dialog = page.locator('[data-slot="dialog-content"]')
        advanced_trigger = page.locator("#model-output-settings")
        scroll_viewport = dialog.locator('form > [data-slot="field-group"]')
        advanced_trigger.wait_for(state="visible")
        expect(advanced_trigger).to_have_attribute("aria-expanded", "false")
        page.wait_for_timeout(240)

        dialog_before = dialog.bounding_box()
        scroll_before = scroll_viewport.evaluate("element => element.scrollTop")
        assert dialog_before is not None
        page.evaluate(
            """
            () => {
              const originalScrollIntoView = Element.prototype.scrollIntoView;
              const originalScrollTo = HTMLElement.prototype.scrollTo;
              window.__modelOutputRevealBehaviors = [];
              window.__modelOutputRevealFrames = [];
              Element.prototype.scrollIntoView = function (options) {
                if (this.id === 'model-max-tokens') {
                  window.__modelOutputRevealBehaviors.push({
                    behavior: options?.behavior,
                    method: 'scrollIntoView',
                  });
                }
                return originalScrollIntoView.call(this, options);
              };
              HTMLElement.prototype.scrollTo = function (options, y) {
                if (this.matches(
                  '[data-slot="dialog-content"] form > [data-slot="field-group"]',
                )) {
                  window.__modelOutputRevealBehaviors.push({
                    behavior: typeof options === 'object'
                      ? options.behavior
                      : undefined,
                    method: 'scrollTo',
                  });
                }
                return arguments.length === 1
                  ? originalScrollTo.call(this, options)
                  : originalScrollTo.call(this, options, y);
              };

              const startedAt = performance.now();
              const sample = timestamp => {
                const content = document.querySelector(
                  '#model-output-settings-content',
                );
                if (content instanceof HTMLElement) {
                  const rect = content.getBoundingClientRect();
                  window.__modelOutputRevealFrames.push({
                    elapsed: timestamp - startedAt,
                    height: rect.height,
                  });
                }
                if (timestamp - startedAt < 340) {
                  requestAnimationFrame(sample);
                  return;
                }
                window.__modelOutputRevealFramesDone = true;
              };
              requestAnimationFrame(sample);
            }
            """
        )

        advanced_trigger.click()
        expect(advanced_trigger).to_have_attribute("aria-expanded", "true")
        advanced_content = page.locator("#model-output-settings-content")
        advanced_content.wait_for(state="visible")
        page.wait_for_function("() => window.__modelOutputRevealFramesDone === true")
        reveal_frames = page.evaluate("window.__modelOutputRevealFrames")
        rendered_heights = [
            frame["height"] for frame in reveal_frames if frame["height"] > 1
        ]
        assert len(rendered_heights) >= 5, reveal_frames
        assert max(rendered_heights) - min(rendered_heights) <= 1, {
            "message": "Advanced field was progressively clipped during reveal.",
            "frames": reveal_frames,
        }
        page.wait_for_function(
            """
            () => {
              const viewport = document.querySelector(
                '[data-slot="dialog-content"] form > [data-slot="field-group"]',
              );
              const input = document.querySelector('#model-max-tokens');
              if (!(viewport instanceof HTMLElement) ||
                  !(input instanceof HTMLElement)) {
                return false;
              }
              const viewportRect = viewport.getBoundingClientRect();
              const inputRect = input.getBoundingClientRect();
              return inputRect.top >= viewportRect.top - 1 &&
                inputRect.bottom <= viewportRect.bottom + 1;
            }
            """,
        )

        dialog_after = dialog.bounding_box()
        scroll_box = scroll_viewport.bounding_box()
        max_tokens_field_box = page.locator(
            '[data-slot="field"]:has(#model-max-tokens)'
        ).bounding_box()
        max_tokens_label_box = page.locator(
            'label[for="model-max-tokens"]'
        ).bounding_box()
        dialog_title_box = dialog.locator('[data-slot="dialog-title"]').bounding_box()
        top_close_button = dialog.locator(':scope > button[data-slot="dialog-close"]')
        top_close_button_box = top_close_button.bounding_box()
        top_close_icon_box = top_close_button.locator("svg").bounding_box()
        cancel_button_box = dialog.locator(
            '[data-slot="dialog-footer"] button[type="button"]'
        ).bounding_box()
        submit_button_box = dialog.locator(
            '[data-slot="dialog-footer"] button[type="submit"]'
        ).bounding_box()
        max_tokens_input = page.locator("#model-max-tokens")
        input_box = max_tokens_input.bounding_box()
        advanced_content_box = advanced_content.bounding_box()
        expect(max_tokens_input).to_have_attribute("placeholder", "自动")
        max_tokens_input.focus()
        expect(max_tokens_input).to_be_focused()
        focused_input_rendering = advanced_content.evaluate(
            """
            (content) => {
              const input = content.querySelector('#model-max-tokens');
              const contentStyle = getComputedStyle(content);
              const inputStyle = input instanceof HTMLElement
                ? getComputedStyle(input)
                : null;
              return {
                overflowX: contentStyle.overflowX,
                overflowY: contentStyle.overflowY,
                inputBoxShadow: inputStyle?.boxShadow ?? 'none',
              };
            }
            """
        )
        scroll_after = scroll_viewport.evaluate("element => element.scrollTop")
        assert dialog_after is not None
        assert scroll_box is not None
        assert max_tokens_field_box is not None
        assert max_tokens_label_box is not None
        assert dialog_title_box is not None
        assert top_close_button_box is not None
        assert top_close_icon_box is not None
        assert cancel_button_box is not None
        assert submit_button_box is not None
        assert input_box is not None
        assert advanced_content_box is not None
        for key in ("x", "y", "width", "height"):
            assert abs(dialog_after[key] - dialog_before[key]) <= 1, (
                dialog_before,
                dialog_after,
            )
        assert scroll_after > scroll_before
        assert input_box["y"] >= scroll_box["y"] - 1
        assert input_box["y"] + input_box["height"] <= (
            scroll_box["y"] + scroll_box["height"] + 1
        )
        assert (
            abs(
                input_box["x"]
                + input_box["width"]
                - max_tokens_field_box["x"]
                - max_tokens_field_box["width"]
            )
            <= 1
        )
        assert abs(input_box["width"] - 128) <= 1
        assert (
            abs(
                input_box["y"]
                + input_box["height"] / 2
                - max_tokens_label_box["y"]
                - max_tokens_label_box["height"] / 2
            )
            <= 1
        )
        assert (
            max_tokens_label_box["x"] + max_tokens_label_box["width"] + 11
            <= (input_box["x"])
        )
        assert (
            abs(
                input_box["x"]
                + input_box["width"]
                - advanced_content_box["x"]
                - advanced_content_box["width"]
            )
            <= 1
        )
        assert focused_input_rendering["inputBoxShadow"] != "none"
        assert focused_input_rendering["overflowX"] == "visible", (
            focused_input_rendering
        )
        assert focused_input_rendering["overflowY"] == "visible", (
            focused_input_rendering
        )
        assert top_close_button_box["width"] >= 32
        assert top_close_button_box["height"] >= 32
        assert (
            abs(
                top_close_button_box["x"]
                + top_close_button_box["width"] / 2
                - top_close_icon_box["x"]
                - top_close_icon_box["width"] / 2
            )
            <= 1
        )
        assert (
            abs(
                top_close_button_box["y"]
                + top_close_button_box["height"] / 2
                - top_close_icon_box["y"]
                - top_close_icon_box["height"] / 2
            )
            <= 1
        )
        assert (
            abs(
                dialog_title_box["y"]
                + dialog_title_box["height"] / 2
                - top_close_button_box["y"]
                - top_close_button_box["height"] / 2
            )
            <= 1
        )
        title_left_inset = dialog_title_box["x"] - dialog_after["x"]
        close_icon_right_inset = (
            dialog_after["x"]
            + dialog_after["width"]
            - top_close_icon_box["x"]
            - top_close_icon_box["width"]
        )
        assert abs(title_left_inset - close_icon_right_inset) <= 1
        minimum_fixed_region_gap = 16
        assert (
            dialog_title_box["y"]
            + dialog_title_box["height"]
            + minimum_fixed_region_gap
            <= scroll_box["y"] + 1
        ), {
            "message": "Scrollable fields reached into the dialog title region.",
            "title": dialog_title_box,
            "scroll": scroll_box,
        }
        scroll_bottom = scroll_box["y"] + scroll_box["height"]
        for name, button_box in (
            ("cancel", cancel_button_box),
            ("submit", submit_button_box),
        ):
            assert scroll_bottom + minimum_fixed_region_gap <= button_box["y"] + 1, {
                "message": "Scrollable fields reached into the dialog action region.",
                "scroll": scroll_box,
                name: button_box,
            }
        dialog_inner_bottom = dialog.evaluate(
            """
            element => {
              const rect = element.getBoundingClientRect();
              return rect.top + element.clientTop + element.clientHeight;
            }
            """
        )
        actions_bottom = max(
            button_box["y"] + button_box["height"]
            for button_box in (cancel_button_box, submit_button_box)
        )
        assert abs(dialog_inner_bottom - actions_bottom - 16) <= 1
        assert page.evaluate("window.__modelOutputRevealBehaviors") == [
            {"behavior": "smooth", "method": "scrollTo"}
        ]

        page.evaluate(
            """
            () => {
              window.__modelOutputCollapseFrames = [];
              const startedAt = performance.now();
              const sample = timestamp => {
                const dialog = document.querySelector(
                  '[data-slot="dialog-content"]',
                );
                const content = document.querySelector(
                  '#model-output-settings-content',
                );
                const inner = content?.querySelector(
                  '.model-output-settings-content-inner',
                );
                const viewport = document.querySelector(
                  '[data-slot="dialog-content"] form > [data-slot="field-group"]',
                );
                const dialogRect = dialog instanceof HTMLElement
                  ? dialog.getBoundingClientRect()
                  : null;
                const dialogStyle = dialog instanceof HTMLElement
                  ? getComputedStyle(dialog)
                  : null;
                const contentStyle = content instanceof HTMLElement
                  ? getComputedStyle(content)
                  : null;
                const innerStyle = inner instanceof HTMLElement
                  ? getComputedStyle(inner)
                  : null;
                const centerOwner = dialogRect
                  ? document.elementFromPoint(
                      dialogRect.left + dialogRect.width / 2,
                      dialogRect.top + dialogRect.height / 2,
                    )
                  : null;
                window.__modelOutputCollapseFrames.push({
                  elapsed: timestamp - startedAt,
                  height: content instanceof HTMLElement
                    ? content.getBoundingClientRect().height
                    : 0,
                  dialogVisible: dialog instanceof HTMLElement &&
                    dialog.isConnected &&
                    dialogStyle?.display !== 'none' &&
                    dialogStyle?.visibility !== 'hidden' &&
                    Number(dialogStyle?.opacity ?? 0) > 0.99 &&
                    Boolean(dialogRect?.width) &&
                    Boolean(dialogRect?.height) &&
                    dialog.contains(centerOwner),
                  dialogOpacity: Number(dialogStyle?.opacity ?? 0),
                  dialogRect: dialogRect ? {
                    x: dialogRect.x,
                    y: dialogRect.y,
                    width: dialogRect.width,
                    height: dialogRect.height,
                  } : null,
                  contentOpacity: contentStyle
                    ? Number(contentStyle.opacity)
                    : null,
                  contentWillChange: contentStyle?.willChange ?? null,
                  innerWillChange: innerStyle?.willChange ?? null,
                  scrollTop: viewport instanceof HTMLElement
                    ? viewport.scrollTop
                    : null,
                });
                if (timestamp - startedAt < 520) {
                  requestAnimationFrame(sample);
                  return;
                }
                window.__modelOutputCollapseFramesDone = true;
              };
              requestAnimationFrame(sample);
            }
            """
        )
        advanced_trigger.click()
        expect(advanced_trigger).to_have_attribute("aria-expanded", "false")
        expect(advanced_content).to_have_attribute("data-state", "closed")
        assert (
            advanced_content.evaluate("element => getComputedStyle(element).overflow")
            == "clip"
        )
        assert (
            advanced_content.evaluate(
                "element => getComputedStyle(element).animationName"
            )
            == "model-output-settings-exit"
        )
        page.wait_for_function("() => window.__modelOutputCollapseFramesDone === true")
        collapse_frames = page.evaluate("window.__modelOutputCollapseFrames")
        assert collapse_frames
        assert all(frame["dialogVisible"] for frame in collapse_frames), {
            "message": (
                "The model dialog disappeared during advanced-settings collapse."
            ),
            "frames": collapse_frames,
        }
        assert all(frame["dialogOpacity"] > 0.99 for frame in collapse_frames), {
            "message": "The model dialog faded during an internal field transition.",
            "frames": collapse_frames,
        }
        for frame in collapse_frames:
            assert frame["dialogRect"] is not None, collapse_frames
            for key in ("x", "y", "width", "height"):
                assert abs(frame["dialogRect"][key] - dialog_before[key]) <= 1, {
                    "message": "The fixed model dialog moved during collapse.",
                    "frames": collapse_frames,
                }
        painted_content_frames = [
            frame for frame in collapse_frames if frame["height"] > 1
        ]
        assert painted_content_frames, collapse_frames
        assert all(
            frame["contentOpacity"] is not None
            and frame["contentOpacity"] > 0.99
            and frame["contentWillChange"] == "auto"
            and frame["innerWillChange"] == "auto"
            for frame in painted_content_frames
        ), {
            "message": (
                "Collapsing content created nested opacity/transform layers inside "
                "the fixed dialog."
            ),
            "frames": collapse_frames,
        }
        expanded_height = max(frame["height"] for frame in collapse_frames)
        intermediate_heights = [
            frame["height"]
            for frame in collapse_frames
            if 1 < frame["height"] < expanded_height - 1
        ]
        assert len(intermediate_heights) >= 4, {
            "message": "Advanced field height snapped closed instead of collapsing.",
            "frames": collapse_frames,
        }
        collapse_scroll_positions = {
            round(frame["scrollTop"], 1)
            for frame in collapse_frames
            if frame["scrollTop"] is not None
        }
        assert len(collapse_scroll_positions) >= 4, {
            "message": "The form viewport snapped after advanced content unmounted.",
            "frames": collapse_frames,
        }
        advanced_content.wait_for(state="hidden")
        dialog_collapsed = dialog.bounding_box()
        assert dialog_collapsed is not None
        for key in ("x", "y", "width", "height"):
            assert abs(dialog_collapsed[key] - dialog_before[key]) <= 1, (
                dialog_before,
                dialog_collapsed,
            )

        page.emulate_media(reduced_motion="reduce")
        scroll_viewport.evaluate("element => { element.scrollTop = 0; }")
        advanced_trigger.click()
        expect(advanced_trigger).to_have_attribute("aria-expanded", "true")
        advanced_content.wait_for(state="visible")
        assert (
            advanced_content.evaluate(
                "element => getComputedStyle(element).animationName"
            )
            == "none"
        )
        page.wait_for_function(
            """
            () => {
              const viewport = document.querySelector(
                '[data-slot="dialog-content"] form > [data-slot="field-group"]',
              );
              const input = document.querySelector('#model-max-tokens');
              if (!(viewport instanceof HTMLElement) ||
                  !(input instanceof HTMLElement)) {
                return false;
              }
              const viewportRect = viewport.getBoundingClientRect();
              const inputRect = input.getBoundingClientRect();
              return inputRect.top >= viewportRect.top - 1 &&
                inputRect.bottom <= viewportRect.bottom + 1;
            }
            """,
        )
        assert page.evaluate("window.__modelOutputRevealBehaviors.at(-1)") == {
            "behavior": "auto",
            "method": "scrollTo",
        }
    finally:
        context.close()
