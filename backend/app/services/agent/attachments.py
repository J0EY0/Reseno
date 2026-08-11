from __future__ import annotations

import io
import json
import re
import shutil
import xml.etree.ElementTree as ElementTree
import zipfile
from base64 import b64encode
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import RLock
from typing import Any, Literal
from uuid import UUID, uuid4

from pypdf import PdfReader

from app.config import get_settings
from app.db.connection import connect
from app.schemas.agent import AgentAttachmentResponse, AgentChatRequest
from app.services.agent.privacy import sanitize_agent_text
from app.services.agent.resume_owner import active_resume_transaction

MAX_AGENT_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_AGENT_ATTACHMENT_TEXT_CHARS = 250_000
MAX_AGENT_CONTEXT_ATTACHMENTS = 5
# Request-level caps bound aggregate provider payload and extraction memory even
# when every individual attachment remains below its own limit.
MAX_AGENT_REQUEST_ATTACHMENT_BYTES = 20 * 1024 * 1024
MAX_AGENT_REQUEST_ATTACHMENT_TEXT_CHARS = 400_000
MAX_AGENT_ATTACHMENT_FILENAME_BYTES = 180
MAX_PDF_PAGES = 50
MAX_DOCX_XML_BYTES = 8 * 1024 * 1024
ATTACHMENT_STORAGE_VERSION = 2
ATTACHMENT_STORAGE_DIRNAME = "agent-attachments"
ATTACHMENT_METADATA_DIRNAME = ".metadata"
ATTACHMENT_CACHE_DIRNAME = ".cache"
UNSENT_ATTACHMENT_TTL = timedelta(hours=24)
DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

_SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$")
_TEXT_SUFFIXES = {
    ".csv",
    ".json",
    ".md",
    ".markdown",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

# Attachment metadata and SQLite history cannot share one transaction. This
# process-local lock makes cleanup/manual deletion and the consumption handoff
# mutually exclusive, so a stale unsent snapshot cannot delete a file after its
# message becomes authoritative. ResuMate runs one backend process by default;
# avoiding a persistent lock keeps this development-stage boundary lightweight.
_ATTACHMENT_LIFECYCLE_LOCK = RLock()


class AgentAttachmentError(ValueError):
    """Raised when an attachment cannot be stored or read safely."""


@dataclass(frozen=True)
class StoredAgentAttachment:
    """One original file and its storage metadata."""

    id: str
    filename: str
    media_type: str
    kind: Literal["text", "image"]
    size: int
    path: Path
    created_at: str
    sent_at: str | None
    state: Literal["stored", "ready", "consumed"]


@dataclass(frozen=True)
class AgentAttachmentPrevalidation:
    """Validated current-turn attachment totals."""

    attachment_ids: tuple[str, ...]
    total_bytes: int
    total_text_chars: int


@dataclass(frozen=True)
class AgentAttachmentSentReceipt:
    """Metadata snapshots used to compensate a cross-store message write."""

    session_id: str
    previous_metadata: tuple[tuple[str, dict[str, Any]], ...]


def current_request_attachments(request: AgentChatRequest) -> list[dict[str, Any]]:
    """Return only files explicitly attached to the current user request.

    Historical message attachments remain downloadable and can be explicitly
    referenced again by the frontend, but they are never re-sent implicitly.
    This prevents old file bytes from growing every later model request.
    """

    files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for file in request.message.files:
        if not isinstance(file, dict):
            continue
        attachment_id = _normalized_attachment_id(file.get("id"))
        if attachment_id is None or attachment_id in seen:
            continue
        seen.add(attachment_id)
        files.append(file)

    if len(files) > MAX_AGENT_CONTEXT_ATTACHMENTS:
        raise AgentAttachmentError(
            f"At most {MAX_AGENT_CONTEXT_ATTACHMENTS} attachments can be sent "
            "in one request.",
        )

    return files


def store_agent_attachment(
    *,
    session_id: str,
    filename: str,
    media_type: str,
    payload: bytes,
) -> AgentAttachmentResponse:
    """Validate and persist an original inside an already-authorized session.

    Upload intentionally does not extract document text. The original file is
    canonical; extraction is lazy and cached only when an adapter needs a text
    fallback. HTTP uploads must use ``store_resume_agent_attachment`` so the
    filesystem write cannot outlive its resume owner.
    """

    if not _is_valid_session_id(session_id):
        raise AgentAttachmentError("The Agent session id is invalid.")
    if not payload:
        raise AgentAttachmentError("The attachment is empty.")
    if len(payload) > MAX_AGENT_ATTACHMENT_BYTES:
        raise AgentAttachmentError("The attachment exceeds the size limit.")

    safe_filename = _safe_filename(filename)
    kind, detected_media_type = _validate_attachment(
        safe_filename,
        _normalized_media_type(media_type),
        payload,
    )
    with _ATTACHMENT_LIFECYCLE_LOCK:
        attachment_id = uuid4().hex
        session_root = _session_root(session_id)
        session_root.mkdir(parents=True, exist_ok=True)
        original_path = _write_original_with_unique_name(
            session_root,
            safe_filename,
            payload,
        )
        now = _now_iso()

        try:
            metadata = {
                "version": ATTACHMENT_STORAGE_VERSION,
                "id": attachment_id,
                "filename": original_path.name,
                "mediaType": detected_media_type,
                "kind": kind,
                "size": len(payload),
                "createdAt": now,
                "sentAt": None,
                "state": "stored",
            }
            _write_metadata(session_id, attachment_id, metadata)
        except Exception:
            original_path.unlink(missing_ok=True)
            raise

        return AgentAttachmentResponse(
            id=attachment_id,
            filename=original_path.name,
            mediaType=detected_media_type,
            kind=kind,
        )


def store_resume_agent_attachment(
    *,
    resume_id: str,
    filename: str,
    media_type: str,
    payload: bytes,
) -> AgentAttachmentResponse:
    """Store an upload only while its active resume still exists.

    The immediate transaction uses the same DB-before-attachment lock order as
    permanent resume deletion. An upload either finishes before deletion and
    is removed with the resume, or observes that deletion already won.
    """

    with closing(connect()) as conn, active_resume_transaction(conn, resume_id):
        attachment = store_agent_attachment(
            session_id=resume_id,
            filename=filename,
            media_type=media_type,
            payload=payload,
        )

    return attachment


def load_agent_attachment(
    session_id: str,
    file_or_id: dict[str, Any] | str,
) -> StoredAgentAttachment | None:
    """Resolve an opaque attachment id within one session boundary."""

    if not _is_valid_session_id(session_id):
        return None

    raw_id = file_or_id.get("id") if isinstance(file_or_id, dict) else file_or_id
    attachment_id = _normalized_attachment_id(raw_id)
    if attachment_id is None:
        return None

    metadata = _read_metadata(session_id, attachment_id)
    if metadata is None:
        return None

    filename = _safe_filename(str(metadata.get("filename") or "attachment"))
    path = _session_root(session_id) / filename
    if not path.is_file():
        return None

    kind = metadata.get("kind")
    if kind not in {"text", "image"}:
        return None

    size = metadata.get("size")
    if not isinstance(size, int) or size < 0:
        return None

    return StoredAgentAttachment(
        id=attachment_id,
        filename=filename,
        media_type=str(metadata.get("mediaType") or ""),
        kind=kind,
        size=size,
        path=path,
        created_at=str(metadata.get("createdAt") or ""),
        sent_at=(
            str(metadata["sentAt"]) if isinstance(metadata.get("sentAt"), str) else None
        ),
        state=_metadata_state(metadata),
    )


def prevalidate_agent_attachments(
    session_id: str,
    files: list[dict[str, Any]],
    *,
    can_consume_native: Callable[[StoredAgentAttachment], bool] | None = None,
) -> AgentAttachmentPrevalidation:
    """Validate that every current-turn file can be consumed before commit.

    Native-capable files keep their original bytes. Other documents must
    produce readable text, which also warms the extraction cache for runtime.
    Metadata advances to ``ready`` only after the whole batch succeeds.
    """

    unique_files = _unique_attachment_files(files)
    if len(unique_files) > MAX_AGENT_CONTEXT_ATTACHMENTS:
        raise AgentAttachmentError(
            f"At most {MAX_AGENT_CONTEXT_ATTACHMENTS} attachments can be sent "
            "in one request.",
        )

    native_predicate = can_consume_native or (lambda _attachment: False)
    attachments: list[StoredAgentAttachment] = []
    total_bytes = 0
    total_text_chars = 0

    for file in unique_files:
        attachment = load_agent_attachment(session_id, file)
        if attachment is None:
            raise AgentAttachmentError("The attachment is no longer available.")
        payload = _read_validated_payload(attachment)

        total_bytes += len(payload)
        if total_bytes > MAX_AGENT_REQUEST_ATTACHMENT_BYTES:
            raise AgentAttachmentError(
                "The attachments exceed the total size limit for one request.",
            )

        if native_predicate(attachment):
            _validate_native_attachment(attachment, payload)
        elif attachment.kind == "image":
            raise AgentAttachmentError(
                "The selected model cannot consume this image attachment.",
            )
        else:
            text = attachment_text(session_id, file)
            total_text_chars += len(text)
            if total_text_chars > MAX_AGENT_REQUEST_ATTACHMENT_TEXT_CHARS:
                raise AgentAttachmentError(
                    "The extracted attachments exceed the total text limit "
                    "for one request.",
                )
        attachments.append(attachment)

    _mark_agent_attachments_ready(session_id, attachments)
    return AgentAttachmentPrevalidation(
        attachment_ids=tuple(attachment.id for attachment in attachments),
        total_bytes=total_bytes,
        total_text_chars=total_text_chars,
    )


def prepare_agent_history_attachments(
    session_id: str,
    files: list[dict[str, Any]],
) -> tuple[str, ...]:
    """Validate retained history references without current-request quotas.

    History replacement persists metadata; it does not send attachment bytes
    to a provider. Applying request count, aggregate byte, or extracted-text
    limits here would reject otherwise valid long-lived conversations.
    """

    attachments: list[StoredAgentAttachment] = []
    for file in _unique_attachment_files(files):
        attachment = load_agent_attachment(session_id, file)
        if attachment is None:
            raise AgentAttachmentError("The attachment is no longer available.")
        attachments.append(attachment)

    # A stored upload may enter history through replacement rather than a model
    # request. Advance it only after every retained reference resolves so the
    # later consumption step remains all-or-nothing.
    _mark_agent_attachments_ready(session_id, attachments)
    return tuple(attachment.id for attachment in attachments)


def attachment_text(session_id: str, file: dict[str, Any]) -> str:
    """Return cached or lazily extracted text for one original file."""

    attachment = load_agent_attachment(session_id, file)
    if attachment is None:
        raise AgentAttachmentError("The attachment is no longer available.")
    if attachment.kind == "image":
        return ""

    cache_path = _cache_path(session_id, attachment.id)
    try:
        cached = cache_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        cached = ""
    except OSError as exc:
        raise AgentAttachmentError("The attachment cache could not be read.") from exc
    if cached:
        return cached

    try:
        payload = attachment.path.read_bytes()
    except OSError as exc:
        raise AgentAttachmentError("The attachment could not be read.") from exc

    try:
        text = _extract_attachment_text(attachment, payload)
    except AgentAttachmentError:
        raise
    except Exception as exc:
        # Extractor/parser internals are not stable API and must not escape the
        # attachment boundary or leave a half-committed user turn.
        raise AgentAttachmentError(
            "The attachment could not be extracted.",
        ) from exc
    # Extraction can be slow. Revalidate only the cache commit under the
    # lifecycle lock so cleanup or permanent deletion cannot remove the owner
    # and then have this worker recreate an orphan cache containing PII.
    with _ATTACHMENT_LIFECYCLE_LOCK:
        if load_agent_attachment(session_id, attachment.id) is None:
            raise AgentAttachmentError("The attachment is no longer available.")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        _write_text_atomic(cache_path, text)
    return text


def attachment_content_part(
    session_id: str,
    file: dict[str, Any],
    *,
    hidden_terms: tuple[str, ...],
) -> dict[str, str]:
    """Build one provider-neutral current-request binary content block."""

    attachment = load_agent_attachment(session_id, file)
    if attachment is None:
        raise AgentAttachmentError("The attachment is no longer available.")
    try:
        payload = attachment.path.read_bytes()
    except OSError as exc:
        raise AgentAttachmentError("The attachment could not be read.") from exc

    part_type = "image" if attachment.kind == "image" else "file"
    return {
        "type": part_type,
        # Native attachments bypass the extracted-text sanitizer, so their
        # display name must be masked at the binary boundary itself. The file
        # bytes remain canonical and unchanged; only provider-visible metadata
        # is sanitized.
        "filename": sanitize_agent_text(
            attachment.filename,
            hidden_terms=hidden_terms,
        ),
        "media_type": attachment.media_type,
        "data": b64encode(payload).decode("ascii"),
    }


def mark_agent_attachments_sent(
    session_id: str,
    files: list[dict[str, Any]],
) -> AgentAttachmentSentReceipt:
    """Mark message attachments as sent, rolling back any partial file update."""

    with _ATTACHMENT_LIFECYCLE_LOCK:
        pending_updates: list[tuple[str, dict[str, Any]]] = []
        for attachment_id in _attachment_ids(files):
            metadata = _read_metadata(session_id, attachment_id)
            if metadata is None:
                raise AgentAttachmentError("The attachment is no longer available.")
            state = _metadata_state(metadata)
            if state == "stored":
                # Consumption is the commit point; validation must have advanced
                # every attachment in the turn before any metadata is mutated.
                raise AgentAttachmentError(
                    "The attachment is not ready to be consumed.",
                )
            if state == "ready":
                pending_updates.append((attachment_id, dict(metadata)))

        receipt = AgentAttachmentSentReceipt(
            session_id=session_id,
            previous_metadata=tuple(pending_updates),
        )
        sent_at = _now_iso()
        attempted_count = 0
        try:
            for attachment_id, previous_metadata in pending_updates:
                metadata = {
                    **previous_metadata,
                    "sentAt": sent_at,
                    "state": "consumed",
                }
                # Include the current file before writing: storage wrappers may
                # raise after the atomic replace has already reached disk.
                attempted_count += 1
                _write_metadata(session_id, attachment_id, metadata)
        except BaseException:
            partial_receipt = AgentAttachmentSentReceipt(
                session_id=session_id,
                previous_metadata=receipt.previous_metadata[:attempted_count],
            )
            try:
                rollback_agent_attachments_sent(partial_receipt)
            except Exception as rollback_exc:
                raise AgentAttachmentError(
                    "Attachment metadata could not be restored after a partial update.",
                ) from rollback_exc
            raise

    return receipt


def rollback_agent_attachments_sent(
    receipt: AgentAttachmentSentReceipt | None,
) -> None:
    """Restore attachment metadata after the related database write fails."""

    if receipt is None:
        return
    with _ATTACHMENT_LIFECYCLE_LOCK:
        for attachment_id, metadata in receipt.previous_metadata:
            filename = _safe_filename(str(metadata.get("filename") or "attachment"))
            if not (_session_root(receipt.session_id) / filename).is_file():
                # Permanent deletion already won. Restoring metadata would
                # recreate an orphan directory with a PII-bearing filename.
                continue
            _write_metadata(receipt.session_id, attachment_id, dict(metadata))


def delete_pending_agent_attachment(session_id: str, attachment_id: str) -> bool:
    """Delete an unsent upload; sent history must use session lifecycle cleanup."""

    with _ATTACHMENT_LIFECYCLE_LOCK:
        attachment = load_agent_attachment(session_id, attachment_id)
        if attachment is None or attachment.sent_at is not None:
            return False
        _delete_attachment_files(session_id, attachment)
        return True


def prune_sent_agent_attachments(
    session_id: str,
    retained_files: list[dict[str, Any]],
) -> None:
    """Remove sent originals no longer referenced after history replacement."""

    with _ATTACHMENT_LIFECYCLE_LOCK:
        retained_ids = set(_attachment_ids(retained_files))
        for attachment in _iter_session_attachments(session_id):
            if attachment.sent_at is None or attachment.id in retained_ids:
                continue
            _delete_attachment_files(session_id, attachment)
        _remove_empty_session_dirs(session_id)


def delete_agent_session_attachments(session_id: str) -> None:
    """Delete every original and cache owned by a permanently removed session."""

    if not _is_valid_session_id(session_id):
        return
    with _ATTACHMENT_LIFECYCLE_LOCK:
        try:
            shutil.rmtree(_session_root(session_id))
        except FileNotFoundError:
            pass


def cleanup_expired_pending_attachments(
    *,
    now: datetime | None = None,
) -> int:
    """Delete abandoned, unsent uploads without touching chat history files."""

    cutoff = (now or datetime.now(UTC)) - UNSENT_ATTACHMENT_TTL
    deleted = 0
    root = _attachment_root()
    try:
        session_dirs = [path for path in root.iterdir() if path.is_dir()]
    except OSError:
        return 0

    for session_dir in session_dirs:
        if not _is_valid_session_id(session_dir.name):
            continue
        for attachment in _iter_session_attachments(session_dir.name):
            # Re-read under the same lock used by consumption. The object from
            # iteration is only a candidate and may already be stale.
            with _ATTACHMENT_LIFECYCLE_LOCK:
                current = load_agent_attachment(session_dir.name, attachment.id)
                if current is None or current.sent_at is not None:
                    continue
                created_at = _parse_iso(current.created_at)
                if created_at is None or created_at > cutoff:
                    continue
                _delete_attachment_files(session_dir.name, current)
                deleted += 1
        with _ATTACHMENT_LIFECYCLE_LOCK:
            _remove_empty_session_dirs(session_dir.name)

    return deleted


def _attachment_root() -> Path:
    root = get_settings().storage_dir / ATTACHMENT_STORAGE_DIRNAME
    root.mkdir(parents=True, exist_ok=True)
    return root


def _session_root(session_id: str) -> Path:
    return _attachment_root() / session_id


def _metadata_path(session_id: str, attachment_id: str) -> Path:
    return (
        _session_root(session_id)
        / ATTACHMENT_METADATA_DIRNAME
        / f"{attachment_id}.json"
    )


def _cache_path(session_id: str, attachment_id: str) -> Path:
    return _session_root(session_id) / ATTACHMENT_CACHE_DIRNAME / f"{attachment_id}.txt"


def _read_metadata(session_id: str, attachment_id: str) -> dict[str, Any] | None:
    try:
        metadata = json.loads(
            _metadata_path(session_id, attachment_id).read_text(encoding="utf-8"),
        )
    except (OSError, ValueError, TypeError):
        return None

    if not isinstance(metadata, dict):
        return None
    if metadata.get("version") != ATTACHMENT_STORAGE_VERSION:
        return None
    if metadata.get("id") != attachment_id:
        return None
    return metadata


def _write_metadata(
    session_id: str,
    attachment_id: str,
    metadata: dict[str, Any],
) -> None:
    path = _metadata_path(session_id, attachment_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(
        path,
        json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
    )


def _write_text_atomic(path: Path, value: str) -> None:
    temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary_path.write_text(value, encoding="utf-8")
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _write_original_with_unique_name(
    session_root: Path,
    filename: str,
    payload: bytes,
) -> Path:
    """Atomically allocate `name.ext`, then `name(1).ext`, without spaces."""

    path = Path(filename)
    stem = path.stem or "attachment"
    suffix = path.suffix
    sequence = 0
    while True:
        marker = "" if sequence == 0 else f"({sequence})"
        candidate = session_root / _bounded_filename(
            f"{stem}{suffix}",
            marker=marker,
        )
        try:
            with candidate.open("xb") as handle:
                handle.write(payload)
            return candidate
        except FileExistsError:
            sequence += 1


def _iter_session_attachments(session_id: str) -> list[StoredAgentAttachment]:
    metadata_dir = _session_root(session_id) / ATTACHMENT_METADATA_DIRNAME
    try:
        metadata_files = list(metadata_dir.glob("*.json"))
    except OSError:
        return []

    attachments: list[StoredAgentAttachment] = []
    for metadata_file in metadata_files:
        attachment = load_agent_attachment(session_id, metadata_file.stem)
        if attachment is not None:
            attachments.append(attachment)
    return attachments


def _delete_attachment_files(
    session_id: str,
    attachment: StoredAgentAttachment,
) -> None:
    attachment.path.unlink(missing_ok=True)
    _metadata_path(session_id, attachment.id).unlink(missing_ok=True)
    _cache_path(session_id, attachment.id).unlink(missing_ok=True)


def _remove_empty_session_dirs(session_id: str) -> None:
    session_root = _session_root(session_id)
    for child_name in (ATTACHMENT_CACHE_DIRNAME, ATTACHMENT_METADATA_DIRNAME):
        child = session_root / child_name
        try:
            child.rmdir()
        except OSError:
            pass
    try:
        session_root.rmdir()
    except OSError:
        pass


def _attachment_ids(files: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    seen: set[str] = set()
    for file in files:
        if not isinstance(file, dict):
            continue
        attachment_id = _normalized_attachment_id(file.get("id"))
        if attachment_id is None or attachment_id in seen:
            continue
        seen.add(attachment_id)
        ids.append(attachment_id)
    return ids


def _unique_attachment_files(
    files: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    unique_files: list[dict[str, Any]] = []
    seen: set[str] = set()
    for file in files:
        if not isinstance(file, dict):
            raise AgentAttachmentError("The attachment reference is invalid.")
        attachment_id = _normalized_attachment_id(file.get("id"))
        if attachment_id is None:
            raise AgentAttachmentError("The attachment reference is invalid.")
        if attachment_id in seen:
            continue
        seen.add(attachment_id)
        unique_files.append(file)
    return unique_files


def _normalized_attachment_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value).hex
    except ValueError:
        return None


def _is_valid_session_id(value: str) -> bool:
    return bool(_SESSION_ID_PATTERN.fullmatch(value))


def _safe_filename(filename: str) -> str:
    cleaned = Path(filename.replace("\x00", "")).name.strip()
    reserved_names = {
        ".",
        "..",
        ATTACHMENT_METADATA_DIRNAME,
        ATTACHMENT_CACHE_DIRNAME,
    }
    if not cleaned or cleaned in reserved_names:
        return "attachment"
    return _bounded_filename(cleaned)


def _bounded_filename(filename: str, *, marker: str = "") -> str:
    """Fit a filename within the storage byte limit while preserving suffix."""

    path = Path(filename)
    suffix_budget = max(
        0,
        MAX_AGENT_ATTACHMENT_FILENAME_BYTES - len(marker.encode("utf-8")) - 1,
    )
    suffix = _truncate_utf8(path.suffix, suffix_budget)
    stem_budget = max(
        1,
        MAX_AGENT_ATTACHMENT_FILENAME_BYTES
        - len(marker.encode("utf-8"))
        - len(suffix.encode("utf-8")),
    )
    stem = _truncate_utf8(path.stem or "attachment", stem_budget)
    if not stem:
        stem = "a"
    return f"{stem}{marker}{suffix}"


def _truncate_utf8(value: str, max_bytes: int) -> str:
    """Truncate text on a UTF-8 codepoint boundary."""

    encoded = value.encode("utf-8")
    if len(encoded) <= max_bytes:
        return value
    if max_bytes <= 0:
        return ""
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _normalized_media_type(media_type: str) -> str:
    return media_type.partition(";")[0].strip().lower()


def _validate_attachment(
    filename: str,
    media_type: str,
    payload: bytes,
) -> tuple[Literal["text", "image"], str]:
    suffix = Path(filename).suffix.lower()

    if media_type == "application/pdf" or suffix == ".pdf":
        if not payload.startswith(b"%PDF-"):
            raise AgentAttachmentError("The PDF file is invalid.")
        return "text", "application/pdf"

    if media_type == DOCX_MEDIA_TYPE or suffix == ".docx":
        _validate_docx(payload)
        return "text", DOCX_MEDIA_TYPE

    image_media_type = _detected_image_media_type(payload)
    if image_media_type is not None:
        return "image", image_media_type
    if media_type.startswith("image/"):
        raise AgentAttachmentError("The image format is not supported.")

    if media_type.startswith("text/") or suffix in _TEXT_SUFFIXES:
        return "text", media_type or "text/plain"

    raise AgentAttachmentError("The attachment type is not supported.")


def _read_validated_payload(attachment: StoredAgentAttachment) -> bytes:
    try:
        payload = attachment.path.read_bytes()
    except OSError as exc:
        raise AgentAttachmentError("The attachment could not be read.") from exc

    if len(payload) != attachment.size or len(payload) > MAX_AGENT_ATTACHMENT_BYTES:
        raise AgentAttachmentError("The stored attachment size is invalid.")

    kind, media_type = _validate_attachment(
        attachment.filename,
        attachment.media_type,
        payload,
    )
    if kind != attachment.kind or media_type != attachment.media_type:
        raise AgentAttachmentError("The stored attachment metadata is invalid.")
    return payload


def _validate_native_attachment(
    attachment: StoredAgentAttachment,
    payload: bytes,
) -> None:
    if attachment.media_type != "application/pdf":
        return
    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
        if reader.is_encrypted:
            raise AgentAttachmentError("Encrypted PDF attachments are not supported.")
        # Accessing the page tree catches truncated cross-reference structures
        # without requiring text extraction from scanned/native PDF inputs.
        len(reader.pages)
    except AgentAttachmentError:
        raise
    except Exception as exc:
        raise AgentAttachmentError("The PDF could not be read.") from exc


def _validate_docx(payload: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            document_info = archive.getinfo("word/document.xml")
            if document_info.file_size > MAX_DOCX_XML_BYTES:
                raise AgentAttachmentError("The DOCX document is too large.")
    except AgentAttachmentError:
        raise
    except (KeyError, OSError, zipfile.BadZipFile) as exc:
        raise AgentAttachmentError("The DOCX file could not be read.") from exc


def _extract_attachment_text(
    attachment: StoredAgentAttachment,
    payload: bytes,
) -> str:
    if attachment.media_type == "application/pdf":
        return _extract_pdf_text(payload)
    if attachment.media_type == DOCX_MEDIA_TYPE:
        return _extract_docx_text(payload)
    return _decode_text(payload)


def _extract_pdf_text(payload: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(payload), strict=False)
        if len(reader.pages) > MAX_PDF_PAGES:
            raise AgentAttachmentError(
                "The PDF has too many pages for direct attachment extraction.",
            )
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
    except AgentAttachmentError:
        raise
    except Exception as exc:
        # PDF parsers raise several format-specific errors. Collapse them at
        # this untrusted-file boundary without leaking parser internals.
        raise AgentAttachmentError("The PDF could not be read.") from exc

    return _require_text(text)


def _extract_docx_text(payload: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            document_info = archive.getinfo("word/document.xml")
            if document_info.file_size > MAX_DOCX_XML_BYTES:
                raise AgentAttachmentError("The DOCX document is too large.")
            document_xml = archive.read(document_info)
        root = ElementTree.fromstring(document_xml)
    except AgentAttachmentError:
        raise
    except (KeyError, OSError, ValueError, zipfile.BadZipFile) as exc:
        raise AgentAttachmentError("The DOCX file could not be read.") from exc
    except ElementTree.ParseError as exc:
        raise AgentAttachmentError("The DOCX document XML is invalid.") from exc

    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        text = "".join(
            node.text or "" for node in paragraph.iter(f"{namespace}t")
        ).strip()
        if text:
            paragraphs.append(text)
    return _require_text("\n".join(paragraphs))


def _decode_text(payload: bytes) -> str:
    if payload.startswith((b"\xff\xfe", b"\xfe\xff")):
        return _require_text(payload.decode("utf-16"))
    try:
        text = payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = payload.decode("utf-8", errors="replace")
    return _require_text(text)


def _require_text(value: str) -> str:
    text = value.replace("\x00", "").strip()
    if not text:
        raise AgentAttachmentError("No readable text was found in the attachment.")
    if len(text) > MAX_AGENT_ATTACHMENT_TEXT_CHARS:
        raise AgentAttachmentError(
            "The extracted attachment is too large for a single model request.",
        )
    return text


def _metadata_state(
    metadata: dict[str, Any],
) -> Literal["stored", "ready", "consumed"]:
    state = metadata.get("state")
    if state == "stored":
        return "stored"
    if state == "ready":
        return "ready"
    if state == "consumed":
        return "consumed"
    # Version 2 metadata created before lifecycle states remains valid during
    # development; sentAt is sufficient to infer its terminal state.
    return "consumed" if metadata.get("sentAt") else "stored"


def _mark_agent_attachments_ready(
    session_id: str,
    attachments: list[StoredAgentAttachment],
) -> None:
    with _ATTACHMENT_LIFECYCLE_LOCK:
        pending_updates: list[tuple[str, dict[str, Any]]] = []
        for attachment in attachments:
            # Re-resolve the original under the lifecycle lock. Without this
            # check, cleanup could delete both files after validation and a
            # later metadata write could resurrect a file-less attachment.
            if load_agent_attachment(session_id, attachment.id) is None:
                raise AgentAttachmentError("The attachment is no longer available.")
            metadata = _read_metadata(session_id, attachment.id)
            if metadata is None:
                raise AgentAttachmentError("The attachment is no longer available.")
            if _metadata_state(metadata) == "stored":
                pending_updates.append((attachment.id, dict(metadata)))

        attempted_count = 0
        try:
            for attachment_id, previous_metadata in pending_updates:
                attempted_count += 1
                _write_metadata(
                    session_id,
                    attachment_id,
                    {**previous_metadata, "state": "ready"},
                )
        except BaseException:
            try:
                for attachment_id, metadata in pending_updates[:attempted_count]:
                    _write_metadata(session_id, attachment_id, metadata)
            except Exception as rollback_exc:
                raise AgentAttachmentError(
                    "Attachment metadata could not be restored after validation.",
                ) from rollback_exc
            raise


def _detected_image_media_type(payload: bytes) -> str | None:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if len(payload) >= 12 and payload[:4] == b"RIFF" and payload[8:12] == b"WEBP":
        return "image/webp"
    return None


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
