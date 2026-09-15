from __future__ import annotations

import json
import os
import time
from typing import Any
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Request, Route, expect
from playwright.sync_api import Error as PlaywrightError

from tests.e2e.agent_session_support import seed_pending_agent_draft
from tests.e2e.browser_support import RouteReady
from tests.e2e.browser_support import authenticated_context as _authenticated_context
from tests.e2e.workspace_network_support import ApiRequest, api_request_key

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_pending_agent_draft_page_load_stays_preview_only(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()

    try:
        pending_summary = "Pending Agent preview must never autosave."
        resume_id, detail_before, _ = seed_pending_agent_draft(
            page,
            frontend_url,
            message_id="assistant-pending-page-load",
            summary=pending_summary,
        )
        formal_resume = detail_before["resume"]["resume"]

        writes: list[ApiRequest] = []

        def record_write(request: Request) -> None:
            api_request = api_request_key(request)
            if api_request and request.method in {"PATCH", "POST", "PUT", "DELETE"}:
                writes.append(api_request)

        page.on("request", record_write)
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )
        page.get_by_role("button", name="应用剩余全部", exact=True).wait_for(
            state="visible"
        )
        assert page.get_by_text(pending_summary, exact=True).count() > 0

        # Cross the complete autosave debounce without touching either draft
        # decision. Hydration may render the candidate, but it is not a user
        # confirmation and must remain read-only.
        page.wait_for_timeout(5_500)

        assert writes == []
        detail_after = page.request.get(
            f"{frontend_url}/api/resumes/{resume_id}"
        ).json()["data"]
        session_after = page.request.get(
            f"{frontend_url}/api/agent/resumes/{resume_id}/session"
        ).json()["data"]
        assistant_response = session_after["messages"][-1]["response"]

        assert detail_after["versionId"] == detail_before["versionId"]
        assert detail_after["resume"]["resume"] == formal_resume
        assert assistant_response["draft"]["reviewItems"][0]["status"] == ("pending")
    finally:
        context.close()


