from __future__ import annotations

import re
import unicodedata
from hashlib import blake2s
from typing import Any

from app.schemas.agent import AgentChatRequest, AgentResumeEditSuggestion

from .attachments import AgentAttachmentError, attachment_text

_HISTORICAL_PROMPT_PREFIX = "prompt:history:"
_BASIC_FIELDS = frozenset(
    {"avatar", "email", "headline", "location", "name", "phone", "summary"},
)
_BASIC_IDENTITY_FIELDS = frozenset(
    {"email", "location", "name", "phone"},
)
_ITEM_IDENTITY_FIELDS = frozenset(
    {
        "company",
        "date",
        "degree",
        "gpa",
        "issuer",
        "location",
        "major",
        "name",
        "period",
        "position",
        "role",
        "school",
    },
)
_IGNORED_TEXT_KEYS = frozenset(
    {
        "avatar",
        "email",
        "id",
        "itemId",
        "kind",
        "phone",
        "sectionId",
        "title",
        "url",
    },
)
_NUMBER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.])\d+(?:[.,]\d+)?"
    r"(?:\s*(?:%|％|倍|x|ms|s|秒|分钟|小时|万|亿|k|m))?"
    r"(?![A-Za-z0-9_]|[.,]\d)",
    flags=re.IGNORECASE,
)
_CHINESE_NUMBER_PATTERN = re.compile(
    r"百分之[零〇一二三四五六七八九十百千万亿两]+|"
    r"[零〇一二三四五六七八九十百千万亿两]+"
    r"(?:倍|万|亿|毫秒|秒|分钟|小时|人|名|位)",
)
_LATIN_CJK_BOUNDARY_SPACE_PATTERN = re.compile(
    r"(?<=[A-Za-z0-9]) (?=[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF])|"
    r"(?<=[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]) (?=[A-Za-z0-9])",
)
_ClaimKey = tuple[str, str, str]


def historical_prompt_evidence_ref(message_id: str) -> str:
    """Return the stable evidence reference for one persisted user message."""

    digest = blake2s(message_id.encode("utf-8"), digest_size=16).hexdigest()
    return f"{_HISTORICAL_PROMPT_PREFIX}{digest}"


def ground_edit_evidence(
    before_resume: dict[str, Any],
    request: AgentChatRequest,
    edits: list[AgentResumeEditSuggestion],
    *,
    materials: dict[str, str] | None = None,
) -> tuple[list[AgentResumeEditSuggestion], list[dict[str, Any]]]:
    """Attach provenance and reject only unsupported objective material claims."""

    material_texts = materials or {}
    allowed_refs = _allowed_evidence_refs(before_resume, request, material_texts)
    grounded_edits: list[AgentResumeEditSuggestion] = []
    issues: list[dict[str, Any]] = []

    for operation_index, edit in enumerate(edits, start=1):
        provided_refs = _unique_strings(edit.evidence_refs)
        invalid_refs = [ref for ref in provided_refs if ref not in allowed_refs]
        if invalid_refs:
            issues.append(
                _issue(
                    "invalid_edit_evidence",
                    edit,
                    operation_index,
                    invalidEvidenceRefs=invalid_refs,
                ),
            )

        evidence_refs = provided_refs or _inferred_evidence_refs(
            edit.operation,
            allowed_refs,
            request,
            material_texts,
        )
        if not evidence_refs:
            issues.append(_issue("missing_edit_evidence", edit, operation_index))

        local_refs = _target_local_evidence_refs(
            edit.operation,
            evidence_refs,
            merge_source_refs=_verified_merge_source_refs(
                edit,
                edits,
                evidence_refs,
            ),
            split_source_ref=_verified_split_source_ref(
                edit,
                edits,
                evidence_refs,
            ),
        )
        unsupported = _unsupported_material_claims(
            before_resume,
            request,
            edit.operation,
            local_refs,
            material_texts,
        )
        if unsupported:
            issues.append(
                _issue(
                    "unsupported_edit_claim",
                    edit,
                    operation_index,
                    claims=unsupported,
                ),
            )

        grounded_edits.append(
            edit.model_copy(update={"evidence_refs": evidence_refs}),
        )

    return grounded_edits, issues


