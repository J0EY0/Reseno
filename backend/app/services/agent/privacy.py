import re
from copy import deepcopy
from difflib import SequenceMatcher
from html import escape
from typing import Any

from app.services.resume_rich_text import (
    ResumeTextProjection,
    ResumeTextSpan,
    resume_text_content,
    resume_text_projection,
)

PII_BASIC_FIELDS = frozenset({"name", "phone", "email", "location", "avatar"})
HIDDEN_BASIC_VALUE = "[hidden]"
_REDACTION_MARKER_RE = re.compile(
    r"\[(?:hidden|redacted(?:_[^\[\]]*)?)\]", re.IGNORECASE
)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_CANDIDATE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d(?!\w)")
HTTP_URL_RE = re.compile(r"https?://[^\s<>\"']+", flags=re.IGNORECASE)
DATE_RANGE_RE = re.compile(
    r"(?:19|20)\d{2}\s*[./-]\s*(?:0?[1-9]|1[0-2])\s*"
    r"(?:-|–|—|至|to)\s*"
    r"(?:19|20)\d{2}\s*[./-]\s*(?:0?[1-9]|1[0-2])",
    flags=re.IGNORECASE,
)
TIMESTAMP_RE = re.compile(
    r"(?:19|20)\d{2}[./-](?:0?[1-9]|1[0-2])[./-]"
    r"(?:0?[1-9]|[12]\d|3[01])[T\s]+"
    r"(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?"
    r"(?:Z|[+-]\d{2}:?\d{2})?",
    flags=re.IGNORECASE,
)


def is_pii_basic_path(path: str) -> bool:
    """Return whether a basic path targets model-hidden personal data."""

    return path.startswith("basic.") and path[6:] in PII_BASIC_FIELDS


class AgentPrivacyPlaceholderError(ValueError):
    """Raised when an edit contains a privacy marker without an exact original."""


def resume_hidden_terms(*resumes: dict[str, Any]) -> tuple[str, ...]:
    """Return stable identity slots shared by saved and active resume views."""

    terms: list[str] = []
    for resume in resumes:
        basic = resume.get("basic")
        if not isinstance(basic, dict):
            continue
        for field in ("name", "location"):
            value = basic.get(field)
            if isinstance(value, str):
                normalized = resume_text_content(value).strip()
                if len(normalized) >= 2 and normalized not in terms:
                    terms.append(normalized)
    return tuple(terms)


def restore_agent_edit_value(value: Any, *, hidden_terms: tuple[str, ...]) -> Any:
    """Restore known identity slots and reject opaque privacy markers in edits."""

    originals = {
        f"[redacted_identity_{index}]": term for index, term in enumerate(hidden_terms)
    }

    def restore_marker(match: re.Match[str], *, rich_text: bool) -> str:
        marker = match.group(0)
        original = originals.get(marker)
        if original is None and (fragment := re.fullmatch(
            r"\[redacted_identity_(\d+)_(\d+)_(\d+)\]", marker,
        )):
            index, start, end = map(int, fragment.groups())
            if (
                index < len(hidden_terms)
                and 0 <= start < end <= len(hidden_terms[index])
            ):
                original = hidden_terms[index][start:end]
        if original is None:
            raise AgentPrivacyPlaceholderError(
                "The edit contains an unresolved privacy placeholder. "
                "Keep the protected text unchanged and edit the surrounding content."
            )
        return escape(original, quote=False) if rich_text else original

    def restore(current: Any) -> Any:
        if isinstance(current, str):
            rich_text = resume_text_projection(current) is not None
            return _REDACTION_MARKER_RE.sub(
                lambda match: restore_marker(match, rich_text=rich_text), current,
            )
        if isinstance(current, list):
            return [restore(item) for item in current]
        if isinstance(current, dict):
            return {key: restore(item) for key, item in current.items()}
        return current

    return restore(value)


