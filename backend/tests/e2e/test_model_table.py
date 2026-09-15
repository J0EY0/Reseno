from __future__ import annotations

import json
import os
from typing import Any

import pytest
from playwright.sync_api import Browser, Locator, Route, expect

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_models_route_uses_table_skeleton_and_preserves_dialog_exit(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1280, "height": 800})
    page = context.new_page()
    page.add_init_script(
        script="""
        (() => {
          const originalFetch = window.fetch.bind(window);
          let hasHeldInitialModelsRoute = false;
          window.__releaseModelsInitialRoute = null;
          window.fetch = async (input, init) => {
            const request = new Request(input, init);
            if (
              !hasHeldInitialModelsRoute &&
              new URL(request.url).pathname === "/api/workspace/pages/models"
            ) {
              hasHeldInitialModelsRoute = true;
              await new Promise((resolve) => {
                window.__releaseModelsInitialRoute = resolve;
              });
            }
            return originalFetch(input, init);
          };
        })();
        """,
    )

    try:
        page.goto(f"{frontend_url}/models", wait_until="domcontentloaded")
        page.wait_for_function("window.__releaseModelsInitialRoute !== null")

        skeleton = page.locator('[data-slot="model-config-panel-skeleton"]')
        skeleton.wait_for(state="visible")
        assert skeleton.locator('[data-slot="table-header"]').count() == 1
        assert skeleton.locator('[data-slot="table-row"]').count() >= 3
        skeleton_content_height = skeleton.locator(
            '[data-slot="model-config-content-skeleton"]'
        ).evaluate("element => element.getBoundingClientRect().height")
        skeleton_table_height = skeleton.locator(
            '[data-slot="data-table-skeleton"]'
        ).evaluate("element => element.getBoundingClientRect().height")
        skeleton_surface_height = skeleton.locator(
            ':scope > [data-slot="card"]'
        ).evaluate("element => element.getBoundingClientRect().height")
        assert abs(skeleton_content_height - 390) <= 1
        assert skeleton_table_height < skeleton_content_height
        assert abs(skeleton_surface_height - 476) <= 1

        page.evaluate("window.__releaseModelsInitialRoute()")
        page.locator('[data-slot="empty-description"]').wait_for(state="visible")
        empty_content = page.locator('[data-slot="model-config-content"]')
        empty_content_height = empty_content.evaluate(
            "element => element.getBoundingClientRect().height"
        )
        empty_surface_height = page.locator(
            '[data-slot="model-config-panel"] > [data-slot="card"]'
        ).evaluate("element => element.getBoundingClientRect().height")
        assert abs(empty_content_height - 390) <= 1
        assert abs(empty_surface_height - 476) <= 1
        assert abs(skeleton_surface_height - empty_surface_height) <= 1
        trigger = page.locator('[data-slot="dialog-trigger"]').first
        trigger.evaluate("element => { window.__modelDialogTrigger = element; }")
        trigger.click()

        dialog = page.locator('[data-slot="dialog-content"]')
        expect(dialog).to_have_attribute("data-state", "open")
        assert (
            dialog.evaluate("element => getComputedStyle(element).animationName")
            == "dialog-content-enter"
        )
        assert (
            dialog.evaluate("element => getComputedStyle(element).animationDuration")
            == "0.21s"
        )
        page.keyboard.press("Escape")
        expect(dialog).to_have_attribute("data-state", "closed")
        assert (
            dialog.evaluate("element => getComputedStyle(element).animationName")
            == "dialog-content-exit"
        )
        assert (
            dialog.evaluate("element => getComputedStyle(element).animationDuration")
            == "0.15s"
        )
        dialog.wait_for(state="detached")

        assert (
            page.evaluate(
                """
            () => window.__modelDialogTrigger ===
              document.querySelector('[data-slot="dialog-trigger"]')
            """
            )
            is True
        )
        assert trigger.evaluate("element => document.activeElement === element") is True
    finally:
        context.close()


