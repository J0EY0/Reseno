from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, expect

from tests.e2e.agent_session_support import seed_pending_agent_draft
from tests.e2e.browser_support import authenticated_context as _authenticated_context
from tests.template_fixtures import portable_template

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


@pytest.mark.parametrize(
    (
        "basic_info",
        "avatar_position",
        "avatar_width",
        "avatar_height",
        "offset_x",
        "offset_y",
        "summary",
    ),
    [
        ("centered", "right", 25, 32, 0, 0, ""),
        ("centered", "left", 25, 32, 0, 0, ""),
        (
            "centered",
            "right",
            25,
            32,
            0,
            0,
            "具备软件开发经验，关注工程质量和产品体验。" * 4,
        ),
        (
            "centered",
            "left",
            25,
            32,
            0,
            0,
            "具备软件开发经验，关注工程质量和产品体验。" * 4,
        ),
        (
            "centered",
            "right",
            25,
            32,
            0,
            0,
            "具备软件开发经验，关注工程质量和产品体验。" * 12,
        ),
        (
            "centered",
            "left",
            25,
            32,
            0,
            0,
            "具备软件开发经验，关注工程质量和产品体验。" * 12,
        ),
        (
            "centered",
            "right",
            48,
            56,
            -4,
            6,
            "具备软件开发经验，关注工程质量和产品体验。" * 4,
        ),
        (
            "centered",
            "left",
            48,
            56,
            4,
            6,
            "具备软件开发经验，关注工程质量和产品体验。" * 4,
        ),
        (
            "left",
            "right",
            25,
            32,
            -12,
            10,
            "具备软件开发经验，关注工程质量和产品体验。" * 4,
        ),
        (
            "left",
            "left",
            25,
            32,
            12,
            10,
            "具备软件开发经验，关注工程质量和产品体验。" * 4,
        ),
        (
            "profile",
            "center",
            25,
            32,
            0,
            12,
            "具备软件开发经验，关注工程质量和产品体验。" * 4,
        ),
        (
            "split",
            "right",
            25,
            32,
            -12,
            10,
            "具备软件开发经验，关注工程质量和产品体验。" * 4,
        ),
        (
            "sidebar",
            "center",
            25,
            32,
            0,
            12,
            "具备软件开发经验，关注工程质量和产品体验。" * 4,
        ),
        ("left", "left", 25, 32, 12, 0, ""),
        ("split", "right", 25, 32, -12, 0, ""),
    ],
    ids=[
        "right",
        "left",
        "right-summary",
        "left-summary",
        "right-long-summary",
        "left-long-summary",
        "right-large-offset-summary",
        "left-large-offset-summary",
        "aligned-right-offset-summary",
        "aligned-left-offset-summary",
        "profile-center-offset",
        "split-right-offset-summary",
        "sidebar-offset",
        "aligned-left-horizontal-offset",
        "split-right-horizontal-offset",
    ],
)
def test_short_header_keeps_avatar_above_resume_sections(
    browser: Browser,
    workspace_servers: tuple[str, str],
    tmp_path: Path,
    basic_info: str,
    avatar_position: str,
    avatar_width: int,
    avatar_height: int,
    offset_x: int,
    offset_y: int,
    summary: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 960}
    )
    page = context.new_page()
    template_id: str | None = None
    resume_id: str | None = None
    try:
        template = portable_template("Short header avatar")
        template["typography"]["fontSize"] = 12
        template["layout"].update(
            basicInfo=basic_info,
            avatarPosition=avatar_position,
            avatarWidth=avatar_width,
            avatarHeight=avatar_height,
            avatarOffsetX=offset_x,
            avatarOffsetY=offset_y,
        )
        response = context.request.post(
            f"{frontend_url}/api/templates", data={"template": template}
        )
        assert response.ok
        template_id = response.json()["data"]["template"]["id"]
        response = context.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": "Avatar layout",
                "template": template_id,
            },
        )
        assert response.ok
        created = response.json()["data"]["resume"]
        resume_id = created["id"]
        created["resume"]["basic"].update(
            name="测试姓名",
            phone="+86 13800000000",
            email="name@example.com",
            summary=summary,
            avatar="data:image/gif;base64,R0lGODlhAQABAIAAAJSjuJSjuCwAAAAAAQABAAACAUwAOw==",
        )
        education = created["resume"]["sections"][0]
        education["items"][0].update(
            school="示例大学",
            major="计算机技术",
            degree="硕士",
            period="2024.09 - 至今",
        )
        response = context.request.put(
            f"{frontend_url}/api/resumes/{resume_id}",
            data={
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
            },
        )
        assert response.ok
        for route in (
            f"/resume/{resume_id}",
            f"/pdf-export?resumeId={resume_id}&documentLocale=zh",
        ):
            page.goto(f"{frontend_url}{route}", wait_until="networkidle")
            if route.startswith("/pdf-export"):
                page.locator('main[data-pdf-ready="true"]').wait_for(state="visible")
            preview = page.locator('[data-export-root="resume-page"]:visible').first
            avatar = preview.locator('[data-avatar-frame="true"]')
            expect(avatar).to_be_visible()
            geometry = preview.evaluate(
                """resumePage => {
                  const avatar = resumePage.querySelector('[data-avatar-frame="true"]');
                  const header = resumePage.querySelector(
                    '[data-resume-section-id="basic"]'
                  );
                  const section = resumePage.querySelector('section');
                  const avatarRect = avatar.getBoundingClientRect();
                  const identity = header.querySelector('h1').parentElement;
                  const nameRange = document.createRange();
                  nameRange.selectNodeContents(header.querySelector('h1'));
                  const nameRect = nameRange.getBoundingClientRect();
                  const headerRect = header.getBoundingClientRect();
                  const summary = header.querySelector('p');
                  const summaryRange = document.createRange();
                  if (summary) summaryRange.selectNodeContents(summary);
                  const summaryRects = Array.from(summaryRange.getClientRects());
                  const walker = document.createTreeWalker(
                    resumePage, NodeFilter.SHOW_TEXT
                  );
                  const overlaps = [];
                  let node;
                  while ((node = walker.nextNode())) {
                    if (!node.textContent.trim()) continue;
                    const range = document.createRange();
                    range.selectNodeContents(node);
                    for (const rect of range.getClientRects()) {
                      if (rect.right > avatarRect.left + 1 &&
                          rect.left < avatarRect.right - 1 &&
                          rect.bottom > avatarRect.top + 1 &&
                          rect.top < avatarRect.bottom - 1) {
                        overlaps.push(node.textContent);
                      }
                    }
                  }
                  return {
                    avatarBottom: avatarRect.bottom,
                    headerBottom: header.getBoundingClientRect().bottom,
                    sectionTop: section.getBoundingClientRect().top,
                    identityBottom: identity.getBoundingClientRect().bottom,
                    nameCenter: (nameRect.left + nameRect.right) / 2,
                    headerCenter: (headerRect.left + headerRect.right) / 2,
                    summaryTop: summaryRects[0]?.top,
                    summaryBelowAvatar: summaryRects.some(rect =>
                      rect.top >= avatarRect.bottom &&
                      (rect.left < avatarRect.right && rect.right > avatarRect.left)
                    ),
                    overlaps,
                  };
                }"""
            )
            surface = "export" if route.startswith("/pdf-export") else "preview"
            preview.screenshot(path=str(tmp_path / f"avatar-{surface}.png"))
            assert geometry["avatarBottom"] <= geometry["headerBottom"] + 1, geometry
            if basic_info != "sidebar":
                assert geometry["avatarBottom"] <= geometry["sectionTop"] + 1, geometry
            assert geometry["overlaps"] == [], geometry
            if basic_info == "centered":
                assert abs(geometry["nameCenter"] - geometry["headerCenter"]) <= 1, (
                    geometry
                )
            if basic_info == "centered" and summary:
                assert geometry["summaryTop"] < geometry["avatarBottom"], geometry
                assert geometry["summaryTop"] <= geometry["identityBottom"] + 20, (
                    geometry
                )
                if len(summary) > 200:
                    assert geometry["summaryBelowAvatar"], geometry
    finally:
        if resume_id:
            context.request.post(f"{frontend_url}/api/resumes/{resume_id}/trash")
            context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        if template_id:
            context.request.post(f"{frontend_url}/api/templates/{template_id}/trash")
            context.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


