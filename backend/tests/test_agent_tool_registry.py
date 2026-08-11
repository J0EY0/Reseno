import inspect

from jsonschema import Draft7Validator

from app.services.agent.tools.registry import (
    AGENT_TOOL_SCHEMAS,
    AGENT_TOOL_SPECS,
    AGENT_TOOL_SPECS_BY_NAME,
    DRAFT_REWRITE_SCHEMA,
    EDIT_EXECUTE_SCHEMA,
    EDIT_MOVE_ITEM_SCHEMA,
    EDIT_PLAN_SCHEMA,
    FINISH_SCHEMA,
    SKILLS_CLASSIFY_SCHEMA,
    UPDATE_TARGET_CONTEXT_SCHEMA,
    agent_tool_spec,
)
from app.services.agent.tools.runner import AgentToolRunner


def test_tool_registry_is_the_execution_source_of_truth() -> None:
    assert len(AGENT_TOOL_SPECS_BY_NAME) == len(AGENT_TOOL_SPECS)
    assert [schema["function"]["name"] for schema in AGENT_TOOL_SCHEMAS] == [
        spec.name for spec in AGENT_TOOL_SPECS
    ]

    for spec in AGENT_TOOL_SPECS:
        handler = getattr(AgentToolRunner, spec.handler_name)

        assert agent_tool_spec(spec.name) is spec
        assert spec.schema["function"]["name"] == spec.name
        assert inspect.iscoroutinefunction(handler) is (spec.execution == "async")


def test_unknown_tool_has_no_registered_execution_contract() -> None:
    assert agent_tool_spec("not-a-real-tool") is None


def test_edit_tools_require_one_or_more_explicit_entries() -> None:
    for schema, field in (
        (EDIT_PLAN_SCHEMA, "steps"),
        (EDIT_EXECUTE_SCHEMA, "edits"),
        (DRAFT_REWRITE_SCHEMA, "edits"),
    ):
        parameters = schema["function"]["parameters"]

        assert parameters["required"] == [field]
        assert parameters["properties"][field]["minItems"] == 1


def test_target_context_clear_has_no_fake_context_field() -> None:
    validator = Draft7Validator(
        UPDATE_TARGET_CONTEXT_SCHEMA["function"]["parameters"],
    )

    assert list(validator.iter_errors({"mode": "clear", "context": {}})) == []
    assert list(
        validator.iter_errors(
            {"mode": "clear", "context": {"kind": "general"}},
        ),
    )
    assert list(validator.iter_errors({"mode": "merge", "context": {}}))


def test_edit_plan_exposes_only_executable_non_empty_steps() -> None:
    validator = Draft7Validator(EDIT_PLAN_SCHEMA["function"]["parameters"])
    step = {
        "action": "replace_field",
        "target": "basic.summary",
        "reason": "Make the requested summary shorter.",
    }

    assert list(validator.iter_errors({"steps": [step]})) == []
    assert (
        "intent" not in validator.schema["properties"]["steps"]["items"]["properties"]
    )
    assert list(
        validator.iter_errors(
            {"steps": [{**step, "action": "invent_a_new_operation"}]},
        ),
    )
    for field in ("action", "target", "reason"):
        assert list(
            validator.iter_errors({"steps": [{**step, field: ""}]}),
        )
    for field in ("target", "reason"):
        assert list(
            validator.iter_errors({"steps": [{**step, field: "   "}]}),
        )


def test_structured_write_tools_reject_empty_required_values() -> None:
    move_validator = Draft7Validator(
        EDIT_MOVE_ITEM_SCHEMA["function"]["parameters"],
    )
    skills_validator = Draft7Validator(
        SKILLS_CLASSIFY_SCHEMA["function"]["parameters"],
    )
    finish_validator = Draft7Validator(FINISH_SCHEMA["function"]["parameters"])

    assert list(
        move_validator.iter_errors(
            {"fromSectionId": "", "toSectionId": "projects", "itemId": "p1"},
        ),
    )
    assert list(
        move_validator.iter_errors(
            {"fromSectionId": "   ", "toSectionId": "projects", "itemId": "p1"},
        ),
    )
    assert list(skills_validator.iter_errors({"groups": []}))
    assert list(
        skills_validator.iter_errors(
            {"groups": [{"title": "", "skills": [""]}]},
        ),
    )
    assert list(
        skills_validator.iter_errors(
            {"groups": [{"title": "   ", "skills": ["   "]}]},
        ),
    )
    assert list(finish_validator.iter_errors({"status": "ready", "reason": ""}))
    assert list(
        finish_validator.iter_errors({"status": "ready", "reason": "   "}),
    )
