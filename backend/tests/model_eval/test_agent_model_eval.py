import asyncio
import json
from types import SimpleNamespace

import pytest

from app.schemas.agent import AgentChatRequest
from app.services.llm import AgentLlmConfig
from scripts.agent_model_eval import (
    DEFAULT_FIXTURE,
    AttachmentFixture,
    CaseExpectation,
    EvaluationObservation,
    ModelEvalCase,
    execute_real_agent,
    load_suite,
    prepared_request,
    redact_error,
    run_suite,
)

EXPECTED_CASE_IDS = {
    "advice_only_no_edits",
    "explicit_edit_provisional_draft",
    "no_unsupported_achievement",
    "graduate_application_context",
    "scholarship_application_context",
    "current_attachment_boundary",
    "multi_operation_transaction_repair",
}


def _config() -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="configured-model",
        name="Configured model",
        provider="test-provider",
        model="test-model",
        base_url="https://provider.example/v1",
        api_key="super-secret-api-key",
        temperature=None,
        top_p=None,
        max_tokens=None,
        timeout_seconds=30,
    )


def _request_data(message_id: str, text: str) -> dict[str, object]:
    return {
        "message": {
            "id": message_id,
            "role": "user",
            "text": text,
        },
        "locale": "en",
        "resume": {"basic": {}, "sections": []},
    }


def _case(case_id: str, *, required: str = "") -> ModelEvalCase:
    return ModelEvalCase(
        id=case_id,
        description=f"Scenario {case_id}",
        request=_request_data(
            f"{case_id}-current",
            f"Evaluate {case_id}",
        ),
        expect=CaseExpectation(
            minEdits=1,
            transactionState="provisional",
            requiredEditStrings=[required] if required else [],
        ),
    )


def test_default_fixture_covers_required_agent_behaviors() -> None:
    suite = load_suite(DEFAULT_FIXTURE)

    assert suite.schema_version == 2
    assert {case.id for case in suite.cases} == EXPECTED_CASE_IDS
    assert all("message" in case.request for case in suite.cases)
    assert all("prompt" not in case.request for case in suite.cases)


def test_run_suite_uses_injected_provider_and_reports_failures() -> None:
    config = _config()
    calls: list[tuple[str, str, str]] = []

    async def fake_provider(request, selected_config):
        calls.append(
            (
                request.message.text,
                selected_config.provider,
                selected_config.model,
            ),
        )
        marker = "expected-marker" if request.message.text.endswith("passing") else ""
        return EvaluationObservation(
            response_text=marker,
            edit_payloads=(marker,),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="provisional",
            runner_transaction_state="committed",
            tool_names=("edit_execute",),
            tool_error_count=0,
            finish_status="ready",
        )

    report = asyncio.run(
        run_suite(
            [
                _case("passing", required="expected-marker"),
                _case("failing", required="expected-marker"),
            ],
            config,
            executor=fake_provider,
        ),
    )

    assert calls == [
        ("Evaluate passing", "test-provider", "test-model"),
        ("Evaluate failing", "test-provider", "test-model"),
    ]
    assert report["provider"] == "test-provider"
    assert report["model"] == "test-model"
    assert report["summary"] == {
        "total": 2,
        "passed": 1,
        "failed": 1,
        "passRate": 0.5,
    }
    assert report["cases"][0]["passed"] is True
    assert report["cases"][1]["failureReasons"][0]["code"] == (
        "required_edit_string_missing"
    )
    assert "super-secret-api-key" not in json.dumps(report)


def test_edit_evidence_cannot_be_satisfied_by_response_text() -> None:
    case = ModelEvalCase(
        id="edit-domain",
        description="Required draft evidence must be present in the edit payload.",
        request=_request_data("edit-domain-current", "Create a grounded draft."),
        expect=CaseExpectation(
            minEdits=1,
            transactionState="provisional",
            requiredEditStrings=["draft-evidence-marker"],
        ),
    )

    async def marker_only_in_response(_request, _selected_config):
        return EvaluationObservation(
            response_text="I used draft-evidence-marker.",
            edit_payloads=(json.dumps({"replacement": "unrelated draft"}),),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="provisional",
            runner_transaction_state="committed",
            tool_names=("edit_execute",),
            tool_error_count=0,
            finish_status="ready",
        )

    report = asyncio.run(
        run_suite([case], _config(), executor=marker_only_in_response),
    )

    assert report["cases"][0]["passed"] is False
    assert report["cases"][0]["failureReasons"] == [
        {
            "code": "required_edit_string_missing",
            "detail": "Missing required edit string: 'draft-evidence-marker'.",
        },
    ]


