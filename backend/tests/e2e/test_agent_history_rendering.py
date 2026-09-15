from __future__ import annotations

import os
from typing import Any

import pytest
from playwright.sync_api import Browser, Page, Route, expect
from playwright.sync_api import Error as PlaywrightError

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def _seed_sourced_agent_response(page: Page, frontend_url: str) -> str:
    create_response = page.request.post(
        f"{frontend_url}/api/resumes",
        data={"documentLocale": "zh"},
    )
    assert create_response.ok
    resume_id = str(create_response.json()["data"]["resume"]["id"])
    session = page.request.get(
        f"{frontend_url}/api/agent/resumes/{resume_id}/session"
    ).json()["data"]
    message_id = "assistant-sources"
    response_text = "**公开岗位样本**显示常见要求。\n\n"
    seed_response = page.request.put(
        f"{frontend_url}/api/agent/resumes/{resume_id}/session",
        data={
            "locale": "zh",
            "revision": session["revision"],
            "messages": [
                {
                    "id": "user-sources",
                    "role": "user",
                    "text": "研究 AI 前端工程师的公开要求。",
                    "createdAt": "2026-08-10T00:00:00.000Z",
                },
                {
                    "id": message_id,
                    "role": "assistant",
                    "text": response_text,
                    "createdAt": "2026-08-10T00:00:01.000Z",
                    "response": {
                        "id": message_id,
                        "role": "assistant",
                        "text": response_text,
                        "sources": [
                            {
                                "id": "source-a",
                                "title": "AI Frontend Engineer",
                                "sourceType": "web",
                                "url": "https://aiqicha.baidu.com/details/unknown",
                                "excerpt": (
                                    "Requirements include React and TypeScript."
                                ),
                            },
                            {
                                "id": "source-b",
                                "title": "Duplicate Source",
                                "sourceType": "web",
                                "url": "https://aiqicha.baidu.com/details/unknown",
                            },
                            {
                                "id": "source-c",
                                "title": "Frontend role guide",
                                "sourceType": "web",
                                "url": "https://b.example/frontend-guide",
                            },
                            {
                                "id": "source-d",
                                "title": "Frontend role sample C",
                                "sourceType": "web",
                                "url": "https://c.example/frontend-guide",
                            },
                            {
                                "id": "source-e",
                                "title": "Frontend role sample D",
                                "sourceType": "web",
                                "url": "https://d.example/frontend-guide",
                            },
                            {
                                "id": "source-f",
                                "title": "Frontend role sample E",
                                "sourceType": "web",
                                "url": "https://e.example/frontend-guide",
                            },
                        ],
                    },
                },
            ],
        },
    )
    assert seed_response.ok
    return resume_id


def _seed_long_agent_history(
    page: Page,
    frontend_url: str,
    *,
    rounds: int = 12,
) -> str:
    create_response = page.request.post(
        f"{frontend_url}/api/resumes",
        data={"documentLocale": "zh"},
    )
    assert create_response.ok
    resume_id = str(create_response.json()["data"]["resume"]["id"])
    session = page.request.get(
        f"{frontend_url}/api/agent/resumes/{resume_id}/session"
    ).json()["data"]
    messages: list[dict[str, Any]] = []

    for index in range(rounds):
        user_id = f"user-scroll-{resume_id}-{index}"
        assistant_id = f"assistant-scroll-{resume_id}-{index}"
        user_text = f"第 {index + 1} 轮：分析这份简历与目标岗位的匹配情况。"
        assistant_text = (
            f"第 {index + 1} 轮分析结果：保留已有事实，"
            "并从职责、技术栈和可验证成果三个角度说明改进方向。"
        )
        messages.extend(
            [
                {
                    "id": user_id,
                    "role": "user",
                    "text": user_text,
                    "createdAt": f"2026-08-10T00:{index * 2:02d}:00.000Z",
                },
                {
                    "id": assistant_id,
                    "role": "assistant",
                    "text": assistant_text,
                    "createdAt": f"2026-08-10T00:{index * 2 + 1:02d}:00.000Z",
                    "response": {
                        "id": assistant_id,
                        "role": "assistant",
                        "text": assistant_text,
                    },
                },
            ]
        )

    seed_response = page.request.put(
        f"{frontend_url}/api/agent/resumes/{resume_id}/session",
        data={
            "locale": "zh",
            "revision": session["revision"],
            "messages": messages,
        },
    )
    assert seed_response.ok
    return resume_id