def _issue(
    code: str,
    edit: AgentResumeEditSuggestion,
    operation_index: int,
    **details: object,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": "error",
        "target": edit.target,
        "scope": "evidence",
        "operationIndex": operation_index,
        **details,
    }


def _unsupported_material_claims(
    resume: dict[str, Any],
    request: AgentChatRequest,
    operation: dict[str, Any] | None,
    evidence_refs: list[str],
    materials: dict[str, str],
) -> list[str]:
    if _restoration_content_mismatch(resume, request.resume, operation):
        return ["restoration_content_mismatch"]

    before_value, candidate_value = _operation_material_values(resume, operation)
    before_claims = _material_claims(before_value)
    candidate_claims = _material_claims(candidate_value)
    evidence_texts = [
        _evidence_text(resume, request, reference, materials)
        for reference in evidence_refs
    ]
    return sorted(
        display
        for key, display in candidate_claims.items()
        if key not in before_claims
        and not any(_evidence_supports_claim(text, key) for text in evidence_texts)
    )


def _operation_material_values(
    resume: dict[str, Any],
    operation: dict[str, Any] | None,
) -> tuple[object, object]:
    if not isinstance(operation, dict):
        return {}, {}

    operation_type = _string(operation.get("type"))
    if operation_type == "replace_field":
        path = _string(operation.get("path"))
        if not path.startswith("basic."):
            return {}, {}
        field = path.removeprefix("basic.")
        basic = resume.get("basic")
        before = basic.get(field) if isinstance(basic, dict) else None
        return {field: before}, {field: operation.get("value")}

    section = _find_section(resume, _string(operation.get("sectionId")))
    if operation_type == "update_item":
        item = _find_item(section, _string(operation.get("itemId"))) or {}
        patch = operation.get("patch")
        if not isinstance(patch, dict):
            return {}, {}
        return {key: item.get(key) for key in patch}, patch
    if operation_type == "insert_item":
        return {}, operation.get("item")
    if operation_type == "insert_section":
        return {}, operation.get("section")
    return {}, {}


def _material_claims(value: object) -> dict[_ClaimKey, str]:
    text = _flatten_text(value)
    claims: dict[_ClaimKey, str] = {}
    for normalized, display in _number_claims(text).items():
        claims[("number", "", normalized)] = display
    for normalized, display in _tech_stack_claims(value).items():
        claims[("technology", "", normalized)] = display
    claims.update(_identity_claims(value))
    return claims


def _identity_claims(value: object) -> dict[_ClaimKey, str]:
    claims: dict[_ClaimKey, str] = {}
    if isinstance(value, list):
        for item in value:
            claims.update(_identity_claims(item))
        return claims
    if not isinstance(value, dict):
        return claims

    for field, field_value in value.items():
        if field in _BASIC_IDENTITY_FIELDS | _ITEM_IDENTITY_FIELDS:
            display = _string(field_value)
            normalized = _normalize(display)
            if normalized:
                claims[("identity", field, normalized)] = (
                    f"identity:{field}:{display[:80]}"
                )
        if isinstance(field_value, (dict, list)):
            claims.update(_identity_claims(field_value))
    return claims


def _number_claims(text: str) -> dict[str, str]:
    normalized_text = unicodedata.normalize("NFKC", text)
    values = {
        _number_claim_key(match.group(0)): re.sub(r"\s+", "", match.group(0))
        for match in _NUMBER_PATTERN.finditer(normalized_text)
    }
    values.update(
        {
            _normalize(match.group(0)): match.group(0)
            for match in _CHINESE_NUMBER_PATTERN.finditer(normalized_text)
        },
    )
    return values


def _number_claim_key(value: str) -> str:
    return re.sub(r"\s+", "", _normalize(value))


