import json

import anyio
import pytest
import starlette.formparsers
from starlette.datastructures import UploadFile

from app.db.connection import connect
from app.routers.upload_route import MAX_MULTIPART_BODY_BYTES
from app.schemas.common import APP_MESSAGE_BAD_REQUEST
from app.services.imports import MAX_JSON_UPLOAD_BYTES
from tests.template_fixtures import portable_template


@pytest.fixture
def opened_files(monkeypatch):
    opened = []
    original = starlette.formparsers.SpooledTemporaryFile

    def record(*args, **kwargs):
        uploaded = original(*args, **kwargs)
        opened.append(uploaded)
        return uploaded

    monkeypatch.setattr(starlette.formparsers, "SpooledTemporaryFile", record)
    yield opened
    for uploaded in opened:
        uploaded.close()


def _artifact() -> bytes:
    return json.dumps(
        {
            "format": "reseno.template",
            "formatVersion": 1,
            "templates": [portable_template("Upload boundary")],
        }
    ).encode()


def test_upload_rejects_extra_file_before_spooling_it(client, monkeypatch):
    written = {}
    original = UploadFile.write

    async def record(upload, data):
        written[upload.filename] = written.get(upload.filename, 0) + len(data)
        await original(upload, data)

    monkeypatch.setattr(UploadFile, "write", record)
    response = client.post(
        "/api/import/templates",
        files=[
            ("file", ("template.json", _artifact(), "application/json")),
            ("ignored", ("ignored.bin", b"x" * 4096, "application/octet-stream")),
        ],
    )
    assert response.status_code == 400
    assert written.get("ignored.bin", 0) == 0


def test_large_upload_is_rejected_before_multipart_spooling(client, monkeypatch):
    written = 0
    original = UploadFile.write

    async def record(upload, data):
        nonlocal written
        written += len(data)
        await original(upload, data)

    monkeypatch.setattr(UploadFile, "write", record)
    response = client.post(
        "/api/import/templates",
        files={
            "file": (
                "large.json",
                b" " * (MAX_JSON_UPLOAD_BYTES + 1024 * 1024),
                "application/json",
            ),
        },
    )
    assert response.status_code == 413
    assert response.json()["message"] == "JSON_UPLOAD_TOO_LARGE"
    assert written == 0


def test_import_accepts_file_exactly_at_limit(client, opened_files):
    content = _artifact()
    response = client.post(
        "/api/import/templates",
        files={
            "file": (
                "limit.json",
                content.ljust(MAX_JSON_UPLOAD_BYTES, b" "),
                "application/json",
            ),
        },
    )
    assert response.status_code == 200
    assert len(response.json()["data"]["templates"]) == 1
    assert len(opened_files) == 1
    assert opened_files[0].closed


def _post_chunks(
    client,
    chunks,
    *,
    content_type,
    content_length=None,
    path="/api/import/templates",
):
    headers = [
        (b"content-type", content_type.encode()),
        (b"authorization", client.headers["authorization"].encode()),
    ]
    if content_length is not None:
        headers.append((b"content-length", content_length.encode()))
    consumed = 0
    messages = []

    async def run():
        async def receive():
            nonlocal consumed
            if consumed == len(chunks):
                await anyio.sleep_forever()
            body = chunks[consumed]
            consumed += 1
            return {
                "type": "http.request",
                "body": body,
                "more_body": consumed < len(chunks),
            }

        async def send(message):
            messages.append(message)

        with anyio.fail_after(10):
            await client.app(
                {
                    "type": "http",
                    "asgi": {"version": "3.0", "spec_version": "2.4"},
                    "http_version": "1.1",
                    "method": "POST",
                    "scheme": "http",
                    "path": path,
                    "raw_path": path.encode(),
                    "query_string": b"",
                    "headers": headers,
                    "server": ("testserver", 80),
                    "client": ("127.0.0.1", 50000),
                },
                receive,
                send,
            )

    client.portal.call(run)
    status = next(
        message["status"]
        for message in messages
        if message["type"] == "http.response.start"
    )
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    return status, json.loads(body), consumed


@pytest.mark.parametrize(
    ("path", "message"),
    [
        ("/api/import/templates", "JSON_UPLOAD_TOO_LARGE"),
        ("/api/agent/attachments", APP_MESSAGE_BAD_REQUEST),
    ],
)
@pytest.mark.parametrize(
    "content_length", [None, "1"], ids=["no-length", "false-length"]
)
def test_streamed_upload_rejects_untrusted_length_and_closes_files(
    client,
    opened_files,
    content_length,
    path,
    message,
):
    preamble = (
        b'--upload\r\nContent-Disposition: form-data; name="file"; '
        b'filename="large.json"\r\nContent-Type: application/json\r\n\r\n'
    )
    chunk = b" " * (1024 * 1024)
    chunks = [
        preamble,
        *([chunk] * 10),
        b" " * (64 * 1024),
        b"unread tail",
        b"\r\n--upload--\r\n",
    ]
    assert sum(map(len, chunks[:12])) > MAX_MULTIPART_BODY_BYTES
    status, body, consumed = _post_chunks(
        client,
        chunks,
        content_type="multipart/form-data; boundary=upload",
        content_length=content_length,
        path=path,
    )
    assert status == 413
    assert body["message"] == message
    assert consumed == 12
    assert len(opened_files) == 1
    assert opened_files[0].closed


def test_streamed_urlencoded_upload_stops_at_body_limit(client):
    chunks = [b"file=", *([b"x" * (1024 * 1024)] * 11), b"unread tail"]
    status, body, consumed = _post_chunks(
        client,
        chunks,
        content_type="application/x-www-form-urlencoded",
    )
    assert status == 413
    assert body["message"] == "JSON_UPLOAD_TOO_LARGE"
    assert consumed == 12


def test_malformed_multipart_stays_a_bad_request(client):
    response = client.post(
        "/api/import/templates",
        content=b"invalid multipart boundary",
        headers={"content-type": "multipart/form-data; boundary=upload"},
    )
    assert response.status_code == 400
    assert response.json()["message"] == APP_MESSAGE_BAD_REQUEST


def test_agent_upload_accepts_resume_id_and_closes_file(client, opened_files):
    resume_id = "uploadboundaryresume"
    with connect() as conn:
        conn.execute(
            "INSERT INTO resumes (id, title, saved_at) VALUES (?, ?, ?)",
            (resume_id, "Upload boundary", "2026-09-08T00:00:00Z"),
        )
    response = client.post(
        "/api/agent/attachments",
        data={"resumeId": resume_id},
        files={"file": ("notes.txt", b"Interview notes", "text/plain")},
    )
    assert response.status_code == 200
    uploaded = response.json()["data"]
    assert uploaded["filename"] == "notes.txt"
    assert len(opened_files) == 1
    assert opened_files[0].closed
    download = client.get(
        f"/api/agent/resumes/{resume_id}/attachments/{uploaded['id']}",
    )
    assert download.status_code == 200
    assert download.content == b"Interview notes"


@pytest.mark.parametrize(
    "fields",
    [
        [("resumeId", (None, "uploadboundaryresume")), ("extra", (None, "ignored"))],
        [("resumeId", (None, "x" * 1025))],
    ],
)
def test_extra_or_oversized_form_fields_close_parsed_files(
    client,
    opened_files,
    fields,
):
    response = client.post(
        "/api/agent/attachments",
        files=[("file", ("notes.txt", b"Interview notes", "text/plain")), *fields],
    )
    assert response.status_code == 400
    assert response.json()["message"] == APP_MESSAGE_BAD_REQUEST
    assert len(opened_files) == 1
    assert opened_files[0].closed
