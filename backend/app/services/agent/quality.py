import re
from difflib import SequenceMatcher
from typing import Any

from app.schemas.agent import AgentResumeEditSuggestion

MAX_HIGHLIGHT_CHARS = 180
MAX_SUMMARY_CHARS = 360
MAX_DESCRIPTION_CHARS = 220
MAX_ITEM_HIGHLIGHTS = 5
ITEM_TEXT_FIELDS = ("title", "subtitle", "meta", "period", "description")
ITEM_DEDUPE_FIELDS = ("title", "subtitle", "meta", "period")
BLOCKING_QUALITY_SEVERITY = "error"
OPEN_ENDED_PERIOD_MARKERS = frozenset(
    {"present", "current", "now", "ongoing", "至今", "现在"},
)
OPEN_ENDED_PERIOD_VALUE = 9999 * 12 + 12
PERIOD_RANGE_PATTERN = re.compile(
    r"^\s*(?P<start>.+?)\s*(?:[–—~]|\s+-\s+|\s+to\s+|至)\s*(?P<end>.+?)\s*$",
    re.IGNORECASE,
)
SEASON_MONTHS = {
    "spring": 3,
    "summer": 6,
    "autumn": 9,
    "fall": 9,
    "winter": 12,
}
MONTH_NAME_NUMBERS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
MIN_SEMANTIC_DUPLICATE_CHARS = 32
SEMANTIC_DUPLICATE_RATIO = 0.84
PRESENT_ACTION_VERBS = frozenset(
    {
        "build",
        "collaborate",
        "create",
        "deliver",
        "design",
        "develop",
        "drive",
        "implement",
        "improve",
        "lead",
        "manage",
        "optimize",
        "own",
        "support",
    },
)
TARGET_REQUIREMENT_KEYS = (
    "requirements",
    "requiredKeywords",
    "keywords",
    "missingKeywords",
)
TARGET_STOP_WORDS = frozenset(
    {
        "a",
        "ability",
        "an",
        "and",
        "experience",
        "in",
        "knowledge",
        "of",
        "preferred",
        "proficiency",
        "required",
        "skills",
        "strong",
        "the",
        "to",
        "with",
        "优先",
        "具备",
        "掌握",
        "熟悉",
        "经验",
        "能力",
    },
)


def draft_quality_issues(
    after_resume: dict[str, Any],
    edits: list[AgentResumeEditSuggestion],
    *,
    target_context: object | None = None,
) -> list[dict[str, Any]]:
    """Return deterministic errors and advisory warnings for a candidate draft."""

    issues: list[dict[str, Any]] = []
    seen: set[tuple[object, ...]] = set()

    for operation_index, edit in enumerate(edits, start=1):
        operation = edit.operation or {}
        operation_type = _string_value(operation.get("type"))
        if operation_type == "replace_field":
            _add_basic_field_issues(
                issues,
                seen,
                edit,
                operation,
                operation_index,
            )
            continue

        if operation_type == "insert_section":
            section: dict[str, Any] | None = _section_by_id(
                after_resume,
                _section_id(operation.get("section")),
            )
            if section is None:
                section = _dict_value(operation.get("section"))
            if section is not None:
                _add_section_issues(
                    issues,
                    seen,
                    edit,
                    operation_type,
                    section,
                    operation_index,
                )
                for item in _section_items(section):
                    _add_item_issues(
                        issues,
                        seen,
                        edit,
                        operation_type,
                        item,
                        operation_index,
                    )
            continue

        if operation_type == "insert_item":
            inserted_item = _item_after_operation(after_resume, operation)
            if inserted_item is not None:
                _add_item_issues(
                    issues,
                    seen,
                    edit,
                    operation_type,
                    inserted_item,
                    operation_index,
                )
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
                    operation_index,
                    touched_fields=_operation_patch_fields(operation),
                )

    _add_full_resume_period_issues(issues, seen, after_resume)
    _add_full_resume_duplicate_issues(issues, seen, after_resume)
    _add_full_resume_language_issues(issues, seen, after_resume)
    _add_full_resume_tense_issues(issues, seen, after_resume)
    _add_target_coverage_issues(
        issues,
        seen,
        after_resume,
        target_context=target_context,
    )
    return issues


