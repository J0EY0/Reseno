from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Locator, Request, expect

from tests.e2e.browser_support import DeferredRoute
from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


@pytest.mark.browser_smoke
def test_resume_history_preview_and_explicit_restore_preserve_formal_document(
    browser: Browser,
    workspace_servers: tuple[str, str],
    tmp_path: Path,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()
    resume_id: str | None = None
    version_gate: DeferredRoute | None = None
    restore_gate: DeferredRoute | None = None
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
            wait_until="domcontentloaded",
        )
        preview = page.locator(
            ".resume-preview-card article.resume-page",
        )
        expect(preview).to_contain_text(second_name)
        page.clock.install()

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
        version_button_bounds = historical_version.bounding_box()
        assert version_button_bounds is not None

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

        version_gate = DeferredRoute(page, version_pattern)
        historical_version.click()
        version_gate.wait()

        expect(version_popover).to_be_visible()
        expect(historical_version).to_be_visible()
        expect(historical_version).to_be_disabled()
        assert historical_version.bounding_box() == pytest.approx(
            version_button_bounds, abs=1
        )
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

        version_gate.release()

        expect(preview).to_contain_text(initial_name)
        expect(version_popover).to_be_visible()
        expect(historical_version).to_be_visible()
        expect(historical_version).to_contain_text("查看中")
        expect(page.locator('[data-slot="save-status-announcement"]')).to_contain_text(
            "正在查看历史版本"
        )
        banner = page.get_by_role("region", name="正在查看历史版本", exact=True)
        expect(banner).to_be_visible()
        expect(page.get_by_role("button", name="保存状态", exact=True)).to_be_disabled()
        expect(page.locator(".resume-editor-panel")).to_have_attribute("inert", "")
        page.clock.fast_forward(30_000)
        assert resume_save_requests == []
        current_detail = page.request.get(
            f"{frontend_url}/api/resumes/{resume_id}"
        ).json()["data"]
        assert (
            current_detail["versionId"]
            == checkpoint_response.json()["data"]["versionId"]
        )
        assert current_detail["resume"]["resume"]["basic"]["name"] == second_name
        page.keyboard.press("Escape")
        expect(version_popover).not_to_be_visible()
        theme_toggle = page.get_by_role(
            "button", name="切换日间 / 夜间模式", exact=True
        )
        theme_toggle.click()
        page.wait_for_function("document.documentElement.classList.contains('dark')")
        page.screenshot(path=str(tmp_path / "history-dark-desktop.png"))
        theme_toggle.click()
        page.get_by_role("button", name="回到最新版", exact=True).click()
        expect(preview).to_contain_text(second_name)
        expect(banner).not_to_be_visible()
        assert resume_save_requests == []

        history_trigger.click()
        version_popover.get_by_role("button").last.click()
        expect(preview).to_contain_text(initial_name)
        expect(banner).to_be_visible()
        page.keyboard.press("Escape")

        restore_gate = DeferredRoute(
            page, f"**/api/resumes/{resume_id}?saveMode=checkpoint"
        )
        page.get_by_role("button", name="恢复此版本", exact=True).click()
        restore_gate.wait()
        expect(
            page.get_by_role("button", name="正在恢复版本…", exact=True)
        ).to_be_disabled()
        expect(
            page.get_by_role("button", name="回到最新版", exact=True)
        ).to_be_disabled()
        restore_gate.release(
            lambda route: route.fulfill(
                status=503,
                json={"code": 50000, "message": "REQUEST_FAILED", "data": None},
            )
        )
        expect(banner.get_by_role("alert")).to_have_text("恢复此版本失败，请重试。")
        expect(
            page.get_by_role("button", name="恢复此版本", exact=True)
        ).to_be_enabled()
        unchanged = page.request.get(f"{frontend_url}/api/resumes/{resume_id}").json()[
            "data"
        ]
        assert unchanged["resume"]["resume"]["basic"]["name"] == second_name

        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
            )
        ) as restored_response:
            page.get_by_role("button", name="恢复此版本", exact=True).click()
        assert restored_response.value.ok
        expect(banner).not_to_be_visible()
        expect(preview).to_contain_text(initial_name)
        expect(page.get_by_role("button", name="保存状态", exact=True)).to_be_enabled()
        restored_detail = page.request.get(
            f"{frontend_url}/api/resumes/{resume_id}"
        ).json()["data"]
        assert restored_detail["resume"]["resume"]["basic"]["name"] == initial_name
        assert restored_detail["versionId"] != "1"
        assert restored_detail["versionId"] != current_detail["versionId"]
        assert len(resume_save_requests) == 2
        page.reload(wait_until="domcontentloaded")
        expect(preview).to_contain_text(initial_name)
        expect(banner).not_to_be_visible()
    finally:
        if version_gate:
            version_gate.release()
        if restore_gate:
            restore_gate.release()
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def _assert_history_toolbar_bounds(toolbar: Locator) -> dict[str, float]:
    geometry = toolbar.evaluate(
        """element => {
          const card = element.closest('.resume-preview-card');
          const controls = card?.querySelector(
            '[data-slot="document-canvas-controls"]');
          const rect = node => {
            const {x, y, width, height} = node.getBoundingClientRect();
            return {x, y, width, height};
          };
          return {
            toolbar: rect(element),
            card: card ? rect(card) : null,
            controls: controls ? rect(controls) : null,
            viewport: {width: innerWidth, height: innerHeight},
          };
        }"""
    )
    bar, card, controls = (
        geometry["toolbar"],
        geometry["card"],
        geometry["controls"],
    )
    assert card is not None and controls is not None, geometry
    assert (
        card["x"] <= bar["x"] < bar["x"] + bar["width"] <= (card["x"] + card["width"])
    ), geometry
    assert (
        card["y"] <= bar["y"] < bar["y"] + bar["height"] <= (card["y"] + card["height"])
    ), geometry
    assert 0 <= bar["x"] and bar["x"] + bar["width"] <= geometry["viewport"]["width"]
    assert 0 <= bar["y"] and bar["y"] + bar["height"] <= geometry["viewport"]["height"]
    assert (
        bar["y"] + bar["height"] <= controls["y"]
        or controls["y"] + controls["height"] <= bar["y"]
        or bar["x"] + bar["width"] <= controls["x"]
        or controls["x"] + controls["width"] <= bar["x"]
    ), geometry
    return bar


