from dataclasses import dataclass
from typing import Any, Literal

from ..models import FINISH_MISSING_ENUM, PLAN_INTENT_ENUM
from ..prompts import EDIT_OPERATION_GUIDE
from ..section_registry import SECTION_KIND_ENUM

ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "title": {
            "type": "string",
            "description": (
                "Project, company, school, certificate, or award name only."
            ),
        },
        "subtitle": {
            "type": "string",
            "description": "Role, position, major, degree, or identity only.",
        },
        "meta": {
            "type": "string",
            "description": "Tech stack, GPA, location, organization, or metadata.",
        },
        "period": {
            "type": "string",
            "description": "Time range only. Use this for date/date range.",
        },
        "description": {
            "type": "string",
            "description": "One short background sentence only; may be empty.",
        },
        "highlights": {
            "type": "array",
            "description": (
                "Concrete actions, technical solutions, outcomes, and impact. "
                "Do not repeat title, subtitle, meta, or period."
            ),
            "items": {"type": "string"},
        },
    },
    "additionalProperties": False,
}

SECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "section_type": {
            "type": "string",
            "enum": SECTION_KIND_ENUM,
            "description": (
                "Standard resume section type. Use this instead of inventing "
                "free-form module names."
            ),
        },
        "kind": {
            "type": "string",
            "enum": SECTION_KIND_ENUM,
            "description": "Backward-compatible alias for section_type.",
        },
        "layout": {"type": "string", "enum": ["timeline", "list"]},
        "customTitle": {
            "type": "string",
            "description": "Only use for section_type=custom; otherwise leave empty.",
        },
        "items": {"type": "array", "items": ITEM_SCHEMA},
    },
    "required": ["section_type", "layout", "items"],
    "additionalProperties": False,
}

ITEM_PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subtitle": {"type": "string"},
        "meta": {"type": "string"},
        "period": {"type": "string"},
        "description": {"type": "string"},
        "highlights": {"type": "array", "items": {"type": "string"}},
    },
    "minProperties": 1,
    "additionalProperties": False,
}

SECTION_PATCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": SECTION_KIND_ENUM},
        "section_type": {"type": "string", "enum": SECTION_KIND_ENUM},
        "layout": {"type": "string", "enum": ["timeline", "list"]},
        "customTitle": {"type": "string"},
    },
    "minProperties": 1,
    "additionalProperties": False,
}


def _operation_variant(
    operation_type: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    """Return one operation-specific schema branch."""

    return {
        "type": "object",
        "properties": {
            "type": {"type": "string", "enum": [operation_type]},
            **properties,
        },
        "required": ["type", *required],
        "additionalProperties": False,
    }


OPERATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "oneOf": [
        _operation_variant(
            "replace_field",
            {
                "path": {"type": "string"},
                "value": {"type": "string"},
            },
            ["path", "value"],
        ),
        _operation_variant(
            "insert_section",
            {
                "section": SECTION_SCHEMA,
                "index": {"type": "integer"},
            },
            ["section"],
        ),
        _operation_variant(
            "update_section",
            {
                "sectionId": {"type": "string"},
                "patch": SECTION_PATCH_SCHEMA,
            },
            ["sectionId", "patch"],
        ),
        _operation_variant(
            "delete_section",
            {"sectionId": {"type": "string"}},
            ["sectionId"],
        ),
        _operation_variant(
            "reorder_sections",
            {"sectionIds": {"type": "array", "items": {"type": "string"}}},
            ["sectionIds"],
        ),
        _operation_variant(
            "insert_item",
            {
                "sectionId": {"type": "string"},
                "item": ITEM_SCHEMA,
                "index": {"type": "integer"},
            },
            ["sectionId", "item"],
        ),
        _operation_variant(
            "update_item",
            {
                "sectionId": {"type": "string"},
                "itemId": {"type": "string"},
                "patch": ITEM_PATCH_SCHEMA,
            },
            ["sectionId", "itemId", "patch"],
        ),
        _operation_variant(
            "delete_item",
            {
                "sectionId": {"type": "string"},
                "itemId": {"type": "string"},
            },
            ["sectionId", "itemId"],
        ),
        _operation_variant(
            "reorder_items",
            {
                "sectionId": {"type": "string"},
                "itemIds": {"type": "array", "items": {"type": "string"}},
            },
            ["sectionId", "itemIds"],
        ),
    ],
}

AgentToolMode = Literal["read", "write", "control"]


@dataclass(frozen=True)
class AgentToolSpec:
    """Static metadata for one model-visible agent tool."""

    name: str
    mode: AgentToolMode
    schema: dict[str, Any]
    handler_name: str
    requires_pending_draft: bool = False


