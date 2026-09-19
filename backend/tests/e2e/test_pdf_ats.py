"""Real PDF export regressions for ATS-readable text layers.

Run explicitly because these checks start both application servers, launch
Chromium, and inspect the generated PDF bytes:

    RUN_BROWSER_E2E=1 pytest tests/e2e/test_pdf_ats.py -q

The matrix always checks pypdf and PDF.js, and checks PDFKit on macOS when
swiftc is available. Set PDFTOTEXT_EXECUTABLE to include Poppler. Set
PDF_ATS_OUTPUT_DIR to retain the generated matrix for visual inspection;
otherwise pytest uses its temporary directory.
"""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any, Literal

import pytest
from playwright.sync_api import Browser
from pypdf import PdfReader

from tests.e2e.browser_support import authenticated_context as _authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)

TEMPLATE_IDS = (
    "minimal",
    "modern",
    "compact",
    "classic",
    "executive",
    "academic",
)
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PDFJS_TEXT_EXTRACTOR = REPOSITORY_ROOT / "frontend" / "scripts" / "extract-pdf-text.mjs"
PDFKIT_TEXT_EXTRACTOR = Path(__file__).with_name("extract_pdfkit_text.swift")
ATS_MARKERS = (
    "HEADER_SENTINEL",
    "EXPERIENCE_1_SENTINEL",
    "EXPERIENCE_2_SENTINEL",
    "EXPERIENCE_3_SENTINEL",
    "EXPERIENCE_4_SENTINEL",
    "EXPERIENCE_5_SENTINEL",
    "EDUCATION_SENTINEL",
    "PROJECT_SENTINEL",
    "PUBLICATION_SENTINEL",
    "ACHIEVEMENT_SENTINEL",
    "SKILLS_SENTINEL",
)


