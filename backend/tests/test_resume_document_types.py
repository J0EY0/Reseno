import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

from app.services import resume_document_contract as contract
from app.services.resume_starters import create_empty_resume
from scripts.generate_resume_document_types import (
    OUTPUT_PATH,
    SCHEMA_PATH,
    render_resume_document_types,
)


def test_generated_document_types_match_canonical_schema() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert OUTPUT_PATH.read_text(encoding="utf-8") == render_resume_document_types(
        schema
    )


def test_document_field_metadata_matches_each_discriminated_item() -> None:
    schema = contract.resume_document_schema()
    definitions = schema["definitions"]

    for branch in definitions["section"]["oneOf"]:
        section = definitions[branch["$ref"].rsplit("/", 1)[1]]
        properties = section["properties"]
        kind = properties["kind"]["const"]
        item_name = properties["items"]["items"]["$ref"].rsplit("/", 1)[1]
        item_fields = definitions[item_name]["properties"]
        assert set(contract.ITEM_FIELDS_BY_KIND[kind]) == set(item_fields)
        assert set(contract.ITEM_STRING_FIELDS_BY_KIND[kind]) == {
            name for name, shape in item_fields.items()
            if name != "id" and shape.get("type") == "string"
        }
        assert set(contract.ITEM_LIST_FIELDS_BY_KIND[kind]) == {
            name for name, shape in item_fields.items()
            if shape.get("type") == "array"
        }


def test_item_validation_and_generated_type_follow_schema_extension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema = deepcopy(contract.resume_document_schema())
    schema["definitions"]["thesis"] = {"type": "string"}
    education = schema["definitions"]["educationItem"]
    education["properties"]["thesis"] = {"$ref": "#/definitions/thesis"}
    education["required"].append("thesis")
    item = create_empty_resume("earlyCareer", "en")["sections"][0]["items"][0]
    item["thesis"] = "Synthetic schema extension"
    monkeypatch.setattr(contract, "resume_document_schema", lambda: schema)
    contract._resume_item_validators.cache_clear()
    try:
        assert contract.is_resume_item_for_kind(item, "education")
        assert "thesis" in contract._item_fields_by_type(schema, "string")["education"]
        assert "    thesis: Thesis\n" in render_resume_document_types(schema)
        del item["thesis"]
        assert not contract.is_resume_item_for_kind(item, "education")
    finally:
        contract._resume_item_validators.cache_clear()


@pytest.mark.parametrize("valid", [True, False])
def test_validated_document_has_checked_fields_and_section_discriminators(
    tmp_path: Path,
    valid: bool,
) -> None:
    probe = tmp_path / "document_types.py"
    statements = (
        "    name: str = document['basic']['name']\n"
        "    for section in document['sections']:\n"
        "        if section['kind'] == 'education':\n"
        "            school: str = section['items'][0]['school']\n"
        "            print(name, school)\n"
        if valid
        else "    document['sections'] = 42\n"
        "    document['basic']['summray'] = False\n"
        "    name: int = document['basic']['name']\n"
    )
    probe.write_text(
        "from app.services.resume_document_contract import validate_resume_document\n"
        "\n"
        "def check(value: object) -> None:\n"
        "    document = validate_resume_document(value)\n"
        + statements,
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "mypy",
            "--strict",
            "--follow-imports=silent",
            "--cache-dir",
            str(tmp_path / "mypy-cache"),
            str(probe),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )

    if valid:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode == 1, result.stdout + result.stderr
        assert result.stdout.count(" error:") == 3, result.stdout
        assert "[typeddict-item]" in result.stdout
        assert "[typeddict-unknown-key]" in result.stdout
        assert "[assignment]" in result.stdout
