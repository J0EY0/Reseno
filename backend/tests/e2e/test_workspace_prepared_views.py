from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Page, Request, Route

from tests.e2e.browser_support import authenticated_context as _authenticated_context
from tests.e2e.workspace_frame_support import (
    assert_visible_once_mounted,
    boolean_runs,
    install_workspace_frame_recorder,
    start_workspace_frame_recording,
    stop_workspace_frame_recording,
)

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


def _wait_for_route_frames(page: Page, path: str) -> None:
    page.wait_for_function(
        """path => window.__workspaceFrames.filter(
          frame => frame.path === path
        ).length >= 2""",
        arg=path,
        timeout=5_000,
    )


@pytest.mark.browser_smoke
def test_resume_navigation_keeps_cached_views_mounted_and_preview_fits(
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
    install_workspace_frame_recorder(page)

    def continue_after_delay(route: Route) -> None:
        time.sleep(0.2)
        route.continue_()

    page.route("**/api/workspace/pages/resume-editor", continue_after_delay)
    page.route("**/api/workspace/pages/resumes", continue_after_delay)

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        resume_link = page.locator(f'a[href="/resume/{resume_id}"]')

        assert resume_link.count() == 1
        start_workspace_frame_recording(page)
        resume_link.click()
        page.wait_for_url(f"{frontend_url}/resume/{resume_id}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        _wait_for_route_frames(page, f"/resume/{resume_id}")
        detail_frames = stop_workspace_frame_recording(page)

        preview_frame = page.locator('[data-slot="document-canvas-viewport"]')
        preview_page = page.locator(
            ".resume-preview-card article.resume-page",
        )
        agent_dock = page.locator('.agent-panel-dock[aria-hidden="false"]')

        assert preview_frame.count() == 1
        assert preview_page.count() == 1
        assert agent_dock.count() == 1
        frame_box = preview_frame.bounding_box()
        page_box = preview_page.bounding_box()
        agent_box = agent_dock.bounding_box()

        assert frame_box is not None
        assert page_box is not None
        assert agent_box is not None
        assert agent_box["width"] > 0
        routed_frames = [
            frame for frame in detail_frames if frame["path"] == f"/resume/{resume_id}"
        ]
        assert len(routed_frames) >= 2
        assert_visible_once_mounted(routed_frames, "hasResumeDetail")
        assert all(
            bool(frame["hasResumeGallery"]) or bool(frame["hasResumeDetail"])
            for frame in routed_frames
        )
        assert not any(bool(frame["hasAppFallback"]) for frame in routed_frames)
        assert not any(bool(frame["hasRouteSkeleton"]) for frame in routed_frames)
        assert all(
            bool(frame["resumePreviewFits"])
            for frame in routed_frames
            if frame["hasResumeDetail"]
        )
        assert page_box["x"] >= frame_box["x"] - 1
        assert page_box["x"] + page_box["width"] <= (
            frame_box["x"] + frame_box["width"] + 1
        )

        back_button = page.get_by_role(
            "button",
            name="返回简历列表",
            exact=True,
        )
        assert back_button.count() == 1
        start_workspace_frame_recording(page)
        back_button.click()
        page.wait_for_url(f"{frontend_url}/resume")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        _wait_for_route_frames(page, "/resume")
        gallery_frames = stop_workspace_frame_recording(page)
        routed_gallery_frames = [
            frame for frame in gallery_frames if frame["path"] == "/resume"
        ]
        assert len(routed_gallery_frames) >= 2
        assert_visible_once_mounted(routed_gallery_frames, "hasResumeGallery")
        assert all(
            bool(frame["hasResumeDetail"]) or bool(frame["hasResumeGallery"])
            for frame in routed_gallery_frames
        )
        assert not any(bool(frame["hasAppFallback"]) for frame in routed_gallery_frames)
        assert not any(
            bool(frame["hasRouteSkeleton"]) for frame in routed_gallery_frames
        )
    finally:
        context.close()


@pytest.mark.parametrize(
    "edit_before_checkpoint",
    [False, True],
    ids=["same-content-checkpoint", "edited-checkpoint"],
)
def test_resume_preparation_establishes_checkpoint_before_editor_mount(
    browser: Browser,
    workspace_servers: tuple[str, str],
    edit_before_checkpoint: bool,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()
    resume_id: str | None = None
    preparation_requests = 0
    checkpoint_responses = 0
    checkpoint_saved_at: str | None = None

    def capture_checkpoint(response) -> None:
        nonlocal checkpoint_responses, checkpoint_saved_at
        if (
            resume_id
            and response.request.method == "PUT"
            and urlparse(response.url).path == f"/api/resumes/{resume_id}"
        ):
            checkpoint_responses += 1
            checkpoint_saved_at = response.json()["data"]["savedAt"]

    def capture_preparation(request: Request) -> None:
        nonlocal preparation_requests
        if (
            resume_id
            and request.method == "GET"
            and urlparse(request.url).path == f"/api/resumes/{resume_id}"
        ):
            preparation_requests += 1

    page.on("response", capture_checkpoint)
    page.on("request", capture_preparation)

    try:
        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": "Prepared checkpoint regression",
            },
        )
        assert create_response.ok
        initial_detail = create_response.json()["data"]
        resume_id = initial_detail["resume"]["id"]
        checkpoint_saved_at = initial_detail["savedAt"]
        # Keep the original and new checkpoint labels distinct to make the
        # version-list assertion deterministic at second precision.
        page.wait_for_timeout(1_100)

        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.evaluate(
            f"""
            () => {{
              window.__resumePreparationCheckpointSent = false;
              window.__resumePreparationReleased = false;
              const originalFetch = window.fetch.bind(window);
              window.fetch = async (input, init) => {{
                const request = new Request(input, init);
                const response = await originalFetch(input, init);
                if (
                  request.method === "GET" &&
                  new URL(request.url).pathname ===
                    "/api/resumes/{resume_id}"
                ) {{
                  // Hold the prepared response after transport completes. The
                  // click must keep the gallery URL until this promise settles.
                  await new Promise((resolve) => window.setTimeout(resolve, 2_000));
                  window.__resumePreparationReleased = true;
                }}
                return response;
              }};
              const editBeforeCheckpoint = {str(edit_before_checkpoint).lower()};
              const deadline = performance.now() + 8_000;
              let openedBasicInfo = false;
              const saveWhenReady = () => {{
                const input = document.querySelector(
                  '[role="textbox"][aria-label="姓名"]',
                );
                const saveButton = document.querySelector(
                  'button[aria-label="保存状态"]',
                );
                if (
                  window.location.pathname === "/resume/{resume_id}" &&
                  saveButton instanceof HTMLButtonElement &&
                  (!editBeforeCheckpoint ||
                    (input instanceof HTMLElement && input.isContentEditable))
                ) {{
                  if (
                    editBeforeCheckpoint &&
                    input instanceof HTMLElement &&
                    input.isContentEditable
                  ) {{
                    input.focus();
                    window.getSelection()?.selectAllChildren(input);
                    if (!document.execCommand(
                      "insertText", false, "Saved After Preparation Returned",
                    )) {{
                      throw new Error("Name editor could not accept text.");
                    }}
                  }}
                  window.setTimeout(() => {{
                    saveButton.click();
                    window.__resumePreparationCheckpointSent = true;
                  }}, 100);
                  return;
                }}
                if (
                  window.location.pathname === "/resume/{resume_id}" &&
                  editBeforeCheckpoint &&
                  !openedBasicInfo
                ) {{
                  const trigger = [...document.querySelectorAll("button")]
                    .find((candidate) =>
                      candidate.getAttribute("aria-label") ===
                      "基本信息: 展开或收起模块",
                    );
                  if (trigger instanceof HTMLButtonElement) {{
                    openedBasicInfo = true;
                    trigger.click();
                  }}
                }}
                if (performance.now() < deadline) {{
                  requestAnimationFrame(saveWhenReady);
                }}
              }};
              requestAnimationFrame(saveWhenReady);
            }}
            """
        )

        page.locator(f'a[href="/resume/{resume_id}"]').click()
        page.wait_for_timeout(250)
        assert page.url == f"{frontend_url}/resume"
        page.wait_for_url(f"{frontend_url}/resume/{resume_id}")
        page.wait_for_function("window.__resumePreparationCheckpointSent === true")
        expected_checkpoint_responses = int(edit_before_checkpoint)
        deadline = time.monotonic() + 8
        while (
            preparation_requests < 1
            or checkpoint_responses < expected_checkpoint_responses
        ) and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        page.wait_for_timeout(150)

        assert preparation_requests == 1
        assert checkpoint_responses == expected_checkpoint_responses
        assert checkpoint_saved_at is not None
        assert page.evaluate("window.__resumePreparationCheckpointSent") is True
        page.wait_for_function("window.__resumePreparationReleased === true")
        page.wait_for_timeout(100)
        if edit_before_checkpoint:
            assert page.get_by_role(
                "textbox", name="姓名", exact=True
            ).inner_text() == ("Saved After Preparation Returned")
        page.get_by_role("button", name="保存状态", exact=True).hover()
        page.get_by_text("有未保存更改", exact=True).wait_for(state="detached")
        checkpoint_label = page.evaluate(
            """
            (savedAt) => new Intl.DateTimeFormat("zh-CN", {
              month: "2-digit",
              day: "2-digit",
              hour: "2-digit",
              minute: "2-digit",
              second: "2-digit",
            }).format(new Date(savedAt))
            """,
            checkpoint_saved_at,
        )
        page.get_by_text(checkpoint_label, exact=False).first.wait_for(state="visible")
        persisted_response = page.request.get(f"{frontend_url}/api/resumes/{resume_id}")
        assert persisted_response.ok
        persisted_detail = persisted_response.json()["data"]
        if edit_before_checkpoint:
            assert (
                persisted_detail["resume"]["resume"]["basic"]["name"]
                == "Saved After Preparation Returned"
            )
            assert persisted_detail["savedAt"] != initial_detail["savedAt"]
            assert persisted_detail["versionId"] != initial_detail["versionId"]
        else:
            assert persisted_detail["savedAt"] == initial_detail["savedAt"]
            assert persisted_detail["versionId"] == initial_detail["versionId"]
            assert (
                persisted_detail["resume"]["resume"]
                == initial_detail["resume"]["resume"]
            )
    finally:
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_template_navigation_keeps_cached_views_mounted(
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
    install_workspace_frame_recorder(page)

    def continue_after_delay(route: Route) -> None:
        time.sleep(0.2)
        route.continue_()

    page.route("**/api/workspace/pages/templates", continue_after_delay)

    try:
        page.goto(f"{frontend_url}/templates", wait_until="networkidle")
        template_link = page.locator('a[href="/template/minimal"]')

        assert template_link.count() == 1
        start_workspace_frame_recording(page)
        template_link.click()
        page.wait_for_url(f"{frontend_url}/template/minimal")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        detail_frames = stop_workspace_frame_recording(page)
        routed_detail_frames = [
            frame for frame in detail_frames if frame["path"] == "/template/minimal"
        ]
        assert len(routed_detail_frames) >= 2
        assert_visible_once_mounted(routed_detail_frames, "hasTemplateDetail")
        assert all(
            bool(frame["hasTemplateGallery"]) or bool(frame["hasTemplateDetail"])
            for frame in routed_detail_frames
        )
        assert not any(bool(frame["hasAppFallback"]) for frame in routed_detail_frames)
        assert not any(
            bool(frame["hasRouteSkeleton"]) for frame in routed_detail_frames
        )

        back_button = page.get_by_role(
            "button",
            name="返回模板列表",
            exact=True,
        )
        assert back_button.count() == 1
        start_workspace_frame_recording(page)
        back_button.click()
        page.wait_for_url(f"{frontend_url}/templates")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        gallery_frames = stop_workspace_frame_recording(page)
        routed_gallery_frames = [
            frame for frame in gallery_frames if frame["path"] == "/templates"
        ]
        assert len(routed_gallery_frames) >= 2
        assert_visible_once_mounted(
            routed_gallery_frames,
            "hasTemplateGallery",
        )
        assert all(
            bool(frame["hasTemplateDetail"]) or bool(frame["hasTemplateGallery"])
            for frame in routed_gallery_frames
        )
        assert not any(bool(frame["hasAppFallback"]) for frame in routed_gallery_frames)
        assert not any(
            bool(frame["hasRouteSkeleton"]) for frame in routed_gallery_frames
        )
    finally:
        context.close()


def test_template_preparation_finishes_before_detail_becomes_editable(
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
    preparation_requests = 0

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="创建副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = page.url.rsplit("/", maxsplit=1)[-1]
        page.get_by_role(
            "button",
            name="返回模板列表",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/templates")
        page.wait_for_load_state("networkidle")

        # Expire the shared template-catalog cache so the click must perform a
        # fresh target preparation before it can commit the detail URL.
        page.wait_for_timeout(3_200)

        def delay_preparation(route: Route) -> None:
            nonlocal preparation_requests
            preparation_requests += 1
            time.sleep(1)
            route.continue_()

        page.route("**/api/workspace/pages/templates", delay_preparation)
        page.evaluate(
            f"""
            () => {{
              window.__templatePreparationDraftEdited = false;
              const deadline = performance.now() + 5_000;
              let openedTemplateMetadata = false;
              const editWhenReady = () => {{
                const input = document.querySelector(
                  'input[name="templateName"]',
                );
                const valueSetter = Object.getOwnPropertyDescriptor(
                  HTMLInputElement.prototype,
                  "value",
                )?.set;
                if (
                  window.location.pathname === "/template/{template_id}" &&
                  input instanceof HTMLInputElement &&
                  valueSetter
                ) {{
                  valueSetter.call(input, "Local Edit After Preparation");
                  input.dispatchEvent(new Event("input", {{ bubbles: true }}));
                  const form = input.closest("form");
                  if (form instanceof HTMLFormElement) {{
                    form.requestSubmit();
                    window.__templatePreparationDraftEdited = true;
                  }}
                  return;
                }}
                if (
                  window.location.pathname === "/template/{template_id}" &&
                  !openedTemplateMetadata
                ) {{
                  const trigger = document.querySelector(
                    '[data-template-metadata-trigger="true"]',
                  );
                  if (trigger instanceof HTMLElement) {{
                    openedTemplateMetadata = true;
                    trigger.click();
                  }}
                }}
                if (performance.now() < deadline) {{
                  requestAnimationFrame(editWhenReady);
                }}
              }};
              requestAnimationFrame(editWhenReady);
            }}
            """
        )

        page.locator(f'a[href="/template/{template_id}"]').click()
        page.wait_for_url(f"{frontend_url}/template/{template_id}")
        deadline = time.monotonic() + 5
        while preparation_requests < 1 and time.monotonic() < deadline:
            page.wait_for_timeout(50)
        page.wait_for_function(
            "window.__templatePreparationDraftEdited === true",
            timeout=5_000,
        )

        assert preparation_requests == 1
        assert page.evaluate("window.__templatePreparationDraftEdited") is True
        assert page.locator('[data-slot="template-editor-title"]').inner_text() == (
            "Local Edit After Preparation"
        )
    finally:
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize(
    ("target_route", "api_path", "frame_key"),
    [
        (
            "/templates",
            "/api/workspace/pages/templates",
            "hasTemplateGallery",
        ),
        ("/trash", "/api/workspace/pages/trash", "hasTrashContent"),
        ("/models", "/api/workspace/pages/models", "hasModelsContent"),
        (
            "/settings",
            "/api/workspace/pages/settings",
            "hasSettingsContent",
        ),
    ],
)
def test_prepared_lateral_navigation_never_shows_loading_surface(
    browser: Browser,
    workspace_servers: tuple[str, str],
    target_route: str,
    api_path: str,
    frame_key: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 870}
    )
    page = context.new_page()
    install_workspace_frame_recorder(page)

    def continue_after_delay(route: Route) -> None:
        time.sleep(0.2)
        route.continue_()

    page.route(f"**{api_path}", continue_after_delay)

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        target_link = page.locator(f'a[href="{target_route}"]')

        assert target_link.count() == 1
        target_link.hover()
        page.wait_for_timeout(200)
        start_workspace_frame_recording(page)
        target_link.click()
        page.wait_for_url(f"{frontend_url}{target_route}")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(600)
        _wait_for_route_frames(page, target_route)
        frames = stop_workspace_frame_recording(page)
        routed_frames = [frame for frame in frames if frame["path"] == target_route]

        assert len(routed_frames) >= 2
        assert_visible_once_mounted(routed_frames, frame_key)
        handoff_states = [
            bool(frame["hasResumeGallery"]) or bool(frame[frame_key])
            for frame in routed_frames
        ]
        app_fallback_states = [bool(frame["hasAppFallback"]) for frame in routed_frames]
        skeleton_states = [bool(frame["hasRouteSkeleton"]) for frame in routed_frames]
        sidebar_states = [bool(frame["hasSidebar"]) for frame in routed_frames]

        assert all(handoff_states), boolean_runs(handoff_states)
        assert not any(app_fallback_states), boolean_runs(app_fallback_states)
        assert not any(skeleton_states), boolean_runs(skeleton_states)
        assert all(sidebar_states), boolean_runs(sidebar_states)
    finally:
        context.close()


def test_lateral_history_uses_latest_view_snapshot_without_blank_frame(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1672, "height": 870})
    page = context.new_page()
    install_workspace_frame_recorder(page)

    def continue_after_delay(route: Route) -> None:
        time.sleep(0.2)
        route.continue_()

    page.route("**/api/workspace/pages/resumes", continue_after_delay)
    page.route("**/api/workspace/pages/settings", continue_after_delay)

    try:
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.locator('a[href="/settings"]').click()
        page.wait_for_url(f"{frontend_url}/settings")
        page.wait_for_load_state("networkidle")
        # Expire requestApi's short GET cache so the first POP frame is proven
        # to come from route memory rather than an already-resolved request.
        page.wait_for_timeout(3200)

        start_workspace_frame_recording(page)
        page.go_back(wait_until="commit")
        page.wait_for_url(f"{frontend_url}/resume")
        page.wait_for_timeout(600)
        back_frames = stop_workspace_frame_recording(page)
        routed_back_frames = [
            frame for frame in back_frames if frame["path"] == "/resume"
        ]

        assert len(routed_back_frames) >= 2
        assert_visible_once_mounted(routed_back_frames, "hasResumeGallery")
        assert all(
            bool(frame["hasSettingsContent"]) or bool(frame["hasResumeGallery"])
            for frame in routed_back_frames
        )
        assert not any(bool(frame["hasAppFallback"]) for frame in routed_back_frames)
        assert not any(bool(frame["hasRouteSkeleton"]) for frame in routed_back_frames)
        assert all(bool(frame["hasSidebar"]) for frame in routed_back_frames)

        start_workspace_frame_recording(page)
        page.go_forward(wait_until="commit")
        page.wait_for_url(f"{frontend_url}/settings")
        page.wait_for_timeout(600)
        forward_frames = stop_workspace_frame_recording(page)
        routed_forward_frames = [
            frame for frame in forward_frames if frame["path"] == "/settings"
        ]

        assert len(routed_forward_frames) >= 2
        assert_visible_once_mounted(
            routed_forward_frames,
            "hasSettingsContent",
        )
        assert all(
            bool(frame["hasResumeGallery"]) or bool(frame["hasSettingsContent"])
            for frame in routed_forward_frames
        )
        assert not any(bool(frame["hasAppFallback"]) for frame in routed_forward_frames)
        assert not any(
            bool(frame["hasRouteSkeleton"]) for frame in routed_forward_frames
        )
        assert all(bool(frame["hasSidebar"]) for frame in routed_forward_frames)
    finally:
        context.close()
