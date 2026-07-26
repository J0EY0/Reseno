import asyncio
import json

from app.services.llm import AgentLlmConfig
from scripts.agent_model_eval import (
    DEFAULT_FIXTURE,
    CaseExpectation,
    EvaluationObservation,
    ModelEvalCase,
    load_suite,
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


def _case(case_id: str, *, required: str = "") -> ModelEvalCase:
    return ModelEvalCase(
        id=case_id,
        description=f"Scenario {case_id}",
        request={
            "prompt": f"Evaluate {case_id}",
            "locale": "en",
            "resume": {"basic": {}, "sections": []},
        },
        expect=CaseExpectation(
            minEdits=1,
            transactionState="provisional",
            requiredStrings=[required] if required else [],
        ),
    )


def test_default_fixture_covers_required_agent_behaviors() -> None:
    suite = load_suite(DEFAULT_FIXTURE)

    assert suite.schema_version == 1
    assert {case.id for case in suite.cases} == EXPECTED_CASE_IDS


def test_run_suite_uses_injected_provider_and_reports_failures() -> None:
    config = _config()
    calls: list[tuple[str, str, str]] = []

    async def fake_provider(request, selected_config):
        calls.append(
            (
                request.prompt,
                selected_config.provider,
                selected_config.model,
            ),
        )
        marker = "expected-marker" if request.prompt.endswith("passing") else ""
        return EvaluationObservation(
            response_text=marker,
            edit_payloads=(marker,),
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
        "required_string_missing"
    )
    assert "super-secret-api-key" not in json.dumps(report)


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
