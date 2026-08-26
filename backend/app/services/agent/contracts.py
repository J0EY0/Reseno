"""Canonical resume-agent tool and edit-operation contracts."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

# jsonschema has no bundled stubs in this environment. Keep the suppression at
# the dependency boundary so the rest of the module remains strict.
from jsonschema import Draft7Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import best_match  # type: ignore[import-untyped]

from app.schemas.agent import AgentChatRequest
from app.schemas.agent_settings import AgentConfirmationMode

from .adapters.attachments import historical_text_attachment_files
from .preferences import execution_profile_for_request

_SCHEMA_PATH = Path(__file__).with_name("resume_edit_operation.schema.json")
_RESUME_SCHEMA_PATH = _SCHEMA_PATH.parent.parent / "resume_document.schema.json"
_RESUME_SCHEMA_REFERENCE = "https://resumate.local/schemas/resume-document-v2.json"


def _schema_target(root: dict[str, Any], reference: str) -> object:
    """Resolve a JSON pointer within one loaded schema."""

    if not reference.startswith("#/"):
        raise RuntimeError(f"Unsupported schema reference: {reference}.")

    target: object = root
    for raw_part in reference[2:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if not isinstance(target, dict) or part not in target:
            raise RuntimeError(f"Invalid schema reference: {reference}.")
        target = target[part]
    return target


def _inline_schema_references(
    value: object,
    *,
    resume_root: dict[str, Any],
    current_root: dict[str, Any],
    resolving: tuple[tuple[int, str], ...] = (),
) -> object:
    """Materialize operation and ResumeDocument references for provider tools."""

    if isinstance(value, list):
        return [
            _inline_schema_references(
                item,
                resume_root=resume_root,
                current_root=current_root,
                resolving=resolving,
            )
            for item in value
        ]
    if not isinstance(value, dict):
        return value

    reference = value.get("$ref")
    if isinstance(reference, str):
        if reference.startswith("#/"):
            target_root = current_root
            pointer = reference
        elif reference.startswith(f"{_RESUME_SCHEMA_REFERENCE}#/"):
            target_root = resume_root
            pointer = reference.removeprefix(_RESUME_SCHEMA_REFERENCE)
        else:
            raise RuntimeError(f"Unsupported schema reference: {reference}.")

        marker = (id(target_root), pointer)
        if marker in resolving:
            raise RuntimeError(f"Schema reference cycle at {reference}.")
        resolved = _inline_schema_references(
            _schema_target(target_root, pointer),
            resume_root=resume_root,
            current_root=target_root,
            resolving=(*resolving, marker),
        )
        if not isinstance(resolved, dict):
            return resolved
        siblings = {
            key: item
            for key, item in value.items()
            if key not in {"$ref", "x-typescript-type"}
        }
        resolved_siblings = _inline_schema_references(
            siblings,
            resume_root=resume_root,
            current_root=current_root,
            resolving=resolving,
        )
        if not isinstance(resolved_siblings, dict):
            raise RuntimeError("Schema reference siblings must form an object.")
        return {
            **resolved,
            **resolved_siblings,
        }

    return {
        key: _inline_schema_references(
            item,
            resume_root=resume_root,
            current_root=current_root,
            resolving=resolving,
        )
        for key, item in value.items()
    }


@lru_cache(maxsize=1)
def resume_edit_operation_schema() -> dict[str, Any]:
    """Load the operation union with canonical ResumeDocument shapes inlined."""

    payload = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    resume_payload = json.loads(_RESUME_SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(resume_payload, dict):
        raise RuntimeError("Resume edit operation schema must be a JSON object.")
    materialized = _inline_schema_references(
        payload,
        resume_root=resume_payload,
        current_root=payload,
    )
    if not isinstance(materialized, dict):
        raise RuntimeError("Resume edit operation schema must be a JSON object.")
    Draft7Validator.check_schema(materialized)
    return materialized


@lru_cache(maxsize=1)
def _resume_edit_operation_validator() -> Draft7Validator:
    return Draft7Validator(resume_edit_operation_schema())


def resume_edit_operation_error(operation: object) -> str | None:
    """Return the most useful canonical operation validation error, if any."""

    validator = _resume_edit_operation_validator()
    if isinstance(operation, dict) and isinstance(operation.get("type"), str):
        operation_type = operation["type"]
        operation_schema = next(
            (
                branch
                for branch in resume_edit_operation_schema()["oneOf"]
                if branch.get("properties", {}).get("type", {}).get("const")
                == operation_type
            ),
            None,
        )
        if isinstance(operation_schema, dict):
            validator = Draft7Validator(
                _specialize_insert_item_schema(operation_schema, operation),
            )

    error = best_match(validator.iter_errors(operation))
    if error is None:
        return None
    path = ".".join(str(part) for part in error.absolute_path)
    return f"{path}: {error.message}" if path else error.message


def _specialize_insert_item_schema(
    operation_schema: dict[str, Any],
    operation: dict[str, Any],
) -> dict[str, Any]:
    """Choose the closest item branch so repair observations name missing fields."""

    if operation.get("type") != "insert_item" or not isinstance(
        item := operation.get("item"),
        dict,
    ):
        return operation_schema

    properties = operation_schema.get("properties")
    if not isinstance(properties, dict):
        return operation_schema
    item_schema = properties.get("item")
    branches = item_schema.get("oneOf") if isinstance(item_schema, dict) else None
    if not isinstance(branches, list):
        return operation_schema

    candidates = [branch for branch in branches if isinstance(branch, dict)]
    scored = [
        (
            len(set(item) & set(branch_properties)),
            branch,
        )
        for branch in candidates
        if isinstance(branch_properties := branch.get("properties"), dict)
    ]
    if not scored:
        return operation_schema

    best_score = max(score for score, _branch in scored)
    best = [branch for score, branch in scored if score == best_score]
    if best_score < 1 or len(best) != 1:
        return operation_schema

    return {
        **operation_schema,
        "properties": {
            **properties,
            "item": best[0],
        },
    }


def _relax_item_for_model(item_schema: dict[str, Any]) -> None:
    """Let the model omit empty canonical fields from an inserted item."""

    branches = item_schema.get("oneOf")
    if isinstance(branches, list):
        for branch in branches:
            if isinstance(branch, dict):
                branch["required"] = ["id"]
        return
    item_schema["required"] = ["id"]


def _relax_model_insert_shapes(schema: dict[str, Any]) -> None:
    """Derive the compact model input view from the canonical operation union."""

    for branch in schema["oneOf"]:
        properties = branch.get("properties", {})
        operation_type = properties.get("type", {}).get("const")
        if operation_type == "insert_item":
            item_schema = properties.get("item")
            if isinstance(item_schema, dict):
                _relax_item_for_model(item_schema)
        elif operation_type == "insert_section":
            section_schema = properties.get("section", {})
            section_branches = section_schema.get("oneOf", [])
            for section_branch in section_branches:
                if not isinstance(section_branch, dict):
                    continue
                section_properties = section_branch.get("properties", {})
                kind = section_properties.get("kind", {}).get("const")
                section_branch["required"] = (
                    ["id", "kind", "items"]
                    if kind == "simple_list"
                    else ["id", "kind"]
                )
                items_schema = section_properties.get("items", {})
                item_schema = items_schema.get("items")
                if isinstance(item_schema, dict):
                    _relax_item_for_model(item_schema)


def _model_operation_schema() -> dict[str, Any]:
    """Build the self-contained model schema from the canonical operation union."""

    canonical = resume_edit_operation_schema()
    branches = canonical.get("oneOf")
    if not isinstance(branches, list) or not branches:
        raise RuntimeError("Resume edit operation schema must define oneOf variants.")

    signatures = [
        (
            f"{branch['properties']['type']['const']}"
            f"({', '.join(field for field in branch['required'] if field != 'type')})"
        )
        for branch in branches
    ]
    description = (
        f"{canonical.get('description', '').strip()} "
        f"Inputs by type: {'; '.join(signatures)}."
    ).strip()
    inlined = deepcopy({"description": description, "oneOf": branches})
    if not isinstance(inlined, dict):
        raise RuntimeError("Model operation schema must be a JSON object.")
    _relax_model_insert_shapes(inlined)
    Draft7Validator.check_schema(inlined)
    return inlined


OPERATION_SCHEMA: dict[str, Any] = _model_operation_schema()

AgentToolMode = Literal["read", "write"]


@dataclass(frozen=True)
class AgentToolSpec:
    """Static metadata for one model-visible agent tool."""

    name: str
    mode: AgentToolMode
    schema: dict[str, Any]


WEB_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the public web with one focused query and read the most relevant "
            "pages. For current roles, prefer readable employer or ATS postings; "
            "use the fewest primary sources sufficient for the requested claim "
            "instead of aggregators or resume guides. The result separates read "
            "references from discovery candidates. References are already read and "
            "contain sourceId, relevant page passages, and available page dates as "
            "publishedDate or validThrough; never pass a reference URL to web_fetch. "
            "Readable references do not by themselves prove authority, recency, or "
            "page type. Candidates contain search snippets only and are not factual "
            "sources; use web_fetch on a candidate URL before relying on its details."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                    "pattern": r"\S",
                    "description": "A concise public-web search query.",
                },
                "timeRange": {
                    "type": "string",
                    "enum": ["day", "week", "month", "year"],
                    "description": (
                        "Optional publish/update recency filter for time-sensitive "
                        "opportunities. Omit it for evergreen pages."
                    ),
                },
                "includeDomains": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 253,
                        "pattern": r"^[A-Za-z0-9.-]+$",
                    },
                    "maxItems": 5,
                    "uniqueItems": True,
                    "description": (
                        "Optional bare-hostname allowlist. Use it only when the actual "
                        "page host is known; official jobs may live on an external ATS."
                    ),
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

WEB_FETCH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": (
            "Read a relevant public URL supplied by the user, returned by web_search, "
            "or retained from history. Use it when material page detail or status "
            "is still missing from the available references. The result contains a "
            "citable reference with relevant page passages and available page dates. "
            "Readable references do not by themselves prove authority, recency, or "
            "page type."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "minLength": 1,
                    "pattern": r"\S",
                    "description": "A relevant public HTTP(S) URL to fetch.",
                },
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
}

ATTACHMENT_READ_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "attachment_read",
        "description": (
            "Read text from an attachment listed in historicalAttachments. "
            "Use nextOffset to continue only when the needed detail is not in "
            "the returned excerpt. Current-turn attachments are already in context."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "attachmentId": {
                    "type": "string",
                    "minLength": 1,
                    "description": "The opaque id from historicalAttachments.",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Optional nextOffset from an earlier read.",
                },
            },
            "required": ["attachmentId"],
            "additionalProperties": False,
        },
    },
}

EDIT_EXECUTE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "edit_execute",
        "description": (
            "Create one complete preview batch for explicit resume edits after "
            "the target field, sectionId, or itemId is known. Keep normalization to "
            "requested fields or clearly misplaced values needed to complete that "
            "request; avoid adjacent cleanup. Improve prose only where "
            "requested. Move existing facts instead of duplicating them and omit "
            "exact no-op operations. When one request spans basic fields and section "
            "items, include every requested operation together in the edits array."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "minItems": 1,
                    "description": (
                        "Executable edits. Each edit includes one canonical "
                        "ResumeEditOperation object."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "operation": OPERATION_SCHEMA,
                        },
                        "required": ["operation"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["edits"],
            "additionalProperties": False,
        },
    },
}

AGENT_TOOL_SPECS: list[AgentToolSpec] = [
    AgentToolSpec("web_search", "read", WEB_SEARCH_SCHEMA),
    AgentToolSpec("web_fetch", "read", WEB_FETCH_SCHEMA),
    AgentToolSpec("attachment_read", "read", ATTACHMENT_READ_SCHEMA),
    AgentToolSpec("edit_execute", "write", EDIT_EXECUTE_SCHEMA),
]

AGENT_TOOL_SPECS_BY_NAME = {spec.name: spec for spec in AGENT_TOOL_SPECS}
if len(AGENT_TOOL_SPECS_BY_NAME) != len(AGENT_TOOL_SPECS):
    raise RuntimeError("Agent tool contracts contain duplicate tool names.")

AGENT_TOOL_SCHEMAS = [spec.schema for spec in AGENT_TOOL_SPECS]
WEB_TOOL_NAMES = frozenset({"web_search", "web_fetch"})


def agent_tool_specs_for_request(
    request: AgentChatRequest,
    *,
    include_web_tools: bool = True,
) -> tuple[AgentToolSpec, ...]:
    """Select the canonical model-visible tools for one frozen request."""

    has_historical_text = bool(historical_text_attachment_files(request))
    specs = [
        spec
        for spec in AGENT_TOOL_SPECS
        if (include_web_tools or spec.name not in WEB_TOOL_NAMES)
        and (spec.name != "attachment_read" or has_historical_text)
    ]
    if (
        execution_profile_for_request(request).confirmation_mode
        is AgentConfirmationMode.SUGGEST_ONLY
    ):
        return tuple(spec for spec in specs if spec.mode != "write")
    return tuple(specs)


def agent_tool_spec(tool_name: str) -> AgentToolSpec | None:
    """Return the single registered execution contract for a tool name."""

    return AGENT_TOOL_SPECS_BY_NAME.get(tool_name)


__all__ = [
    "AGENT_TOOL_SCHEMAS",
    "AGENT_TOOL_SPECS",
    "AGENT_TOOL_SPECS_BY_NAME",
    "ATTACHMENT_READ_SCHEMA",
    "EDIT_EXECUTE_SCHEMA",
    "OPERATION_SCHEMA",
    "WEB_FETCH_SCHEMA",
    "WEB_SEARCH_SCHEMA",
    "WEB_TOOL_NAMES",
    "AgentToolMode",
    "AgentToolSpec",
    "agent_tool_spec",
    "agent_tool_specs_for_request",
    "resume_edit_operation_error",
    "resume_edit_operation_schema",
]
