import json
from pathlib import Path
from typing import Any

REGISTRY_PATH = Path(__file__).with_name("section_registry.json")


def _load_section_registry() -> list[dict[str, Any]]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError(
            "section_registry.json must contain a non-empty sections list."
        )

    kinds: set[str] = set()
    for section in sections:
        kind = section.get("kind")
        labels = section.get("labels")
        layout = section.get("defaultLayout")
        if not isinstance(kind, str) or not kind:
            raise ValueError("Each section registry entry must define kind.")
        if kind in kinds:
            raise ValueError(f"Duplicate section kind in registry: {kind}")
        if layout not in {"timeline", "list"}:
            raise ValueError(f"Invalid defaultLayout for section kind: {kind}")
        if not isinstance(labels, dict) or not labels.get("zh") or not labels.get("en"):
            raise ValueError(f"Section kind {kind} must define zh/en labels.")
        kinds.add(kind)

    return sections


SECTION_REGISTRY = _load_section_registry()
SECTION_KIND_ENUM = [section["kind"] for section in SECTION_REGISTRY]
SECTION_LABELS = {section["kind"]: section["labels"] for section in SECTION_REGISTRY}
SECTION_DEFAULT_LAYOUTS = {
    section["kind"]: section["defaultLayout"] for section in SECTION_REGISTRY
}
SECTION_KIND_ALIASES = {
    alias: section["kind"]
    for section in SECTION_REGISTRY
    for alias in section.get("aliases", [])
    if isinstance(alias, str) and alias
}


def section_kind_values() -> str:
    return ", ".join(SECTION_KIND_ENUM)


def section_label_lines(locale_order: tuple[str, ...] = ("zh", "en")) -> str:
    lines = []
    for section in SECTION_REGISTRY:
        kind = section["kind"]
        labels = SECTION_LABELS[kind]
        label_parts = [
            label for locale in locale_order if (label := labels.get(locale))
        ]
        label_text = " / ".join(label_parts) if label_parts else kind
        lines.append(f"- {kind}: {label_text}")
    return "\n".join(lines)