WEB_FETCH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": (
            "Fetch and extract text from a user-provided URL for an explicit "
            "resume-editing purpose. Do not infer personal experience facts "
            "from fetched pages; use them only as reference material."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The user-provided URL to fetch.",
                },
                "purpose": {
                    "type": "string",
                    "enum": [
                        "jd",
                        "project_reference",
                        "portfolio_reference",
                        "company_reference",
                    ],
                    "description": (
                        "Why this URL should be fetched. If unsure, ask the "
                        "user before calling this tool."
                    ),
                },
            },
            "required": ["url", "purpose"],
            "additionalProperties": False,
        },
    },
}

WEB_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": (
            "Search the web only for target role, JD, company, or public "
            "reference context. For role exploration, prefer one call with "
            "3-5 complementary queries and summarize the combined results. "
            "Never use search as evidence for the user's personal experience."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Single search query for external reference context."
                    ),
                },
                "queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 1,
                    "maxItems": 5,
                    "description": (
                        "Optional complementary queries for one search task, "
                        "such as responsibilities, required skills, and resume "
                        "keywords for the same target role."
                    ),
                },
                "maxResults": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 10,
                    "description": (
                        "Maximum deduplicated search references to return. "
                        "Use up to 10 for role exploration."
                    ),
                },
                "role": {
                    "type": "string",
                    "description": "Target role inferred from the user prompt.",
                },
                "purpose": {
                    "type": "string",
                    "enum": ["jd", "target_context", "company_reference"],
                },
                "language": {
                    "type": "string",
                    "enum": ["zh", "en"],
                },
            },
            "required": ["purpose"],
            "additionalProperties": False,
        },
    },
}

MATERIAL_EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "material_extract",
        "description": (
            "Extract bounded, sanitized candidate resume facts from the user's "
            "prompt, pasted job brief, or uploaded attachments. Use this before "
            "drafting from newly supplied materials. This tool does not write "
            "the resume and does not verify facts."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "enum": [
                        "all",
                        "resume_facts",
                        "experience",
                        "project",
                        "work",
                        "internship",
                        "skills",
                        "education",
                        "jd",
                    ],
                    "description": (
                        "Which kind of material to extract. Use resume_facts "
                        "for user-provided resume evidence and jd for job text."
                    ),
                },
                "maxItems": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 8,
                    "description": "Maximum candidate snippets to return.",
                },
            },
            "additionalProperties": False,
        },
    },
}

RESUME_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "resume_analysis",
        "description": (
            "Analyze the current structured resume JSON, keyword gaps, and "
            "target-role fit hints for conservative resume editing."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
}

RESUME_LOOKUP_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "resume_lookup",
        "description": (
            "Locate specific resume sections or items by id, kind, or query. "
            "Use this when you need exact sectionId/itemId for a targeted edit "
            "instead of running broad resume analysis again."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": (
                        "Optional text to match against section/item content."
                    ),
                },
                "sectionId": {"type": "string"},
                "itemId": {"type": "string"},
                "sectionKind": {"type": "string", "enum": SECTION_KIND_ENUM},
                "includeItems": {
                    "type": "boolean",
                    "description": "Whether to include matching item snapshots.",
                },
            },
            "additionalProperties": False,
        },
    },
}

DRAFT_DIFF_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "draft_diff_summary",
        "description": (
            "Inspect the current pending draft edits/diffs so follow-up requests "
            "can explain, shorten, remove, or continue a previous draft."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
}

EDIT_PLAN_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "edit_plan",
        "description": (
            "Create a concise edit plan. Prefer providing explicit steps "
            "with the exact target and, when possible, the operation to execute."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "description": (
                        "Planned edits. Keep this limited to changes that "
                        "the user requested or that are directly supported."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "description": (
                                    "One of replace_field, update_item, insert_item, "
                                    "insert_section, update_section, delete_item, "
                                    "delete_section, reorder_items, reorder_sections."
                                ),
                            },
                            "intent": {
                                "type": "string",
                                "enum": PLAN_INTENT_ENUM,
                                "description": (
                                    "Optional machine-readable edit intent for "
                                    "draft-changing plans. Do not use this for "
                                    "explaining an existing draft; use "
                                    "draft_diff_summary and a natural-language answer "
                                    "instead."
                                ),
                            },
                            "target": {
                                "type": "string",
                                "description": (
                                    "Frontend target path, e.g. basic.summary "
                                    "or sections.<sectionId>.items.<itemId>."
                                ),
                            },
                            "reason": {"type": "string"},
                            "title": {"type": "string"},
                            "replacement": {
                                "type": "string",
                                "description": (
                                    "Short human-readable replacement preview."
                                ),
                            },
                            "operation": {
                                **OPERATION_SCHEMA,
                                "description": (
                                    "Optional frontend ResumeEditOperation. "
                                    "If present, edit_execute can reuse it. "
                                    f"{EDIT_OPERATION_GUIDE}"
                                ),
                            },
                        },
                        "required": ["action", "target", "reason"],
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
    },
}

