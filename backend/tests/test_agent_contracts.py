from typing import Any

from jsonschema import Draft7Validator

from app.schemas.agent import AgentChatRequest, AgentConversationItem
from app.schemas.agent_settings import normalize_agent_settings
from app.services.agent.contracts import (
    AGENT_TOOL_SCHEMAS,
    AGENT_TOOL_SPECS,
    AGENT_TOOL_SPECS_BY_NAME,
    ATTACHMENT_READ_SCHEMA,
    EDIT_EXECUTE_SCHEMA,
    OPERATION_SCHEMA,
    WEB_FETCH_SCHEMA,
    WEB_SEARCH_SCHEMA,
    WEB_TOOL_NAMES,
    agent_tool_spec,
    agent_tool_specs_for_request,
    resume_edit_operation_error,
    resume_edit_operation_schema,
)
from app.services.agent.preferences import prepare_agent_request
from app.services.agent.prompt import AGENT_PROMPT

EXPECTED_TOOL_NAMES = [
    "web_search",
    "web_fetch",
    "attachment_read",
    "edit_execute",
]
DEFAULT_TOOL_NAMES = ["web_search", "web_fetch", "edit_execute"]


def _operation_signatures(schema: dict[str, Any]) -> dict[str, frozenset[str]]:
    signatures: dict[str, frozenset[str]] = {}
    for branch in schema["oneOf"]:
        operation_type = branch["properties"]["type"]["const"]
        signatures[operation_type] = frozenset(branch["required"])
    return signatures


def _operation_branch(operation_type: str) -> dict[str, Any]:
    return next(
        branch
        for branch in OPERATION_SCHEMA["oneOf"]
        if branch["properties"]["type"]["const"] == operation_type
    )


def _contains_ref(value: object) -> bool:
    if isinstance(value, dict):
        return "$ref" in value or any(_contains_ref(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_ref(item) for item in value)
    return False


def test_model_operation_schema_inlines_the_canonical_variants() -> None:
    canonical = resume_edit_operation_schema()

    assert _operation_signatures(OPERATION_SCHEMA) == _operation_signatures(canonical)
    assert not _contains_ref(OPERATION_SCHEMA)
    Draft7Validator.check_schema(OPERATION_SCHEMA)


def test_edit_execute_embeds_the_generated_operation_schema() -> None:
    edit_item = EDIT_EXECUTE_SCHEMA["function"]["parameters"]["properties"]["edits"][
        "items"
    ]

    assert edit_item["properties"]["operation"] is OPERATION_SCHEMA
    assert _operation_signatures(edit_item["properties"]["operation"]) == (
        _operation_signatures(resume_edit_operation_schema())
    )


def test_contract_registry_contains_only_independent_tools_in_stable_order() -> None:
    assert [spec.name for spec in AGENT_TOOL_SPECS] == EXPECTED_TOOL_NAMES
    assert [
        schema["function"]["name"] for schema in AGENT_TOOL_SCHEMAS
    ] == EXPECTED_TOOL_NAMES
    assert len(AGENT_TOOL_SPECS_BY_NAME) == len(AGENT_TOOL_SPECS)
    assert all(agent_tool_spec(spec.name) is spec for spec in AGENT_TOOL_SPECS)
    assert agent_tool_spec("not-a-real-tool") is None


def test_contract_catalog_selects_tools_for_the_frozen_request() -> None:
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-contract-catalog",
            role="user",
            text="按需优化这份简历。",
        ),
        resume={"basic": {}, "sections": []},
    )
    suggest_only = prepare_agent_request(
        request,
        normalize_agent_settings({"confirmationMode": "suggestOnly"}),
    )

    assert [spec.name for spec in agent_tool_specs_for_request(request)] == (
        DEFAULT_TOOL_NAMES
    )
    assert [spec.name for spec in agent_tool_specs_for_request(suggest_only)] == [
        "web_search",
        "web_fetch",
    ]
    assert [
        spec.name
        for spec in agent_tool_specs_for_request(
            request,
            include_web_tools=False,
        )
    ] == ["edit_execute"]


def test_contract_catalog_progressively_discloses_historical_attachment_read() -> None:
    request = AgentChatRequest(
        message=AgentConversationItem(
            id="turn-read-history",
            role="user",
            text="Use the earlier notes.",
        ),
        messages=[
            AgentConversationItem(
                id="turn-with-notes",
                role="user",
                text="Keep these project facts.",
                files=[
                    {
                        "id": "11111111111141118111111111111111",
                        "filename": "notes.txt",
                        "kind": "text",
                    },
                ],
            ),
        ],
        resumeId="resumewithhistory",
        expectedRevision="1",
        resume={"basic": {}, "sections": []},
    )

    assert [spec.name for spec in agent_tool_specs_for_request(request)] == [
        "web_search",
        "web_fetch",
        "attachment_read",
        "edit_execute",
    ]
    assert [
        spec.name
        for spec in agent_tool_specs_for_request(
            request,
            include_web_tools=False,
        )
    ] == ["attachment_read", "edit_execute"]


def test_canonical_operation_error_is_used_for_model_operations() -> None:
    valid_operation = {
        "type": "replace_field",
        "path": "basic.summary",
        "value": "Outcome-focused engineer.",
    }
    invalid_operation = {
        "type": "replace_field",
        "path": "basic.location",
        "value": "Remote",
    }

    assert Draft7Validator(OPERATION_SCHEMA).is_valid(valid_operation)
    assert not Draft7Validator(OPERATION_SCHEMA).is_valid(invalid_operation)
    assert resume_edit_operation_error(valid_operation) is None
    assert resume_edit_operation_error(invalid_operation) is not None


