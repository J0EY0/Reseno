import re
from copy import deepcopy
from typing import Any
from uuid import uuid4

from app.schemas.agent import AgentChatRequest, AgentResumeEditSuggestion

from ..localization import agent_text
from ..models import EditPlanStep
from ..parsing_patterns import compiled_agent_pattern
from ..privacy import AGENT_WRITABLE_BASIC_FIELDS, is_pii_basic_path
from ..prompts import (
    DEFAULT_REACT_MAX_ITERATIONS,
    MAX_REACT_MAX_ITERATIONS,
    MIN_REACT_MAX_ITERATIONS,
)
from ..section_registry import SECTION_KIND_ALIASES


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
SECTION_PATCH_FIELDS = {"kind", "section_type", "layout", "customTitle"}
ITEM_PATCH_FIELDS = {"title", "subtitle", "meta", "period", "description", "highlights"}
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

    text = _model_string(value).lower()
    if not text:
        return ""

    direct = SECTION_KIND_ALIASES.get(text)
    if direct:
        return direct

    for token, kind in SECTION_KIND_ALIASES.items():
        if token and token in text:
            return kind

    return ""


def _normalized_section_kind(*values: object) -> str:
    """Return a standard section kind, falling back to custom."""

    for value in values:
        kind = _section_kind_from_text(value)
        if kind and kind != "custom":
            return kind

    return "custom"


def _normalized_custom_title(value: object, kind: str) -> str:
    """Allow free section names only for custom sections."""

    title = _model_string(value)
    if kind != "custom":
        return ""

    if _section_kind_from_text(title) and _section_kind_from_text(title) != "custom":
        return ""

    return title


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


def _field_values_for_dedupe(item: dict[str, Any]) -> list[str]:
    """Return fields that should not be repeated in prose or bullets."""

    return [
        _model_string(item.get("title")),
        _model_string(item.get("subtitle")),
        _model_string(item.get("meta")),
        _model_string(item.get("period")),
    ]


def _has_repeated_field_values(value: str, field_values: list[str]) -> bool:
    """Return whether text repeats multiple structured fields."""

    text_key = _duplicate_key(value)
    matches = 0
    for field_value in field_values:
        field_key = _duplicate_key(field_value)
        if len(field_key) >= 3 and field_key in text_key:
            matches += 1

    return matches >= 2


def _clean_resume_item_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Keep generated resume item fields in their own lanes."""

    cleaned = {**item}
    for key in ("title", "subtitle", "meta", "period", "description"):
        cleaned[key] = _clean_generated_text(cleaned.get(key))

    field_values = _field_values_for_dedupe(cleaned)
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

    cleaned["highlights"] = next_highlights
    return cleaned


def _model_int(value: object) -> int | None:
    """Return a bounded integer from model-provided JSON."""

    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)

    return None


def _normalized_item(value: object) -> dict[str, Any] | None:
    """Return a safe ResumeSectionItem payload from model JSON."""

    if not isinstance(value, dict):
        return None

    item_id = _model_string(value.get("id")) or f"item-agent-{uuid4().hex[:8]}"
    return _clean_resume_item_fields({
        "id": item_id,
        "title": _model_string(value.get("title")),
        "subtitle": _model_string(value.get("subtitle")),
        "meta": _model_string(value.get("meta")),
        "period": _model_string(value.get("period")),
        "description": _model_string(value.get("description")),
        "highlights": _string_list(value.get("highlights")),
    })


def _normalized_section(value: object) -> dict[str, Any] | None:
    """Return a safe ResumeSection payload from model JSON."""

    if not isinstance(value, dict):
        return None

    kind = _normalized_section_kind(
        value.get("section_type"),
        value.get("sectionType"),
        value.get("kind"),
        value.get("customTitle"),
    )
    layout = _model_string(value.get("layout"))
    items = value.get("items")
    normalized_items = (
        [_normalized_item(item) for item in items] if isinstance(items, list) else []
    )
    normalized_items = [item for item in normalized_items if item is not None]

    return {
        "id": _model_string(value.get("id")) or f"section-agent-{uuid4().hex[:8]}",
        "kind": kind,
        "layout": layout if layout in {"timeline", "list"} else "timeline",
        "customTitle": _normalized_custom_title(value.get("customTitle"), kind),
        "items": normalized_items,
    }


def _safe_item_patch(
    value: object,
    *,
    base_item: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return only frontend-writable item fields from a model patch."""

    if not isinstance(value, dict):
        return {}

    patch: dict[str, Any] = {}
    for key in ITEM_PATCH_FIELDS:
        field_value = value.get(key)
        if key == "highlights":
            highlights = _string_list(field_value)
            if highlights:
                patch[key] = highlights
            continue

        if isinstance(field_value, str):
            patch[key] = field_value

    if not patch:
        return {}

    merged = _clean_resume_item_fields({**(base_item or {}), **patch})
    cleaned_patch: dict[str, Any] = {}
    for key in patch:
        if key not in merged:
            continue
        if key == "highlights" and not merged[key]:
            continue
        cleaned_patch[key] = merged[key]

    return cleaned_patch


