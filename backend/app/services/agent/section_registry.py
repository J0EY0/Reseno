import json
import re
import unicodedata
from pathlib import Path
from typing import Literal, TypedDict

from app.agent_locales import SUPPORTED_AGENT_LOCALES

REGISTRY_PATH = Path(__file__).with_name("section_registry.json")
SectionLayout = Literal["timeline", "list"]
CJK_RADICAL_TEXT_EQUIVALENTS: dict[str, str] = {
    # PDF Type3 fonts can expose these radicals instead of their simplified
    # characters. Keep registry validation aligned with the importer.
    "⻚": "页",
    "⻬": "齐",
}


class SectionRegistryEntry(TypedDict):
    """Validated shape shared by registry consumers after JSON loading."""

    kind: str
    defaultLayout: SectionLayout
    labels: dict[str, str]
    aliases: list[str]


def normalize_section_alias(alias: str) -> str:
    """Return the canonical key shared by registry validation and matching."""

    normalized = "".join(
        CJK_RADICAL_TEXT_EQUIVALENTS.get(character, character)
        for character in unicodedata.normalize("NFKC", alias)
    )
    # JavaScript uses toLowerCase() for the same registry in PDF import.
    # Python lower(), unlike casefold(), keeps both runtimes equivalent.
    return re.sub(r"[\s:：]+", "", normalized).lower()


def _load_section_registry() -> list[SectionRegistryEntry]:
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("section_registry.json must contain an object.")

    sections = payload.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError(
            "section_registry.json must contain a non-empty sections list."
        )

    kinds: set[str] = set()
    aliases_by_key: dict[str, tuple[str, str, int]] = {}
    validated_sections: list[SectionRegistryEntry] = []
    for section in sections:
        if not isinstance(section, dict):
            raise ValueError("Each section registry entry must be an object.")

        kind = section.get("kind")
        labels = section.get("labels")
        layout = section.get("defaultLayout")
        aliases = section.get("aliases")
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("Each section registry entry must define kind.")
        if kind != kind.strip() or re.fullmatch(r"[a-z][a-z0-9_]*", kind) is None:
            raise ValueError(
                "Section kind must be a canonical lowercase identifier: "
                f"{kind!r}"
            )
        if kind in kinds:
            raise ValueError(f"Duplicate section kind in registry: {kind}")
        if layout not in {"timeline", "list"}:
            raise ValueError(f"Invalid defaultLayout for section kind: {kind}")
        if not isinstance(labels, dict):
            expected = "/".join(SUPPORTED_AGENT_LOCALES)
            raise ValueError(f"Section kind {kind} must define {expected} labels.")
        if any(
            not isinstance(label_key, str)
            or not isinstance(label_value, str)
            or not label_key.strip()
            or not label_value.strip()
            for label_key, label_value in labels.items()
        ) or any(
            not isinstance(labels.get(locale), str)
            or not labels[locale].strip()
            for locale in SUPPORTED_AGENT_LOCALES
        ):
            expected = "/".join(SUPPORTED_AGENT_LOCALES)
            raise ValueError(
                f"Section kind {kind} must define non-empty {expected} labels."
            )
        if not isinstance(aliases, list):
            raise ValueError(f"Section kind {kind} aliases must be a list.")
        if not aliases:
            raise ValueError(
                f"Section kind {kind} aliases must be a non-empty list."
            )

        for alias_index, alias in enumerate(aliases):
            if not isinstance(alias, str) or not alias.strip():
                raise ValueError(
                    f"Section kind {kind} alias at index {alias_index} "
                    "must be a non-empty string."
                )

            alias_key = normalize_section_alias(alias)
            if not alias_key:
                raise ValueError(
                    f"Section kind {kind} alias at index {alias_index} "
                    "is empty after normalization."
                )

            existing = aliases_by_key.get(alias_key)
            if existing is not None:
                existing_kind, existing_alias, existing_index = existing
                if existing_kind == kind:
                    raise ValueError(
                        f"Section kind {kind} alias at index {alias_index} "
                        f"({alias!r}) duplicates alias at index {existing_index} "
                        f"({existing_alias!r}) after normalization."
                    )
                raise ValueError(
                    f"Section kind {kind} alias at index {alias_index} "
                    f"({alias!r}) conflicts with section kind {existing_kind} "
                    f"alias at index {existing_index} ({existing_alias!r}) "
                    "after normalization."
                )

            aliases_by_key[alias_key] = (kind, alias, alias_index)
        kinds.add(kind)
        validated_layout: SectionLayout = (
            "timeline" if layout == "timeline" else "list"
        )
        validated_sections.append(
            {
                "kind": kind,
                "defaultLayout": validated_layout,
                "labels": {
                    label_key: label_value
                    for label_key, label_value in labels.items()
                },
                "aliases": [alias for alias in aliases],
            }
        )

    return validated_sections


SECTION_REGISTRY = _load_section_registry()
SECTION_KIND_ENUM: list[str] = [section["kind"] for section in SECTION_REGISTRY]
SECTION_LABELS: dict[str, dict[str, str]] = {
    section["kind"]: section["labels"] for section in SECTION_REGISTRY
}
SECTION_DEFAULT_LAYOUTS: dict[str, SectionLayout] = {
    section["kind"]: section["defaultLayout"]
    for section in SECTION_REGISTRY
}
SECTION_KIND_ALIASES: dict[str, str] = {
    normalize_section_alias(alias): section["kind"]
    for section in SECTION_REGISTRY
    for alias in section["aliases"]
}
# Model-provided labels may contain prose around a known section name. Prefer
# the most specific alias so "internship experience" does not fall through to
# the shorter generic "experience" alias.
SECTION_KIND_ALIAS_MATCHES: tuple[tuple[str, str], ...] = tuple(
    sorted(
        (
            (alias, section["kind"])
            for section in SECTION_REGISTRY
            for alias in section["aliases"]
        ),
        key=lambda item: len(normalize_section_alias(item[0])),
        reverse=True,
    )
)


def section_kind_values() -> str:
    return ", ".join(SECTION_KIND_ENUM)


def section_label_lines(locale_order: tuple[str, ...] = SUPPORTED_AGENT_LOCALES) -> str:
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