def test_forbidden_edit_pattern_checks_the_draft_not_the_explanation() -> None:
    expectation = CaseExpectation(
        minEdits=1,
        transactionState="provisional",
        forbiddenEditRegex=[r"\b\d+(?:\.\d+)?\s*%"],
    )
    cases = [
        ModelEvalCase(
            id="grounded-draft",
            description="An explanation may mention the forbidden metric category.",
            request=_request_data(
                "grounded-draft-current",
                "Build grounded-draft",
            ),
            expect=expectation,
        ),
        ModelEvalCase(
            id="invented-metric",
            description="The draft itself must not contain an invented metric.",
            request=_request_data(
                "invented-metric-current",
                "Build invented-metric",
            ),
            expect=expectation,
        ),
    ]

    async def provider(request, _selected_config):
        replacement = (
            "Improved accessibility"
            if request.message.text.endswith("grounded-draft")
            else "Improved conversion by 50%"
        )
        return EvaluationObservation(
            response_text="I did not invent a 50% improvement.",
            edit_payloads=(json.dumps({"replacement": replacement}),),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="provisional",
            runner_transaction_state="committed",
            tool_names=("edit_execute",),
            tool_error_count=0,
            finish_status="ready",
        )

    report = asyncio.run(run_suite(cases, _config(), executor=provider))

    assert [case["passed"] for case in report["cases"]] == [True, False]
    assert report["cases"][1]["failureReasons"][0]["code"] == (
        "forbidden_edit_pattern_present"
    )


def test_required_edit_targets_reject_an_unrelated_batch() -> None:
    case = ModelEvalCase(
        id="required-targets",
        description="A repaired batch must update both requested targets.",
        request=_request_data("required-targets-current", "Repair both edits."),
        expect=CaseExpectation(
            minEdits=2,
            transactionState="provisional",
            requiredEditTargets=[
                "basic.summary",
                "sections.project.items.project-1",
            ],
        ),
    )

    async def unrelated_batch(_request, _selected_config):
        return EvaluationObservation(
            response_text="Draft ready.",
            edit_payloads=("summary edit", "unrelated edit"),
            edit_targets=("basic.summary", "basic.headline"),
            edit_count=2,
            rejected_edit_count=0,
            transaction_state="provisional",
            runner_transaction_state="committed",
            tool_names=("edit_execute",),
            tool_error_count=1,
            finish_status="ready",
        )

    report = asyncio.run(run_suite([case], _config(), executor=unrelated_batch))

    assert report["cases"][0]["passed"] is False
    assert report["cases"][0]["failureReasons"][0]["code"] == (
        "required_edit_target_missing"
    )


def test_required_tool_sequence_rejects_out_of_order_repair() -> None:
    case = ModelEvalCase(
        id="repair-sequence",
        description="The failed batch must be repaired before the turn finishes.",
        request=_request_data("repair-sequence-current", "Repair the transaction."),
        expect=CaseExpectation(
            minEdits=2,
            transactionState="provisional",
            requiredToolSequence=["edit_execute", "edit_execute", "finish"],
        ),
    )

    async def out_of_order_repair(_request, _selected_config):
        return EvaluationObservation(
            response_text="Done.",
            edit_payloads=("summary edit", "project edit"),
            edit_targets=(
                "basic.summary",
                "sections.project.items.project-1",
            ),
            edit_count=2,
            rejected_edit_count=0,
            transaction_state="provisional",
            runner_transaction_state="committed",
            tool_names=("edit_execute", "finish", "edit_execute"),
            tool_error_count=1,
            finish_status="ready",
        )

    report = asyncio.run(
        run_suite([case], _config(), executor=out_of_order_repair),
    )

    assert report["cases"][0]["passed"] is False
    assert report["cases"][0]["failureReasons"][0]["code"] == ("tool_sequence_mismatch")


