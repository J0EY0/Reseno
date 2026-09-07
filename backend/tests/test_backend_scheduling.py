import asyncio
import io
import json
from threading import Event, Thread, current_thread

import pytest
from fastapi import UploadFile
from fastapi.testclient import TestClient

from app.routers import imports as import_routes
from app.services import imports as import_service
from app.services import resumes
from tests.template_fixtures import portable_template


@pytest.mark.parametrize("kind", ["resume", "templates"])
@pytest.mark.parametrize("phase", ["decode", "validate"])
def test_import_computation_yields_to_other_coroutines(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    phase: str,
) -> None:
    if kind == "resume":
        saved = resumes.create_resume({"documentLocale": "en"})["resume"]
        payload = {
            "format": "reseno.resume",
            "formatVersion": 1,
            "templates": [],
            "resumes": [
                {
                    key: value
                    for key, value in saved.items()
                    if key not in {"id", "updatedAt"}
                }
            ],
        }
        route = import_routes.import_resume
        parser_name = "parse_resume_artifact"
    else:
        payload = {
            "format": "reseno.template",
            "formatVersion": 1,
            "templates": [portable_template("Import")],
        }
        route = import_routes.import_templates
        parser_name = "parse_template_artifact"
    owner = import_service if phase == "decode" else import_routes
    function_name = "_decode_json_upload" if phase == "decode" else parser_name
    original = getattr(owner, function_name)
    started = Event()
    release = Event()

    def blocked_computation(value):
        started.set()
        if not release.wait(timeout=2):
            raise TimeoutError("Import computation blocked the event loop")
        return original(value)

    monkeypatch.setattr(owner, function_name, blocked_computation)

    async def scenario() -> None:
        upload = UploadFile(file=io.BytesIO(json.dumps(payload).encode()))
        task = asyncio.create_task(route(upload))

        async def wait_for_computation() -> None:
            while not started.is_set():
                await asyncio.sleep(0.001)

        try:
            await asyncio.wait_for(wait_for_computation(), timeout=3)
            assert not task.done()
            release.set()
            result = await asyncio.wait_for(task, timeout=3)
            assert result.data is not None
        finally:
            release.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


def test_gallery_validation_releases_write_lock_but_retains_version_snapshot(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    created = resumes.create_resume({"documentLocale": "en"})["resume"]
    resume_id = created["id"]
    first = resumes.save_resume(
        resume_id, {**created, "title": "Autosave A"}, save_mode="autosave"
    )
    parsing = Event()
    release = Event()
    saved = Event()
    errors: list[BaseException] = []
    titles: list[str] = []
    original_parse = resumes._parse_resume_bytes

    def paused_parse(content: bytes):
        if current_thread().name == "gallery-reader":
            parsing.set()
            if not release.wait(timeout=5):
                raise TimeoutError("Gallery validation was not released")
        return original_parse(content)

    def read() -> None:
        try:
            titles.extend(item.title for item in resumes.list_resumes().resumes)
        except BaseException as exc:
            errors.append(exc)

    def write() -> None:
        try:
            resumes.save_resume(
                resume_id,
                {**first["resume"], "title": "Autosave B"},
                save_mode="autosave",
            )
            saved.set()
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(resumes, "_parse_resume_bytes", paused_parse)
    reader = Thread(target=read, name="gallery-reader")
    writer = Thread(target=write, name="gallery-writer")
    reader.start()
    try:
        assert parsing.wait(timeout=5)
        writer.start()
        assert saved.wait(timeout=3), "Gallery validation retained the write lock"
        assert not resumes._resume_version_path(
            resume_id, int(first["versionId"])
        ).exists()
    finally:
        release.set()
        reader.join(timeout=5)
        if writer.ident is not None:
            writer.join(timeout=5)

    assert not reader.is_alive()
    assert not writer.is_alive()
    assert not errors
    assert titles == ["Autosave A"]
    assert resumes.load_resume(resume_id)["resume"]["title"] == "Autosave B"
