from __future__ import annotations

import os
import time
from typing import Any

import pytest
from playwright.sync_api import Browser, expect

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


@pytest.mark.browser_smoke
@pytest.mark.parametrize(
    (
        "gallery_path",
        "search_name",
        "baseline_query",
        "single_query",
        "seed_resume_count",
    ),
    [
        ("/templates", "template-search", "", "Minimal", 0),
        (
            "/resume",
            "resume-search",
            "Gallery alignment",
            "Gallery alignment 1",
            6,
        ),
    ],
)
def test_gallery_sparse_results_start_at_centered_grid_first_column(
    browser: Browser,
    workspace_servers: tuple[str, str],
    gallery_path: str,
    search_name: str,
    baseline_query: str,
    single_query: str,
    seed_resume_count: int,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 1100},
    )
    page = context.new_page()
    seeded_resume_ids: list[str] = []

    def gallery_geometry() -> dict[str, float | int]:
        return page.locator('[data-slot="gallery-grid"]').evaluate(
            """
            element => {
              const gridRect = element.getBoundingClientRect();
              const items = [...element.children].map(child =>
                child.getBoundingClientRect()
              );
              if (items.length === 0) {
                throw new Error('Expected gallery items.');
              }
              const firstRow = items.filter(
                item => Math.abs(item.top - items[0].top) <= 1
              );
              const rowTops = [];
              for (const item of items) {
                if (!rowTops.some(top => Math.abs(top - item.top) <= 1)) {
                  rowTops.push(item.top);
                }
              }
              return {
                gridLeft: gridRect.left,
                gridRight: gridRect.right,
                firstLeft: firstRow[0].left,
                lastRight: firstRow.at(-1).right,
                firstRowCount: firstRow.length,
                itemCount: items.length,
                rowCount: rowTops.length,
              };
            }
            """
        )

    try:
        for index in range(seed_resume_count):
            create_response = context.request.post(
                f"{frontend_url}/api/resumes",
                data={
                    "documentLocale": "zh",
                    "title": f"Gallery alignment {index + 1}",
                },
            )
            assert create_response.ok
            create_payload = create_response.json()
            assert create_payload["code"] == 0
            seeded_resume_ids.append(create_payload["data"]["resume"]["id"])

        page.goto(f"{frontend_url}{gallery_path}", wait_until="networkidle")
        search = page.locator(f'input[name="{search_name}"]')
        if baseline_query:
            search.fill(baseline_query)

        page.wait_for_function(
            """
            minimum => document.querySelector(
              '[data-slot="gallery-grid"]'
            )?.children.length >= minimum
            """,
            arg=max(2, seed_resume_count),
        )
        baseline = gallery_geometry()
        left_gutter = baseline["firstLeft"] - baseline["gridLeft"]
        right_gutter = baseline["gridRight"] - baseline["lastRight"]

        assert baseline["rowCount"] >= 2, baseline
        assert baseline["firstRowCount"] >= 2, baseline
        assert abs(left_gutter - right_gutter) <= 1.5, baseline

        search.fill(single_query)
        page.wait_for_function(
            """
            () => document.querySelector(
              '[data-slot="gallery-grid"]'
            )?.children.length === 1
            """
        )
        single = gallery_geometry()

        assert single["itemCount"] == 1, single
        assert abs(single["firstLeft"] - baseline["firstLeft"]) <= 1.5, {
            "baseline": baseline,
            "single": single,
        }
        assert single["gridRight"] - single["lastRight"] > 200, single
    finally:
        for resume_id in seeded_resume_ids:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


