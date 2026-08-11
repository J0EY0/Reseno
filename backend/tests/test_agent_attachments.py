import base64
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from app.config import get_settings
from app.db.connection import connect
from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentConversationItem,
)
from app.schemas.common import APP_CODE_NOT_FOUND
from app.services import agent_sessions, resumes
from app.services.agent import attachments as agent_attachments
from app.services.agent.attachments import mark_agent_attachments_sent
from app.services.agent.runtime.messages import (
    build_agent_messages,
    is_native_attachment_unsupported,
)
from app.services.agent_sessions import _current_user_message
from app.services.llm import AgentLlmConfig, LlmRequestError, common
from app.services.llm.adapters import (
    anthropic_messages,
    google_gemini,
    openai_responses,
)

SYNTHETIC_SESSION_REVISION = "synthetic-session-revision"


def _current_session_revision(session_id: str) -> str:
    conn = connect()
    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO resumes (id, title, saved_at)
            VALUES (?, 'Attachment test resume', ?)
            """,
            (session_id, datetime.now(UTC).isoformat()),
        )
        return agent_sessions.load_agent_session(conn, session_id).revision
    finally:
        conn.close()


def _config(*, api_family: str = "openai_compatible_chat") -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="attachment-test",
        name="Attachment Test",
        provider="openai",
        model="test-model",
        base_url="https://api.example.test/v1",
        api_key="sk-test",
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=30,
        api_family=api_family,
        supports_image=True,
    )


def _request(
    attachment: dict[str, Any],
    *,
    session_id: str,
) -> AgentChatRequest:
    return AgentChatRequest(
        message=AgentConversationItem(
            id=f"turn-attachment-{session_id}",
            role="user",
            text="Use the attached material.",
            files=[attachment],
        ),
        locale="en",
        resume={"basic": {}, "sections": []},
        resume_id=session_id,
        expected_revision=SYNTHETIC_SESSION_REVISION,
    )


def _upload(
    client: TestClient,
    *,
    session_id: str,
    filename: str,
    payload: bytes,
    media_type: str,
) -> dict[str, Any]:
    with connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO resumes (id, title, saved_at)
            VALUES (?, 'Attachment test resume', ?)
            """,
            (session_id, datetime.now(UTC).isoformat()),
        )
    response = client.post(
        "/api/agent/attachments",
        data={"resumeId": session_id},
        files={"file": (filename, payload, media_type)},
    )
    assert response.status_code == 200
    return response.json()["data"]


def _current_request_files(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    content = messages[-1]["content"]
    if not isinstance(content, list):
        return []

    for part in content:
        if part.get("type") != "text":
            continue
        text = part.get("text")
        if not isinstance(text, str) or not text.lstrip().startswith(
            '{"currentRequestFiles":',
        ):
            continue
        return json.loads(text)["currentRequestFiles"]
    return []


def _pdf_with_text(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode()
    objects = [
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        (
            b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>\n"
            b"endobj\n"
        ),
        (
            f"4 0 obj\n<< /Length {len(stream)} >>\nstream\n".encode()
            + stream
            + b"\nendstream\nendobj\n"
        ),
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]
    document = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for value in objects:
        offsets.append(len(document))
        document.extend(value)

    xref_offset = len(document)
    document.extend(f"xref\n0 {len(objects) + 1}\n".encode())
    document.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        document.extend(f"{offset:010d} 00000 n \n".encode())
    document.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode(),
    )
    return bytes(document)


def _docx_with_text(text: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
              <Default Extension="xml" ContentType="application/xml"/>
            </Types>""",
        )
        archive.writestr(
            "word/document.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>
            </w:document>""",
        )
    return buffer.getvalue()


def _encrypted_pdf() -> bytes:
    buffer = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt("secret")
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.parametrize(
    ("filename", "expected_filename", "case_id"),
    [
        ("John_Smith_CV.pdf", "[redacted_name]_CV.pdf", "underscore"),
        ("John-Smith-CV.pdf", "[redacted_name]-CV.pdf", "hyphen"),
        ("John.Smith.CV.pdf", "[redacted_name].CV.pdf", "period"),
    ],
)
def test_current_attachment_filename_hides_resume_name(
    client: TestClient,
    filename: str,
    expected_filename: str,
    case_id: str,
) -> None:
    session_id = f"resume-private-current-filename-{case_id}"
    attachment = _upload(
        client,
        session_id=session_id,
        filename=filename,
        payload=_pdf_with_text("Public project evidence"),
        media_type="application/pdf",
    )
    request = _request(attachment, session_id=session_id)
    request.resume["basic"]["name"] = "John Smith"

    messages = build_agent_messages(
        request,
        _config(),
        mode="streaming_final",
        force_attachment_text=True,
    )

    assert _current_request_files(messages)[0]["filename"] == expected_filename


def test_prevalidate_rejects_corrupt_pdf_before_consumption(
    client: TestClient,
) -> None:
    session_id = "resume-corrupt-pdf"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="corrupt.pdf",
        payload=b"%PDF-1.4\nnot-a-valid-document",
        media_type="application/pdf",
    )

    with pytest.raises(
        agent_attachments.AgentAttachmentError,
        match="PDF could not be read",
    ):
        agent_attachments.prevalidate_agent_attachments(
            session_id,
            [attachment],
        )

    stored = agent_attachments.load_agent_attachment(session_id, attachment)
    assert stored is not None
    assert stored.state == "stored"


def test_prevalidate_rejects_encrypted_native_pdf(
    client: TestClient,
) -> None:
    session_id = "resume-encrypted-pdf"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="encrypted.pdf",
        payload=_encrypted_pdf(),
        media_type="application/pdf",
    )

    with pytest.raises(
        agent_attachments.AgentAttachmentError,
        match="Encrypted PDF attachments are not supported",
    ):
        agent_attachments.prevalidate_agent_attachments(
            session_id,
            [attachment],
            can_consume_native=lambda _attachment: True,
        )

    stored = agent_attachments.load_agent_attachment(session_id, attachment)
    assert stored is not None
    assert stored.state == "stored"


def test_prevalidate_normalizes_unexpected_extraction_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "resume-extraction-failure"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="notes.txt",
        payload=b"Readable source material",
        media_type="text/plain",
    )

    def fail_extraction(
        stored: agent_attachments.StoredAgentAttachment,
        payload: bytes,
    ) -> str:
        del stored, payload
        raise RuntimeError("extractor crashed")

    monkeypatch.setattr(
        agent_attachments,
        "_extract_attachment_text",
        fail_extraction,
    )

    with pytest.raises(
        agent_attachments.AgentAttachmentError,
        match="could not be extracted",
    ):
        agent_attachments.prevalidate_agent_attachments(
            session_id,
            [attachment],
        )

    stored = agent_attachments.load_agent_attachment(session_id, attachment)
    assert stored is not None
    assert stored.state == "stored"


