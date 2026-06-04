from typing import Any

from ..prompts import EDIT_OPERATION_GUIDE

AGENT_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "jd_url_fetch",
            "description": "Fetch and extract text from a user-provided JD URL.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The job description URL to fetch.",
                    },
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "jd_reference_search",
            "description": (
                "Search the web for a target-role JD when the user did not "
                "provide a JD URL. Do not use this for a normal resume edit "
                "unless the user explicitly asks for target-role or JD matching."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query for the target role JD.",
                    },
                    "role": {
                        "type": "string",
                        "description": "Target role inferred from the user prompt.",
                    },
                    "language": {
                        "type": "string",
                        "enum": ["zh", "en"],
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "resume_analysis",
            "description": "Analyze the current structured resume JSON.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
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
                                        "One of replace_field, update_item, "
                                        "insert_item, insert_section, update_section, "
                                        "delete_item, delete_section, reorder_items, "
                                        "reorder_sections."
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
                                    "type": "object",
                                    "description": (
                                        "Optional frontend ResumeEditOperation. "
                                        "If present, edit_execute can reuse it. "
                                        f"{EDIT_OPERATION_GUIDE}"
                                    ),
                                    "additionalProperties": True,
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
    },
    {
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
                                    "type": "object",
                                    "description": EDIT_OPERATION_GUIDE,
                                    "additionalProperties": True,
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
    },
    {
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
                        "description": (
                            "Short reason based on the latest Observation."
                        ),
                    },
                },
                "required": ["status", "reason"],
                "additionalProperties": False,
            },
        },
    },
]

__all__ = ["AGENT_TOOL_SCHEMAS"]