@pytest.mark.browser_smoke
def test_sidebar_reflows_gallery_cards_with_position_motion(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 1100},
    )
    page = context.new_page()
    seeded_resume_ids: list[str] = []

    def gallery_layout() -> dict[str, Any]:
        return page.locator('[data-slot="gallery-grid"]').evaluate(
            """
            grid => {
              const items = [...grid.querySelectorAll(
                ':scope > [data-gallery-item-id]'
              )];
              const rects = items.map(item => item.getBoundingClientRect());
              return {
                columns: getComputedStyle(grid).gridTemplateColumns
                  .split(' ')
                  .filter(Boolean).length,
                ids: items.map(item => item.dataset.galleryItemId),
                rowTops: [...new Set(rects.map(rect => Math.round(rect.top)))],
                activeReflows: document.getAnimations().filter(
                  animation => animation.id === 'gallery-grid-reflow'
                ).length,
              };
            }
            """
        )

    def sidebar_layout() -> dict[str, float]:
        return page.locator('[data-slot="sidebar-container"]').evaluate(
            """
            container => {
              const header = container.querySelector(
                '[data-slot="sidebar-header"]'
              );
              const logo = header?.querySelector('img')?.parentElement;
              const brand = header?.querySelector('p')?.parentElement;
              const containerRect = container.getBoundingClientRect();
              const logoRect = logo?.getBoundingClientRect();
              return {
                width: containerRect.width,
                headerHeight: header?.getBoundingClientRect().height ?? 0,
                logoSize: logoRect?.width ?? 0,
                logoCenterOffset: logoRect
                  ? logoRect.left + logoRect.width / 2
                    - (containerRect.left + containerRect.width / 2)
                  : 0,
                brandOpacity: brand
                  ? Number(getComputedStyle(brand).opacity)
                  : 0,
              };
            }
            """
        )

    try:
        for index in range(6):
            create_response = context.request.post(
                f"{frontend_url}/api/resumes",
                data={
                    "documentLocale": "zh",
                    "title": f"Sidebar motion {index + 1}",
                },
            )
            assert create_response.ok
            seeded_resume_ids.append(create_response.json()["data"]["resume"]["id"])

        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.locator('input[name="resume-search"]').fill("Sidebar motion")
        page.wait_for_function(
            """
            () => document.querySelectorAll(
              '[data-slot="gallery-grid"] > [data-gallery-item-id]'
            ).length === 6
            """
        )

        trigger = page.locator('[data-slot="sidebar-trigger"]')
        expanded = gallery_layout()
        expanded_sidebar = sidebar_layout()
        assert expanded["columns"] == 5, expanded
        assert len(expanded["rowTops"]) == 2, expanded
        assert expanded_sidebar["width"] == pytest.approx(256, abs=1)
        assert expanded_sidebar["headerHeight"] == pytest.approx(80, abs=1)
        assert expanded_sidebar["logoSize"] == pytest.approx(40, abs=1)
        assert expanded_sidebar["brandOpacity"] == pytest.approx(1, abs=0.01)

        motion = trigger.evaluate(
            """
            async trigger => {
              const sidebar = document.querySelector(
                '[data-slot="sidebar-container"]'
              );
              const item = document.querySelectorAll('[data-gallery-item-id]')[5];
              const deadline = performance.now() + 2000;
              let movingWidth = null;
              let sawReflow = false;

              trigger.click();
              do {
                await new Promise(requestAnimationFrame);
                await new Promise(resolve => setTimeout(resolve, 0));
                const width = sidebar.getBoundingClientRect().width;
                if (48 < width && width < 256) movingWidth ??= width;
                sawReflow ||= document.getAnimations().some(
                  animation => animation.id === 'gallery-grid-reflow'
                );
              } while (
                (movingWidth === null || !sawReflow)
                && performance.now() < deadline
              );

              return {
                width: movingWidth,
                sawReflow,
                sameNode: document.querySelectorAll('[data-gallery-item-id]')[5]
                  === item,
              };
            }
            """
        )
        assert motion["width"] is not None, motion
        assert 48 < motion["width"] < 256, motion
        assert motion["sawReflow"], motion
        assert motion["sameNode"], motion

        page.wait_for_timeout(320)
        collapsed = gallery_layout()
        collapsed_sidebar = sidebar_layout()
        assert collapsed["columns"] == 6, collapsed
        assert len(collapsed["rowTops"]) == 1, collapsed
        assert collapsed["activeReflows"] == 0, collapsed
        assert collapsed_sidebar["width"] == pytest.approx(48, abs=1)
        assert collapsed_sidebar["headerHeight"] == pytest.approx(64, abs=1)
        assert collapsed_sidebar["logoSize"] == pytest.approx(32, abs=1)
        assert collapsed_sidebar["logoCenterOffset"] == pytest.approx(0, abs=1)
        assert collapsed_sidebar["brandOpacity"] == pytest.approx(0, abs=0.01)

        trigger.click()
        page.wait_for_function(
            """
            () => document.getAnimations().some(
              animation => animation.id === 'gallery-grid-reflow'
            )
            """
        )
        trigger.click()
        page.wait_for_timeout(400)
        reversed_layout = gallery_layout()
        assert reversed_layout["columns"] == 6, reversed_layout
        assert reversed_layout["activeReflows"] == 0, reversed_layout

        page.emulate_media(reduced_motion="reduce")
        trigger.click()
        page.wait_for_timeout(50)
        reduced_motion_layout = gallery_layout()
        reduced_motion_sidebar = sidebar_layout()
        assert reduced_motion_layout["columns"] == 5, reduced_motion_layout
        assert reduced_motion_layout["activeReflows"] == 0, reduced_motion_layout
        assert reduced_motion_sidebar["width"] == pytest.approx(256, abs=1)
    finally:
        for resume_id in seeded_resume_ids:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


