import re
import unicodedata
from copy import deepcopy
from typing import Any
from uuid import uuid4

from app.schemas.agent import AgentChatRequest, AgentResumeEditSuggestion
from app.services.resume_document_contract import (
    ITEM_LIST_FIELDS_BY_KIND,
    ITEM_STRING_FIELDS_BY_KIND,
    ResumeDocumentContractError,
    is_resume_item_for_kind,
    validate_resume_document,
)

from ..localization import agent_text
from ..models import EditPlanStep
from ..operation_contract import resume_edit_operation_error
from ..parsing_patterns import compiled_agent_pattern
from ..privacy import AGENT_WRITABLE_BASIC_FIELDS, is_pii_basic_path
from ..prompts import (
    DEFAULT_REACT_MAX_ITERATIONS,
    MAX_REACT_MAX_ITERATIONS,
    MIN_REACT_MAX_ITERATIONS,
)
from ..section_registry import (
    SECTION_KIND_ALIAS_MATCHES,
    SECTION_KIND_ALIASES,
    SECTION_KIND_ENUM,
    normalize_section_alias,
)


def _string_list(value: object) -> list[str]:
    """Return only string entries from a possible list."""

    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str)]


BASIC_EDIT_FIELDS = {
    "name",
    "headline",
    "phone",
    "email",
    "location",
    "avatar",
    "summary",
}
FIELD_ONLY_LABEL_RE = compiled_agent_pattern("editing.field_only_label")
CONTENT_LABEL_RE = compiled_agent_pattern("editing.content_label")
MIXED_FIELD_LABEL_RE = compiled_agent_pattern("editing.mixed_field_label")
REQUEST_PREFIX_RE = compiled_agent_pattern("editing.request_prefix")


def _resume_sections(resume: dict[str, Any]) -> list[dict[str, Any]]:
    """Return mutable section dicts from resume payload."""

    sections = resume.get("sections")
    if not isinstance(sections, list):
        return []

    return [section for section in sections if isinstance(section, dict)]


def _find_resume_section(
    resume: dict[str, Any],
    section_id: str,
) -> dict[str, Any] | None:
    """Return a section by id from resume payload."""

    return next(
        (
            section
            for section in _resume_sections(resume)
            if section.get("id") == section_id
        ),
        None,
    )


def _find_resume_item(
    section: dict[str, Any],
    item_id: str,
) -> dict[str, Any] | None:
    """Return an item by id from one section payload."""

    items = section.get("items")
    if not isinstance(items, list):
        return None

    return next(
        (
            item
            for item in items
            if isinstance(item, dict) and item.get("id") == item_id
        ),
        None,
    )


def _resume_item_ids(resume: dict[str, Any]) -> set[str]:
    """Return every item ID; V2 item identity is document-wide."""

    return {
        item_id
        for section in _resume_sections(resume)
        for item in section.get("items", [])
        if isinstance(item, dict)
        and isinstance((item_id := item.get("id")), str)
    }


def _model_string(value: object) -> str:
    """Return a stripped model-provided string."""

    return value.strip() if isinstance(value, str) else ""


def _compact_whitespace(value: str) -> str:
    """Collapse text spacing for duplicate checks."""

    return re.sub(r"\s+", " ", value).strip()


def _duplicate_key(value: str) -> str:
    """Return a punctuation-light key for comparing generated fields."""

    return re.sub(r"[\s:：,，.。;；\-–—/、·]+", "", value).lower()


def _section_kind_from_text(value: object) -> str:
    """Map a model-provided section type/name to a standard section kind."""

    raw_text = _model_string(value)
    text = normalize_section_alias(raw_text)
    if not text:
        return ""

    if text in SECTION_KIND_ENUM:
        return text

    direct = SECTION_KIND_ALIASES.get(text)
    if direct:
        return direct

    for alias, kind in SECTION_KIND_ALIAS_MATCHES:
        if _section_alias_matches_text(raw_text, alias):
            return kind

    return ""


def _section_alias_matches_text(value: str, alias: str) -> bool:
    """Match prose aliases without treating short English aliases as substrings."""

    normalized_alias = unicodedata.normalize("NFKC", alias).lower().strip()
    if re.fullmatch(r"[a-z0-9]+(?:\s+[a-z0-9]+)*", normalized_alias):
        words = normalized_alias.split()
        pattern = (
            r"(?<![a-z0-9])"
            + r"[\W_]+".join(re.escape(word) for word in words)
            + r"(?![a-z0-9])"
        )
        normalized_value = unicodedata.normalize("NFKC", value).lower()
        return re.search(pattern, normalized_value) is not None

    return normalize_section_alias(alias) in normalize_section_alias(value)


def _normalized_section_kind(*values: object) -> str:
    """Return a canonical section kind, or an empty string when unknown."""

    for value in values:
        kind = _section_kind_from_text(value)
        if kind:
            return kind

    return ""


