import argparse
import json
from pathlib import Path
from typing import Any

_SOURCES = (("litellm", "LiteLLM"), ("modelsDev", "models.dev"))
_MAX_DETAIL_ROWS = 50
_MAX_CELL_BYTES = 180
_MISSING = object()
_RecordKey = tuple[str, ...]
_Records = dict[_RecordKey, dict[str, Any]]
_Detail = tuple[str, _RecordKey, str, Any, Any]


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _code(value: str) -> str:
    chunks: list[str] = []
    size = 0
    for character in value:
        if character in "&<>`*_{}[]()#+!|\\~@":
            chunk = f"&#{ord(character)};"
        elif ord(character) < 32 or ord(character) == 127:
            chunk = f"\\u{ord(character):04x}"
        else:
            chunk = character
        size += len(chunk.encode("utf-8"))
        if size > _MAX_CELL_BYTES:
            chunks.append("…")
            break
        chunks.append(chunk)
    return "<code>" + "".join(chunks) + "</code>"


def _value(value: Any) -> str:
    return "—" if value is _MISSING else _code(_json(value))


def _record_changes(
    before: _Records,
    after: _Records,
) -> tuple[tuple[int, int, int], list[_Detail]]:
    added = sorted(after.keys() - before.keys())
    removed = sorted(before.keys() - after.keys())
    modified = [
        key
        for key in sorted(before.keys() & after.keys())
        if _json(before[key]) != _json(after[key])
    ]
    details: list[_Detail] = [
        ("Added", key, "", _MISSING, after[key]) for key in added
    ]
    details.extend(("Removed", key, "", before[key], _MISSING) for key in removed)
    for key in modified:
        old, new = before[key], after[key]
        for field in sorted(old.keys() | new.keys()):
            previous, current = old.get(field, _MISSING), new.get(field, _MISSING)
            if (
                previous is _MISSING
                or current is _MISSING
                or _json(previous) != _json(current)
            ):
                details.append(("Modified", key, field, previous, current))
    return (len(added), len(removed), len(modified)), details


def _provider_records(catalog: dict[str, Any]) -> _Records:
    return {
        (provider, model): facts
        for provider, models in catalog["providers"].items()
        for model, facts in models.items()
    }


def _context_records(catalog: dict[str, Any]) -> _Records:
    return {(model,): facts for model, facts in catalog["contextModels"].items()}


def render_report(before: dict[str, Any], after: dict[str, Any]) -> str:
    """Summarize normalized snapshot records and changed fields for a pull request."""

    lines = [
        "## Model metadata changes",
        "",
        "Counts compare model records; timestamps do not count as model changes.",
        "Each provider/model pair is a separate record.",
        f"At most {_MAX_DETAIL_ROWS} detail rows are shown. Long cells end with …; "
        "see **Files changed** for the complete data.",
    ]
    changed_headers = [
        key for key in ("version", "source") if _json(before[key]) != _json(after[key])
    ]
    if changed_headers:
        lines.extend(
            [
                "",
                "| Snapshot field | Before | After |",
                "| --- | --- | --- |",
            ],
        )
        for header_field in changed_headers:
            lines.append(
                f"| {header_field} | {_value(before[header_field])} | "
                f"{_value(after[header_field])} |",
            )

    sources = []
    for source, title in _SOURCES:
        old, new = before["catalogs"][source], after["catalogs"][source]
        groups = [
            ("Provider models", _provider_records(old), _provider_records(new)),
            ("Context references", _context_records(old), _context_records(new)),
        ]
        changes = [
            (label, *_record_changes(first, second))
            for label, first, second in groups
        ]
        sources.append((source, title, old, new, changes))

    selected: dict[tuple[str, str], list[_Detail]] = {}
    remaining = _MAX_DETAIL_ROWS
    for kind in ("Modified", "Removed", "Added"):
        for source, _, _, _, changes in sources:
            for label, _, details in changes:
                visible = selected.setdefault((source, label), [])
                for detail in details:
                    if detail[0] == kind and remaining:
                        visible.append(detail)
                        remaining -= 1

    for source, title, old, new, changes in sources:
        lines.extend(
            [
                "",
                f"### {title}",
                "",
                f"Source fetched at: {_value(old['fetchedAt'])} → "
                f"{_value(new['fetchedAt'])}.",
                "",
                "| Records | Added | Removed | Modified |",
                "| --- | ---: | ---: | ---: |",
            ],
        )
        for label, counts, _ in changes:
            lines.append(f"| {label} | {counts[0]} | {counts[1]} | {counts[2]} |")
        if not any(details for _, _, details in changes):
            lines.extend(["", "No model records changed."])
        for label, _, details in changes:
            if not details:
                continue
            visible = selected[(source, label)]
            lines.extend(["", f"#### {label}", ""])
            if visible:
                identifier = (
                    "Provider / model" if label == "Provider models" else "Model"
                )
                lines.extend(
                    [
                        f"| Change | {identifier} | Field | Before | After |",
                        "| --- | --- | --- | --- | --- |",
                    ],
                )
                for change, key, field, previous, current in visible:
                    lines.append(
                        f"| {change} | {_code(' / '.join(key))} | "
                        f"{_code(field) if field else '—'} | "
                        f"{_value(previous)} | {_value(current)} |",
                    )
            omitted = len(details) - len(visible)
            if omitted:
                lines.extend(
                    [
                        "",
                        f"{omitted} additional detail rows omitted; "
                        "see **Files changed**.",
                    ],
                )
    return "\n".join(lines) + "\n"


def _read_snapshot(path: Path) -> dict[str, Any]:
    snapshot = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(snapshot, dict):
        raise ValueError(f"Model metadata snapshot must be a JSON object: {path}")
    return snapshot


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize model metadata snapshot changes.",
    )
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--updated", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = render_report(_read_snapshot(args.base), _read_snapshot(args.updated))
        args.output.write_text(report, encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Model metadata report failed: {error}\n")


if __name__ == "__main__":
    main()