def _tech_stack_claims(value: object) -> dict[str, str]:
    """Extract only technologies placed in the structured techStack field."""

    claims: dict[str, str] = {}
    if isinstance(value, list):
        for item in value:
            claims.update(_tech_stack_claims(item))
        return claims
    if not isinstance(value, dict):
        return claims

    stack = value.get("techStack")
    if isinstance(stack, list):
        for raw_value in stack:
            if not isinstance(raw_value, str):
                continue
            for segment in re.split(r"[,，、;；|·]+", raw_value):
                display = segment.strip()
                if not display:
                    continue
                claims[_normalize(display)] = display
    for child in value.values():
        if isinstance(child, (dict, list)):
            claims.update(_tech_stack_claims(child))
    return claims


def _evidence_supports_claim(text: str, claim: _ClaimKey) -> bool:
    kind, _field, normalized = claim
    if kind == "number":
        return normalized in _number_claims(text)
    return _contains_value(text, normalized)


def _contains_value(text: str, normalized_value: str) -> bool:
    normalized_text = _normalize(text)
    if not normalized_value:
        return False
    if re.fullmatch(r"[a-z0-9.+#/-]+(?: [a-z0-9.+#/-]+)*", normalized_value):
        pattern = re.escape(normalized_value).replace(r"\ ", r"\s+")
        return (
            re.search(
                rf"(?<![a-z0-9]){pattern}(?![a-z0-9])",
                normalized_text,
            )
            is not None
        )
    return normalized_value in normalized_text


def _target_local_evidence_refs(
    operation: dict[str, Any] | None,
    evidence_refs: list[str],
    *,
    merge_source_refs: set[str],
    split_source_ref: str,
) -> list[str]:
    if not isinstance(operation, dict):
        return list(evidence_refs)
    operation_type = operation.get("type")
    if operation_type == "insert_item":
        item = operation.get("item")
        inserted_id = _string(item.get("id")) if isinstance(item, dict) else ""
        restored_item_ref = (
            f"resume:item:{_string(operation.get('sectionId'))}:{inserted_id}"
        )
        return [
            ref
            for ref in evidence_refs
            if ref in {split_source_ref, restored_item_ref}
            or ref.startswith("prompt:")
            or ref.startswith("attachment:")
        ]
    if operation_type != "update_item":
        return list(evidence_refs)

    target_ref = (
        f"resume:item:{_string(operation.get('sectionId'))}:"
        f"{_string(operation.get('itemId'))}"
    )
    return [
        ref
        for ref in evidence_refs
        if ref == target_ref
        or ref in merge_source_refs
        or ref.startswith("prompt:")
        or ref.startswith("attachment:")
    ]


def _verified_merge_source_refs(
    edit: AgentResumeEditSuggestion,
    edits: list[AgentResumeEditSuggestion],
    evidence_refs: list[str],
) -> set[str]:
    operation = edit.operation
    if not isinstance(operation, dict) or operation.get("type") != "update_item":
        return set()
    section_id = _string(operation.get("sectionId"))
    item_id = _string(operation.get("itemId"))
    target_ref = f"resume:item:{section_id}:{item_id}"
    if not section_id or not item_id or target_ref not in evidence_refs:
        return set()

    source_refs = {
        parts[3]: ref
        for ref in evidence_refs
        for parts in [ref.split(":", maxsplit=3)]
        if len(parts) == 4
        and parts[:3] == ["resume", "item", section_id]
        and parts[3] != item_id
    }
    deleted_ids = {
        _string(candidate_operation.get("itemId"))
        for candidate in edits
        if candidate is not edit
        and isinstance((candidate_operation := candidate.operation), dict)
        and candidate_operation.get("type") == "delete_item"
        and _string(candidate_operation.get("sectionId")) == section_id
    }
    return set(source_refs.values()) if set(source_refs) == deleted_ids else set()