def _safe_section_patch(value: object) -> dict[str, Any]:
    """Return only frontend-writable section fields from a model patch."""

    if not isinstance(value, dict):
        return {}

    patch: dict[str, Any] = {}
    for key in SECTION_PATCH_FIELDS:
        field_value = value.get(key)
        if not isinstance(field_value, str):
            continue
        if key in {"kind", "section_type"}:
            patch["kind"] = _normalized_section_kind(field_value)
            continue
        if key == "layout" and field_value not in {"timeline", "list"}:
            continue
        if key == "customTitle":
            kind = _normalized_section_kind(
                value.get("kind"),
                value.get("section_type"),
            )
            patch[key] = _normalized_custom_title(field_value, kind)
        else:
            patch[key] = field_value

    return patch


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
        if section["id"] in existing_ids or len(item_ids) != len(set(item_ids)):
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
        item = _normalized_item(operation.get("item"))
        section = _find_resume_section(resume, section_id)
        if (
            not section_id
            or not item
            or not section
            or _find_resume_item(section, item["id"])
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
        patch = _safe_item_patch(
            operation.get("patch"),
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
        if section and item_id and _find_resume_item(section, item_id):
            return {"type": "delete_item", "sectionId": section_id, "itemId": item_id}
        return None

    if operation_type == "reorder_items":
        section_id = _model_string(operation.get("sectionId"))
        section = _find_resume_section(resume, section_id)
        item_ids = _string_list(operation.get("itemIds"))
        if not section or not item_ids:
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
            description = patch.get("description")
            if isinstance(description, str):
                return description
            highlights = _string_list(patch.get("highlights"))
            if highlights:
                return " / ".join(highlights[:2])
    if operation_type == "insert_section":
        section = operation.get("section", {})
        if isinstance(section, dict):
            title = _model_string(section.get("customTitle"))
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
        if is_pii_basic_path(path):
            return "replace_field cannot edit hidden personal fields."
        if not path.startswith("basic.") or path[6:] not in BASIC_EDIT_FIELDS:
            return "replace_field requires path basic.<writableField>."
        if path[6:] not in AGENT_WRITABLE_BASIC_FIELDS:
            return "replace_field can only edit basic.headline or basic.summary."
        if not isinstance(operation.get("value"), str):
            return "replace_field requires a string value."
        basic = resume.get("basic")
        if isinstance(basic, dict) and basic.get(path[6:]) == operation.get("value"):
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
        if not section_id or not _find_resume_section(resume, section_id):
            return "insert_item requires an existing sectionId."
        if not _normalized_item(operation.get("item")):
            return "insert_item requires a valid item object."
        item = _normalized_item(operation.get("item"))
        section = _find_resume_section(resume, section_id)
        if section and item and _find_resume_item(section, item["id"]):
            return "insert_item requires a unique item id in the target section."

    if operation_type in {"update_item", "delete_item", "reorder_items"}:
        section_id = _model_string(operation.get("sectionId"))
        section = _find_resume_section(resume, section_id)
        if not section:
            return f"{operation_type} requires an existing sectionId."

        if operation_type == "reorder_items":
            item_ids = _string_list(operation.get("itemIds"))
            current_item_ids = [
                str(item.get("id"))
                for item in section.get("items", [])
                if isinstance(item, dict) and isinstance(item.get("id"), str)
            ]
            if len(item_ids) != len(set(item_ids)):
                return "reorder_items cannot contain duplicate itemIds."
            if (
                len(item_ids) != len(current_item_ids)
                or set(item_ids) != set(current_item_ids)
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
            base_item=item if isinstance(item, dict) else None,
        ):
            return "update_item requires at least one writable item patch field."
        if operation_type == "update_item":
            patch = _safe_item_patch(operation.get("patch"), base_item=item)
            if all(item.get(key) == value for key, value in patch.items()):
                return "update_item must change at least one field."

    return "Operation was rejected by validation."


def _model_edit_suggestions_with_diagnostics(
    resume: dict[str, Any],
    value: object,
    *,
    locale: str,
) -> tuple[list[AgentResumeEditSuggestion], list[dict[str, Any]]]:
    """Convert model edits and return rejected entries for tool observations."""

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

        edits.append(
            AgentResumeEditSuggestion(
                id=f"edit-{uuid4().hex[:8]}",
                title=title,
                target=target,
                reason=reason,
                replacement=replacement,
                operation=operation,
                status="executed",
            ),
        )
        _apply_edit_operation(working_resume, operation)

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


def _resume_item_observation_text(item: object) -> str:
    """Return a concise user-readable item snapshot."""

    if not isinstance(item, dict):
        return ""

    fields = [
        _model_string(item.get("title")),
        _model_string(item.get("subtitle")),
        _model_string(item.get("meta")),
        _model_string(item.get("period")),
        _model_string(item.get("description")),
    ]
    highlights = item.get("highlights")
    if isinstance(highlights, list):
        fields.extend(_model_string(highlight) for highlight in highlights)

    return "\n".join(field for field in fields if field)


def _resume_item_preview(item: object) -> str:
    """Return the first readable field from a resume item."""

    if not isinstance(item, dict):
        return ""

    for key in ("title", "subtitle", "meta", "period", "description"):
        if value := _model_string(item.get(key)):
            return value

    highlights = item.get("highlights")
    if isinstance(highlights, list):
        for highlight in highlights:
            if value := _model_string(highlight):
                return value

    return ""


def _resume_section_observation_text(section: object) -> str:
    """Return a concise user-readable section snapshot."""

    if not isinstance(section, dict):
        return ""

    fields = [_model_string(section.get("customTitle"))]
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
        index = _bounded_index(_model_int(operation.get("index")), len(items))
        items.insert(index, deepcopy(operation.get("item")))
        return

    if operation_type == "update_item":
        item = _find_resume_item(section, str(operation.get("itemId", "")))
        patch = operation.get("patch")
        if item and isinstance(patch, dict):
            item.update(patch)
        return

    if operation_type == "delete_item":
        item_id = str(operation.get("itemId", ""))
        section["items"] = [
            item
            for item in items
            if not isinstance(item, dict) or item.get("id") != item_id
        ]
        return

    if operation_type == "reorder_items":
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
    """Merge later draft edits by target so corrective actions replace stale ones."""

    merged = list(current_edits)
    target_index = {edit.target: index for index, edit in enumerate(merged)}
    for edit in incoming_edits:
        if edit.target in target_index:
            merged[target_index[edit.target]] = edit
        else:
            target_index[edit.target] = len(merged)
            merged.append(edit)

    return merged