def test_canonical_operation_error_uses_the_matching_variant() -> None:
    error = resume_edit_operation_error(
        {
            "type": "update_item",
            "sectionId": "project",
            "patch": {"highlights": ["Verified result"]},
        },
    )

    assert error is not None
    assert "itemId" in error


def test_web_tools_expose_focused_search_and_public_fetch() -> None:
    search = WEB_SEARCH_SCHEMA["function"]
    search_parameters = search["parameters"]
    fetch = WEB_FETCH_SCHEMA["function"]
    fetch_parameters = fetch["parameters"]

    assert WEB_TOOL_NAMES == frozenset({"web_search", "web_fetch"})
    assert set(search_parameters["properties"]) == {
        "query",
        "timeRange",
        "includeDomains",
    }
    assert search_parameters["required"] == ["query"]
    assert search_parameters["properties"]["timeRange"]["enum"] == [
        "day",
        "week",
        "month",
        "year",
    ]
    assert search_parameters["properties"]["includeDomains"]["maxItems"] == 5
    assert all(
        field in search["description"]
        for field in (
            "references",
            "candidates",
            "sourceId",
            "passages",
            "publishedDate",
            "validThrough",
        )
    )
    assert "employer or ATS postings" in search["description"]
    assert "fewest primary sources sufficient" in search["description"]
    assert "aggregators" in search["description"]
    assert "already read" in search["description"]
    assert "never pass a reference URL to web_fetch" in search["description"]
    assert "do not by themselves prove authority, recency, or page type" in (
        search["description"]
    )
    assert set(fetch_parameters["properties"]) == {"url"}
    assert fetch_parameters["required"] == ["url"]
    assert "material page detail" in fetch["description"]
    assert "citable reference" in fetch["description"]
    assert "do not by themselves prove authority, recency, or page type" in (
        fetch["description"]
    )
    assert "public HTTP(S) URL" in fetch_parameters["properties"]["url"]["description"]


def test_attachment_read_contract_is_a_bounded_history_reader() -> None:
    attachment = ATTACHMENT_READ_SCHEMA["function"]
    parameters = attachment["parameters"]

    assert set(parameters["properties"]) == {"attachmentId", "offset"}
    assert parameters["required"] == ["attachmentId"]
    assert parameters["properties"]["offset"]["minimum"] == 0
    assert "historicalAttachments" in attachment["description"]
    assert "nextOffset" in attachment["description"]


def test_edit_execute_exposes_only_operations_and_nonempty_batch_contracts() -> None:
    parameters = EDIT_EXECUTE_SCHEMA["function"]["parameters"]
    edits = parameters["properties"]["edits"]
    edit_item = edits["items"]
    assert parameters["required"] == ["edits"]
    assert edits["minItems"] == 1
    assert set(edit_item["properties"]) == {"operation"}
    assert edit_item["required"] == ["operation"]
    assert "evidenceRefs" not in AGENT_PROMPT


def test_edit_execute_explains_field_semantics_and_normalization_at_its_seam() -> None:
    tool_description = EDIT_EXECUTE_SCHEMA["function"]["description"]
    patch = _operation_branch("update_item")["properties"]["patch"]
    patch_description = patch["description"]

    assert (
        "Keep normalization to requested fields or clearly misplaced values needed to "
        "complete that request"
        in tool_description
    )
    assert "avoid adjacent cleanup" in tool_description
    assert "First normalize" not in tool_description
    assert "omit exact no-op operations" in tool_description
    assert "company is the employer" in patch_description
    assert "position is the role or title" in patch_description
    assert "location is a geographic place" in patch_description
    assert "name is the project or product name" in patch_description
    assert "role is the candidate's role" in patch_description
    assert "techStack contains individual technologies only" in patch_description
    assert "Move misplaced existing content" in patch_description
    assert "clear it with an empty string" in patch["properties"]["role"][
        "description"
    ]
    assert "move that value" in patch["properties"]["location"]["description"]
    assert "Brief context or scope only" in patch["properties"]["description"][
        "description"
    ]
    assert "Move non-technology contribution facts" in patch["properties"][
        "techStack"
    ]["description"]
    assert "Recover contribution facts" in patch["properties"]["highlights"][
        "description"
    ]
    assert "ownership or impact is unknown" in patch["properties"]["highlights"][
        "description"
    ]


def test_simple_list_content_contract_preserves_canonical_rich_text() -> None:
    update_content = _operation_branch("update_item")["properties"]["patch"][
        "properties"
    ]["content"]
    insert_item = _operation_branch("insert_item")["properties"]["item"]
    simple_list_item = next(
        branch
        for branch in insert_item["oneOf"]
        if set(branch.get("properties", {})) == {"id", "content"}
    )
    insert_content = simple_list_item["properties"]["content"]

    assert update_content == insert_content
    description = update_content["description"]
    assert "canonical sanitized rich-text html" in description.casefold()
    assert "<ul>" in description
    assert "<li>" in description
    assert "tags render structure" in description.casefold()
    assert "preserve html when editing" in description.casefold()


def test_prompt_does_not_duplicate_canonical_operation_variants() -> None:
    operation_types = set(_operation_signatures(OPERATION_SCHEMA))

    assert operation_types == {
        "replace_field",
        "insert_section",
        "update_section",
        "delete_section",
        "reorder_sections",
        "insert_item",
        "update_item",
        "delete_item",
        "reorder_items",
    }
    assert all(operation_type not in AGENT_PROMPT for operation_type in operation_types)