def _verified_split_source_ref(
    edit: AgentResumeEditSuggestion,
    edits: list[AgentResumeEditSuggestion],
    evidence_refs: list[str],
) -> str:
    operation = edit.operation
    if not isinstance(operation, dict) or operation.get("type") != "insert_item":
        return ""
    section_id = _string(operation.get("sectionId"))
    source_refs: set[str] = set()
    for candidate in edits:
        candidate_operation = candidate.operation
        if (
            candidate is edit
            or not isinstance(candidate_operation, dict)
            or candidate_operation.get("type") != "update_item"
            or _string(candidate_operation.get("sectionId")) != section_id
        ):
            continue
        source_ref = (
            f"resume:item:{section_id}:{_string(candidate_operation.get('itemId'))}"
        )
        if source_ref in candidate.evidence_refs and source_ref in evidence_refs:
            source_refs.add(source_ref)
    return next(iter(source_refs)) if len(source_refs) == 1 else ""


def _restoration_content_mismatch(
    active_resume: dict[str, Any],
    formal_resume: dict[str, Any],
    operation: dict[str, Any] | None,
) -> bool:
    if not isinstance(operation, dict):
        return False
    operation_type = _string(operation.get("type"))
    if operation_type == "insert_item":
        section_id = _string(operation.get("sectionId"))
        item = operation.get("item")
        item_id = _string(item.get("id")) if isinstance(item, dict) else ""
        formal_item = _find_item(_find_section(formal_resume, section_id), item_id)
        return bool(
            formal_item is not None
            and not _resume_has_item(active_resume, item_id)
            and item != formal_item
        )
    if operation_type == "insert_section":
        section = operation.get("section")
        section_id = _string(section.get("id")) if isinstance(section, dict) else ""
        formal_section = _find_section(formal_resume, section_id)
        return bool(
            formal_section is not None
            and _find_section(active_resume, section_id) is None
            and section != formal_section
        )
    return False


def _resume_has_item(resume: dict[str, Any], item_id: str) -> bool:
    sections = resume.get("sections")
    return isinstance(sections, list) and any(
        _find_item(section, item_id) is not None
        for section in sections
        if isinstance(section, dict)
    )


def _allowed_evidence_refs(
    resume: dict[str, Any],
    request: AgentChatRequest,
    materials: dict[str, str],
) -> set[str]:
    refs = {f"resume:basic:{field}" for field in _BASIC_FIELDS}
    refs.update(_prompt_evidence_by_ref(request))
    for evidence_resume in (request.resume, resume):
        sections = evidence_resume.get("sections")
        if not isinstance(sections, list):
            continue
        for section in sections:
            if not isinstance(section, dict):
                continue
            section_id = _string(section.get("id"))
            if not section_id:
                continue
            refs.add(f"resume:section:{section_id}")
            items = section.get("items")
            if isinstance(items, list):
                refs.update(
                    f"resume:item:{section_id}:{item_id}"
                    for item in items
                    if isinstance(item, dict) and (item_id := _string(item.get("id")))
                )
    refs.update(
        f"attachment:{attachment_id}"
        for file in _request_files(request)
        if (attachment_id := _string(file.get("id")))
    )
    refs.update(materials)
    return refs


def _prompt_evidence_by_ref(request: AgentChatRequest) -> dict[str, str]:
    evidence = {"prompt:current": request.message.text}
    duplicate_refs: set[str] = set()
    for message in request.messages:
        if message.role != "user" or not (message_id := _string(message.id)):
            continue
        reference = historical_prompt_evidence_ref(message_id)
        if reference in evidence:
            duplicate_refs.add(reference)
        else:
            evidence[reference] = message.text
    for reference in duplicate_refs:
        evidence.pop(reference, None)
    return evidence