def test_prevalidate_rejects_aggregate_raw_bytes_without_partial_readiness(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "resume-aggregate-bytes"
    files = [
        _upload(
            client,
            session_id=session_id,
            filename=f"part-{index}.txt",
            payload=b"123456",
            media_type="text/plain",
        )
        for index in range(2)
    ]
    monkeypatch.setattr(
        agent_attachments,
        "MAX_AGENT_REQUEST_ATTACHMENT_BYTES",
        10,
    )

    with pytest.raises(
        agent_attachments.AgentAttachmentError,
        match="total size limit",
    ):
        agent_attachments.prevalidate_agent_attachments(session_id, files)

    assert [
        agent_attachments.load_agent_attachment(session_id, file).state
        for file in files
    ] == ["stored", "stored"]


def test_prevalidate_rejects_aggregate_extracted_text(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "resume-aggregate-text"
    files = [
        _upload(
            client,
            session_id=session_id,
            filename=f"part-{index}.txt",
            payload=b"abcdef",
            media_type="text/plain",
        )
        for index in range(2)
    ]
    monkeypatch.setattr(
        agent_attachments,
        "MAX_AGENT_REQUEST_ATTACHMENT_TEXT_CHARS",
        10,
    )

    with pytest.raises(
        agent_attachments.AgentAttachmentError,
        match="total text limit",
    ):
        agent_attachments.prevalidate_agent_attachments(session_id, files)

    assert [
        agent_attachments.load_agent_attachment(session_id, file).state
        for file in files
    ] == ["stored", "stored"]


def test_attachment_lifecycle_advances_after_batch_validation_and_consumption(
    client: TestClient,
) -> None:
    session_id = "resume-attachment-lifecycle"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="evidence.txt",
        payload=b"Verified evidence",
        media_type="text/plain",
    )

    stored = agent_attachments.load_agent_attachment(session_id, attachment)
    assert stored is not None
    assert stored.state == "stored"

    result = agent_attachments.prevalidate_agent_attachments(
        session_id,
        [attachment],
    )
    ready = agent_attachments.load_agent_attachment(session_id, attachment)
    assert result.total_bytes == len(b"Verified evidence")
    assert result.total_text_chars == len("Verified evidence")
    assert ready is not None
    assert ready.state == "ready"

    mark_agent_attachments_sent(session_id, [attachment])
    consumed = agent_attachments.load_agent_attachment(session_id, attachment)
    assert consumed is not None
    assert consumed.state == "consumed"
    assert consumed.sent_at is not None

    repeated_receipt = mark_agent_attachments_sent(session_id, [attachment])
    assert repeated_receipt.previous_metadata == ()


def test_cleanup_cannot_delete_attachment_referenced_by_committed_history(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "resume-cleanup-consume-race"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="evidence.txt",
        payload=b"Verified evidence",
        media_type="text/plain",
    )
    agent_attachments.prevalidate_agent_attachments(session_id, [attachment])

    delete_started = Event()
    consumed_metadata_written = Event()
    original_delete = agent_attachments._delete_attachment_files
    original_write = agent_attachments._write_metadata

    def pause_stale_cleanup(
        cleanup_session_id: str,
        stored: agent_attachments.StoredAgentAttachment,
    ) -> None:
        delete_started.set()
        consumed_metadata_written.wait(timeout=1)
        original_delete(cleanup_session_id, stored)

    def observe_consumption(
        metadata_session_id: str,
        attachment_id: str,
        metadata: dict[str, Any],
    ) -> None:
        original_write(metadata_session_id, attachment_id, metadata)
        if metadata.get("state") == "consumed":
            consumed_metadata_written.set()

    monkeypatch.setattr(
        agent_attachments,
        "_delete_attachment_files",
        pause_stale_cleanup,
    )
    monkeypatch.setattr(agent_attachments, "_write_metadata", observe_consumption)

    cleanup_thread = Thread(
        target=agent_attachments.cleanup_expired_pending_attachments,
        kwargs={"now": datetime.now(UTC) + timedelta(days=2)},
    )
    cleanup_thread.start()
    assert delete_started.wait(timeout=1)

    request = AgentChatRequest(
        resumeId=session_id,
        expectedRevision=_current_session_revision(session_id),
        message=AgentConversationItem(
            id="agent-user-cleanup-race",
            role="user",
            text="Use the evidence.",
            files=[attachment],
        ),
    )
    prepare_errors: list[BaseException] = []

    def prepare_turn() -> None:
        conn = connect()
        try:
            agent_sessions.prepare_agent_turn(conn, request)
        except BaseException as exc:
            prepare_errors.append(exc)
        finally:
            conn.close()

    prepare_thread = Thread(target=prepare_turn)
    prepare_thread.start()
    prepare_thread.join(timeout=2)
    cleanup_thread.join(timeout=2)
    assert not prepare_thread.is_alive()
    assert not cleanup_thread.is_alive()

    conn = connect()
    try:
        persisted = agent_sessions.load_agent_session(conn, session_id)
    finally:
        conn.close()
    stored = agent_attachments.load_agent_attachment(session_id, attachment)

    # Cleanup may win and make the turn fail, or consumption may win and keep
    # the file. It must never leave committed history pointing at a deleted file.
    assert not (persisted.messages and stored is None)
    if persisted.messages:
        assert not prepare_errors
        assert stored is not None
        assert stored.state == "consumed"


def test_cleanup_cannot_delete_during_attachment_readiness_handoff(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "resume-cleanup-ready-race"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="history.txt",
        payload=b"Retained history",
        media_type="text/plain",
    )

    ready_write_started = Event()
    cleanup_finished = Event()
    original_write = agent_attachments._write_metadata

    def pause_ready_write(
        metadata_session_id: str,
        attachment_id: str,
        metadata: dict[str, Any],
    ) -> None:
        if metadata.get("state") == "ready":
            ready_write_started.set()
            cleanup_finished.wait(timeout=1)
        original_write(metadata_session_id, attachment_id, metadata)

    monkeypatch.setattr(agent_attachments, "_write_metadata", pause_ready_write)

    messages = [
        AgentConversationItem(
            id="history-ready-race",
            role="user",
            text="Retain this attachment.",
            files=[attachment],
        ),
    ]
    replace_errors: list[BaseException] = []

    def replace_history() -> None:
        conn = connect()
        try:
            revision = agent_sessions.load_agent_session(conn, session_id).revision
            agent_sessions.replace_agent_session_messages(
                conn,
                session_id,
                locale="en",
                messages=messages,
                revision=revision,
            )
        except BaseException as exc:
            replace_errors.append(exc)
        finally:
            conn.close()

    replace_thread = Thread(target=replace_history)
    replace_thread.start()
    assert ready_write_started.wait(timeout=1)

    def cleanup() -> None:
        try:
            agent_attachments.cleanup_expired_pending_attachments(
                now=datetime.now(UTC) + timedelta(days=2),
            )
        finally:
            cleanup_finished.set()

    cleanup_thread = Thread(target=cleanup)
    cleanup_thread.start()
    replace_thread.join(timeout=2)
    cleanup_thread.join(timeout=2)
    assert not replace_thread.is_alive()
    assert not cleanup_thread.is_alive()

    conn = connect()
    try:
        persisted = agent_sessions.load_agent_session(conn, session_id)
    finally:
        conn.close()
    stored = agent_attachments.load_agent_attachment(session_id, attachment)

    assert not (persisted.messages and stored is None)
    if persisted.messages:
        assert not replace_errors
        assert stored is not None
        assert stored.state == "consumed"


def test_mark_sent_rejects_attachment_that_is_still_stored(
    client: TestClient,
) -> None:
    session_id = "resume-stored-attachment-consumption"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="unvalidated.txt",
        payload=b"Unvalidated evidence",
        media_type="text/plain",
    )

    with pytest.raises(
        agent_attachments.AgentAttachmentError,
        match="not ready",
    ):
        mark_agent_attachments_sent(session_id, [attachment])

    stored = agent_attachments.load_agent_attachment(session_id, attachment)
    assert stored is not None
    assert stored.state == "stored"
    assert stored.sent_at is None


