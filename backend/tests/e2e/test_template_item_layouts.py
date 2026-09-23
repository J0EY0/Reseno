from __future__ import annotations

import io
import os
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import Browser, Page, expect
from pypdf import PdfReader

from tests.e2e.browser_support import authenticated_context
from tests.template_fixtures import portable_template

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _select(page: Page, label: str, option: str) -> None:
    control = page.get_by_role("combobox", name=label, exact=True)
    control.click()
    page.get_by_role("option", name=option, exact=True).click()
    expect(control).to_have_text(option)


def _artifacts(tmp_path: Path) -> Path:
    path = Path(os.getenv("E2E_ARTIFACTS_DIR", str(tmp_path)))
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
def test_section_layout_disclosure_animates_and_keeps_keyboard_focus(
    browser: Browser,
    workspace_servers: tuple[str, str],
    reduced_motion: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="en-US",
        viewport={"width": 1440, "height": 1000},
        reduced_motion=reduced_motion,
    )
    page = context.new_page()
    created = context.request.post(
        f"{frontend_url}/api/templates",
        data={"template": portable_template("Section disclosure")},
    )
    assert created.ok
    template_id = created.json()["data"]["template"]["id"]
    try:
        page.goto(f"{frontend_url}/template/{template_id}", wait_until="networkidle")
        trigger = page.get_by_role("button", name="Layouts by section", exact=True)
        panel_id = trigger.get_attribute("aria-controls")
        assert panel_id
        control = page.get_by_role("combobox", name="Education", exact=True)
        for expanded in (True, False, True):
            trigger.focus()
            page.evaluate(
                """id => {
                  window.__sectionMotion = { frames: [], done: false };
                  const started = performance.now();
                  function sample() {
                    const panel = document.getElementById(id);
                    window.__sectionMotion.frames.push({
                      height: panel?.getBoundingClientRect().height ?? 0,
                      running: panel?.getAnimations({ subtree: true }).some(
                        animation => animation.playState === 'running'
                      ) ?? false,
                    });
                    if (performance.now() - started < 650) {
                      requestAnimationFrame(sample);
                    } else window.__sectionMotion.done = true;
                  }
                  sample();
                }""",
                panel_id,
            )
            page.keyboard.press("Enter")
            if not expanded:
                page.keyboard.press("Tab")
                assert page.evaluate(
                    """id => !document.getElementById(id)?.contains(
                      document.activeElement
                    )""",
                    panel_id,
                )
            else:
                expect(trigger).to_be_focused()
            expect(trigger).to_have_attribute("aria-expanded", str(expanded).lower())
            page.wait_for_function("window.__sectionMotion.done")
            frames = page.evaluate("window.__sectionMotion.frames")
            heights = [frame["height"] for frame in frames]
            if reduced_motion == "reduce":
                assert not any(frame["running"] for frame in frames), frames
            else:
                assert any(frame["running"] for frame in frames), frames
                assert any(1 < height < max(heights) - 1 for height in heights), frames
            if expanded:
                expect(control).to_be_visible()
            else:
                expect(control).to_be_hidden()

        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        page.keyboard.press("Enter")
        expect(trigger).to_have_attribute("aria-expanded", "false")
        expect(control).to_be_hidden()
        expect(trigger).to_be_focused()
        page.keyboard.press("Tab")
        assert page.evaluate(
            """id => !document.getElementById(id)?.contains(document.activeElement)""",
            panel_id,
        )
    finally:
        context.request.post(f"{frontend_url}/api/templates/{template_id}/trash")
        context.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


