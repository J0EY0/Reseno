from collections.abc import Iterable

from app.schemas.agent import AgentDraftReviewItem, AgentResumeEditSuggestion


def build_draft_review_items(
    edits: Iterable[AgentResumeEditSuggestion],
) -> list[AgentDraftReviewItem]:
    """Group ordered edits that cannot be reviewed independently.

    A structural insertion owns operations that reference the inserted section
    or item. Insertions and deletions in one ordered collection stay atomic,
    collection reorders join every structural change in that collection, and
    deleting a section joins its child operations. These groups keep every
    review item valid regardless of the order in which other review items are
    resolved. Repeated writes to one target also remain ordered in a single
    item.
    """

    ordered_edits = list(edits)
    parents = list(range(len(ordered_edits)))
    first_target_index: dict[str, int] = {}
    inserted_section_index: dict[str, int] = {}
    inserted_item_index: dict[str, int] = {}
    section_reference_indices: dict[str, list[int]] = {}
    deleted_section_indices: dict[str, list[int]] = {}
    structural_section_indices: list[int] = []
    reorder_section_indices: list[int] = []
    structural_item_indices: dict[str, list[int]] = {}
    reorder_item_indices: dict[str, list[int]] = {}

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root == right_root:
            return
        if left_root < right_root:
            parents[right_root] = left_root
        else:
            parents[left_root] = right_root

    def join_target(index: int, key: str) -> None:
        if not key:
            return
        owner = first_target_index.setdefault(key, index)
        union(index, owner)

    for index, edit in enumerate(ordered_edits):
        operation = edit.operation or {}
        operation_type = str(operation.get("type") or "")
        section_id = _operation_section_id(operation)
        item_id = _operation_item_id(operation)

        join_target(index, _operation_target_key(edit, operation))

        if section_id and section_id in inserted_section_index:
            union(index, inserted_section_index[section_id])
        if item_id and item_id in inserted_item_index:
            union(index, inserted_item_index[item_id])

        if section_id:
            section_reference_indices.setdefault(section_id, []).append(index)

        if operation_type == "reorder_sections":
            reorder_section_indices.append(index)
        elif operation_type == "reorder_items":
            if section_id:
                reorder_item_indices.setdefault(section_id, []).append(index)

        if operation_type == "insert_section":
            structural_section_indices.append(index)
            section = operation.get("section")
            if isinstance(section, dict):
                inserted_section_id = _non_empty_string(section.get("id"))
                if inserted_section_id:
                    inserted_section_index[inserted_section_id] = index
                items = section.get("items")
                if isinstance(items, list):
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        inserted_item_id = _non_empty_string(item.get("id"))
                        if inserted_item_id:
                            inserted_item_index[inserted_item_id] = index
        elif operation_type == "delete_section" and section_id:
            structural_section_indices.append(index)
            deleted_section_indices.setdefault(section_id, []).append(index)
        elif operation_type in {"insert_item", "delete_item"} and section_id:
            structural_item_indices.setdefault(section_id, []).append(index)
            if operation_type == "insert_item" and item_id:
                inserted_item_index[item_id] = index

    if structural_section_indices:
        collection_owner = structural_section_indices[0]
        for structural_index in structural_section_indices[1:]:
            union(collection_owner, structural_index)

    for structural_indices in structural_item_indices.values():
        collection_owner = structural_indices[0]
        for structural_index in structural_indices[1:]:
            union(collection_owner, structural_index)

    for reorder_index in reorder_section_indices:
        for structural_index in structural_section_indices:
            union(reorder_index, structural_index)

    for section_id, reorder_indices in reorder_item_indices.items():
        for reorder_index in reorder_indices:
            for structural_index in structural_item_indices.get(section_id, []):
                union(reorder_index, structural_index)

    for section_id, delete_indices in deleted_section_indices.items():
        for delete_index in delete_indices:
            for reference_index in section_reference_indices.get(section_id, []):
                union(delete_index, reference_index)

    grouped_indices: dict[int, list[int]] = {}
    for index in range(len(ordered_edits)):
        grouped_indices.setdefault(find(index), []).append(index)

    return [
        AgentDraftReviewItem(
            id=f"agent-review-{ordered_edits[indices[0]].id}",
            editIds=[ordered_edits[index].id for index in indices],
            status="pending",
        )
        for _, indices in sorted(
            grouped_indices.items(),
            key=lambda entry: entry[1][0],
        )
    ]


def _operation_target_key(
    edit: AgentResumeEditSuggestion,
    operation: dict[str, object],
) -> str:
    operation_type = str(operation.get("type") or "")
    if operation_type == "replace_field":
        return f"field:{_non_empty_string(operation.get('path'))}"
    if operation_type == "insert_section":
        section = operation.get("section")
        section_id = (
            _non_empty_string(section.get("id")) if isinstance(section, dict) else ""
        )
        return f"section:{section_id}" if section_id else ""
    if operation_type in {"update_section", "delete_section"}:
        section_id = _non_empty_string(operation.get("sectionId"))
        return f"section:{section_id}" if section_id else ""
    if operation_type == "reorder_sections":
        return "collection:sections"
    if operation_type == "insert_item":
        item = operation.get("item")
        item_id = _non_empty_string(item.get("id")) if isinstance(item, dict) else ""
        return f"item:{item_id}" if item_id else ""
    if operation_type in {"update_item", "delete_item"}:
        item_id = _non_empty_string(operation.get("itemId"))
        return f"item:{item_id}" if item_id else ""
    if operation_type == "reorder_items":
        section_id = _non_empty_string(operation.get("sectionId"))
        return f"collection:section:{section_id}:items" if section_id else ""
    return f"target:{edit.target}" if edit.target else ""


def _operation_section_id(operation: dict[str, object]) -> str:
    if operation.get("type") == "insert_section":
        section = operation.get("section")
        return _non_empty_string(section.get("id")) if isinstance(section, dict) else ""
    return _non_empty_string(operation.get("sectionId"))


def _operation_item_id(operation: dict[str, object]) -> str:
    if operation.get("type") == "insert_item":
        item = operation.get("item")
        return _non_empty_string(item.get("id")) if isinstance(item, dict) else ""
    return _non_empty_string(operation.get("itemId"))


def _non_empty_string(value: object) -> str:
    return value if isinstance(value, str) and value else ""
