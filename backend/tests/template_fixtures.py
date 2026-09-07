from copy import deepcopy
from typing import Any

from app.services.template_presets import get_builtin_template_preset


def portable_template(name: str = "Test template") -> dict[str, Any]:
    preset = get_builtin_template_preset("minimal")
    return {
        "preset": "minimal",
        "name": name,
        "description": "Test template",
        **{key: deepcopy(preset[key]) for key in ("layout", "typography", "settings")},
    }
