import re
from copy import deepcopy
from typing import Any

PII_BASIC_FIELDS = frozenset({"name", "phone", "email", "location", "avatar"})
HIDDEN_BASIC_VALUE = "[hidden]"
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


def resume_hidden_terms(resume: dict[str, Any]) -> tuple[str, ...]:
    """Return exact identity strings that should not enter model context."""

    basic = resume.get("basic")
    if not isinstance(basic, dict):
        return ()

    # Direct fields are replaced below, while this shared set also removes
    # copies embedded in summaries, attachments, tool output, and web queries.
    terms: list[str] = []
    for field in ("name", "location"):
        value = basic.get(field)
        if isinstance(value, str) and len(value.strip()) >= 2:
            normalized = value.strip()
            if normalized not in terms:
                terms.append(normalized)
    return tuple(terms)


def sanitize_agent_text(
    value: str,
    *,
    hidden_terms: tuple[str, ...] = (),
) -> str:
    """Mask personal contact strings before text is sent to the model."""

    text = EMAIL_RE.sub("[redacted_email]", value)
    text = PHONE_CANDIDATE_RE.sub(_phone_replacement, text)
    for term in sorted((term for term in hidden_terms if term), key=len, reverse=True):
        text = _replace_hidden_term(text, term)
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


def _replace_hidden_term(text: str, term: str) -> str:
    western_name_tokens = [
        token for token in re.split(r"[\s._'’\-]+", term.strip()) if token
    ]
    if len(western_name_tokens) >= 2 and all(
        re.fullmatch(r"[A-Za-z]+", token) for token in western_name_tokens
    ):
        normalized_name = r"[\s._'’\-]+".join(
            re.escape(token) for token in western_name_tokens
        )
        return re.sub(
            rf"(?<![^\W_]){normalized_name}(?![^\W_])",
            "[redacted_name]",
            text,
            flags=re.IGNORECASE,
        )

    if re.fullmatch(r"[\w\s.'-]+", term, flags=re.ASCII):
        pattern = rf"(?<!\w){re.escape(term)}(?!\w)"
        return re.sub(pattern, "[redacted_name]", text)

    return text.replace(term, "[redacted_name]")


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
