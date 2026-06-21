import re
from typing import Any

from app.schemas.agent import AgentResumeEditSuggestion

MAX_HIGHLIGHT_CHARS = 180
MAX_SUMMARY_CHARS = 360
MAX_DESCRIPTION_CHARS = 220
MAX_ITEM_HIGHLIGHTS = 5
ITEM_TEXT_FIELDS = ("title", "subtitle", "meta", "period", "description")
ITEM_DEDUPE_FIELDS = ("title", "subtitle", "meta", "period")


def draft_quality_issues(
    _before_resume: dict[str, Any],
    after_resume: dict[str, Any],
    edits: list[AgentResumeEditSuggestion],
) -> list[dict[str, Any]]:
    """Return non-blocking resume-specific quality issues from fresh edits."""

    issues: list[dict[str, Any]] = []
    seen: set[tuple[object, ...]] = set()

    for edit in edits:
        operation = edit.operation or {}
        operation_type = _string_value(operation.get("type"))
        if operation_type == "replace_field":
            _add_basic_field_issues(issues, seen, edit, operation)
            continue

        if operation_type == "insert_section":
            section: dict[str, Any] | None = _section_by_id(
                after_resume,
                _section_id(operation.get("section")),
            )
            if section is None:
                section = _dict_value(operation.get("section"))
            if section is not None:
                _add_section_issues(issues, seen, edit, operation_type, section)
                for item in _section_items(section):
                    _add_item_issues(issues, seen, edit, operation_type, item)
            continue

        if operation_type == "insert_item":
            inserted_item = _item_after_operation(after_resume, operation)
            if inserted_item is not None:
                _add_item_issues(issues, seen, edit, operation_type, inserted_item)
            continue

        if operation_type == "update_item":
            updated_item = _item_after_operation(after_resume, operation)
            if updated_item is not None:
                _add_item_issues(
                    issues,
                    seen,
                    edit,
                    operation_type,
                    updated_item,
                    touched_fields=_operation_patch_fields(operation),
                )

    return issues


def _add_basic_field_issues(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    edit: AgentResumeEditSuggestion,
    operation: dict[str, Any],
) -> None:
    if operation.get("path") != "basic.summary":
        return

    value = _string_value(operation.get("value"))
    if len(value) <= MAX_SUMMARY_CHARS:
        return

    _append_issue(
        issues,
        seen,
        {
            "code": "long_summary",
            "severity": "warning",
            "target": edit.target,
            "operationType": "replace_field",
            "field": "summary",
            "length": len(value),
            "maxLength": MAX_SUMMARY_CHARS,
        },
    )


def _add_section_issues(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    edit: AgentResumeEditSuggestion,
    operation_type: str,
    section: dict[str, Any],
) -> None:
    if _section_has_visible_content(section):
        return

    _append_issue(
        issues,
        seen,
        {
            "code": "empty_resume_section",
            "severity": "warning",
            "target": edit.target,
            "operationType": operation_type,
            "scope": "section",
        },
    )


def _add_item_issues(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    edit: AgentResumeEditSuggestion,
    operation_type: str,
    item: dict[str, Any],
    touched_fields: set[str] | None = None,
) -> None:
    if not _item_has_visible_content(item):
        _append_issue(
            issues,
            seen,
            {
                "code": "empty_resume_item",
                "severity": "warning",
                "target": edit.target,
                "operationType": operation_type,
                "scope": "item",
            },
        )

    field_values = [_string_value(item.get(field)) for field in ITEM_DEDUPE_FIELDS]
    description = _string_value(item.get("description"))
    check_description = _should_check_field(touched_fields, "description")
    if check_description and len(description) > MAX_DESCRIPTION_CHARS:
        _append_issue(
            issues,
            seen,
            {
                "code": "long_description",
                "severity": "warning",
                "target": edit.target,
                "operationType": operation_type,
                "field": "description",
                "length": len(description),
                "maxLength": MAX_DESCRIPTION_CHARS,
            },
        )
    if (
        check_description
        and description
        and _has_repeated_field_values(description, field_values)
    ):
        _append_issue(
            issues,
            seen,
            {
                "code": "duplicate_item_field_in_description",
                "severity": "warning",
                "target": edit.target,
                "operationType": operation_type,
                "field": "description",
            },
        )

    highlights = _item_highlights(item)
    check_highlights = _should_check_field(touched_fields, "highlights")
    if check_highlights and len(highlights) > MAX_ITEM_HIGHLIGHTS:
        _append_issue(
            issues,
            seen,
            {
                "code": "too_many_highlights",
                "severity": "warning",
                "target": edit.target,
                "operationType": operation_type,
                "field": "highlights",
                "count": len(highlights),
                "maxCount": MAX_ITEM_HIGHLIGHTS,
            },
        )

    if not check_highlights:
        return

    for index, highlight in enumerate(highlights):
        if len(highlight) > MAX_HIGHLIGHT_CHARS:
            _append_issue(
                issues,
                seen,
                {
                    "code": "long_highlight",
                    "severity": "warning",
                    "target": edit.target,
                    "operationType": operation_type,
                    "field": "highlights",
                    "index": index,
                    "length": len(highlight),
                    "maxLength": MAX_HIGHLIGHT_CHARS,
                },
            )
        if _has_repeated_field_values(highlight, field_values):
            _append_issue(
                issues,
                seen,
                {
                    "code": "duplicate_item_field_in_highlight",
                    "severity": "warning",
                    "target": edit.target,
                    "operationType": operation_type,
                    "field": "highlights",
                    "index": index,
                },
            )