@pytest.fixture(scope="session")
def pdfkit_text_extractor(
    tmp_path_factory: pytest.TempPathFactory,
    record_testsuite_property: Callable[[str, object], None],
) -> Path | None:
    if sys.platform != "darwin":
        record_testsuite_property("PDFKit extraction", "not run: requires macOS")
        return None
    swiftc = shutil.which("swiftc")
    if swiftc is None:
        record_testsuite_property("PDFKit extraction", "not run: swiftc unavailable")
        return None

    build_dir = tmp_path_factory.mktemp("pdfkit-extractor")
    executable = build_dir / "extract-pdfkit-text"
    subprocess.run(
        [
            swiftc,
            "-module-cache-path",
            str(build_dir / "module-cache"),
            str(PDFKIT_TEXT_EXTRACTOR),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
    )
    record_testsuite_property("PDFKit extraction", "enabled")
    return executable


def _experience_item(index: int, locale: Literal["en", "zh"]) -> dict[str, Any]:
    is_zh = locale == "zh"
    marker = f" EXPERIENCE_{index}_SENTINEL"
    return {
        "id": f"ats-experience-{index}",
        "company": f"{'北辰数据科技' if is_zh else 'Northstar Analytics'} {index}",
        "position": "资深平台工程师" if is_zh else "Staff Platform Engineer",
        "location": "中国上海" if is_zh else "Shanghai, China",
        "period": "2024.09 - 2027.06",
        "description": (
            "负责多语言文档系统与可靠导出链路。"
            if is_zh
            else "Designed multilingual document systems and export pipelines."
        )
        + marker,
        "highlights": [
            "使用 Golang / Swift 开发文档系统。"
            if is_zh
            else "Built document systems with Golang / Swift.",
            (
                "将文档处理错误率降低 37%，并覆盖跨部门交付。"
                if is_zh
                else "Reduced document-processing errors by 37% across teams."
            ),
            (
                "建立可重复的质量门禁并负责上线。"
                if is_zh
                else "Established repeatable quality gates and owned rollout."
            ),
        ],
    }


def _create_probe_resume(
    created: dict[str, Any],
    locale: Literal["en", "zh"],
) -> dict[str, Any]:
    is_zh = locale == "zh"
    resume = created["resume"]
    resume["basic"] = {
        "name": "陈艾文" if is_zh else "Avery Chen",
        "headline": "ATS 系统工程师" if is_zh else "ATS Systems Engineer",
        "phone": "+86 138-0000-0000",
        "email": "avery_chen@example.com",
        "location": "中国上海" if is_zh else "Shanghai, China",
        "avatar": "",
        "summary": (
            "HEADER_SENTINEL 构建可靠的多语言简历导出系统。"
            if is_zh
            else "HEADER_SENTINEL builds reliable multilingual resume exports."
        ),
        "customFields": [
            {
                "id": "ats-portfolio",
                "type": "url",
                "label": "作品集" if is_zh else "Portfolio",
                "value": "https://example.com/avery_chen",
            }
        ],
    }
    resume["sections"] = [
        {
            "id": "ats-experience",
            "kind": "experience",
            "title": "工作经历" if is_zh else "Professional Experience",
            "items": [_experience_item(index, locale) for index in range(1, 6)],
        },
        {
            "id": "ats-education",
            "kind": "education",
            "title": "教育经历" if is_zh else "Education",
            "items": [
                {
                    "id": "ats-education-1",
                    "school": "复旦大学" if is_zh else "Fudan University",
                    "degree": "工学硕士" if is_zh else "Master of Engineering",
                    "major": "计算机科学" if is_zh else "Computer Science",
                    "gpa": "3.9/4.0",
                    "location": "中国上海" if is_zh else "Shanghai, China",
                    "period": "2018 - 2021",
                    "description": (
                        "EDUCATION_SENTINEL 研究可靠文档处理。"
                        if is_zh
                        else (
                            "EDUCATION_SENTINEL researched reliable document "
                            "processing."
                        )
                    ),
                    "highlights": [],
                }
            ],
        },
        {
            "id": "ats-project",
            "kind": "project",
            "title": "代表项目" if is_zh else "Selected Projects",
            "items": [
                {
                    "id": "ats-project-1",
                    "name": (
                        "多语言简历平台" if is_zh else "Multilingual Resume Platform"
                    ),
                    "role": "技术负责人" if is_zh else "Technical Lead",
                    "techStack": ["TypeScript", "Python", "PostgreSQL"],
                    "period": "2024",
                    "url": "https://example.com/projects/resume-platform",
                    "description": (
                        "PROJECT_SENTINEL 支持中英文导出。"
                        if is_zh
                        else "PROJECT_SENTINEL supports English and Chinese exports."
                    ),
                    "highlights": [],
                }
            ],
        },
        {
            "id": "ats-publication",
            "kind": "publication",
            "title": "代表性论文" if is_zh else "Selected Publications",
            "items": [
                {
                    "id": "ats-publication-1",
                    "title": (
                        "可靠简历解析研究"
                        if is_zh
                        else "Reliable Resume Parsing at Scale"
                    ),
                    "authors": "Avery Chen, Morgan Lee",
                    "venue": "Document Intelligence Review",
                    "date": "2025",
                    "url": "https://example.com/publications/resume-parsing",
                    "description": (
                        "PUBLICATION_SENTINEL 提出可复现评测方法。"
                        if is_zh
                        else "PUBLICATION_SENTINEL presents a reproducible evaluation."
                    ),
                }
            ],
        },
        {
            "id": "ats-achievement",
            "kind": "achievement",
            "title": "荣誉与奖项" if is_zh else "Honors and Awards",
            "items": [
                {
                    "id": "ats-achievement-1",
                    "name": "年度工程奖" if is_zh else "Engineering Excellence Award",
                    "issuer": "Reseno Foundation",
                    "date": "2025",
                    "url": "https://example.com/awards/engineering",
                    "description": (
                        "ACHIEVEMENT_SENTINEL 表彰质量工程实践。"
                        if is_zh
                        else "ACHIEVEMENT_SENTINEL recognizes quality engineering."
                    ),
                }
            ],
        },
        {
            "id": "ats-skills",
            "kind": "simple_list",
            "title": "专业技能" if is_zh else "Technical Skills",
            "items": [
                {
                    "id": "ats-skills-1",
                    "content": (
                        "<ul><li>SKILLS_SENTINEL Python 与 TypeScript</li>"
                        "<li>PDF 与 Unicode 质量保证；实现 get_user_name</li></ul>"
                        if is_zh
                        else "<ul><li>SKILLS_SENTINEL Python and TypeScript</li>"
                        "<li>PDF quality assurance and get_user_name</li></ul>"
                    ),
                }
            ],
        },
    ]
    return resume


def _normalize_whitespace(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).replace("\u200b", "")
    return re.sub(r"\s+", " ", normalized).strip()


def _without_whitespace(text: str) -> str:
    return re.sub(r"\s+", "", _normalize_whitespace(text))


def _assert_ats_text(
    text: str,
    *,
    extractor: str,
    locale: Literal["en", "zh"],
) -> None:
    collapsed = _normalize_whitespace(text)
    compact = _without_whitespace(text)

    assert "\ufffd" not in text, f"{extractor} emitted Unicode replacement glyphs"
    assert "\x00" not in text, f"{extractor} emitted NUL characters"
    assert "Page 1" not in collapsed
    assert "Loading" not in collapsed
    assert "加载中" not in collapsed
    assert "avery_chen@example.com" in collapsed, (
        f"{extractor} split or dropped the email address"
    )
    assert "https://example.com/avery_chen" in collapsed, (
        f"{extractor} split or dropped the portfolio URL"
    )
    if locale == "en":
        assert "Avery Chen" in collapsed, f"{extractor} split the candidate name"
    else:
        for phrase in ("陈艾文", "工作经历", "复旦大学", "可靠简历解析研究"):
            assert phrase in compact, f"{extractor} dropped CJK text: {phrase}"

    if extractor in {"pdfjs", "pdfkit"}:
        phrases = ["2024.09 - 2027.06", "Golang / Swift", "get_user_name"]
        if locale == "zh":
            phrases.extend(
                (
                    "构建可靠的多语言简历导出系统。",
                    "负责多语言文档系统与可靠导出链路。",
                    "使用 Golang / Swift 开发文档系统。",
                )
            )
        else:
            phrases.append("Built document systems with Golang / Swift.")
        for phrase in phrases:
            assert phrase in collapsed, f"{extractor} split copied text: {phrase}"

    marker_text = text if extractor in {"pdfjs", "pdfkit"} else compact
    marker_positions: list[int] = []
    for marker in ATS_MARKERS:
        assert marker_text.count(marker) == 1, (
            f"{extractor} must extract {marker} exactly once"
        )
        marker_positions.append(marker_text.index(marker))
    assert marker_positions == sorted(marker_positions), (
        f"{extractor} changed the canonical section reading order"
    )


def _extract_with_pypdf(pdf_bytes: bytes) -> tuple[PdfReader, str, str]:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    page_text = [page.extract_text() or "" for page in reader.pages]
    layout_text = [
        page.extract_text(extraction_mode="layout") or "" for page in reader.pages
    ]
    assert all(text.strip() for text in page_text), "PDF contains a text-empty page"
    assert all(text.strip() for text in layout_text), (
        "PDF contains a layout-text-empty page"
    )
    return reader, "\n".join(page_text), "\n".join(layout_text)


def _assert_pdf_structure(reader: PdfReader) -> None:
    assert not reader.is_encrypted
    for page in reader.pages:
        assert abs(float(page.mediabox.width) - 595.0) < 1.0
        assert abs(float(page.mediabox.height) - 842.0) < 1.0

        resources = page["/Resources"].get_object()
        fonts = resources["/Font"].get_object()
        assert fonts, "PDF page must use at least one font"
        for font_ref in fonts.values():
            font = font_ref.get_object()
            assert "/ToUnicode" in font, "Every PDF font needs a Unicode map"
            assert font.get("/Subtype") != "/Type3", (
                "PDF text must use embedded outline fonts, not Type3 glyph programs"
            )
            outline_fonts = (
                font["/DescendantFonts"] if font.get("/Subtype") == "/Type0" else [font]
            )
            for outline_font_ref in outline_fonts:
                outline_font = outline_font_ref.get_object()
                descriptor = outline_font["/FontDescriptor"].get_object()
                assert any(
                    key in descriptor
                    for key in ("/FontFile", "/FontFile2", "/FontFile3")
                ), "PDF font outlines must be embedded"


def _extract_with_poppler(pdf_path: Path) -> str | None:
    executable = os.getenv("PDFTOTEXT_EXECUTABLE")
    if not executable:
        return None

    result = subprocess.run(
        [executable, "-enc", "UTF-8", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _extract_with_pdfjs(pdf_path: Path) -> str:
    node = shutil.which("node")
    assert node is not None, "Node.js is required for the PDF.js ATS check"
    result = subprocess.run(
        [node, str(PDFJS_TEXT_EXTRACTOR), str(pdf_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        cwd=REPOSITORY_ROOT / "frontend",
    )
    pages = json.loads(result.stdout)
    assert isinstance(pages, list) and pages
    assert all(isinstance(page, str) and page.strip() for page in pages), (
        "PDF.js found a text-empty page"
    )
    return "\n".join(pages)


def _extract_with_pdfkit(pdf_path: Path, executable: Path) -> str:
    result = subprocess.run(
        [str(executable), str(pdf_path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    pages = json.loads(result.stdout)
    assert isinstance(pages, list) and pages
    assert all(isinstance(page, str) and page.strip() for page in pages), (
        "PDFKit found a text-empty page"
    )
    return "\n".join(pages)


def _iter_pdf_uris(reader: PdfReader) -> Iterable[str]:
    for page in reader.pages:
        for annotation_ref in page.get("/Annots", []):
            annotation = annotation_ref.get_object()
            action = annotation.get("/A")
            if action and action.get("/URI"):
                yield str(action["/URI"])


@pytest.mark.parametrize(
    ("template_id", "font_family"),
    [pytest.param(template_id, None, id=template_id) for template_id in TEMPLATE_IDS]
    + [pytest.param("minimal", "noto_sans_sc", id="noto-sans-sc")],
)
@pytest.mark.parametrize("locale", ("en", "zh"))
def test_all_builtin_templates_export_ats_readable_pdf(
    browser: Browser,
    workspace_servers: tuple[str, str],
    tmp_path: Path,
    pdfkit_text_extractor: Path | None,
    template_id: str,
    font_family: str | None,
    locale: Literal["en", "zh"],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser)
    resume_id: str | None = None

    try:
        create_response = context.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": locale,
                "title": f"ATS {template_id} {locale}",
                "template": template_id,
            },
        )
        assert create_response.ok
        created = create_response.json()["data"]["resume"]
        resume_id = str(created["id"])
        if font_family is not None:
            created["typography"]["fontFamily"] = font_family

        save_response = context.request.put(
            f"{frontend_url}/api/resumes/{resume_id}",
            data={
                "documentLocale": created["documentLocale"],
                "jobBrief": created["jobBrief"],
                "resume": _create_probe_resume(created, locale),
                "template": created["template"],
                "templateSettings": created["templateSettings"],
                "title": created["title"],
                "typography": created["typography"],
            },
        )
        assert save_response.ok, save_response.text()
        saved = save_response.json()["data"]

        export_response = context.request.post(
            f"{frontend_url}/api/exports/resume-pdf",
            data={
                "fileNameSeed": f"ats-{template_id}-{locale}",
                "resumeId": resume_id,
                "savedAt": saved["savedAt"],
                "versionId": saved["versionId"],
            },
        )
        assert export_response.ok
        download_url = export_response.json()["data"]["downloadUrl"]
        download_response = context.request.get(f"{frontend_url}{download_url}")
        assert download_response.ok
        pdf_bytes = download_response.body()

        pdf_name = f"ats-{template_id}-{font_family or 'default'}-{locale}.pdf"
        pdf_path = tmp_path / pdf_name
        pdf_path.write_bytes(pdf_bytes)
        if output_dir_value := os.getenv("PDF_ATS_OUTPUT_DIR"):
            output_dir = Path(output_dir_value)
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / pdf_path.name).write_bytes(pdf_bytes)

        reader, pypdf_text, pypdf_layout_text = _extract_with_pypdf(pdf_bytes)
        assert 1 <= len(reader.pages) <= 4
        _assert_pdf_structure(reader)
        _assert_ats_text(pypdf_text, extractor="pypdf", locale=locale)
        _assert_ats_text(
            pypdf_layout_text,
            extractor="pypdf-layout",
            locale=locale,
        )
        _assert_ats_text(
            _extract_with_pdfjs(pdf_path),
            extractor="pdfjs",
            locale=locale,
        )
        if pdfkit_text_extractor is not None:
            _assert_ats_text(
                _extract_with_pdfkit(pdf_path, pdfkit_text_extractor),
                extractor="pdfkit",
                locale=locale,
            )

        poppler_text = _extract_with_poppler(pdf_path)
        if poppler_text is not None:
            _assert_ats_text(poppler_text, extractor="pdftotext", locale=locale)

        uris = set(_iter_pdf_uris(reader))
        assert "mailto:avery_chen@example.com" in uris
        assert "tel:+86 138-0000-0000" in uris
        assert "https://example.com/avery_chen" in uris
        assert "https://example.com/projects/resume-platform" in uris
        assert "https://example.com/publications/resume-parsing" in uris
        assert "https://example.com/awards/engineering" in uris
    finally:
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()


def test_resume_image_export_uses_authenticated_renderer(
    browser: Browser,
    workspace_servers: tuple[str, str],
) -> None:
    frontend_url, _ = workspace_servers
    context = _authenticated_context(browser)
    resume_id: str | None = None
    try:
        create_response = context.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "en",
                "title": "Authenticated image export",
                "template": "minimal",
            },
        )
        assert create_response.ok
        created = create_response.json()["data"]
        resume_id = str(created["resume"]["id"])
        export_response = context.request.post(
            f"{frontend_url}/api/exports/resume-images",
            data={
                "fileNameSeed": "authenticated-resume",
                "resumeId": resume_id,
                "savedAt": created["savedAt"],
                "versionId": created["versionId"],
            },
        )
        assert export_response.ok, export_response.text()
        exported = export_response.json()["data"]
        assert exported["pageCount"] == 1
        assert exported["isArchive"] is False
        download_response = context.request.get(
            f"{frontend_url}{exported['downloadUrl']}"
        )
        assert download_response.ok
        assert download_response.headers["content-type"] == "image/png"
        png = download_response.body()
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert int.from_bytes(png[16:20], "big") >= 794
        assert int.from_bytes(png[20:24], "big") >= 1123
    finally:
        if resume_id:
            trash_response = context.request.post(
                f"{frontend_url}/api/resumes/{resume_id}/trash"
            )
            if trash_response.ok:
                context.request.delete(f"{frontend_url}/api/resumes/{resume_id}")
        context.close()
