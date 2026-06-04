from copy import deepcopy
from typing import Any
from uuid import uuid4

from app.schemas.agent import AgentChatRequest, AgentResumeEditSuggestion

from ..models import EditPlanStep
from ..prompts import (
    DEFAULT_REACT_MAX_ITERATIONS,
    MAX_REACT_MAX_ITERATIONS,
    MIN_REACT_MAX_ITERATIONS,
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
SECTION_PATCH_FIELDS = {"kind", "layout", "customTitle"}
ITEM_PATCH_FIELDS = {"title", "subtitle", "meta", "period", "description", "highlights"}


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
    return {
        "id": item_id,
        "title": _model_string(value.get("title")),
        "subtitle": _model_string(value.get("subtitle")),
        "meta": _model_string(value.get("meta")),
        "period": _model_string(value.get("period")),
        "description": _model_string(value.get("description")),
        "highlights": _string_list(value.get("highlights")),
    }


def _normalized_section(value: object) -> dict[str, Any] | None:
    """Return a safe ResumeSection payload from model JSON."""

    if not isinstance(value, dict):
        return None

    kind = _model_string(value.get("kind"))
    layout = _model_string(value.get("layout"))
    items = value.get("items")
    normalized_items = (
        [_normalized_item(item) for item in items] if isinstance(items, list) else []
    )
    normalized_items = [item for item in normalized_items if item is not None]

    return {
        "id": _model_string(value.get("id")) or f"section-agent-{uuid4().hex[:8]}",
        "kind": (
            kind
            if kind in {"education", "internship", "project", "other", "custom"}
            else "custom"
        ),
        "layout": layout if layout in {"timeline", "list"} else "timeline",
        "customTitle": _model_string(value.get("customTitle")),
        "items": normalized_items,
    }


def _safe_item_patch(value: object) -> dict[str, Any]:
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

    return patch


def _safe_section_patch(value: object) -> dict[str, Any]:
    """Return only frontend-writable section fields from a model patch."""

    if not isinstance(value, dict):
        return {}

    patch: dict[str, Any] = {}
    for key in SECTION_PATCH_FIELDS:
        field_value = value.get(key)
        if not isinstance(field_value, str):
            continue
        if key == "kind" and field_value not in {
            "education",
            "internship",
            "project",
            "other",
            "custom",
        }:
            continue
        if key == "layout" and field_value not in {"timeline", "list"}:
            continue
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
            and path[6:] in BASIC_EDIT_FIELDS
            and isinstance(value, str)
        ):
            return {"type": "replace_field", "path": path, "value": value}
        return None

    if operation_type == "insert_section":
        section = _normalized_section(operation.get("section"))
        if not section:
            return None
        normalized: dict[str, Any] = {"type": "insert_section", "section": section}
        index = _model_int(operation.get("index"))
        if index is not None:
            normalized["index"] = index
        return normalized

    if operation_type == "update_section":
        section_id = _model_string(operation.get("sectionId"))
        patch = _safe_section_patch(operation.get("patch"))
        if section_id and patch and _find_resume_section(resume, section_id):
            return {"type": "update_section", "sectionId": section_id, "patch": patch}
        return None

    if operation_type == "delete_section":
        section_id = _model_string(operation.get("sectionId"))
        if section_id and _find_resume_section(resume, section_id):
            return {"type": "delete_section", "sectionId": section_id}
        return None

    if operation_type == "reorder_sections":
        section_ids = _string_list(operation.get("sectionIds"))
        valid_ids = {
            str(section.get("id"))
            for section in _resume_sections(resume)
            if isinstance(section.get("id"), str)
        }
        ordered_ids = [
            section_id for section_id in section_ids if section_id in valid_ids
        ]
        if ordered_ids:
            return {"type": "reorder_sections", "sectionIds": ordered_ids}
        return None

    if operation_type == "insert_item":
        section_id = _model_string(operation.get("sectionId"))
        item = _normalized_item(operation.get("item"))
        if not section_id or not item or not _find_resume_section(resume, section_id):
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
        patch = _safe_item_patch(operation.get("patch"))
        if section and item_id and patch and _find_resume_item(section, item_id):
            return {
                "type": "update_item",
                "sectionId": section_id,
                "itemId": item_id,
                "patch": patch,
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
        valid_item_ids = {
            str(item.get("id"))
            for item in section.get("items", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        ordered_ids = [item_id for item_id in item_ids if item_id in valid_item_ids]
        if ordered_ids:
            return {
                "type": "reorder_items",
                "sectionId": section_id,
                "itemIds": ordered_ids,
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
            if isinstance(patch.get("description"), str):
                return patch["description"]
            highlights = _string_list(patch.get("highlights"))
            if highlights:
                return " / ".join(highlights[:2])
    if operation_type == "insert_section":
        section = operation.get("section", {})
        if isinstance(section, dict):
            return _model_string(section.get("customTitle")) or _model_string(
                section.get("kind"),
            )
    if operation_type == "insert_item":
        item = operation.get("item", {})
        if isinstance(item, dict):
            return _model_string(item.get("title")) or _model_string(
                item.get("description"),
            )
    return None


def _model_edit_suggestions(
    resume: dict[str, Any],
    value: object,
    *,
    locale: str,
) -> list[AgentResumeEditSuggestion]:
    """Convert model-supplied edits into validated frontend operations."""

    if not isinstance(value, list):
        return []

    edits: list[AgentResumeEditSuggestion] = []
    for index, item in enumerate(value, start=1):
        if not isinstance(item, dict):
            continue

        operation = _normalize_edit_operation(resume, item.get("operation"))
        if not operation:
            continue

        title = _model_string(item.get("title")) or (
            f"修改建议 {index}" if locale == "zh" else f"Edit {index}"
        )
        target = _model_string(item.get("target")) or _operation_target(operation)
        reason = _model_string(item.get("reason")) or (
            "根据当前请求生成可预览草稿。"
            if locale == "zh"
            else "Create a previewable draft for the current request."
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
                    _operation_snapshot(before_resume, operation),
                ),
                "after": _compact_observation_value(
                    _operation_snapshot(after_resume, operation),
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
