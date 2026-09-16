import io
import os
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser, expect
from pypdf import PdfReader

from tests.e2e.diagnostics import SERVER_LOGS
from tests.e2e.production_server import ProductionServer

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 and build the frontend to run production E2E tests",
)


@pytest.fixture
def production_server(
    tmp_path: Path, request: pytest.FixtureRequest
) -> Iterator[ProductionServer]:
    server = ProductionServer(tmp_path)
    module = request.node.getparent(pytest.Module)
    if module is not None:
        module.stash[SERVER_LOGS] = {"server.log": server.log_path}
    try:
        yield server
    finally:
        server.remove_volume()


def test_production_frontend_exports_and_preserves_workspace(
    browser: Browser, production_server: ProductionServer
) -> None:
    base_url = production_server.url
    credentials = {"username": "container-owner", "password": "ContainerTest2026"}
    saved_resumes = {}
    with production_server.running():
        with httpx.Client(base_url=base_url, timeout=60, trust_env=False) as api:
            health = api.get("/health")
            assert health.status_code == 200
            assert health.json() == {"status": "ok"}
            setup = api.post(
                "/api/auth/setup",
                json={**credentials, "confirmPassword": credentials["password"]},
            )
            if production_server.image:
                assert setup.status_code == 403
                production_server.setup_container_owner(credentials)
                setup = api.post("/api/auth/login", json=credentials)
            setup.raise_for_status()
            api.headers["Authorization"] = (
                f"Bearer {setup.json()['data']['accessToken']}"
            )
            context = browser.new_context()
            try:
                page = context.new_page()
                page.goto(f"{base_url}/login")
                page.locator("#username").fill(credentials["username"])
                page.locator("#password").fill(credentials["password"])
                page.locator('form button[type="submit"]').click()
                page.wait_for_url(f"{base_url}/resume")
                expect(page.locator('input[name="resume-search"]')).to_be_visible()
                page.reload()
                expect(page.locator('input[name="resume-search"]')).to_be_visible()

                for locale, name in (("en", "Docker Example"), ("zh", "容器示例")):
                    response = api.post(
                        "/api/resumes",
                        json={"documentLocale": locale, "template": "minimal"},
                    )
                    response.raise_for_status()
                    record = response.json()["data"]["resume"]
                    resume_id = record["id"]
                    record["resume"]["basic"]["name"] = name
                    payload = {
                        key: record[key]
                        for key in (
                            "documentLocale",
                            "jobBrief",
                            "resume",
                            "template",
                            "templateSettings",
                            "title",
                            "typography",
                        )
                    }
                    response = api.put(
                        f"/api/resumes/{resume_id}",
                        json=payload,
                    )
                    response.raise_for_status()
                    saved_resumes[resume_id] = payload
                    saved = response.json()["data"]
                    export_request = {
                        "fileNameSeed": f"container-{locale}",
                        "resumeId": resume_id,
                        "savedAt": saved["savedAt"],
                        "versionId": saved["versionId"],
                    }
                    response = api.post("/api/exports/resume-pdf", json=export_request)
                    response.raise_for_status()
                    download = api.get(response.json()["data"]["downloadUrl"])
                    download.raise_for_status()
                    reader = PdfReader(io.BytesIO(download.content))
                    text = "".join(page.extract_text() or "" for page in reader.pages)
                    assert name.replace(" ", "") in "".join(text.split())

                response = api.post("/api/exports/resume-images", json=export_request)
                response.raise_for_status()
                download = api.get(response.json()["data"]["downloadUrl"])
                download.raise_for_status()
                assert download.content.startswith(b"\x89PNG\r\n\x1a\n")
            finally:
                context.close()
        saved_keys = production_server.keys_digest()

    with production_server.running():
        with httpx.Client(base_url=base_url, trust_env=False) as api:
            assert api.get("/api/auth/setup").json()["data"]["setupRequired"] is False
            response = api.post("/api/auth/login", json=credentials)
            response.raise_for_status()
            api.headers["Authorization"] = (
                f"Bearer {response.json()['data']['accessToken']}"
            )
            for resume_id, expected in saved_resumes.items():
                response = api.get(f"/api/resumes/{resume_id}")
                assert response.status_code == 200
                persisted = response.json()["data"]["resume"]
                assert {key: persisted[key] for key in expected} == expected
            assert production_server.keys_digest() == saved_keys