def test_real_observation_records_finish_and_only_actual_mutation_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edit = SimpleNamespace(
        title="The explanation-only-marker title",
        target="basic.summary",
        reason="Mention explanation-only-marker without writing it.",
        replacement="Actual grounded replacement.",
        operation={"op": "set", "value": "Actual grounded replacement."},
        status="executed",
    )
    runner = SimpleNamespace(
        build_message=lambda: SimpleNamespace(text="Draft ready."),
        edits=[edit],
        finish_status="ready",
        finished=True,
        tools=[SimpleNamespace(state="output-available", type="tool-edit_execute")],
        transaction_failed=False,
        transaction_state="committed",
    )

    async def fake_loop(_request, _config):
        yield SimpleNamespace(kind="done", runner=runner)

    monkeypatch.setattr(
        "app.services.agent.runtime.loop.async_iter_agent_tool_call_loop",
        fake_loop,
    )
    request = AgentChatRequest.model_validate(
        _request_data("real-observation-current", "Create a grounded draft."),
    )

    observation = asyncio.run(execute_real_agent(request, _config()))

    assert observation.tool_names == ("edit_execute", "finish")
    assert "Actual grounded replacement." in observation.edit_payloads[0]
    assert "explanation-only-marker" not in observation.edit_payloads[0]


def test_runner_transaction_state_must_match_the_expected_commit() -> None:
    case = ModelEvalCase(
        id="runner-state",
        description="A provisional UI draft still requires a committed tool batch.",
        request=_request_data("runner-state-current", "Create the draft."),
        expect=CaseExpectation(
            minEdits=1,
            transactionState="provisional",
            runnerTransactionState="committed",
        ),
    )

    async def rolled_back_runner(_request, _selected_config):
        return EvaluationObservation(
            response_text="Draft ready.",
            edit_payloads=("summary edit",),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="provisional",
            runner_transaction_state="rolled_back",
            tool_names=("edit_execute", "finish"),
            tool_error_count=0,
            finish_status="ready",
        )

    report = asyncio.run(
        run_suite([case], _config(), executor=rolled_back_runner),
    )

    assert report["cases"][0]["passed"] is False
    assert report["cases"][0]["failureReasons"][0]["code"] == (
        "runner_transaction_state_mismatch"
    )


def test_finish_status_must_match_the_expected_ready_state() -> None:
    case = ModelEvalCase(
        id="finish-state",
        description="A successful draft must explicitly finish ready.",
        request=_request_data("finish-state-current", "Create the draft."),
        expect=CaseExpectation(
            minEdits=1,
            transactionState="provisional",
            finishStatus="ready",
        ),
    )

    async def blocked_finish(_request, _selected_config):
        return EvaluationObservation(
            response_text="Draft ready.",
            edit_payloads=("summary edit",),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="provisional",
            runner_transaction_state="committed",
            tool_names=("edit_execute", "finish"),
            tool_error_count=0,
            finish_status="blocked",
        )

    report = asyncio.run(run_suite([case], _config(), executor=blocked_finish))

    assert report["cases"][0]["passed"] is False
    assert report["cases"][0]["failureReasons"][0]["code"] == ("finish_status_mismatch")


def test_response_pattern_cannot_be_satisfied_by_an_edit_payload() -> None:
    case = ModelEvalCase(
        id="response-domain",
        description="Advice expectations apply to the visible response.",
        request=_request_data(
            "response-domain-current",
            "Explain the research gap.",
        ),
        expect=CaseExpectation(
            maxEdits=1,
            requiredResponseRegex=["research"],
        ),
    )

    async def marker_only_in_edit(_request, _selected_config):
        return EvaluationObservation(
            response_text="Here is the requested advice.",
            edit_payloads=("research experience",),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="provisional",
            runner_transaction_state="committed",
            tool_names=("edit_execute", "finish"),
            tool_error_count=0,
            finish_status="ready",
        )

    report = asyncio.run(
        run_suite([case], _config(), executor=marker_only_in_edit),
    )

    assert report["cases"][0]["passed"] is False
    assert report["cases"][0]["failureReasons"][0]["code"] == (
        "required_response_pattern_missing"
    )