EDIT_EXECUTE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "edit_execute",
        "description": (
            "Execute explicit draft edit operations. Use this only after "
            "you know the target field, sectionId, or itemId."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "description": (
                        "Executable edits. Each edit must include a frontend "
                        "ResumeEditOperation object."
                    ),
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "target": {"type": "string"},
                            "reason": {"type": "string"},
                            "replacement": {"type": "string"},
                            "operation": {
                                **OPERATION_SCHEMA,
                                "description": EDIT_OPERATION_GUIDE,
                            },
                        },
                        "required": ["title", "target", "reason", "operation"],
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": False,
        },
    },
}

EDIT_MOVE_ITEM_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "edit_move_item",
        "description": (
            "Move one existing resume item within a section or into another "
            "existing section. Use after resume_lookup/resume_analysis has "
            "identified sectionId and itemId."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "fromSectionId": {"type": "string"},
                "toSectionId": {"type": "string"},
                "itemId": {"type": "string"},
                "index": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["fromSectionId", "toSectionId", "itemId"],
            "additionalProperties": False,
        },
    },
}

EDIT_SPLIT_ITEM_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "edit_split_item",
        "description": (
            "Split one long resume item into two clearer items in the same "
            "section. The first object patches the existing item; the second "
            "object becomes the inserted item."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sectionId": {"type": "string"},
                "itemId": {"type": "string"},
                "first": ITEM_PATCH_SCHEMA,
                "second": ITEM_SCHEMA,
                "index": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["sectionId", "itemId", "first", "second"],
            "additionalProperties": False,
        },
    },
}

EDIT_MERGE_ITEMS_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "edit_merge_items",
        "description": (
            "Merge multiple related resume items into the first item and delete "
            "the rest. Use only when the items represent the same experience "
            "or should be consolidated."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sectionId": {"type": "string"},
                "itemIds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 2,
                },
                "mergedItem": ITEM_PATCH_SCHEMA,
                "reason": {"type": "string"},
            },
            "required": ["sectionId", "itemIds", "mergedItem"],
            "additionalProperties": False,
        },
    },
}

SKILLS_CLASSIFY_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "skills_classify",
        "description": (
            "Create or replace grouped skill items in the skills section. Use "
            "this when the user asks to organize, categorize, or normalize skills."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "sectionId": {"type": "string"},
                "groups": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "skills": {
                                "type": "array",
                                "items": {"type": "string"},
                            },
                        },
                        "required": ["title", "skills"],
                        "additionalProperties": False,
                    },
                },
                "index": {"type": "integer"},
                "reason": {"type": "string"},
            },
            "required": ["groups"],
            "additionalProperties": False,
        },
    },
}

DRAFT_REWRITE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "draft_rewrite",
        "description": (
            "Apply additional explicit edits to the current pending draft. Use "
            "this for follow-up requests such as making a previous draft item "
            "shorter, more specific, or reverting one suggested edit."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "edits": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "target": {"type": "string"},
                            "reason": {"type": "string"},
                            "replacement": {"type": "string"},
                            "operation": OPERATION_SCHEMA,
                        },
                        "required": ["title", "target", "reason", "operation"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["edits"],
            "additionalProperties": False,
        },
    },
}

FINISH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "finish",
        "description": (
            "Finish the ReAct loop after the latest observations show that "
            "the current draft satisfies the user request, or that the task "
            "is blocked and needs user input."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "enum": ["ready", "blocked"],
                    "description": "Whether the draft is ready or blocked.",
                },
                "reason": {
                    "type": "string",
                    "description": "Short reason based on the latest Observation.",
                },
                "missing": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": FINISH_MISSING_ENUM,
                    },
                    "description": (
                        "Structured missing context when status=blocked. "
                        "Leave empty when the task is ready."
                    ),
                },
            },
            "required": ["status", "reason"],
            "additionalProperties": False,
        },
    },
}