@pytest.mark.parametrize("locale", ["zh-CN", "en-US"])
def test_section_layout_overrides_survive_global_changes_reload_and_copy(
    browser: Browser,
    workspace_servers: tuple[str, str],
    tmp_path: Path,
    locale: str,
) -> None:
    frontend_url, _ = workspace_servers
    zh = locale == "zh-CN"
    labels = {
        "tab": "布局" if zh else "Layout",
        "copy": "创建副本" if zh else "Create Copy",
        "edit": "修改模板信息" if zh else "Edit template details",
        "global": "经历布局" if zh else "Entry layout",
        "sections": "按模块设置" if zh else "Layouts by section",
        "education": "教育经历" if zh else "Education",
        "experience": "工作经历" if zh else "Experience",
        "inline": "同行并列" if zh else "Inline heading",
        "stacked": "上下堆叠" if zh else "Stacked",
        "compact": "紧凑双行" if zh else "Compact Two-Line",
        "inherit": "跟随全局" if zh else "Follow global",
    }
    context = authenticated_context(
        browser, locale=locale, viewport={"width": 1440, "height": 1000}
    )
    page = context.new_page()
    ids: list[str] = []
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def open_layout() -> None:
        page.get_by_role("tab", name=labels["tab"], exact=True).click()
        sections = page.get_by_role("button", name=labels["sections"], exact=True)
        if sections.get_attribute("aria-expanded") != "true":
            sections.click()
        expect(
            page.get_by_role("combobox", name=labels["education"], exact=True)
        ).to_be_visible()

    def copy() -> str:
        previous_url = page.url
        page.get_by_role("button", name=labels["copy"], exact=True).click()
        page.wait_for_url(lambda url: str(url) != previous_url)
        expect(
            page.get_by_role("button", name=labels["edit"], exact=True)
        ).to_be_visible()
        template_id = urlparse(page.url).path.rsplit("/", maxsplit=1)[-1]
        ids.append(template_id)
        return template_id

    def save(template_id: str, global_layout: str, overrides: dict) -> None:
        path = f"/api/templates/{template_id}"
        with page.expect_response(
            lambda response: (
                response.request.method == "PUT"
                and urlparse(response.url).path == path
                and response.request.post_data_json["saveMode"] == "checkpoint"
            )
        ) as response:
            page.keyboard.press("ControlOrMeta+s")
        assert response.value.ok
        assert response.value.json()["data"]["checkpoint"] is None
        for layout in (
            response.value.request.post_data_json["template"]["layout"],
            page.request.get(f"{frontend_url}{path}").json()["data"]["template"][
                "layout"
            ],
        ):
            assert layout["timelineItemLayout"] == global_layout
            assert layout["sectionItemLayouts"] == overrides

    try:
        page.goto(f"{frontend_url}/template/minimal", wait_until="networkidle")
        open_layout()
        for field in ("global", "education", "experience"):
            expect(
                page.get_by_role("combobox", name=labels[field], exact=True)
            ).to_be_disabled()
        original_id = copy()
        open_layout()
        _select(page, labels["global"], labels["inline"])
        _select(page, labels["education"], labels["inline"])
        _select(page, labels["experience"], labels["stacked"])
        _select(page, labels["global"], labels["compact"])
        expect(
            page.get_by_role("combobox", name=labels["education"], exact=True)
        ).to_have_text(labels["inline"])
        overrides = {"education": "inline", "experience": "stacked"}
        save(original_id, "compact", overrides)
        page.reload(wait_until="networkidle")
        open_layout()
        for field, option in (
            ("global", "compact"),
            ("education", "inline"),
            ("experience", "stacked"),
        ):
            expect(
                page.get_by_role("combobox", name=labels[field], exact=True)
            ).to_have_text(labels[option])

        for width in (1440, 360):
            page.set_viewport_size({"width": width, "height": 1000})
            education = page.get_by_role(
                "combobox", name=labels["education"], exact=True
            )
            education.scroll_into_view_if_needed()
            panel = page.locator(".resume-template-editor-panel")
            overflow = panel.evaluate(
                """panel => ({
                  panel: panel.scrollWidth - panel.clientWidth,
                  document: document.documentElement.scrollWidth - innerWidth,
                  controls: [...panel.querySelectorAll('[role=combobox]')]
                    .filter(control => control.getClientRects().length)
                    .map(control => control.scrollWidth - control.clientWidth),
                })"""
            )
            assert overflow["panel"] <= 1, overflow
            assert overflow["document"] <= 1, overflow
            assert all(value <= 1 for value in overflow["controls"]), overflow
            page.screenshot(
                path=str(_artifacts(tmp_path) / f"section-layouts-{locale}-{width}.png")
            )

        page.set_viewport_size({"width": 1440, "height": 1000})
        source = page.request.get(f"{frontend_url}/api/templates/{original_id}")
        assert source.ok
        definition = source.json()["data"]["template"]
        copied_payload = {
            key: definition[key]
            for key in (
                "preset",
                "name",
                "description",
                "layout",
                "typography",
                "settings",
            )
        }
        copied_payload["name"] = f"{definition['name']} copy"
        copied = page.request.post(
            f"{frontend_url}/api/templates", data={"template": copied_payload}
        )
        assert copied.ok
        copied_id = copied.json()["data"]["template"]["id"]
        assert copied_id != original_id
        ids.append(copied_id)
        page.goto(f"{frontend_url}/template/{copied_id}", wait_until="networkidle")
        open_layout()
        copied = page.request.get(f"{frontend_url}/api/templates/{copied_id}")
        assert copied.ok
        assert copied.json()["data"]["template"]["layout"]["sectionItemLayouts"] == (
            overrides
        )
        _select(page, labels["education"], labels["inherit"])
        _select(page, labels["experience"], labels["inherit"])
        _select(page, labels["global"], labels["stacked"])
        save(copied_id, "stacked", {})
        page.reload(wait_until="networkidle")
        open_layout()
        for field in ("education", "experience"):
            expect(
                page.get_by_role("combobox", name=labels[field], exact=True)
            ).to_have_text(labels["inherit"])
        original = page.request.get(f"{frontend_url}/api/templates/{original_id}")
        assert original.json()["data"]["template"]["layout"]["sectionItemLayouts"] == (
            overrides
        )
        assert errors == []
    finally:
        for template_id in reversed(ids):
            response = page.request.post(
                f"{frontend_url}/api/templates/{template_id}/trash"
            )
            if response.ok:
                page.request.delete(f"{frontend_url}/api/templates/{template_id}")
        context.close()


