from __future__ import annotations

import json
import os
from typing import Any

import pytest
from playwright.sync_api import Browser, Route, expect

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_resume_agent_uses_canvas_toggle_and_compact_actions_menu(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()

    try:
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )

        header = page.locator("header")
        workspace = page.locator(".resume-workspace")
        workspace.wait_for(state="visible")

        assert header.get_by_text("Reseno AI", exact=True).count() == 0
        assert (
            page.locator(
                '[data-slot="sheet-content"], [data-slot="sheet-overlay"]'
            ).count()
            == 0
        )
        assert page.get_by_role("dialog").count() == 0

        trigger = workspace.locator('[data-slot="agent-panel-toggle"]')
        trigger.wait_for(state="visible")
        assert trigger.count() == 1
        assert trigger.get_attribute("aria-expanded") == "false"

        trigger_box = trigger.bounding_box()
        canvas_controls = workspace.locator('[data-slot="document-canvas-controls"]')
        controls_box = canvas_controls.bounding_box()
        assert trigger_box is not None
        assert controls_box is not None
        assert trigger_box["width"] >= 40
        assert 30 <= trigger_box["height"] <= 34
        assert 30 <= controls_box["height"] <= 34
        assert trigger_box["width"] > trigger_box["height"]
        controls_gap = trigger_box["x"] - (controls_box["x"] + controls_box["width"])
        assert 4 <= controls_gap <= 16
        assert abs(trigger_box["y"] - controls_box["y"]) <= 1

        fit_to_width = page.get_by_role(
            "button",
            name="适合宽度",
            exact=True,
        )
        fit_to_width.click()
        expect(fit_to_width).to_have_attribute("aria-pressed", "true")

        panel = workspace.locator("section.agent-panel-card")
        assert not panel.is_visible()

        def assert_no_horizontal_page_overflow() -> None:
            overflow = page.evaluate(
                """
                () => ({
                  clientWidth: document.documentElement.clientWidth,
                  scrollWidth: document.documentElement.scrollWidth,
                })
                """
            )
            assert overflow["scrollWidth"] <= overflow["clientWidth"] + 1, overflow

        def start_motion_probe() -> None:
            page.evaluate(
                """
                () => {
                  const samples = [];
                  const startedAt = performance.now();

                  const sample = timestamp => {
                    const workspace = document.querySelector(
                      '.resume-workspace',
                    );
                    const dock = workspace?.querySelector(
                      '.agent-panel-dock',
                    );
                    const panelLayer = document.querySelector(
                      '.resume-workspace .agent-panel-motion-layer',
                    );
                    const panelCard = document.querySelector(
                      '.resume-workspace .agent-panel-card',
                    );
                    const editor = document.querySelector(
                      '.resume-workspace .resume-editor-panel',
                    );
                    const previewFrame = document.querySelector(
                      '.resume-workspace [data-slot="document-canvas-viewport"]',
                    );
                    const previewElement = document.querySelector(
                      '.resume-workspace .document-canvas-scale-content',
                    );
                    const workspaceStyle = workspace
                      ? getComputedStyle(workspace)
                      : null;
                    const dockStyle = dock ? getComputedStyle(dock) : null;
                    const panelStyle = panelLayer
                      ? getComputedStyle(panelLayer)
                      : null;
                    const previewStyle = previewElement
                      ? getComputedStyle(previewElement)
                      : null;
                    const frameRect = previewFrame?.getBoundingClientRect();
                    const contentRect = previewElement?.getBoundingClientRect();
                    const dockRect = dock?.getBoundingClientRect();
                    const panelCardRect = panelCard?.getBoundingClientRect();
                    const editorRect = editor?.getBoundingClientRect();
                    const editorStyle = editor
                      ? getComputedStyle(editor)
                      : null;
                    const editorCenterOwner = editorRect
                      ? document.elementFromPoint(
                          editorRect.left + editorRect.width / 2,
                          Math.min(
                            editorRect.bottom - 1,
                            editorRect.top + 24,
                          ),
                        )
                      : null;
                    const columns = workspaceStyle?.gridTemplateColumns
                      .split(/\\s+/)
                      .map(value => Number.parseFloat(value)) ?? [];
                    samples.push({
                      elapsed: timestamp - startedAt,
                      panelColumnWidth: columns[2] ?? null,
                      dockOverflow: dockStyle?.overflow ?? null,
                      panelLayerWidth: panelLayer
                        ? panelLayer.getBoundingClientRect().width
                        : null,
                      panelLeftClip: dockRect && panelCardRect
                        ? Math.max(0, dockRect.left - panelCardRect.left)
                        : null,
                      panelRightClip: dockRect && panelCardRect
                        ? Math.max(0, panelCardRect.right - dockRect.right)
                        : null,
                      panelOpacity: panelStyle
                        ? Number.parseFloat(panelStyle.opacity)
                        : null,
                      panelTransform: panelStyle?.transform ?? null,
                      previewTransform: previewStyle?.transform ?? null,
                      previewContentWillChange: previewElement
                        ? getComputedStyle(previewElement).willChange
                        : null,
                      previewAnimationCount: previewElement
                        ? previewElement.getAnimations().length
                        : 0,
                      previewClippedLeft: frameRect && contentRect
                        ? Math.max(0, frameRect.left - contentRect.left)
                        : null,
                      previewClippedRight: frameRect && contentRect
                        ? Math.max(0, contentRect.right - frameRect.right)
                        : null,
                      workspaceAnimationCount: workspace
                        ? workspace.getAnimations().filter(animation =>
                            ['pending', 'running'].includes(animation.playState)
                          ).length
                        : 0,
                      editorVisible: editor instanceof HTMLElement &&
                        editor.isConnected &&
                        editorStyle?.display !== 'none' &&
                        editorStyle?.visibility !== 'hidden' &&
                        Number(editorStyle?.opacity ?? 0) > 0.99 &&
                        Boolean(editorRect?.width) &&
                        Boolean(editorRect?.height) &&
                        editor.contains(editorCenterOwner),
                      editorRect: editorRect ? {
                        x: editorRect.x,
                        y: editorRect.y,
                        width: editorRect.width,
                        height: editorRect.height,
                      } : null,
                    });
                  };

                  sample(startedAt);
                  window.__agentPanelMotionProbe = {
                    done: false,
                    samples,
                  };

                  const tick = timestamp => {
                    sample(timestamp);
                    if (timestamp - startedAt < 320) {
                      requestAnimationFrame(tick);
                      return;
                    }
                    window.__agentPanelMotionProbe.done = true;
                  };

                  requestAnimationFrame(tick);
                }
                """
            )

        def finish_motion_probe(*, expanded: bool) -> None:
            page.wait_for_function(
                "() => window.__agentPanelMotionProbe?.done === true"
            )
            samples = page.evaluate(
                """
                () => {
                  const result = window.__agentPanelMotionProbe;
                  delete window.__agentPanelMotionProbe;
                  return result.samples;
                }
                """
            )
            panel_opacities = [
                sample["panelOpacity"]
                for sample in samples
                if sample["panelOpacity"] is not None
            ]
            panel_column_widths = [
                sample["panelColumnWidth"]
                for sample in samples
                if sample["panelColumnWidth"] is not None
            ]
            panel_layer_widths = [
                sample["panelLayerWidth"]
                for sample in samples
                if sample["panelLayerWidth"] is not None
            ]
            preview_clipping = [
                max(sample["previewClippedLeft"], sample["previewClippedRight"])
                for sample in samples
                if sample["previewClippedLeft"] is not None
                and sample["previewClippedRight"] is not None
            ]
            width_deltas = [
                current - previous
                for previous, current in zip(
                    panel_column_widths,
                    panel_column_widths[1:],
                    strict=False,
                )
            ]
            intermediate_widths = {
                round(width) for width in panel_column_widths if 1 < width < 359
            }
            middle_panel_reveal_samples = [
                sample
                for sample in samples
                if sample["panelColumnWidth"] is not None
                and 72 < sample["panelColumnWidth"] < 288
                and sample["panelOpacity"] is not None
                and sample["panelOpacity"] > 0.05
                and sample["panelLeftClip"] is not None
                and sample["panelRightClip"] is not None
            ]

            assert len(samples) >= 4, samples
            assert len(intermediate_widths) >= 3, samples
            assert max(sample["workspaceAnimationCount"] for sample in samples) <= 1
            assert all(
                sample["dockOverflow"] in (None, "hidden") for sample in samples
            ), samples
            assert all(abs(width - 360) <= 1 for width in panel_layer_widths), samples
            assert max(panel_opacities) - min(panel_opacities) >= 0.8, samples
            assert any(0.05 < opacity < 0.95 for opacity in panel_opacities), samples
            assert (panel_opacities[-1] >= 0.95) is expanded, samples
            assert all(
                sample["previewTransform"] in (None, "none") for sample in samples
            ), samples
            assert all(
                sample["previewContentWillChange"] in (None, "auto")
                for sample in samples
            ), {
                "message": (
                    "The scaled preview kept a persistent compositor hint while "
                    "its grid track was moving."
                ),
                "samples": samples,
            }
            assert all(sample["previewAnimationCount"] == 0 for sample in samples)
            assert preview_clipping[-1] <= 1.5, samples
            assert all(sample["editorVisible"] for sample in samples), {
                "message": "The resume editor disappeared during Agent motion.",
                "samples": samples,
            }
            editor_rects = [
                sample["editorRect"]
                for sample in samples
                if sample["editorRect"] is not None
            ]
            assert editor_rects, samples
            for editor_rect in editor_rects[1:]:
                for key in ("x", "y", "width", "height"):
                    assert abs(editor_rect[key] - editor_rects[0][key]) <= 1, {
                        "message": (
                            "The fixed editor pane moved while the Agent column "
                            "was resizing."
                        ),
                        "samples": samples,
                    }
            if expanded:
                assert len(middle_panel_reveal_samples) >= 2, samples
                assert (
                    max(
                        sample["panelLeftClip"]
                        for sample in middle_panel_reveal_samples
                    )
                    <= 1.5
                ), middle_panel_reveal_samples
                assert (
                    min(
                        sample["panelRightClip"]
                        for sample in middle_panel_reveal_samples
                    )
                    >= 24
                ), middle_panel_reveal_samples
                assert all(delta >= -1 for delta in width_deltas), samples
                assert panel_column_widths[-1] >= 359, samples
            else:
                assert all(delta <= 1 for delta in width_deltas), samples
                assert panel_column_widths[-1] <= 1, samples
                assert all(
                    sample["panelOpacity"] is None
                    or sample["panelColumnWidth"] is None
                    or sample["panelColumnWidth"] <= 8
                    or sample["panelOpacity"] > 0.01
                    for sample in samples
                ), samples

        def layout_metrics() -> dict[str, Any]:
            return workspace.evaluate(
                """
                element => {
                  const editor = element.querySelector(".resume-editor-panel");
                  const preview = element.querySelector(".resume-preview-card");
                  const panel = element.querySelector(".agent-panel-card");
                  if (!(editor instanceof HTMLElement) ||
                      !(preview instanceof HTMLElement)) {
                    throw new Error("Missing resume workspace panes.");
                  }

                  const editorRect = editor.getBoundingClientRect();
                  const previewRect = preview.getBoundingClientRect();
                  const panelRect = panel?.getBoundingClientRect();
                  const headerRect = element.ownerDocument
                    .querySelector("header")
                    ?.getBoundingClientRect();
                  return {
                    columns: getComputedStyle(element)
                      .gridTemplateColumns
                      .split(/\\s+/)
                      .map(value => Number.parseFloat(value)),
                    headerBottom: headerRect?.bottom ?? null,
                    editorPreviewSpan: previewRect.right - editorRect.left,
                    editorWidth: editorRect.width,
                    previewWidth: previewRect.width,
                    previewBottomGap: window.innerHeight - previewRect.bottom,
                    editor: {
                      bottom: editorRect.bottom,
                      left: editorRect.left,
                      right: editorRect.right,
                      top: editorRect.top,
                    },
                    preview: {
                      bottom: previewRect.bottom,
                      left: previewRect.left,
                      right: previewRect.right,
                      top: previewRect.top,
                    },
                    panel: panelRect ? {
                      bottom: panelRect.bottom,
                      left: panelRect.left,
                      right: panelRect.right,
                      top: panelRect.top,
                      width: panelRect.width,
                    } : null,
                  };
                }
                """
            )

        collapsed = layout_metrics()
        assert len(collapsed["columns"]) == 3
        assert collapsed["columns"][2] <= 1
        assert collapsed["editorWidth"] > 0
        assert collapsed["previewWidth"] > 0
        assert abs(collapsed["previewBottomGap"]) <= 1
        assert collapsed["headerBottom"] is not None
        assert abs(collapsed["editor"]["top"] - collapsed["headerBottom"]) <= 1
        assert abs(collapsed["preview"]["top"] - collapsed["headerBottom"]) <= 1
        assert abs(collapsed["editor"]["bottom"] - collapsed["preview"]["bottom"]) <= 1
        assert abs(collapsed["editor"]["right"] - collapsed["preview"]["left"]) <= 1
        assert_no_horizontal_page_overflow()

        page.locator(
            ".resume-workspace .resume-preview-card "
            '[data-resume-pagination-ready="true"]'
        ).wait_for(state="visible")
        page.evaluate(
            """
            () => {
              const viewport = document.querySelector(
                '.resume-workspace [data-slot="document-canvas-viewport"]',
              );
              const content = viewport?.querySelector(
                '.document-canvas-scale-content',
              );
              if (!(viewport instanceof HTMLElement) ||
                  !(content instanceof HTMLElement)) {
                throw new Error('Missing document canvas elements.');
              }

              const clientWidthGetter = Object.getOwnPropertyDescriptor(
                Element.prototype,
                'clientWidth',
              )?.get;
              if (!clientWidthGetter) {
                throw new Error('Canvas viewport width accessor is unavailable.');
              }

              const result = {
                viewportWidthReads: 0,
                resizeCallbacks: 0,
                styleMutations: 0,
                postResizeClipping: [],
                viewportWidthReadsByFrame: {},
              };
              let frameId = 0;
              let frameMarkerId = 0;
              const markFrame = () => {
                frameId += 1;
                frameMarkerId = requestAnimationFrame(markFrame);
              };
              frameMarkerId = requestAnimationFrame(markFrame);
              const recordRead = key => {
                const readsByFrame = result[key];
                readsByFrame[frameId] = (readsByFrame[frameId] ?? 0) + 1;
              };
              Object.defineProperty(viewport, 'clientWidth', {
                configurable: true,
                get() {
                  result.viewportWidthReads += 1;
                  recordRead('viewportWidthReadsByFrame');
                  return clientWidthGetter.call(this);
                },
              });
              const resizeObserver = new ResizeObserver(() => {
                result.resizeCallbacks += 1;
                const viewportRect = viewport.getBoundingClientRect();
                const contentRect = content.getBoundingClientRect();
                result.postResizeClipping.push(Math.max(
                  viewportRect.left - contentRect.left,
                  contentRect.right - viewportRect.right,
                  0,
                ));
              });
              const mutationObserver = new MutationObserver((records) => {
                result.styleMutations += records.filter(
                  record => record.target === viewport,
                ).length;
              });

              resizeObserver.observe(viewport);
              mutationObserver.observe(viewport, {
                attributes: true,
                attributeFilter: ['style'],
              });
              const snapshot = () => {
                result.styleMutations += mutationObserver
                  .takeRecords()
                  .filter(record => record.target === viewport).length;
                return {
                  ...result,
                  maxViewportWidthReadsPerFrame: Math.max(
                    0,
                    ...Object.values(result.viewportWidthReadsByFrame),
                  ),
                };
              };
              window.__agentPanelPreviewProbe = {
                snapshot,
                stop() {
                  cancelAnimationFrame(frameMarkerId);
                  resizeObserver.disconnect();
                  mutationObserver.disconnect();
                  delete viewport.clientWidth;
                  return snapshot();
                },
              };
            }
            """
        )

        start_motion_probe()
        trigger.click()

        collapse_trigger = trigger
        collapse_trigger.wait_for(state="visible")
        expect(collapse_trigger).to_have_attribute("aria-expanded", "true")
        finish_motion_probe(expanded=True)

        page.wait_for_function(
            """
            () => {
              const workspace = document.querySelector(".resume-workspace");
              if (!(workspace instanceof HTMLElement)) return false;
              const columns = getComputedStyle(workspace)
                .gridTemplateColumns
                .split(/\\s+/)
                .map(value => Number.parseFloat(value));
              return columns.length === 3 && columns[2] > 350;
            }
            """
        )

        panel.wait_for(state="visible")

        preview_probe_at_settle = page.evaluate(
            """
            () => window.__agentPanelPreviewProbe?.snapshot()
            """
        )
        page.evaluate(
            """
            () => new Promise(resolve => {
              let remainingFrames = 8;
              const tick = () => {
                remainingFrames -= 1;
                if (remainingFrames <= 0) {
                  resolve();
                  return;
                }
                requestAnimationFrame(tick);
              };
              requestAnimationFrame(tick);
            })
            """
        )
        preview_probe = page.evaluate(
            """
            () => {
              const probe = window.__agentPanelPreviewProbe;
              if (!probe) {
                throw new Error('The Agent panel preview probe is unavailable.');
              }
              delete window.__agentPanelPreviewProbe;
              return probe.stop();
            }
            """
        )
        assert preview_probe_at_settle is not None
        assert preview_probe["resizeCallbacks"] >= 3, preview_probe
        assert preview_probe["styleMutations"] >= 3, preview_probe
        assert preview_probe["viewportWidthReads"] >= 3, preview_probe
        assert preview_probe["maxViewportWidthReadsPerFrame"] <= 1, preview_probe
        assert preview_probe["postResizeClipping"], preview_probe
        assert max(preview_probe["postResizeClipping"]) <= 1.5, preview_probe
        assert (
            preview_probe["viewportWidthReads"]
            == preview_probe_at_settle["viewportWidthReads"]
        ), preview_probe

        preview_fit = page.evaluate(
            """
            () => {
              const frame = document.querySelector(
                '.resume-workspace [data-slot="document-canvas-viewport"]',
              );
              const content = frame?.querySelector(
                '.document-canvas-scale-content',
              );
              if (!(frame instanceof HTMLElement) ||
                  !(content instanceof HTMLElement)) {
                throw new Error('Missing scaled preview content.');
              }
              const frameRect = frame.getBoundingClientRect();
              const contentRect = content.getBoundingClientRect();
              return {
                left: contentRect.left - frameRect.left,
                right: frameRect.right - contentRect.right,
              };
            }
            """
        )
        assert preview_fit["left"] >= -1, preview_fit
        assert preview_fit["right"] >= -1, preview_fit

        assert (
            page.locator(
                '[data-slot="sheet-content"], [data-slot="sheet-overlay"]'
            ).count()
            == 0
        )
        assert page.get_by_role("dialog").count() == 0

        expanded = layout_metrics()
        assert len(expanded["columns"]) == 3
        assert expanded["columns"][2] > 350
        assert collapsed["editorPreviewSpan"] - expanded["editorPreviewSpan"] > 300
        assert collapsed["previewWidth"] - expanded["previewWidth"] > 300
        assert expanded["panel"] is not None
        assert expanded["preview"]["right"] <= expanded["panel"]["left"]
        assert abs(expanded["panel"]["width"] - expanded["columns"][2]) <= 1
        assert abs(expanded["panel"]["top"] - expanded["headerBottom"]) <= 1
        assert abs(expanded["panel"]["bottom"] - expanded["preview"]["bottom"]) <= 1
        assert abs(expanded["editor"]["right"] - expanded["preview"]["left"]) <= 1
        assert abs(expanded["preview"]["right"] - expanded["panel"]["left"]) <= 1
        assert_no_horizontal_page_overflow()

        agent_thread = workspace.locator(".agent-thread-layout")
        agent_thread.wait_for(state="visible")
        page.evaluate(
            """
            () => {
              window.__retainedAgentThread = document.querySelector(
                '.resume-workspace .agent-thread-layout',
              );
            }
            """
        )

        start_motion_probe()
        collapse_trigger.click()
        finish_motion_probe(expanded=False)
        trigger.wait_for(state="visible")
        retained_after_collapse = page.evaluate(
            """
            () => {
              const retained = window.__retainedAgentThread;
              const current = document.querySelector(
                '.resume-workspace .agent-thread-layout',
              );
              const dock = document.querySelector(
                '.resume-workspace .agent-panel-dock',
              );
              return {
                connected: retained?.isConnected ?? false,
                sameNode: retained === current,
                ariaHidden: dock?.getAttribute('aria-hidden'),
                inert: dock instanceof HTMLElement ? dock.inert : false,
              };
            }
            """
        )
        assert retained_after_collapse == {
            "connected": True,
            "sameNode": True,
            "ariaHidden": "true",
            "inert": True,
        }

        trigger.click()
        expect(trigger).to_have_attribute("aria-expanded", "true")
        page.wait_for_function(
            """
            () => {
              const workspace = document.querySelector('.resume-workspace');
              if (!(workspace instanceof HTMLElement)) return false;
              const width = Number.parseFloat(
                getComputedStyle(workspace).gridTemplateColumns.split(/\\s+/)[2]
              );
              return 24 < width && width < 336;
            }
            """
        )
        interrupted_reversal = workspace.evaluate(
            """
            element => {
              const trigger = element.querySelector(
                '[data-slot="agent-panel-toggle"]',
              );
              if (!(trigger instanceof HTMLButtonElement)) {
                throw new Error('Missing Agent panel trigger.');
              }
              const readWidth = () => Number.parseFloat(
                getComputedStyle(element).gridTemplateColumns.split(/\\s+/)[2]
              );
              const before = readWidth();
              trigger.click();
              return new Promise(resolve => {
                requestAnimationFrame(() => resolve({
                      before,
                      after: readWidth(),
                      ariaExpandedAfter: trigger.getAttribute('aria-expanded'),
                      workspaceAnimationCount: element.getAnimations()
                        .filter(animation =>
                          ['pending', 'running'].includes(animation.playState)
                        ).length,
                    }));
              });
            }
            """
        )
        assert 24 < interrupted_reversal["before"] < 336, interrupted_reversal
        assert interrupted_reversal["ariaExpandedAfter"] == "false"
        assert 1 < interrupted_reversal["after"] < 359, interrupted_reversal
        assert interrupted_reversal["workspaceAnimationCount"] == 1
        expect(trigger).to_have_attribute("aria-expanded", "false")
        page.wait_for_timeout(320)
        interrupted_motion = workspace.evaluate(
            """
            element => {
              const panelLayer = element.querySelector(
                '.agent-panel-motion-layer',
              );
              const columns = getComputedStyle(element)
                .gridTemplateColumns
                .split(/\\s+/)
                .map(value => Number.parseFloat(value));
              const activeAnimationCount = [element, panelLayer]
                .filter(Boolean)
                .flatMap(target => target.getAnimations())
                .filter(animation =>
                  ['pending', 'running'].includes(animation.playState)
                ).length;
              const retained = window.__retainedAgentThread;
              return {
                activeAnimationCount,
                panelColumnWidth: columns[2],
                retainedThread:
                  retained?.isConnected === true &&
                  retained === element.querySelector('.agent-thread-layout'),
              };
            }
            """
        )
        assert interrupted_motion == {
            "activeAnimationCount": 0,
            "panelColumnWidth": 0,
            "retainedThread": True,
        }

        page.emulate_media(reduced_motion="reduce")
        trigger.click()
        expect(trigger).to_have_attribute("aria-expanded", "true")
        page.evaluate(
            """
            () => new Promise(resolve =>
              requestAnimationFrame(() => requestAnimationFrame(resolve))
            )
            """
        )
        reduced_motion = workspace.evaluate(
            """
            element => {
              const panelLayer = element.querySelector(
                '.agent-panel-motion-layer',
              );
              const previewElement = element.querySelector(
                '.document-canvas-scale-content',
              );
              const columns = getComputedStyle(element)
                .gridTemplateColumns
                .split(/\\s+/)
                .map(value => Number.parseFloat(value));
              const activeAnimations = [element, panelLayer]
                .filter(Boolean)
                .flatMap(target => target.getAnimations())
                .filter(animation => {
                  const duration = animation.effect
                    ?.getComputedTiming().duration;
                  return duration !== 0 &&
                    ['pending', 'running'].includes(animation.playState);
                });
              return {
                activeAnimationCount: activeAnimations.length,
                panelOpacity: panelLayer
                  ? Number.parseFloat(getComputedStyle(panelLayer).opacity)
                  : null,
                previewTransform: previewElement
                  ? getComputedStyle(previewElement).transform
                  : null,
                panelColumnWidth: columns[2],
                retainedThread:
                  window.__retainedAgentThread?.isConnected === true &&
                  window.__retainedAgentThread ===
                    element.querySelector('.agent-thread-layout'),
              };
            }
            """
        )
        assert reduced_motion["activeAnimationCount"] == 0, reduced_motion
        assert reduced_motion["panelOpacity"] == 1, reduced_motion
        assert reduced_motion["previewTransform"] == "none", reduced_motion
        assert reduced_motion["panelColumnWidth"] > 350, reduced_motion
        assert reduced_motion["retainedThread"], reduced_motion

        trigger.click()
        expect(trigger).to_have_attribute("aria-expanded", "false")
        page.evaluate(
            """
            () => new Promise(resolve =>
              requestAnimationFrame(() => requestAnimationFrame(resolve))
            )
            """
        )
        reduced_collapse = workspace.evaluate(
            """
            element => {
              const panelLayer = element.querySelector(
                '.agent-panel-motion-layer',
              );
              const panelColumnWidth = Number.parseFloat(
                getComputedStyle(element).gridTemplateColumns.split(/\\s+/)[2]
              );
              return {
                activeAnimationCount: [element, panelLayer]
                  .filter(Boolean)
                  .flatMap(target => target.getAnimations())
                  .filter(animation => {
                    const duration = animation.effect
                      ?.getComputedTiming().duration;
                    return duration !== 0 &&
                      ['pending', 'running'].includes(animation.playState);
                  }).length,
                panelColumnWidth,
                panelOpacity: panelLayer
                  ? Number.parseFloat(getComputedStyle(panelLayer).opacity)
                  : null,
                retainedThread:
                  window.__retainedAgentThread?.isConnected === true &&
                  window.__retainedAgentThread ===
                    element.querySelector('.agent-thread-layout'),
              };
            }
            """
        )
        assert reduced_collapse == {
            "activeAnimationCount": 0,
            "panelColumnWidth": 0,
            "panelOpacity": 0,
            "retainedThread": True,
        }
        page.emulate_media(reduced_motion="no-preference")
        page.evaluate("delete window.__retainedAgentThread")
        page.set_viewport_size({"width": 1200, "height": 900})

        narrow_layout = workspace.evaluate(
            """
            element => {
              const editor = element.querySelector(".resume-editor-panel");
              const preview = element.querySelector(".resume-preview-card");
              if (!(editor instanceof HTMLElement) ||
                  !(preview instanceof HTMLElement)) {
                throw new Error("Missing narrow resume workspace panes.");
              }
              const editorRect = editor.getBoundingClientRect();
              const previewRect = preview.getBoundingClientRect();
              return {
                editorTop: editorRect.top,
                previewTop: previewRect.top,
              };
            }
            """
        )
        assert narrow_layout["previewTop"] > narrow_layout["editorTop"]
        expect(trigger).to_be_hidden()

        actions_menu = header.get_by_role("button", name="操作", exact=True)
        actions_menu.click()
        page.get_by_role("menuitem", name="展开 AI 助手", exact=True).click()
        panel.wait_for(state="visible")
        narrow_expanded = workspace.evaluate(
            """
            element => {
              const preview = element.querySelector(".resume-preview-card");
              const panel = element.querySelector(".agent-panel-card");
              if (!(preview instanceof HTMLElement) ||
                  !(panel instanceof HTMLElement)) {
                throw new Error("Missing narrow inline Agent panel.");
              }
              const previewRect = preview.getBoundingClientRect();
              const panelRect = panel.getBoundingClientRect();
              return {
                panelBottom: panelRect.bottom,
                panelTop: panelRect.top,
                previewTop: previewRect.top,
              };
            }
            """
        )
        assert narrow_expanded["panelTop"] < narrow_expanded["previewTop"]
        assert narrow_expanded["panelBottom"] <= narrow_expanded["previewTop"]
        assert page.get_by_role("dialog").count() == 0
        assert_no_horizontal_page_overflow()

        actions_menu.click()
        page.get_by_role("menuitem", name="收起 AI 助手", exact=True).click()
        panel.wait_for(state="hidden")
        compact_dock = workspace.locator(".agent-panel-dock")
        expect(compact_dock).to_have_attribute("aria-hidden", "true")
        assert compact_dock.evaluate("element => element.inert")
        assert_no_horizontal_page_overflow()
    finally:
        context.close()


