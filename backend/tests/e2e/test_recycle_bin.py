from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Locator, Request, Route, expect

from tests.e2e.browser_support import authenticated_context as _authenticated_context
from tests.e2e.workspace_network_support import ApiRequest, api_request_key

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_recycle_bin_keeps_baseline_then_paginates_six_table_rows(
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
    resume_ids: list[str] = []
    visible_count = 1

    def fulfill_seeded_trash(route: Route) -> None:
        response = route.fetch()
        payload = response.json()
        seeded_items = [
            item
            for item in payload["data"]["deletedResumes"]
            if item["id"] in resume_ids
        ]
        payload["data"]["deletedResumes"] = seeded_items[:visible_count]
        payload["data"]["deletedTemplates"] = []
        route.fulfill(
            response=response,
            content_type="application/json",
            body=json.dumps(payload),
        )

    try:
        for index in range(7):
            create_response = context.request.post(
                f"{frontend_url}/api/resumes",
                data={
                    "documentLocale": "zh",
                    "title": f"Recycle height {index + 1}",
                },
            )
            assert create_response.ok
            resume_id = create_response.json()["data"]["resume"]["id"]
            resume_ids.append(resume_id)
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            assert trash_response.ok

        page.route("**/api/workspace/pages/trash", fulfill_seeded_trash)
        surface_heights: dict[int, float] = {}

        for item_count in range(8):
            visible_count = item_count
            page.goto(f"{frontend_url}/trash", wait_until="networkidle")
            surface = page.locator('[data-slot="recycle-bin-panel"]')
            surface.wait_for(state="visible")
            table_rows = surface.locator(
                '[data-slot="trash-table"] '
                '[data-slot="table-body"] > [data-slot="table-row"]'
            )
            expect(table_rows).to_have_count(min(item_count, 6))
            surface_heights[item_count] = surface.evaluate(
                "element => element.getBoundingClientRect().height"
            )
            pagination = surface.locator('[data-slot="pagination"]')
            expect(pagination).to_have_count(1 if item_count > 6 else 0)

            if item_count == 6:
                scroll_state = page.evaluate(
                    """
                    () => {
                      const content = document.querySelector(
                        '[data-slot="trash-list-content"]',
                      );
                      if (!content) {
                        throw new Error('Missing trash list content');
                      }

                      return {
                        contentClientHeight: content.clientHeight,
                        contentScrollHeight: content.scrollHeight,
                      };
                    }
                    """
                )
                assert scroll_state["contentScrollHeight"] == pytest.approx(
                    scroll_state["contentClientHeight"], abs=1
                )

        for item_count in range(1, 5):
            assert surface_heights[item_count] == pytest.approx(
                surface_heights[0], abs=1
            )
        for item_count in range(5, 7):
            assert surface_heights[item_count] > surface_heights[item_count - 1]
        assert surface_heights[7] > surface_heights[6]

        pagination = page.locator('[data-slot="pagination"]')
        pagination.locator('[data-slot="pagination-link"]').last.click()
        page.wait_for_url(f"{frontend_url}/trash?page=2")
        expect(
            page.locator(
                '[data-slot="trash-table"] '
                '[data-slot="table-body"] > [data-slot="table-row"]'
            )
        ).to_have_count(1)
        second_page_height = page.locator('[data-slot="recycle-bin-panel"]').evaluate(
            "element => element.getBoundingClientRect().height"
        )
        assert second_page_height == pytest.approx(surface_heights[0], abs=1)
    finally:
        for resume_id in resume_ids:
            context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_recycle_bin_thumbnail_renders_full_resume_content(
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
    resume_id: str | None = None
    title = "Recycle thumbnail content"

    try:
        create_response = context.request.post(
            f"{frontend_url}/api/resumes",
            data={"documentLocale": "zh", "title": title},
        )
        assert create_response.ok
        created = create_response.json()["data"]["resume"]
        resume_id = created["id"]
        sections = [
            {
                "id": f"thumbnail-section-{index}",
                "kind": "simple_list",
                "title": f"Thumbnail section {index + 1}",
                "items": [
                    {
                        "id": f"thumbnail-section-{index}-content",
                        "content": (
                            "<ul><li>First detail</li><li>Second detail</li></ul>"
                        ),
                    }
                ],
            }
            for index in range(4)
        ]
        save_response = context.request.put(
            f"{frontend_url}/api/resumes/{resume_id}",
            data={
                "title": title,
                "documentLocale": created["documentLocale"],
                "resume": {
                    **created["resume"],
                    "basic": {
                        **created["resume"]["basic"],
                        "name": "Thumbnail Candidate",
                        "email": "thumbnail@example.com",
                    },
                    "sections": sections,
                },
                "jobBrief": created["jobBrief"],
                "typography": created["typography"],
                "template": created["template"],
                "templateSettings": created["templateSettings"],
            },
        )
        assert save_response.ok

        geometry_script = """
            element => {
              const pageRect = element.getBoundingClientRect();
              const sections = [
                ...element.querySelectorAll('[data-resume-section-id]'),
              ];
              const contentBottom = sections.length > 0
                ? Math.max(
                    ...sections.map(
                      section => section.getBoundingClientRect().bottom,
                    ),
                  )
                : pageRect.top;

              return {
                contentFillRatio:
                  (contentBottom - pageRect.top) / pageRect.height,
                pageHeight: pageRect.height,
                sectionCount: sections.length,
              };
            }
        """
        page.goto(f"{frontend_url}/resume", wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        active_thumbnail_page = (
            page.locator("a", has_text=title).locator("article.resume-page").first
        )
        active_thumbnail_page.wait_for(state="visible")
        active_geometry = active_thumbnail_page.evaluate(geometry_script)
        assert active_geometry["sectionCount"] == 4, active_geometry
        assert active_geometry["contentFillRatio"] >= 0.4, active_geometry

        trash_response = context.request.post(
            f"{frontend_url}/api/resumes/{resume_id}/trash"
        )
        assert trash_response.ok

        page.goto(f"{frontend_url}/trash", wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        row = page.locator(
            '[data-slot="trash-table"] '
            '[data-slot="table-body"] > [data-slot="table-row"]',
            has_text=title,
        )
        expect(row).to_have_count(1)
        thumbnail_page = row.locator("article.resume-page").first
        thumbnail_page.wait_for(state="visible")
        geometry = thumbnail_page.evaluate(geometry_script)

        assert geometry["sectionCount"] == active_geometry["sectionCount"]
        assert geometry["contentFillRatio"] == pytest.approx(
            active_geometry["contentFillRatio"], abs=0.01
        )
    finally:
        if resume_id:
            context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize(
    ("locale", "actions_label", "menu_labels"),
    [
        ("zh-CN", "操作", ["预览", "恢复", "删除"]),
        ("en-US", "Actions", ["Preview", "Restore", "Delete"]),
    ],
    ids=["zh", "en"],
)
def test_recycle_bin_row_menu_fits_localized_actions(
    browser: Browser,
    workspace_servers: tuple[str, str],
    locale: str,
    actions_label: str,
    menu_labels: list[str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale=locale,
        viewport={"width": 1280, "height": 800},
    )
    page = context.new_page()
    resume_id: str | None = None
    title = f"Localized trash menu {locale}"

    try:
        create_response = context.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh" if locale == "zh-CN" else "en",
                "title": title,
            },
        )
        assert create_response.ok
        resume_id = create_response.json()["data"]["resume"]["id"]
        trash_response = context.request.post(
            f"{frontend_url}/api/resumes/{resume_id}/trash"
        )
        assert trash_response.ok

        page.goto(f"{frontend_url}/trash", wait_until="networkidle")
        page.get_by_role("button", name=f"{actions_label}: {title}", exact=True).click()
        menu = page.locator('[data-slot="dropdown-menu-content"]')
        expect(menu).to_be_visible()
        assert menu.get_by_role("menuitem").all_inner_texts() == menu_labels
        geometry = menu.evaluate(
            """
            element => ({
              width: Number.parseFloat(getComputedStyle(element).width),
              clientWidth: element.clientWidth,
              scrollWidth: element.scrollWidth,
              itemOverflow: [...element.querySelectorAll('[role="menuitem"]')]
                .map(item => item.scrollWidth > item.clientWidth),
            })
            """
        )
        assert geometry["width"] == pytest.approx(128, abs=1)
        assert geometry["scrollWidth"] <= geometry["clientWidth"]
        assert geometry["itemOverflow"] == [False, False, False]
    finally:
        if resume_id:
            context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_recycle_bin_bulk_actions_appear_after_selection(
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
    resume_ids: list[str] = []
    titles = ["Bulk selection one", "Bulk selection two"]

    try:
        for title in titles:
            create_response = context.request.post(
                f"{frontend_url}/api/resumes",
                data={"documentLocale": "zh", "title": title},
            )
            assert create_response.ok
            resume_id = create_response.json()["data"]["resume"]["id"]
            resume_ids.append(resume_id)
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            assert trash_response.ok

        page.goto(f"{frontend_url}/trash", wait_until="networkidle")
        bulk_actions = page.locator('[data-slot="trash-bulk-actions"]')
        expect(bulk_actions).to_have_attribute("data-state", "closed")
        expect(bulk_actions).to_have_attribute("aria-hidden", "true")
        for title in titles:
            expect(
                page.get_by_role("button", name=f"操作: {title}", exact=True)
            ).to_have_count(1)

        page.get_by_role("button", name=f"操作: {titles[0]}", exact=True).click()
        expect(page.get_by_role("menuitem", name="预览", exact=True)).to_be_visible()
        expect(page.get_by_role("menuitem", name="恢复", exact=True)).to_be_visible()
        delete_menu_item = page.get_by_role("menuitem", name="删除", exact=True)
        expect(delete_menu_item).to_be_visible()
        menu_groups = page.locator('[data-slot="dropdown-menu-group"]')
        expect(menu_groups).to_have_count(2)
        assert menu_groups.nth(0).get_by_role("menuitem").all_inner_texts() == [
            "预览",
            "恢复",
        ]
        assert menu_groups.nth(1).get_by_role("menuitem").all_inner_texts() == ["删除"]
        page.keyboard.press("Escape")

        first_selection = page.get_by_role("checkbox", name=f"选择: {titles[0]}")
        second_selection = page.get_by_role("checkbox", name=f"选择: {titles[1]}")
        first_selection.check()
        expect(bulk_actions).to_have_attribute("data-state", "open")
        expect(bulk_actions).to_have_attribute("aria-hidden", "false")
        bulk_restore = page.get_by_role("button", name="批量恢复", exact=True)
        expect(bulk_restore).to_be_visible()
        bulk_delete = bulk_actions.get_by_role("button", name="彻底删除", exact=True)
        expect(bulk_delete).to_be_visible()
        bulk_delete.click()
        expect(page.get_by_text("确认彻底删除这份简历？", exact=True)).to_be_visible()
        page.get_by_role("button", name="取消", exact=True).click()
        expect(bulk_actions).to_have_attribute("data-state", "open")

        second_selection.check()
        expect(bulk_actions).to_have_attribute("data-state", "open")
        expect(bulk_actions).to_have_attribute("aria-hidden", "false")
        expect(bulk_restore).to_have_attribute("data-size", "default")
        expect(bulk_delete).to_have_attribute("data-variant", "destructive")
        expect(bulk_delete).to_have_attribute("data-size", "default")
        bulk_delete.click()
        expect(page.get_by_text("确认彻底删除这些简历？", exact=True)).to_be_visible()
        page.get_by_role("button", name="取消", exact=True).click()
        expect(bulk_actions).to_have_attribute("data-state", "open")

        second_selection.uncheck()
        expect(bulk_actions).to_have_attribute("data-state", "open")
        expect(bulk_actions).to_have_attribute("aria-hidden", "false")

        first_selection.uncheck()
        expect(bulk_actions).to_have_attribute("data-state", "closed")
        expect(bulk_actions).to_have_attribute("aria-hidden", "true")

        select_all = page.get_by_role("checkbox", name="全选", exact=True)
        select_all.check()
        expect(bulk_actions).to_have_attribute("data-state", "open")
        select_all.uncheck()
        expect(bulk_actions).to_have_attribute("data-state", "closed")

        page.set_viewport_size({"width": 390, "height": 844})
        mobile_overflow = page.evaluate(
            """
            () => {
              const tableContainer = document.querySelector(
                '[data-slot="trash-table"] [data-slot="table-container"]',
              );
              if (!tableContainer) {
                throw new Error('Missing recycle-bin table container');
              }

              return {
                documentClientWidth: document.documentElement.clientWidth,
                documentScrollWidth: document.documentElement.scrollWidth,
                tableClientWidth: tableContainer.clientWidth,
                tableScrollWidth: tableContainer.scrollWidth,
              };
            }
            """
        )
        assert mobile_overflow["documentScrollWidth"] == pytest.approx(
            mobile_overflow["documentClientWidth"], abs=1
        )
        assert mobile_overflow["tableScrollWidth"] > mobile_overflow["tableClientWidth"]
    finally:
        for resume_id in resume_ids:
            context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


@pytest.mark.browser_smoke
@pytest.mark.parametrize("collection", ["resumes", "templates"])
@pytest.mark.parametrize("operation", ["delete", "restore"])
def test_recycle_bin_partial_batch_keeps_only_unfinished_items(
    browser: Browser,
    workspace_servers: tuple[str, str],
    collection: str,
    operation: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, locale="en-US")
    context.add_init_script("localStorage.setItem('reseno-locale', 'en')")
    page = context.new_page()
    items: dict[str, str] = {}
    attempts: list[str] = []

    try:
        for index in range(2):
            title = f"Partial batch {collection} {operation} {index}"
            if collection == "resumes":
                data = {"documentLocale": "en", "title": title}
            else:
                preset = json.loads(
                    (BACKEND_ROOT / "app/services/template_presets.json").read_text()
                )["minimal"]
                data = {
                    "template": {
                        "preset": "minimal",
                        "name": title,
                        "description": "",
                        **{
                            key: preset[key]
                            for key in ("layout", "typography", "settings")
                        },
                    }
                }
            response = context.request.post(
                f"{frontend_url}/api/{collection}", data=data
            )
            assert response.ok, response.text()
            item_id = response.json()["data"][collection.removesuffix("s")]["id"]
            items[item_id] = title
            assert context.request.post(
                f"{frontend_url}/api/{collection}/{item_id}/trash"
            ).ok

        def fail_second_item(route: Route) -> None:
            parts = urlparse(route.request.url).path.split("/")
            item_id = parts[3]
            expected_method = "DELETE" if operation == "delete" else "POST"
            if item_id not in items or route.request.method != expected_method:
                route.continue_()
                return
            attempts.append(item_id)
            if len(attempts) == 2:
                route.fulfill(
                    status=503,
                    json={"code": 50000, "message": "REQUEST_FAILED", "data": None},
                )
            else:
                route.continue_()

        page.route(f"**/api/{collection}/**", fail_second_item)
        page.goto(f"{frontend_url}/trash?tab={collection}", wait_until="networkidle")
        for title in items.values():
            page.get_by_role("checkbox", name=f"Select: {title}", exact=True).check()

        if operation == "delete":
            delete_button = page.get_by_role(
                "button", name="Permanently Delete", exact=True
            )
            delete_button.click()
            dialog = page.get_by_role("alertdialog")
            confirm_delete = dialog.locator(delete_button)
            confirm_delete.click()
        else:
            page.get_by_role("button", name="Restore selected", exact=True).click()

        expect(
            page.get_by_text("Request failed. Please try again later.", exact=True)
        ).to_be_visible()
        assert len(attempts) == 2
        succeeded, failed = attempts
        expect(page.get_by_text(items[succeeded], exact=True)).to_have_count(0)
        expect(page.get_by_text(items[failed], exact=True)).to_have_count(1)

        if operation == "delete":
            confirm_delete.click()
            expect(dialog).to_have_count(0)
        else:
            page.get_by_role("button", name="Restore selected", exact=True).click()

        expect(page.get_by_text(items[failed], exact=True)).to_have_count(0)
        assert attempts == [succeeded, failed, failed]
        source = context.request.get(f"{frontend_url}/api/{collection}").json()["data"]
        active_ids = {item["id"] for item in source[collection]}
        assert (set(items) <= active_ids) is (operation == "restore")
    finally:
        for item_id in items:
            context.request.post(f"{frontend_url}/api/{collection}/{item_id}/trash")
            context.request.delete(f"{frontend_url}/api/{collection}/{item_id}")
        context.close()


def test_recycle_bin_preview_is_read_only_for_resume_and_template(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
    )
    page = context.new_page()
    resume_id: str | None = None
    template_id: str | None = None
    resume_title = "Trash preview resume"
    resume_marker = "回收站实际预览内容"
    preview_writes: list[ApiRequest] = []

    try:
        create_resume_response = context.request.post(
            f"{frontend_url}/api/resumes",
            data={"documentLocale": "zh", "title": resume_title},
        )
        assert create_resume_response.ok
        resume_id = create_resume_response.json()["data"]["resume"]["id"]
        resume_detail = context.request.get(
            f"{frontend_url}/api/resumes/{resume_id}"
        ).json()["data"]["resume"]
        resume_detail["resume"]["basic"]["name"] = resume_marker
        save_resume_response = context.request.put(
            f"{frontend_url}/api/resumes/{resume_id}",
            data={
                key: resume_detail.get(key)
                for key in (
                    "title",
                    "documentLocale",
                    "resume",
                    "jobBrief",
                    "typography",
                    "template",
                    "templateSettings",
                )
            },
        )
        assert save_resume_response.ok
        trash_resume_response = context.request.post(
            f"{frontend_url}/api/resumes/{resume_id}/trash"
        )
        assert trash_resume_response.ok

        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        page.get_by_role(
            "button",
            name="创建可编辑副本",
            exact=True,
        ).click()
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = urlparse(page.url).path.rsplit("/", maxsplit=1)[-1]
        template_route_data = context.request.get(
            f"{frontend_url}/api/workspace/pages/templates"
        ).json()["data"]
        template_title = next(
            item["name"]
            for item in template_route_data["customTemplates"]
            if item["id"] == template_id
        )
        trash_template_response = context.request.post(
            f"{frontend_url}/api/templates/{template_id}/trash"
        )
        assert trash_template_response.ok

        page.goto(f"{frontend_url}/trash", wait_until="networkidle")

        def record_preview_write(request: Request) -> None:
            api_request = api_request_key(request)
            if api_request and request.method in {"PATCH", "POST", "PUT", "DELETE"}:
                preview_writes.append(api_request)

        page.on("request", record_preview_write)

        def preview_item(title: str, expected_text: str | None = None) -> Locator:
            trigger = page.get_by_role("button", name=f"操作: {title}", exact=True)
            trigger.click()
            page.get_by_role("menuitem", name="预览", exact=True).click()
            dialog = page.get_by_role("dialog", name=f"预览: {title}", exact=True)
            expect(dialog).to_be_visible()
            initial_focus = dialog.locator('[data-slot="dialog-title"]')
            expect(initial_focus).to_have_attribute("tabindex", "-1")
            expect(initial_focus).to_be_focused()
            dialog.locator('[data-resume-pagination-ready="true"]').wait_for(
                state="visible"
            )
            expect(dialog.locator('[data-slot="dialog-header"]')).to_have_count(0)
            expect(dialog.get_by_text("实时预览", exact=True)).to_have_count(0)
            expect(
                dialog.locator('article[data-export-root="resume-page"]').first
            ).to_be_visible()
            preview_shell = dialog.locator('[data-slot="trash-preview-dialog"]')
            shell_geometry = preview_shell.evaluate(
                """
                (shell) => {
                  const content = shell.closest('[data-slot="dialog-content"]');
                  const previewCard = shell.querySelector('.resume-preview-card');
                  const canvasViewport = shell.querySelector(
                    '[data-slot="document-canvas-viewport"]',
                  );
                  if (!content || !previewCard || !canvasViewport) {
                    throw new Error('Missing recycle preview surface');
                  }

                  const contentStyle = getComputedStyle(content);
                  const shellStyle = getComputedStyle(shell);
                  const cardStyle = getComputedStyle(previewCard);
                  const canvasViewportStyle = getComputedStyle(canvasViewport);
                  const contentRect = content.getBoundingClientRect();
                  const shellRect = shell.getBoundingClientRect();
                  const cardRect = previewCard.getBoundingClientRect();
                  return {
                    backgroundColor: contentStyle.backgroundColor,
                    borderTopWidth: contentStyle.borderTopWidth,
                    contentRadii: [
                      contentStyle.borderTopLeftRadius,
                      contentStyle.borderTopRightRadius,
                      contentStyle.borderBottomRightRadius,
                      contentStyle.borderBottomLeftRadius,
                    ],
                    cardRadii: [
                      cardStyle.borderTopLeftRadius,
                      cardStyle.borderTopRightRadius,
                      cardStyle.borderBottomRightRadius,
                      cardStyle.borderBottomLeftRadius,
                    ],
                    contentOverflowX: contentStyle.overflowX,
                    contentOverflowY: contentStyle.overflowY,
                    shellOverflowY: shellStyle.overflowY,
                    canvasViewportOverflowY: canvasViewportStyle.overflowY,
                    canvasViewportClientHeight: canvasViewport.clientHeight,
                    canvasViewportScrollHeight: canvasViewport.scrollHeight,
                    contentRect: {
                      top: contentRect.top,
                      right: contentRect.right,
                      bottom: contentRect.bottom,
                      left: contentRect.left,
                    },
                    shellRect: {
                      top: shellRect.top,
                      right: shellRect.right,
                      bottom: shellRect.bottom,
                      left: shellRect.left,
                    },
                    cardTop: cardRect.top,
                    paddingTop: shellStyle.paddingTop,
                    paddingRight: shellStyle.paddingRight,
                    paddingBottom: shellStyle.paddingBottom,
                    paddingLeft: shellStyle.paddingLeft,
                  };
                }
                """
            )
            assert shell_geometry["backgroundColor"] == "rgba(0, 0, 0, 0)"
            assert shell_geometry["borderTopWidth"] == "0px"
            assert shell_geometry["contentRadii"] == shell_geometry["cardRadii"]
            assert all(
                float(radius.removesuffix("px")) > 0
                for radius in shell_geometry["contentRadii"]
            )
            assert {
                shell_geometry["contentOverflowX"],
                shell_geometry["contentOverflowY"],
            } == {"hidden"}
            assert shell_geometry["shellOverflowY"] == "hidden"
            assert shell_geometry["canvasViewportOverflowY"] == "auto"
            assert (
                shell_geometry["canvasViewportScrollHeight"]
                > shell_geometry["canvasViewportClientHeight"]
            )
            for edge in ("top", "right", "bottom", "left"):
                assert shell_geometry["shellRect"][edge] == pytest.approx(
                    shell_geometry["contentRect"][edge], abs=1
                )
            assert {
                shell_geometry["paddingTop"],
                shell_geometry["paddingRight"],
                shell_geometry["paddingBottom"],
                shell_geometry["paddingLeft"],
            } == {"0px"}
            assert shell_geometry["cardTop"] == pytest.approx(
                shell_geometry["contentRect"]["top"], abs=1
            )
            expect(initial_focus).to_be_focused()
            expect(
                dialog.get_by_role("button", name="关闭", exact=True)
            ).not_to_be_focused()
            if expected_text:
                expect(
                    dialog.get_by_text(expected_text, exact=True).last
                ).to_be_visible()
            close_button = dialog.get_by_role("button", name="关闭", exact=True)
            close_button.click()
            expect(dialog).to_be_hidden()
            expect(trigger).to_be_focused()
            return trigger

        preview_item(resume_title, resume_marker)

        page.get_by_role("tab").filter(has_text="模板").click()
        preview_item(template_title)

        assert preview_writes == []
        expect(
            page.get_by_role("button", name=f"操作: {template_title}", exact=True)
        ).to_have_count(1)
        deleted_route_data = context.request.get(
            f"{frontend_url}/api/workspace/pages/trash"
        ).json()["data"]
        assert resume_id in {
            item["id"] for item in deleted_route_data["deletedResumes"]
        }
        assert template_id in {
            item["id"] for item in deleted_route_data["deletedTemplates"]
        }
    finally:
        if resume_id:
            context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        if template_id:
            context.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


def test_recycle_bin_count_badges_contrast_with_their_tab_surfaces(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser, viewport={"width": 1280, "height": 800})
    page = context.new_page()

    def tab_surface_colors() -> dict[str, Any]:
        return page.locator('[data-slot="tabs-list"]').evaluate(
            """
            (list) => {
              const tabs = [...list.querySelectorAll('[data-slot="tabs-trigger"]')];
              const indicator = list.querySelector(':scope > span[aria-hidden="true"]');
              return {
                listBackground: getComputedStyle(list).backgroundColor,
                indicatorBackground: indicator
                  ? getComputedStyle(indicator).backgroundColor
                  : null,
                tabs: tabs.map((tab) => {
                  const badge = tab.querySelector('[data-slot="badge"]');
                  return {
                    state: tab.getAttribute("data-state"),
                    badgeBackground: badge
                      ? getComputedStyle(badge).backgroundColor
                      : null,
                  };
                }),
              };
            }
            """
        )

    def assert_count_badge_contrast() -> None:
        colors = tab_surface_colors()
        assert len(colors["tabs"]) == 2
        active = next(tab for tab in colors["tabs"] if tab["state"] == "active")
        inactive = next(tab for tab in colors["tabs"] if tab["state"] == "inactive")
        assert inactive["badgeBackground"] != colors["listBackground"]
        assert active["badgeBackground"] != colors["indicatorBackground"]
        assert active["badgeBackground"] != inactive["badgeBackground"]

    try:
        page.goto(f"{frontend_url}/trash", wait_until="networkidle")
        tabs = page.locator('[data-slot="tabs-trigger"]')
        expect(tabs).to_have_count(2)

        assert_count_badge_contrast()

        inactive_tab = page.locator('[data-slot="tabs-trigger"][data-state="inactive"]')
        inactive_tab_id = inactive_tab.get_attribute("id")
        assert inactive_tab_id
        target_tab = page.locator(f'[data-slot="tabs-trigger"][id="{inactive_tab_id}"]')
        target_tab.click()
        expect(target_tab).to_have_attribute("data-state", "active")
        assert_count_badge_contrast()

        page.evaluate("document.documentElement.classList.add('dark')")
        assert_count_badge_contrast()
    finally:
        context.close()
