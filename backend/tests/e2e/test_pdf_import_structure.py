"""PDF imports preserve readable structure and single-page layouts."""

from __future__ import annotations

import html
import io
import os
import re
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Page, expect
from pypdf import PdfReader

from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


def _source(locale: str) -> tuple[str, list[str], str, list[str]]:
    if locale == "zh":
        name, education, school = "林星河", "教育背景", "示例大学"
        skills, research, awards = "技术能力", "研究活动", "荣誉奖励"
        paragraphs = [
            "熟悉工程开发和数据处理，能够运用多种工具完成需求分析、系统设计、"
            "服务开发以及质量验证，并结合实际项目持续改进工作流程和团队协作方式。"
            "能够清晰记录系统行为，维护稳定的交付流程。"
            "在实施过程中保持充分沟通，及时验证关键假设并整理技术资料。",
            "具备扎实的问题分析能力，能够独立复现复杂场景并定位根本原因，"
            "通过可重复的验证方法评估解决方案，推动团队建立可靠且便于维护的工程实践。"
            "重视用户反馈，持续改善产品体验和技术文档。"
            "能够围绕实际目标制定工作安排，并与不同职责的同事共同完成项目。",
        ]
        research_text = (
            "参与文档结构识别研究，负责整理匿名样本、设计评估方法和分析实验结果，"
            "针对不同语言及页面布局验证文本提取效果，并持续记录实验条件、"
            "关键发现和待解决的问题，为后续研究提供可靠依据。"
        )
        award_names = [
            "工程竞赛一等奖",
            "创新实践二等奖",
            "优秀研究奖",
            "社区服务奖",
            "学业优秀奖",
            "团队协作奖",
        ]
    else:
        name, education, school = "Robin Example", "Education", "Example University"
        skills, research, awards = (
            "Technical Skills",
            "Research Activities",
            "Honors and Awards",
        )
        paragraphs = [
            "Builds reliable services through careful requirements analysis, "
            "system design, implementation and quality checks. Uses reproducible "
            "methods to investigate complex failures and documents the observed "
            "behavior so the team can maintain "
            "a dependable delivery process and improve collaboration over time.",
            "Communicates technical findings clearly and works with colleagues "
            "to evaluate "
            "practical solutions. Collects user feedback, verifies important workflows "
            "and maintains useful documentation while steadily improving "
            "product quality "
            "and the experience of the people who use the system.",
        ]
        research_text = (
            "Studied document structure using anonymous samples and reproducible "
            "evaluation "
            "methods. Compared extraction across different languages and page layouts, "
            "recorded experimental conditions and analyzed the results to "
            "identify useful "
            "improvements and open questions for subsequent research."
        )
        award_names = [
            "Engineering Gold Award",
            "Innovation Silver Award",
            "Research Excellence",
            "Community Service",
            "Academic Distinction",
            "Teamwork Award",
        ]
    paragraph_html = "".join(f"<p>{html.escape(text)}</p>" for text in paragraphs)
    award_html = "".join(f"<div>{html.escape(name)}</div>" for name in award_names)
    markup = f"""
      <style>
        @page {{ size: A4; margin: 40px; }}
        html, body {{ margin: 0; padding: 0; background: white; }}
        .import-source {{ width: 714px; color: #111;
          font: 14px/21px "Noto Sans SC Variable", sans-serif; }}
        .import-source h1 {{ margin: 0 0 8px; font-size: 26px;
          line-height: 32px; font-weight: 700; }}
        .import-source h2 {{ margin: 20px 0 8px; font-size: 16px;
          line-height: 22px; font-weight: 700; }}
        .import-source p {{ margin: 0 0 14px; }}
        .import-source .awards {{ display: grid;
          grid-template-columns: 1fr 1fr; column-gap: 42px; row-gap: 8px; }}
      </style>
      <main class="import-source">
        <h1>{name}</h1><div>robin@example.com</div>
        <h2>{education}</h2><div>{school}</div><div>2020 - 2024</div>
        <h2>{skills}</h2><section class="skills">{paragraph_html}</section>
        <h2>{research}</h2><p>{research_text}</p>
        <h2>{awards}</h2><div class="awards">{award_html}</div>
      </main>
    """
    return markup, paragraphs, research_text, award_names


