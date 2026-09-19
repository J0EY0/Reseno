import argparse
import asyncio
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services import model_metadata
from scripts.model_metadata_diff import render_metadata_diff, semantic_snapshot


def _read_catalog(path: Path) -> dict[str, Any]:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict):
        raise ValueError(f"Model catalog must be a JSON object: {path}")
    return catalog


def _write_snapshot(output: Path, snapshot: dict[str, Any]) -> None:
    content = (
        json.dumps(
            snapshot,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        )
        + "\n"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output.parent,
            prefix=f".{output.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


async def update_snapshot(
    output: Path,
    *,
    litellm_file: Path | None = None,
    models_dev_file: Path | None = None,
    fetched_at: str | None = None,
    previous_snapshot: Path | None = None,
) -> bool:
    if (litellm_file is None) != (models_dev_file is None):
        raise ValueError("Provide both --litellm-file and --models-dev-file.")
    timestamp = datetime.fromisoformat(fetched_at) if fetched_at else datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("--fetched-at must include a timezone.")
    if litellm_file is not None and models_dev_file is not None:
        litellm = _read_catalog(litellm_file)
        models_dev = _read_catalog(models_dev_file)
    else:
        litellm, models_dev = await asyncio.gather(
            model_metadata._fetch_catalog(),
            model_metadata._fetch_reasoning_catalog(),
        )
    snapshot = model_metadata.build_model_metadata_snapshot(
        litellm,
        models_dev,
        fetched_at=timestamp.astimezone(UTC).isoformat(timespec="seconds"),
    )
    current = _read_catalog(output) if output.exists() else None
    if current is not None and semantic_snapshot(current) == semantic_snapshot(
        snapshot
    ):
        return False

    references = [current] if current is not None else []
    if previous_snapshot is not None:
        references.append(_read_catalog(previous_snapshot))
    for source, catalog in snapshot["catalogs"].items():
        for reference in references:
            previous = reference["catalogs"][source]
            if {k: v for k, v in catalog.items() if k != "fetchedAt"} == {
                k: v for k, v in previous.items() if k != "fetchedAt"
            }:
                catalog["fetchedAt"] = previous["fetchedAt"]
                break
    _write_snapshot(output, snapshot)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Reseno's bundled model metadata from both upstreams.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=model_metadata.MODEL_METADATA_SNAPSHOT_PATH,
    )
    parser.add_argument("--litellm-file", type=Path)
    parser.add_argument(
        "--models-dev-file",
        type=Path,
        help="Path to models.dev/catalog.json",
    )
    parser.add_argument("--fetched-at", help="ISO 8601 source timestamp with timezone")
    parser.add_argument(
        "--previous-snapshot",
        type=Path,
        help="Snapshot from the existing update branch",
    )
    parser.add_argument("--report", type=Path, help="Write the semantic Markdown diff")
    parser.add_argument("--github-output", type=Path, help="Append the changed output")
    args = parser.parse_args()
    try:
        before = _read_catalog(args.output) if args.output.exists() else {}
        changed = asyncio.run(
            update_snapshot(
                args.output,
                litellm_file=args.litellm_file,
                models_dev_file=args.models_dev_file,
                fetched_at=args.fetched_at,
                previous_snapshot=args.previous_snapshot,
            ),
        )
        if args.report is not None:
            args.report.write_text(
                render_metadata_diff(before, _read_catalog(args.output)),
                encoding="utf-8",
            )
        if args.github_output is not None:
            with args.github_output.open("a", encoding="utf-8") as handle:
                handle.write(f"changed={str(changed).lower()}\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Model metadata generation failed: {error}\n")
    action = "Generated" if changed else "Unchanged"
    print(f"{action} {args.output} ({args.output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