def test_agent_draft_review_supports_single_item_decisions_and_motion(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    context.add_init_script(script="localStorage.setItem('reseno-theme', 'dark');")
    page = context.new_page()
    held_decision_routes: list[Route] = []

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
    page.add_init_script(
        script="""
        window.__agentReviewInitialEnterCounts = {};
        document.addEventListener('animationstart', event => {
          if (
            !(event.target instanceof HTMLElement) ||
            event.animationName !== 'resume-diff-review-enter' ||
            event.target.parentElement?.closest(
              '[data-resume-review-item-id]',
            )
          ) {
            return;
          }
          const reviewItemId = event.target.dataset.resumeReviewItemId;
          if (reviewItemId) {
            window.__agentReviewInitialEnterCounts[reviewItemId] =
              (window.__agentReviewInitialEnterCounts[reviewItemId] ?? 0) + 1;
          }
        }, true);
        """
    )

    try:
        message_id = "assistant-two-item-review"
        pending_summary = "逐项审阅保留的个人总结。"
        pending_headline = "逐项审阅后放弃的职业标题"
        resume_id, detail_before, _ = seed_pending_agent_draft(
            page,
            frontend_url,
            headline=pending_headline,
            message_id=message_id,
            summary=pending_summary,
        )
        summary_review_id = f"agent-review-edit-{message_id}"
        headline_review_id = f"agent-review-edit-{message_id}-headline"
        decision_path = (
            f"/api/agent/resumes/{resume_id}/session/messages/{message_id}/draft"
        )
        decision_pattern = f"**{decision_path}"

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        expect(page.get_by_text("2 项待确认", exact=True)).to_be_visible()
        assert page.get_by_text(pending_summary, exact=True).count() > 0
        assert page.get_by_text(pending_headline, exact=True).count() > 0

        summary_target = page.locator(
            f'[data-resume-review-item-id="{summary_review_id}"]'
        ).first
        headline_target = page.locator(
            f'[data-resume-review-item-id="{headline_review_id}"]'
        ).first
        summary_target.wait_for(state="visible")
        headline_target.wait_for(state="visible")
        page.wait_for_timeout(250)
        initial_enter_counts = page.evaluate(
            "() => window.__agentReviewInitialEnterCounts"
        )
        assert initial_enter_counts[summary_review_id] == 1
        assert initial_enter_counts[headline_review_id] == 1
        assert (
            summary_target.evaluate(
                "element => getComputedStyle(element).animationName"
            )
            == "none"
        )
        repeated_enter_animations = summary_target.evaluate(
            """
            async target => {
              let starts = 0;
              const onAnimationStart = event => {
                if (event.target === target &&
                    event.animationName === 'resume-diff-review-enter') {
                  starts += 1;
                }
              };
              target.addEventListener('animationstart', onAnimationStart);
              await new Promise(resolve => window.setTimeout(resolve, 1_000));
              target.removeEventListener('animationstart', onAnimationStart);
              return starts;
            }
            """
        )
        assert repeated_enter_animations == 0
        review_visual_signature = """
            element => {
              const style = getComputedStyle(element);
              return {
                backgroundColor: style.backgroundColor,
                boxShadow: style.boxShadow,
                outlineColor: style.outlineColor,
                outlineStyle: style.outlineStyle,
                outlineWidth: style.outlineWidth,
              };
            }
        """
        all_mode_visual_style = summary_target.evaluate(review_visual_signature)

        def install_review_transition_probe(
            retained_review_item_id: str,
            *watched_review_item_ids: str,
        ) -> None:
            page.evaluate(
                """
                ({ retainedReviewItemId, watchedReviewItemIds }) => {
                  const isTopLevelTarget = element =>
                    !element.parentElement?.closest(
                      '[data-resume-review-item-id]',
                    );
                  const findTopLevelTarget = reviewItemId =>
                    [...document.querySelectorAll(
                      `[data-resume-review-item-id="${CSS.escape(reviewItemId)}"]`,
                    )].find(isTopLevelTarget) ?? null;
                  const readHighlight = element => {
                    const style = getComputedStyle(element);
                    return {
                      backgroundColor: style.backgroundColor,
                      boxShadow: style.boxShadow,
                    };
                  };
                  const retainedTarget = findTopLevelTarget(
                    retainedReviewItemId,
                  );
                  if (!retainedTarget) {
                    throw new Error('Retained review target was not found.');
                  }
                  const baseline = readHighlight(retainedTarget);
                  const viewport = retainedTarget.closest(
                    '[data-slot="document-canvas-viewport"]',
                  );
                  const initialScrollTop = viewport?.scrollTop ?? 0;
                  const startedAt = performance.now();
                  const frames = [];
                  const scrollPositions = [];
                  const motionFrames = Object.fromEntries(
                    watchedReviewItemIds.map(reviewItemId => [reviewItemId, []]),
                  );
                  const animationStarts = Object.fromEntries(
                    watchedReviewItemIds.map(reviewItemId => [
                      reviewItemId,
                      { enter: 0, exit: 0 },
                    ]),
                  );
                  const exitAnimations = {};
                  const onAnimationStart = event => {
                    if (
                      !(event.target instanceof HTMLElement) ||
                      !isTopLevelTarget(event.target)
                    ) {
                      return;
                    }
                    const counts = animationStarts[
                      event.target.dataset.resumeReviewItemId
                    ];
                    if (!counts) {
                      return;
                    }
                    if (event.animationName === 'resume-diff-review-enter') {
                      counts.enter += 1;
                    }
                    if (event.animationName === 'resume-diff-review-exit') {
                      counts.exit += 1;
                      exitAnimations[event.target.dataset.resumeReviewItemId] = {
                        animationName: getComputedStyle(event.target).animationName,
                        reviewState: event.target.dataset.resumeReviewState,
                        isConnected: event.target.isConnected,
                      };
                    }
                  };
                  document.addEventListener(
                    'animationstart',
                    onAnimationStart,
                    true,
                  );
                  let frameId = 0;
                  const sample = () => {
                    scrollPositions.push(viewport?.scrollTop ?? 0);
                    frames.push(
                      retainedTarget.isConnected
                        ? readHighlight(retainedTarget)
                        : null,
                    );
                    const elapsed = performance.now() - startedAt;
                    for (const reviewItemId of watchedReviewItemIds) {
                      const target = findTopLevelTarget(reviewItemId);
                      if (!target) {
                        motionFrames[reviewItemId].push(null);
                        continue;
                      }
                      const style = getComputedStyle(target);
                      const targetRect = target.getBoundingClientRect();
                      const viewportRect = viewport?.getBoundingClientRect();
                      motionFrames[reviewItemId].push({
                        elapsed,
                        opacity: Number.parseFloat(style.opacity),
                        transform: style.transform,
                        withinViewport:
                          !viewportRect ||
                          (targetRect.top >= viewportRect.top &&
                            targetRect.bottom <= viewportRect.bottom),
                      });
                    }
                    frameId = requestAnimationFrame(sample);
                  };
                  frameId = requestAnimationFrame(sample);
                  window.__agentReviewTransitionProbe = {
                    finish() {
                      cancelAnimationFrame(frameId);
                      document.removeEventListener(
                        'animationstart',
                        onAnimationStart,
                        true,
                      );
                      return {
                        animationStarts,
                        exitAnimations,
                        motion: Object.fromEntries(
                          Object.entries(motionFrames).map(
                            ([reviewItemId, samples]) => {
                              const visibleSamples = samples.filter(Boolean);
                              return [
                                reviewItemId,
                                {
                                  distinctOpacities: new Set(
                                    visibleSamples.map(sample =>
                                      sample.opacity.toFixed(2),
                                    ),
                                  ).size,
                                  firstSeenMs:
                                    visibleSamples[0]?.elapsed ?? null,
                                  firstSeenWithinViewport:
                                    visibleSamples[0]?.withinViewport ?? false,
                                  minimumOpacity:
                                    visibleSamples.length > 0
                                      ? Math.min(
                                          ...visibleSamples.map(
                                            sample => sample.opacity,
                                          ),
                                        )
                                      : null,
                                },
                              ];
                            },
                          ),
                        ),
                        sameNode:
                          findTopLevelTarget(retainedReviewItemId) ===
                          retainedTarget,
                        sampledFrames: frames.length,
                        scrollDistance: Math.max(
                          ...scrollPositions.map(position =>
                            Math.abs(position - initialScrollTop),
                          ),
                        ),
                        stableHighlight: frames.every(
                          frame =>
                            frame?.backgroundColor === baseline.backgroundColor &&
                            frame.boxShadow === baseline.boxShadow,
                        ),
                      };
                    },
                  };
                }
                """,
                {
                    "retainedReviewItemId": retained_review_item_id,
                    "watchedReviewItemIds": list(watched_review_item_ids),
                },
            )

        def finish_review_transition_probe() -> dict[str, Any]:
            return page.evaluate("() => window.__agentReviewTransitionProbe.finish()")

        install_review_transition_probe(
            summary_review_id,
            summary_review_id,
            headline_review_id,
        )
        page.get_by_role("button", name="逐项查看", exact=True).click()
        expect(page.get_by_text("第 1/2 项", exact=True)).to_be_visible()
        assert page.get_by_text(pending_summary, exact=True).count() > 0
        assert page.get_by_text(pending_headline, exact=True).count() == 0
        page.wait_for_timeout(250)
        all_to_single_probe = finish_review_transition_probe()
        assert all_to_single_probe["sameNode"] is True
        assert all_to_single_probe["sampledFrames"] > 0
        assert all_to_single_probe["stableHighlight"] is True
        assert all_to_single_probe["animationStarts"][summary_review_id] == {
            "enter": 0,
            "exit": 0,
        }
        assert all_to_single_probe["animationStarts"][headline_review_id] == {
            "enter": 0,
            "exit": 1,
        }
        assert all_to_single_probe["exitAnimations"][headline_review_id] == {
            "animationName": "resume-diff-review-exit",
            "reviewState": "exiting",
            "isConnected": True,
        }

        summary_target = page.locator(
            f'[data-resume-review-item-id="{summary_review_id}"]'
        ).first
        assert summary_target.evaluate(review_visual_signature) == all_mode_visual_style
        summary_target.hover()
        expect(page.get_by_text("修改前", exact=True)).to_be_visible()
        expect(page.get_by_text("修改后", exact=True)).to_be_visible()
        comparison_colors = page.locator('[data-slot="popover-content"]').evaluate(
            """
            (popover) => {
              const rows = ['修改前', '修改后'].map(label => {
                const term = [...popover.querySelectorAll('dt')].find(
                  element => element.textContent?.trim() === label,
                );
                const value = term?.nextElementSibling;
                if (!(term instanceof HTMLElement) ||
                    !(value instanceof HTMLElement)) {
                  throw new Error(`Missing comparison row: ${label}`);
                }
                const valueStyle = getComputedStyle(value);
                return {
                  backgroundColor: valueStyle.backgroundColor,
                  borderColor: valueStyle.borderColor,
                  borderStyle: valueStyle.borderTopStyle,
                  borderWidth: valueStyle.borderTopWidth,
                  label,
                  textColor: valueStyle.color,
                };
              });
              return {
                isDark: document.documentElement.classList.contains('dark'),
                rows,
              };
            }
            """
        )
        assert comparison_colors["isDark"] is True
        assert (
            comparison_colors["rows"][0]["textColor"]
            == comparison_colors["rows"][1]["textColor"]
        )
        assert (
            comparison_colors["rows"][0]["backgroundColor"]
            == comparison_colors["rows"][1]["backgroundColor"]
        )
        assert (
            comparison_colors["rows"][0]["borderColor"]
            != comparison_colors["rows"][1]["borderColor"]
        )
        assert all(
            row["borderStyle"] == "solid" and row["borderWidth"] != "0px"
            for row in comparison_colors["rows"]
        ), comparison_colors
        assert (
            comparison_colors["rows"][0]["borderWidth"]
            == comparison_colors["rows"][1]["borderWidth"]
        )
        assert summary_target.evaluate(review_visual_signature) == all_mode_visual_style

        review_all_button = page.get_by_role("button", name="全部", exact=True)
        install_review_transition_probe(
            summary_review_id,
            summary_review_id,
            headline_review_id,
        )
        review_all_button.click()
        expect(page.get_by_text("2 项待确认", exact=True)).to_be_visible()
        assert page.get_by_text(pending_summary, exact=True).count() > 0
        assert page.get_by_text(pending_headline, exact=True).count() > 0
        page.wait_for_timeout(350)
        single_to_all_probe = finish_review_transition_probe()
        assert single_to_all_probe["sameNode"] is True
        assert single_to_all_probe["sampledFrames"] > 0
        assert single_to_all_probe["stableHighlight"] is True
        assert single_to_all_probe["animationStarts"][summary_review_id] == {
            "enter": 0,
            "exit": 0,
        }
        assert single_to_all_probe["animationStarts"][headline_review_id] == {
            "enter": 1,
            "exit": 0,
        }
        assert single_to_all_probe["motion"][headline_review_id]["minimumOpacity"] < 0.5
        assert (
            single_to_all_probe["motion"][headline_review_id]["distinctOpacities"] >= 3
        )

        page.get_by_role("button", name="逐项查看", exact=True).click()
        expect(page.get_by_text("第 1/2 项", exact=True)).to_be_visible()
        assert page.get_by_text(pending_summary, exact=True).count() > 0
        assert page.get_by_text(pending_headline, exact=True).count() == 0
        page.wait_for_timeout(250)
        review_all_button = page.get_by_role("button", name="全部", exact=True)
        page.locator('[data-slot="document-canvas-viewport"]').evaluate(
            "viewport => { viewport.scrollTop = viewport.scrollHeight; }"
        )
        install_review_transition_probe(
            summary_review_id,
            summary_review_id,
            headline_review_id,
        )
        review_all_button.evaluate(
            """
            button => {
              const baselineOpacity = Number.parseFloat(
                getComputedStyle(button).opacity,
              );
              let minimumOpacity = baselineOpacity;
              let opacityTransitionStarts = 0;
              let sawDisabled = button.disabled;
              const onTransitionStart = event => {
                if (event.target === button && event.propertyName === 'opacity') {
                  opacityTransitionStarts += 1;
                }
              };
              button.addEventListener('transitionstart', onTransitionStart);
              let frameId = 0;
              const sample = () => {
                minimumOpacity = Math.min(
                  minimumOpacity,
                  Number.parseFloat(getComputedStyle(button).opacity),
                );
                sawDisabled ||= button.disabled;
                frameId = requestAnimationFrame(sample);
              };
              frameId = requestAnimationFrame(sample);
              window.__agentReviewAllButtonProbe = {
                finish(currentButton) {
                  cancelAnimationFrame(frameId);
                  button.removeEventListener('transitionstart', onTransitionStart);
                  return {
                    baselineOpacity,
                    minimumOpacity,
                    opacityTransitionStarts,
                    sameButton: currentButton === button,
                    sawDisabled,
                  };
                },
              };
            }
            """
        )
        page.get_by_role("button", name="下一项修改", exact=True).click()
        expect(page.get_by_text("第 2/2 项", exact=True)).to_be_visible()
        assert page.get_by_text(pending_headline, exact=True).count() > 0
        assert page.get_by_text(pending_summary, exact=True).count() == 0
        page.wait_for_timeout(350)
        review_all_button_probe = review_all_button.evaluate(
            """
            button => window.__agentReviewAllButtonProbe.finish(button)
            """
        )
        assert review_all_button_probe["sameButton"] is True
        assert review_all_button_probe["sawDisabled"] is False
        assert review_all_button_probe["baselineOpacity"] == pytest.approx(1)
        assert review_all_button_probe["minimumOpacity"] == pytest.approx(1)
        assert review_all_button_probe["opacityTransitionStarts"] == 0
        single_item_probe = finish_review_transition_probe()
        assert single_item_probe["animationStarts"][summary_review_id] == {
            "enter": 0,
            "exit": 0,
        }
        assert single_item_probe["animationStarts"][headline_review_id] == {
            "enter": 1,
            "exit": 0,
        }
        assert single_item_probe["motion"][headline_review_id]["firstSeenMs"] < 120
        assert single_item_probe["motion"][headline_review_id]["minimumOpacity"] < 0.5
        assert single_item_probe["motion"][headline_review_id]["distinctOpacities"] >= 3
        assert (
            single_item_probe["motion"][headline_review_id]["firstSeenWithinViewport"]
            is True
        )
        assert single_item_probe["scrollDistance"] > 2

        def hold_decision(route: Route) -> None:
            held_decision_routes.append(route)

        page.route(decision_pattern, hold_decision, times=1)
        page.get_by_role("button", name="放弃此项", exact=True).click()
        page.locator(".resume-editor-panel").wait_for(state="visible")
        expect(page.locator(".resume-editor-panel")).to_have_attribute("inert", "")
        page.wait_for_timeout(100)
        assert held_decision_routes
        headline_target = page.locator(
            f'[data-resume-review-item-id="{headline_review_id}"]'
        ).first
        expect(headline_target).to_have_attribute(
            "data-resume-review-state",
            "exiting",
        )

        pending_decision_routes = held_decision_routes.copy()
        held_decision_routes.clear()
        for route in pending_decision_routes:
            route.continue_()
        expect(page.get_by_text("第 1/1 项", exact=True)).to_be_visible()
        assert page.get_by_text(pending_summary, exact=True).count() > 0
        assert page.get_by_text(pending_headline, exact=True).count() == 0

        page.get_by_role("button", name="应用此项", exact=True).click()
        exiting_dock = page.locator(
            '[data-slot="agent-draft-review-dock"][data-presence="exiting"]'
        )
        exiting_dock.wait_for(state="visible")
        assert (
            exiting_dock.evaluate("element => getComputedStyle(element).animationName")
            == "agent-draft-review-dock-exit"
        )
        expect(page.get_by_text("已应用 1 项，已放弃 1 项", exact=True)).to_be_visible()

        detail_after = page.request.get(
            f"{frontend_url}/api/resumes/{resume_id}"
        ).json()["data"]
        assert detail_after["resume"]["resume"]["basic"]["summary"] == (pending_summary)
        assert (
            detail_after["resume"]["resume"]["basic"]["headline"]
            == (detail_before["resume"]["resume"]["basic"]["headline"])
        )
        session_after = page.request.get(
            f"{frontend_url}/api/agent/resumes/{resume_id}/session"
        ).json()["data"]
        statuses = {
            item["id"]: item["status"]
            for item in session_after["messages"][-1]["response"]["draft"][
                "reviewItems"
            ]
        }
        assert statuses == {
            summary_review_id: "applied",
            headline_review_id: "discarded",
        }
    finally:
        for route in held_decision_routes:
            route.continue_()
        context.close()


def test_pending_agent_draft_waits_for_complete_session_hydration(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()

    try:
        pending_summary = "Pending draft restored after complete hydration."
        resume_id, _, _ = seed_pending_agent_draft(
            page,
            frontend_url,
            message_id="assistant-pending-hydration",
            summary=pending_summary,
        )
        held_recovery_routes: list[Route] = []
        recovery_ready = RouteReady()
        recovery_pattern = f"**/api/agent/resumes/{resume_id}/recovery"

        def hold_recovery(route: Route) -> None:
            held_recovery_routes.append(route)
            recovery_ready.set()

        page.route(recovery_pattern, hold_recovery)
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="domcontentloaded",
        )

        loading = page.get_by_text("正在加载 Agent 对话…", exact=True)
        loading.wait_for(state="visible")
        recovery_ready.wait(page)
        assert held_recovery_routes
        expect(loading).to_be_visible()
        empty_prompt = page.get_by_text("我可以帮你润色经历、调整简历结构", exact=True)
        assert empty_prompt.count() == 0
        assert page.get_by_role("button", name="应用剩余全部", exact=True).count() == 0
        assert page.get_by_role("button", name="放弃剩余全部", exact=True).count() == 0

        page.unroute(recovery_pattern, hold_recovery)
        for route in held_recovery_routes:
            try:
                route.continue_()
            except PlaywrightError:
                # React Strict Mode may already have aborted an earlier owner.
                pass
        held_recovery_routes.clear()
        loading.wait_for(state="hidden")
        page.get_by_role("button", name="应用剩余全部", exact=True).wait_for(
            state="visible"
        )
        assert page.get_by_role("button", name="放弃剩余全部", exact=True).count() == 1
        assert page.get_by_text(pending_summary, exact=True).count() > 0
    finally:
        for route in held_recovery_routes:
            route.continue_()
        context.close()


@pytest.mark.parametrize(
    ("decision_button_name", "decision_id"),
    [("应用剩余全部", "apply"), ("放弃剩余全部", "discard")],
)
def test_agent_draft_decision_revision_is_used_by_next_prompt(
    browser: Browser,
    workspace_servers: tuple[str, str],
    decision_button_name: str,
    decision_id: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()

    try:
        model_response = page.request.post(
            f"{frontend_url}/api/model-configs",
            data={
                "id": "llm-agent-draft-revision",
                "provider": "openai",
                "providerKind": "custom",
                "apiFamily": "openai_compatible_chat",
                "nickname": "Agent draft revision",
                "apiKey": "test-key",
                "model": "test-model",
                "apiUrl": "http://127.0.0.1:9/v1",
                "temperature": None,
                "topP": None,
                "maxTokens": 512,
            },
        )
        assert model_response.ok
        message_id = f"assistant-{decision_id}-next-prompt"
        resume_id, _, _ = seed_pending_agent_draft(
            page,
            frontend_url,
            message_id=message_id,
            summary="Discard this draft before the next prompt.",
        )
        decision_path = (
            f"/api/agent/resumes/{resume_id}/session/messages/{message_id}/draft"
        )

        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )
        decision_button = page.get_by_role(
            "button",
            name=decision_button_name,
            exact=True,
        )
        decision_button.wait_for(state="visible")
        with page.expect_response(
            lambda response: (
                response.request.method == "PATCH"
                and urlparse(response.url).path == decision_path
            )
        ) as decision_response_info:
            decision_button.click()

        decision_response = decision_response_info.value
        assert decision_response.ok
        decision_session = decision_response.json()["data"]["session"]
        decision_button.wait_for(state="hidden")

        prompt = page.get_by_role(
            "textbox",
            name="你想了解什么？",
            exact=True,
        )
        prompt.fill("继续检查这份简历。")
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlparse(response.url).path == "/api/agent/chat"
            )
        ) as chat_response_info:
            with page.expect_request(
                lambda request: (
                    request.method == "POST"
                    and urlparse(request.url).path == "/api/agent/chat"
                )
            ) as chat_request_info:
                prompt.press("Enter")

        chat_request = chat_request_info.value
        chat_response = chat_response_info.value
        request_payload = json.loads(chat_request.post_data or "{}")
        assert request_payload["expectedRevision"] == decision_session["revision"]
        assert chat_response.status == 200
    finally:
        context.close()


