import base64
import io
import json
import zipfile
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.connection import connect
from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentConversationItem,
)
from app.schemas.common import APP_CODE_NOT_FOUND
from app.services import agent_sessions
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
        prompt="Use the attached material.",
        files=[attachment],
        locale="en",
        resume={"basic": {}, "sections": []},
        resume_id=session_id,
    )


def _upload(
    client: TestClient,
    *,
    session_id: str,
    filename: str,
    payload: bytes,
    media_type: str,
) -> dict[str, Any]:
    response = client.post(
        "/api/agent/attachments",
        data={"resumeId": session_id},
        files={"file": (filename, payload, media_type)},
    )
    assert response.status_code == 200
    return response.json()["data"]


def _user_payload(messages: list[dict[str, Any]]) -> dict[str, Any]:
    content = messages[-1]["content"]
    if isinstance(content, list):
        text_part = next(part for part in content if part.get("type") == "text")
        content = text_part["text"]

    assert isinstance(content, str)
    return json.loads(content)


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
        files=[attachment],
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
        prompt="Use the evidence.",
        files=[attachment],
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
        agent_sessions.replace_agent_session_messages(
            conn,
            session_id,
            locale="en",
            messages=[original],
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

        with pytest.raises(OSError, match="metadata write failed"):
            agent_sessions.replace_agent_session_messages(
                conn,
                session_id,
                locale="en",
                messages=[replacement],
            )

        persisted = agent_sessions.load_agent_session(conn, session_id)
    finally:
        conn.close()

    assert [message.id for message in persisted.messages] == [
        "original-user-message",
    ]


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
    payload = _user_payload(messages)

    assert expected in payload["files"][0]["excerpt"]
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

    assert expected in _user_payload(messages)["files"][0]["excerpt"]


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
        prompt="Summarize the paper again.",
        files=[],
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
            AgentConversationItem(
                id="user-follow-up",
                role="user",
                text="Summarize the paper again.",
            ),
        ],
        locale="en",
        resume={"basic": {}, "sections": []},
        resume_id=session_id,
    )

    messages = build_agent_messages(request, _config(), mode="tools")
    payload = _user_payload(messages)

    assert payload["files"] == []
    assert expected not in json.dumps(payload)


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
        prompt="What did the notes say?",
        files=[attachment],
        message=AgentConversationItem(
            id="user-current",
            role="user",
            text="What did the notes say?",
            files=[attachment],
        ),
        locale="en",
        resume={"basic": {}, "sections": []},
        resume_id=session_id,
    )

    messages = build_agent_messages(request, _config(), mode="tools")
    payload = _user_payload(messages)

    assert expected in payload["files"][0]["excerpt"]
    assert payload["files"][0]["filename"] == "notes.pdf"


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

    assert expected in _user_payload(messages)["files"][0]["excerpt"]


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
    assert wrong_session_response.status_code == 200
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
    mark_agent_attachments_sent(session_id, [sent])

    pending_response = client.delete(
        f"/api/agent/resumes/{session_id}/attachments/{pending['id']}",
    )
    sent_response = client.delete(
        f"/api/agent/resumes/{session_id}/attachments/{sent['id']}",
    )

    assert pending_response.status_code == 200
    assert (
        client.get(
            f"/api/agent/resumes/{session_id}/attachments/{pending['id']}",
        ).json()["code"]
        == APP_CODE_NOT_FOUND
    )
    assert sent_response.status_code == 200
    assert sent_response.json()["code"] == APP_CODE_NOT_FOUND
    assert (
        client.get(
            f"/api/agent/resumes/{session_id}/attachments/{sent['id']}",
        ).status_code
        == 200
    )


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
        prompt="Review all files.",
        files=files,
        locale="en",
        resume={"basic": {}, "sections": []},
        resume_id="resume-too-many",
    )

    with pytest.raises(LlmRequestError, match="At most 5 attachments"):
        build_agent_messages(request, _config(), mode="tools")
