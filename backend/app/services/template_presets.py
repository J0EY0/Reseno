import json
from pathlib import Path
from typing import Any, cast

_PRESET_PATH = Path(__file__).with_name("template_presets.json")
TEMPLATE_STARTER_IDS = frozenset(
    {"earlyCareer", "experienced", "executive", "research"}
)


def _load_builtin_template_presets() -> dict[str, dict[str, Any]]:
    payload = json.loads(_PRESET_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise RuntimeError("Built-in template presets must be a non-empty object.")

    presets: dict[str, dict[str, Any]] = {}
    for template_id, preset in payload.items():
        if not isinstance(template_id, str) or not isinstance(preset, dict):
            raise RuntimeError("Built-in template presets are malformed.")
        if preset.get("starter") not in TEMPLATE_STARTER_IDS:
            raise RuntimeError(
                f"Built-in template preset {template_id} has an invalid starter."
            )
        presets[template_id] = cast(dict[str, Any], preset)
    return presets


BUILTIN_TEMPLATE_PRESETS = _load_builtin_template_presets()
BUILT_IN_TEMPLATE_IDS = frozenset(BUILTIN_TEMPLATE_PRESETS)


def get_builtin_template_preset(template_id: str) -> dict[str, Any]:
    return BUILTIN_TEMPLATE_PRESETS[template_id]