def test_agent_draft_decision_blocks_a_concurrent_prompt(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()
    held_decision_routes: list[Route] = []
    held_chat_routes: list[Route] = []

    def hold_decision(route: Route) -> None:
        held_decision_routes.append(route)

    def hold_chat(route: Route) -> None:
        held_chat_routes.append(route)

    try:
        model_response = page.request.post(
            f"{frontend_url}/api/model-configs",
            data={
                "id": "llm-agent-draft-decision-gate",
                "provider": "openai",
                "providerKind": "custom",
                "apiFamily": "openai_compatible_chat",
                "nickname": "Agent draft decision gate",
                "apiKey": "test-key",
                "model": "test-model",
                "apiUrl": "http://127.0.0.1:9/v1",
                "temperature": None,
                "topP": None,
                "maxTokens": 512,
            },
        )
        assert model_response.ok
        message_id = "assistant-decision-gates-prompt"
        resume_id, _, _ = seed_pending_agent_draft(
            page,
            frontend_url,
            message_id=message_id,
            summary="Keep the next prompt behind this decision.",
        )
        decision_path = (
            f"/api/agent/resumes/{resume_id}/session/messages/{message_id}/draft"
        )
        decision_pattern = f"**{decision_path}"
        chat_pattern = "**/api/agent/chat"

        page.route(decision_pattern, hold_decision)
        page.route(chat_pattern, hold_chat)
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )
        prompt = page.get_by_role(
            "textbox",
            name="你想了解什么？",
            exact=True,
        )
        prompt.fill("这条消息必须等草稿决策完成。")
        discard_button = page.get_by_role(
            "button",
            name="放弃剩余全部",
            exact=True,
        )
        discard_button.click()
        page.wait_for_timeout(100)
        assert held_decision_routes

        prompt.evaluate("element => element.form?.requestSubmit()")
        page.wait_for_timeout(600)

        assert held_chat_routes == []
        assert prompt.is_disabled()

        page.unroute(decision_pattern, hold_decision)
        pending_decision_routes = held_decision_routes.copy()
        held_decision_routes.clear()
        for route in pending_decision_routes:
            route.continue_()
        discard_button.wait_for(state="hidden")
        expect(prompt).to_be_enabled()
    finally:
        page.unroute("**/api/agent/chat", hold_chat)
        for route in held_chat_routes:
            route.abort()
        for route in held_decision_routes:
            route.continue_()
        context.close()