@pytest.mark.browser_smoke
def test_template_gallery_reflow_finishes_with_sidebar_motion(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 1100},
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/templates", wait_until="networkidle")
        page.wait_for_function(
            """
            () => document.querySelectorAll(
              '[data-slot="gallery-grid"] > [data-gallery-item-id]'
            ).length === 6
            """
        )

        motion_state = page.locator('[data-slot="sidebar-trigger"]').evaluate(
            """
            async trigger => {
              const sidebarGap = document.querySelector(
                '[data-slot="sidebar-gap"]'
              );
              let sawSidebarMotion = false;

              trigger.click();
              for (let index = 0; index < 60; index += 1) {
                await new Promise(requestAnimationFrame);
                const hasSidebarMotion = sidebarGap
                  .getAnimations()
                  .some(animation => animation.transitionProperty === 'width');
                sawSidebarMotion ||= hasSidebarMotion;

                if (sawSidebarMotion && !hasSidebarMotion) {
                  return {
                    sidebarFinished: true,
                    activeReflows: document.getAnimations().filter(
                      animation => animation.id === 'gallery-grid-reflow'
                    ).length,
                  };
                }
              }

              return {
                sidebarFinished: false,
                activeReflows: document.getAnimations().filter(
                  animation => animation.id === 'gallery-grid-reflow'
                ).length,
              };
            }
            """
        )

        assert motion_state["sidebarFinished"], motion_state
        assert motion_state["activeReflows"] == 0, motion_state
    finally:
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize(
    ("gallery_path", "search_name", "search_query"),
    [
        ("/resume", "resume-search", "Sparse sidebar motion"),
        ("/templates", "template-search", "Minimal"),
    ],
)
def test_sidebar_motion_keeps_sparse_gallery_cards_stable(
    browser: Browser,
    workspace_servers: tuple[str, str],
    gallery_path: str,
    search_name: str,
    search_query: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 1100},
    )
    page = context.new_page()
    resume_id: str | None = None

    def capture_motion() -> dict[str, Any]:
        return page.locator('[data-slot="sidebar-trigger"]').evaluate(
            """
            async trigger => {
              const grid = document.querySelector('[data-slot="gallery-grid"]');
              const sidebarGap = document.querySelector(
                '[data-slot="sidebar-gap"]'
              );
              const item = grid.querySelector(
                ':scope > [data-gallery-item-id]'
              );
              const frames = [];
              let sawSidebarMotion = false;

              const captureFrame = () => {
                const currentItem = grid.querySelector(
                  ':scope > [data-gallery-item-id]'
                );
                const itemRect = currentItem.getBoundingClientRect();
                const itemRects = [...grid.querySelectorAll(
                  ':scope > [data-gallery-item-id]'
                )].map(element => element.getBoundingClientRect());

                frames.push({
                  itemId: currentItem.dataset.galleryItemId,
                  sameNode: currentItem === item,
                  x: itemRect.x,
                  y: itemRect.y,
                  width: itemRect.width,
                  height: itemRect.height,
                  rowCount: new Set(
                    itemRects.map(rect => Math.round(rect.top))
                  ).size,
                  columns: getComputedStyle(grid).gridTemplateColumns
                    .split(' ')
                    .filter(Boolean).length,
                });
              };

              captureFrame();
              trigger.click();

              for (let index = 0; index < 60; index += 1) {
                await new Promise(requestAnimationFrame);
                await new Promise(resolve => setTimeout(resolve, 0));
                captureFrame();

                const hasSidebarMotion = sidebarGap
                  .getAnimations()
                  .some(animation => animation.transitionProperty === 'width');
                sawSidebarMotion ||= hasSidebarMotion;

                if (sawSidebarMotion && !hasSidebarMotion) {
                  break;
                }
              }

              return { frames, sawSidebarMotion };
            }
            """
        )

    def assert_stable_motion(result: dict[str, Any]) -> None:
        frames = result["frames"]
        assert result["sawSidebarMotion"], result
        assert len(frames) >= 2, result
        assert {frame["rowCount"] for frame in frames} == {1}, result
        assert all(frame["sameNode"] for frame in frames), result
        assert len({frame["itemId"] for frame in frames}) == 1, result
        assert len({frame["columns"] for frame in frames}) == 2, result

        for key in ("y", "width", "height"):
            values = [frame[key] for frame in frames]
            assert max(values) - min(values) <= 1, {key: values}

        x_values = [frame["x"] for frame in frames]
        assert abs(x_values[-1] - x_values[0]) > 100, x_values
        direction = 1 if x_values[-1] > x_values[0] else -1
        progress = [
            direction * (right - left)
            for left, right in zip(x_values, x_values[1:], strict=False)
        ]
        assert min(progress) >= -0.5, {"x": x_values, "progress": progress}

    try:
        if gallery_path == "/resume":
            search_query = f"{search_query} {time.time_ns()}"
            created_response = context.request.post(
                f"{frontend_url}/api/resumes",
                data={"documentLocale": "zh", "title": search_query},
            )
            assert created_response.ok
            resume_id = created_response.json()["data"]["resume"]["id"]

        page.goto(f"{frontend_url}{gallery_path}", wait_until="networkidle")
        page.locator(f'input[name="{search_name}"]').fill(search_query)

        page.wait_for_function(
            """
            () => document.querySelectorAll(
              '[data-slot="gallery-grid"] > [data-gallery-item-id]'
            ).length === 1
            """
        )

        assert_stable_motion(capture_motion())
        assert_stable_motion(capture_motion())
    finally:
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize(
    ("gallery_path", "search_name", "search_query", "seed_resume_count"),
    [
        ("/templates", None, None, 0),
        ("/resume", "resume-search", "Expand motion", 6),
    ],
)
def test_gallery_expand_motion_stays_in_phase_with_sidebar(
    browser: Browser,
    workspace_servers: tuple[str, str],
    gallery_path: str,
    search_name: str | None,
    search_query: str | None,
    seed_resume_count: int,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1992, "height": 1100},
    )
    page = context.new_page()
    seeded_resume_ids: list[str] = []

    try:
        for index in range(seed_resume_count):
            create_response = context.request.post(
                f"{frontend_url}/api/resumes",
                data={
                    "documentLocale": "zh",
                    "title": f"Expand motion {index + 1}",
                },
            )
            assert create_response.ok
            seeded_resume_ids.append(create_response.json()["data"]["resume"]["id"])

        page.goto(f"{frontend_url}{gallery_path}", wait_until="networkidle")
        if search_name and search_query:
            page.locator(f'input[name="{search_name}"]').fill(search_query)
        page.wait_for_function(
            """
            () => document.querySelectorAll(
              '[data-slot="gallery-grid"] > [data-gallery-item-id]'
            ).length === 6
            """
        )
        page.set_viewport_size({"width": 700, "height": 1100})
        expect(page.locator('[data-slot="sidebar"][data-state]')).to_have_count(0)
        page.set_viewport_size({"width": 1992, "height": 1100})
        expect(page.locator('[data-slot="sidebar"][data-state]')).to_have_count(1)
        trigger = page.locator('[data-slot="sidebar-trigger"]')
        trigger.click()
        page.wait_for_timeout(400)
        collapsed_column_count = page.locator('[data-slot="gallery-grid"]').evaluate(
            """
            grid => getComputedStyle(grid).gridTemplateColumns
              .split(' ')
              .filter(Boolean).length
            """
        )

        motion = trigger.evaluate(
            """
            async trigger => {
              const grid = document.querySelector('[data-slot="gallery-grid"]');
              const sidebarGap = document.querySelector(
                '[data-slot="sidebar-gap"]'
              );
              const frames = [];
              const initialItems = [...grid.querySelectorAll(
                ':scope > [data-gallery-item-id]'
              )];
              const initialX = initialItems.map(
                item => item.getBoundingClientRect().x
              );
              const initialSidebarWidth = sidebarGap.getBoundingClientRect().width;
              let sawSidebarMotion = false;
              let timeline = null;

              trigger.click();
              for (let index = 0; index < 60; index += 1) {
                await new Promise(requestAnimationFrame);
                await new Promise(resolve => setTimeout(resolve, 0));
                const items = [...grid.querySelectorAll(
                  ':scope > [data-gallery-item-id]'
                )];
                const sidebarAnimation = sidebarGap
                  .getAnimations()
                  .find(animation => animation.transitionProperty === 'width');
                const reflowAnimation = items[0]
                  .getAnimations()
                  .find(animation => animation.id === 'gallery-grid-reflow');
                const rects = items.map(item => item.getBoundingClientRect());
                const hasSidebarMotion = Boolean(sidebarAnimation);
                sawSidebarMotion ||= hasSidebarMotion;
                if (
                  !timeline
                  && sidebarAnimation?.startTime != null
                  && reflowAnimation?.startTime != null
                ) {
                  timeline = {
                    sidebarStartTime: sidebarAnimation.startTime,
                    reflowStartTime: reflowAnimation.startTime,
                    sidebarDuration:
                      sidebarAnimation.effect.getTiming().duration,
                    reflowDuration: reflowAnimation.effect.getTiming().duration,
                    sidebarEasing: sidebarAnimation.effect.getTiming().easing,
                    reflowEasing: reflowAnimation.effect.getTiming().easing,
                  };
                }
                frames.push({
                  reflowActive: Boolean(reflowAnimation),
                  sidebarActive: hasSidebarMotion,
                  sidebarWidth: sidebarGap.getBoundingClientRect().width,
                  columns: getComputedStyle(grid).gridTemplateColumns
                    .split(' ')
                    .filter(Boolean).length,
                  rowCount: new Set(
                    rects.map(rect => Math.round(rect.top))
                  ).size,
                  sameNodes: items.every(
                    (item, itemIndex) => item === initialItems[itemIndex]
                  ),
                  x: rects.map(rect => rect.x),
                  y: rects.map(rect => rect.y),
                  width: rects.map(rect => rect.width),
                  height: rects.map(rect => rect.height),
                });

                if (sawSidebarMotion && !hasSidebarMotion) {
                  break;
                }
              }

              return {
                frames,
                initialX,
                initialSidebarWidth,
                sawSidebarMotion,
                timeline,
              };
            }
            """
        )
        frames = motion["frames"]
        assert motion["sawSidebarMotion"], motion
        assert not frames[-1]["sidebarActive"], frames
        assert not frames[-1]["reflowActive"], frames
        assert {frame["rowCount"] for frame in frames} == {1}, frames
        assert all(frame["sameNodes"] for frame in frames), frames
        assert collapsed_column_count == 7
        assert {frame["columns"] for frame in frames} == {6}, frames
        assert motion["timeline"] is not None, motion
        timeline = motion["timeline"]
        assert abs(timeline["sidebarStartTime"] - timeline["reflowStartTime"]) <= 1, (
            timeline
        )
        assert timeline["sidebarDuration"] == timeline["reflowDuration"], timeline
        assert timeline["sidebarEasing"] == timeline["reflowEasing"], timeline

        sidebar_start = motion["initialSidebarWidth"]
        sidebar_end = frames[-1]["sidebarWidth"]
        assert sidebar_end - sidebar_start > 100, motion

        for item_index in range(6):
            for key in ("y", "width", "height"):
                values = [frame[key][item_index] for frame in frames]
                assert max(values) - min(values) <= 1, {
                    "itemIndex": item_index,
                    key: values,
                }

            x_values = [
                motion["initialX"][item_index],
                *[frame["x"][item_index] for frame in frames],
            ]
            assert abs(x_values[-1] - x_values[0]) > 100, x_values
            direction = 1 if x_values[-1] > x_values[0] else -1
            progress = [
                direction * (right - left)
                for left, right in zip(x_values, x_values[1:], strict=False)
            ]
            assert min(progress) >= -0.5, {
                "itemIndex": item_index,
                "x": x_values,
                "progress": progress,
            }

            card_distance = x_values[-1] - x_values[0]
            sidebar_distance = sidebar_end - sidebar_start
            phase_delta = [
                abs(
                    (frame["x"][item_index] - x_values[0]) / card_distance
                    - (frame["sidebarWidth"] - sidebar_start) / sidebar_distance
                )
                for frame in frames
            ]
            assert max(phase_delta) <= 0.05, {
                "itemIndex": item_index,
                "phaseDelta": phase_delta,
                "x": x_values,
                "sidebar": [
                    sidebar_start,
                    *[frame["sidebarWidth"] for frame in frames],
                ],
            }

        trigger.click()
        page.wait_for_timeout(400)
        trigger.click()
        page.wait_for_timeout(80)
        reversed_motion = trigger.evaluate(
            """
            async trigger => {
              const grid = document.querySelector('[data-slot="gallery-grid"]');
              const sidebarGap = document.querySelector(
                '[data-slot="sidebar-gap"]'
              );
              const item = grid.querySelector(
                ':scope > [data-gallery-item-id]'
              );
              const initialX = item.getBoundingClientRect().x;
              const initialSidebarWidth = sidebarGap.getBoundingClientRect().width;
              const frames = [];
              let sawSidebarMotion = false;
              let timeline = null;

              trigger.click();
              for (let index = 0; index < 60; index += 1) {
                await new Promise(requestAnimationFrame);
                await new Promise(resolve => setTimeout(resolve, 0));
                const currentItem = grid.querySelector(
                  ':scope > [data-gallery-item-id]'
                );
                const sidebarAnimation = sidebarGap
                  .getAnimations()
                  .find(animation => animation.transitionProperty === 'width');
                const reflowAnimation = currentItem
                  .getAnimations()
                  .find(animation => animation.id === 'gallery-grid-reflow');
                const hasSidebarMotion = Boolean(sidebarAnimation);
                sawSidebarMotion ||= hasSidebarMotion;
                if (
                  !timeline
                  && sidebarAnimation?.startTime != null
                  && reflowAnimation?.startTime != null
                ) {
                  timeline = {
                    sidebarStartTime: sidebarAnimation.startTime,
                    reflowStartTime: reflowAnimation.startTime,
                    sidebarDuration:
                      sidebarAnimation.effect.getTiming().duration,
                    reflowDuration: reflowAnimation.effect.getTiming().duration,
                    sidebarEasing: sidebarAnimation.effect.getTiming().easing,
                    reflowEasing: reflowAnimation.effect.getTiming().easing,
                  };
                }
                frames.push({
                  x: currentItem.getBoundingClientRect().x,
                  sidebarWidth: sidebarGap.getBoundingClientRect().width,
                  columns: getComputedStyle(grid).gridTemplateColumns
                    .split(' ')
                    .filter(Boolean).length,
                  sameNode: currentItem === item,
                  sidebarActive: hasSidebarMotion,
                  reflowActive: Boolean(reflowAnimation),
                });

                if (sawSidebarMotion && !hasSidebarMotion) {
                  break;
                }
              }

              return {
                frames,
                initialX,
                initialSidebarWidth,
                sawSidebarMotion,
                timeline,
              };
            }
            """
        )
        reversed_frames = reversed_motion["frames"]
        assert reversed_motion["sawSidebarMotion"], reversed_motion
        assert reversed_motion["timeline"] is not None, reversed_motion
        assert not reversed_frames[-1]["sidebarActive"], reversed_frames
        assert not reversed_frames[-1]["reflowActive"], reversed_frames
        assert all(frame["sameNode"] for frame in reversed_frames)
        assert {frame["columns"] for frame in reversed_frames} == {7}
        reversed_timeline = reversed_motion["timeline"]
        assert (
            abs(
                reversed_timeline["sidebarStartTime"]
                - reversed_timeline["reflowStartTime"]
            )
            <= 1
        ), reversed_timeline
        assert (
            reversed_timeline["sidebarDuration"] == reversed_timeline["reflowDuration"]
        ), reversed_timeline
        assert (
            reversed_timeline["sidebarEasing"] == reversed_timeline["reflowEasing"]
        ), reversed_timeline

        reversed_x = [
            reversed_motion["initialX"],
            *[frame["x"] for frame in reversed_frames],
        ]
        reversed_sidebar = [
            reversed_motion["initialSidebarWidth"],
            *[frame["sidebarWidth"] for frame in reversed_frames],
        ]
        assert reversed_x[0] - reversed_x[-1] > 10, reversed_x
        assert reversed_sidebar[0] - reversed_sidebar[-1] > 10, reversed_sidebar
        assert (
            max(
                right - left
                for left, right in zip(reversed_x, reversed_x[1:], strict=False)
            )
            <= 0.5
        ), reversed_x
        reversed_card_distance = reversed_x[-1] - reversed_x[0]
        reversed_sidebar_distance = reversed_sidebar[-1] - reversed_sidebar[0]
        reversed_phase_delta = [
            abs(
                (frame["x"] - reversed_x[0]) / reversed_card_distance
                - (frame["sidebarWidth"] - reversed_sidebar[0])
                / reversed_sidebar_distance
            )
            for frame in reversed_frames
        ]
        assert max(reversed_phase_delta) <= 0.05, reversed_phase_delta

        trigger.click()
        page.wait_for_function(
            """
            () => document.getAnimations().some(
              animation => animation.id === 'gallery-grid-reflow'
            )
            """
        )
        page.evaluate(
            """
            () => {
              window.__galleryReducedMotionState = null;
              matchMedia('(prefers-reduced-motion: reduce)').addEventListener(
                'change',
                () => queueMicrotask(() => {
                  const grid = document.querySelector('[data-slot="gallery-grid"]');
                  window.__galleryReducedMotionState = {
                    inlineTemplate: grid.style.gridTemplateColumns,
                    activeReflows: document.getAnimations().filter(
                      animation => animation.id === 'gallery-grid-reflow'
                    ).length,
                  };
                }),
                { once: true },
              );
            }
            """
        )
        page.emulate_media(reduced_motion="reduce")
        page.wait_for_function("window.__galleryReducedMotionState !== null")
        reduced_motion_state = page.evaluate("window.__galleryReducedMotionState")
        assert reduced_motion_state == {
            "inlineTemplate": "",
            "activeReflows": 0,
        }
    finally:
        for resume_id in seeded_resume_ids:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


