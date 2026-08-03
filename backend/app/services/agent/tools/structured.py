from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import uuid4

from app.schemas.agent import AgentDraftState, AgentResumeEditSuggestion

from ..editing import _string_list
from ..localization import agent_text

EDIT_ENTRY = dict[str, Any]
ITEM_TEXT_FIELDS = ("title", "subtitle", "meta", "period", "description")


def string_arg(args: dict[str, Any], key: str) -> str:
    """Return a stripped string argument."""

    value = args.get(key)
    return value.strip() if isinstance(value, str) else ""


def int_arg(args: dict[str, Any], key: str) -> int | None:
    """Return an integer argument without accepting bools."""

    value = args.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def resume_sections(resume: dict[str, Any]) -> list[dict[str, Any]]:
    """Return section dictionaries from a resume payload."""

    sections = resume.get("sections")
    if not isinstance(sections, list):
        return []

    return [section for section in sections if isinstance(section, dict)]


def find_section(
    resume: dict[str, Any],
    section_id: str,
) -> dict[str, Any] | None:
    """Return one section by id."""

    return next(
        (
            section
            for section in resume_sections(resume)
            if section.get("id") == section_id
        ),
        None,
    )


def section_items(section: dict[str, Any]) -> list[dict[str, Any]]:
    """Return item dictionaries from one section."""

    items = section.get("items")
    if not isinstance(items, list):
        return []

    return [item for item in items if isinstance(item, dict)]


def find_item(
    section: dict[str, Any],
    item_id: str,
) -> dict[str, Any] | None:
    """Return one item by id from a section."""

    return next(
        (item for item in section_items(section) if item.get("id") == item_id),
        None,
    )


def compact_text(value: object, limit: int = 220) -> str:
    """Return a compact text value for tool observations."""

    if not isinstance(value, str):
        return ""

    text = " ".join(value.split())
    return text if len(text) <= limit else f"{text[: limit - 3]}..."


def item_snapshot(item: dict[str, Any]) -> dict[str, Any]:
    """Return the fields a model needs to target or rewrite an item."""

    snapshot: dict[str, Any] = {"id": str(item.get("id") or "")}
    for field in ITEM_TEXT_FIELDS:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            snapshot[field] = compact_text(value)

    highlights = _string_list(item.get("highlights"))
    if highlights:
        snapshot["highlights"] = [
            compact_text(highlight) for highlight in highlights[:5]
        ]

    return snapshot


def section_snapshot(
    section: dict[str, Any],
    *,
    include_items: bool,
) -> dict[str, Any]:
    """Return a compact section snapshot."""

    snapshot = {
        "id": str(section.get("id") or ""),
        "kind": str(section.get("kind") or ""),
        "customTitle": str(section.get("customTitle") or ""),
        "layout": str(section.get("layout") or ""),
        "itemCount": len(section_items(section)),
    }
    if include_items:
        snapshot["items"] = [item_snapshot(item) for item in section_items(section)[:8]]

    return snapshot


