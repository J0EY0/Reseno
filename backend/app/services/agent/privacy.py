import re
from copy import deepcopy
from typing import Any

PII_BASIC_FIELDS = frozenset({"name", "phone", "email", "location", "avatar"})
HIDDEN_BASIC_VALUE = "[hidden]"
# Location is intentionally write-only for the Agent: it may set a value that
# the user explicitly supplied, while the existing value remains redacted from
# model context and tool observations.
AGENT_WRITABLE_BASIC_FIELDS = frozenset({"headline", "location", "summary"})

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_CANDIDATE_RE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{8,}\d(?!\w)")


def is_pii_basic_path(path: str) -> bool:
    """Return whether a basic path targets model-hidden personal data."""

    return path.startswith("basic.") and path[6:] in PII_BASIC_FIELDS


def resume_hidden_terms(resume: dict[str, Any]) -> tuple[str, ...]:
    """Return exact identity strings that should not enter model context."""

    basic = resume.get("basic")
    if not isinstance(basic, dict):
        return ()

    name = basic.get("name")
    if isinstance(name, str) and len(name.strip()) >= 2:
        return (name.strip(),)

    return ()


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
        return [
            sanitize_agent_value(item, hidden_terms=hidden_terms) for item in value
        ]

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
                ""
                if field_status.get(field) == "missing"
                else HIDDEN_BASIC_VALUE
            )

    sanitized["basicFieldStatus"] = field_status
    return sanitized


def _phone_replacement(match: re.Match[str]) -> str:
    digits = re.sub(r"\D", "", match.group(0))
    if len(digits) < 10:
        return match.group(0)
    return "[redacted_phone]"


def _replace_hidden_term(text: str, term: str) -> str:
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