def normalization_loss_issues(
    before_resume: dict[str, Any],
    entries: object,
    edits: list[AgentResumeEditSuggestion],
) -> list[dict[str, Any]]:
    """Report non-empty item content discarded while normalizing model JSON.

    Sanitization remains defensive, but silently publishing a partial operation
    would violate the Agent's atomic edit contract. Empty input still represents
    an intentional field clear and is therefore not reported.
    """

    if not isinstance(entries, list) or len(entries) != len(edits):
        return []

    issues: list[dict[str, Any]] = []
    for operation_index, (entry, edit) in enumerate(
        zip(entries, edits, strict=True),
        start=1,
    ):
        raw_operation = entry.get("operation") if isinstance(entry, dict) else None
        normalized_operation = edit.operation
        if not isinstance(raw_operation, dict) or not isinstance(
            normalized_operation,
            dict,
        ):
            continue

        operation_type = _string_value(normalized_operation.get("type"))
        if operation_type == "update_item":
            base_section = _section_by_id(
                before_resume,
                _string_value(normalized_operation.get("sectionId")),
            )
            base_item = (
                _item_by_id(
                    base_section,
                    _string_value(normalized_operation.get("itemId")),
                )
                if base_section is not None
                else None
            )
            _add_normalization_loss_for_item(
                issues,
                raw_operation.get("patch"),
                normalized_operation.get("patch"),
                edit,
                operation_type,
                operation_index,
                base_item=base_item,
            )
        elif operation_type == "insert_item":
            _add_normalization_loss_for_item(
                issues,
                raw_operation.get("item"),
                normalized_operation.get("item"),
                edit,
                operation_type,
                operation_index,
            )
        elif operation_type == "insert_section":
            raw_section = _dict_value(raw_operation.get("section"))
            normalized_section = _dict_value(normalized_operation.get("section"))
            if raw_section is None or normalized_section is None:
                continue
            raw_items = raw_section.get("items")
            normalized_items = normalized_section.get("items")
            if not isinstance(raw_items, list) or not isinstance(
                normalized_items,
                list,
            ):
                continue
            if len(raw_items) != len(normalized_items):
                issues.append(
                    {
                        "code": "normalized_section_items_were_dropped",
                        "severity": BLOCKING_QUALITY_SEVERITY,
                        "target": edit.target,
                        "operationType": operation_type,
                        "operationIndex": operation_index,
                        "field": "items",
                    },
                )
                continue
            for raw_item, normalized_item in zip(
                raw_items,
                normalized_items,
                strict=True,
            ):
                _add_normalization_loss_for_item(
                    issues,
                    raw_item,
                    normalized_item,
                    edit,
                    operation_type,
                    operation_index,
                )

    return issues