AGENT_TOOL_SPECS: list[AgentToolSpec] = [
    AgentToolSpec("web_fetch", "read", WEB_FETCH_SCHEMA, "run_web_fetch_async"),
    AgentToolSpec("web_search", "read", WEB_SEARCH_SCHEMA, "run_web_search_async"),
    AgentToolSpec(
        "material_extract",
        "read",
        MATERIAL_EXTRACT_SCHEMA,
        "run_material_extract",
    ),
    AgentToolSpec(
        "resume_analysis",
        "read",
        RESUME_ANALYSIS_SCHEMA,
        "run_resume_analysis",
    ),
    AgentToolSpec("resume_lookup", "read", RESUME_LOOKUP_SCHEMA, "run_resume_lookup"),
    AgentToolSpec(
        "draft_diff_summary",
        "read",
        DRAFT_DIFF_SUMMARY_SCHEMA,
        "run_draft_diff_summary",
    ),
    AgentToolSpec("edit_plan", "write", EDIT_PLAN_SCHEMA, "run_edit_plan"),
    AgentToolSpec("edit_execute", "write", EDIT_EXECUTE_SCHEMA, "run_edit_execute"),
    AgentToolSpec(
        "edit_move_item",
        "write",
        EDIT_MOVE_ITEM_SCHEMA,
        "run_edit_move_item",
    ),
    AgentToolSpec(
        "edit_split_item",
        "write",
        EDIT_SPLIT_ITEM_SCHEMA,
        "run_edit_split_item",
    ),
    AgentToolSpec(
        "edit_merge_items",
        "write",
        EDIT_MERGE_ITEMS_SCHEMA,
        "run_edit_merge_items",
    ),
    AgentToolSpec(
        "skills_classify",
        "write",
        SKILLS_CLASSIFY_SCHEMA,
        "run_skills_classify",
    ),
    AgentToolSpec(
        "draft_rewrite",
        "write",
        DRAFT_REWRITE_SCHEMA,
        "run_draft_rewrite",
        requires_pending_draft=True,
    ),
    AgentToolSpec("finish", "control", FINISH_SCHEMA, "run_finish"),
]

AGENT_TOOL_SCHEMAS = [spec.schema for spec in AGENT_TOOL_SPECS]
WEB_FETCH_TOOL_NAMES = frozenset({"web_fetch"})
WEB_SEARCH_TOOL_NAMES = frozenset({"web_search"})
CONTROL_TOOL_NAMES = frozenset(
    spec.name for spec in AGENT_TOOL_SPECS if spec.mode == "control"
)
FOLLOWUP_DRAFT_TOOL_NAMES = frozenset(
    spec.name for spec in AGENT_TOOL_SPECS if spec.requires_pending_draft
)
DRAFT_WRITE_TOOL_NAMES = frozenset(
    spec.name
    for spec in AGENT_TOOL_SPECS
    if spec.mode == "write" and not spec.requires_pending_draft
)
LOCAL_READ_TOOL_NAMES = frozenset(
    spec.name
    for spec in AGENT_TOOL_SPECS
    if spec.mode == "read"
    and spec.name not in WEB_FETCH_TOOL_NAMES
    and spec.name not in WEB_SEARCH_TOOL_NAMES
)
READ_TOOL_NAMES = LOCAL_READ_TOOL_NAMES | WEB_FETCH_TOOL_NAMES | WEB_SEARCH_TOOL_NAMES
WRITE_TOOL_NAMES = DRAFT_WRITE_TOOL_NAMES | FOLLOWUP_DRAFT_TOOL_NAMES
ALL_KNOWN_TOOL_NAMES = READ_TOOL_NAMES | WRITE_TOOL_NAMES | CONTROL_TOOL_NAMES


def agent_tool_schemas_for_names(
    tool_names: set[str] | frozenset[str],
) -> list[dict[str, Any]]:
    """Return registered tool schemas in stable order for allowed tool names."""

    return [spec.schema for spec in AGENT_TOOL_SPECS if spec.name in tool_names]


__all__ = [
    "AGENT_TOOL_SCHEMAS",
    "AGENT_TOOL_SPECS",
    "ALL_KNOWN_TOOL_NAMES",
    "CONTROL_TOOL_NAMES",
    "DRAFT_WRITE_TOOL_NAMES",
    "FOLLOWUP_DRAFT_TOOL_NAMES",
    "LOCAL_READ_TOOL_NAMES",
    "READ_TOOL_NAMES",
    "SECTION_KIND_ENUM",
    "WEB_FETCH_TOOL_NAMES",
    "WEB_SEARCH_TOOL_NAMES",
    "WRITE_TOOL_NAMES",
    "AgentToolSpec",
    "agent_tool_schemas_for_names",
]