def test_version_two_metadata_without_state_is_inferred(
    client: TestClient,
) -> None:
    session_id = "resume-legacy-attachment-state"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="legacy.txt",
        payload=b"Legacy metadata",
        media_type="text/plain",
    )
    metadata = agent_attachments._read_metadata(session_id, attachment["id"])
    assert metadata is not None
    metadata.pop("state")
    agent_attachments._write_metadata(session_id, attachment["id"], metadata)

    stored = agent_attachments.load_agent_attachment(session_id, attachment)
    assert stored is not None
    assert stored.state == "stored"

    agent_attachments.prevalidate_agent_attachments(session_id, [attachment])
    mark_agent_attachments_sent(session_id, [attachment])
    consumed = agent_attachments.load_agent_attachment(session_id, attachment)
    assert consumed is not None
    assert consumed.state == "consumed"


@pytest.mark.parametrize(
    ("status_code", "message", "expected"),
    [
        (400, "Unsupported attachment type application/pdf", True),
        (415, "Invalid media type for input_file", True),
        (400, "Invalid request parameter: temperature", False),
        (401, "Unsupported attachment type application/pdf", False),
        (429, "Unsupported attachment type application/pdf", False),
        (500, "Unsupported attachment type application/pdf", False),
    ],
)
def test_native_attachment_fallback_requires_explicit_client_rejection(
    status_code: int,
    message: str,
    expected: bool,
) -> None:
    error = LlmRequestError(message, status_code=status_code)

    assert is_native_attachment_unsupported(error) is expected


def test_attachment_only_message_is_persisted_without_generated_text() -> None:
    attachment = {
        "id": "attachment-id",
        "filename": "portfolio.pdf",
        "mediaType": "application/pdf",
        "kind": "text",
    }
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="agent-user-attachment",
            role="user",
            text="",
            files=[attachment],
        ),
    )

    message = _current_user_message(request, "2026-07-16T00:00:00.000Z")

    assert message is not None
    assert message.id == "agent-user-attachment"
    assert message.text == ""
    assert message.files == [attachment]


def test_attachment_filename_limit_counts_utf8_bytes(client: TestClient) -> None:
    session_id = "resume-unicode-filename"
    filename = f"{'简历' * 100}.pdf"
    payload = _pdf_with_text("Unicode filename")

    first = _upload(
        client,
        session_id=session_id,
        filename=filename,
        payload=payload,
        media_type="application/pdf",
    )
    second = _upload(
        client,
        session_id=session_id,
        filename=filename,
        payload=payload,
        media_type="application/pdf",
    )

    assert first["filename"].endswith(".pdf")
    assert second["filename"].endswith("(1).pdf")
    assert len(first["filename"].encode("utf-8")) <= 180
    assert len(second["filename"].encode("utf-8")) <= 180