def test_first_model_creation_keeps_the_compact_panel_height(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()

    def fulfill_empty_models(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["modelConfigs"] = []
        route.fulfill(
            response=response,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def fulfill_local_provider(route: Route) -> None:
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "code": 0,
                    "message": "OK",
                    "data": {
                        "providers": [
                            {
                                "id": "ollama",
                                "label": "Ollama",
                                "kind": "local",
                                "apiFamily": "openai_compatible_chat",
                                "iconProvider": "ollama",
                                "defaultBaseUrl": "http://localhost:11434/v1",
                                "officialUrl": "",
                                "authRequired": False,
                                "supportsModelDiscovery": False,
                                "supportsCustomCapabilities": False,
                                "supportsTools": True,
                                "supportsStreaming": True,
                            }
                        ]
                    },
                }
            ),
        )

    def fulfill_created_model(route: Route) -> None:
        request_payload = route.request.post_data_json
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "code": 0,
                    "message": "OK",
                    "data": {
                        **request_payload,
                        "id": "llm-first-height",
                        "providerLabel": "Ollama",
                        "iconProvider": "ollama",
                        "apiKeyPreview": "",
                    },
                }
            ),
        )

    page.route("**/api/workspace/pages/models", fulfill_empty_models)
    page.route("**/api/model-providers", fulfill_local_provider)
    page.route("**/api/model-configs", fulfill_created_model)

    try:
        page.goto(f"{frontend_url}/models", wait_until="networkidle")
        panel = page.locator('[data-slot="model-config-panel"]')
        panel.wait_for(state="visible")
        model_surface_height = panel.locator(':scope > [data-slot="card"]').evaluate(
            "element => element.getBoundingClientRect().height"
        )

        trash_page = context.new_page()

        def fulfill_empty_trash(route: Route) -> None:
            response = route.fetch()
            payload = response.json()
            payload["data"]["deletedResumes"] = []
            payload["data"]["deletedTemplates"] = []
            route.fulfill(
                response=response,
                content_type="application/json",
                body=json.dumps(payload),
            )

        trash_page.route("**/api/workspace/pages/trash", fulfill_empty_trash)
        trash_page.goto(f"{frontend_url}/trash", wait_until="networkidle")
        recycle_surface = trash_page.locator('[data-slot="recycle-bin-panel"]')
        recycle_surface.wait_for(state="visible")
        recycle_surface_height = recycle_surface.evaluate(
            "element => element.getBoundingClientRect().height"
        )
        trash_page.close()

        assert abs(model_surface_height - 476) <= 1
        assert abs(recycle_surface_height - 476) <= 1
        assert abs(model_surface_height - recycle_surface_height) <= 1
        page.evaluate(
            """
            () => {
              window.__modelAddHeightFrames = [];
              window.__recordModelAddHeightFrames = true;
              const sample = () => {
                const panel = document.querySelector(
                  '[data-slot="model-config-panel"]',
                );
                const card = panel?.querySelector('[data-slot="card"]');
                const content = panel?.querySelector(
                  '[data-slot="model-config-content"]',
                );
                const row = content?.querySelector(
                  '[data-slot="table-body"] [data-slot="table-row"]',
                );
                const rowStyle = row ? getComputedStyle(row) : null;
                const rowTransform = rowStyle?.transform ?? null;
                window.__modelAddHeightFrames.push({
                  card: card?.getBoundingClientRect().height ?? null,
                  content: content?.getBoundingClientRect().height ?? null,
                  hasEmpty: Boolean(content?.querySelector('[data-slot="empty"]')),
                  panel: panel?.getBoundingClientRect().height ?? null,
                  rowAnimationName: rowStyle?.animationName ?? null,
                  rowCount: content?.querySelectorAll(
                    '[data-slot="table-body"] [data-slot="table-row"]',
                  ).length ?? 0,
                  rowOpacity: rowStyle?.opacity ?? null,
                  rowTransform,
                  rowTranslateY: rowTransform
                    ? new DOMMatrixReadOnly(rowTransform).m42
                    : null,
                });
                if (window.__recordModelAddHeightFrames) {
                  requestAnimationFrame(sample);
                }
              };
              requestAnimationFrame(sample);
            }
            """
        )

        page.locator('[data-slot="dialog-trigger"]').first.click()
        expect(page.locator("#model-nickname")).to_be_focused()
        expect(page.locator("#model-provider")).to_contain_text("Ollama")
        page.locator("#model-name").fill("height-test-model")
        page.locator("#model-nickname").fill("Height test")
        page.get_by_role("button", name="创建模型", exact=True).click()

        expect(page.get_by_text("Height test", exact=False)).to_be_visible()
        page.wait_for_timeout(240)
        page.evaluate("window.__recordModelAddHeightFrames = false")
        frames = page.evaluate("window.__modelAddHeightFrames")
        empty_frames = [frame for frame in frames if frame["hasEmpty"]]
        row_frames = [frame for frame in frames if frame["rowCount"] == 1]

        assert empty_frames, frames
        assert row_frames, frames
        for key in ("card", "content", "panel"):
            assert (
                max(frame[key] for frame in frames)
                - min(frame[key] for frame in frames)
                <= 1
            ), frames
        assert max(abs(frame["rowTranslateY"]) for frame in row_frames) <= 0.1, frames
    finally:
        context.close()