def _clean_generated_text(value: object) -> str:
    """Remove user-command prefixes and normalize model-provided prose."""

    text = _compact_whitespace(_model_string(value))
    return REQUEST_PREFIX_RE.sub("", text, count=1).strip()


def _clean_highlight_text(value: object) -> str:
    """Normalize one generated bullet/highlight."""

    text = _clean_generated_text(value).strip(" -•\t")
    text = CONTENT_LABEL_RE.sub("", text, count=1).strip()
    if FIELD_ONLY_LABEL_RE.search(text):
        return ""
    return text


def _contains_mixed_field_labels(value: str) -> bool:
    """Return whether text still looks like an unsplit resume paragraph."""

    return len(MIXED_FIELD_LABEL_RE.findall(value)) >= 2


def _field_values_for_dedupe(item: dict[str, Any], kind: str) -> list[str]:
    """Return fields that should not be repeated in prose or bullets."""

    excluded = {"description", "content", "url"}
    return [
        _model_string(item.get(field))
        for field in ITEM_STRING_FIELDS_BY_KIND.get(kind, ())
        if field not in excluded
    ]


def _has_repeated_field_values(value: str, field_values: list[str]) -> bool:
    """Return whether text repeats multiple structured fields."""

    text_key = _duplicate_key(value)
    field_keys = {
        field_key
        for field_value in field_values
        if len(field_key := _duplicate_key(field_value)) >= 3
    }
    return sum(field_key in text_key for field_key in field_keys) >= 2


def _clean_resume_item_fields(item: dict[str, Any], kind: str) -> dict[str, Any]:
    """Keep generated semantic item fields in their kind-specific lanes."""

    cleaned = {**item}
    for key in ITEM_STRING_FIELDS_BY_KIND.get(kind, ()):
        cleaned[key] = _clean_generated_text(cleaned.get(key))

    for key in ITEM_LIST_FIELDS_BY_KIND.get(kind, ()):
        if key == "highlights":
            continue
        cleaned[key] = [
            text
            for value in _string_list(cleaned.get(key))
            if (text := _clean_generated_text(value))
        ]

    field_values = _field_values_for_dedupe(cleaned, kind)
    description = _model_string(cleaned.get("description"))
    if description and (
        _contains_mixed_field_labels(description)
        or _has_repeated_field_values(description, field_values)
    ):
        cleaned["description"] = ""

    highlights = cleaned.get("highlights")
    next_highlights: list[str] = []
    seen: set[str] = set()
    if isinstance(highlights, list):
        for highlight in highlights:
            text = _clean_highlight_text(highlight)
            if not text:
                continue
            if _contains_mixed_field_labels(text):
                continue
            if _has_repeated_field_values(text, field_values):
                continue
            key = _duplicate_key(text)
            if key and key not in seen:
                next_highlights.append(text)
                seen.add(key)

    if "highlights" in ITEM_LIST_FIELDS_BY_KIND.get(kind, ()):
        cleaned["highlights"] = next_highlights
    return cleaned


def _model_int(value: object) -> int | None:
    """Return a bounded integer from model-provided JSON."""

    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)

    return None


def _normalized_item(value: object, kind: str) -> dict[str, Any] | None:
    """Return one exact semantic item for the target section kind."""

    if not isinstance(value, dict) or kind not in ITEM_STRING_FIELDS_BY_KIND:
        return None
    allowed_fields = {
        "id",
        *ITEM_STRING_FIELDS_BY_KIND[kind],
        *ITEM_LIST_FIELDS_BY_KIND[kind],
    }
    if not set(value).issubset(allowed_fields):
        return None
    if "id" in value and not isinstance(value["id"], str):
        return None
    if any(
        field in value and not isinstance(value[field], str)
        for field in ITEM_STRING_FIELDS_BY_KIND[kind]
    ):
        return None
    if any(
        field in value
        and (
            not isinstance(value[field], list)
            or not all(isinstance(item, str) for item in value[field])
        )
        for field in ITEM_LIST_FIELDS_BY_KIND[kind]
    ):
        return None

    item: dict[str, Any] = {
        "id": _model_string(value.get("id")) or f"item-agent-{uuid4().hex[:8]}"
    }
    item.update(
        {
            field: _model_string(value.get(field))
            for field in ITEM_STRING_FIELDS_BY_KIND[kind]
        }
    )
    item.update(
        {
            field: _string_list(value.get(field))
            for field in ITEM_LIST_FIELDS_BY_KIND[kind]
        }
    )
    return _clean_resume_item_fields(item, kind)