def test_resume_agent_toggle_keeps_dark_surface_opaque_during_panel_motion(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
    )
    context.add_init_script(script="localStorage.setItem('reseno-theme', 'dark');")
    page = context.new_page()

    def serve_dark_resume_workspace(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        payload["data"]["theme"] = "dark"
        route.fulfill(
            response=response,
            content_type="application/json",
            body=json.dumps(payload),
        )

    page.route(
        "**/api/workspace/pages/resume-editor",
        serve_dark_resume_workspace,
    )

    try:
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )
        assert page.locator("html").evaluate(
            """
            element => ({
              colorScheme: element.style.colorScheme,
              dark: element.classList.contains('dark'),
            })
            """
        ) == {"colorScheme": "dark", "dark": True}

        workspace = page.locator(".resume-workspace")
        trigger = workspace.locator('[data-slot="agent-panel-toggle"]')
        controls = workspace.locator('[data-slot="document-canvas-controls"]')
        trigger.wait_for(state="visible")
        controls.wait_for(state="visible")

        samples = page.evaluate(
            """
            async ([trigger, controls]) => {
              const readColor = (element, property) => {
                const canvas = document.createElement('canvas');
                canvas.width = 1;
                canvas.height = 1;
                const context = canvas.getContext('2d', {
                  willReadFrequently: true,
                });
                context.clearRect(0, 0, 1, 1);
                context.fillStyle = getComputedStyle(element)[property];
                context.fillRect(0, 0, 1, 1);
                const [red, green, blue, alpha] = context
                  .getImageData(0, 0, 1, 1)
                  .data;
                return {
                  red: red / 255,
                  green: green / 255,
                  blue: blue / 255,
                  alpha: alpha / 255,
                };
              };
              const composite = (foreground, background) => ({
                red:
                  foreground.red * foreground.alpha +
                  background.red * (1 - foreground.alpha),
                green:
                  foreground.green * foreground.alpha +
                  background.green * (1 - foreground.alpha),
                blue:
                  foreground.blue * foreground.alpha +
                  background.blue * (1 - foreground.alpha),
                alpha: 1,
              });
              const luminance = color => {
                const linear = channel =>
                  channel <= 0.04045
                    ? channel / 12.92
                    : ((channel + 0.055) / 1.055) ** 2.4;
                return (
                  0.2126 * linear(color.red) +
                  0.7152 * linear(color.green) +
                  0.0722 * linear(color.blue)
                );
              };
              const contrast = (first, second) => {
                const firstLuminance = luminance(first);
                const secondLuminance = luminance(second);
                return (
                  (Math.max(firstLuminance, secondLuminance) + 0.05) /
                  (Math.min(firstLuminance, secondLuminance) + 0.05)
                );
              };
              const white = {
                red: 1,
                green: 1,
                blue: 1,
                alpha: 1,
              };
              const readSurface = () => {
                const workspace = trigger.closest('.resume-workspace');
                const background = readColor(trigger, 'backgroundColor');
                const effectiveBackground = composite(background, white);
                const foreground = readColor(
                  trigger.querySelector('svg'),
                  'color',
                );
                const effectiveForeground = composite(
                  foreground,
                  effectiveBackground,
                );
                return {
                  controlsAlpha: readColor(
                    controls,
                    'backgroundColor',
                  ).alpha,
                  toggleAlpha: background.alpha,
                  toggleBackground: getComputedStyle(trigger).backgroundColor,
                  contrastOnWhite: contrast(
                    effectiveForeground,
                    effectiveBackground,
                  ),
                  expanded: trigger.getAttribute('aria-expanded'),
                  panelColumnWidth: workspace
                    ? Number.parseFloat(
                        getComputedStyle(workspace)
                          .gridTemplateColumns
                          .split(/\\s+/)[2],
                      )
                    : null,
                };
              };
              const frames = [];
              const startedAt = performance.now();
              const sample = now => {
                frames.push({
                  elapsed: now - startedAt,
                  ...readSurface(),
                });
              };

              window.__readAgentToggleSurface = readSurface;
              sample(startedAt);
              trigger.click();
              await new Promise(resolve => {
                const tick = now => {
                  sample(now);
                  if (now - startedAt >= 320) {
                    resolve();
                    return;
                  }
                  requestAnimationFrame(tick);
                };
                requestAnimationFrame(tick);
              });
              return frames;
            }
            """,
            [trigger.element_handle(), controls.element_handle()],
        )

        assert len(samples) >= 5, samples
        assert samples[0]["expanded"] == "false", samples
        assert samples[-1]["expanded"] == "true", samples
        assert (
            len(
                {
                    round(sample["panelColumnWidth"])
                    for sample in samples
                    if sample["expanded"] == "true"
                    and sample["panelColumnWidth"] is not None
                    and 1 < sample["panelColumnWidth"] < 359
                }
            )
            >= 3
        ), samples
        assert all(sample["controlsAlpha"] >= 0.9 for sample in samples), samples
        assert all(
            sample["toggleAlpha"] >= sample["controlsAlpha"] - 0.05
            for sample in samples
        ), samples
        assert all(sample["contrastOnWhite"] >= 3 for sample in samples), samples
        expect(trigger).to_have_attribute("aria-expanded", "true")

        trigger.hover()
        page.wait_for_timeout(200)
        hover_surface = page.evaluate(
            """
            () => {
              const result = window.__readAgentToggleSurface();
              delete window.__readAgentToggleSurface;
              return result;
            }
            """
        )
        assert hover_surface["toggleAlpha"] >= hover_surface["controlsAlpha"] - 0.05, (
            hover_surface
        )
        assert hover_surface["contrastOnWhite"] >= 3, hover_surface
    finally:
        context.close()