def lookup_resume(resume: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    """Find resume sections/items without requiring a full resume analysis."""

    section_id = string_arg(args, "sectionId")
    item_id = string_arg(args, "itemId")
    section_kind = string_arg(args, "sectionKind")
    query = string_arg(args, "query").lower()
    include_items = args.get("includeItems") is not False

    matched_sections: list[dict[str, Any]] = []
    matched_items: list[dict[str, Any]] = []

    for section in resume_sections(resume):
        if section_id and section.get("id") != section_id:
            continue
        if section_kind and section.get("kind") != section_kind:
            continue

        section_text = " ".join(
            compact_text(section.get(key)).lower()
            for key in ("id", "kind", "customTitle")
        )
        section_matches = not query or query in section_text

        item_matches: list[dict[str, Any]] = []
        for item in section_items(section):
            if item_id and item.get("id") != item_id:
                continue

            item_text = " ".join(
                [
                    compact_text(item.get(key)).lower()
                    for key in ("id", *ITEM_TEXT_FIELDS)
                ]
                + [
                    compact_text(highlight).lower()
                    for highlight in _string_list(item.get("highlights"))
                ]
            )
            if query and query not in item_text and not section_matches:
                continue

            item_matches.append(item)

        if section_matches or item_matches:
            matched_sections.append(
                section_snapshot(
                    {
                        **section,
                        "items": item_matches if item_matches else section.get("items"),
                    },
                    include_items=include_items,
                ),
            )
            for item in item_matches[:8]:
                matched_items.append(
                    {
                        "sectionId": str(section.get("id") or ""),
                        "sectionKind": str(section.get("kind") or ""),
                        **item_snapshot(item),
                    },
                )

    return {
        "sectionCount": len(matched_sections),
        "itemCount": len(matched_items),
        "sections": matched_sections[:8],
        "items": matched_items[:12],
    }


def draft_diff_summary(
    draft_state: AgentDraftState | None,
    edits: list[AgentResumeEditSuggestion],
) -> dict[str, Any]:
    """Return the current draft changes that follow-up prompts can reference."""

    if edits:
        edit_summaries = [
            {
                "index": index,
                "id": edit.id,
                "title": edit.title,
                "target": edit.target,
                "replacement": compact_text(edit.replacement),
                "operationType": edit.operation.get("type")
                if isinstance(edit.operation, dict)
                else None,
            }
            for index, edit in enumerate(edits[:12], start=1)
        ]
        return {
            "status": "pending",
            "editCount": len(edits),
            "edits": edit_summaries,
            "referenceMap": _draft_reference_map(edit_summaries),
        }

    if not draft_state:
        return {
            "status": "none",
            "editCount": 0,
            "edits": [],
            "diffs": [],
            "referenceMap": [],
        }

    edit_summaries = [
        {
            "index": index,
            "id": str(edit.get("id") or ""),
            "title": compact_text(edit.get("title")),
            "target": compact_text(edit.get("target")),
            "replacement": compact_text(edit.get("replacement")),
            "operationType": _operation_type(edit.get("operation")),
            "status": compact_text(edit.get("status")),
        }
        for index, edit in enumerate(draft_state.edits[:12], start=1)
        if isinstance(edit, dict)
    ]

    return {
        "id": draft_state.id,
        "status": draft_state.status,
        "editCount": draft_state.edit_count,
        "edits": edit_summaries,
        "diffs": [
            {
                "index": index,
                "id": str(diff.get("id") or diff.get("operationId") or ""),
                "operationId": str(diff.get("operationId") or ""),
                "path": compact_text(diff.get("path")),
                "label": compact_text(diff.get("label") or diff.get("title")),
                "before": compact_text(diff.get("before")),
                "after": compact_text(diff.get("after")),
            }
            for index, diff in enumerate(draft_state.diffs[:12], start=1)
            if isinstance(diff, dict)
        ],
        "referenceMap": _draft_reference_map(edit_summaries),
    }


def _draft_reference_map(edits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return compact index-to-target hints for follow-up draft references."""

    return [
        {
            "index": edit.get("index"),
            "editId": edit.get("id"),
            "target": edit.get("target"),
            "operationType": edit.get("operationType"),
        }
        for edit in edits
    ]


def _operation_type(value: object) -> str | None:
    if not isinstance(value, dict) or not value.get("type"):
        return None
    return str(value.get("type"))


def move_item_entries(
    resume: dict[str, Any],
    args: dict[str, Any],
    *,
    locale: str,
) -> tuple[list[EDIT_ENTRY], str | None]:
    """Build edit entries for moving one item across or within sections."""

    from_section_id = string_arg(args, "fromSectionId")
    to_section_id = string_arg(args, "toSectionId")
    item_id = string_arg(args, "itemId")
    reason = string_arg(args, "reason") or agent_text(
        locale,
        "structured.reason.move_item",
    )

    from_section = find_section(resume, from_section_id)
    to_section = find_section(resume, to_section_id)
    if not from_section or not to_section:
        return [], agent_text(locale, "error.move_item_missing_sections")

    item = find_item(from_section, item_id)
    if not item:
        return [], agent_text(locale, "error.move_item_missing_item")

    index = int_arg(args, "index")
    if from_section_id == to_section_id:
        item_ids = [
            str(entry.get("id"))
            for entry in section_items(from_section)
            if isinstance(entry.get("id"), str) and entry.get("id") != item_id
        ]
        insert_index = (
            len(item_ids) if index is None else max(0, min(index, len(item_ids)))
        )
        item_ids.insert(insert_index, item_id)
        return [
            edit_entry(
                agent_text(locale, "structured.title.move_item"),
                f"sections.{from_section_id}.items",
                reason,
                {
                    "type": "reorder_items",
                    "sectionId": from_section_id,
                    "itemIds": item_ids,
                },
            ),
        ], None

    insert_operation: dict[str, Any] = {
        "type": "insert_item",
        "sectionId": to_section_id,
        "item": deepcopy(item),
    }
    if index is not None:
        insert_operation["index"] = index

    return [
        edit_entry(
            agent_text(locale, "structured.title.move_item_to_section"),
            f"sections.{to_section_id}.items.{item_id}",
            reason,
            insert_operation,
        ),
        edit_entry(
            agent_text(locale, "structured.title.remove_original_item"),
            f"sections.{from_section_id}.items.{item_id}",
            reason,
            {"type": "delete_item", "sectionId": from_section_id, "itemId": item_id},
        ),
    ], None


def split_item_entries(
    resume: dict[str, Any],
    args: dict[str, Any],
    *,
    locale: str,
) -> tuple[list[EDIT_ENTRY], str | None]:
    """Build edit entries for splitting one item into two records."""

    section_id = string_arg(args, "sectionId")
    item_id = string_arg(args, "itemId")
    first = args.get("first")
    second = args.get("second")
    if (
        not section_id
        or not item_id
        or not isinstance(first, dict)
        or not isinstance(second, dict)
    ):
        return [], agent_text(locale, "error.split_item_missing_args")

    section = find_section(resume, section_id)
    if not section or not find_item(section, item_id):
        return [], agent_text(locale, "error.split_item_missing_target")

    reason = string_arg(args, "reason") or agent_text(
        locale,
        "structured.reason.split_item",
    )
    second_item = {**second, "id": f"item-agent-split-{uuid4().hex[:8]}"}
    index = int_arg(args, "index")

    insert_operation: dict[str, Any] = {
        "type": "insert_item",
        "sectionId": section_id,
        "item": second_item,
    }
    if index is not None:
        insert_operation["index"] = index

    return [
        edit_entry(
            agent_text(locale, "structured.title.update_split_item"),
            f"sections.{section_id}.items.{item_id}",
            reason,
            {
                "type": "update_item",
                "sectionId": section_id,
                "itemId": item_id,
                "patch": first,
            },
        ),
        edit_entry(
            agent_text(locale, "structured.title.insert_split_item"),
            f"sections.{section_id}.items",
            reason,
            insert_operation,
        ),
    ], None


def merge_item_entries(
    resume: dict[str, Any],
    args: dict[str, Any],
    *,
    locale: str,
) -> tuple[list[EDIT_ENTRY], str | None]:
    """Build edit entries for merging multiple items into the first item."""

    section_id = string_arg(args, "sectionId")
    item_ids = _string_list(args.get("itemIds"))
    merged_item = args.get("mergedItem")
    if not section_id or len(item_ids) < 2 or not isinstance(merged_item, dict):
        return (
            [],
            agent_text(locale, "error.merge_items_missing_args"),
        )

    unique_item_ids = list(dict.fromkeys(item_ids))
    section = find_section(resume, section_id)
    if len(unique_item_ids) < 2 or not section:
        return [], agent_text(locale, "error.merge_items_missing_targets")
    if any(not find_item(section, item_id) for item_id in unique_item_ids):
        return [], agent_text(locale, "error.merge_items_missing_targets")

    reason = string_arg(args, "reason") or agent_text(
        locale,
        "structured.reason.merge_items",
    )
    entries = [
        edit_entry(
            agent_text(locale, "structured.title.merge_item_content"),
            f"sections.{section_id}.items.{unique_item_ids[0]}",
            reason,
            {
                "type": "update_item",
                "sectionId": section_id,
                "itemId": unique_item_ids[0],
                "patch": merged_item,
            },
        ),
    ]
    for item_id in unique_item_ids[1:]:
        entries.append(
            edit_entry(
                agent_text(locale, "structured.title.delete_merged_item"),
                f"sections.{section_id}.items.{item_id}",
                reason,
                {"type": "delete_item", "sectionId": section_id, "itemId": item_id},
            ),
        )

    return entries, None


def classify_skills_entries(
    resume: dict[str, Any],
    args: dict[str, Any],
    *,
    locale: str,
) -> tuple[list[EDIT_ENTRY], str | None]:
    """Build edit entries for grouping skills into a skills section."""

    groups = args.get("groups")
    if not isinstance(groups, list) or not groups:
        return [], agent_text(locale, "error.skills_classify_empty_groups")

    items = []
    for group in groups:
        if not isinstance(group, dict):
            continue
        title = string_arg(group, "title")
        skills = _string_list(group.get("skills")) or _string_list(
            group.get("highlights"),
        )
        if title and skills:
            separator = "、" if locale == "zh" else ", "
            items.append(
                {
                    "id": f"item-agent-skill-{uuid4().hex[:8]}",
                    "title": title,
                    "subtitle": separator.join(skills),
                    "meta": "",
                    "period": "",
                    "description": "",
                    "highlights": [],
                },
            )

    if not items:
        return [], agent_text(locale, "error.skills_classify_empty_items")

    reason = string_arg(args, "reason") or agent_text(
        locale,
        "structured.reason.classify_skills",
    )
    section_id = string_arg(args, "sectionId")
    existing_section = find_section(resume, section_id) if section_id else None
    if not existing_section:
        existing_section = next(
            (
                section
                for section in resume_sections(resume)
                if section.get("kind") == "skills"
            ),
            None,
        )

    if not existing_section:
        section = {
            "id": f"section-agent-skills-{uuid4().hex[:8]}",
            "kind": "skills",
            "layout": "list",
            "customTitle": "",
            "items": items,
        }
        return [
            edit_entry(
                agent_text(locale, "structured.title.add_skills_section"),
                "sections",
                reason,
                {
                    "type": "insert_section",
                    "section": section,
                    "index": int_arg(args, "index"),
                },
            ),
        ], None

    section_id = str(existing_section.get("id") or "")
    entries = [
        edit_entry(
            agent_text(locale, "structured.title.remove_old_skill_group"),
            f"sections.{section_id}.items.{item['id']}",
            reason,
            {"type": "delete_item", "sectionId": section_id, "itemId": str(item["id"])},
        )
        for item in section_items(existing_section)
        if isinstance(item.get("id"), str)
    ]
    entries.extend(
        edit_entry(
            agent_text(locale, "structured.title.add_skill_group"),
            f"sections.{section_id}.items",
            reason,
            {"type": "insert_item", "sectionId": section_id, "item": item},
        )
        for item in items
    )
    return entries, None


def edit_entry(
    title: str,
    target: str,
    reason: str,
    operation: dict[str, Any],
) -> EDIT_ENTRY:
    """Return an edit_execute-compatible entry."""

    return {
        "title": title,
        "target": target,
        "reason": reason,
        "operation": operation,
    }