def test_append_exchange_rolls_back_when_attachment_protection_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "resume-append-rollback"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="evidence.pdf",
        payload=_pdf_with_text("Evidence"),
        media_type="application/pdf",
    )
    request = AgentChatRequest(
        resumeId=session_id,
        expectedRevision=_current_session_revision(session_id),
        message=AgentConversationItem(
            id="agent-user-rollback",
            role="user",
            text="Use the evidence.",
            files=[attachment],
        ),
    )
    assistant = AgentChatMessage(
        id="agent-assistant-rollback",
        role="assistant",
        text="Done.",
    )

    def fail_protection(
        protected_session_id: str,
        files: list[dict[str, Any]],
    ) -> None:
        del protected_session_id, files
        raise OSError("metadata write failed")

    monkeypatch.setattr(
        agent_sessions,
        "mark_agent_attachments_sent",
        fail_protection,
    )

    conn = connect()
    try:
        with pytest.raises(OSError, match="metadata write failed"):
            agent_sessions.append_agent_exchange(conn, request, assistant)

        message_count = conn.execute(
            "SELECT COUNT(*) FROM agent_messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
        session_count = conn.execute(
            "SELECT COUNT(*) FROM agent_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    assert message_count == 0
    assert session_count == 0


def test_stale_assistant_is_rejected_after_session_history_replacement(
    client: TestClient,
) -> None:
    del client  # The fixture provides an isolated database for this session test.
    session_id = "resume-stale-assistant"
    request = AgentChatRequest(
        resumeId=session_id,
        expectedRevision=_current_session_revision(session_id),
        message=AgentConversationItem(
            id="agent-user-old-run",
            role="user",
            text="Old run prompt",
        ),
    )
    assistant = AgentChatMessage(
        id="agent-assistant-old-run",
        role="assistant",
        text="Old run response",
    )
    replacement = AgentConversationItem(
        id="agent-user-replacement",
        role="user",
        text="Replacement history",
    )

    conn = connect()
    try:
        agent_sessions.persist_agent_user_message(conn, request)
        revision = agent_sessions.load_agent_session(conn, session_id).revision
        agent_sessions.replace_agent_session_messages(
            conn,
            session_id,
            locale="en",
            messages=[replacement],
            revision=revision,
        )

        with pytest.raises(agent_sessions.AgentSessionTurnConflictError):
            agent_sessions.append_agent_exchange(conn, request, assistant)

        persisted = agent_sessions.load_agent_session(conn, session_id)
    finally:
        conn.close()

    assert [message.id for message in persisted.messages] == [
        "agent-user-replacement",
    ]


def test_marking_multiple_attachments_is_all_or_nothing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "resume-attachment-partial-failure"
    first = _upload(
        client,
        session_id=session_id,
        filename="first.pdf",
        payload=_pdf_with_text("First"),
        media_type="application/pdf",
    )
    second = _upload(
        client,
        session_id=session_id,
        filename="second.pdf",
        payload=_pdf_with_text("Second"),
        media_type="application/pdf",
    )
    agent_attachments.prevalidate_agent_attachments(session_id, [first, second])
    original_write_metadata = agent_attachments._write_metadata
    sent_write_count = 0

    def fail_second_sent_write(
        protected_session_id: str,
        attachment_id: str,
        metadata: dict[str, Any],
    ) -> None:
        nonlocal sent_write_count
        if metadata.get("sentAt"):
            sent_write_count += 1
        original_write_metadata(protected_session_id, attachment_id, metadata)
        if sent_write_count == 2 and metadata.get("sentAt"):
            raise OSError("second metadata write failed")

    monkeypatch.setattr(
        agent_attachments,
        "_write_metadata",
        fail_second_sent_write,
    )

    with pytest.raises(OSError, match="second metadata write failed"):
        mark_agent_attachments_sent(session_id, [first, second])

    first_attachment = agent_attachments.load_agent_attachment(session_id, first)
    second_attachment = agent_attachments.load_agent_attachment(session_id, second)
    assert first_attachment is not None
    assert second_attachment is not None
    assert first_attachment.sent_at is None
    assert second_attachment.sent_at is None


def test_user_message_and_attachment_state_are_compensated_on_db_failure(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "resume-user-message-compensation"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="evidence.pdf",
        payload=_pdf_with_text("Evidence"),
        media_type="application/pdf",
    )
    request = AgentChatRequest(
        resumeId=session_id,
        expectedRevision=_current_session_revision(session_id),
        message=AgentConversationItem(
            id="agent-user-compensation",
            role="user",
            text="Use the evidence.",
            files=[attachment],
        ),
    )

    def fail_insert(*args: object, **kwargs: object) -> bool:
        del args, kwargs
        raise OSError("message insert failed")

    monkeypatch.setattr(agent_sessions, "_insert_message", fail_insert)

    conn = connect()
    try:
        with pytest.raises(OSError, match="message insert failed"):
            agent_sessions.persist_agent_user_message(conn, request)
        message_count = conn.execute(
            "SELECT COUNT(*) FROM agent_messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()[0]
    finally:
        conn.close()

    stored_attachment = agent_attachments.load_agent_attachment(
        session_id,
        attachment,
    )
    assert message_count == 0
    assert stored_attachment is not None
    assert stored_attachment.sent_at is None


def test_replace_session_rolls_back_when_attachment_protection_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "resume-replace-rollback"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="replacement.pdf",
        payload=_pdf_with_text("Replacement"),
        media_type="application/pdf",
    )
    original = AgentConversationItem(
        id="original-user-message",
        role="user",
        text="Original message",
    )
    replacement = AgentConversationItem(
        id="replacement-user-message",
        role="user",
        text="Replacement message",
        files=[attachment],
    )

    conn = connect()
    try:
        initial_revision = agent_sessions.load_agent_session(conn, session_id).revision
        agent_sessions.replace_agent_session_messages(
            conn,
            session_id,
            locale="en",
            messages=[original],
            revision=initial_revision,
        )
        replacement_revision = agent_sessions.load_agent_session(
            conn,
            session_id,
        ).revision

        def fail_protection(
            protected_session_id: str,
            files: list[dict[str, Any]],
        ) -> None:
            del protected_session_id, files
            raise OSError("metadata write failed")

        monkeypatch.setattr(
            agent_sessions,
            "mark_agent_attachments_sent",
            fail_protection,
        )

        with pytest.raises(OSError, match="metadata write failed"):
            agent_sessions.replace_agent_session_messages(
                conn,
                session_id,
                locale="en",
                messages=[replacement],
                revision=replacement_revision,
            )

        persisted = agent_sessions.load_agent_session(conn, session_id)
    finally:
        conn.close()

    assert [message.id for message in persisted.messages] == [
        "original-user-message",
    ]


def test_history_replacement_preserves_more_than_request_attachment_limit(
    client: TestClient,
) -> None:
    session_id = "resume-history-many-attachments"
    attachments = [
        _upload(
            client,
            session_id=session_id,
            filename=f"history-{index}.txt",
            payload=f"History {index}".encode(),
            media_type="text/plain",
        )
        for index in range(agent_attachments.MAX_AGENT_CONTEXT_ATTACHMENTS + 1)
    ]
    for attachment in attachments:
        agent_attachments.prevalidate_agent_attachments(session_id, [attachment])
        mark_agent_attachments_sent(session_id, [attachment])

    messages = [
        AgentConversationItem(
            id=f"history-message-{index}",
            role="user",
            text=f"History message {index}",
            files=[attachment],
        )
        for index, attachment in enumerate(attachments)
    ]

    conn = connect()
    try:
        revision = agent_sessions.load_agent_session(conn, session_id).revision
        replaced = agent_sessions.replace_agent_session_messages(
            conn,
            session_id,
            locale="en",
            messages=messages,
            revision=revision,
        )
    finally:
        conn.close()

    assert [message.id for message in replaced.messages] == [
        message.id for message in messages
    ]
    assert sum(len(message.files) for message in replaced.messages) == len(attachments)


def test_history_replacement_ignores_current_request_aggregate_size_limit(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "resume-history-aggregate-size"
    attachments = [
        _upload(
            client,
            session_id=session_id,
            filename=f"history-{index}.txt",
            payload=b"historical attachment",
            media_type="text/plain",
        )
        for index in range(2)
    ]
    for attachment in attachments:
        agent_attachments.prevalidate_agent_attachments(session_id, [attachment])
        mark_agent_attachments_sent(session_id, [attachment])

    monkeypatch.setattr(
        agent_attachments,
        "MAX_AGENT_REQUEST_ATTACHMENT_BYTES",
        1,
    )
    messages = [
        AgentConversationItem(
            id=f"aggregate-history-message-{index}",
            role="user",
            text=f"History message {index}",
            files=[attachment],
        )
        for index, attachment in enumerate(attachments)
    ]

    conn = connect()
    try:
        revision = agent_sessions.load_agent_session(conn, session_id).revision
        replaced = agent_sessions.replace_agent_session_messages(
            conn,
            session_id,
            locale="en",
            messages=messages,
            revision=revision,
        )
    finally:
        conn.close()

    assert sum(len(message.files) for message in replaced.messages) == len(attachments)


def test_uploaded_pdf_reaches_agent_model_payload(client: TestClient) -> None:
    session_id = "resume-pdf-text"
    expected = "Senior TypeScript platform role"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="role.pdf",
        payload=_pdf_with_text(expected),
        media_type="application/pdf",
    )

    assert attachment == {
        "id": attachment["id"],
        "filename": "role.pdf",
        "mediaType": "application/pdf",
        "kind": "text",
    }

    messages = build_agent_messages(
        _request(attachment, session_id=session_id),
        _config(),
        mode="tools",
    )
    files = _current_request_files(messages)

    assert expected in files[0]["excerpt"]
    assert "blob:" not in json.dumps(attachment)


def test_uploaded_pdf_keeps_content_beyond_preview_sized_excerpt(
    client: TestClient,
) -> None:
    session_id = "resume-pdf-complete"
    expected = "late-paper-finding-retained"
    paper_text = f"{'context ' * 2_500}{expected}"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="paper.pdf",
        payload=_pdf_with_text(paper_text),
        media_type="application/pdf",
    )

    messages = build_agent_messages(
        _request(attachment, session_id=session_id),
        _config(),
        mode="tools",
    )

    assert expected in _current_request_files(messages)[0]["excerpt"]


def test_historical_attachment_is_not_resent_implicitly(
    client: TestClient,
) -> None:
    session_id = "resume-history"
    expected = "hierarchical visual context improves fine-grained perception"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="paper.pdf",
        payload=_pdf_with_text(expected),
        media_type="application/pdf",
    )
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="user-follow-up",
            role="user",
            text="Summarize the paper again.",
        ),
        messages=[
            AgentConversationItem(
                id="user-with-paper",
                role="user",
                text="Read this paper.",
                files=[attachment],
            ),
            AgentConversationItem(
                id="assistant-summary",
                role="assistant",
                text="I reviewed the paper.",
            ),
        ],
        locale="en",
        resume={"basic": {}, "sections": []},
        resume_id=session_id,
        expected_revision=SYNTHETIC_SESSION_REVISION,
    )

    messages = build_agent_messages(request, _config(), mode="tools")
    files = _current_request_files(messages)

    assert files == []
    assert expected not in json.dumps(messages)


