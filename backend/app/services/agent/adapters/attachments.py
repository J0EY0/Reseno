from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.schemas.agent import AgentChatRequest, AgentToolInvocation

from ..attachments import AgentAttachmentError, attachment_text
from ..privacy import sanitize_agent_text
from ..runtime.context import AgentRuntimeContext

ATTACHMENT_READ_CHARS = 16_000


def historical_text_attachment_files(
    request: AgentChatRequest,
) -> tuple[dict[str, Any], ...]:
    """Return addressable text files from prior user turns only."""

    if not (request.resume_id or "").strip():
        return ()

    current_ids = {
        attachment_id
        for file in request.message.files
        if isinstance(file, dict)
        and (attachment_id := _attachment_id(file.get("id"))) is not None
    }
    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for message in request.messages:
        if message.role != "user":
            continue
        for file in message.files:
            if not isinstance(file, dict) or file.get("kind") != "text":
                continue
            attachment_id = _attachment_id(file.get("id"))
            if (
                attachment_id is None
                or attachment_id in current_ids
                or attachment_id in seen
            ):
                continue
            seen.add(attachment_id)
            files.append(
                {
                    "id": attachment_id,
                    "filename": str(file.get("filename") or "Attachment"),
                    "kind": "text",
                },
            )
    return tuple(files)


@dataclass(frozen=True)
class AttachmentReadResult:
    invocation: AgentToolInvocation
    evidence_ref: str | None = None
    material_text: str = ""


@dataclass(frozen=True)
class AttachmentToolAdapter:
    """Read only text attachments explicitly retained in this request history."""

    _session_id: str
    _files_by_id: dict[str, dict[str, Any]]
    _hidden_terms: tuple[str, ...]

    @classmethod
    def open(
        cls,
        request: AgentChatRequest,
        *,
        hidden_terms: tuple[str, ...],
    ) -> AttachmentToolAdapter:
        files = historical_text_attachment_files(request)
        return cls(
            _session_id=(request.resume_id or "").strip(),
            _files_by_id={str(file["id"]): file for file in files},
            _hidden_terms=hidden_terms,
        )

    async def invoke(
        self,
        attachment_id: object,
        offset: object,
        runtime: AgentRuntimeContext,
    ) -> AttachmentReadResult:
        normalized_id = _attachment_id(attachment_id)
        file = self._files_by_id.get(normalized_id or "")
        if file is None:
            return self._error(
                attachment_id,
                offset,
                "The attachment is not available in this conversation history.",
            )
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            return self._error(
                normalized_id,
                offset,
                "The attachment offset must be a non-negative integer.",
            )

        try:
            text = await runtime.run_sync(
                attachment_text,
                self._session_id,
                file,
            )
        except AgentAttachmentError as exc:
            return self._error(normalized_id, offset, str(exc))
        if offset > len(text):
            return self._error(
                normalized_id,
                offset,
                "The attachment offset is beyond the end of the document.",
            )

        end = min(len(text), offset + ATTACHMENT_READ_CHARS)
        material = text[offset:end]
        excerpt = sanitize_agent_text(material, hidden_terms=self._hidden_terms)
        invocation = AgentToolInvocation(
            id="",
            type="tool-attachment_read",
            title="attachment_read",
            state="output-available",
            input={"attachmentId": normalized_id, "offset": offset},
            output={
                "attachmentId": normalized_id,
                "filename": sanitize_agent_text(
                    str(file["filename"]),
                    hidden_terms=self._hidden_terms,
                ),
                "excerpt": excerpt,
                "offset": offset,
                "nextOffset": end if end < len(text) else None,
                "totalChars": len(text),
            },
        )
        return AttachmentReadResult(
            invocation=invocation,
            evidence_ref=f"attachment:{normalized_id}",
            material_text=material,
        )

    @staticmethod
    def _error(
        attachment_id: object,
        offset: object,
        message: str,
    ) -> AttachmentReadResult:
        return AttachmentReadResult(
            invocation=AgentToolInvocation(
                id="",
                type="tool-attachment_read",
                title="attachment_read",
                state="output-error",
                input={"attachmentId": attachment_id, "offset": offset},
                errorText=message,
            ),
        )


def _attachment_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value.strip()).hex
    except ValueError:
        return None


__all__ = [
    "ATTACHMENT_READ_CHARS",
    "AttachmentReadResult",
    "AttachmentToolAdapter",
    "historical_text_attachment_files",
]