def blocking_quality_issues(
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return deterministic issues that must reject the complete edit batch."""

    return [
        issue for issue in issues if issue.get("severity") == BLOCKING_QUALITY_SEVERITY
    ]


def _add_basic_field_issues(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    edit: AgentResumeEditSuggestion,
    operation: dict[str, Any],
    operation_index: int,
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
            "operationIndex": operation_index,
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
    operation_index: int,
) -> None:
    if _section_has_visible_content(section):
        return

    _append_issue(
        issues,
        seen,
        {
            "code": "empty_resume_section",
            "severity": BLOCKING_QUALITY_SEVERITY,
            "target": edit.target,
            "operationType": operation_type,
            "operationIndex": operation_index,
            "scope": "section",
        },
    )


def _add_full_resume_period_issues(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    resume: dict[str, Any],
) -> None:
    """Validate every candidate period instead of only fields touched this turn.

    Date validation is intentionally conservative: accepted forms are parsed
    deterministically, while ambiguous prose is rejected instead of being
    silently reinterpreted and potentially corrupting the timeline.
    """

    for section in _resume_sections(resume):
        section_id = _string_value(section.get("id"))
        previous_item_id = ""
        previous_period: tuple[int, int] | None = None
        for item in _section_items(section):
            period = _string_value(item.get("period"))
            if not period:
                continue

            item_id = _string_value(item.get("id"))
            parsed_period = _parse_period(period)
            if parsed_period is None:
                _append_issue(
                    issues,
                    seen,
                    {
                        "code": "invalid_item_period",
                        "severity": BLOCKING_QUALITY_SEVERITY,
                        "target": _item_field_target(section_id, item_id, "period"),
                        "scope": "resume",
                        "field": "period",
                        "sectionId": section_id,
                        "itemId": item_id,
                    },
                )
                continue

            if parsed_period[0] > parsed_period[1]:
                _append_issue(
                    issues,
                    seen,
                    {
                        "code": "inverted_item_period",
                        "severity": BLOCKING_QUALITY_SEVERITY,
                        "target": _item_field_target(section_id, item_id, "period"),
                        "scope": "resume",
                        "field": "period",
                        "sectionId": section_id,
                        "itemId": item_id,
                    },
                )
                continue

            # Resume sections conventionally list the most recent experience
            # first. Compare parsed endpoints so formatting differences do not
            # affect ordering and undated items remain outside this rule.
            if previous_period is not None and _period_sort_key(
                previous_period
            ) < _period_sort_key(parsed_period):
                _append_issue(
                    issues,
                    seen,
                    {
                        "code": "resume_items_not_reverse_chronological",
                        "severity": BLOCKING_QUALITY_SEVERITY,
                        "target": (
                            f"sections.{section_id}" if section_id else "sections"
                        ),
                        "scope": "resume",
                        "field": "items",
                        "sectionId": section_id,
                        "itemId": item_id,
                        "previousItemId": previous_item_id,
                    },
                )
            previous_period = parsed_period
            previous_item_id = item_id


def _add_full_resume_duplicate_issues(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    resume: dict[str, Any],
) -> None:
    """Warn when separate resume items make substantially the same claim.

    This deliberately compares only descriptions and highlights from different
    items. Titles, short labels, and fields within one item often repeat by
    design and are handled by the existing edit-local checks.
    """

    content: list[tuple[str, str, str, str]] = []
    for section in _resume_sections(resume):
        section_id = _string_value(section.get("id"))
        for item in _section_items(section):
            item_id = _string_value(item.get("id"))
            description = _string_value(item.get("description"))
            if _is_substantive_duplicate_candidate(description):
                content.append(
                    (
                        _item_field_target(section_id, item_id, "description"),
                        section_id,
                        item_id,
                        description,
                    ),
                )
            for index, highlight in enumerate(_item_highlights(item)):
                if not _is_substantive_duplicate_candidate(highlight):
                    continue
                content.append(
                    (
                        _item_field_target(
                            section_id,
                            item_id,
                            f"highlights.{index}",
                        ),
                        section_id,
                        item_id,
                        highlight,
                    ),
                )

    for current_index, current in enumerate(content):
        current_target, section_id, item_id, current_text = current
        for previous in content[:current_index]:
            previous_target, previous_section_id, previous_item_id, previous_text = (
                previous
            )
            if (
                section_id,
                item_id,
            ) == (
                previous_section_id,
                previous_item_id,
            ):
                continue
            if not _texts_are_semantically_duplicate(previous_text, current_text):
                continue
            _append_issue(
                issues,
                seen,
                {
                    "code": "semantically_duplicate_resume_content",
                    "severity": "warning",
                    "target": current_target,
                    "scope": "resume",
                    "sectionId": section_id,
                    "itemId": item_id,
                    "duplicateOf": previous_target,
                },
            )
            break


def _add_full_resume_language_issues(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    resume: dict[str, Any],
) -> None:
    """Flag only clear sentence-level Chinese/English mixing.

    Technical terms embedded in otherwise Chinese text are common and should
    not trigger this warning, so short labels and ambiguous mixed units remain
    unclassified.
    """

    language_counts = {"en": 0, "zh": 0}
    for text in _resume_narrative_texts(resume):
        language = _substantive_language(text)
        if language is not None:
            language_counts[language] += 1

    if not all(language_counts.values()):
        return

    _append_issue(
        issues,
        seen,
        {
            "code": "mixed_resume_languages",
            "severity": "warning",
            "target": "resume",
            "scope": "resume",
            "languageCounts": language_counts,
        },
    )


def _add_full_resume_tense_issues(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    resume: dict[str, Any],
) -> None:
    """Warn about present-tense English bullets attached to an ended role.

    Current roles legitimately mix completed achievements and ongoing duties.
    Restricting this rule to ended periods keeps the signal deterministic and
    avoids treating stylistic verb choices as structural failures.
    """

    for section in _resume_sections(resume):
        section_id = _string_value(section.get("id"))
        for item in _section_items(section):
            parsed_period = _parse_period(_string_value(item.get("period")))
            if (
                parsed_period is None
                or parsed_period[0] > parsed_period[1]
                or parsed_period[1] == OPEN_ENDED_PERIOD_VALUE
            ):
                continue

            present_indexes = [
                index
                for index, highlight in enumerate(_item_highlights(item))
                if _starts_with_present_action_verb(highlight)
            ]
            if not present_indexes:
                continue

            item_id = _string_value(item.get("id"))
            _append_issue(
                issues,
                seen,
                {
                    "code": "inconsistent_item_tense",
                    "severity": "warning",
                    "target": _item_field_target(
                        section_id,
                        item_id,
                        "highlights",
                    ),
                    "scope": "resume",
                    "field": "highlights",
                    "sectionId": section_id,
                    "itemId": item_id,
                    "indexes": present_indexes,
                },
            )


def _add_target_coverage_issues(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    resume: dict[str, Any],
    *,
    target_context: object | None,
) -> None:
    """Compare explicit target requirements with the complete candidate resume."""

    requirements = _target_requirements(target_context)
    if not requirements:
        return

    resume_text = " ".join(_resume_searchable_texts(resume))
    missing_indexes = [
        index
        for index, requirement in enumerate(requirements)
        if not _requirement_is_covered(requirement, resume_text)
    ]
    if not missing_indexes:
        return

    _append_issue(
        issues,
        seen,
        {
            "code": "target_requirements_not_covered",
            "severity": "warning",
            "target": "resume",
            "scope": "target",
            "requirementCount": len(requirements),
            "coveredCount": len(requirements) - len(missing_indexes),
            "missingRequirementIndexes": missing_indexes,
        },
    )


def _add_item_issues(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    edit: AgentResumeEditSuggestion,
    operation_type: str,
    item: dict[str, Any],
    operation_index: int,
    touched_fields: set[str] | None = None,
) -> None:
    if not _item_has_visible_content(item):
        _append_issue(
            issues,
            seen,
            {
                "code": "empty_resume_item",
                "severity": BLOCKING_QUALITY_SEVERITY,
                "target": edit.target,
                "operationType": operation_type,
                "operationIndex": operation_index,
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
                "operationIndex": operation_index,
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
                "severity": BLOCKING_QUALITY_SEVERITY,
                "target": edit.target,
                "operationType": operation_type,
                "operationIndex": operation_index,
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
                "operationIndex": operation_index,
                "field": "highlights",
                "count": len(highlights),
                "maxCount": MAX_ITEM_HIGHLIGHTS,
            },
        )

    if not check_highlights:
        return

    highlight_keys: dict[str, int] = {}
    for index, highlight in enumerate(highlights):
        highlight_key = _duplicate_key(highlight)
        previous_index = highlight_keys.get(highlight_key)
        if highlight_key and previous_index is not None:
            _append_issue(
                issues,
                seen,
                {
                    "code": "duplicate_highlight",
                    "severity": BLOCKING_QUALITY_SEVERITY,
                    "target": edit.target,
                    "operationType": operation_type,
                    "operationIndex": operation_index,
                    "field": "highlights",
                    "index": index,
                    "duplicateOf": previous_index,
                },
            )
        else:
            highlight_keys[highlight_key] = index

        if len(highlight) > MAX_HIGHLIGHT_CHARS:
            _append_issue(
                issues,
                seen,
                {
                    "code": "long_highlight",
                    "severity": "warning",
                    "target": edit.target,
                    "operationType": operation_type,
                    "operationIndex": operation_index,
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
                    "severity": BLOCKING_QUALITY_SEVERITY,
                    "target": edit.target,
                    "operationType": operation_type,
                    "operationIndex": operation_index,
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


def _add_normalization_loss_for_item(
    issues: list[dict[str, Any]],
    raw_value: object,
    normalized_value: object,
    edit: AgentResumeEditSuggestion,
    operation_type: str,
    operation_index: int,
    *,
    base_item: dict[str, Any] | None = None,
) -> None:
    raw_item = _dict_value(raw_value)
    normalized_item = _dict_value(normalized_value)
    if raw_item is None or normalized_item is None:
        return

    for field in ITEM_TEXT_FIELDS:
        raw_text = _string_value(raw_item.get(field))
        normalized_text = _string_value(normalized_item.get(field))
        if (
            raw_text
            and not normalized_text
            and not _same_text(raw_text, _string_value((base_item or {}).get(field)))
        ):
            issues.append(
                {
                    "code": "normalized_item_field_was_dropped",
                    "severity": BLOCKING_QUALITY_SEVERITY,
                    "target": edit.target,
                    "operationType": operation_type,
                    "operationIndex": operation_index,
                    "field": field,
                },
            )

    raw_highlights = _string_list(raw_item.get("highlights"))
    normalized_highlights = _string_list(normalized_item.get("highlights"))
    base_highlights = _string_list((base_item or {}).get("highlights"))
    if (
        raw_highlights
        and len(normalized_highlights) < len(raw_highlights)
        and not _same_string_list(raw_highlights, base_highlights)
    ):
        issues.append(
            {
                "code": "normalized_item_highlights_were_dropped",
                "severity": BLOCKING_QUALITY_SEVERITY,
                "target": edit.target,
                "operationType": operation_type,
                "operationIndex": operation_index,
                "field": "highlights",
            },
        )


def _append_issue(
    issues: list[dict[str, Any]],
    seen: set[tuple[object, ...]],
    issue: dict[str, Any],
) -> None:
    key = (
        issue.get("code"),
        issue.get("target"),
        issue.get("operationIndex"),
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


def _parse_period(value: str) -> tuple[int, int] | None:
    # Chinese resumes commonly concatenate the open-ended marker without a
    # separator (for example, "2024年1月至今").
    open_ended_match = re.fullmatch(r"(?P<start>.+?)\s*至今", value.strip())
    if open_ended_match is not None:
        start_text = re.sub(
            r"\s*[-–—~]\s*$",
            "",
            open_ended_match.group("start"),
        )
        start = _parse_period_point(start_text)
        return (start, OPEN_ENDED_PERIOD_VALUE) if start is not None else None

    range_match = PERIOD_RANGE_PATTERN.fullmatch(value)
    if range_match is None:
        point = _parse_period_point(value)
        return (point, point) if point is not None else None

    start = _parse_period_point(range_match.group("start"))
    end = _parse_period_point(range_match.group("end"))
    if start is None or end is None:
        return None
    return start, end


def _parse_period_point(value: str) -> int | None:
    normalized = " ".join(value.casefold().split())
    if normalized in OPEN_ENDED_PERIOD_MARKERS:
        return OPEN_ENDED_PERIOD_VALUE

    season_match = re.fullmatch(
        r"(spring|summer|autumn|fall|winter)\s+(\d{4})",
        normalized,
    )
    if season_match is not None:
        return int(season_match.group(2)) * 12 + SEASON_MONTHS[season_match.group(1)]

    month_name_match = re.fullmatch(r"([a-z]+)\.?\s+(\d{4})", normalized)
    if month_name_match is not None:
        month = MONTH_NAME_NUMBERS.get(month_name_match.group(1)[:3])
        year = int(month_name_match.group(2))
        if month is None or year < 1900:
            return None
        return year * 12 + month

    year_month_match = re.fullmatch(
        r"(?P<year>\d{4})(?:[./-](?P<month>\d{1,2}))?",
        normalized,
    )
    if year_month_match is None:
        year_month_match = re.fullmatch(
            r"(?P<year>\d{4})年(?:(?P<month>\d{1,2})月)?",
            normalized,
        )
    if year_month_match is None:
        month_year_match = re.fullmatch(
            r"(?P<month>\d{1,2})/(?P<year>\d{4})",
            normalized,
        )
        if month_year_match is None:
            return None
        year_month_match = month_year_match

    year = int(year_month_match.group("year"))
    month_text = year_month_match.group("month")
    month = int(month_text) if month_text is not None else 1
    if year < 1900 or month < 1 or month > 12:
        return None
    return year * 12 + month


def _period_sort_key(period: tuple[int, int]) -> tuple[int, int]:
    return period[1], period[0]


def _item_field_target(section_id: str, item_id: str, field: str) -> str:
    if section_id and item_id:
        return f"sections.{section_id}.items.{item_id}.{field}"
    return field


def _resume_narrative_texts(resume: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    basic = _dict_value(resume.get("basic"))
    if basic is not None:
        summary = _string_value(basic.get("summary"))
        if summary:
            texts.append(summary)
    for section in _resume_sections(resume):
        for item in _section_items(section):
            description = _string_value(item.get("description"))
            if description:
                texts.append(description)
            texts.extend(_item_highlights(item))
    return texts


def _resume_searchable_texts(resume: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    basic = _dict_value(resume.get("basic"))
    if basic is not None:
        for field in ("headline", "summary"):
            value = _string_value(basic.get(field))
            if value:
                texts.append(value)
        custom_fields = basic.get("customFields")
        if isinstance(custom_fields, list):
            for custom_field in custom_fields:
                data = _dict_value(custom_field)
                if data is not None:
                    value = _string_value(data.get("value"))
                    if value:
                        texts.append(value)

    for section in _resume_sections(resume):
        custom_title = _string_value(section.get("customTitle"))
        if custom_title:
            texts.append(custom_title)
        for item in _section_items(section):
            texts.extend(
                value
                for field in ITEM_TEXT_FIELDS
                if (value := _string_value(item.get(field)))
            )
            texts.extend(_item_highlights(item))
    return texts


def _substantive_language(value: str) -> str | None:
    cjk_count = len(re.findall(r"[\u3400-\u9fff]", value))
    latin_words = re.findall(r"[A-Za-z]+", value)
    if cjk_count >= 8 and cjk_count >= len(latin_words) * 2:
        return "zh"
    if len(latin_words) >= 6 and cjk_count <= 2:
        return "en"
    return None


def _starts_with_present_action_verb(value: str) -> bool:
    first_word = re.search(r"[A-Za-z]+", value)
    return (
        first_word is not None
        and first_word.group(0).casefold() in PRESENT_ACTION_VERBS
    )


def _target_requirements(target_context: object | None) -> list[str]:
    if target_context is None:
        return []

    values: list[str] = []
    if isinstance(target_context, dict):
        for key in TARGET_REQUIREMENT_KEYS:
            values.extend(_requirement_values(target_context.get(key)))
    else:
        values.extend(_requirement_values(target_context))

    requirements: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _duplicate_key(value)
        if not key or key in seen:
            continue
        seen.add(key)
        requirements.append(value)
    return requirements


def _requirement_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [
            item.strip(" \t-•")
            for item in re.split(r"[\n;；]+", value)
            if item.strip(" \t-•")
        ]
    if not isinstance(value, (list, tuple, set)):
        return []
    return [text for item in value if isinstance(item, str) and (text := item.strip())]


def _requirement_is_covered(requirement: str, resume_text: str) -> bool:
    # CJK keywords are not whitespace-delimited, while Latin requirements must
    # respect token boundaries (for example, Python must not match Pythonic).
    requirement_key = _duplicate_key(requirement)
    if (
        re.search(r"[\u3400-\u9fff]", requirement)
        and requirement_key
        and requirement_key in _duplicate_key(resume_text)
    ):
        return True

    requirement_phrase = _semantic_duplicate_key(requirement)
    resume_phrase = _semantic_duplicate_key(resume_text)
    if requirement_phrase and f" {requirement_phrase} " in f" {resume_phrase} ":
        return True

    requirement_tokens = {
        token
        for token in re.findall(
            r"[a-z0-9+#.]+|[\u3400-\u9fff]{2,}",
            requirement.casefold(),
        )
        if token not in TARGET_STOP_WORDS
    }
    if not requirement_tokens:
        return False
    resume_tokens = set(
        re.findall(
            r"[a-z0-9+#.]+|[\u3400-\u9fff]{2,}",
            resume_text.casefold(),
        ),
    )
    covered_count = len(requirement_tokens.intersection(resume_tokens))
    return covered_count / len(requirement_tokens) >= 0.67


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []

    return [text for item in value if (text := _string_value(item))]


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


def _semantic_duplicate_key(value: str) -> str:
    return " ".join(re.findall(r"[\w]+", value.casefold()))


def _is_substantive_duplicate_candidate(value: str) -> bool:
    return len(_duplicate_key(value)) >= MIN_SEMANTIC_DUPLICATE_CHARS


def _texts_are_semantically_duplicate(first: str, second: str) -> bool:
    first_key = _semantic_duplicate_key(first)
    second_key = _semantic_duplicate_key(second)
    if not first_key or not second_key:
        return False
    return (
        SequenceMatcher(None, first_key, second_key).ratio() >= SEMANTIC_DUPLICATE_RATIO
    )


def _same_text(first: str, second: str) -> bool:
    return bool(first and second) and _duplicate_key(first) == _duplicate_key(second)


def _same_string_list(first: list[str], second: list[str]) -> bool:
    return [_duplicate_key(value) for value in first] == [
        _duplicate_key(value) for value in second
    ]


def _has_repeated_field_values(value: str, field_values: list[str]) -> bool:
    value_key = _duplicate_key(value)
    field_keys = {
        field_key
        for field_value in field_values
        if len(field_key := _duplicate_key(field_value)) >= 3
    }
    return sum(field_key in value_key for field_key in field_keys) >= 2
