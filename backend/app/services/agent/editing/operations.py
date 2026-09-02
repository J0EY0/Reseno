import re
from copy import deepcopy
from html import escape
from typing import Any
from uuid import uuid4

from app.schemas.agent import AgentResumeEditSuggestion
from app.services.resume_document_contract import (
    ITEM_LIST_FIELDS_BY_KIND,
    ITEM_STRING_FIELDS_BY_KIND,
    ResumeDocumentContractError,
    is_resume_item_for_kind,
    validate_resume_document,
)

from ..contracts import resume_edit_operation_error
from ..localization import agent_text
from ..privacy import is_pii_basic_path


def _string_list(value: object) -> list[str]:
    """Return only string entries from a possible list."""

    if not isinstance(value, list):
        return []

    return [item for item in value if isinstance(item, str)]


QUALIFIED_ITEM_DIFF_FIELDS = frozenset(
    {
        "name",
        "title",
        "authors",
        "venue",
        "role",
        "url",
        "description",
        "highlights",
    },
)


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
        if isinstance(item, dict) and isinstance((item_id := item.get("id")), str)
    }


def _model_string(value: object) -> str:
    """Return a stripped model-provided string."""

    return value.strip() if isinstance(value, str) else ""


def _model_int(value: object) -> int | None:
    """Return a bounded integer from model-provided JSON."""

    if isinstance(value, int) and not isinstance(value, bool):
        return int(value)

    return None


def _complete_inserted_item(value: object, kind: str) -> object:
    """Fill canonical empty fields without asking the model to serialize them."""

    if not isinstance(value, dict) or kind not in ITEM_STRING_FIELDS_BY_KIND:
        return value
    item = deepcopy(value)
    for field in ITEM_STRING_FIELDS_BY_KIND[kind]:
        item.setdefault(field, "")
    for field in ITEM_LIST_FIELDS_BY_KIND[kind]:
        item.setdefault(field, [])
    return item


_RICH_TEXT_DOCUMENT_PATTERN = re.compile(
    r"^\s*<(ol|p|ul)>[\s\S]*</\1>\s*$",
    flags=re.IGNORECASE,
)
_RICH_TEXT_STRUCTURAL_SPACE_PATTERN = re.compile(
    r"(</?(?:li|ol|p|ul)>)\s+(?=</?(?:li|ol|p|ul)>)",
    flags=re.IGNORECASE,
)
_RICH_TEXT_SINGLE_LIST_PARAGRAPH_PATTERN = re.compile(
    r"<li><p>([\s\S]*?)</p></li>",
    flags=re.IGNORECASE,
)


def _rich_text_comparison_key(value: object) -> str | None:
    """Return a conservative key for one canonical rich-text document."""

    if not isinstance(value, str) or not _RICH_TEXT_DOCUMENT_PATTERN.fullmatch(value):
        return None
    normalized = _RICH_TEXT_STRUCTURAL_SPACE_PATTERN.sub(r"\1", value.strip())
    return _RICH_TEXT_SINGLE_LIST_PARAGRAPH_PATTERN.sub(
        r"<li>\1</li>",
        normalized,
    )


def _edit_field_values_equal(field: str, current: object, proposed: object) -> bool:
    if field == "content":
        current_key = _rich_text_comparison_key(current)
        proposed_key = _rich_text_comparison_key(proposed)
        if current_key is not None and proposed_key is not None:
            return current_key == proposed_key
    if (
        field == "highlights"
        and isinstance(current, list)
        and isinstance(proposed, list)
        and len(current) == len(proposed) == 1
    ):
        current_key = _rich_text_comparison_key(current[0])
        proposed_key = _rich_text_comparison_key(proposed[0])
        if current_key is not None and proposed_key is not None:
            return current_key == proposed_key
    return current == proposed


def _canonical_highlight_update(current: object, proposed: object) -> object:
    """Keep edits to editor-owned highlights in its one-document shape."""

    current_values = _string_list(current)
    proposed_values = _string_list(proposed)
    if (
        len(current_values) != 1
        or not _RICH_TEXT_DOCUMENT_PATTERN.fullmatch(current_values[0])
        or not isinstance(proposed, list)
        or len(proposed_values) != len(proposed)
        or not proposed_values
        or (
            len(proposed_values) == 1
            and _RICH_TEXT_DOCUMENT_PATTERN.fullmatch(proposed_values[0])
        )
    ):
        return proposed

    items = "".join(f"<li>{escape(value)}</li>" for value in proposed_values)
    return [f"<ul>{items}</ul>"]


