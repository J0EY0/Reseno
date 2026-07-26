import inspect

from app.services.agent.tools.registry import (
    AGENT_TOOL_SCHEMAS,
    AGENT_TOOL_SPECS,
    AGENT_TOOL_SPECS_BY_NAME,
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