def test_agent_history_stays_clear_without_masking_native_scrollbar(
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
        resume_id = _seed_long_agent_history(page, frontend_url)
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")

        scroll_owner = page.locator(".agent-thread-scroll")
        scroll_owner.wait_for(state="visible")
        composer_shield = page.locator('[data-slot="agent-thread-composer-shield"]')
        composer = page.locator('[data-slot="agent-composer"]')

        assert composer_shield.count() == 1
        assert composer.count() == 1
        metrics = page.locator(".agent-thread-layout").evaluate(
            """
            layout => {
              const scrollOwner = layout.querySelector('.agent-thread-scroll');
              const composerShield = layout.querySelector(
                '[data-slot="agent-thread-composer-shield"]',
              );
              const composer = layout.querySelector('[data-slot="agent-composer"]');
              const safeArea = layout.querySelector('.agent-thread-safe-area');
              if (!(scrollOwner instanceof HTMLElement) ||
                  !(composerShield instanceof HTMLElement) ||
                  !(composer instanceof HTMLElement) ||
                  !(safeArea instanceof HTMLElement)) {
                throw new Error('Missing Agent thread layout surfaces.');
              }

              const scrollStyle = getComputedStyle(scrollOwner);
              const shieldStyle = getComputedStyle(composerShield);
              const layoutStyle = getComputedStyle(layout);
              const scrollRect = scrollOwner.getBoundingClientRect();
              const shieldRect = composerShield.getBoundingClientRect();
              const composerRect = composer.getBoundingClientRect();
              const safeAreaRect = safeArea.getBoundingClientRect();
              const safeAreaStyle = getComputedStyle(safeArea);
              const contentRight =
                safeAreaRect.right - Number.parseFloat(safeAreaStyle.paddingRight);
              const midpoint = Number.parseFloat(
                layoutStyle.getPropertyValue('--agent-composer-midpoint'),
              );
              const safeGap = Number.parseFloat(
                layoutStyle.getPropertyValue('--agent-thread-safe-gap'),
              );
              const safePadding = Number.parseFloat(
                getComputedStyle(safeArea).paddingBottom,
              );

              scrollOwner.scrollTop = Math.round(
                (scrollOwner.scrollHeight - scrollOwner.clientHeight) / 2,
              );

              return {
                backgroundImage: shieldStyle.backgroundImage,
                backgroundSize: shieldStyle.backgroundSize,
                composerHeight: composerRect.height,
                contentRight,
                shieldBottom: shieldRect.bottom,
                shieldIsOutsideScrollOwner:
                  composerShield.parentElement === layout &&
                  !scrollOwner.contains(composerShield),
                shieldPointerEvents: shieldStyle.pointerEvents,
                shieldRightClearance: scrollRect.right - shieldRect.right,
                shieldRight: shieldRect.right,
                isScrollable: scrollOwner.scrollHeight > scrollOwner.clientHeight,
                maskImage: scrollStyle.maskImage,
                midpoint,
                overflowY: scrollStyle.overflowY,
                safeGap,
                safePadding,
                scrollBottom: scrollRect.bottom,
                scrollbarGutter: scrollStyle.scrollbarGutter,
                scrollTop: scrollOwner.scrollTop,
                webkitMaskImage: scrollStyle.webkitMaskImage,
              };
            }
            """
        )

        assert metrics["isScrollable"] is True
        assert metrics["scrollTop"] > 0
        assert metrics["overflowY"] == "auto"
        assert metrics["maskImage"] == "none"
        assert metrics["webkitMaskImage"] == "none"
        assert metrics["shieldIsOutsideScrollOwner"] is True
        assert metrics["shieldPointerEvents"] == "none"
        assert metrics["backgroundImage"].count("linear-gradient") == 1
        assert metrics["backgroundSize"] == f"100% {metrics['midpoint']}px"
        assert "stable" in metrics["scrollbarGutter"]
        assert metrics["shieldRightClearance"] > 0
        assert abs(metrics["shieldRight"] - metrics["contentRight"]) <= 1
        assert abs(metrics["shieldBottom"] - metrics["scrollBottom"]) <= 1
        assert abs(metrics["midpoint"] - metrics["composerHeight"] / 2) <= 1
        assert (
            abs(
                metrics["safePadding"]
                - (metrics["composerHeight"] + metrics["safeGap"])
            )
            <= 1
        )

        scroll_owner.evaluate(
            "element => { element.scrollTop = element.scrollHeight; }"
        )
        page.wait_for_function(
            """
            () => {
              const owner = document.querySelector('.agent-thread-scroll');
              return owner instanceof HTMLElement &&
                Math.abs(
                  owner.scrollHeight - owner.clientHeight - owner.scrollTop
                ) <= 1;
            }
            """
        )
    finally:
        context.close()


def test_agent_history_hydrates_over_multiple_frames(
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
    held_recovery_routes: list[Route] = []

    try:
        resume_id = _seed_long_agent_history(page, frontend_url, rounds=30)
        recovery_pattern = f"**/api/agent/resumes/{resume_id}/recovery"

        def hold_recovery(route: Route) -> None:
            held_recovery_routes.append(route)

        page.route(recovery_pattern, hold_recovery)
        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="domcontentloaded",
        )
        page.locator(
            '[data-slot="agent-panel-stable-loader"] [data-slot="agent-panel-loading"]'
        ).wait_for(
            state="visible",
            timeout=5_000,
        )
        page.wait_for_function("() => window.performance != null")
        page.evaluate(
            """
            () => {
              window.__agentHistoryFrames = [];
              let remainingFrames = 120;
              const sample = () => {
                const owner = document.querySelector('.agent-thread-scroll');
                window.__agentHistoryFrames.push({
                  bottomGap: owner instanceof HTMLElement
                    ? owner.scrollHeight - owner.clientHeight - owner.scrollTop
                    : null,
                  count: document.querySelectorAll(
                    '.agent-thread-scroll .is-user, ' +
                    '.agent-thread-scroll .is-assistant',
                  ).length,
                  hasNewest: document.body.textContent.includes(
                    '第 30 轮：分析这份简历与目标岗位的匹配情况。',
                  ),
                  hasOldest: document.body.textContent.includes(
                    '第 1 轮：分析这份简历与目标岗位的匹配情况。',
                  ),
                  time: performance.now(),
                });
                remainingFrames -= 1;
                if (remainingFrames > 0) {
                  requestAnimationFrame(sample);
                }
              };
              requestAnimationFrame(sample);
            }
            """
        )

        page.unroute(recovery_pattern, hold_recovery)
        for route in held_recovery_routes:
            try:
                route.continue_()
            except PlaywrightError:
                pass
        held_recovery_routes.clear()

        page.wait_for_function(
            """
            () => document.querySelectorAll(
              '.agent-thread-scroll .is-user, ' +
              '.agent-thread-scroll .is-assistant',
            ).length === 60
            """,
            timeout=5_000,
        )
        page.wait_for_timeout(100)
        frames = page.evaluate("() => window.__agentHistoryFrames")
        positive_frames = [frame for frame in frames if frame["count"] > 0]
        positive_counts = [frame["count"] for frame in positive_frames]

        assert positive_counts, frames
        assert positive_counts[0] < 60, frames
        assert positive_counts[-1] == 60, frames
        assert len(set(positive_counts)) >= 2, frames
        assert positive_frames[0]["hasNewest"], frames
        assert not positive_frames[0]["hasOldest"], frames
        assert any(
            frame["count"] < 60
            and frame["bottomGap"] is not None
            and abs(frame["bottomGap"]) <= 1
            for frame in positive_frames
        ), frames
        expect(
            page.get_by_text(
                "第 1 轮：分析这份简历与目标岗位的匹配情况。",
                exact=True,
            )
        ).to_be_visible()
        expect(
            page.get_by_text(
                "第 12 轮：分析这份简历与目标岗位的匹配情况。",
                exact=True,
            )
        ).to_be_visible()
        expect(
            page.get_by_text(
                "第 30 轮：分析这份简历与目标岗位的匹配情况。",
                exact=True,
            )
        ).to_be_visible()
        page.wait_for_function(
            """
            () => {
              const owner = document.querySelector('.agent-thread-scroll');
              return owner instanceof HTMLElement &&
                Math.abs(
                  owner.scrollHeight - owner.clientHeight - owner.scrollTop
                ) <= 1;
            }
            """
        )
        latest_user_message = page.locator(
            ".agent-thread-scroll .is-user",
            has_text="第 30 轮：分析这份简历与目标岗位的匹配情况。",
        )
        latest_user_message.hover()
        latest_user_message.get_by_role(
            "button",
            name="修改消息",
            exact=True,
        ).click()
        expect(latest_user_message.locator("textarea")).to_have_value(
            "第 30 轮：分析这份简历与目标岗位的匹配情况。"
        )
        latest_user_message.get_by_role(
            "button",
            name="取消",
            exact=True,
        ).click()
        expect(latest_user_message.locator("textarea")).to_have_count(0)
    finally:
        for route in held_recovery_routes:
            try:
                route.continue_()
            except PlaywrightError:
                pass
        context.close()


def test_agent_sources_render_once_after_the_response(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()
    page.add_init_script(
        """
        Object.defineProperty(navigator, "clipboard", {
          configurable: true,
          value: {
            writeText: async (value) => {
              window.__copiedSourceUrl = value;
            },
          },
        });
        """
    )

    try:
        resume_id = _seed_sourced_agent_response(page, frontend_url)
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")

        claim = page.get_by_text(
            "公开岗位样本显示常见要求。",
            exact=True,
        )
        claim.wait_for(state="visible")
        assert claim.locator('[data-streamdown="strong"]').count() == 1
        assert page.get_by_role("button", name="Sources (1)").count() == 0
        trigger = page.get_by_text("aiqicha.baidu.com +4", exact=True)
        assert trigger.count() == 1

        claim_tail_box = claim.evaluate(
            """
            (element) => {
              const walker = document.createTreeWalker(
                element,
                NodeFilter.SHOW_TEXT,
              );
              let tail = null;
              for (let node = walker.nextNode(); node; node = walker.nextNode()) {
                if (node.textContent) {
                  tail = node;
                }
              }
              const range = document.createRange();
              range.setStart(tail, tail.textContent.length - 1);
              range.setEnd(tail, tail.textContent.length);
              const rect = range.getBoundingClientRect();
              return {
                x: rect.x,
                y: rect.y,
                width: rect.width,
                height: rect.height,
              };
            }
            """
        )
        trigger_box = trigger.bounding_box()
        assert trigger_box is not None
        assert (
            abs(
                (claim_tail_box["y"] + claim_tail_box["height"] / 2)
                - (trigger_box["y"] + trigger_box["height"] / 2)
            )
            <= 4
        )
        tail_gap = trigger_box["x"] - (claim_tail_box["x"] + claim_tail_box["width"])
        assert 0 <= tail_gap <= 16

        trigger.hover()
        card = page.locator('[data-slot="hover-card-content"]')
        card.wait_for(state="visible")

        card_box = card.bounding_box()
        viewport = page.viewport_size
        assert card_box is not None
        assert viewport is not None
        assert card_box["x"] >= 12
        assert card_box["x"] + card_box["width"] <= viewport["width"] - 12

        source_url = "https://aiqicha.baidu.com/details/unknown"
        source_link = card.locator(f'a[href="{source_url}"]')
        copy_buttons = card.get_by_role(
            "button",
            name="Copy source link",
            exact=True,
        )
        copy_button = copy_buttons.first
        page.evaluate(
            """
            () => {
              window.__citationCardStates = [];
              let lastState = null;
              const record = () => {
                const content = document.querySelector(
                  '[data-slot="hover-card-content"]',
                );
                const state = content?.getAttribute("data-state") ?? "unmounted";
                if (state !== lastState) {
                  window.__citationCardStates.push(state);
                  lastState = state;
                }
              };
              record();
              new MutationObserver(record).observe(document.body, {
                attributeFilter: ["data-state"],
                attributes: true,
                childList: true,
                subtree: true,
              });
            }
            """
        )
        page.mouse.move(
            trigger_box["x"] + trigger_box["width"] / 2,
            trigger_box["y"] + trigger_box["height"] / 2,
        )
        page.mouse.move(
            trigger_box["x"] + trigger_box["width"] / 2,
            (card_box["y"] + card_box["height"] + trigger_box["y"]) / 2,
        )
        page.wait_for_timeout(60)
        gap_state = card.get_attribute("data-state") if card.count() else "unmounted"
        page.mouse.move(
            card_box["x"] + card_box["width"] / 2,
            card_box["y"] + card_box["height"] / 2,
            steps=12,
        )
        page.wait_for_timeout(280)
        arrival_state = (
            card.get_attribute("data-state") if card.count() else "unmounted"
        )
        assert {
            "arrivalState": arrival_state,
            "copyButtonCount": copy_buttons.count(),
            "cardStates": page.evaluate("window.__citationCardStates"),
            "gapState": gap_state,
            "linkCount": source_link.count(),
        } == {
            "arrivalState": "open",
            "copyButtonCount": 5,
            "cardStates": ["open"],
            "gapState": "open",
            "linkCount": 1,
        }

        copy_button.click()
        page.wait_for_function(
            "expected => window.__copiedSourceUrl === expected",
            arg=source_url,
        )
        assert source_link.get_attribute("target") == "_blank"
        assert source_link.get_attribute("rel") == "noreferrer"
        context.route(
            source_url,
            lambda route: route.fulfill(
                status=200,
                content_type="text/plain",
                body="source",
            ),
        )
        with page.expect_popup() as source_page_info:
            source_link.click()
        source_page = source_page_info.value
        source_page.wait_for_load_state("domcontentloaded")
        assert source_page.url == source_url
        source_page.close()
        trigger.hover()
        card.wait_for(state="visible")

        assert card.get_by_text("AI Frontend Engineer", exact=True).count() == 1
        expect(card.get_by_text("1/5", exact=True)).to_be_visible()
        assert page.get_by_text("Duplicate Source", exact=True).count() == 0
        assert (
            card.get_by_text(
                "Requirements include React and TypeScript.",
                exact=True,
            ).count()
            == 0
        )
        card.get_by_role("button", name="Next source", exact=True).click()
        expect(card.get_by_text("Frontend role guide", exact=True)).to_be_visible()
        expect(card.get_by_text("2/5", exact=True)).to_be_visible()
    finally:
        context.close()