@pytest.mark.browser_smoke
def test_mobile_workspace_headers_fit_and_keep_primary_actions(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="en-US",
        viewport={"width": 390, "height": 844},
    )
    page = context.new_page()

    def assert_header_fits_single_row() -> None:
        header = page.locator("#main-content > header")
        header.wait_for(state="visible")
        geometry = header.evaluate(
            """
            (element) => {
              const rect = element.getBoundingClientRect();
              const visibleChildren = [...element.children]
                .filter(child => {
                  const style = getComputedStyle(child);
                  const childRect = child.getBoundingClientRect();
                  return style.display !== 'none' &&
                    style.visibility !== 'hidden' &&
                    childRect.width > 0 && childRect.height > 0;
                })
                .map(child => {
                  const childRect = child.getBoundingClientRect();
                  return {
                    left: childRect.left,
                    right: childRect.right,
                    top: childRect.top,
                    bottom: childRect.bottom,
                  };
                });
              return {
                clientHeight: element.clientHeight,
                clientWidth: element.clientWidth,
                documentWidth: document.documentElement.scrollWidth,
                header: {
                  left: rect.left,
                  right: rect.right,
                  top: rect.top,
                  bottom: rect.bottom,
                  height: rect.height,
                },
                scrollHeight: element.scrollHeight,
                scrollWidth: element.scrollWidth,
                viewportWidth: window.innerWidth,
                visibleChildren,
              };
            }
            """
        )

        assert 63 <= geometry["header"]["height"] <= 65, geometry
        assert geometry["scrollHeight"] <= geometry["clientHeight"] + 1, geometry
        assert geometry["scrollWidth"] <= geometry["clientWidth"] + 1, geometry
        assert geometry["documentWidth"] <= geometry["viewportWidth"], geometry
        assert len(geometry["visibleChildren"]) >= 2, geometry
        assert all(
            child["left"] >= geometry["header"]["left"] - 1
            and child["right"] <= geometry["header"]["right"] + 1
            and child["top"] >= geometry["header"]["top"] - 1
            and child["bottom"] <= geometry["header"]["bottom"] + 1
            for child in geometry["visibleChildren"]
        ), geometry

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        assert_header_fits_single_row()

        gallery_header = page.locator("#main-content > header")
        gallery_menu_trigger = gallery_header.locator(
            '[data-slot="dropdown-menu-trigger"]'
        )
        expect(gallery_menu_trigger).to_be_visible()
        expect(gallery_menu_trigger).to_have_attribute("aria-haspopup", "menu")
        assert gallery_menu_trigger.get_attribute("aria-label")
        gallery_menu_trigger.click()

        gallery_menu = page.locator('[data-slot="dropdown-menu-content"]')
        expect(gallery_menu).to_be_visible()
        expect(gallery_menu.locator('[role="menuitemradio"]')).to_have_count(2)
        expect(gallery_menu.locator('[role="menuitem"]')).to_have_count(2)
        page.keyboard.press("Escape")

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.locator(".resume-preview-card article.resume-page").wait_for(
            state="visible"
        )
        assert_header_fits_single_row()

        detail_header = page.locator("#main-content > header")
        format_trigger = detail_header.locator('[data-slot="popover-trigger"]').first
        save_group = detail_header.locator('[data-slot="save-status-group"]')
        save_trigger = save_group.locator(
            ':scope > button:not([data-slot="popover-trigger"])'
        )
        history_trigger = save_group.locator('[data-slot="popover-trigger"]')
        detail_menu_trigger = detail_header.locator(
            '[data-slot="dropdown-menu-trigger"]'
        )
        expect(format_trigger).to_be_visible()
        assert format_trigger.get_attribute("aria-label")
        expect(save_trigger).to_be_visible()
        assert save_trigger.get_attribute("aria-label")
        expect(history_trigger).to_be_visible()
        assert history_trigger.get_attribute("aria-label")
        expect(detail_menu_trigger).to_be_visible()
        expect(detail_menu_trigger).to_have_attribute("aria-haspopup", "menu")

        history_trigger.focus()
        page.keyboard.press("Enter")
        version_popover = page.locator('[data-slot="popover-content"]')
        expect(version_popover).to_be_visible()
        assert version_popover.get_attribute("aria-label")
        first_version = version_popover.get_by_role("button").first
        expect(first_version).to_be_focused()
        page.keyboard.press("Enter")
        expect(version_popover).to_be_visible()
        expect(first_version).to_be_focused()

        detail_menu_trigger.click()
        detail_menu = page.locator('[data-slot="dropdown-menu-content"]')
        expect(detail_menu).to_be_visible()
        expect(detail_menu.locator('[role="menuitemradio"]')).to_have_count(2)
        assert detail_menu.locator('[role="menuitem"]').count() >= 4
        expect(
            detail_menu.locator('[data-slot="dropdown-menu-sub-trigger"]')
        ).to_have_count(1)

        page.keyboard.press("Escape")
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.locator(
            ".template-workspace .resume-preview-card article.resume-page"
        ).first.wait_for(state="visible")
        assert_header_fits_single_row()

        template_header = page.locator("#main-content > header")
        template_menu_trigger = template_header.locator(
            '[data-slot="dropdown-menu-trigger"]'
        )
        expect(template_menu_trigger).to_be_visible()
        expect(template_menu_trigger).to_have_attribute("aria-haspopup", "menu")
        assert template_menu_trigger.get_attribute("aria-label")
    finally:
        context.close()