def sanitize_agent_text(
    value: str,
    *,
    hidden_terms: tuple[str, ...] = (),
) -> str:
    """Mask personal contact strings before text is sent to the model."""

    projection = resume_text_projection(value)
    if projection is not None:
        value = _sanitize_rich_text(value, projection, hidden_terms)

    text = EMAIL_RE.sub("[redacted_email]", value)
    text = PHONE_CANDIDATE_RE.sub(_phone_replacement, text)
    for index, term in sorted(
        enumerate(hidden_terms),
        key=lambda entry: len(entry[1]),
        reverse=True,
    ):
        if term:
            text = _replace_hidden_term(text, term, f"[redacted_identity_{index}]")
    return text


def sanitize_agent_value(
    value: Any,
    *,
    hidden_terms: tuple[str, ...] = (),
) -> Any:
    """Recursively mask personal data in model-visible payloads."""

    if isinstance(value, str):
        return sanitize_agent_text(value, hidden_terms=hidden_terms)

    if isinstance(value, list):
        return [sanitize_agent_value(item, hidden_terms=hidden_terms) for item in value]

    if isinstance(value, dict):
        return {
            key: sanitize_agent_value(item, hidden_terms=hidden_terms)
            for key, item in value.items()
        }

    return value


def sanitize_agent_resume(
    resume: dict[str, Any],
    *,
    hidden_terms: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Return a model-visible resume copy without raw personal identity fields."""

    terms = hidden_terms if hidden_terms is not None else resume_hidden_terms(resume)
    sanitized = sanitize_agent_value(deepcopy(resume), hidden_terms=terms)
    if not isinstance(sanitized, dict):
        return {}

    source_basic = resume.get("basic")
    source_basic_data = source_basic if isinstance(source_basic, dict) else {}
    field_status = _basic_field_status(source_basic_data)
    basic = sanitized.setdefault("basic", {})
    if isinstance(basic, dict):
        for field in PII_BASIC_FIELDS:
            # Preserve the distinction between absent and deliberately hidden
            # values. An empty replacement makes models report that populated
            # personal fields are missing, while this marker reveals no value.
            basic[field] = (
                "" if field_status.get(field) == "missing" else HIDDEN_BASIC_VALUE
            )

    sanitized["basicFieldStatus"] = field_status
    return sanitized


def _phone_replacement(match: re.Match[str]) -> str:
    if DATE_RANGE_RE.fullmatch(match.group(0).strip()):
        return match.group(0)
    if any(
        timestamp.start() <= match.start() and match.end() <= timestamp.end()
        for timestamp in TIMESTAMP_RE.finditer(match.string)
    ):
        return match.group(0)
    if _is_numeric_url_path_segment(match):
        return match.group(0)
    digits = re.sub(r"\D", "", match.group(0))
    if len(digits) < 10:
        return match.group(0)
    return "[redacted_phone]"


def _is_numeric_url_path_segment(match: re.Match[str]) -> bool:
    if not match.group(0).isdigit():
        return False

    for url_match in HTTP_URL_RE.finditer(match.string):
        if not (url_match.start() <= match.start() and match.end() <= url_match.end()):
            continue

        url = url_match.group(0)
        authority_start = url.find("://") + 3
        path_start = url.find("/", authority_start)
        if path_start == -1:
            return False

        path_end = len(url)
        for separator in ("?", "#"):
            separator_index = url.find(separator, path_start)
            if separator_index != -1:
                path_end = min(path_end, separator_index)

        relative_start = match.start() - url_match.start()
        relative_end = match.end() - url_match.start()
        return path_start < relative_start and relative_end <= path_end

    return False


def _hidden_term_pattern(
    term: str, *, allow_script_suffix: bool = False,
) -> re.Pattern[str]:
    western_name_tokens = [
        token for token in re.split(r"[\s._'’\-]+", term.strip()) if token
    ]
    if len(western_name_tokens) >= 2 and all(
        re.fullmatch(r"[A-Za-z]+", token) for token in western_name_tokens
    ):
        normalized_name = r"[\s._'’\-]+".join(
            re.escape(token) for token in western_name_tokens
        )
        suffix = "" if allow_script_suffix else r"(?![^\W_])"
        return re.compile(
            rf"(?<![^\W_]){normalized_name}{suffix}", flags=re.IGNORECASE,
        )

    if re.fullmatch(r"[\w\s.'-]+", term, flags=re.ASCII):
        suffix = "" if allow_script_suffix else r"(?!\w)"
        pattern = rf"(?<!\w){re.escape(term)}{suffix}"
        return re.compile(pattern)

    return re.compile(re.escape(term))



def _replace_hidden_term(text: str, term: str, replacement: str) -> str:
    return _hidden_term_pattern(term).sub(lambda _: replacement, text)


def _identity_slice_offsets(value: str, canonical: str) -> list[int]:
    if len(value) == len(canonical):
        return list(range(len(value) + 1))
    offsets = [0] * (len(value) + 1)
    for _, start, end, canonical_start, canonical_end in SequenceMatcher(
        None, value.casefold(), canonical.casefold(), autojunk=False,
    ).get_opcodes():
        width = end - start
        for index in range(start, end + 1):
            offsets[index] = canonical_start + (
                (index - start) * (canonical_end - canonical_start) // width
                if width else canonical_end - canonical_start
            )
    return offsets


def _sanitize_rich_text(
    value: str,
    projection: ResumeTextProjection,
    hidden_terms: tuple[str, ...],
) -> str:
    text = projection.text
    redactions: list[tuple[int, int, str, int | None]] = [
        (match.start(), match.end(), "[redacted_email]", None)
        for match in EMAIL_RE.finditer(text)
    ]
    for match in PHONE_CANDIDATE_RE.finditer(text):
        if (
            _phone_replacement(match) != match.group(0)
            and not any(start < match.end() and match.start() < end
                        for start, end, _, _ in redactions)
        ):
            redactions.append((match.start(), match.end(), "[redacted_phone]", None))
    for index, term in sorted(
        enumerate(hidden_terms), key=lambda entry: len(entry[1]), reverse=True,
    ):
        if not term:
            continue
        full_pattern = _hidden_term_pattern(term)
        rich_pattern = _hidden_term_pattern(term, allow_script_suffix=True)
        for match in rich_pattern.finditer(text):
            if (full_pattern.match(text, match.start()) is None
                    and match.end() not in projection.script_boundaries):
                continue
            if any(start < match.end() and match.start() < end
                   for start, end, _, _ in redactions):
                continue
            redactions.append((
                match.start(), match.end(), f"[redacted_identity_{index}]", index,
            ))

    replacements: dict[ResumeTextSpan, list[tuple[int, int, str]]] = {}
    for start, end, marker, identity_index in redactions:
        spans = [span for span in projection.spans
                 if span.text_start < end and start < span.text_end]
        offsets = (
            _identity_slice_offsets(text[start:end], hidden_terms[identity_index])
            if identity_index is not None and len(spans) > 1 else None
        )
        for span_index, span in enumerate(spans):
            text_start = max(start, span.text_start)
            text_end = min(end, span.text_end)
            replacement = marker if span_index == 0 else ""
            if offsets is not None:
                slice_start = offsets[text_start - start]
                slice_end = offsets[text_end - start]
                replacement = (
                    f"[redacted_identity_{identity_index}_{slice_start}_{slice_end}]"
                    if slice_start < slice_end else ""
                )
            replacements.setdefault(span, []).append((
                text_start - span.text_start, text_end - span.text_start, replacement,
            ))

    for span, edits in sorted(
        replacements.items(), key=lambda entry: entry[0].source_start, reverse=True,
    ):
        content = text[span.text_start:span.text_end]
        for start, end, replacement in sorted(edits, reverse=True):
            content = content[:start] + replacement + content[end:]
        value = (
            value[:span.source_start] + escape(content, quote=False)
            + value[span.source_end:]
        )
    return value


def _basic_field_status(basic: dict[str, Any]) -> dict[str, str]:
    return {
        "name": _presence_status(basic.get("name")),
        "phone": _phone_status(basic.get("phone")),
        "email": _email_status(basic.get("email")),
        "location": _presence_status(basic.get("location")),
        "avatar": _presence_status(basic.get("avatar")),
    }


def _presence_status(value: Any) -> str:
    return "present" if isinstance(value, str) and value.strip() else "missing"


def _email_status(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "missing"
    return "present" if EMAIL_RE.fullmatch(value.strip()) else "invalid"


def _phone_status(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "missing"
    digits = re.sub(r"\D", "", value)
    return "present" if len(digits) >= 10 else "invalid"
