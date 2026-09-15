from __future__ import annotations

import os
import re
import time
from typing import Any
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Route, expect

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def test_resume_title_preserves_draft_and_normalizes_on_commit(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()
    save_payloads: list[dict[str, object]] = []

    def capture_save(route: Route) -> None:
        if route.request.method == "PUT":
            payload = route.request.post_data_json
            assert isinstance(payload, dict)
            save_payloads.append(payload)
        route.continue_()

    page.route(f"**/api/resumes/{resume_id}*", capture_save)

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        persisted_response = page.request.get(f"{frontend_url}/api/resumes/{resume_id}")
        fallback_title = persisted_response.json()["data"]["resume"]["resume"]["basic"][
            "name"
        ]

        page.get_by_role("button", name="修改简历标题", exact=True).click()
        title_input = page.locator("#resume-title-input")
        overlong_draft = "  😀" + "a" * 60
        expected_truncated_draft = "  😀" + "a" * 47
        title_input.fill(overlong_draft)

        assert title_input.input_value() == expected_truncated_draft
        assert page.get_by_text("50/50", exact=True).count() == 1

        title_input.fill("  Trim Me  ")
        assert title_input.input_value() == "  Trim Me  "
        page.get_by_role("button", name="保存", exact=True).click()
        page.keyboard.press("Control+S")

        deadline = time.monotonic() + 5
        while len(save_payloads) < 1 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert save_payloads[-1]["title"] == "Trim Me"
        page.wait_for_load_state("networkidle")

        page.get_by_role("button", name="修改简历标题", exact=True).click()
        title_input.fill("   ")
        assert title_input.input_value() == "   "
        page.get_by_role("button", name="保存", exact=True).click()
        page.keyboard.press("Control+S")

        deadline = time.monotonic() + 5
        while len(save_payloads) < 2 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert save_payloads[-1]["title"] == (fallback_title or "新建简历1")
    finally:
        context.close()


def test_resume_section_delete_dialog_loads_and_preserves_exit_presence(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, resume_id = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 870},
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.locator('button[aria-label$=": 删除模块"]').first.click()

        dialog = page.locator('[data-slot="alert-dialog-content"]')
        overlay = page.locator('[data-slot="alert-dialog-overlay"]')
        dialog.wait_for(state="visible")
        expect(dialog).to_have_attribute("data-state", "open")
        assert (
            dialog.evaluate("element => getComputedStyle(element).animationName")
            == "dialog-content-enter"
        )
        assert (
            dialog.evaluate("element => getComputedStyle(element).animationDuration")
            == "0.21s"
        )
        assert (
            overlay.evaluate("element => getComputedStyle(element).animationName")
            == "dialog-overlay-enter"
        )

        page.get_by_role("button", name="取消", exact=True).click()
        expect(dialog).to_have_attribute("data-state", "closed")
        assert (
            dialog.evaluate("element => getComputedStyle(element).animationName")
            == "dialog-content-exit"
        )
        assert (
            dialog.evaluate("element => getComputedStyle(element).animationDuration")
            == "0.15s"
        )
        assert (
            overlay.evaluate("element => getComputedStyle(element).animationName")
            == "dialog-overlay-exit"
        )
        dialog.wait_for(state="detached")
    finally:
        context.close()


@pytest.mark.browser_smoke
def test_resume_section_operations_keep_a_single_open_editor(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 1000},
    )
    page = context.new_page()
    resume_id: str | None = None

    try:
        created_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"documentLocale": "zh", "title": "Section editor ownership"},
        )
        assert created_response.ok
        created = created_response.json()["data"]["resume"]
        resume_id = created["id"]
        sections = [
            {"id": "education", "kind": "education", "title": "教育经历", "items": []},
            {
                "id": "experience",
                "kind": "experience",
                "title": "既有经历",
                "items": [],
            },
        ]
        saved_response = page.request.put(
            f"{frontend_url}/api/resumes/{resume_id}",
            data={
                "title": created["title"],
                "documentLocale": created["documentLocale"],
                "resume": {**created["resume"], "sections": sections},
                "jobBrief": created["jobBrief"],
                "typography": created["typography"],
                "template": created["template"],
                "templateSettings": created["templateSettings"],
            },
        )
        assert saved_response.ok
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        open_sections = page.locator(
            '.resume-editor-panel button[aria-label$=": 展开或收起模块"]'
            '[aria-expanded="true"]'
        )
        basic = page.get_by_role("button", name="基本信息: 展开或收起模块", exact=True)
        education = page.get_by_role(
            "button", name="教育经历: 展开或收起模块", exact=True
        )
        project = page.get_by_role(
            "button", name="项目经历: 展开或收起模块", exact=True
        )
        expect(open_sections).to_have_count(0)
        basic.click()
        expect(basic).to_have_attribute("aria-expanded", "true")
        education.click()
        expect(education).to_have_attribute("aria-expanded", "true")
        expect(basic).to_have_attribute("aria-expanded", "false")
        expect(open_sections).to_have_count(1)
        education.click()
        expect(open_sections).to_have_count(0)
        education.click()

        page.get_by_role("button", name="新增模块", exact=True).click()
        page.get_by_role("option", name=re.compile("^项目经历")).click()
        expect(project).to_have_attribute("aria-expanded", "true")
        expect(education).to_have_attribute("aria-expanded", "false")
        expect(open_sections).to_have_count(1)

        page.get_by_role("button", name="教育经历: 删除模块", exact=True).click()
        dialog = page.get_by_role("alertdialog")
        dialog.get_by_role("button", name="删除模块", exact=True).click()
        expect(education).to_have_count(0)
        expect(project).to_have_attribute("aria-expanded", "true")
        expect(open_sections).to_have_count(1)
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
            )
        ) as saving:
            page.keyboard.press("ControlOrMeta+s")
        assert saving.value.ok
        persisted = page.request.get(f"{frontend_url}/api/resumes/{resume_id}").json()
        persisted_sections = persisted["data"]["resume"]["resume"]["sections"]
        assert [section["title"] for section in persisted_sections] == [
            "既有经历",
            "项目经历",
        ]

        page.get_by_role("button", name="项目经历: 删除模块", exact=True).click()
        dialog.get_by_role("button", name="删除模块", exact=True).click()
        expect(project).to_have_count(0)
        expect(open_sections).to_have_count(0)
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == f"/api/resumes/{resume_id}"
            )
        ) as saving:
            page.keyboard.press("ControlOrMeta+s")
        assert saving.value.ok
        persisted = page.request.get(f"{frontend_url}/api/resumes/{resume_id}").json()
        assert persisted["data"]["resume"]["resume"]["sections"] == [sections[1]]
        page.reload(wait_until="networkidle")
        expect(open_sections).to_have_count(0)
        expect(
            page.get_by_role("button", name="既有经历: 展开或收起模块", exact=True)
        ).to_have_attribute("aria-expanded", "false")
    finally:
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_project_tech_stack_is_saved_without_blurring_the_input(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        viewport={"width": 1672, "height": 870},
        locale="zh-CN",
    )
    page = context.new_page()
    save_payloads: list[dict[str, object]] = []

    def capture_save(route: Route) -> None:
        if route.request.method == "PUT":
            payload = route.request.post_data_json
            assert isinstance(payload, dict)
            save_payloads.append(payload)
        route.continue_()

    try:
        created_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"documentLocale": "zh", "template": "minimal"},
        )
        assert created_response.ok
        resume_id = created_response.json()["data"]["resume"]["id"]
        page.route(f"**/api/resumes/{resume_id}*", capture_save)
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="项目经历: 展开或收起模块",
            exact=True,
        ).click()
        item_toggle = page.get_by_role(
            "button",
            name="展开或收起条目 1",
            exact=True,
        )
        item_shell = item_toggle.locator("xpath=ancestor::section[1]")
        item_header = item_shell.locator("h4").locator("xpath=..")
        item_toggle.click()

        tech_stack_input = page.get_by_label("技术栈", exact=True)
        expected_tech_stack = ["React", "TypeScript", "FastAPI"]
        tech_stack_input.fill(", ".join(expected_tech_stack))
        assert tech_stack_input.evaluate(
            "element => element === document.activeElement"
        )

        page.keyboard.press("Control+S")

        deadline = time.monotonic() + 5
        while len(save_payloads) < 1 and time.monotonic() < deadline:
            page.wait_for_timeout(50)

        assert save_payloads, "Focused tech-stack edits did not trigger a save."
        project_section = next(
            section
            for section in save_payloads[-1]["resume"]["sections"]
            if section["kind"] == "project"
        )
        assert project_section["items"][0]["techStack"] == expected_tech_stack
        assert tech_stack_input.evaluate(
            "element => element === document.activeElement"
        )
        item_toggle.click()
        assert item_header.locator("p").count() == 0
    finally:
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize("item_count", [3, 16])
def test_rich_text_editor_lazy_mount_preserves_collapsible_height(
    browser: Browser,
    workspace_servers: tuple[str, str],
    item_count: int,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        viewport={"width": 1672, "height": 870},
        locale="zh-CN",
    )
    page = context.new_page()
    resume_id: str | None = None

    def delay_rich_text_editor(route: Route) -> None:
        time.sleep(0.16)
        route.continue_()

    page.route(
        "**/src/components/editor/rich-highlights-editor.tsx*",
        delay_rich_text_editor,
    )
    page.add_init_script(
        """
        (() => {
          window.__richEditorFrames = [];
          window.__recordRichEditorFrames = false;
          window.__richEditorAnimations = [];
          document.addEventListener('animationstart', event => {
            if (!window.__recordRichEditorFrames || !event.target.closest(
              '[data-slot="collapsible"]'
            )?.querySelector('button[aria-label="技能: 展开或收起模块"]') ||
              !event.animationName.startsWith('collapsible-')) return;
            const animation = event.target.getAnimations().find(
              animation => animation.animationName === event.animationName
            );
            if (animation) {
              animation.pause();
              animation.currentTime = 0;
              window.__richEditorAnimations.push({animation, step: 0});
            }
          });

          const capture = (now) => {
            if (window.__recordRichEditorFrames) {
              for (const sample of window.__richEditorAnimations) {
                if (sample.step < 8) {
                  sample.animation.currentTime =
                    Number(sample.animation.effect.getTiming().duration) *
                    sample.step++ / 8;
                } else if (sample.animation.playState === 'paused') {
                  sample.animation.play();
                }
              }
              const toggle = document.querySelector(
                'button[aria-label="技能: 展开或收起模块"]',
              );
              const root = toggle?.closest('[data-slot="collapsible"]');
              const content = root?.querySelector(
                '[data-slot="collapsible-content"]',
              );
              const inner = content?.querySelector(
                '.collapsible-content-inner',
              );

              if (content && inner) {
                const contentStyle = window.getComputedStyle(content);
                const innerStyle = window.getComputedStyle(inner);
                window.__richEditorFrames.push({
                  time: now,
                  state: content.getAttribute('data-state'),
                  contentHeight: content.getBoundingClientRect().height,
                  innerHeight: inner.getBoundingClientRect().height,
                  scrollHeight: content.scrollHeight,
                  radixHeight: contentStyle
                    .getPropertyValue('--radix-collapsible-content-height')
                    .trim(),
                  animationName: contentStyle.animationName,
                  innerAnimationName: innerStyle.animationName,
                  innerOpacity: Number(innerStyle.opacity),
                  hasSkeleton: Boolean(
                    inner.querySelector('[data-slot="skeleton"]'),
                  ),
                  hasEditor: Boolean(inner.querySelector('.ProseMirror')),
                });
              }
            }

            window.requestAnimationFrame(capture);
          };

          window.requestAnimationFrame(capture);
        })();
        """
    )

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": f"Rich editor expand layout regression {item_count}",
            },
        )
        assert create_response.ok
        created = create_response.json()["data"]["resume"]
        resume_id = str(created["id"])
        save_response = page.request.put(
            f"{frontend_url}/api/resumes/{resume_id}",
            data={
                "title": created["title"],
                "documentLocale": created["documentLocale"],
                "resume": {
                    **created["resume"],
                    "sections": [
                        {
                            "id": "expand-layout-skills",
                            "kind": "simple_list",
                            "title": "技能",
                            "items": [
                                {
                                    "id": "expand-layout-skills-content",
                                    "content": (
                                        "<ul>"
                                        + "".join(
                                            f"<li>Skill {index + 1}</li>"
                                            for index in range(item_count)
                                        )
                                        + "</ul>"
                                    ),
                                }
                            ],
                        }
                    ],
                },
                "jobBrief": created["jobBrief"],
                "typography": created["typography"],
                "template": created["template"],
                "templateSettings": created["templateSettings"],
            },
        )
        assert save_response.ok

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        toggle = page.get_by_role(
            "button",
            name="技能: 展开或收起模块",
            exact=True,
        )
        expect(toggle).to_have_attribute("aria-expanded", "false")

        page.evaluate(
            """
            () => {
              window.__richEditorFrames = [];
              window.__recordRichEditorFrames = true;
            }
            """
        )
        toggle.click()
        editor = page.locator(
            '[data-slot="collapsible-content"] .ProseMirror',
        )
        editor.wait_for(state="visible")
        expect(editor).to_contain_text("Skill 1")
        page.wait_for_timeout(360)
        page.wait_for_function(
            """() => window.__richEditorAnimations.every(({animation}) =>
              animation.playState === 'finished' || animation.playState === 'idle'
            )""",
            timeout=5_000,
        )
        frames: list[dict[str, Any]] = page.evaluate(
            """
            () => {
              window.__recordRichEditorFrames = false;
              return window.__richEditorFrames;
            }
            """
        )

        skeleton_frames = [frame for frame in frames if frame["hasSkeleton"]]
        editor_frames = [frame for frame in frames if frame["hasEditor"]]
        assert skeleton_frames, frames
        assert editor_frames, frames

        last_skeleton = skeleton_frames[-1]
        first_editor = next(
            frame for frame in editor_frames if frame["time"] >= last_skeleton["time"]
        )
        assert first_editor["innerHeight"] == pytest.approx(
            last_skeleton["innerHeight"],
            abs=2,
        ), {"lastSkeleton": last_skeleton, "firstEditor": first_editor}

        final_frame = editor_frames[-1]
        radix_height = float(str(final_frame["radixHeight"]).removesuffix("px"))
        assert final_frame["innerHeight"] == pytest.approx(radix_height, abs=2), {
            "finalFrame": final_frame,
            "frames": frames,
        }

        opening_frames = [
            frame
            for frame in frames
            if frame["state"] == "open" and frame["contentHeight"] > 1
        ]
        assert (
            len({round(float(frame["contentHeight"]), 1) for frame in opening_frames})
            >= 4
        ), opening_frames
        assert any(
            frame["animationName"] == "collapsible-down" for frame in opening_frames
        ), opening_frames
        assert any(
            frame["innerAnimationName"] == "collapsible-inner-in"
            for frame in opening_frames
        ), opening_frames
        assert any(0 < float(frame["innerOpacity"]) < 1 for frame in opening_frames), (
            opening_frames
        )

        if item_count == 3:
            page.evaluate(
                """
                () => {
                  window.__richEditorFrames = [];
                  window.__recordRichEditorFrames = true;
                }
                """
            )
            toggle.click()
            expect(toggle).to_have_attribute("aria-expanded", "false")
            page.wait_for_timeout(260)
            page.wait_for_function(
                """() => window.__richEditorAnimations.every(({animation}) =>
                  animation.playState === 'finished' || animation.playState === 'idle'
                )""",
                timeout=5_000,
            )
            closing_frames: list[dict[str, Any]] = page.evaluate(
                """
                () => {
                  window.__recordRichEditorFrames = false;
                  return window.__richEditorFrames;
                }
                """
            )
            closing_visible_frames = [
                frame
                for frame in closing_frames
                if frame["state"] == "closed" and frame["contentHeight"] > 1
            ]
            assert (
                len(
                    {
                        round(float(frame["contentHeight"]), 1)
                        for frame in closing_visible_frames
                    }
                )
                >= 4
            ), closing_frames
            assert (
                closing_visible_frames[0]["contentHeight"]
                > (closing_visible_frames[-1]["contentHeight"])
            ), closing_visible_frames
            assert any(
                frame["animationName"] == "collapsible-up"
                for frame in closing_visible_frames
            ), closing_visible_frames
            assert any(
                frame["innerAnimationName"] == "collapsible-inner-out"
                for frame in closing_visible_frames
            ), closing_visible_frames

            page.emulate_media(reduced_motion="reduce")
            page.evaluate(
                """
                () => {
                  window.__richEditorFrames = [];
                  window.__recordRichEditorFrames = true;
                }
                """
            )
            toggle.click()
            editor.wait_for(state="visible")
            expect(toggle).to_have_attribute("aria-expanded", "true")
            page.wait_for_timeout(50)
            page.wait_for_function(
                "() => window.__richEditorFrames.length > 0", timeout=5_000
            )
            reduced_motion_frames: list[dict[str, Any]] = page.evaluate(
                """
                () => {
                  window.__recordRichEditorFrames = false;
                  return window.__richEditorFrames;
                }
                """
            )
            assert reduced_motion_frames, reduced_motion_frames
            assert all(
                frame["animationName"] == "none"
                and frame["innerAnimationName"] == "none"
                for frame in reduced_motion_frames
            ), reduced_motion_frames
    finally:
        if resume_id:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize(
    ("gallery_path", "detail_href_prefix"),
    [
        ("/resume", "/resume/"),
        ("/templates", "/template/"),
    ],
)
def test_detail_push_resets_document_scroll_and_focuses_main_content(
    browser: Browser,
    workspace_servers: tuple[str, str],
    gallery_path: str,
    detail_href_prefix: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1280, "height": 720},
    )
    page = context.new_page()

    try:
        page.goto(f"{frontend_url}{gallery_path}", wait_until="networkidle")
        target_link = page.locator(
            f'#main-content a[href^="{detail_href_prefix}"]'
        ).first
        target_link.wait_for(state="visible")
        target_href = target_link.get_attribute("href")
        assert target_href

        scroll_top = target_link.evaluate(
            """
            element => {
              const main = document.querySelector('#main-content');
              if (!(main instanceof HTMLElement)) {
                throw new Error('Workspace main content is unavailable.');
              }
              const spacer = document.createElement('div');
              spacer.setAttribute('aria-hidden', 'true');
              spacer.style.flex = '0 0 1400px';
              main.append(spacer);
              element.focus();
              window.scrollTo({ top: 600, behavior: 'instant' });
              return document.scrollingElement?.scrollTop ?? 0;
            }
            """
        )
        assert scroll_top > 0
        expect(target_link).to_be_focused()

        target_link.evaluate("element => element.click()")
        page.wait_for_url(f"**{urlparse(target_href).path}")
        main_content = page.locator("#main-content")
        expect(main_content).to_be_focused()
        page.wait_for_timeout(200)

        assert page.evaluate("document.scrollingElement?.scrollTop ?? 0") == 0
        expect(main_content).to_be_focused()
    finally:
        context.close()
