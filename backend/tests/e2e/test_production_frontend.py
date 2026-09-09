import io
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Browser, expect
from pypdf import PdfReader

from tests.e2e.conftest import (
    BACKEND_ROOT,
    FRONTEND_ROOT,
    _stop_process,
    _unused_port,
    _wait_for_url,
)
from tests.runtime_environment import runtime_environment

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_BROWSER_E2E") != "1",
    reason="set RUN_BROWSER_E2E=1 and build the frontend to run production E2E tests",
)


def test_production_frontend_exports_and_preserves_workspace(
    browser: Browser, tmp_path: Path
) -> None:
    dist = FRONTEND_ROOT / "dist"
    assert (dist / "index.html").is_file(), "Build the frontend before this test."
    port = _unused_port()
    base_url = f"http://127.0.0.1:{port}"
    data_dir = tmp_path / "data"
    env = {
        **os.environ,
        **runtime_environment(data_dir),
        "FRONTEND_DIST_DIR": str(dist),
        "FRONTEND_RENDER_BASE_URL": base_url,
        "BACKEND_CORS_ORIGINS": "",
    }
    credentials = {"username": "container-owner", "password": "ContainerTest2026"}
    command = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--workers",
        "1",
    ]
    resume_ids = []
    with (tmp_path / "server.log").open("w+", encoding="utf-8") as log:
        process = subprocess.Popen(
            command, cwd=BACKEND_ROOT, env=env, stdout=log, stderr=log, text=True
        )
        try:
            _wait_for_url(f"{base_url}/health", process, log)
            with httpx.Client(base_url=base_url, timeout=60, trust_env=False) as api:
                setup = api.post(
                    "/api/auth/setup",
                    json={**credentials, "confirmPassword": credentials["password"]},
                )
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
                        resume_ids.append(resume_id)
                        record["resume"]["basic"]["name"] = name
                        response = api.put(
                            f"/api/resumes/{resume_id}",
                            json={
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
                            },
                        )
                        response.raise_for_status()
                        saved = response.json()["data"]
                        export_request = {
                            "fileNameSeed": f"container-{locale}",
                            "resumeId": resume_id,
                            "savedAt": saved["savedAt"],
                            "versionId": saved["versionId"],
                        }
                        response = api.post(
                            "/api/exports/resume-pdf", json=export_request
                        )
                        response.raise_for_status()
                        download = api.get(response.json()["data"]["downloadUrl"])
                        download.raise_for_status()
                        reader = PdfReader(io.BytesIO(download.content))
                        text = "".join(
                            page.extract_text() or "" for page in reader.pages
                        )
                        assert name.replace(" ", "") in "".join(text.split())

                    response = api.post(
                        "/api/exports/resume-images", json=export_request
                    )
                    response.raise_for_status()
                    download = api.get(response.json()["data"]["downloadUrl"])
                    download.raise_for_status()
                    assert download.content.startswith(b"\x89PNG\r\n\x1a\n")
                finally:
                    context.close()
        finally:
            _stop_process(process)

        saved_keys = (data_dir / ".env").read_bytes()
        process = subprocess.Popen(
            command, cwd=BACKEND_ROOT, env=env, stdout=log, stderr=log, text=True
        )
        try:
            _wait_for_url(f"{base_url}/health", process, log)
            with httpx.Client(base_url=base_url, trust_env=False) as api:
                assert (
                    api.get("/api/auth/setup").json()["data"]["setupRequired"] is False
                )
                response = api.post("/api/auth/login", json=credentials)
                response.raise_for_status()
                api.headers["Authorization"] = (
                    f"Bearer {response.json()['data']['accessToken']}"
                )
                for resume_id in resume_ids:
                    assert api.get(f"/api/resumes/{resume_id}").status_code == 200
                assert (data_dir / ".env").read_bytes() == saved_keys
        finally:
            _stop_process(process)