def _render_source_pdf(page: Page, markup: str, path: Path) -> bytes:
    page.evaluate("markup => { document.body.innerHTML = markup; }", markup)
    page.evaluate("document.fonts.ready")
    assert page.locator(".skills p").evaluate_all(
        "elements => elements.every(element => element.clientHeight >= 63)"
    ), "Each fixture paragraph must physically wrap across at least three lines."
    page.screenshot(path=str(path.with_suffix(".source.png")), full_page=True)
    return page.pdf(path=str(path), prefer_css_page_size=True, print_background=True)


@pytest.mark.parametrize("locale", ["zh", "en"])
def test_pdf_import_preserves_wrapped_paragraphs_and_six_awards(
    browser: Browser,
    workspace_servers: tuple[str, str],
    tmp_path: Path,
    locale: str,
) -> None:
    url, seed_resume_id = workspace_servers
    context = authenticated_context(
        browser,
        locale="en-US" if locale == "zh" else "zh-CN",
        viewport={"width": 1672, "height": 1100},
    )
    page = context.new_page()
    source_page = context.new_page()
    page_errors: list[str] = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        source_page.goto(f"{url}/resume/{seed_resume_id}", wait_until="networkidle")
        expect(
            source_page.locator('[data-resume-pagination-ready="true"]')
        ).to_be_visible()
        markup, paragraphs, research_text, award_names = _source(locale)
        payload = _render_source_pdf(
            source_page, markup, tmp_path / f"anonymous-{locale}.pdf"
        )
        source_page.close()

        page.goto(f"{url}/resume", wait_until="networkidle")
        with page.expect_response(
            lambda response: (
                response.url == f"{url}/api/resumes"
                and response.request.method == "POST"
            )
        ) as saved_response:
            page.locator('input[type="file"]').set_input_files(
                {
                    "name": f"anonymous-{locale}.pdf",
                    "mimeType": "application/pdf",
                    "buffer": payload,
                }
            )
        assert saved_response.value.ok
        saved_resume = saved_response.value.json()["data"]["resume"]
        resume_id = saved_resume["id"]
        expect(page).to_have_url(f"{url}/resume/{resume_id}")
        expect(page.locator('[data-resume-pagination-ready="true"]')).to_be_visible()
        page.screenshot(path=str(tmp_path / f"imported-{locale}.png"), full_page=True)

        stored_response = page.request.get(f"{url}/api/resumes/{resume_id}")
        assert stored_response.ok
        stored = stored_response.json()["data"]["resume"]
        assert stored["documentLocale"] == locale
        sections = stored["resume"]["sections"]
        assert [section["kind"] for section in sections] == [
            "education",
            "simple_list",
            "simple_list",
            "achievement",
        ]
        skills, research, awards = sections[1:]
        assert len(skills["items"]) == 1
        assert skills["items"][0]["content"].count("<li>") == 2
        assert research["items"][0]["content"].count("<li>") == 1
        assert sorted(item["name"] for item in awards["items"]) == sorted(award_names)

        preview = page.locator(
            '.resume-workspace [data-export-root="resume-page"]'
        ).first
        skill_section = preview.locator(f'[data-resume-section-id="{skills["id"]}"]')
        expect(skill_section.locator("li")).to_have_text(paragraphs)
        research_section = preview.locator(
            f'[data-resume-section-id="{research["id"]}"]'
        )
        expect(research_section.locator("li")).to_have_text([research_text])
        award_section = preview.locator(f'[data-resume-section-id="{awards["id"]}"]')
        expect(award_section.locator("[data-resume-item-id]")).to_have_count(6)
        for award in award_names:
            expect(award_section).to_contain_text(award)
        assert page_errors == []
    finally:
        context.close()