def _normalized_section(value: object) -> dict[str, Any] | None:
    """Return a safe ResumeSection payload from model JSON."""

    if not isinstance(value, dict):
        return None
    if not set(value).issubset(
        {"id", "section_type", "sectionType", "kind", "title", "items"}
    ):
        return None
    if "id" in value and not isinstance(value["id"], str):
        return None
    if "title" in value and not isinstance(value["title"], str):
        return None
    if _section_kind_aliases_conflict(
        value.get("section_type"),
        value.get("sectionType"),
        value.get("kind"),
    ):
        return None

    kind = _normalized_section_kind(
        value.get("section_type"),
        value.get("sectionType"),
        value.get("kind"),
    )
    items = value.get("items")
    if not kind or not isinstance(items, list):
        return None
    normalized_items = [_normalized_item(item, kind) for item in items]
    if any(item is None for item in normalized_items):
        return None
    normalized_items = [item for item in normalized_items if item is not None]
    if kind == "simple_list" and len(normalized_items) != 1:
        return None

    return {
        "id": _model_string(value.get("id")) or f"section-agent-{uuid4().hex[:8]}",
        "kind": kind,
        "title": _model_string(value.get("title")),
        "items": normalized_items,
    }


def _safe_item_patch(
    value: object,
    *,
    kind: str,
    base_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return only fields writable by the target section's item contract."""

    if not isinstance(value, dict) or kind not in ITEM_STRING_FIELDS_BY_KIND:
        return {}
    allowed_fields = {
        *ITEM_STRING_FIELDS_BY_KIND[kind],
        *ITEM_LIST_FIELDS_BY_KIND[kind],
    }
    if not set(value).issubset(allowed_fields):
        return {}

    patch: dict[str, Any] = {}
    for key in ITEM_STRING_FIELDS_BY_KIND[kind]:
        field_value = value.get(key)
        if isinstance(field_value, str):
            patch[key] = field_value

    for key in ITEM_LIST_FIELDS_BY_KIND[kind]:
        field_value = value.get(key)
        if isinstance(field_value, list) and all(
            isinstance(item, str) for item in field_value
        ):
            patch[key] = field_value

    if not patch:
        return {}

    merged = _clean_resume_item_fields({**(base_item or {}), **patch}, kind)
    cleaned_patch: dict[str, Any] = {}
    for key in patch:
        if key not in merged:
            continue
        cleaned_patch[key] = merged[key]

    return cleaned_patch


def _section_kind_aliases_conflict(*values: object) -> bool:
    """Return whether aliases resolve to different known section kinds."""

    resolved = {kind for value in values if (kind := _section_kind_from_text(value))}
    return len(resolved) > 1


def _safe_section_patch(value: object) -> dict[str, Any]:
    """Return the only Agent-writable section field: its display title."""

    if not isinstance(value, dict) or not set(value).issubset({"title"}):
        return {}

    title = value.get("title")
    return {"title": title.strip()} if isinstance(title, str) else {}


def _normalize_edit_operation(
    resume: dict[str, Any],
    operation: object,
) -> dict[str, Any] | None:
    """Validate and normalize a frontend ResumeEditOperation from model JSON."""

    if not isinstance(operation, dict):
        return None

    operation_type = _model_string(operation.get("type"))
    if operation_type == "replace_field":
        path = _model_string(operation.get("path"))
        value = operation.get("value")
        if (
            path.startswith("basic.")
            and path[6:] in AGENT_WRITABLE_BASIC_FIELDS
            and isinstance(value, str)
        ):
            basic = resume.get("basic")
            current = basic.get(path[6:]) if isinstance(basic, dict) else None
            if current != value:
                return {"type": "replace_field", "path": path, "value": value}
        return None

    if operation_type == "insert_section":
        section = _normalized_section(operation.get("section"))
        if not section:
            return None
        existing_ids = {
            str(candidate.get("id"))
            for candidate in _resume_sections(resume)
            if isinstance(candidate.get("id"), str)
        }
        item_ids = [
            str(item.get("id"))
            for item in section.get("items", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        if (
            section["id"] in existing_ids
            or len(item_ids) != len(set(item_ids))
            or bool(set(item_ids) & _resume_item_ids(resume))
        ):
            return None
        normalized: dict[str, Any] = {"type": "insert_section", "section": section}
        index = _model_int(operation.get("index"))
        if index is not None:
            normalized["index"] = index
        return normalized

    if operation_type == "update_section":
        section_id = _model_string(operation.get("sectionId"))
        section = _find_resume_section(resume, section_id)
        patch = _safe_section_patch(operation.get("patch"))
        changed_patch = (
            {key: value for key, value in patch.items() if section.get(key) != value}
            if section
            else {}
        )
        if section_id and changed_patch and section:
            return {
                "type": "update_section",
                "sectionId": section_id,
                "patch": changed_patch,
            }
        return None

    if operation_type == "delete_section":
        section_id = _model_string(operation.get("sectionId"))
        if section_id and _find_resume_section(resume, section_id):
            return {"type": "delete_section", "sectionId": section_id}
        return None

    if operation_type == "reorder_sections":
        section_ids = _string_list(operation.get("sectionIds"))
        current_ids = [
            str(section.get("id"))
            for section in _resume_sections(resume)
            if isinstance(section.get("id"), str)
        ]
        if (
            len(section_ids) == len(current_ids)
            and len(section_ids) == len(set(section_ids))
            and set(section_ids) == set(current_ids)
            and section_ids != current_ids
        ):
            return {"type": "reorder_sections", "sectionIds": section_ids}
        return None

    if operation_type == "insert_item":
        section_id = _model_string(operation.get("sectionId"))
        section = _find_resume_section(resume, section_id)
        kind = _model_string(section.get("kind")) if section else ""
        item = _normalized_item(operation.get("item"), kind)
        if (
            not section_id
            or not item
            or not section
            or kind == "simple_list"
            or item["id"] in _resume_item_ids(resume)
        ):
            return None
        normalized = {"type": "insert_item", "sectionId": section_id, "item": item}
        index = _model_int(operation.get("index"))
        if index is not None:
            normalized["index"] = index
        return normalized

    if operation_type == "update_item":
        section_id = _model_string(operation.get("sectionId"))
        item_id = _model_string(operation.get("itemId"))
        section = _find_resume_section(resume, section_id)
        item = _find_resume_item(section, item_id) if section else None
        kind = _model_string(section.get("kind")) if section else ""
        patch = _safe_item_patch(
            operation.get("patch"),
            kind=kind,
            base_item=item if isinstance(item, dict) else None,
        )
        changed_patch = (
            {key: value for key, value in patch.items() if item.get(key) != value}
            if item
            else {}
        )
        if section and item_id and changed_patch and item:
            return {
                "type": "update_item",
                "sectionId": section_id,
                "itemId": item_id,
                "patch": changed_patch,
            }
        return None

    if operation_type == "delete_item":
        section_id = _model_string(operation.get("sectionId"))
        item_id = _model_string(operation.get("itemId"))
        section = _find_resume_section(resume, section_id)
        if (
            section
            and section.get("kind") != "simple_list"
            and item_id
            and _find_resume_item(section, item_id)
        ):
            return {"type": "delete_item", "sectionId": section_id, "itemId": item_id}
        return None

    if operation_type == "reorder_items":
        section_id = _model_string(operation.get("sectionId"))
        section = _find_resume_section(resume, section_id)
        item_ids = _string_list(operation.get("itemIds"))
        if not section or section.get("kind") == "simple_list" or not item_ids:
            return None
        current_item_ids = [
            str(item.get("id"))
            for item in section.get("items", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        if (
            len(item_ids) == len(current_item_ids)
            and len(item_ids) == len(set(item_ids))
            and set(item_ids) == set(current_item_ids)
            and item_ids != current_item_ids
        ):
            return {
                "type": "reorder_items",
                "sectionId": section_id,
                "itemIds": item_ids,
            }
        return None

    return None


def _operation_target(operation: dict[str, Any]) -> str:
    """Return the frontend target path for an operation."""

    operation_type = operation.get("type")
    if operation_type == "replace_field":
        return str(operation["path"])
    if operation_type == "insert_section":
        section = operation["section"]
        return f"sections.{section['id']}"
    if operation_type in {"update_section", "delete_section"}:
        return f"sections.{operation['sectionId']}"
    if operation_type == "reorder_sections":
        return "sections"
    if operation_type == "insert_item":
        return f"sections.{operation['sectionId']}.items.{operation['item']['id']}"
    if operation_type in {"update_item", "delete_item"}:
        return f"sections.{operation['sectionId']}.items.{operation['itemId']}"
    if operation_type == "reorder_items":
        return f"sections.{operation['sectionId']}.items"
    return ""


def _operation_replacement(operation: dict[str, Any]) -> str | None:
    """Return a compact replacement preview for an operation."""

    operation_type = operation.get("type")
    if operation_type == "replace_field":
        return str(operation.get("value", ""))
    if operation_type == "update_item":
        patch = operation.get("patch", {})
        if isinstance(patch, dict):
            for field in (
                "content",
                "name",
                "school",
                "company",
                "position",
                "role",
                "description",
            ):
                if value := _model_string(patch.get(field)):
                    return value
            for field in ("techStack", "highlights"):
                values = _string_list(patch.get(field))
                if values:
                    return " / ".join(values[:2])
    if operation_type == "insert_section":
        section = operation.get("section", {})
        if isinstance(section, dict):
            title = _model_string(section.get("title"))
            if title:
                return title
            items = section.get("items")
            if isinstance(items, list):
                for item in items:
                    if item_preview := _resume_item_preview(item):
                        return item_preview
    if operation_type == "insert_item":
        item = operation.get("item", {})
        if isinstance(item, dict):
            return _resume_item_preview(item)
    return None


def _invalid_operation_reason(resume: dict[str, Any], operation: object) -> str:
    """Return a compact reason for a rejected model operation."""

    if not isinstance(operation, dict):
        return "Missing operation object."

    operation_type = _model_string(operation.get("type"))
    if not operation_type:
        return "Missing operation type."

    supported_types = {
        "replace_field",
        "update_item",
        "insert_item",
        "update_section",
        "insert_section",
        "delete_item",
        "delete_section",
        "reorder_sections",
        "reorder_items",
    }
    if operation_type not in supported_types:
        return f"Unsupported operation type: {operation_type}."

    if operation_type == "replace_field":
        path = _model_string(operation.get("path"))
        field = path[6:] if path.startswith("basic.") else ""
        if is_pii_basic_path(path) and field not in AGENT_WRITABLE_BASIC_FIELDS:
            return "replace_field cannot edit hidden personal fields."
        if not path.startswith("basic.") or field not in BASIC_EDIT_FIELDS:
            return "replace_field requires path basic.<writableField>."
        if field not in AGENT_WRITABLE_BASIC_FIELDS:
            return "replace_field targets a read-only basic field."
        if not isinstance(operation.get("value"), str):
            return "replace_field requires a string value."
        basic = resume.get("basic")
        if isinstance(basic, dict) and basic.get(field) == operation.get("value"):
            return "replace_field must change the current value."

    if operation_type == "insert_section":
        section = _normalized_section(operation.get("section"))
        if not section:
            return "insert_section requires a valid section object."
        if _find_resume_section(resume, section["id"]):
            return "insert_section requires a unique section id."
        item_ids = [
            str(item.get("id"))
            for item in section.get("items", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        if len(item_ids) != len(set(item_ids)):
            return "insert_section requires unique item ids."
        if set(item_ids) & _resume_item_ids(resume):
            return "insert_section item ids must be unique in the resume."

    if operation_type == "update_section":
        section_id = _model_string(operation.get("sectionId"))
        if not section_id or not _find_resume_section(resume, section_id):
            return "update_section requires an existing sectionId."
        if not _safe_section_patch(operation.get("patch")):
            return "update_section requires at least one writable section patch field."
        section = _find_resume_section(resume, section_id)
        patch = _safe_section_patch(operation.get("patch"))
        if section and all(section.get(key) == value for key, value in patch.items()):
            return "update_section must change at least one field."

    if operation_type == "delete_section":
        section_id = _model_string(operation.get("sectionId"))
        if not section_id or not _find_resume_section(resume, section_id):
            return "delete_section requires an existing sectionId."

    if operation_type == "reorder_sections":
        section_ids = _string_list(operation.get("sectionIds"))
        current_ids = [
            str(section.get("id"))
            for section in _resume_sections(resume)
            if isinstance(section.get("id"), str)
        ]
        if len(section_ids) != len(set(section_ids)):
            return "reorder_sections cannot contain duplicate sectionIds."
        if len(section_ids) != len(current_ids) or set(section_ids) != set(current_ids):
            return "reorder_sections requires every existing sectionId exactly once."
        if section_ids == current_ids:
            return "reorder_sections must change the current order."

    if operation_type == "insert_item":
        section_id = _model_string(operation.get("sectionId"))
        section = _find_resume_section(resume, section_id)
        if not section_id or not section:
            return "insert_item requires an existing sectionId."
        kind = _model_string(section.get("kind"))
        if kind == "simple_list":
            return "simple_list has one rich-text item; update its content instead."
        if not _normalized_item(operation.get("item"), kind):
            return "insert_item requires a valid item object."
        item = _normalized_item(operation.get("item"), kind)
        if item and item["id"] in _resume_item_ids(resume):
            return "insert_item requires a resume-wide unique item id."

    if operation_type in {"update_item", "delete_item", "reorder_items"}:
        section_id = _model_string(operation.get("sectionId"))
        section = _find_resume_section(resume, section_id)
        if not section:
            return f"{operation_type} requires an existing sectionId."

        if (
            section.get("kind") == "simple_list"
            and operation_type in {"delete_item", "reorder_items"}
        ):
            return "simple_list has one rich-text item; update its content instead."

        if operation_type == "reorder_items":
            item_ids = _string_list(operation.get("itemIds"))
            current_item_ids = [
                str(item.get("id"))
                for item in section.get("items", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ]
            if len(item_ids) != len(set(item_ids)):
                return "reorder_items cannot contain duplicate itemIds."
            if len(item_ids) != len(current_item_ids) or set(item_ids) != set(
                current_item_ids
            ):
                return "reorder_items requires every existing itemId exactly once."
            if item_ids == current_item_ids:
                return "reorder_items must change the current order."
            return "Operation was rejected by validation."

        item_id = _model_string(operation.get("itemId"))
        item = _find_resume_item(section, item_id)
        if not item_id or not item:
            return f"{operation_type} requires an existing itemId."
        if operation_type == "update_item" and not _safe_item_patch(
            operation.get("patch"),
            kind=_model_string(section.get("kind")),
            base_item=item if isinstance(item, dict) else None,
        ):
            return "update_item requires at least one writable item patch field."
        if operation_type == "update_item":
            patch = _safe_item_patch(
                operation.get("patch"),
                kind=_model_string(section.get("kind")),
                base_item=item,
            )
            if all(item.get(key) == value for key, value in patch.items()):
                return "update_item must change at least one field."

    return "Operation was rejected by validation."


def _model_edit_suggestions_with_diagnostics(
    resume: dict[str, Any],
    value: object,
    *,
    locale: str,
    allow_missing_operations: bool = False,
) -> tuple[list[AgentResumeEditSuggestion], list[dict[str, Any]]]:
    """Convert model edits and return rejected entries for tool observations.

    Plan steps may omit their optional executable operation. Callers can allow
    those metadata-only steps while still rejecting every operation that was
    explicitly supplied but failed validation.
    """

    if not isinstance(value, list):
        return [], []

    edits: list[AgentResumeEditSuggestion] = []
    rejected: list[dict[str, Any]] = []
    # Validate against a work copy so later operations can target entities
    # inserted earlier in the same batch without mutating the real draft.
    working_resume = deepcopy(resume)
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            rejected.append(
                {
                    "index": index,
                    "title": agent_text(locale, "edit.default.title", index=index),
                    "reason": agent_text(locale, "error.edit_entry_must_object"),
                },
            )
            continue

        if allow_missing_operations and "operation" not in item:
            continue

        operation = _normalize_edit_operation(
            working_resume,
            item.get("operation"),
        )
        if not operation:
            rejected.append(
                {
                    "index": index,
                    "title": _model_string(item.get("title"))
                    or agent_text(locale, "edit.default.title", index=index),
                    "reason": _invalid_operation_reason(
                        working_resume,
                        item.get("operation"),
                    ),
                },
            )
            continue

        contract_error = resume_edit_operation_error(operation)
        if contract_error is not None:
            rejected.append(
                {
                    "index": index,
                    "title": _model_string(item.get("title"))
                    or agent_text(locale, "edit.default.title", index=index),
                    "reason": (
                        "Normalized operation violates the resume edit "
                        f"protocol: {contract_error}"
                    ),
                },
            )
            continue

        candidate_resume = deepcopy(working_resume)
        _apply_edit_operation(candidate_resume, operation)
        try:
            validate_resume_document(candidate_resume)
        except ResumeDocumentContractError as exc:
            rejected.append(
                {
                    "index": index,
                    "title": _model_string(item.get("title"))
                    or agent_text(locale, "edit.default.title", index=index),
                    "reason": f"{exc.code} at {exc.path}.",
                },
            )
            continue

        title = _model_string(item.get("title")) or agent_text(
            locale,
            "edit.default.title",
            index=index,
        )
        target = _model_string(item.get("target")) or _operation_target(operation)
        reason = _model_string(item.get("reason")) or agent_text(
            locale,
            "edit.default.reason",
        )
        replacement = _model_string(item.get("replacement")) or _operation_replacement(
            operation,
        )
        evidence_refs = list(
            dict.fromkeys(
                reference.strip()
                for reference in _string_list(item.get("evidenceRefs"))
                if reference.strip()
            ),
        )

        edits.append(
            AgentResumeEditSuggestion(
                id=f"edit-{uuid4().hex[:8]}",
                title=title,
                target=target,
                reason=reason,
                replacement=replacement,
                operation=operation,
                evidenceRefs=evidence_refs,
                status="executed",
            ),
        )
        working_resume = candidate_resume

    return edits, rejected


def _model_edit_suggestions(
    resume: dict[str, Any],
    value: object,
    *,
    locale: str,
) -> list[AgentResumeEditSuggestion]:
    """Convert model-supplied edits into validated frontend operations."""

    edits, _rejected = _model_edit_suggestions_with_diagnostics(
        resume,
        value,
        locale=locale,
    )
    return edits


def _model_plan_steps(value: object) -> list[EditPlanStep]:
    """Convert model-supplied plan steps into lightweight plan metadata."""

    if not isinstance(value, list):
        return []

    steps: list[EditPlanStep] = []
    for item in value:
        if not isinstance(item, dict):
            continue

        action = _model_string(item.get("action"))
        target = _model_string(item.get("target"))
        reason = _model_string(item.get("reason"))
        if action and target and reason:
            steps.append(EditPlanStep(action=action, target=target, reason=reason))

    return steps


def _react_max_iterations(request: AgentChatRequest) -> int:
    """Return the bounded per-request ReAct attempt limit."""

    raw_value = request.settings.get("maxReActIterations")
    if not isinstance(raw_value, int) or isinstance(raw_value, bool):
        raw_value = DEFAULT_REACT_MAX_ITERATIONS

    return min(
        MAX_REACT_MAX_ITERATIONS,
        max(MIN_REACT_MAX_ITERATIONS, raw_value),
    )


def _bounded_index(index: int | None, length: int) -> int:
    """Return a safe insertion index for draft mutations."""

    if index is None:
        return length

    return min(length, max(0, index))


def _compact_observation_value(value: object) -> object:
    """Return a compact value safe for model observation and tool UI."""

    if isinstance(value, str):
        return value if len(value) <= 220 else f"{value[:217]}..."
    if isinstance(value, list):
        return [_compact_observation_value(item) for item in value[:6]]
    if isinstance(value, dict):
        return {
            str(key): _compact_observation_value(item)
            for key, item in list(value.items())[:10]
        }

    return value


def _item_kind_from_shape(item: dict[str, Any]) -> str:
    """Infer a validated V2 item's kind from its discriminating field names."""

    if "school" in item:
        return "education"
    if "company" in item:
        return "experience"
    if "techStack" in item:
        return "project"
    if "issuer" in item:
        return "achievement"
    if "content" in item:
        return "simple_list"
    return ""


def _resume_item_observation_text(item: object) -> str:
    """Return a concise user-readable semantic item snapshot."""

    if not isinstance(item, dict):
        return ""

    kind = _item_kind_from_shape(item)
    fields = [
        _model_string(item.get(field))
        for field in ITEM_STRING_FIELDS_BY_KIND.get(kind, ())
    ]
    for field in ITEM_LIST_FIELDS_BY_KIND.get(kind, ()):
        fields.extend(_string_list(item.get(field)))

    return "\n".join(field for field in fields if field)


def _resume_item_preview(item: object) -> str:
    """Return the first readable field from a resume item."""

    if not isinstance(item, dict):
        return ""

    kind = _item_kind_from_shape(item)
    for key in ITEM_STRING_FIELDS_BY_KIND.get(kind, ()):
        if value := _model_string(item.get(key)):
            return value

    for field in ITEM_LIST_FIELDS_BY_KIND.get(kind, ()):
        for entry in _string_list(item.get(field)):
            if value := _model_string(entry):
                return value

    return ""


def _resume_section_observation_text(section: object) -> str:
    """Return a concise user-readable section snapshot."""

    if not isinstance(section, dict):
        return ""

    fields = [_model_string(section.get("title"))]
    items = section.get("items")
    if isinstance(items, list):
        fields.extend(
            item_text
            for item in items[:3]
            if (item_text := _resume_item_observation_text(item))
        )

    return "\n\n".join(field for field in fields if field)


def _operation_snapshot(
    resume: dict[str, Any],
    operation: dict[str, Any],
) -> object:
    """Return the current draft value targeted by an operation."""

    operation_type = operation.get("type")
    if operation_type == "replace_field":
        basic = resume.get("basic")
        if not isinstance(basic, dict):
            return None

        path = str(operation.get("path", ""))
        return basic.get(path[6:]) if path.startswith("basic.") else None

    if operation_type == "insert_section":
        return {"sectionCount": len(_resume_sections(resume))}

    if operation_type in {"update_section", "delete_section"}:
        return _find_resume_section(resume, str(operation.get("sectionId", "")))

    if operation_type == "reorder_sections":
        return [section.get("id") for section in _resume_sections(resume)]

    if operation_type == "insert_item":
        section = _find_resume_section(resume, str(operation.get("sectionId", "")))
        items = section.get("items") if section else None
        return {"itemCount": len(items)} if isinstance(items, list) else None

    if operation_type in {"update_item", "delete_item"}:
        section = _find_resume_section(resume, str(operation.get("sectionId", "")))
        if not section:
            return None
        return _find_resume_item(section, str(operation.get("itemId", "")))

    if operation_type == "reorder_items":
        section = _find_resume_section(resume, str(operation.get("sectionId", "")))
        items = section.get("items") if section else None
        if not isinstance(items, list):
            return None
        return [item.get("id") for item in items if isinstance(item, dict)]

    return None


def _operation_observation_value(
    resume: dict[str, Any],
    operation: dict[str, Any],
    *,
    after: bool,
) -> object:
    """Return a user-facing before/after observation value."""

    operation_type = operation.get("type")
    if operation_type == "replace_field":
        path = str(operation.get("path", ""))
        if is_pii_basic_path(path):
            # Never echo an existing personal value back into model-visible
            # tool output. The post-edit value is safe because it came from
            # the current user request.
            return operation.get("value") if after else "[hidden]"

    if operation_type == "insert_section":
        if not after:
            return None
        return _resume_section_observation_text(operation.get("section"))

    if operation_type == "insert_item":
        if not after:
            return None
        return _resume_item_observation_text(operation.get("item"))

    return _operation_snapshot(resume, operation)


def _apply_edit_operation(
    resume: dict[str, Any],
    operation: dict[str, Any],
) -> None:
    """Apply one normalized edit operation to the local draft copy."""

    operation_type = operation.get("type")
    if operation_type == "replace_field":
        basic = resume.setdefault("basic", {})
        if isinstance(basic, dict):
            path = str(operation.get("path", ""))
            if path.startswith("basic."):
                basic[path[6:]] = operation.get("value")
        return

    sections = resume.setdefault("sections", [])
    if not isinstance(sections, list):
        resume["sections"] = []
        sections = resume["sections"]

    if operation_type == "insert_section":
        index = _bounded_index(_model_int(operation.get("index")), len(sections))
        sections.insert(index, deepcopy(operation.get("section")))
        return

    if operation_type == "update_section":
        section = _find_resume_section(resume, str(operation.get("sectionId", "")))
        patch = operation.get("patch")
        if section and isinstance(patch, dict):
            section.update(patch)
        return

    if operation_type == "delete_section":
        section_id = str(operation.get("sectionId", ""))
        resume["sections"] = [
            section
            for section in sections
            if not isinstance(section, dict) or section.get("id") != section_id
        ]
        return

    if operation_type == "reorder_sections":
        section_ids = _string_list(operation.get("sectionIds"))
        indexed = {
            str(section.get("id")): section
            for section in sections
            if isinstance(section, dict) and isinstance(section.get("id"), str)
        }
        ordered = [
            indexed[section_id] for section_id in section_ids if section_id in indexed
        ]
        remaining = [
            section
            for section in sections
            if not isinstance(section, dict)
            or not isinstance(section.get("id"), str)
            or section.get("id") not in section_ids
        ]
        resume["sections"] = [*ordered, *remaining]
        return

    section = _find_resume_section(resume, str(operation.get("sectionId", "")))
    if not section:
        return

    items = section.setdefault("items", [])
    if not isinstance(items, list):
        section["items"] = []
        items = section["items"]

    if operation_type == "insert_item":
        candidate = operation.get("item")
        kind = _model_string(section.get("kind"))
        if (
            kind == "simple_list"
            or not is_resume_item_for_kind(candidate, kind)
            or not isinstance(candidate, dict)
            or candidate["id"] in _resume_item_ids(resume)
        ):
            return
        index = _bounded_index(_model_int(operation.get("index")), len(items))
        items.insert(index, deepcopy(candidate))
        return

    if operation_type == "update_item":
        item = _find_resume_item(section, str(operation.get("itemId", "")))
        patch = operation.get("patch")
        if item and isinstance(patch, dict):
            kind = _model_string(section.get("kind"))
            safe_patch = _safe_item_patch(patch, kind=kind, base_item=item)
            candidate = {**item, **safe_patch}
            if set(safe_patch) == set(patch) and is_resume_item_for_kind(
                candidate,
                kind,
            ):
                item.update(safe_patch)
        return

    if operation_type == "delete_item":
        if section.get("kind") == "simple_list":
            return
        item_id = str(operation.get("itemId", ""))
        section["items"] = [
            item
            for item in items
            if not isinstance(item, dict) or item.get("id") != item_id
        ]
        return

    if operation_type == "reorder_items":
        if section.get("kind") == "simple_list":
            return
        item_ids = _string_list(operation.get("itemIds"))
        indexed_items = {
            str(item.get("id")): item
            for item in items
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        ordered_items = [
            indexed_items[item_id] for item_id in item_ids if item_id in indexed_items
        ]
        remaining_items = [
            item
            for item in items
            if not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or item.get("id") not in item_ids
        ]
        section["items"] = [*ordered_items, *remaining_items]


def _apply_edit_operations(
    resume: dict[str, Any],
    edits: list[AgentResumeEditSuggestion],
) -> None:
    """Apply accepted edit operations to the local draft copy."""

    for edit in edits:
        if edit.operation:
            _apply_edit_operation(resume, edit.operation)


def _edit_observations(
    before_resume: dict[str, Any],
    after_resume: dict[str, Any],
    edits: list[AgentResumeEditSuggestion],
) -> list[dict[str, Any]]:
    """Build observations that let the model inspect draft edit effects."""

    observations: list[dict[str, Any]] = []
    for edit in edits:
        operation = edit.operation or {}
        observations.append(
            {
                "target": edit.target,
                "operationType": operation.get("type"),
                "status": edit.status,
                "before": _compact_observation_value(
                    _operation_observation_value(
                        before_resume,
                        operation,
                        after=False,
                    ),
                ),
                "after": _compact_observation_value(
                    _operation_observation_value(
                        after_resume,
                        operation,
                        after=True,
                    ),
                ),
                "instruction": (
                    "Decide from this Observation whether the draft now satisfies "
                    "the user request. If yes, call finish. If not, choose the "
                    "next corrective Action."
                ),
            },
        )

    return observations


def _merge_edits(
    current_edits: list[AgentResumeEditSuggestion],
    incoming_edits: list[AgentResumeEditSuggestion],
) -> list[AgentResumeEditSuggestion]:
    """Preserve the exact operation sequence used to build the server draft.

    Targets are descriptive labels, not operation identities. Collapsing by
    target can drop an insert followed by an update, leaving the client unable
    to replay the same transaction that the server already validated.
    """

    return [*current_edits, *incoming_edits]