def test_inline_section_headings_wrap_and_export_all_pages_without_losing_text(
    browser: Browser,
    workspace_servers: tuple[str, str],
    tmp_path: Path,
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(browser, viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    try:
        template = portable_template("Inline pagination")
        template["layout"].update(
            timelineItemLayout="stacked",
            sectionItemLayouts={"education": "inline", "experience": "inline"},
        )
        created_template = context.request.post(
            f"{frontend_url}/api/templates", data={"template": template}
        )
        assert created_template.ok
        template_id = created_template.json()["data"]["template"]["id"]
        created_response = context.request.post(
            f"{frontend_url}/api/resumes",
            data={"documentLocale": "en", "template": template_id},
        )
        assert created_response.ok
        created = created_response.json()["data"]["resume"]
        resume_id = created["id"]
        fields = [
            ("Short School", "Computer Science", "2018 - 2022"),
            (
                "跨学科人工智能与分布式系统研究大学教育学院",
                "软件工程及人机交互研究方向硕士学位",
                "September 2015 - December 2025",
            ),
            (
                "UNBROKENSCHOOL" * 8,
                "UNBROKENMAJOR" * 8,
                "UNBROKENDATE" * 7,
            ),
        ]
        education = [
            {
                "id": f"education-{index}",
                "school": school,
                "degree": "",
                "major": major,
                "gpa": "",
                "location": f"EDU_PLACE_{index:02d}",
                "period": period,
                "description": "",
                "highlights": [],
            }
            for index, (school, major, period) in enumerate(fields)
        ]
        experiences = [
            {
                "id": f"experience-{index}",
                "company": (
                    f"COMPANY_{index:02d} International Research and Development"
                ),
                "position": f"POSITION_{index:02d} Senior Software Engineer 软件工程师",
                "location": f"LOCATION_{index:02d} 跨地区协作中心",
                "period": f"DATE_{index:02d} September 2020 - December 2025",
                "description": "",
                "highlights": [f"<p>RESULT_{index:02d} Reliable delivery.</p>"],
            }
            for index in range(18)
        ]
        created["resume"]["basic"]["name"] = "Inline pagination"
        created["resume"]["sections"] = [
            {
                "id": "education-probe",
                "kind": "education",
                "title": "Education",
                "items": education,
            },
            {
                "id": "experience-probe",
                "kind": "experience",
                "title": "Experience",
                "items": experiences,
            },
        ]
        saved = context.request.put(
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
        assert saved.ok, saved.text()
        page.goto(f"{frontend_url}/pdf-export?resumeId={resume_id}&documentLocale=en")
        page.locator('main[data-pdf-ready="true"]').wait_for(state="visible")
        papers = page.locator('[data-export-root="resume-page"]')
        page_count = papers.count()
        assert page_count > 1
        geometry = papers.evaluate_all(
            """papers => {
              const violations = [];
              let shortHeading = null;
              for (const paper of papers) {
                const viewport = paper.querySelector('.resume-page-content-viewport');
                const clip = viewport.getBoundingClientRect();
                for (const heading of viewport.querySelectorAll(
                  '[data-resume-item-id] > [data-resume-page-block]'
                )) {
                  const bounds = heading.getBoundingClientRect();
                  if (bounds.bottom <= clip.top || bounds.top >= clip.bottom) continue;
                  const walker = document.createTreeWalker(
                    heading, NodeFilter.SHOW_TEXT,
                  );
                  const lines = [];
                  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
                    if (!node.textContent.trim()) continue;
                    const range = document.createRange();
                    range.selectNodeContents(node);
                    for (const rect of range.getClientRects()) {
                      lines.push({ text: node.textContent, rect });
                    }
                  }
                  if (!lines.some(({ rect }) =>
                    rect.bottom > clip.top && rect.top < clip.bottom
                  )) continue;
                  if (bounds.top < clip.top - 1 || bounds.bottom > clip.bottom + 1) {
                    violations.push({ splitHeading: heading.textContent,
                      bounds: bounds.toJSON(), clip: clip.toJSON() });
                  }
                  if (heading.parentElement.dataset.resumeItemId === 'education-0') {
                    const title = heading.querySelector('h3').getBoundingClientRect();
                    const subtitle = heading.querySelector('p').getBoundingClientRect();
                    shortHeading = {
                      title: title.toJSON(), subtitle: subtitle.toJSON(),
                    };
                  }
                  for (const { text, rect } of lines) {
                    if (rect.right > clip.right + 1 || rect.left < clip.left - 1 ||
                        rect.right > bounds.right + 1 ||
                        rect.left < bounds.left - 1) {
                      violations.push({ text, rect: rect.toJSON(),
                        clip: clip.toJSON(), bounds: bounds.toJSON() });
                    }
                  }
                }
              }
              return { violations, shortHeading };
            }"""
        )
        assert geometry["violations"] == [], geometry
        short = geometry["shortHeading"]
        assert short is not None
        assert short["subtitle"]["left"] > short["title"]["right"]
        assert short["subtitle"]["top"] < short["title"]["bottom"]
        papers.first.screenshot(
            path=str(_artifacts(tmp_path) / "inline-first-page.png")
        )
        result = context.request.post(
            f"{frontend_url}/api/exports/resume-pdf",
            data={
                "resumeId": resume_id,
                "fileNameSeed": "Inline pagination",
                "savedAt": saved.json()["data"]["savedAt"],
                "versionId": saved.json()["data"]["versionId"],
            },
            timeout=60000,
        )
        assert result.ok, result.text()
        downloaded = context.request.get(
            f"{frontend_url}{result.json()['data']['downloadUrl']}"
        )
        assert downloaded.ok
        pdf = downloaded.body()
        (_artifacts(tmp_path) / "inline-pagination.pdf").write_bytes(pdf)
        reader = PdfReader(io.BytesIO(pdf))
        assert len(reader.pages) == page_count
        text = "".join("".join(item.extract_text().split()) for item in reader.pages)
        for values in fields:
            for value in values:
                assert "".join(value.split()) in text, value
        for index in range(18):
            for field in ("COMPANY", "POSITION", "LOCATION", "DATE", "RESULT"):
                marker = f"{field}_{index:02d}"
                assert text.count(marker) == 1, marker

        template["layout"].update(timelineItemLayout="inline", sectionItemLayouts={})
        updated = context.request.put(
            f"{frontend_url}/api/templates/{template_id}",
            data={"template": template},
        )
        assert updated.ok
        page.reload()
        page.locator('main[data-pdf-ready="true"]').wait_for(state="visible")
        inherited = papers.first.locator('[data-resume-item-id="education-0"]')
        title = inherited.locator("h3").bounding_box()
        subtitle = inherited.locator("p").first.bounding_box()
        assert title is not None and subtitle is not None
        assert subtitle["x"] > title["x"] + title["width"]
        assert subtitle["y"] < title["y"] + title["height"]
        assert papers.count() == page_count
    finally:
        context.close()
