from __future__ import annotations

import json
import os
import time
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Request, Route, expect
from playwright.sync_api import Error as PlaywrightError

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


@pytest.mark.browser_smoke
def test_resume_version_switch_keeps_workspace_and_history_popover_stable(
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
    resume_id: str | None = None
    held_version_routes: list[Route] = []
    resume_save_requests: list[Request] = []

    def record_resume_save(request: Request) -> None:
        if (
            request.method == "PUT"
            and urlparse(request.url).path == f"/api/resumes/{resume_id}"
        ):
            resume_save_requests.append(request)

    page.on("request", record_resume_save)

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": "Version switch stability regression",
            },
        )
        assert create_response.ok
        created = create_response.json()["data"]["resume"]
        resume_id = str(created["id"])
        initial_name = str(created["resume"]["basic"]["name"])
        second_name = "Version Switch Current Checkpoint"
        second_resume = json.loads(json.dumps(created["resume"]))
        second_resume["basic"]["name"] = second_name
        checkpoint_response = page.request.put(
            f"{frontend_url}/api/resumes/{resume_id}?saveMode=checkpoint",
            data={
                "documentLocale": created["documentLocale"],
                "jobBrief": created["jobBrief"],
                "resume": second_resume,
                "template": created["template"],
                "templateSettings": created["templateSettings"],
                "title": created["title"],
                "typography": created["typography"],
            },
        )
        assert checkpoint_response.ok
        assert checkpoint_response.json()["data"]["versionId"] != "1"

        page.goto(
            f"{frontend_url}/resume/{resume_id}",
            wait_until="networkidle",
        )
        preview = page.locator(
            ".resume-preview-card article.resume-page",
        )
        expect(preview).to_contain_text(second_name)

        history_trigger = page.locator(
            '[data-slot="save-status-group"] [data-slot="popover-trigger"]'
        )
        history_trigger.click()
        version_popover = page.locator(
            '[data-slot="popover-content"][aria-label="历史版本"]'
        )
        expect(version_popover).to_be_visible()
        version_buttons = version_popover.get_by_role("button")
        expect(version_buttons).to_have_count(2)
        historical_version = version_buttons.last
        historical_version.hover()

        before = page.evaluate(
            """
            (popover) => {
              const preview = document.querySelector(
                '.resume-preview-card article.resume-page',
              );
              const editor = document.querySelector('.resume-editor-panel');
              if (!(preview instanceof HTMLElement) ||
                  !(editor instanceof HTMLElement) ||
                  !(popover instanceof HTMLElement)) {
                throw new Error('Missing version switch stability surface.');
              }
              window.__versionSwitchPreview = preview;
              window.__versionSwitchEditor = editor;
              window.__versionSwitchPopover = popover;
              const previewRect = preview.getBoundingClientRect();
              const editorRect = editor.getBoundingClientRect();
              return {
                editor: {
                  height: editorRect.height,
                  width: editorRect.width,
                  x: editorRect.x,
                  y: editorRect.y,
                },
                preview: {
                  height: previewRect.height,
                  width: previewRect.width,
                  x: previewRect.x,
                  y: previewRect.y,
                },
              };
            }
            """,
            version_popover.element_handle(),
        )

        version_pattern = f"**/api/resumes/{resume_id}/versions/1"

        def hold_version(route: Route) -> None:
            held_version_routes.append(route)

        page.route(version_pattern, hold_version)
        historical_version.click()
        deadline = time.monotonic() + 3
        while not held_version_routes and time.monotonic() < deadline:
            page.wait_for_timeout(20)
        assert held_version_routes
        page.wait_for_timeout(250)

        expect(version_popover).to_be_visible()
        expect(historical_version).to_be_visible()
        assert historical_version.evaluate("element => element.matches(':hover')")
        during = page.evaluate(
            """
            () => {
              const preview = window.__versionSwitchPreview;
              const editor = window.__versionSwitchEditor;
              const popover = window.__versionSwitchPopover;
              const previewRect = preview?.getBoundingClientRect();
              const editorRect = editor?.getBoundingClientRect();
              return {
                editorConnected: editor?.isConnected === true,
                popoverConnected: popover?.isConnected === true,
                previewConnected: preview?.isConnected === true,
                skeletonCount: document.querySelectorAll(
                  '[data-slot="workspace-panel-skeleton"], ' +
                  '[data-slot="workspace-preview-skeleton"]',
                ).length,
                editor: editorRect ? {
                  height: editorRect.height,
                  width: editorRect.width,
                  x: editorRect.x,
                  y: editorRect.y,
                } : null,
                preview: previewRect ? {
                  height: previewRect.height,
                  width: previewRect.width,
                  x: previewRect.x,
                  y: previewRect.y,
                } : null,
              };
            }
            """
        )
        assert during["editorConnected"], during
        assert during["popoverConnected"], during
        assert during["previewConnected"], during
        assert during["skeletonCount"] == 0, during
        assert during["editor"] == pytest.approx(before["editor"], abs=1), during
        assert during["preview"] == pytest.approx(before["preview"], abs=1), during

        for route in held_version_routes:
            route.continue_()
        held_version_routes.clear()
        page.unroute(version_pattern, hold_version)

        expect(preview).to_contain_text(initial_name)
        expect(version_popover).to_be_visible()
        expect(historical_version).to_be_visible()
        assert historical_version.evaluate("element => element.matches(':hover')")
        expect(page.locator('[data-slot="save-status-announcement"]')).to_contain_text(
            "已保存"
        )
        page.wait_for_timeout(5_500)
        assert resume_save_requests == []
        current_detail = page.request.get(
            f"{frontend_url}/api/resumes/{resume_id}"
        ).json()["data"]
        assert (
            current_detail["versionId"]
            == checkpoint_response.json()["data"]["versionId"]
        )
        assert current_detail["resume"]["resume"]["basic"]["name"] == second_name
    finally:
        for route in held_version_routes:
            try:
                route.continue_()
            except PlaywrightError:
                pass
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


