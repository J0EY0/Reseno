import json
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

# jsonschema has no bundled stubs in this environment. Keep suppressions at
# the dependency boundary so the contract helpers remain fully typed.
from jsonschema import Draft7Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import best_match  # type: ignore[import-untyped]

from app.schemas.resume_document_generated import ResumeDocument

RESUME_DOCUMENT_INVALID = "RESUME_DOCUMENT_INVALID"
RESUME_DOCUMENT_DUPLICATE_ID = "RESUME_DOCUMENT_DUPLICATE_ID"

_SCHEMA_PATH = Path(__file__).with_name("resume_document.schema.json")

class ResumeDocumentContractError(ValueError):
    """Describe one stable resume-document invariant violation."""

    def __init__(self, code: str, path: str) -> None:
        super().__init__(code)
        self.code = code
        self.path = path


@lru_cache(maxsize=1)
def resume_document_schema() -> dict[str, Any]:
    """Load the canonical V2 document schema packaged with the backend."""

    payload = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Resume document schema must be a JSON object.")
    Draft7Validator.check_schema(payload)
    return payload


def _schema_definition(schema: dict[str, Any], reference: str) -> dict[str, Any]:
    prefix = "#/definitions/"
    if not reference.startswith(prefix):
        raise ValueError(f"Unsupported resume schema reference: {reference}")
    definition = schema["definitions"][reference.removeprefix(prefix)]
    if not isinstance(definition, dict):
        raise ValueError(
            f"Resume schema reference must resolve to an object: {reference}"
        )
    return definition


def _item_schemas_by_kind(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    section_schema = _schema_definition(
        schema, schema["properties"]["sections"]["items"]["$ref"],
    )
    item_schemas: dict[str, dict[str, Any]] = {}
    for branch in section_schema["oneOf"]:
        section = _schema_definition(schema, branch["$ref"])
        properties = section["properties"]
        kind = properties["kind"]["const"]
        item_schemas[kind] = _schema_definition(
            schema, properties["items"]["items"]["$ref"],
        )
    return item_schemas


_ITEM_SCHEMAS_BY_KIND = _item_schemas_by_kind(resume_document_schema())


def _item_fields_by_type(
    schema: dict[str, Any],
    field_type: str,
) -> dict[str, tuple[str, ...]]:
    fields_by_kind: dict[str, tuple[str, ...]] = {}
    for kind, item_schema in _item_schemas_by_kind(schema).items():
        fields: list[str] = []
        for field, shape in item_schema["properties"].items():
            while "$ref" in shape:
                shape = _schema_definition(schema, shape["$ref"])
            if field != "id" and shape.get("type") == field_type:
                fields.append(field)
        fields_by_kind[kind] = tuple(fields)
    return fields_by_kind


ITEM_STRING_FIELDS_BY_KIND = _item_fields_by_type(resume_document_schema(), "string")
ITEM_LIST_FIELDS_BY_KIND = _item_fields_by_type(resume_document_schema(), "array")
ITEM_FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    kind: tuple(item_schema["properties"])
    for kind, item_schema in _ITEM_SCHEMAS_BY_KIND.items()
}


@lru_cache(maxsize=1)
def _resume_item_validators() -> dict[str, Draft7Validator]:
    schema = resume_document_schema()
    return {
        kind: Draft7Validator({**item_schema, "definitions": schema["definitions"]})
        for kind, item_schema in _item_schemas_by_kind(schema).items()
    }


def is_resume_item_for_kind(value: object, kind: str) -> bool:
    """Validate one item using its canonical section discriminator."""

    validator = _resume_item_validators().get(kind)
    return validator is not None and bool(validator.is_valid(value))


@lru_cache(maxsize=1)
def _resume_document_validator() -> Draft7Validator:
    return Draft7Validator(resume_document_schema())


def _validation_path(error: object) -> str:
    """Translate one jsonschema error path to the stable API path format."""

    absolute_path = getattr(error, "absolute_path", ())
    suffix = ".".join(str(part) for part in absolute_path)
    return f"resume.{suffix}" if suffix else "resume"


def validate_resume_document(value: object) -> ResumeDocument:
    """Validate the exact V2 shape shared by persistence, imports, and Agent.

    JSON Schema owns field-level discrimination and rejects unknown fields.
    The explicit ID pass covers the document-wide identity invariant that JSON
    Schema cannot express for object properties.
    """

    error = best_match(_resume_document_validator().iter_errors(value))
    if error is not None:
        raise ResumeDocumentContractError(
            RESUME_DOCUMENT_INVALID,
            _validation_path(error),
        )

    document = cast(ResumeDocument, value)
    section_ids: set[str] = set()
    item_ids: set[str] = set()
    for section_index, section in enumerate(document["sections"]):
        section_id = section["id"]
        if section_id in section_ids:
            raise ResumeDocumentContractError(
                RESUME_DOCUMENT_DUPLICATE_ID,
                f"resume.sections.{section_index}.id",
            )
        section_ids.add(section_id)

        for item_index, item in enumerate(section["items"]):
            item_id = item["id"]
            if item_id in item_ids:
                raise ResumeDocumentContractError(
                    RESUME_DOCUMENT_DUPLICATE_ID,
                    f"resume.sections.{section_index}.items.{item_index}.id",
                )
            item_ids.add(item_id)

    return document