def test_dense_single_page_pdf_keeps_one_page_and_persists_fitted_style(
    browser: Browser,
    workspace_servers: tuple[str, str],
    tmp_path: Path,
) -> None:
    url, seed_resume_id = workspace_servers
    context = authenticated_context(
        browser, locale="en-US", viewport={"width": 1672, "height": 1100}
    )
    page = context.new_page()
    source_page = context.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        source_page.goto(f"{url}/resume/{seed_resume_id}", wait_until="networkidle")
        expect(
            source_page.locator('[data-resume-pagination-ready="true"]')
        ).to_be_visible()
        markup, original_paragraphs, research_text, award_names = _source("en")
        paragraphs = [
            f"Sample {index + 1} {original_paragraphs[index % 2]}" for index in range(8)
        ]
        markup = markup.replace(
            "".join(f"<p>{html.escape(text)}</p>" for text in original_paragraphs),
            "".join(f"<p>{html.escape(text)}</p>" for text in paragraphs),
        ).replace(
            "</style>",
            ".import-source { font-size: 12px; line-height: 16px; }"
            ".import-source p { margin-bottom: 8px; }</style>",
        )
        source_page.evaluate("markup => { document.body.innerHTML = markup; }", markup)
        source_page.evaluate("document.fonts.ready")
        payload = source_page.pdf(
            path=str(tmp_path / "dense-single-page.pdf"),
            prefer_css_page_size=True,
            print_background=True,
        )
        assert len(PdfReader(io.BytesIO(payload)).pages) == 1
        source_page.close()

        page.goto(f"{url}/resume", wait_until="networkidle")
        with page.expect_response(
            lambda response: (
                response.url == f"{url}/api/resumes"
                and response.request.method == "POST"
            )
        ) as saved_response:
            page.locator('input[type="file"]').set_input_files(
                {
                    "name": "dense-single-page.pdf",
                    "mimeType": "application/pdf",
                    "buffer": payload,
                }
            )
        assert saved_response.value.ok
        saved = saved_response.value.json()["data"]["resume"]
        expect(page).to_have_url(f"{url}/resume/{saved['id']}")
        stack = page.locator(".resume-workspace [data-resume-page-count]")
        expect(stack).to_have_attribute("data-resume-pagination-ready", "true")
        page.screenshot(path=str(tmp_path / "dense-import.png"), full_page=True)
        expect(stack).to_have_attribute("data-resume-page-count", "1")
        assert saved["templateSettings"] is not None

        page.reload(wait_until="networkidle")
        expect(stack).to_have_attribute("data-resume-pagination-ready", "true")
        expect(stack).to_have_attribute("data-resume-page-count", "1")
        sections = saved["resume"]["sections"]
        assert len(sections) == 4
        skills, research, awards = sections[1:]
        preview = page.locator('.resume-workspace [data-export-root="resume-page"]')
        expect(
            preview.locator(f'[data-resume-section-id="{skills["id"]}"] li')
        ).to_have_text(paragraphs)
        expect(
            preview.locator(f'[data-resume-section-id="{research["id"]}"] li')
        ).to_have_text([research_text])
        assert sorted(item["name"] for item in awards["items"]) == sorted(award_names)
        assert page.locator(".resume-workspace .resume-page-stack").evaluate(
            """stack => {
                const flow = stack.querySelector(
                    '.resume-page-content-flow--measure');
                const viewport = stack.querySelector(
                    '.resume-page-content-viewport');
                return flow.scrollHeight <= viewport.clientHeight + 1;
            }"""
        )
        page.get_by_role("button", name="Export", exact=True).click()
        with page.expect_download(timeout=45_000) as exported:
            page.get_by_role("menuitem", name="Export PDF", exact=True).click()
        exported_path = tmp_path / "dense-export.pdf"
        exported.value.save_as(exported_path)
        exported_pdf = PdfReader(exported_path)
        assert len(exported_pdf.pages) == 1
        exported_text = re.sub(r"\s+", "", exported_pdf.pages[0].extract_text())
        for text in [*paragraphs, research_text, *award_names]:
            assert re.sub(r"\s+", "", text) in exported_text
        assert errors == []
    finally:
        context.close()