def test_queued_agent_draft_apply_stops_after_save_owner_unmounts(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()

    try:
        message_id = "assistant-queued-apply-unmount"
        resume_id, detail_before, candidate_resume = seed_pending_agent_draft(
            page,
            frontend_url,
            message_id=message_id,
            summary="A queued apply must stop when its route owner unmounts.",
        )
        review_item_id = f"agent-review-edit-{message_id}"

        writes: list[ApiRequest] = []

        def delay_save_and_record_writes(route: Route) -> None:
            request = route.request
            api_request = api_request_key(request)
            if api_request and request.method in {"PATCH", "POST", "PUT", "DELETE"}:
                writes.append(api_request)
            if (
                request.method == "PUT"
                and urlparse(request.url).path == f"/api/resumes/{resume_id}"
            ):
                time.sleep(0.8)
            route.continue_()

        page.route("**/api/**", delay_save_and_record_writes)
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )

        submitted_resume = json.loads(json.dumps(detail_before["resume"]))
        submitted_resume["title"] = "Save in flight before route unmount"
        page.evaluate(
            """
            async ({ detailBefore, resumeId, submittedResume }) => {
              const ReactModule = await import('/@id/react');
              const ReactDomModule = await import('/@id/react-dom/client');
              const React = ReactModule.default ?? ReactModule;
              const createRoot =
                ReactDomModule.createRoot ?? ReactDomModule.default?.createRoot;
              const { useResumeDetailSave } = await import(
                '/src/components/workspace/use-resume-detail-save.ts'
              );
              const host = document.createElement('div');
              host.hidden = true;
              document.body.append(host);
              if (typeof createRoot !== 'function') {
                throw new Error('React createRoot is unavailable.');
              }
              const root = createRoot(host);
              window.__queuedApplyHarness = { controller: null, root };

              function Harness() {
                const controller = useResumeDetailSave({
                  getSnapshot: () => submittedResume,
                  initialCheckpoint: {
                    savedAt: detailBefore.savedAt,
                    versionId: detailBefore.versionId,
                  },
                  initialResume: detailBefore.resume,
                  isLoading: true,
                  liveFingerprint: 'queued-apply-harness',
                  liveResume: submittedResume,
                  messages: { loadError: 'load error' },
                  onAdoptSavedResume: () => undefined,
                  onHydrateResume: () => undefined,
                  resumeId,
                });
                window.__queuedApplyHarness.controller = controller;
                return null;
              }

              root.render(React.createElement(Harness));
              await new Promise((resolve) => requestAnimationFrame(resolve));
            }
            """,
            {
                "detailBefore": detail_before,
                "resumeId": resume_id,
                "submittedResume": submitted_resume,
            },
        )
        page.evaluate(
            """
            ({ candidateResume, messageId, reviewItemId }) => {
              const harness = window.__queuedApplyHarness;
              if (!harness?.controller) {
                throw new Error('The save lifecycle harness is unavailable.');
              }
              const save = harness.controller.save('autosave');
              const decision = harness.controller.resolveAgentDraftReview(
                messageId,
                candidateResume,
                [reviewItemId],
                'applied',
              );
              window.__queuedApplyPromises = [save, decision];
              window.setTimeout(() => harness.root.unmount(), 50);
            }
            """,
            {
                "candidateResume": candidate_resume,
                "messageId": message_id,
                "reviewItemId": review_item_id,
            },
        )
        page.wait_for_timeout(1_800)

        draft_patch = (
            "PATCH",
            f"/api/agent/resumes/{resume_id}/session/messages/{message_id}/draft",
        )
        assert draft_patch not in writes, writes
        session_after = page.request.get(
            f"{frontend_url}/api/agent/resumes/{resume_id}/session"
        ).json()["data"]
        assert (
            session_after["messages"][-1]["response"]["draft"]["reviewItems"][0][
                "status"
            ]
            == "pending"
        )
    finally:
        context.close()
