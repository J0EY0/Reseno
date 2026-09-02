import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, cast

# jsonschema has no bundled stubs in this environment. Keep suppressions at
# the dependency boundary so the contract helpers remain fully typed.
from jsonschema import Draft7Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import best_match  # type: ignore[import-untyped]

RESUME_DOCUMENT_INVALID = "RESUME_DOCUMENT_INVALID"
RESUME_DOCUMENT_DUPLICATE_ID = "RESUME_DOCUMENT_DUPLICATE_ID"
RESUME_NODE_ID_PATTERN = re.compile(r"^[A-Za-z0-9-]+$")

_SCHEMA_PATH = Path(__file__).with_name("resume_document.schema.json")

# These tuples are the backend's small semantic vocabulary. Agent adapters use
# them to remain kind-aware; the JSON Schema remains the authority for exact
# required fields and wire validation.
SECTION_KINDS = (
    "education",
    "experience",
    "project",
    "publication",
    "achievement",
    "simple_list",
)
ITEM_STRING_FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    "education": (
        "school",
        "degree",
        "major",
        "gpa",
        "location",
        "period",
        "description",
    ),
    "experience": (
        "company",
        "position",
        "location",
        "period",
        "description",
    ),
    "project": ("name", "role", "period", "url", "description"),
    "publication": ("title", "authors", "venue", "date", "url", "description"),
    "achievement": ("name", "issuer", "date", "url", "description"),
    "simple_list": ("content",),
}
ITEM_LIST_FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    "education": ("highlights",),
    "experience": ("highlights",),
    "project": ("techStack", "highlights"),
    "publication": (),
    "achievement": (),
    "simple_list": (),
}
ITEM_FIELDS_BY_KIND: dict[str, tuple[str, ...]] = {
    kind: ("id", *ITEM_STRING_FIELDS_BY_KIND[kind], *ITEM_LIST_FIELDS_BY_KIND[kind])
    for kind in SECTION_KINDS
}


def is_resume_item_for_kind(value: object, kind: str) -> bool:
    """Return whether an item exactly matches one V2 section discriminator."""

    if not isinstance(value, dict) or kind not in ITEM_FIELDS_BY_KIND:
        return False
    if set(value) != set(ITEM_FIELDS_BY_KIND[kind]):
        return False
    item_id = value.get("id")
    if not isinstance(item_id, str) or not RESUME_NODE_ID_PATTERN.fullmatch(item_id):
        return False
    if any(
        not isinstance(value.get(field), str)
        for field in ITEM_STRING_FIELDS_BY_KIND[kind]
    ):
        return False
    return all(
        isinstance(entries := value.get(field), list)
        and all(isinstance(entry, str) for entry in entries)
        for field in ITEM_LIST_FIELDS_BY_KIND[kind]
    )


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


@lru_cache(maxsize=1)
def _resume_document_validator() -> Draft7Validator:
    return Draft7Validator(resume_document_schema())


def _validation_path(error: object) -> str:
    """Translate one jsonschema error path to the stable API path format."""

    absolute_path = getattr(error, "absolute_path", ())
    suffix = ".".join(str(part) for part in absolute_path)
    return f"resume.{suffix}" if suffix else "resume"


def validate_resume_document(value: Any) -> dict[str, Any]:
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

    section_ids: set[str] = set()
    item_ids: set[str] = set()
    for section_index, section in enumerate(value["sections"]):
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

    return cast(dict[str, Any], value)
