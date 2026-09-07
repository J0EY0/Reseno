import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from playwright.sync_api import Browser, expect

from tests.e2e.browser_support import authenticated_context

pytestmark = [
    pytest.mark.browser_smoke,
    pytest.mark.skipif(
        os.getenv("RUN_BROWSER_E2E") != "1",
        reason="set RUN_BROWSER_E2E=1 to run browser integration tests",
    ),
]


@pytest.mark.parametrize("kind", ["resume", "template"])
@pytest.mark.parametrize("reduced_motion", ["no-preference", "reduce"])
def test_detail_navigation_transfers_only_a_token_and_reloads_after_refresh(
    browser: Browser,
    workspace_servers: tuple[str, str],
    kind: str,
    reduced_motion: str,
) -> None:
    url, _ = workspace_servers
    context = authenticated_context(
        browser,
        locale="zh-CN",
        viewport={"width": 1440, "height": 900},
        reduced_motion=reduced_motion,
    )
    context.add_init_script(
        """(() => {
          window.detailHandoffs = [];
          const push = history.pushState.bind(history);
          history.pushState = (state, ...args) => {
            if (state?.usr?.kind?.endsWith('detail-handoff')) {
              window.detailHandoffs.push(JSON.parse(JSON.stringify(state.usr)));
            }
            return push(state, ...args);
          };
        })();"""
    )
    page = context.new_page()
    try:
        name = f"Token handoff {uuid4().hex[:8]}"
        if kind == "resume":
            response = page.request.post(
                f"{url}/api/resumes", data={"title": name, "documentLocale": "zh"}
            )
            assert response.ok
            item_id = response.json()["data"]["resume"]["id"]
            gallery = "/resume"
            endpoint = f"/api/resumes/{item_id}"
        else:
            presets = json.loads(
                (
                    Path(__file__).resolve().parents[2]
                    / "app/services/template_presets.json"
                ).read_text()
            )
            response = page.request.post(
                f"{url}/api/templates",
                data={
                    "template": {
                        "name": name,
                        "description": "",
                        "preset": "minimal",
                        **{
                            key: presets["minimal"][key]
                            for key in ("layout", "typography", "settings")
                        },
                    }
                },
            )
            assert response.ok
            item_id = response.json()["data"]["template"]["id"]
            gallery = "/templates"
            endpoint = "/api/workspace/pages/templates"

        page.goto(f"{url}{gallery}", wait_until="networkidle")
        page.locator(f'a[href="/{kind}/{item_id}"]').click()
        page.wait_for_url(f"{url}/{kind}/{item_id}")
        expect(page.locator('[data-resume-pagination-ready="true"]')).to_be_visible()
        handoffs = page.evaluate("window.detailHandoffs")
        assert len(handoffs) == 1
        assert set(handoffs[0]) == {"kind", "token"}
        assert isinstance(handoffs[0]["token"], str)
        assert len(json.dumps(handoffs[0])) < 256
        page.wait_for_function("history.state?.usr == null")
        if kind == "template":
            reloads = []
            page.on(
                "request",
                lambda request: reloads.append(request.url)
                if request.method == "GET" and endpoint in request.url
                else None,
            )
            page.get_by_role("tab", name="装饰", exact=True).click()
            page.get_by_role("button", name="添加图片占位符", exact=True).click()
            image = page.get_by_role("group", name="图片元素 1", exact=True)
            expect(image).to_be_visible()
            page.get_by_role("combobox", name="语言", exact=True).click()
            page.get_by_role("option", name="EN", exact=True).click()
            expect(
                page.get_by_role("combobox", name="Language", exact=True)
            ).to_be_visible()
            page.wait_for_load_state("networkidle")
            assert not reloads
            expect(page.locator('[data-slot="template-image-card-header"]')).to_have_count(1)
        with page.expect_response(lambda response: endpoint in response.url):
            page.reload(wait_until="networkidle")
        expect(page.locator('[data-resume-pagination-ready="true"]')).to_be_visible()
        expect(page.get_by_role("heading", name=name, exact=True)).to_be_visible()
        if kind == "template":
            reloads.clear()
            page.get_by_role("tab", name="Decoration", exact=True).click()
            images = page.locator('[data-slot="template-image-card-header"]')
            image_count = images.count()
            page.get_by_role(
                "button", name="Add Image Placeholder", exact=True
            ).click()
            expect(images).to_have_count(image_count + 1)
            page.get_by_role("combobox", name="Language", exact=True).click()
            page.get_by_role("option", name="中文", exact=True).click()
            expect(
                page.get_by_role("combobox", name="语言", exact=True)
            ).to_be_visible()
            page.wait_for_load_state("networkidle")
            assert not reloads
            expect(images).to_have_count(image_count + 1)
    finally:
        context.close()
