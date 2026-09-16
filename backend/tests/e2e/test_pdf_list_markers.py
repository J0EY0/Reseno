"""Exported list markers retain all painted pixels at the page margin."""

from __future__ import annotations

import base64
import io
import os
from pathlib import Path

import pytest
from playwright.sync_api import Browser
from pypdf import PdfReader

from tests.e2e.browser_support import authenticated_context

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
)


@pytest.mark.browser_smoke
@pytest.mark.parametrize("template_id", ("minimal", "modern", "compact", "academic"))
def test_exported_list_markers_are_not_clipped_at_content_margin(
    browser: Browser,
    workspace_servers: tuple[str, str],
    tmp_path: Path,
    template_id: str,
) -> None:
    frontend_url, _ = workspace_servers
    context = authenticated_context(browser, device_scale_factor=2)
    try:
        created_response = context.request.post(
            f"{frontend_url}/api/resumes",
            data={
                "documentLocale": "en",
                "title": "List marker export",
                "template": template_id,
            },
        )
        assert created_response.ok, created_response.text()
        created = created_response.json()["data"]["resume"]
        created["resume"]["basic"]["name"] = "List Marker Probe"
        created["resume"]["sections"] = [
            {
                "id": "marker-section",
                "kind": "simple_list",
                "title": "Skills",
                "items": [
                    {
                        "id": "marker-item",
                        "content": (
                            "<ul><li>Unordered first item 编程语言</li>"
                            "<li>Unordered second item"
                            "<ul><li>Nested unordered item 数据系统</li></ul></li></ul>"
                            "<ol>"
                            + "".join(
                                f"<li>Ordered item {index}</li>"
                                for index in range(1, 13)
                            )
                            + "</ol>"
                        ),
                    }
                ],
            }
        ]
        saved_response = context.request.put(
            f"{frontend_url}/api/resumes/{created['id']}",
            data={
                key: created[key]
                for key in (
                    "documentLocale",
                    "title",
                    "resume",
                    "jobBrief",
                    "template",
                    "templateSettings",
                    "typography",
                )
            },
        )
        assert saved_response.ok, saved_response.text()
        saved = saved_response.json()["data"]
        export_request = {
            "fileNameSeed": "list-markers",
            "resumeId": created["id"],
            "savedAt": saved["savedAt"],
            "versionId": saved["versionId"],
        }
        exported_response = context.request.post(
            f"{frontend_url}/api/exports/resume-images",
            data=export_request,
        )
        assert exported_response.ok, exported_response.text()
        exported = exported_response.json()["data"]
        assert exported["pageCount"] == 1
        downloaded = context.request.get(f"{frontend_url}{exported['downloadUrl']}")
        assert downloaded.ok, downloaded.text()
        actual_png = downloaded.body()
        (tmp_path / "markers-exported.png").write_bytes(actual_png)

        page = context.new_page()
        page.goto(
            f"{frontend_url}/pdf-export?resumeId={created['id']}&documentLocale=en"
        )
        page.wait_for_selector("[data-pdf-ready='true']")
        page.emulate_media(media="print")
        page.add_style_tag(
            content=(
                ".resume-page-content-viewport {"
                "overflow: visible; clip-path: inset(0 -4em); }"
            )
        )
        reference_png = page.locator("[data-export-root='resume-page']").screenshot(
            animations="disabled"
        )
        (tmp_path / "markers-unclipped.png").write_bytes(reference_png)
        differences = page.evaluate(
            """async ([actual, expected]) => {
                const read = async encoded => {
                    const image = new Image();
                    image.src = `data:image/png;base64,${encoded}`;
                    await image.decode();
                    const canvas = document.createElement('canvas');
                    canvas.width = image.naturalWidth;
                    canvas.height = image.naturalHeight;
                    const context = canvas.getContext('2d');
                    context.drawImage(image, 0, 0);
                    return {
                        width: canvas.width,
                        height: canvas.height,
                        data: context.getImageData(
                            0, 0, canvas.width, canvas.height
                        ).data
                    };
                };
                const a = await read(actual);
                const b = await read(expected);
                let count = 0;
                for (let index = 0; index < a.data.length; index += 4) {
                    const distance = [0, 1, 2].reduce(
                        (sum, channel) => sum + Math.abs(
                            a.data[index + channel] - b.data[index + channel]
                        ), 0
                    );
                    if (distance > 30) count += 1;
                }
                return {
                    count,
                    actual: [a.width, a.height],
                    expected: [b.width, b.height]
                };
            }""",
            [
                base64.b64encode(actual_png).decode(),
                base64.b64encode(reference_png).decode(),
            ],
        )
        assert differences["actual"] == differences["expected"]
        assert differences["count"] == 0, differences

        pdf_response = context.request.post(
            f"{frontend_url}/api/exports/resume-pdf", data=export_request
        )
        assert pdf_response.ok, pdf_response.text()
        pdf_download = context.request.get(
            f"{frontend_url}{pdf_response.json()['data']['downloadUrl']}"
        )
        assert pdf_download.ok, pdf_download.text()
        pdf_bytes = pdf_download.body()
        (tmp_path / "markers-exported.pdf").write_bytes(pdf_bytes)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) == 1
        text = reader.pages[0].extract_text()
        for label in (
            "Unordered first item",
            "Unordered second item",
            "Nested unordered item",
            *(f"Ordered item {index}" for index in range(1, 13)),
        ):
            assert label in text
    finally:
        context.close()