def test_historical_attachment_can_be_explicitly_referenced_again(
    client: TestClient,
) -> None:
    session_id = "resume-reference"
    expected = "stable-material-context"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="notes.pdf",
        payload=_pdf_with_text(expected),
        media_type="application/pdf",
    )
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="user-current",
            role="user",
            text="What did the notes say?",
            files=[attachment],
        ),
        locale="en",
        resume={"basic": {}, "sections": []},
        resume_id=session_id,
        expected_revision=SYNTHETIC_SESSION_REVISION,
    )

    messages = build_agent_messages(request, _config(), mode="tools")
    files = _current_request_files(messages)

    assert expected in files[0]["excerpt"]
    assert files[0]["filename"] == "notes.pdf"


def test_uploaded_docx_reaches_agent_model_payload(client: TestClient) -> None:
    session_id = "resume-docx"
    expected = "Reduced deployment time by 35 percent"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="evidence.docx",
        payload=_docx_with_text(expected),
        media_type=(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ),
    )

    messages = build_agent_messages(
        _request(attachment, session_id=session_id),
        _config(),
        mode="tools",
    )

    assert expected in _current_request_files(messages)[0]["excerpt"]


def test_uploaded_image_is_mapped_for_every_visual_adapter(
    client: TestClient,
) -> None:
    session_id = "resume-image"
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
        "/x8AAusB9Wl6Y2sAAAAASUVORK5CYII=",
    )
    attachment = _upload(
        client,
        session_id=session_id,
        filename="portfolio.png",
        payload=png,
        media_type="image/png",
    )

    messages = build_agent_messages(
        _request(attachment, session_id=session_id),
        _config(),
        mode="tools",
    )
    content = messages[-1]["content"]

    assert isinstance(content, list)
    assert content[1] == {
        "type": "image",
        "filename": "portfolio.png",
        "media_type": "image/png",
        "data": base64.b64encode(png).decode("ascii"),
    }

    chat_messages = common.chat_completion_params(
        _config(),
        messages,
        stream=False,
    )["messages"]
    assert chat_messages[-1]["content"][1] == {
        "type": "image_url",
        "image_url": {
            "url": f"data:image/png;base64,{base64.b64encode(png).decode('ascii')}",
        },
    }

    _, responses_items = openai_responses.responses_input(messages)
    assert responses_items[-1]["content"][1] == {
        "type": "input_image",
        "image_url": f"data:image/png;base64,{base64.b64encode(png).decode('ascii')}",
    }

    _, anthropic_items = anthropic_messages.anthropic_messages(messages)
    assert anthropic_items[-1]["content"][1] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": base64.b64encode(png).decode("ascii"),
        },
    }

    gemini_items = google_gemini.gemini_payload(_config(), messages)["input"]
    assert gemini_items[-1]["content"][1] == {
        "type": "image",
        "data": base64.b64encode(png).decode("ascii"),
        "mime_type": "image/png",
    }


