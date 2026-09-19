import html
import json
import re
from collections import Counter
from copy import deepcopy
from typing import Any

_MISSING = object()
_STATUSES = ("Added", "Removed", "Modified")


def semantic_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Copy a snapshot without per-catalog fetch timestamps."""
    result = deepcopy(snapshot)
    for catalog in result.get("catalogs", {}).values():
        catalog.pop("fetchedAt", None)
    return result


def _code(text: str) -> str:
    text = text.replace("\r", "\\r").replace("\n", "\\n")
    escaped = html.escape(text, quote=True)
    escaped = re.sub(r"[\\`|*_\[\]~@]", lambda match: f"&#{ord(match[0])};", escaped)
    return f"<code>{escaped}</code>"


def _value(value: Any) -> str:
    if value is _MISSING:
        return "—"
    return _code(json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False))


def _status(before: Any, after: Any) -> str:
    if before is _MISSING:
        return "Added"
    if after is _MISSING:
        return "Removed"
    return "Modified"


def _field_changes(
    before: dict[str, Any],
    after: dict[str, Any],
    prefix: tuple[str, ...] = (),
) -> list[tuple[str, Any, Any]]:
    changes: list[tuple[str, Any, Any]] = []
    for key in sorted(before.keys() | after.keys()):
        old = before.get(key, _MISSING)
        new = after.get(key, _MISSING)
        if old == new:
            continue
        path = (*prefix, key)
        if isinstance(old, dict) and isinstance(new, dict):
            changes.extend(_field_changes(old, new, path))
        else:
            pointer = "/".join(
                part.replace("~", "~0").replace("/", "~1") for part in path
            )
            changes.append((pointer, old, new))
    return changes


def _table(headers: tuple[str, ...], rows: list[list[str]]) -> str:
    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *("| " + " | ".join(row) + " |" for row in rows),
        ]
    )


def _field_table(changes: list[tuple[str, Any, Any]]) -> str:
    return _table(
        ("Field", "Change", "Before", "After"),
        [
            [_code(field), _status(old, new), _value(old), _value(new)]
            for field, old, new in changes
        ],
    )


def _model_rows(
    before: dict[str, Any],
    after: dict[str, Any],
    counts: Counter[str],
    *,
    provider: str | None = None,
) -> list[list[str]]:
    rows = []
    for model in sorted(before.keys() | after.keys()):
        old = before.get(model, _MISSING)
        new = after.get(model, _MISSING)
        if old == new:
            continue
        status = _status(old, new)
        counts[status] += 1
        changes = (
            _field_changes(old, new)
            if isinstance(old, dict) and isinstance(new, dict)
            else [("(model)", old, new)]
        )
        for field, old_value, new_value in changes:
            row = [
                _code(model),
                status,
                _code(field),
                _value(old_value),
                _value(new_value),
            ]
            if provider is not None:
                row.insert(0, _code(provider))
            rows.append(row)
    return rows


def render_metadata_diff(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Render every semantic snapshot change as an escaped Markdown PR body."""
    old_snapshot = semantic_snapshot(before)
    new_snapshot = semantic_snapshot(after)
    introduction = (
        "## Model metadata update\n\n"
        "Changes to the bundled model metadata are listed below. "
        "Catalog fetch timestamps are excluded. Counts represent source records; "
        "a model present in two sources counts twice. "
        "`—` means absent; `false` is a recorded value."
    )
    if old_snapshot == new_snapshot:
        return introduction + "\n\nNo semantic changes.\n"

    counts: dict[str, Counter[str]] = {
        category: Counter()
        for category in (
            "Sources",
            "Provider records",
            "Provider model records",
            "Context model records",
            "Snapshot fields",
        )
    }
    sections = []
    source_summary_rows = []
    snapshot_changes = _field_changes(
        {key: value for key, value in old_snapshot.items() if key != "catalogs"},
        {key: value for key, value in new_snapshot.items() if key != "catalogs"},
    )
    if snapshot_changes:
        counts["Snapshot fields"].update(
            _status(old, new) for _, old, new in snapshot_changes
        )
        sections.append("### Snapshot metadata\n\n" + _field_table(snapshot_changes))

    old_catalogs = old_snapshot.get("catalogs", {})
    new_catalogs = new_snapshot.get("catalogs", {})
    for source in sorted(old_catalogs.keys() | new_catalogs.keys()):
        old = old_catalogs.get(source, _MISSING)
        new = new_catalogs.get(source, _MISSING)
        if old == new:
            continue
        status = _status(old, new)
        counts["Sources"][status] += 1
        source_sections = []
        model_counts: Counter[str] = Counter()
        context_counts: Counter[str] = Counter()
        old_catalog = {} if old is _MISSING else old
        new_catalog = {} if new is _MISSING else new
        catalog_changes = _field_changes(
            {
                key: value
                for key, value in old_catalog.items()
                if key not in {"providers", "contextModels"}
            },
            {
                key: value
                for key, value in new_catalog.items()
                if key not in {"providers", "contextModels"}
            },
        )
        if catalog_changes:
            source_sections.append(
                "#### Catalog metadata\n\n" + _field_table(catalog_changes)
            )

        old_providers = old_catalog.get("providers", {})
        new_providers = new_catalog.get("providers", {})
        provider_rows = []
        for provider in sorted(old_providers.keys() | new_providers.keys()):
            old_models = old_providers.get(provider, _MISSING)
            new_models = new_providers.get(provider, _MISSING)
            if old_models == new_models:
                continue
            provider_status = _status(old_models, new_models)
            counts["Provider records"][provider_status] += 1
            if provider_status != "Modified":
                source_sections.append(
                    f"Provider {_code(provider)}: {provider_status.lower()}."
                )
            provider_rows.extend(
                _model_rows(
                    {} if old_models is _MISSING else old_models,
                    {} if new_models is _MISSING else new_models,
                    model_counts,
                    provider=provider,
                )
            )
        if provider_rows:
            source_sections.append(
                "#### Provider models\n\n"
                + _table(
                    ("Provider", "Model", "Change", "Field", "Before", "After"),
                    provider_rows,
                )
            )

        context_rows = _model_rows(
            old_catalog.get("contextModels", {}),
            new_catalog.get("contextModels", {}),
            context_counts,
        )
        if context_rows:
            source_sections.append(
                "#### Context models\n\n"
                + _table(("Model", "Change", "Field", "Before", "After"), context_rows)
            )
        counts["Provider model records"].update(model_counts)
        counts["Context model records"].update(context_counts)
        for collection, source_counts in (
            ("Provider models", model_counts),
            ("Context models", context_counts),
        ):
            source_summary_rows.append(
                [
                    _code(source),
                    collection,
                    *(str(source_counts[change]) for change in _STATUSES),
                ]
            )
        details = "\n\n".join(source_sections) or "No provider or model record changes."
        sections.append(
            f"<details>\n<summary>Source {_code(source)} — {status}</summary>\n\n"
            f"{details}\n\n</details>"
        )

    summary = _table(
        ("Entity", *_STATUSES),
        [
            [category, *(str(counter[status]) for status in _STATUSES)]
            for category, counter in counts.items()
        ],
    )
    summaries = [summary]
    if source_summary_rows:
        summaries.append(
            _table(("Source", "Collection", *_STATUSES), source_summary_rows)
        )
    return "\n\n".join([introduction, *summaries, *sections]) + "\n"