@pytest.mark.browser_smoke
@pytest.mark.parametrize("width", [1440, 375], ids=["desktop", "phone"])
@pytest.mark.parametrize("locale", ["zh", "en"])
def test_history_actions_float_inside_preview_and_remain_available_after_scrolling(
    browser: Browser,
    workspace_servers: tuple[str, str],
    width: int,
    locale: str,
    tmp_path: Path,
) -> None:
    base, _ = workspace_servers
    frontend = Path(__file__).resolve().parents[3] / "frontend"
    messages = json.loads(
        (frontend / f"src/i18n/locales/{locale}.json").read_text(encoding="utf-8")
    )
    history_messages = json.loads(
        (frontend / "src/i18n/resume-history.json").read_text(encoding="utf-8")
    )[locale]
    context = _authenticated_context(
        browser,
        locale="zh-CN" if locale == "zh" else "en-US",
        viewport={"width": width, "height": 870},
        reduced_motion="reduce",
    )
    context.add_init_script(f"localStorage.setItem('reseno-locale', '{locale}')")
    page = context.new_page()
    try:
        response = page.request.post(
            f"{base}/api/resumes",
            data={"documentLocale": locale, "template": "minimal", "title": "History"},
        )
        assert response.ok, response.text()
        created = response.json()["data"]["resume"]
        resume_id = created["id"]
        initial_name = created["resume"]["basic"]["name"]
        payload = {
            key: created[key]
            for key in (
                "title",
                "documentLocale",
                "resume",
                "jobBrief",
                "typography",
                "template",
                "templateSettings",
            )
        }
        payload["resume"]["basic"]["name"] = "Current resume"
        response = page.request.put(f"{base}/api/resumes/{resume_id}", data=payload)
        assert response.ok, response.text()
        saves: list[Request] = []
        page.on(
            "request",
            lambda request: (
                saves.append(request)
                if request.method == "PUT"
                and urlparse(request.url).path == f"/api/resumes/{resume_id}"
                else None
            ),
        )
        page.goto(f"{base}/resume/{resume_id}", wait_until="networkidle")
        page.locator(
            '[data-slot="save-status-group"] [data-slot="popover-trigger"]'
        ).click()
        popover = page.get_by_role("dialog", name=messages["saveVersions"], exact=True)
        popover.get_by_role("button").last.click()
        toolbar = page.get_by_role(
            "region", name=history_messages["viewing"], exact=True
        )
        expect(toolbar).to_be_visible()
        page.keyboard.press("Escape")
        card = page.locator(".resume-preview-card")
        card.scroll_into_view_if_needed()
        expect(toolbar.get_by_role("status")).to_contain_text(
            history_messages["viewing"]
        )
        restore = toolbar.get_by_role(
            "button", name=history_messages["restore"], exact=True
        )
        latest = toolbar.get_by_role(
            "button", name=history_messages["returnToLatest"], exact=True
        )
        expect(restore).to_be_enabled()
        expect(latest).to_be_enabled()
        expect(card.locator("article.resume-page").first).to_contain_text(initial_name)
        before = _assert_history_toolbar_bounds(toolbar)
        page.screenshot(path=str(tmp_path / f"history-{locale}-{width}.png"))

        card.get_by_role("button", name=messages["actualSize"], exact=True).click()
        viewport = card.locator('[data-slot="document-canvas-viewport"]')
        viewport.evaluate(
            "element => { element.scrollTop = 240; element.scrollLeft = 120; }"
        )
        expect(viewport).to_have_js_property("scrollTop", 240)
        after = _assert_history_toolbar_bounds(toolbar)
        assert after == pytest.approx(before, abs=1)
        restore.click(trial=True)
        page.screenshot(path=str(tmp_path / f"history-{locale}-{width}-scrolled.png"))
        latest.click()
        expect(toolbar).not_to_be_visible()
        expect(card.locator("article.resume-page").first).to_contain_text(
            "Current resume"
        )
        expect(page.locator(".resume-editor-panel")).not_to_have_attribute("inert", "")
        assert saves == []
    finally:
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
