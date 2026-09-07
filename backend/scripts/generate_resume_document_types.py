import argparse
import json
import keyword
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = BACKEND_ROOT / "app/services/resume_document.schema.json"
OUTPUT_PATH = BACKEND_ROOT / "app/schemas/resume_document_generated.py"


def _type_name(name: str) -> str:
    if not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(f"Invalid schema definition name: {name}")
    return name[0].upper() + name[1:]


def _render_type(node: dict[str, Any]) -> str:
    if "$ref" in node:
        reference = node["$ref"]
        prefix = "#/definitions/"
        if not isinstance(reference, str) or not reference.startswith(prefix):
            raise ValueError(f"Unsupported schema reference: {reference}")
        return _type_name(reference.removeprefix(prefix))
    if "const" in node:
        return f"Literal[{node['const']!r}]"
    if "enum" in node:
        return "Literal[" + ", ".join(repr(value) for value in node["enum"]) + "]"
    if "oneOf" in node:
        return " | ".join(_render_type(branch) for branch in node["oneOf"])
    primitives = {
        "string": "str",
        "integer": "int",
        "number": "float",
        "boolean": "bool",
        "null": "None",
    }
    if node.get("type") in primitives:
        return primitives[node["type"]]
    if node.get("type") == "array":
        return f"list[{_render_type(node['items'])}]"
    raise ValueError(f"Unsupported schema type: {node}")


def _render_definition(name: str, node: dict[str, Any]) -> str:
    if node.get("type") != "object":
        rendered = _render_type(node)
        return (
            f"type {name} = (\n    " + rendered.replace(" | ", "\n    | ") + "\n)"
            if " | " in rendered
            else f"type {name} = {rendered}"
        )
    if node.get("additionalProperties") is not False:
        raise ValueError(f"{name} must define a closed object shape.")
    properties = node["properties"]
    required = set(node.get("required", ()))
    if not required.issubset(properties):
        raise ValueError(f"{name} requires undefined properties.")
    fields: list[str] = []
    for field, shape in properties.items():
        if not field.isidentifier() or keyword.iskeyword(field):
            raise ValueError(f"Invalid field name in {name}: {field}")
        field_type = _render_type(shape)
        if field not in required:
            field_type = f"NotRequired[{field_type}]"
        fields.append(f"    {field}: {field_type}")
    return f"class {name}(TypedDict):\n" + "\n".join(fields)


def render_resume_document_types(schema: dict[str, Any]) -> str:
    definitions = schema["definitions"]
    blocks = [
        _render_definition(_type_name(name), node)
        for name, node in definitions.items()
    ]
    blocks.append(_render_definition("ResumeDocument", schema))
    imports = "Literal, NotRequired, TypedDict" if any(
        "NotRequired[" in block for block in blocks
    ) else "Literal, TypedDict"
    return (
        "from __future__ import annotations\n\n"
        f"from typing import {imports}\n\n"
        + "\n\n\n".join(blocks)
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    rendered = render_resume_document_types(schema)
    if args.write:
        OUTPUT_PATH.write_text(rendered, encoding="utf-8")
        return
    if not OUTPUT_PATH.exists() or OUTPUT_PATH.read_text(encoding="utf-8") != rendered:
        raise SystemExit(
            "Resume document types are stale. Run "
            "uv run --locked python scripts/generate_resume_document_types.py --write"
        )


if __name__ == "__main__":
    main()