def _operation_patch_fields(operation: dict[str, Any]) -> set[str]:
    patch = operation.get("patch")
    if not isinstance(patch, dict):
        return set()

    return {key for key in patch if isinstance(key, str)}


def _should_check_field(touched_fields: set[str] | None, field: str) -> bool:
    return touched_fields is None or field in touched_fields


def _append_issue(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    issue: dict[str, Any],
) -> None:
    key = (
        issue.get("code"),
        issue.get("target"),
        issue.get("field"),
        issue.get("index"),
    )
    if key in seen:
        return

    seen.add(key)
    issues.append(issue)


def _item_after_operation(
    resume: dict[str, Any],
    operation: dict[str, Any],
) -> dict[str, Any] | None:
    section = _section_by_id(resume, _string_value(operation.get("sectionId")))
    if section is None:
        return None

    operation_type = _string_value(operation.get("type"))
    if operation_type == "insert_item":
        item_id = _item_id(operation.get("item"))
    else:
        item_id = _string_value(operation.get("itemId"))

    return _item_by_id(section, item_id)


def _section_by_id(
    resume: dict[str, Any],
    section_id: str,
) -> dict[str, Any] | None:
    if not section_id:
        return None

    for section in _resume_sections(resume):
        if section.get("id") == section_id:
            return section

    return None


def _item_by_id(
    section: dict[str, Any],
    item_id: str,
) -> dict[str, Any] | None:
    if not item_id:
        return None

    for item in _section_items(section):
        if item.get("id") == item_id:
            return item

    return None


def _resume_sections(resume: dict[str, Any]) -> list[dict[str, Any]]:
    sections = resume.get("sections")
    if not isinstance(sections, list):
        return []

    return [section for section in sections if isinstance(section, dict)]


def _section_items(section: dict[str, Any]) -> list[dict[str, Any]]:
    items = section.get("items")
    if not isinstance(items, list):
        return []

    return [item for item in items if isinstance(item, dict)]


def _section_has_visible_content(section: dict[str, Any]) -> bool:
    if _string_value(section.get("customTitle")):
        return True

    return any(_item_has_visible_content(item) for item in _section_items(section))


def _item_has_visible_content(item: dict[str, Any]) -> bool:
    for field in ITEM_TEXT_FIELDS:
        if _string_value(item.get(field)):
            return True

    return bool(_item_highlights(item))


def _item_highlights(item: dict[str, Any]) -> list[str]:
    highlights = item.get("highlights")
    if not isinstance(highlights, list):
        return []

    values = [_string_value(highlight) for highlight in highlights]
    return [highlight for highlight in values if highlight]


def _section_id(value: object) -> str:
    data = _dict_value(value)
    return _string_value(data.get("id")) if data is not None else ""


def _item_id(value: object) -> str:
    data = _dict_value(value)
    return _string_value(data.get("id")) if data is not None else ""


def _dict_value(value: object) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _string_value(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _duplicate_key(value: str) -> str:
    return re.sub(r"\W+", "", value.casefold())


def _has_repeated_field_values(value: str, field_values: list[str]) -> bool:
    value_key = _duplicate_key(value)
    matches = 0
    for field_value in field_values:
        field_key = _duplicate_key(field_value)
        if len(field_key) >= 3 and field_key in value_key:
            matches += 1

    return matches >= 2