def test_model_row_actions_menu_keeps_edit_and_delete_dialogs_stable(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()

    def fulfill_model_config(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["modelConfigs"] = [
            {
                "id": "llm-row-actions",
                "provider": "openai",
                "providerLabel": "OpenAI",
                "iconProvider": "openai",
                "apiFamily": "openai_compatible_chat",
                "providerKind": "cloud",
                "nickname": "Row action model",
                "apiKeyPreview": "sk-test****",
                "model": "gpt-row-actions",
                "apiUrl": "https://api.openai.com/v1",
                "temperature": None,
                "topP": None,
                "maxTokens": None,
                "contextWindowTokens": 128000,
                "supportsImage": True,
                "supportsThinking": True,
                "supportsTools": True,
                "supportsStreaming": True,
            }
        ]
        route.fulfill(
            response=response,
            content_type="application/json",
            body=json.dumps(payload),
        )

    page.route("**/api/workspace/pages/models", fulfill_model_config)

    try:
        page.goto(f"{frontend_url}/models", wait_until="networkidle")
        row = page.locator('[data-slot="table-body"] [data-slot="table-row"]').first
        row.wait_for(state="visible")
        table_surface = page.locator('[data-slot="data-table"]')
        table_head = page.locator('[data-slot="table-head"]').first
        table_cell = row.locator('[data-slot="table-cell"]').first
        table_heads = page.locator('[data-slot="table-head"]')
        row_cells = row.locator('[data-slot="table-cell"]')
        model_header = table_heads.nth(1).locator(":scope > span")
        model_name = row_cells.nth(1).locator(":scope > div > div > span").first
        context_header = table_heads.nth(3).locator(":scope > span")
        context_value = row_cells.nth(3).locator(":scope > div > span")
        capability_header = table_heads.nth(4).locator(":scope > span")
        capability_group = row_cells.nth(4).locator(":scope > div")
        provider_icon_box = row_cells.nth(1).locator(":scope > div > span").first
        table_geometry = page.evaluate(
            """
            ([surface, head, row, cell]) => {
              const surfaceStyle = getComputedStyle(surface);
              const headStyle = getComputedStyle(head);
              const cellStyle = getComputedStyle(cell);
              return {
                radius: surfaceStyle.borderTopLeftRadius,
                shadow: surfaceStyle.boxShadow,
                headHeight: head.getBoundingClientRect().height,
                headPaddingLeft: headStyle.paddingLeft,
                cellPaddingLeft: cellStyle.paddingLeft,
                rowHeight: row.getBoundingClientRect().height,
              };
            }
            """,
            [
                table_surface.element_handle(),
                table_head.element_handle(),
                row.element_handle(),
                table_cell.element_handle(),
            ],
        )
        assert table_geometry["radius"] == "10px", table_geometry
        assert table_geometry["shadow"] == "none", table_geometry
        assert table_geometry["headHeight"] == 40, table_geometry
        assert table_geometry["headPaddingLeft"] == "8px", table_geometry
        assert table_geometry["cellPaddingLeft"] == "8px", table_geometry
        assert abs(table_geometry["rowHeight"] - 48) <= 1, table_geometry
        provider_icon_style = provider_icon_box.evaluate(
            """
            element => {
              const style = getComputedStyle(element);
              return {
                background: style.backgroundColor,
                borderWidth: style.borderTopWidth,
              };
            }
            """
        )
        assert provider_icon_style == {
            "background": "rgba(0, 0, 0, 0)",
            "borderWidth": "0px",
        }, provider_icon_style
        column_alignment = page.evaluate(
            """
            ([modelHeader, modelName, contextHeader, contextValue,
              capabilityHeader, capabilityGroup]) => {
              const contentRect = (element) => {
                const range = document.createRange();
                range.selectNodeContents(element);
                return range.getBoundingClientRect();
              };
              const modelHeaderRect = contentRect(modelHeader);
              const modelNameRect = modelName.getBoundingClientRect();
              const contextHeaderRect = contentRect(contextHeader);
              const contextValueRect = contextValue.getBoundingClientRect();
              const capabilityHeaderRect = contentRect(capabilityHeader);
              const capabilityItemRects = Array.from(capabilityGroup.children)
                .map((item) => item.getBoundingClientRect());
              const capabilityValueRect = {
                left: Math.min(...capabilityItemRects.map((rect) => rect.left)),
                right: Math.max(...capabilityItemRects.map((rect) => rect.right)),
              };
              return {
                modelStartDelta: modelHeaderRect.left - modelNameRect.left,
                contextEndDelta: contextHeaderRect.right - contextValueRect.right,
                capabilityCenterDelta:
                  (capabilityHeaderRect.left + capabilityHeaderRect.right) / 2 -
                  (capabilityValueRect.left + capabilityValueRect.right) / 2,
                contextCapabilityGap:
                  capabilityValueRect.left - contextValueRect.right,
              };
            }
            """,
            [
                model_header.element_handle(),
                model_name.element_handle(),
                context_header.element_handle(),
                context_value.element_handle(),
                capability_header.element_handle(),
                capability_group.element_handle(),
            ],
        )
        assert abs(column_alignment["modelStartDelta"]) <= 1, column_alignment
        assert abs(column_alignment["contextEndDelta"]) <= 1, column_alignment
        assert abs(column_alignment["capabilityCenterDelta"]) <= 1, column_alignment
        assert column_alignment["contextCapabilityGap"] >= 48, column_alignment
        actions_trigger = row.get_by_role("button", name="操作", exact=True)
        actions_trigger_element = row.locator('button[aria-label="操作"]')
        expect(actions_trigger).to_be_visible()
        assert row.get_by_role("button", name="修改模型", exact=True).count() == 0
        assert row.get_by_role("button", name="删除模型", exact=True).count() == 0

        closed_trigger_background = actions_trigger_element.evaluate(
            "element => getComputedStyle(element).backgroundColor"
        )
        actions_trigger.click()
        expect(actions_trigger_element).to_have_attribute("data-state", "open")
        page.wait_for_timeout(180)
        open_trigger_background = actions_trigger_element.evaluate(
            "element => getComputedStyle(element).backgroundColor"
        )
        assert open_trigger_background != closed_trigger_background
        menu = page.get_by_role("menu")
        expect(menu).to_be_visible()
        expect(menu.get_by_role("menuitem", name="修改", exact=True)).to_be_visible()
        expect(menu.get_by_role("menuitem", name="删除", exact=True)).to_be_visible()
        assert menu.locator("svg").count() == 0

        menu.get_by_role("menuitem", name="修改", exact=True).click()
        menu.wait_for(state="detached")
        edit_dialog = page.locator('[data-slot="dialog-content"]')
        expect(edit_dialog).to_have_attribute("data-state", "open")
        edit_heading = edit_dialog.get_by_role("heading", name="修改模型")
        nickname_input = page.locator("#model-nickname")
        expect(edit_heading).to_be_visible()
        expect(nickname_input).to_have_value("Row action model")
        expect(edit_heading).to_be_focused()
        nickname_selection_collapsed = nickname_input.evaluate(
            "element => element.selectionStart === element.selectionEnd"
        )
        assert nickname_selection_collapsed is True
        page.wait_for_timeout(180)
        expect(edit_dialog).to_have_attribute("data-state", "open")

        page.keyboard.press("Escape")
        edit_dialog.wait_for(state="detached")
        assert (
            actions_trigger.evaluate("element => document.activeElement === element")
            is True
        )

        actions_trigger.click()
        page.get_by_role("menuitem", name="删除", exact=True).click()
        confirm_dialog = page.locator('[data-slot="alert-dialog-content"]')
        expect(confirm_dialog).to_be_visible()
        expect(
            confirm_dialog.get_by_role("heading", name="删除这个模型？")
        ).to_be_visible()
        confirm_dialog.get_by_role("button", name="取消", exact=True).click()
        confirm_dialog.wait_for(state="detached")
        expect(row).to_contain_text("Row action model")
    finally:
        context.close()


def test_model_table_selection_and_bulk_delete_are_page_scoped(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()
    bulk_delete_requests: list[list[str]] = []

    def fulfill_model_configs(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["modelConfigs"] = [
            {
                "id": f"llm-selection-{index}",
                "provider": "openai",
                "providerLabel": "OpenAI",
                "iconProvider": "openai",
                "apiFamily": "openai_compatible_chat",
                "providerKind": "custom",
                "nickname": f"Selectable model {index}",
                "apiKeyPreview": "sk-test****",
                "model": f"gpt-selection-{index}",
                "apiUrl": "https://api.openai.com/v1",
                "temperature": None,
                "topP": None,
                "maxTokens": None,
                "contextWindowTokens": 128000,
                "supportsImage": False,
                "supportsThinking": False,
                "supportsTools": True,
                "supportsStreaming": True,
            }
            for index in range(11)
        ]
        route.fulfill(
            response=response,
            content_type="application/json",
            body=json.dumps(payload),
        )

    def fulfill_bulk_delete(route: Route) -> None:
        requested_ids = route.request.post_data_json["ids"]
        bulk_delete_requests.append(requested_ids)
        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(
                {
                    "code": 0,
                    "message": "OK",
                    "data": {"ids": requested_ids},
                }
            ),
        )

    page.route("**/api/workspace/pages/models", fulfill_model_configs)
    page.route("**/api/model-configs/bulk-delete", fulfill_bulk_delete)

    try:
        page.goto(f"{frontend_url}/models", wait_until="networkidle")
        bulk_actions = page.locator('[data-slot="model-config-bulk-actions"]')
        bulk_delete = bulk_actions.locator("button")
        new_model = page.get_by_role("button", name="新建模型", exact=True)
        confirm_dialog = page.locator('[data-slot="alert-dialog-content"]')
        select_all = page.locator('[data-slot="table-header"]').get_by_role("checkbox")
        first_selection = (
            page.locator('[data-slot="table-row"]')
            .filter(
                has=page.get_by_text("Selectable model 0 (gpt-selection-0)", exact=True)
            )
            .get_by_role("checkbox")
        )
        second_selection = (
            page.locator('[data-slot="table-row"]')
            .filter(
                has=page.get_by_text("Selectable model 1 (gpt-selection-1)", exact=True)
            )
            .get_by_role("checkbox")
        )

        def record_selection_motion(selection: Locator) -> dict[str, Any]:
            return page.evaluate(
                """
                async ([checkbox, bulkAction, newModel]) => {
                  const button = bulkAction.querySelector('button');
                  const frames = [];
                  const readFrame = () => {
                    const actionStyle = getComputedStyle(bulkAction);
                    const buttonStyle = getComputedStyle(button);
                    const actionRect = bulkAction.getBoundingClientRect();
                    const newModelRect = newModel.getBoundingClientRect();
                    return {
                      opacity: Number(actionStyle.opacity),
                      translateX:
                        actionStyle.transform === 'none'
                          ? 0
                          : new DOMMatrixReadOnly(actionStyle.transform).m41,
                      actionWidth: actionRect.width,
                      actionHeight: actionRect.height,
                      newModelX: newModelRect.x,
                      newModelY: newModelRect.y,
                      newModelWidth: newModelRect.width,
                      newModelHeight: newModelRect.height,
                      buttonOpacity: Number(buttonStyle.opacity),
                      buttonDisabled: button.disabled,
                      buttonAnimationCount: button.getAnimations().length,
                    };
                  };

                  frames.push(readFrame());
                  checkbox.click();
                  const startedAt = performance.now();
                  await new Promise(resolve => {
                    const sample = now => {
                      frames.push(readFrame());
                      const isRunning = bulkAction.getAnimations().some(
                        animation => animation.playState === 'running'
                      );
                      if (
                        (now - startedAt >= 50 && !isRunning) ||
                        now - startedAt >= 650
                      ) {
                        resolve();
                        return;
                      }
                      requestAnimationFrame(sample);
                    };
                    requestAnimationFrame(sample);
                  });
                  frames.push(readFrame());

                  return {
                    frames,
                    actionNodeStable:
                      document.querySelector(
                        '[data-slot="model-config-bulk-actions"]'
                      ) === bulkAction,
                    actionConnected: bulkAction.isConnected,
                    newModelConnected: newModel.isConnected,
                  };
                }
                """,
                [
                    selection.element_handle(),
                    bulk_actions.element_handle(),
                    new_model.element_handle(),
                ],
            )

        def assert_selection_motion(
            motion: dict[str, Any], final_opacity: float
        ) -> None:
            frames = motion["frames"]
            opacities = [frame["opacity"] for frame in frames]
            assert motion["actionNodeStable"], motion
            assert motion["actionConnected"], motion
            assert motion["newModelConnected"], motion
            assert any(0.02 < opacity < 0.98 for opacity in opacities), motion
            assert opacities[-1] == pytest.approx(final_opacity, abs=0.02), motion
            translations = [frame["translateX"] for frame in frames]
            assert max(translations) - min(translations) >= 3.5, motion
            assert any(0.25 < translation < 3.75 for translation in translations), (
                motion
            )
            for key in (
                "actionWidth",
                "actionHeight",
                "newModelX",
                "newModelY",
                "newModelWidth",
                "newModelHeight",
            ):
                values = [frame[key] for frame in frames]
                assert max(values) - min(values) <= 1, (key, motion)
            assert all(
                frame["buttonOpacity"] == pytest.approx(1, abs=0.01) for frame in frames
            ), motion
            assert all(not frame["buttonDisabled"] for frame in frames), motion
            assert all(frame["buttonAnimationCount"] == 0 for frame in frames), motion

        expect(bulk_actions).to_have_attribute("data-state", "closed")
        expect(bulk_actions).to_have_attribute("aria-hidden", "true")
        expect(bulk_delete).to_have_attribute("tabindex", "-1")
        enter_motion = record_selection_motion(first_selection)
        assert_selection_motion(enter_motion, 1)
        expect(first_selection).to_be_checked()
        expect(select_all).to_have_attribute("data-state", "indeterminate")
        expect(bulk_actions).to_have_attribute("data-state", "open")
        expect(bulk_actions).to_have_attribute("aria-hidden", "false")
        expect(bulk_delete).to_be_visible()
        expect(bulk_delete).to_have_attribute("data-variant", "destructive")
        expect(bulk_delete).to_have_attribute("data-size", "default")
        header_action_geometry = page.evaluate(
            """
            ([bulkDelete, newModel]) => {
              const bulkRect = bulkDelete.getBoundingClientRect();
              const newModelRect = newModel.getBoundingClientRect();
              return {
                centerDelta:
                  (bulkRect.top + bulkRect.bottom) / 2 -
                  (newModelRect.top + newModelRect.bottom) / 2,
                gap: newModelRect.left - bulkRect.right,
                heightDelta: bulkRect.height - newModelRect.height,
              };
            }
            """,
            [bulk_delete.element_handle(), new_model.element_handle()],
        )
        assert abs(header_action_geometry["centerDelta"]) <= 1, header_action_geometry
        assert 0 <= header_action_geometry["gap"] <= 16, header_action_geometry
        assert abs(header_action_geometry["heightDelta"]) <= 1, header_action_geometry

        exit_motion = record_selection_motion(first_selection)
        assert_selection_motion(exit_motion, 0)
        expect(first_selection).not_to_be_checked()
        expect(bulk_actions).to_have_attribute("data-state", "closed")
        expect(bulk_actions).to_have_attribute("aria-hidden", "true")
        expect(bulk_delete).to_have_attribute("tabindex", "-1")

        rapid_reversal = page.evaluate(
            """
            async ([checkbox, bulkAction]) => {
              const originalAction = bulkAction;
              checkbox.click();
              await new Promise(requestAnimationFrame);
              checkbox.click();
              await new Promise(requestAnimationFrame);
              checkbox.click();
              const startedAt = performance.now();
              await new Promise(resolve => {
                const waitForRest = now => {
                  const isRunning = bulkAction.getAnimations().some(
                    animation => animation.playState === 'running'
                  );
                  if (
                    (now - startedAt >= 50 && !isRunning) ||
                    now - startedAt >= 650
                  ) {
                    resolve();
                    return;
                  }
                  requestAnimationFrame(waitForRest);
                };
                requestAnimationFrame(waitForRest);
              });
              return {
                sameNode:
                  document.querySelector(
                    '[data-slot="model-config-bulk-actions"]'
                  ) === originalAction,
                state: bulkAction.dataset.state,
                opacity: Number(getComputedStyle(bulkAction).opacity),
                runningAnimations: bulkAction.getAnimations().filter(
                  animation => animation.playState === 'running'
                ).length,
              };
            }
            """,
            [
                first_selection.element_handle(),
                bulk_actions.element_handle(),
            ],
        )
        assert rapid_reversal == {
            "sameNode": True,
            "state": "open",
            "opacity": 1,
            "runningAnimations": 0,
        }
        expect(first_selection).to_be_checked()
        bulk_delete.click()
        expect(confirm_dialog).to_be_visible()
        expect(
            confirm_dialog.get_by_role("heading", name="删除选中的模型？")
        ).to_be_visible()
        confirm_dialog.locator('[data-slot="alert-dialog-cancel"]').click()
        confirm_dialog.wait_for(state="detached")
        expect(first_selection).to_be_checked()
        expect(bulk_actions).to_have_attribute("data-state", "open")

        second_selection.check()
        expect(bulk_actions).to_have_attribute("data-state", "open")

        page.get_by_role("link", name="2", exact=True).click()
        page.wait_for_url("**/models?page=2")
        expect(page.get_by_text("Selectable model 10", exact=False)).to_be_visible()
        expect(bulk_actions).to_have_attribute("data-state", "closed")
        expect(select_all).not_to_be_checked()

        page.go_back()
        page.wait_for_url(f"{frontend_url}/models")
        expect(first_selection).not_to_be_checked()
        expect(second_selection).not_to_be_checked()
        expect(bulk_actions).to_have_attribute("data-state", "closed")

        page.emulate_media(reduced_motion="reduce")
        select_all.check()
        expect(
            page.locator(
                '[data-slot="table-body"] [data-slot="table-row"]'
                '[data-state="selected"]'
            )
        ).to_have_count(10)
        expect(bulk_actions).to_have_attribute("data-state", "open")
        reduced_motion_open = bulk_actions.evaluate(
            """
            action => ({
              opacity: Number(getComputedStyle(action).opacity),
              transitionProperty: getComputedStyle(action).transitionProperty,
              animationCount: action.getAnimations().length,
            })
            """
        )
        assert reduced_motion_open == {
            "opacity": 1,
            "transitionProperty": "none",
            "animationCount": 0,
        }
        select_all.uncheck()
        expect(bulk_actions).to_have_attribute("data-state", "closed")
        reduced_motion_closed = bulk_actions.evaluate(
            """
            action => ({
              opacity: Number(getComputedStyle(action).opacity),
              transitionProperty: getComputedStyle(action).transitionProperty,
              animationCount: action.getAnimations().length,
            })
            """
        )
        assert reduced_motion_closed == {
            "opacity": 0,
            "transitionProperty": "none",
            "animationCount": 0,
        }
        page.emulate_media(reduced_motion="no-preference")

        first_selection.check()
        second_selection.check()
        bulk_delete.click()
        expect(confirm_dialog).to_be_visible()
        assert confirm_dialog.locator(
            '[data-slot="alert-dialog-title"]'
        ).inner_text() in {
            "删除选中的模型？",
            "Delete the selected models?",
        }
        confirm_dialog.locator('[data-slot="alert-dialog-cancel"]').click()
        confirm_dialog.wait_for(state="detached")
        expect(first_selection).to_be_checked()
        expect(second_selection).to_be_checked()
        expect(bulk_actions).to_have_attribute("data-state", "open")

        bulk_delete.click()
        confirm_dialog.locator('[data-slot="alert-dialog-action"]').click()
        confirm_dialog.wait_for(state="detached")

        expect(first_selection).to_have_count(0)
        expect(second_selection).to_have_count(0)
        expect(page.get_by_text("Selectable model 2", exact=False)).to_be_visible()
        expect(bulk_actions).to_have_attribute("data-state", "closed")
        expect(
            page.locator('[data-slot="table-body"] [data-slot="table-row"]')
        ).to_have_count(9)
        assert bulk_delete_requests == [["llm-selection-0", "llm-selection-1"]]
    finally:
        context.close()


@pytest.mark.parametrize("model_count", [1, 10, 11, 16])
def test_models_configured_layout_grows_with_content_then_paginates(
    browser: Browser,
    workspace_servers: tuple[str, str],
    model_count: int,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()

    def fulfill_model_configs(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["modelConfigs"] = [
            {
                "id": f"llm-layout-{index}",
                "provider": "openai",
                "providerLabel": "OpenAI",
                "iconProvider": "openai",
                "apiFamily": "openai_compatible_chat",
                "providerKind": "custom",
                "nickname": f"Layout model {index}",
                "apiKeyPreview": "sk-test****",
                "model": f"gpt-layout-{index}",
                "apiUrl": "https://api.openai.com/v1",
                "temperature": None,
                "topP": None,
                "maxTokens": None,
                "contextWindowTokens": 128000,
                "supportsImage": False,
                "supportsThinking": False,
                "supportsTools": True,
                "supportsStreaming": True,
            }
            for index in range(model_count)
        ]
        route.fulfill(
            response=response,
            content_type="application/json",
            body=json.dumps(payload),
        )

    page.route("**/api/workspace/pages/models", fulfill_model_configs)

    try:
        page.goto(f"{frontend_url}/models", wait_until="networkidle")
        panel = page.locator('[data-slot="model-config-panel"]')
        content = page.locator('[data-slot="model-config-content"]')
        panel.wait_for(state="visible")
        content.wait_for(state="visible")
        table_rows = content.locator('[data-slot="table-body"] [data-slot="table-row"]')
        expect(table_rows).to_have_count(min(model_count, 10))
        assert page.locator('[data-slot="model-config-table-scroll-area"]').count() == 0

        content_height = content.evaluate(
            "element => element.getBoundingClientRect().height"
        )
        if model_count == 1:
            assert abs(content_height - 390) <= 1
        else:
            assert content_height > 390

        pagination = content.locator('[data-slot="pagination"]')
        assert pagination.count() == (1 if model_count > 10 else 0)

        if model_count > 10:
            pagination.locator('[data-slot="pagination-link"]').last.click()
            page.wait_for_url("**/models?page=2")
            expect(table_rows).to_have_count(model_count - 10)
            expect(page.get_by_text("Layout model 10", exact=False)).to_be_visible()
    finally:
        context.close()
