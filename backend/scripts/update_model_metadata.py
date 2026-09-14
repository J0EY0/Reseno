import argparse
import asyncio
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services import model_metadata


def _read_catalog(path: Path) -> dict[str, Any]:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(catalog, dict):
        raise ValueError(f"Model catalog must be a JSON object: {path}")
    return catalog


def _write_snapshot(output: Path, snapshot: dict[str, Any]) -> None:
    content = json.dumps(
        snapshot,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2,
    ) + "\n"
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
) -> None:
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
    _write_snapshot(output, snapshot)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate Reseno's bundled model metadata from both upstreams.",
    )
    parser.add_argument(
        "--output", type=Path, default=model_metadata.MODEL_METADATA_SNAPSHOT_PATH,
    )
    parser.add_argument("--litellm-file", type=Path)
    parser.add_argument(
        "--models-dev-file", type=Path, help="Path to models.dev/catalog.json",
    )
    parser.add_argument("--fetched-at", help="ISO 8601 source timestamp with timezone")
    args = parser.parse_args()
    try:
        asyncio.run(
            update_snapshot(
                args.output,
                litellm_file=args.litellm_file,
                models_dev_file=args.models_dev_file,
                fetched_at=args.fetched_at,
            ),
        )
    except (OSError, ValueError) as error:
        parser.exit(1, f"Model metadata generation failed: {error}\n")
    print(f"Generated {args.output} ({args.output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