@pytest.mark.parametrize(
    ("template_id", "item_count"),
    [("minimal", 80), ("compact", 80)],
)
def test_resume_pagination_does_not_split_text_lines(
    browser: Browser,
    workspace_servers: tuple[str, str],
    template_id: str,
    item_count: int,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()
    resume_id: str | None = None

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": f"{template_id} pagination line break regression",
                "template": template_id,
            },
        )
        assert create_response.ok
        created = create_response.json()["data"]["resume"]
        resume_id = created["id"]
        list_html = (
            "<ul>"
            + "".join(
                f"<li>Skill {index:02d} React</li>" for index in range(item_count)
            )
            + "</ul>"
        )
        save_response = page.request.put(
            f"{frontend_url}/api/resumes/{resume_id}",
            data={
                "title": created["title"],
                "documentLocale": created["documentLocale"],
                "resume": {
                    **created["resume"],
                    "basic": {
                        **created["resume"]["basic"],
                        "name": "",
                        "headline": "",
                        "phone": "",
                        "email": "",
                        "location": "",
                        "avatar": "",
                        "summary": "",
                    },
                    "sections": [
                        {
                            "id": "pagination-skills",
                            "kind": "simple_list",
                            "title": "Skills",
                            "items": [
                                {
                                    "id": "pagination-skills-content",
                                    "content": list_html,
                                }
                            ],
                        }
                    ],
                },
                "jobBrief": created["jobBrief"],
                "typography": {"fontFamily": "inter", "fontSize": 16},
                "template": created["template"],
                "templateSettings": created["templateSettings"],
            },
        )
        assert save_response.ok

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        preview = page.locator(
            ".resume-workspace .resume-preview-card "
            '[data-resume-pagination-ready="true"]'
        )
        preview.wait_for(state="visible")
        line_geometry_script = """
            stack => {
              const violations = [];
              const pageShells = [...stack.querySelectorAll('.resume-page-shell')];

              pageShells.forEach((shell, pageIndex) => {
                const viewport = shell.querySelector(
                  '.resume-page-content-viewport, .resume-page-flow-viewport',
                );
                const fragment = shell.querySelector(
                  '.resume-page-content-fragment, .resume-page-fragment',
                );
                if (!(viewport instanceof HTMLElement) ||
                    !(fragment instanceof HTMLElement)) {
                  throw new Error('Resume page slice is unavailable.');
                }

                const viewportRect = viewport.getBoundingClientRect();
                const walker = document.createTreeWalker(
                  fragment,
                  NodeFilter.SHOW_TEXT,
                  {
                    acceptNode(node) {
                      return node.textContent?.trim()
                        ? NodeFilter.FILTER_ACCEPT
                        : NodeFilter.FILTER_REJECT;
                    },
                  },
                );
                const range = document.createRange();
                let textNode = walker.nextNode();

                while (textNode) {
                  range.selectNodeContents(textNode);
                  for (const rect of range.getClientRects()) {
                    const intersects =
                      rect.bottom > viewportRect.top + 0.5 &&
                      rect.top < viewportRect.bottom - 0.5;
                    const contained =
                      rect.top >= viewportRect.top - 1 &&
                      rect.bottom <= viewportRect.bottom + 1;
                    if (intersects && !contained) {
                      violations.push({
                        page: pageIndex + 1,
                        text: textNode.textContent,
                        lineTop: rect.top,
                        lineBottom: rect.bottom,
                        viewportTop: viewportRect.top,
                        viewportBottom: viewportRect.bottom,
                      });
                    }
                  }
                  textNode = walker.nextNode();
                }
              });

              return { pageCount: pageShells.length, violations };
            }
            """
        geometry = preview.evaluate(line_geometry_script)
        assert geometry["pageCount"] >= 2, geometry
        assert geometry["violations"] == [], geometry

        canvas_page = page.locator('[data-slot="document-canvas-page"]')
        canvas_viewport = page.locator(
            '.resume-workspace [data-slot="document-canvas-viewport"]'
        )
        expect(canvas_page).to_have_text(f"Page 1 / {geometry['pageCount']}")
        canvas_viewport.evaluate(
            "element => { element.scrollTop = element.scrollHeight; }"
        )
        expect(canvas_page).to_have_text(
            f"Page {geometry['pageCount']} / {geometry['pageCount']}"
        )
        canvas_viewport.evaluate("element => { element.scrollTop = 0; }")
        expect(canvas_page).to_have_text(f"Page 1 / {geometry['pageCount']}")

        if template_id == "minimal":
            format_button = page.locator(
                "header button:has(svg.lucide-sliders-horizontal)"
            )
            format_button.click()
            format_popover = page.locator('[data-slot="popover-content"]')
            font_size_select = format_popover.get_by_role("combobox").nth(2)
            font_size_select.click()
            larger_font_option = page.get_by_role(
                "option",
                name="15 pt",
                exact=True,
            )
            larger_font_option.wait_for(state="visible")
            page.evaluate(
                """() => {
                  const inspect = """
                + line_geometry_script
                + """;
                  const state = {
                    done: false,
                    frames: 0,
                    hiddenPendingFrames: [],
                    sawPending: false,
                    settled: false,
                    timedOut: false,
                    violations: [],
                  };
                  window.__resumePaginationTransition = state;

                  const sampleFrame = () => {
                    const stack = document.querySelector(
                      '.resume-workspace .resume-preview-card '
                      + '[data-resume-page-count]',
                    );
                    state.frames += 1;

                    if (stack instanceof HTMLElement) {
                      const ready =
                        stack.dataset.resumePaginationReady === 'true';
                      state.sawPending ||= !ready;
                      const firstPage = stack.querySelector('.resume-page-shell');
                      const pagesVisible = stack.checkVisibility({
                        checkOpacity: true,
                        checkVisibilityCSS: true,
                      }) && firstPage?.checkVisibility({
                        checkOpacity: true,
                        checkVisibilityCSS: true,
                      });
                      if (!ready && !pagesVisible) {
                        state.hiddenPendingFrames.push(state.frames);
                      }
                      const geometry = inspect(stack);

                      if (state.violations.length < 20) {
                        state.violations.push(
                          ...geometry.violations.slice(
                            0,
                            20 - state.violations.length,
                          ).map(violation => ({
                            ...violation,
                            frame: state.frames,
                            ready,
                          })),
                        );
                      }

                      if (state.sawPending && ready) {
                        state.settled = true;
                        state.done = true;
                        return;
                      }
                    }

                    if (state.frames >= 180) {
                      state.timedOut = true;
                      state.done = true;
                      return;
                    }
                    requestAnimationFrame(sampleFrame);
                  };

                  requestAnimationFrame(sampleFrame);
                }"""
            )
            larger_font_option.click()
            page.wait_for_function("window.__resumePaginationTransition?.done === true")
            transition = page.evaluate("window.__resumePaginationTransition")

            assert transition["sawPending"], transition
            assert transition["settled"], transition
            assert not transition["timedOut"], transition
            assert transition["hiddenPendingFrames"] == [], transition
            assert transition["violations"] == [], transition

        page.goto(
            f"{frontend_url}/pdf-export?resumeId={resume_id}&documentLocale=zh",
            wait_until="networkidle",
        )
        page.locator('main[data-pdf-ready="true"]').wait_for(state="visible")
        page.emulate_media(media="print")
        export_preview = page.locator(
            '.pdf-export-page [data-resume-pagination-ready="true"]'
        )
        export_geometry = export_preview.evaluate(line_geometry_script)

        assert export_geometry["pageCount"] >= 2, export_geometry
        assert export_geometry["violations"] == [], export_geometry
    finally:
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()