def test_original_attachment_can_be_downloaded_only_from_owning_session(
    client: TestClient,
) -> None:
    session_id = "resume-download"
    payload = _pdf_with_text("Download the original bytes")
    attachment = _upload(
        client,
        session_id=session_id,
        filename="report.pdf",
        payload=payload,
        media_type="application/pdf",
    )

    response = client.get(
        f"/api/agent/resumes/{session_id}/attachments/{attachment['id']}",
    )
    wrong_session_response = client.get(
        f"/api/agent/resumes/another-resume/attachments/{attachment['id']}",
    )

    assert response.status_code == 200
    assert response.content == payload
    assert response.headers["content-type"].startswith("application/pdf")
    assert wrong_session_response.status_code == 404
    assert wrong_session_response.json()["code"] == APP_CODE_NOT_FOUND


def test_duplicate_filenames_use_compact_numbered_suffix(
    client: TestClient,
) -> None:
    session_id = "resume-collisions"
    payload = _pdf_with_text("Same display filename")

    first = _upload(
        client,
        session_id=session_id,
        filename="report.pdf",
        payload=payload,
        media_type="application/pdf",
    )
    second = _upload(
        client,
        session_id=session_id,
        filename="report.pdf",
        payload=payload,
        media_type="application/pdf",
    )

    assert first["filename"] == "report.pdf"
    assert second["filename"] == "report(1).pdf"


def test_pending_attachment_can_be_deleted_but_sent_history_is_protected(
    client: TestClient,
) -> None:
    session_id = "resume-pending-delete"
    pending = _upload(
        client,
        session_id=session_id,
        filename="pending.pdf",
        payload=_pdf_with_text("Pending"),
        media_type="application/pdf",
    )
    sent = _upload(
        client,
        session_id=session_id,
        filename="sent.pdf",
        payload=_pdf_with_text("Sent"),
        media_type="application/pdf",
    )
    agent_attachments.prevalidate_agent_attachments(session_id, [sent])
    mark_agent_attachments_sent(session_id, [sent])

    pending_response = client.delete(
        f"/api/agent/resumes/{session_id}/attachments/{pending['id']}",
    )
    sent_response = client.delete(
        f"/api/agent/resumes/{session_id}/attachments/{sent['id']}",
    )

    assert pending_response.status_code == 200
    deleted_pending_response = client.get(
        f"/api/agent/resumes/{session_id}/attachments/{pending['id']}",
    )
    assert deleted_pending_response.status_code == 404
    assert deleted_pending_response.json()["code"] == APP_CODE_NOT_FOUND
    assert sent_response.status_code == 404
    assert sent_response.json()["code"] == APP_CODE_NOT_FOUND
    assert (
        client.get(
            f"/api/agent/resumes/{session_id}/attachments/{sent['id']}",
        ).status_code
        == 200
    )


def test_permanent_resume_delete_preserves_records_when_attachment_cleanup_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        "/api/resumes",
        json={"title": "Protected attachment"},
    ).json()["data"]["resume"]
    resume_id = created["id"]
    initial_session = client.get(
        f"/api/agent/resumes/{resume_id}/session",
    ).json()["data"]
    session_response = client.put(
        f"/api/agent/resumes/{resume_id}/session",
        json={
            "locale": "en",
            "revision": initial_session["revision"],
            "messages": [
                {
                    "id": "protected-attachment-message",
                    "role": "user",
                    "text": "Keep this session if cleanup fails.",
                },
            ],
        },
    )
    assert session_response.status_code == 200

    attachment = _upload(
        client,
        session_id=resume_id,
        filename="private.txt",
        payload=b"private resume material",
        media_type="text/plain",
    )
    stored = agent_attachments.load_agent_attachment(resume_id, attachment)
    assert stored is not None
    attachment_root = stored.path.parent.resolve()

    trash_response = client.post(f"/api/resumes/{resume_id}/trash")
    assert trash_response.status_code == 200

    real_rmtree = agent_attachments.shutil.rmtree

    def deny_attachment_cleanup(
        path: str | Path,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        if Path(path).resolve() == attachment_root:
            if kwargs.get("ignore_errors"):
                return
            raise PermissionError("attachment cleanup denied")
        real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(
        agent_attachments.shutil,
        "rmtree",
        deny_attachment_cleanup,
    )

    with pytest.raises(PermissionError, match="attachment cleanup denied"):
        client.delete(f"/api/resumes/{resume_id}")

    assert stored.path.read_bytes() == b"private resume material"
    with connect() as conn:
        resume_row = conn.execute(
            "SELECT deleted FROM resumes WHERE id = ?",
            (resume_id,),
        ).fetchone()
        session_row = conn.execute(
            "SELECT id FROM agent_sessions WHERE id = ?",
            (resume_id,),
        ).fetchone()

    assert resume_row is not None
    assert resume_row["deleted"] == 1
    assert session_row is not None


def test_delete_agent_session_attachments_accepts_missing_directory(
    client: TestClient,
) -> None:
    del client  # The fixture provides isolated attachment storage and settings.

    agent_attachments.delete_agent_session_attachments(
        "missing-attachment-session",
    )


def test_attachment_rollback_does_not_recreate_deleted_session_directory(
    client: TestClient,
) -> None:
    session_id = "resume-deleted-attachment-rollback"
    attachment = _upload(
        client,
        session_id=session_id,
        filename="private.txt",
        payload=b"private rollback data",
        media_type="text/plain",
    )
    agent_attachments.prevalidate_agent_attachments(session_id, [attachment])
    receipt = mark_agent_attachments_sent(session_id, [attachment])
    attachment_root = (
        get_settings().storage_dir
        / agent_attachments.ATTACHMENT_STORAGE_DIRNAME
        / session_id
    )

    agent_attachments.delete_agent_session_attachments(session_id)
    agent_attachments.rollback_agent_attachments_sent(receipt)

    assert not attachment_root.exists()


def test_attachment_upload_rejects_permanently_deleted_resume(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/resumes",
        json={"title": "Deleted attachment owner"},
    ).json()["data"]["resume"]
    resume_id = created["id"]
    assert client.post(f"/api/resumes/{resume_id}/trash").status_code == 200
    assert client.delete(f"/api/resumes/{resume_id}").status_code == 200

    response = client.post(
        "/api/agent/attachments",
        data={"resumeId": resume_id},
        files={"file": ("orphan.txt", b"private data", "text/plain")},
    )
    attachment_root = (
        get_settings().storage_dir
        / agent_attachments.ATTACHMENT_STORAGE_DIRNAME
        / resume_id
    )

    assert response.status_code == 404
    assert not attachment_root.exists()


def test_attachment_upload_rejects_trashed_resume(client: TestClient) -> None:
    created = client.post(
        "/api/resumes",
        json={"title": "Trashed attachment owner"},
    ).json()["data"]["resume"]
    resume_id = created["id"]
    assert client.post(f"/api/resumes/{resume_id}/trash").status_code == 200

    response = client.post(
        "/api/agent/attachments",
        data={"resumeId": resume_id},
        files={"file": ("orphan.txt", b"private data", "text/plain")},
    )

    assert response.status_code == 404


def test_session_replace_rejects_permanently_deleted_resume(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/resumes",
        json={"title": "Deleted session owner"},
    ).json()["data"]["resume"]
    resume_id = created["id"]
    revision = client.get(
        f"/api/agent/resumes/{resume_id}/session",
    ).json()["data"]["revision"]
    assert client.post(f"/api/resumes/{resume_id}/trash").status_code == 200
    assert client.delete(f"/api/resumes/{resume_id}").status_code == 200

    response = client.put(
        f"/api/agent/resumes/{resume_id}/session",
        json={
            "locale": "en",
            "revision": revision,
            "messages": [
                {
                    "id": "orphan-session-message",
                    "role": "user",
                    "text": "private orphaned message",
                },
            ],
        },
    )

    assert response.status_code == 404
    with connect() as conn:
        session_count = conn.execute(
            "SELECT COUNT(*) FROM agent_sessions WHERE resume_id = ?",
            (resume_id,),
        ).fetchone()[0]
        message_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM agent_messages
            WHERE session_id = ?
            """,
            (resume_id,),
        ).fetchone()[0]
    assert session_count == 0
    assert message_count == 0


def test_agent_chat_rejects_permanently_deleted_resume(
    client: TestClient,
) -> None:
    created = client.post(
        "/api/resumes",
        json={"title": "Deleted chat owner"},
    ).json()["data"]["resume"]
    resume_id = created["id"]
    revision = client.get(
        f"/api/agent/resumes/{resume_id}/session",
    ).json()["data"]["revision"]
    assert client.post(f"/api/resumes/{resume_id}/trash").status_code == 200
    assert client.delete(f"/api/resumes/{resume_id}").status_code == 200

    response = client.post(
        "/api/agent/chat",
        json={
            "resumeId": resume_id,
            "expectedRevision": revision,
            "message": {
                "id": "orphan-chat-message",
                "role": "user",
                "text": "private orphaned chat",
            },
            "messages": [],
            "locale": "en",
            "resume": {"basic": {}, "sections": []},
        },
    )

    assert response.status_code == 404
    with connect() as conn:
        session_count = conn.execute(
            "SELECT COUNT(*) FROM agent_sessions WHERE resume_id = ?",
            (resume_id,),
        ).fetchone()[0]
        message_count = conn.execute(
            "SELECT COUNT(*) FROM agent_messages WHERE session_id = ?",
            (resume_id,),
        ).fetchone()[0]
        execution_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM agent_turn_executions
            WHERE session_id = ?
            """,
            (resume_id,),
        ).fetchone()[0]
    assert session_count == 0
    assert message_count == 0
    assert execution_count == 0