def test_summary_wrapping_avatar_paginates_without_splitting_photo(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 960}
    )
    page = context.new_page()
    resume_id: str | None = None
    try:
        response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={"documentLocale": "zh", "template": "minimal"},
        )
        assert response.ok
        saved = response.json()["data"]["resume"]
        resume_id = saved["id"]
        saved["typography"]["fontSize"] = 16
        saved["resume"]["basic"].update(
            name="测试姓名",
            phone="+86 13800000000",
            email="name@example.com",
            summary="具备软件开发经验，关注工程质量和产品体验。" * 80,
            avatar="data:image/gif;base64,R0lGODlhAQABAIAAAJSjuJSjuCwAAAAAAQABAAACAUwAOw==",
        )
        response = page.request.put(
            f"{frontend_url}/api/resumes/{resume_id}",
            data={
                key: saved[key]
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
        assert response.ok
        for route in (
            f"/resume/{resume_id}",
            f"/pdf-export?resumeId={resume_id}&documentLocale=zh",
        ):
            page.goto(f"{frontend_url}{route}", wait_until="networkidle")
            page.locator('[data-resume-pagination-ready="true"]:visible').wait_for()
            if route.startswith("/pdf-export"):
                page.locator('main[data-pdf-ready="true"]').wait_for(state="visible")
            pages = page.locator('[data-export-root="resume-page"]:visible')
            expect(pages).to_have_count(2)
            geometry = pages.evaluate_all(
                """pages => {
                  const firstViewport = pages[0].querySelector(
                    '.resume-page-content-viewport'
                  ).getBoundingClientRect();
                  const lastViewport = pages.at(-1).querySelector(
                    '.resume-page-content-viewport'
                  ).getBoundingClientRect();
                  const avatar = pages[0].querySelector(
                    '[data-avatar-frame="true"]'
                  ).getBoundingClientRect();
                  return {
                    avatarBottom: avatar.bottom,
                    firstPageBottom: firstViewport.bottom,
                    firstPageHeight: firstViewport.height,
                    nominalPageHeight: lastViewport.height,
                  };
                }"""
            )
            assert geometry["avatarBottom"] <= geometry["firstPageBottom"] + 1, geometry
            assert geometry["firstPageHeight"] >= geometry["nominalPageHeight"] * 0.9, (
                geometry
            )
    finally:
        if resume_id:
            context.request.post(f"{frontend_url}/api/resumes/{resume_id}/trash")
            context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_summary_review_badge_does_not_overlap_avatar(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1672, "height": 960},
        reduced_motion="reduce",
    )
    page = context.new_page()
    resume_id: str | None = None
    try:
        resume_id, detail, _ = seed_pending_agent_draft(
            page,
            frontend_url,
            message_id="avatar-summary-review",
            summary="具备软件开发经验，关注工程质量和产品体验。",
        )
        saved = detail["resume"]
        saved["resume"]["basic"].update(
            name="测试姓名",
            phone="+86 13800000000",
            email="name@example.com",
            avatar="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==",
        )
        saved["typography"]["fontSize"] = 12
        response = page.request.put(
            f"{frontend_url}/api/resumes/{resume_id}",
            data={
                key: saved[key]
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
        assert response.ok
        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        preview = page.locator('[data-export-root="resume-page"]:visible').first
        expect(preview.locator('[data-avatar-frame="true"]')).to_be_visible()
        expect(
            preview.locator('header > p [data-resume-diff-badge="true"]')
        ).to_be_visible()
        geometry = preview.evaluate(
            """resumePage => {
              const avatar = resumePage.querySelector(
                '[data-avatar-frame="true"]'
              ).getBoundingClientRect();
              const badge = resumePage.querySelector(
                'header > p [data-resume-diff-badge="true"]'
              ).getBoundingClientRect();
              return {
                avatar: avatar.toJSON(),
                badge: badge.toJSON(),
                overlaps: avatar.left < badge.right && avatar.right > badge.left &&
                  avatar.top < badge.bottom && avatar.bottom > badge.top,
              };
            }"""
        )
        assert not geometry["overlaps"], geometry
    finally:
        if resume_id:
            context.request.post(f"{frontend_url}/api/resumes/{resume_id}/trash")
            context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_builtin_templates_render_optional_avatars_without_layout_regressions(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="en-US", viewport={"width": 1672, "height": 960}
    )
    page = context.new_page()
    resume_ids: list[str] = []
    template_ids: list[str] = []
    avatar_data_url = (
        "data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw=="
    )

    try:
        for template_id in (
            "minimal",
            "modern",
            "compact",
            "classic",
            "executive",
            "academic",
        ):
            create_response = page.request.post(
                f"{frontend_url}/api/resumes",
                data={
                    "documentLocale": "zh",
                    "title": f"{template_id} optional avatar regression",
                    "template": template_id,
                },
            )
            assert create_response.ok
            created = create_response.json()["data"]["resume"]
            resume_id = created["id"]
            resume_ids.append(resume_id)

            page.goto(
                f"{frontend_url}/resume/{resume_id}",
                wait_until="networkidle",
            )
            preview_page = page.locator(
                '[data-export-root="resume-page"]:visible'
            ).first
            preview_page.wait_for(state="visible")
            assert preview_page.locator('[data-avatar-frame="true"]').count() == 0
            assert preview_page.locator('[data-avatar-image="true"]').count() == 0

            save_payload = {
                "title": created["title"],
                "documentLocale": created["documentLocale"],
                "resume": {
                    **created["resume"],
                    "basic": {
                        **created["resume"]["basic"],
                        "name": "Example Candidate",
                        "headline": "Software Engineer",
                        "phone": "+86 13800000000",
                        "email": "name@example.com",
                        "location": "Shanghai",
                        "avatar": avatar_data_url,
                    },
                },
                "jobBrief": created["jobBrief"],
                "typography": created["typography"],
                "template": created["template"],
                "templateSettings": created["templateSettings"],
            }
            save_response = page.request.put(
                f"{frontend_url}/api/resumes/{resume_id}",
                data=save_payload,
            )
            assert save_response.ok
            assert save_response.json()["code"] == 0

            page.reload(wait_until="networkidle")
            preview_page = page.locator(
                '[data-export-root="resume-page"]:visible'
            ).first
            expect(
                preview_page.get_by_role("heading", name="Example Candidate")
            ).to_be_visible()
            if template_id == "academic":
                expect(
                    preview_page.locator('[data-avatar-frame="true"]')
                ).to_have_count(0)
                expect(
                    preview_page.locator('[data-avatar-image="true"]')
                ).to_have_count(0)
                expect(preview_page.locator("header h1")).to_have_css(
                    "text-align", "center"
                )
                page.goto(f"{frontend_url}/template/academic", wait_until="networkidle")
                page.get_by_role("button", name="Create Copy", exact=True).click()
                page.wait_for_url(f"{frontend_url}/template/template-*")
                custom_template_id = urlparse(page.url).path.rsplit("/", maxsplit=1)[-1]
                template_ids.append(custom_template_id)
                page.get_by_role("combobox", name="Avatar Position", exact=True).click()
                page.get_by_role("option", name="Right", exact=True).click()
                with page.expect_response(
                    lambda response, expected_template_id=custom_template_id: (
                        response.request.method == "PUT"
                        and urlparse(response.url).path
                        == f"/api/templates/{expected_template_id}"
                    )
                ) as template_save_response:
                    page.keyboard.press("Control+S")
                assert template_save_response.value.ok
                save_payload["template"] = custom_template_id
                save_response = page.request.put(
                    f"{frontend_url}/api/resumes/{resume_id}", data=save_payload
                )
                assert save_response.ok
                page.goto(
                    f"{frontend_url}/resume/{resume_id}", wait_until="networkidle"
                )

            avatar_frame = preview_page.locator('[data-avatar-frame="true"]')
            avatar_image = preview_page.locator('img[data-avatar-image="true"]')
            expect(avatar_frame).to_have_count(1)
            expect(avatar_image).to_have_count(1)
            page.wait_for_function(
                "(image) => image.complete && image.naturalWidth > 0",
                arg=avatar_image.element_handle(),
            )

            geometry = preview_page.evaluate(
                """
                (resumePage) => {
                  const avatar = resumePage.querySelector(
                    '[data-avatar-frame="true"]'
                  );
                  if (!(avatar instanceof HTMLElement)) {
                    throw new Error('Avatar frame is unavailable.');
                  }
                  const pageRect = resumePage.getBoundingClientRect();
                  const avatarRect = avatar.getBoundingClientRect();
                  const walker = document.createTreeWalker(
                    resumePage,
                    NodeFilter.SHOW_TEXT
                  );
                  const overlaps = [];
                  let node = walker.nextNode();

                  while (node) {
                    const text = node.textContent?.trim();
                    const parent = node.parentElement;
                    if (text && parent && !parent.closest('[data-avatar-frame]')) {
                      const range = document.createRange();
                      range.selectNodeContents(node);
                      for (const rect of range.getClientRects()) {
                        const intersects =
                          rect.right > avatarRect.left + 1 &&
                          rect.left < avatarRect.right - 1 &&
                          rect.bottom > avatarRect.top + 1 &&
                          rect.top < avatarRect.bottom - 1;
                        if (intersects) overlaps.push(text);
                      }
                    }
                    node = walker.nextNode();
                  }

                  return {
                    avatarInsidePage:
                      avatarRect.left >= pageRect.left - 1 &&
                      avatarRect.top >= pageRect.top - 1 &&
                      avatarRect.right <= pageRect.right + 1 &&
                      avatarRect.bottom <= pageRect.bottom + 1,
                    overlaps,
                  };
                }
                """
            )
            assert geometry["avatarInsidePage"], template_id
            assert geometry["overlaps"] == [], (
                template_id,
                geometry["overlaps"],
            )

            if template_id in {"classic", "academic"}:
                name_alignment = preview_page.locator("header h1").evaluate(
                    "(element) => getComputedStyle(element).textAlign"
                )
                assert name_alignment == (
                    "left" if template_id == "classic" else "center"
                )

            if template_id == "executive":
                name_box = preview_page.locator("header h1").bounding_box()
                email_box = preview_page.get_by_text(
                    "name@example.com", exact=True
                ).bounding_box()
                assert name_box is not None
                assert email_box is not None
                assert email_box["x"] > name_box["x"] + name_box["width"]
    finally:
        for resume_id in resume_ids:
            trash_response = page.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        for template_id in template_ids:
            trash_response = page.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if trash_response.ok:
                page.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


def test_empty_optional_avatar_does_not_reserve_resume_or_export_layout_space(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(
        browser, locale="zh-CN", viewport={"width": 1672, "height": 960}
    )
    page = context.new_page()
    template_id: str | None = None
    resume_id: str | None = None

    def read_header_text_layout() -> list[dict[str, float | str]]:
        preview_page = page.locator('[data-export-root="resume-page"]:visible').first
        preview_page.wait_for(state="visible")
        return preview_page.evaluate(
            """
            (resumePage) => {
              const pageRect = resumePage.getBoundingClientRect();
              const header = resumePage.querySelector('header');
              if (!(header instanceof HTMLElement)) {
                throw new Error('Resume header is unavailable.');
              }

              const result = [];
              const walker = document.createTreeWalker(
                header,
                NodeFilter.SHOW_TEXT
              );
              let node = walker.nextNode();
              while (node) {
                const text = node.textContent?.trim();
                const parent = node.parentElement;
                if (text && parent && !parent.closest('[data-avatar-frame]')) {
                  const range = document.createRange();
                  range.selectNodeContents(node);
                  for (const rect of range.getClientRects()) {
                    result.push({
                      text,
                      left: Math.round((rect.left - pageRect.left) * 10) / 10,
                      top: Math.round((rect.top - pageRect.top) * 10) / 10,
                      width: Math.round(rect.width * 10) / 10,
                      height: Math.round(rect.height * 10) / 10,
                    });
                  }
                }
                node = walker.nextNode();
              }
              return result;
            }
            """
        )

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        with page.expect_response(
            lambda response: (
                response.request.method == "POST"
                and urlparse(response.url).path == "/api/templates"
            )
        ) as create_template_response:
            page.get_by_role("button", name="创建副本", exact=True).click()
        assert create_template_response.value.ok
        saved_template_payload = create_template_response.value.request.post_data_json
        page.wait_for_url(f"{frontend_url}/template/template-*")
        template_id = urlparse(page.url).path.rsplit("/", maxsplit=1)[-1]

        expect(page.get_by_role("combobox", name="头像位置", exact=True)).to_have_text(
            "右侧"
        )
        assert saved_template_payload["template"]["layout"]["avatarPosition"] == "right"

        template_preview = page.locator('[data-export-root="resume-page"]:visible').last
        template_avatar = template_preview.locator('[data-avatar-frame="true"]')
        expect(template_avatar).to_have_count(1)
        expect(
            template_avatar.locator('[data-avatar-placeholder="true"]')
        ).to_have_count(1)
        expect(template_avatar.locator('img[data-avatar-image="true"]')).to_have_count(
            0
        )

        create_response = page.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "zh",
                "title": "Empty optional avatar layout regression",
                "template": template_id,
            },
        )
        assert create_response.ok
        resume_id = create_response.json()["data"]["resume"]["id"]

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        preview_page = page.locator('[data-export-root="resume-page"]:visible').first
        assert preview_page.locator('[data-avatar-frame="true"]').count() == 0
        right_position_layout = read_header_text_layout()
        assert right_position_layout

        page.goto(
            f"{frontend_url}/pdf-export?resumeId={resume_id}&documentLocale=zh",
            wait_until="networkidle",
        )
        page.locator('main[data-pdf-ready="true"]').wait_for(state="visible")
        assert (
            page.locator(
                '[data-export-root="resume-page"]:visible [data-avatar-frame="true"]'
            ).count()
            == 0
        )

        saved_template_payload["template"]["layout"]["avatarPosition"] = "none"
        update_response = page.request.put(
            f"{frontend_url}/api/templates/{template_id}",
            data=saved_template_payload,
        )
        assert update_response.ok

        page.goto(f"{frontend_url}/resume/{resume_id}", wait_until="networkidle")
        hidden_position_layout = read_header_text_layout()
        assert len(right_position_layout) == len(hidden_position_layout)
        for right_rect, hidden_rect in zip(
            right_position_layout, hidden_position_layout, strict=True
        ):
            assert right_rect["text"] == hidden_rect["text"]
            for dimension in ("left", "top", "width", "height"):
                assert (
                    abs(float(right_rect[dimension]) - float(hidden_rect[dimension]))
                    <= 1.0
                ), (right_rect, hidden_rect)
    finally:
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        if template_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()