def _evidence_text(
    resume: dict[str, Any],
    request: AgentChatRequest,
    reference: str,
    materials: dict[str, str],
) -> str:
    if reference in materials:
        return materials[reference]
    if (prompt := _prompt_evidence_by_ref(request).get(reference)) is not None:
        return prompt
    if reference.startswith("resume:basic:"):
        field = reference.removeprefix("resume:basic:")
        basic = resume.get("basic")
        return _flatten_text(basic.get(field) if isinstance(basic, dict) else "")
    if reference.startswith("resume:section:"):
        section_id = reference.removeprefix("resume:section:")
        section = _find_section(resume, section_id) or _find_section(
            request.resume,
            section_id,
        )
        return _flatten_text(section)
    if reference.startswith("resume:item:"):
        parts = reference.split(":", maxsplit=3)
        if len(parts) != 4:
            return ""
        item = _find_item(_find_section(resume, parts[2]), parts[3]) or _find_item(
            _find_section(request.resume, parts[2]),
            parts[3],
        )
        return _flatten_text(item)
    if reference.startswith("attachment:"):
        attachment_id = reference.removeprefix("attachment:")
        file = next(
            (
                candidate
                for candidate in _request_files(request)
                if _string(candidate.get("id")) == attachment_id
            ),
            None,
        )
        if file is None or not (session_id := _string(request.resume_id)):
            return ""
        try:
            return str(attachment_text(session_id, file))
        except AgentAttachmentError:
            return ""
    return ""


def _inferred_evidence_refs(
    operation: dict[str, Any] | None,
    allowed_refs: set[str],
    request: AgentChatRequest,
    materials: dict[str, str],
) -> list[str]:
    if not isinstance(operation, dict):
        return []
    operation_type = _string(operation.get("type"))
    section_id = _string(operation.get("sectionId"))
    item_id = _string(operation.get("itemId"))
    refs: list[str] = []

    if operation_type == "replace_field":
        path = _string(operation.get("path"))
        if path.startswith("basic."):
            refs.append(f"resume:basic:{path.removeprefix('basic.')}")
    elif operation_type in {"update_item", "delete_item"}:
        refs.append(f"resume:item:{section_id}:{item_id}")
    elif operation_type == "insert_item":
        item = operation.get("item")
        inserted_id = _string(item.get("id")) if isinstance(item, dict) else ""
        item_ref = f"resume:item:{section_id}:{inserted_id}"
        refs.append(
            item_ref if item_ref in allowed_refs else f"resume:section:{section_id}",
        )
    elif operation_type in {"update_section", "delete_section", "reorder_items"}:
        refs.append(f"resume:section:{section_id}")
    elif operation_type == "insert_section":
        section = operation.get("section")
        inserted_id = _string(section.get("id")) if isinstance(section, dict) else ""
        refs.append(f"resume:section:{inserted_id}")
    elif operation_type == "reorder_sections":
        refs.extend(
            f"resume:section:{value}" for value in _strings(operation.get("sectionIds"))
        )

    if operation_type in {
        "insert_item",
        "insert_section",
        "replace_field",
        "update_item",
        "update_section",
    }:
        refs.extend(_prompt_evidence_by_ref(request))
        refs.extend(
            f"attachment:{attachment_id}"
            for file in _request_files(request)
            if (attachment_id := _string(file.get("id")))
        )
        refs.extend(materials)
    return [ref for ref in _unique_strings(refs) if ref in allowed_refs]


def _find_section(resume: dict[str, Any], section_id: str) -> dict[str, Any] | None:
    sections = resume.get("sections")
    if not isinstance(sections, list):
        return None
    return next(
        (
            section
            for section in sections
            if isinstance(section, dict) and _string(section.get("id")) == section_id
        ),
        None,
    )


def _find_item(
    section: dict[str, Any] | None,
    item_id: str,
) -> dict[str, Any] | None:
    items = section.get("items") if isinstance(section, dict) else None
    if not isinstance(items, list):
        return None
    return next(
        (
            item
            for item in items
            if isinstance(item, dict) and _string(item.get("id")) == item_id
        ),
        None,
    )


def _flatten_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(_flatten_text(item) for item in value)
    if isinstance(value, dict):
        return "\n".join(
            _flatten_text(item)
            for key, item in value.items()
            if key not in _IGNORED_TEXT_KEYS
        )
    return ""


def _normalize(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    return _LATIN_CJK_BOUNDARY_SPACE_PATTERN.sub("", normalized)


def _request_files(request: AgentChatRequest) -> list[dict[str, Any]]:
    return [file for file in request.message.files if isinstance(file, dict)]


def _strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if isinstance(item, str) and (text := item.strip())]


def _unique_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = ["ground_edit_evidence", "historical_prompt_evidence_ref"]