def test_inflight_attachment_upload_is_removed_by_permanent_delete(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        "/api/resumes",
        json={"title": "Concurrent attachment owner"},
    ).json()["data"]["resume"]
    resume_id = created["id"]
    upload_entered = Event()
    release_upload = Event()
    delete_started = Event()
    real_write_original = agent_attachments._write_original_with_unique_name

    def wait_before_writing(
        session_root: Path,
        filename: str,
        payload: bytes,
    ) -> Path:
        upload_entered.set()
        assert release_upload.wait(timeout=2)
        return real_write_original(session_root, filename, payload)

    monkeypatch.setattr(
        agent_attachments,
        "_write_original_with_unique_name",
        wait_before_writing,
    )
    results: dict[str, Any] = {}

    def upload() -> None:
        results["upload"] = client.post(
            "/api/agent/attachments",
            data={"resumeId": resume_id},
            files={"file": ("private.txt", b"private data", "text/plain")},
        )

    def delete() -> None:
        delete_started.set()
        results["trash"] = resumes.trash_resume(resume_id)
        results["delete"] = resumes.delete_resume_forever(resume_id)

    upload_thread = Thread(target=upload)
    delete_thread = Thread(target=delete)
    upload_thread.start()
    assert upload_entered.wait(timeout=2)
    delete_thread.start()
    assert delete_started.wait(timeout=2)
    release_upload.set()
    upload_thread.join(timeout=3)
    delete_thread.join(timeout=3)

    assert not upload_thread.is_alive()
    assert not delete_thread.is_alive()
    assert results["upload"].status_code == 200
    assert results["delete"] == {"id": resume_id}
    attachment_root = (
        get_settings().storage_dir
        / agent_attachments.ATTACHMENT_STORAGE_DIRNAME
        / resume_id
    )
    assert not attachment_root.exists()
    with connect() as conn:
        resume_row = conn.execute(
            "SELECT id FROM resumes WHERE id = ?",
            (resume_id,),
        ).fetchone()
    assert resume_row is None