def _complete_edit_operation(
    resume: dict[str, Any],
    operation: dict[str, Any],
) -> dict[str, Any]:
    """Return the canonical operation shape for compact model input."""

    parsed = deepcopy(operation)
    operation_type = parsed.get("type")
    if operation_type == "insert_item":
        section = _find_resume_section(resume, _model_string(parsed.get("sectionId")))
        kind = _model_string(section.get("kind")) if section else ""
        parsed["item"] = _complete_inserted_item(parsed.get("item"), kind)
    elif operation_type == "update_item" and isinstance(
        patch := parsed.get("patch"),
        dict,
    ):
        section = _find_resume_section(resume, _model_string(parsed.get("sectionId")))
        item = (
            _find_resume_item(section, _model_string(parsed.get("itemId")))
            if section
            else None
        )
        if item and "highlights" in patch:
            patch["highlights"] = _canonical_highlight_update(
                item.get("highlights"),
                patch["highlights"],
            )
    elif operation_type == "insert_section" and isinstance(
        section := parsed.get("section"),
        dict,
    ):
        kind = _model_string(section.get("kind"))
        section.setdefault("title", "")
        section.setdefault("items", [])
        if isinstance(items := section.get("items"), list):
            section["items"] = [_complete_inserted_item(item, kind) for item in items]
    return parsed