def test_edit_pattern_cannot_be_satisfied_by_the_response() -> None:
    case = ModelEvalCase(
        id="edit-pattern-domain",
        description="Draft language expectations apply to edit payloads.",
        request=_request_data(
            "edit-pattern-domain-current",
            "Create an accessibility draft.",
        ),
        expect=CaseExpectation(
            minEdits=1,
            requiredEditRegex=["accessib(?:ility|le)"],
        ),
    )

    async def marker_only_in_response(_request, _selected_config):
        return EvaluationObservation(
            response_text="I made the draft accessible.",
            edit_payloads=("generic replacement",),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="provisional",
            runner_transaction_state="committed",
            tool_names=("edit_execute", "finish"),
            tool_error_count=0,
            finish_status="ready",
        )

    report = asyncio.run(
        run_suite([case], _config(), executor=marker_only_in_response),
    )

    assert report["cases"][0]["passed"] is False
    assert report["cases"][0]["failureReasons"][0]["code"] == (
        "required_edit_pattern_missing"
    )


def test_forbidden_strings_are_checked_in_their_declared_domain() -> None:
    expectation = CaseExpectation(
        minEdits=1,
        forbiddenResponseStrings=["response-secret"],
        forbiddenEditStrings=["edit-secret"],
    )
    cases = [
        ModelEvalCase(
            id=case_id,
            description=f"Forbidden text domain {case_id}",
            request=_request_data(f"{case_id}-current", case_id),
            expect=expectation,
        )
        for case_id in ("cross-domain", "response-leak", "edit-leak")
    ]

    async def provider(request, _selected_config):
        response_text = (
            "response-secret"
            if request.message.text == "response-leak"
            else "edit-secret"
        )
        edit_text = (
            "edit-secret" if request.message.text == "edit-leak" else "response-secret"
        )
        return EvaluationObservation(
            response_text=response_text,
            edit_payloads=(edit_text,),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="provisional",
            runner_transaction_state="committed",
            tool_names=("edit_execute", "finish"),
            tool_error_count=0,
            finish_status="ready",
        )

    report = asyncio.run(run_suite(cases, _config(), executor=provider))

    assert [case["passed"] for case in report["cases"]] == [True, False, False]
    assert report["cases"][1]["failureReasons"][0]["code"] == (
        "forbidden_response_string_present"
    )
    assert report["cases"][2]["failureReasons"][0]["code"] == (
        "forbidden_edit_string_present"
    )


def test_run_suite_redacts_provider_errors() -> None:
    config = _config()

    async def failing_provider(_request, _selected_config):
        raise RuntimeError(
            "authorization=super-secret-api-key request was rejected",
        )

    report = asyncio.run(
        run_suite(
            [_case("provider-error")],
            config,
            executor=failing_provider,
        ),
    )

    failure = report["cases"][0]["failureReasons"][0]
    assert failure["code"] == "execution_error"
    assert "super-secret-api-key" not in failure["detail"]
    assert "[REDACTED]" in failure["detail"]


def test_redact_error_removes_common_key_shapes() -> None:
    error = RuntimeError(
        "Bearer abcdefgh api_key=sk-example-secret authorization: token-value",
    )

    redacted = redact_error(error, "abcdefgh")

    assert "abcdefgh" not in redacted
    assert "sk-example-secret" not in redacted
    assert "token-value" not in redacted


@pytest.mark.parametrize(
    ("detail", "secret"),
    [
        ("Authorization: Bearer auth-token-123", "auth-token-123"),
        ("authorization=Bearer auth-token-456", "auth-token-456"),
        ("request failed with Bearer standalone-token-789", "standalone-token-789"),
    ],
)
def test_redact_error_removes_authorization_bearer_tokens(
    detail: str,
    secret: str,
) -> None:
    redacted = redact_error(RuntimeError(detail), "different-configured-key")

    assert secret not in redacted
    assert "[REDACTED]" in redacted


def test_prepared_attachment_request_satisfies_session_revision_contract() -> None:
    case = _case("attachment-request")
    case.attachments = [
        AttachmentFixture(
            scope="current",
            filename="evidence.txt",
            content="Synthetic evidence",
        ),
    ]

    with prepared_request(case, _config()) as request:
        assert request.resume_id
        assert request.expected_revision