def test_chat_prevalidation_cannot_recreate_cache_after_permanent_delete(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = client.post(
        "/api/resumes",
        json={"title": "Concurrent chat attachment owner"},
    ).json()["data"]["resume"]
    resume_id = created["id"]
    attachment = _upload(
        client,
        session_id=resume_id,
        filename="private.txt",
        payload=b"private attachment text",
        media_type="text/plain",
    )
    revision = client.get(
        f"/api/agent/resumes/{resume_id}/session",
    ).json()["data"]["revision"]
    extraction_started = Event()
    release_extraction = Event()
    deletion_finished = Event()
    real_extract = agent_attachments._extract_attachment_text

    def wait_after_reading(
        stored: agent_attachments.StoredAgentAttachment,
        payload: bytes,
    ) -> str:
        text = real_extract(stored, payload)
        extraction_started.set()
        assert release_extraction.wait(timeout=2)
        return text

    monkeypatch.setattr(
        agent_attachments,
        "_extract_attachment_text",
        wait_after_reading,
    )
    results: dict[str, Any] = {}

    def start_chat() -> None:
        results["chat"] = client.post(
            "/api/agent/chat",
            json={
                "resumeId": resume_id,
                "expectedRevision": revision,
                "message": {
                    "id": "concurrent-private-attachment",
                    "role": "user",
                    "text": "Use the private attachment.",
                    "files": [attachment],
                },
                "messages": [],
                "locale": "en",
                "resume": {"basic": {}, "sections": []},
            },
        )

    def delete_resume() -> None:
        try:
            results["trash"] = resumes.trash_resume(resume_id)
            try:
                results["delete"] = resumes.delete_resume_forever(resume_id)
            except BaseException as exc:
                results["delete_error"] = exc
        finally:
            deletion_finished.set()

    chat_thread = Thread(target=start_chat)
    delete_thread = Thread(target=delete_resume)
    chat_thread.start()
    assert extraction_started.wait(timeout=2)
    delete_thread.start()
    deletion_finished.wait(timeout=1)
    release_extraction.set()
    chat_thread.join(timeout=3)
    delete_thread.join(timeout=3)

    assert not chat_thread.is_alive()
    assert not delete_thread.is_alive()
    if delete_error := results.get("delete_error"):
        assert getattr(delete_error, "status_code", None) == 409
        results["delete"] = resumes.delete_resume_forever(resume_id)
    assert results["delete"] == {"id": resume_id}
    attachment_root = (
        get_settings().storage_dir
        / agent_attachments.ATTACHMENT_STORAGE_DIRNAME
        / resume_id
    )
    assert not attachment_root.exists()


def test_supported_native_pdf_uses_original_bytes(client: TestClient) -> None:
    session_id = "resume-native-pdf"
    payload = _pdf_with_text("Native PDF payload")
    attachment = _upload(
        client,
        session_id=session_id,
        filename="native.pdf",
        payload=payload,
        media_type="application/pdf",
    )

    messages = build_agent_messages(
        _request(attachment, session_id=session_id),
        _config(api_family="openai_responses"),
        mode="tools",
    )
    content = messages[-1]["content"]

    assert isinstance(content, list)
    assert content[1] == {
        "type": "file",
        "filename": "native.pdf",
        "media_type": "application/pdf",
        "data": base64.b64encode(payload).decode("ascii"),
    }

    _, responses_items = openai_responses.responses_input(messages)
    assert responses_items[-1]["content"][1] == {
        "type": "input_file",
        "filename": "native.pdf",
        "file_data": (
            f"data:application/pdf;base64,{base64.b64encode(payload).decode('ascii')}"
        ),
    }

    _, anthropic_items = anthropic_messages.anthropic_messages(messages)
    assert anthropic_items[-1]["content"][1] == {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.b64encode(payload).decode("ascii"),
        },
    }


@pytest.mark.parametrize(
    ("source_stem", "expected_stem", "case_id"),
    [
        ("John_Smith_CV", "[redacted_name]_CV", "underscore"),
        ("John-Smith-CV", "[redacted_name]-CV", "hyphen"),
        ("John.Smith.CV", "[redacted_name].CV", "period"),
    ],
)
@pytest.mark.parametrize(
    ("extension", "media_type", "part_type"),
    [
        ("pdf", "application/pdf", "file"),
        ("png", "image/png", "image"),
    ],
)
def test_native_attachment_filename_hides_resume_name_without_changing_bytes(
    client: TestClient,
    source_stem: str,
    expected_stem: str,
    case_id: str,
    extension: str,
    media_type: str,
    part_type: str,
) -> None:
    session_id = f"resume-private-native-{extension}-filename-{case_id}"
    payload = (
        _pdf_with_text("Public project evidence")
        if extension == "pdf"
        else base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
            "/x8AAusB9Wl6Y2sAAAAASUVORK5CYII=",
        )
    )
    attachment = _upload(
        client,
        session_id=session_id,
        filename=f"{source_stem}.{extension}",
        payload=payload,
        media_type=media_type,
    )
    request = _request(attachment, session_id=session_id)
    request.resume["basic"]["name"] = "John Smith"

    messages = build_agent_messages(
        request,
        _config(api_family="openai_responses"),
        mode="tools",
    )
    content = messages[-1]["content"]

    assert isinstance(content, list)
    assert content[1] == {
        "type": part_type,
        "filename": f"{expected_stem}.{extension}",
        "media_type": media_type,
        "data": base64.b64encode(payload).decode("ascii"),
    }

    if part_type == "file":
        _, responses_items = openai_responses.responses_input(messages)
        provider_part = responses_items[-1]["content"][1]
        assert provider_part["filename"] == f"{expected_stem}.{extension}"
        assert f"{source_stem}.{extension}" not in json.dumps(responses_items)


@pytest.mark.parametrize(
    ("filename", "expected_filename", "case_id"),
    [
        ("John_Smith_CV.pdf", "[redacted_name]_CV.pdf", "underscore"),
        ("John-Smith-CV.pdf", "[redacted_name]-CV.pdf", "hyphen"),
        ("John.Smith.CV.pdf", "[redacted_name].CV.pdf", "period"),
    ],
)
def test_historical_native_attachment_filename_hides_resume_name_without_bytes(
    client: TestClient,
    filename: str,
    expected_filename: str,
    case_id: str,
) -> None:
    session_id = f"resume-private-native-history-filename-{case_id}"
    payload = _pdf_with_text("Historical project evidence")
    attachment = _upload(
        client,
        session_id=session_id,
        filename=filename,
        payload=payload,
        media_type="application/pdf",
    )
    request = AgentChatRequest(
        message=AgentConversationItem(
            id=f"current-native-history-{case_id}",
            role="user",
            text="Use the earlier evidence.",
        ),
        messages=[
            AgentConversationItem(
                id=f"historical-native-file-{case_id}",
                role="user",
                text="Read this evidence.",
                files=[attachment],
            ),
        ],
        locale="en",
        resume={"basic": {"name": "John Smith"}, "sections": []},
        resume_id=session_id,
        expected_revision=SYNTHETIC_SESSION_REVISION,
    )

    messages = build_agent_messages(
        request,
        _config(api_family="openai_responses"),
        mode="tools",
    )
    serialized = json.dumps(messages)

    assert expected_filename in serialized
    assert filename not in serialized
    assert base64.b64encode(payload).decode("ascii") not in serialized


def test_more_than_five_current_attachments_is_rejected() -> None:
    files = [
        {
            "id": uuid4().hex,
            "filename": f"file-{index}.pdf",
            "mediaType": "application/pdf",
            "kind": "text",
        }
        for index in range(6)
    ]
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-attachments-over-limit",
            role="user",
            text="Review all files.",
            files=files,
        ),
        locale="en",
        resume={"basic": {}, "sections": []},
        resume_id="resume-too-many",
        expected_revision=SYNTHETIC_SESSION_REVISION,
    )

    with pytest.raises(LlmRequestError, match="At most 5 attachments"):
        build_agent_messages(request, _config(), mode="tools")