def _operation_domain_error(
    resume: dict[str, Any],
    operation: dict[str, Any],
) -> str | None:
    """Return a state-dependent error for one schema-valid operation."""

    operation_type = str(operation["type"])
    if operation_type == "replace_field":
        return None

    if operation_type == "insert_section":
        section = operation["section"]
        if not isinstance(section, dict):
            return "Canonical protocol error: section must be an object."
        section_id = str(section["id"])
        if _find_resume_section(resume, section_id):
            return "insert_section requires a unique section id."
        item_ids = [
            str(item["id"]) for item in section["items"] if isinstance(item, dict)
        ]
        if len(item_ids) != len(set(item_ids)):
            return "insert_section requires unique item ids."
        if set(item_ids) & _resume_item_ids(resume):
            return "insert_section item ids must be unique in the resume."
        return None

    if operation_type == "update_section":
        section_id = str(operation["sectionId"])
        section = _find_resume_section(resume, section_id)
        if not section:
            return "update_section requires an existing sectionId."
        patch = operation["patch"]
        return None

    if operation_type == "delete_section":
        return (
            None
            if _find_resume_section(resume, str(operation["sectionId"]))
            else "delete_section requires an existing sectionId."
        )

    if operation_type == "reorder_sections":
        section_ids = _string_list(operation["sectionIds"])
        current_ids = [
            str(section.get("id"))
            for section in _resume_sections(resume)
            if isinstance(section.get("id"), str)
        ]
        if len(section_ids) != len(current_ids) or set(section_ids) != set(current_ids):
            return "reorder_sections requires every existing sectionId exactly once."
        return None

    if operation_type == "insert_item":
        section_id = str(operation["sectionId"])
        section = _find_resume_section(resume, section_id)
        if not section:
            return "insert_item requires an existing sectionId."
        kind = str(section.get("kind") or "")
        if kind == "simple_list":
            return "simple_list has one rich-text item; update its content instead."
        item = operation["item"]
        if not isinstance(item, dict) or not is_resume_item_for_kind(item, kind):
            return "insert_item item fields must match the target section kind."
        if str(item["id"]) in _resume_item_ids(resume):
            return "insert_item requires a resume-wide unique item id."
        return None

    if operation_type == "update_item":
        section_id = str(operation["sectionId"])
        item_id = str(operation["itemId"])
        section = _find_resume_section(resume, section_id)
        if not section:
            return "update_item requires an existing sectionId."
        item = _find_resume_item(section, item_id)
        if not item:
            return "update_item requires an existing itemId."
        patch = operation["patch"]
        if not isinstance(patch, dict) or not is_resume_item_for_kind(
            {**item, **patch},
            str(section.get("kind") or ""),
        ):
            return "update_item patch fields must match the target section kind."
        return None

    if operation_type == "delete_item":
        section_id = str(operation["sectionId"])
        item_id = str(operation["itemId"])
        section = _find_resume_section(resume, section_id)
        if not section:
            return "delete_item requires an existing sectionId."
        if section.get("kind") == "simple_list":
            return "simple_list has one rich-text item; update its content instead."
        if not _find_resume_item(section, item_id):
            return "delete_item requires an existing itemId."
        return None

    if operation_type == "reorder_items":
        section_id = str(operation["sectionId"])
        section = _find_resume_section(resume, section_id)
        if not section:
            return "reorder_items requires an existing sectionId."
        if section.get("kind") == "simple_list":
            return "simple_list has one rich-text item; update its content instead."
        item_ids = _string_list(operation["itemIds"])
        current_item_ids = [
            str(item.get("id"))
            for item in section.get("items", [])
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        if len(item_ids) != len(current_item_ids) or set(item_ids) != set(
            current_item_ids,
        ):
            return "reorder_items requires every existing itemId exactly once."
        return None

    return f"Unsupported operation type: {operation_type}."


def _operation_is_noop(
    resume: dict[str, Any],
    operation: dict[str, Any],
) -> bool:
    """Return whether a valid operation leaves the current draft unchanged."""

    operation_type = str(operation["type"])
    if operation_type == "replace_field":
        basic = resume.get("basic")
        path = str(operation["path"])
        return isinstance(basic, dict) and basic.get(path[6:]) == operation["value"]
    if operation_type == "update_section":
        section = _find_resume_section(resume, str(operation["sectionId"]))
        patch = operation["patch"]
        return bool(
            section
            and isinstance(patch, dict)
            and all(section.get(key) == value for key, value in patch.items())
        )
    if operation_type == "reorder_sections":
        current_ids = [
            str(section.get("id"))
            for section in _resume_sections(resume)
            if isinstance(section.get("id"), str)
        ]
        return _string_list(operation["sectionIds"]) == current_ids
    if operation_type == "update_item":
        section = _find_resume_section(resume, str(operation["sectionId"]))
        item = _find_resume_item(section, str(operation["itemId"])) if section else None
        patch = operation["patch"]
        return bool(
            item
            and isinstance(patch, dict)
            and all(
                _edit_field_values_equal(key, item.get(key), value)
                for key, value in patch.items()
            )
        )
    if operation_type == "reorder_items":
        section = _find_resume_section(resume, str(operation["sectionId"]))
        items = section.get("items") if section else None
        current_ids = [
            str(item.get("id"))
            for item in items or []
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        return _string_list(operation["itemIds"]) == current_ids
    return False


def _parse_edit_operation(
    resume: dict[str, Any],
    operation: object,
) -> tuple[dict[str, Any] | None, str | None]:
    """Parse one canonical operation, then enforce resume-state invariants."""

    if not isinstance(operation, dict):
        return None, "Canonical protocol error: operation must be an object."

    parsed = _complete_edit_operation(resume, operation)
    contract_error = resume_edit_operation_error(parsed)
    if contract_error is not None:
        return None, f"Canonical protocol error: {contract_error}"
    domain_error = _operation_domain_error(resume, parsed)
    if domain_error:
        return None, domain_error
    if _operation_is_noop(resume, parsed):
        return None, None
    return parsed, None


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


def _operation_label(
    resume: dict[str, Any],
    operation: dict[str, Any],
    locale: str,
) -> str:
    operation_type = operation.get("type")
    if operation_type == "replace_field":
        field = _model_string(operation.get("path")).removeprefix("basic.")
        return agent_text(locale, f"diff.field.{field}")
    if operation_type == "reorder_sections":
        return agent_text(locale, "edit.label.sections")

    section = operation.get("section") if operation_type == "insert_section" else None
    if not isinstance(section, dict):
        section = _find_resume_section(
            resume,
            _model_string(operation.get("sectionId")),
        )
    kind = _model_string(section.get("kind")) if section else ""
    return agent_text(locale, f"diff.kind.{kind}") if kind else ""


def _operation_title(
    resume: dict[str, Any],
    operation: object,
    locale: str,
    index: int,
) -> str:
    if not isinstance(operation, dict):
        return agent_text(locale, "edit.default.title", index=index)
    label = _operation_label(resume, operation, locale)
    if not label:
        return agent_text(locale, "edit.default.title", index=index)

    operation_type = operation.get("type")
    if operation_type in {"insert_section", "insert_item"}:
        action = "add"
    elif operation_type in {"delete_section", "delete_item"}:
        action = "delete"
    elif operation_type in {"reorder_sections", "reorder_items"}:
        action = "reorder"
    else:
        action = "update"
    return agent_text(locale, f"edit.title.{action}", label=label)


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
                "title",
                "authors",
                "venue",
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


def parse_edit_batch(
    resume: dict[str, Any],
    value: object,
    *,
    locale: str,
) -> tuple[list[AgentResumeEditSuggestion], list[dict[str, Any]]]:
    """Parse one model edit batch against the canonical operation contract."""

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

        operation, operation_error = _parse_edit_operation(
            working_resume,
            item.get("operation"),
        )
        if operation is None and operation_error is None:
            continue
        if operation is None:
            rejected.append(
                {
                    "index": index,
                    "title": _operation_title(
                        working_resume,
                        item.get("operation"),
                        locale,
                        index,
                    ),
                    "reason": operation_error or "Operation was rejected.",
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
                    "title": _operation_title(
                        working_resume,
                        operation,
                        locale,
                        index,
                    ),
                    "reason": f"{exc.code} at {exc.path}.",
                },
            )
            continue

        title = _operation_title(working_resume, operation, locale, index)
        target = _operation_target(operation)
        reason = agent_text(
            locale,
            "edit.default.reason",
        )
        replacement = _operation_replacement(operation)
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


def _bounded_index(index: int | None, length: int) -> int:
    """Return a safe insertion index for draft mutations."""

    if index is None:
        return length

    return min(length, max(0, index))


def _complete_observation_value(value: object) -> object:
    """Return the complete changed field used for the next model decision.

    Edit observations already contain only the operation target, not the full
    resume. Truncating them can hide a later bullet or the decisive end of a
    description and make the next model action incorrect.
    """

    return deepcopy(value)


def _item_kind_from_shape(item: dict[str, Any]) -> str:
    """Infer a validated V2 item's kind from its discriminating field names."""

    if "school" in item:
        return "education"
    if "company" in item:
        return "experience"
    if "techStack" in item:
        return "project"
    if "authors" in item:
        return "publication"
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
            # PII writes are rejected during normalization. Keep this fallback
            # opaque in both directions so future callers cannot echo a value.
            return "[hidden]"

    if operation_type == "insert_section":
        if not after:
            return None
        return _resume_section_observation_text(operation.get("section"))

    if operation_type == "insert_item":
        if not after:
            return None
        return _resume_item_observation_text(operation.get("item"))

    return _operation_snapshot(resume, operation)


def _operation_diff_value(
    resume: dict[str, Any],
    operation: dict[str, Any],
    *,
    after: bool,
) -> object:
    """Return the complete non-PII value persisted for human draft review."""

    operation_type = operation.get("type")
    if operation_type == "replace_field" and is_pii_basic_path(
        str(operation.get("path", "")),
    ):
        return "[hidden]"
    if operation_type == "insert_section":
        if not after:
            return None
        section = operation.get("section")
        section_id = str(section.get("id", "")) if isinstance(section, dict) else ""
        return _find_resume_section(resume, section_id)
    if operation_type == "insert_item":
        if not after:
            return None
        section = _find_resume_section(resume, str(operation.get("sectionId", "")))
        item = operation.get("item")
        item_id = str(item.get("id", "")) if isinstance(item, dict) else ""
        return _find_resume_item(section, item_id) if section else None
    return _operation_snapshot(resume, operation)


def _minimal_moved_ids(before_ids: list[str], after_ids: list[str]) -> set[str]:
    """Return IDs outside one deterministic longest common subsequence."""

    lengths = [[0] * (len(after_ids) + 1) for _ in range(len(before_ids) + 1)]
    for before_index in range(len(before_ids) - 1, -1, -1):
        for after_index in range(len(after_ids) - 1, -1, -1):
            if before_ids[before_index] == after_ids[after_index]:
                lengths[before_index][after_index] = (
                    lengths[before_index + 1][after_index + 1] + 1
                )
            else:
                lengths[before_index][after_index] = max(
                    lengths[before_index + 1][after_index],
                    lengths[before_index][after_index + 1],
                )

    stable_ids: set[str] = set()
    before_index = 0
    after_index = 0
    while before_index < len(before_ids) and after_index < len(after_ids):
        if before_ids[before_index] == after_ids[after_index]:
            stable_ids.add(before_ids[before_index])
            before_index += 1
            after_index += 1
        elif (
            lengths[before_index + 1][after_index]
            >= lengths[before_index][after_index + 1]
        ):
            before_index += 1
        else:
            after_index += 1

    return set(after_ids) - stable_ids


def _operation_review_diffs(
    *,
    edit: AgentResumeEditSuggestion,
    before_value: object,
    after_value: object,
    locale: str,
    section_kind: str,
    before_previous_id: str = "",
    before_next_id: str = "",
) -> list[dict[str, Any]]:
    """Return canonical review diffs derived only from one normalized operation."""

    operation = edit.operation or {}
    operation_type = str(operation.get("type") or "")
    if operation_type in {"insert_section", "insert_item"}:
        diff_kind = "added"
    elif operation_type in {"delete_section", "delete_item"}:
        diff_kind = "deleted"
    elif operation_type in {"reorder_sections", "reorder_items"}:
        diff_kind = "moved"
    else:
        diff_kind = "modified"

    common: dict[str, Any] = {
        "operationId": edit.id,
        "kind": diff_kind,
    }
    section_id = _model_string(operation.get("sectionId"))
    if operation_type == "insert_section":
        inserted_section = operation.get("section")
        if isinstance(inserted_section, dict):
            section_id = _model_string(inserted_section.get("id"))
    if section_id:
        common["sectionId"] = section_id
    item_id = _model_string(operation.get("itemId"))
    if operation_type == "insert_item":
        inserted_item = operation.get("item")
        if isinstance(inserted_item, dict):
            item_id = _model_string(inserted_item.get("id"))
    if item_id:
        common["itemId"] = item_id
    if diff_kind == "deleted" and before_previous_id:
        common["beforePreviousId"] = before_previous_id
    if diff_kind == "deleted" and before_next_id:
        common["beforeNextId"] = before_next_id

    if operation_type in {"reorder_sections", "reorder_items"}:
        if not (
            isinstance(before_value, list)
            and isinstance(after_value, list)
            and all(isinstance(value, str) for value in before_value)
            and all(isinstance(value, str) for value in after_value)
        ):
            return []
        before_ids = _string_list(before_value)
        after_ids = _string_list(after_value)
        moved_ids = _minimal_moved_ids(before_ids, after_ids)
        before_positions = {value: index for index, value in enumerate(before_ids)}
        diffs: list[dict[str, Any]] = []
        for after_index, moved_id in enumerate(after_ids):
            before_index = before_positions.get(moved_id)
            if before_index is None or moved_id not in moved_ids:
                continue
            if operation_type == "reorder_sections":
                path = f"sections.{moved_id}"
                identity = {"sectionId": moved_id}
            else:
                path = f"sections.{section_id}.items.{moved_id}"
                identity = {"sectionId": section_id, "itemId": moved_id}
            diffs.append(
                {
                    **common,
                    **identity,
                    "id": f"agent-diff-{edit.id}-{moved_id}",
                    "path": path,
                    "label": edit.title or path,
                    "before": before_index,
                    "after": after_index,
                },
            )
        return diffs

    if operation_type == "update_item":
        patch = operation.get("patch")
        if not (
            isinstance(before_value, dict)
            and isinstance(after_value, dict)
            and isinstance(patch, dict)
        ):
            return []
        base_path = _operation_target(operation)
        return [
            {
                **common,
                "id": f"agent-diff-{edit.id}-{field}",
                "path": f"{base_path}.{field}",
                "label": _review_diff_field_label(
                    field,
                    locale=locale,
                    section_kind=section_kind,
                ),
                "before": deepcopy(before_value.get(field)),
                "after": deepcopy(after_value.get(field)),
            }
            for field in patch
            if before_value.get(field) != after_value.get(field)
        ]

    if operation_type == "update_section":
        patch = operation.get("patch")
        if not (
            isinstance(before_value, dict)
            and isinstance(after_value, dict)
            and isinstance(patch, dict)
        ):
            return []
        base_path = _operation_target(operation)
        return [
            {
                **common,
                "id": f"agent-diff-{edit.id}-{field}",
                "path": f"{base_path}.{field}",
                "label": _review_diff_field_label(field, locale=locale),
                "before": deepcopy(before_value.get(field)),
                "after": deepcopy(after_value.get(field)),
            }
            for field in patch
            if before_value.get(field) != after_value.get(field)
        ]

    path = _operation_target(operation)
    field = path.rsplit(".", maxsplit=1)[-1]
    label = (
        _review_diff_field_label(field, locale=locale)
        if operation_type == "replace_field"
        else edit.title or path
    )
    return [
        {
            **common,
            "id": f"agent-diff-{edit.id}",
            "path": path,
            "label": label,
            "before": deepcopy(before_value),
            "after": deepcopy(after_value),
        },
    ]


def _review_diff_field_label(
    field: str,
    *,
    locale: str,
    section_kind: str = "",
) -> str:
    """Return one localized, user-facing label for a canonical field diff."""

    field_label = agent_text(locale, f"diff.field.{field}")
    if section_kind and field in QUALIFIED_ITEM_DIFF_FIELDS:
        return agent_text(
            locale,
            "diff.label.item_field",
            kind=agent_text(locale, f"diff.kind.{section_kind}"),
            field=field_label,
        )
    return field_label


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
        if not isinstance(candidate, dict):
            return
        index = _bounded_index(_model_int(operation.get("index")), len(items))
        items.insert(index, deepcopy(candidate))
        return

    if operation_type == "update_item":
        item = _find_resume_item(section, str(operation.get("itemId", "")))
        patch = operation.get("patch")
        if item and isinstance(patch, dict):
            item.update(patch)
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
    edits: list[AgentResumeEditSuggestion],
    *,
    locale: str,
) -> tuple[list[dict[str, Any]], list[list[dict[str, Any]]]]:
    """Build compact model observations and complete review diffs in sequence."""

    observations: list[dict[str, Any]] = []
    diffs_by_edit: list[list[dict[str, Any]]] = []
    working_resume = deepcopy(before_resume)
    for edit in edits:
        operation = edit.operation or {}
        operation_type = operation.get("type")
        before_previous_id = ""
        before_next_id = ""
        if operation_type == "delete_section":
            section_id = _model_string(operation.get("sectionId"))
            current_sections = _resume_sections(working_resume)
            before_index = next(
                (
                    index
                    for index, candidate in enumerate(current_sections)
                    if candidate.get("id") == section_id
                ),
                None,
            )
            if before_index is not None:
                if before_index > 0:
                    before_previous_id = _model_string(
                        current_sections[before_index - 1].get("id"),
                    )
                if before_index + 1 < len(current_sections):
                    before_next_id = _model_string(
                        current_sections[before_index + 1].get("id"),
                    )
        elif operation_type == "delete_item":
            current_section = _find_resume_section(
                working_resume,
                _model_string(operation.get("sectionId")),
            )
            current_items = current_section.get("items") if current_section else None
            item_id = _model_string(operation.get("itemId"))
            if isinstance(current_items, list):
                before_index = next(
                    (
                        index
                        for index, candidate in enumerate(current_items)
                        if isinstance(candidate, dict)
                        and candidate.get("id") == item_id
                    ),
                    None,
                )
                if before_index is not None:
                    if before_index > 0:
                        previous_item = current_items[before_index - 1]
                        if isinstance(previous_item, dict):
                            before_previous_id = _model_string(previous_item.get("id"))
                    if before_index + 1 < len(current_items):
                        next_item = current_items[before_index + 1]
                        if isinstance(next_item, dict):
                            before_next_id = _model_string(next_item.get("id"))
        raw_before = deepcopy(
            _operation_diff_value(working_resume, operation, after=False),
        )
        section = _find_resume_section(
            working_resume,
            _model_string(operation.get("sectionId")),
        )
        section_kind = _model_string(section.get("kind")) if section else ""
        before_value = _complete_observation_value(
            _operation_observation_value(working_resume, operation, after=False),
        )
        if edit.operation:
            _apply_edit_operation(working_resume, edit.operation)
        raw_after = deepcopy(
            _operation_diff_value(working_resume, operation, after=True),
        )
        observations.append(
            {
                "editId": edit.id,
                "target": edit.target,
                "operationType": operation.get("type"),
                "status": edit.status,
                "before": before_value,
                "after": _complete_observation_value(
                    _operation_observation_value(
                        working_resume,
                        operation,
                        after=True,
                    ),
                ),
                "instruction": (
                    "Decide from this Observation whether the draft now satisfies "
                    "the user request. If yes, answer naturally. If not, choose "
                    "the next corrective Action."
                ),
            },
        )
        diffs_by_edit.append(
            _operation_review_diffs(
                edit=edit,
                before_value=raw_before,
                after_value=raw_after,
                locale=locale,
                section_kind=section_kind,
                before_previous_id=before_previous_id,
                before_next_id=before_next_id,
            ),
        )

    return observations, diffs_by_edit


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
