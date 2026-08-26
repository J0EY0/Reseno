import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.schemas.agent import AgentChatMessage, AgentChatRequest
from app.services.agent.runtime.loop import AgentToolLoopCompleted, AgentTurnResult
from app.services.agent.runtime.streaming import AgentCompleted
from app.services.llm import (
    AgentLlmConfig,
    LlmAssistantMessage,
    LlmStreamEvent,
    LlmUsage,
)
from scripts.agent_model_eval import (
    DEFAULT_FIXTURE,
    AttachmentFixture,
    CaseExpectation,
    EvaluationObservation,
    EvaluationTokenUsage,
    ModelEvalCase,
    _build_parser,
    evaluate_observation,
    execute_real_agent,
    load_suite,
    observation_summary,
    prepared_request,
    redact_error,
    run_suite,
)

EXPECTED_CASE_IDS = {
    "advice_only_no_edits",
    "explicit_edit_provisional_draft",
    "no_unsupported_achievement",
    "graduate_application_context",
    "historical_attachment_grounded_edit",
    "scholarship_application_context",
    "current_attachment_boundary",
    "multi_operation_transaction_repair",
    "cross_module_grounded_enrichment",
    "current_web_jd_tailoring",
    "jd_context_does_not_become_candidate_evidence",
    "insufficient_experience_requests_evidence",
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


def _request_data(
    message_id: str,
    text: str,
    *,
    resume: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "message": {
            "id": message_id,
            "role": "user",
            "text": text,
        },
        "locale": "en",
        "resume": resume or {"basic": {}, "sections": []},
    }


def _turn_result(
    *,
    edits: tuple[SimpleNamespace, ...] = (),
    tools: tuple[SimpleNamespace, ...] = (),
    transaction_state: str = "none",
) -> AgentTurnResult:
    return AgentTurnResult(
        message=None,
        tools=tools,
        edits=edits,
        transaction_state=transaction_state,
        terminal_text="",
    )


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
            transactionState="committed",
            requiredEditStrings=[required] if required else [],
        ),
    )


def test_default_fixture_covers_required_agent_behaviors() -> None:
    suite = load_suite(DEFAULT_FIXTURE)

    assert suite.schema_version == 5
    assert {case.id for case in suite.cases} == EXPECTED_CASE_IDS
    assert all("message" in case.request for case in suite.cases)
    assert all("prompt" not in case.request for case in suite.cases)
    enrichment = next(
        case for case in suite.cases if case.id == "no_unsupported_achievement"
    )
    assert enrichment.expect.min_distinct_highlights == 2
    assert enrichment.expect.required_edit_strings == [
        "键盘交互",
    ]
    assert enrichment.expect.required_edit_regex == [
        "表单.{0,12}状态|状态.{0,12}表单",
    ]
    structural = next(
        case for case in suite.cases if case.id == "cross_module_grounded_enrichment"
    )
    assert structural.expect.required_changed_paths == [
        "sections.experience-1.items.experience-item-1.company",
        "sections.experience-1.items.experience-item-1.position",
        "sections.experience-1.items.experience-item-1.location",
        "sections.experience-1.items.experience-item-1.description",
        "sections.project-1.items.project-item-1.name",
        "sections.project-1.items.project-item-1.role",
        "sections.project-1.items.project-item-1.techStack",
        "sections.project-1.items.project-item-1.description",
        "sections.project-1.items.project-item-1.highlights",
        "sections.skills-1.items.skills-item-1.content",
    ]
    assert structural.expect.required_changed_values == {
        "sections.experience-1.items.experience-item-1.company": "示例科技",
        "sections.experience-1.items.experience-item-1.position": "前端开发实习生",
        "sections.experience-1.items.experience-item-1.location": "",
        "sections.project-1.items.project-item-1.name": "示例 AI 简历工具",
        "sections.project-1.items.project-item-1.role": "",
        "sections.project-1.items.project-item-1.techStack": [
            "React",
            "TypeScript",
            "Tailwind",
            "shadcn/ui",
        ],
    }
    assert structural.expect.min_distinct_highlights == 4
    skills_section = next(
        section
        for section in structural.request["resume"]["sections"]
        if section["kind"] == "simple_list"
    )
    assert skills_section["items"][0]["content"].startswith("<ul><li>")
    assert structural.expect.min_edits == 3
    assert structural.expect.max_edits == 3
    assert "CET-6" in structural.expect.required_edit_strings
    assert any(
        "Prompt Engineering" in pattern
        for pattern in structural.expect.forbidden_edit_regex
    )
    assert "可折叠" in structural.expect.required_edit_strings
    assert {"面向求职者", "面向求职场景", "简历生成"} <= set(
        structural.expect.forbidden_edit_strings
    )
    assert "name 当前为 React" not in structural.request["message"]["text"]
    current_web = next(
        case for case in suite.cases if case.id == "current_web_jd_tailoring"
    )
    assert current_web.expect.min_sources == 1
    assert current_web.expect.required_tool_sequence == ["edit_execute"]
    assert all(
        "citation" not in pattern and "source_ids" not in pattern
        for pattern in current_web.expect.required_response_regex
    )
    jd_grounding = next(
        case
        for case in suite.cases
        if case.id == "jd_context_does_not_become_candidate_evidence"
    )
    forbidden_jd_claims = "|".join(jd_grounding.expect.forbidden_edit_regex)
    assert "React Hooks" in forbidden_jd_claims
    assert "面向求职" in forbidden_jd_claims
    sparse_enrichment = next(
        case
        for case in suite.cases
        if case.id == "insufficient_experience_requests_evidence"
    )
    sparse_question_overreach = "|".join(
        sparse_enrichment.expect.forbidden_response_regex
    )
    assert "项目类型" in sparse_question_overreach
    assert "代码规模" in sparse_question_overreach
    assert "选最贴近" in sparse_question_overreach


def test_required_changed_paths_detect_field_level_misplacement() -> None:
    expectation = CaseExpectation(
        requiredChangedPaths=[
            "sections.project.items.project-1.name",
            "sections.project.items.project-1.techStack",
        ],
    )
    observation = EvaluationObservation(
        response_text="Draft ready.",
        edit_payloads=("React TypeScript ResuMate",),
        edit_targets=("sections.project.items.project-1",),
        edit_count=1,
        rejected_edit_count=0,
        transaction_state="committed",
        tool_names=("edit_execute",),
        tool_error_count=0,
        changed_paths=("sections.project.items.project-1.description",),
    )

    failures = evaluate_observation(expectation, observation)

    assert [failure["code"] for failure in failures] == [
        "required_changed_path_missing",
        "required_changed_path_missing",
    ]


def test_required_changed_values_reject_another_wrong_field_order() -> None:
    expectation = CaseExpectation(
        requiredChangedValues={
            "sections.experience.items.experience-1.company": "示例科技",
            "sections.experience.items.experience-1.position": "前端开发实习生",
            "sections.experience.items.experience-1.location": "",
        },
    )
    observation = EvaluationObservation(
        response_text="Draft ready.",
        edit_payloads=("示例科技 前端开发实习生",),
        edit_targets=("sections.experience.items.experience-1",),
        edit_count=1,
        rejected_edit_count=0,
        transaction_state="committed",
        tool_names=("edit_execute",),
        tool_error_count=0,
        changed_values={
            "sections.experience.items.experience-1.company": "前端开发实习生",
            "sections.experience.items.experience-1.position": "示例科技",
            "sections.experience.items.experience-1.location": "",
        },
    )

    failures = evaluate_observation(expectation, observation)

    assert [failure["code"] for failure in failures] == [
        "required_changed_value_mismatch",
        "required_changed_value_mismatch",
    ]
    correct = replace(
        observation,
        changed_values={
            "sections.experience.items.experience-1.company": "示例科技",
            "sections.experience.items.experience-1.position": "前端开发实习生",
            "sections.experience.items.experience-1.location": "",
        },
    )
    assert evaluate_observation(expectation, correct) == []
    serialized_summary = json.dumps(
        observation_summary(observation),
        ensure_ascii=False,
    )
    assert "changedValues" not in serialized_summary
    assert "示例科技" not in serialized_summary


def test_load_suite_rejects_an_invalid_resume_document(tmp_path) -> None:
    fixture = tmp_path / "invalid-scenarios.json"
    fixture.write_text(
        json.dumps(
            {
                "schemaVersion": 5,
                "cases": [
                    {
                        "id": "invalid-resume",
                        "description": "Fixture resumes use the production contract.",
                        "request": {
                            "message": {
                                "id": "invalid-resume-current",
                                "role": "user",
                                "text": "Review this resume.",
                            },
                            "locale": "en",
                            "resume": {"basic": {}, "sections": []},
                        },
                        "expect": {"maxEdits": 0},
                    },
                ],
            },
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="invalid-resume.*RESUME_DOCUMENT_INVALID"):
        load_suite(fixture)


def test_enrichment_expectation_requires_distinct_resume_highlights() -> None:
    observation = EvaluationObservation(
        response_text="Draft ready.",
        edit_payloads=("Built the form workflow.",),
        edit_targets=("sections.project.items.project-1",),
        edit_count=1,
        rejected_edit_count=0,
        transaction_state="committed",
        tool_names=("edit_execute",),
        tool_error_count=0,
        distinct_highlight_count=1,
    )

    failures = evaluate_observation(
        CaseExpectation(minDistinctHighlights=2),
        observation,
    )

    assert failures == [
        {
            "code": "distinct_highlight_count_too_low",
            "detail": "Expected at least 2 distinct highlights; got 1.",
        },
    ]


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
            transaction_state="committed",
            tool_names=("edit_execute",),
            tool_error_count=0,
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
        "runCount": 2,
        "passedRuns": 1,
        "failedRuns": 1,
        "runPassRate": 0.5,
        "passAtN": {"n": 1, "passedCases": 1, "rate": 0.5},
        "stablePass": {"n": 1, "passedCases": 1, "rate": 0.5},
    }
    assert report["cases"][0]["passed"] is True
    assert report["cases"][1]["failureReasons"][0]["code"] == (
        "required_edit_string_missing"
    )
    assert "super-secret-api-key" not in json.dumps(report)


def test_run_suite_repeats_cases_and_reports_stability_statistics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    clock = iter((0.0, 0.01, 1.0, 1.02, 2.0, 2.04))
    monkeypatch.setattr(
        "scripts.agent_model_eval.perf_counter",
        lambda: next(clock),
    )

    async def varying_provider(
        _request: AgentChatRequest,
        _selected_config: AgentLlmConfig,
    ) -> EvaluationObservation:
        nonlocal attempts
        attempts += 1
        passed = attempts != 2
        return EvaluationObservation(
            response_text="Draft ready.",
            edit_payloads=("expected-marker" if passed else "missing-marker",),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="committed",
            tool_names=tuple("edit_execute" for _ in range(attempts)),
            tool_error_count=0,
            token_usage=EvaluationTokenUsage(
                request_attempts=attempts,
                terminal_responses=attempts,
            ),
        )

    report = asyncio.run(
        run_suite(
            [_case("repeat", required="expected-marker")],
            _config(),
            executor=varying_provider,
            repeat=3,
        ),
    )

    assert attempts == 3
    assert report["summary"] == {
        "total": 1,
        "passed": 0,
        "failed": 1,
        "passRate": 0.0,
        "runCount": 3,
        "passedRuns": 2,
        "failedRuns": 1,
        "runPassRate": 0.6667,
        "passAtN": {"n": 3, "passedCases": 1, "rate": 1.0},
        "stablePass": {"n": 3, "passedCases": 0, "rate": 0.0},
    }
    result = report["cases"][0]
    assert result["passed"] is False
    assert result["passCount"] == 2
    assert result["runCount"] == 3
    assert result["passRate"] == 0.6667
    assert result["durationStatsMs"] == {
        "total": 70,
        "average": 23,
        "p50": 20,
        "p95": 40,
        "maximum": 40,
    }
    assert result["modelAttempts"] == {
        "total": 6,
        "average": 2,
        "p50": 2,
        "p95": 3,
        "maximum": 3,
    }
    assert result["modelResponses"] == result["modelAttempts"]
    assert result["toolCalls"] == {
        "total": 6,
        "average": 2,
        "p50": 2,
        "p95": 3,
        "maximum": 3,
        "byName": {"edit_execute": 6},
    }
    assert [run["passed"] for run in result["runs"]] == [True, False, True]
    assert [run["run"] for run in result["runs"]] == [1, 2, 3]
    assert report["metrics"]["latencyMs"] == result["durationStatsMs"]


def test_cli_repeat_is_a_positive_integer() -> None:
    parser = _build_parser()

    assert parser.parse_args([]).repeat == 1
    assert parser.parse_args(["--repeat", "3"]).repeat == 3
    with pytest.raises(SystemExit):
        parser.parse_args(["--repeat", "0"])


def test_report_exposes_auto_quality_latency_usage_and_cost_availability() -> None:
    expectation = CaseExpectation(
        minEdits=1,
        transactionState="committed",
        forbiddenEditRegex=[r"\b\d+\s*%"],
    )
    cases = [
        ModelEvalCase(
            id=case_id,
            description=f"Auto quality {case_id}",
            request=_request_data(f"{case_id}-current", case_id),
            expect=expectation,
        )
        for case_id in ("grounded", "hallucinated")
    ]

    async def provider(request, _selected_config):
        hallucinated = request.message.text == "hallucinated"
        return EvaluationObservation(
            response_text="Draft ready.",
            edit_payloads=(
                "Improved accessibility by 50%"
                if hallucinated
                else "Improved accessibility",
            ),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="committed",
            tool_names=("edit_execute",),
            tool_error_count=0,
            token_usage=EvaluationTokenUsage(
                request_attempts=2,
                terminal_responses=2,
                input_tokens=100,
                input_tokens_reported_responses=2,
                output_tokens=50,
                output_tokens_reported_responses=2,
                total_tokens=150,
                total_tokens_reported_responses=2,
                cached_input_tokens=40,
                cached_input_tokens_reported_responses=2,
                cache_write_input_tokens=10,
                cache_write_input_tokens_reported_responses=2,
                reasoning_tokens=20,
                reasoning_tokens_reported_responses=2,
            ),
        )

    report = asyncio.run(run_suite(cases, _config(), executor=provider))

    assert report["metrics"]["editAccuracy"] == {
        "evaluatedCases": 2,
        "passedCases": 2,
        "rate": 1.0,
    }
    assert report["metrics"]["toolCompletion"] == {
        "evaluatedCases": 2,
        "passedCases": 2,
        "rate": 1.0,
    }
    assert report["metrics"]["hallucination"] == {
        "evaluatedCases": 2,
        "violationCases": 1,
        "violationRate": 0.5,
    }
    assert report["metrics"]["truncation"] == {
        "evaluatedCases": 2,
        "truncatedCases": 0,
        "rate": 0.0,
    }
    assert report["metrics"]["tokenUsage"] == {
        "requestAttempts": 4,
        "terminalResponses": 4,
        "inputTokens": {
            "value": 200,
            "reportedResponses": 4,
            "complete": True,
        },
        "outputTokens": {
            "value": 100,
            "reportedResponses": 4,
            "complete": True,
        },
        "totalTokens": {
            "value": 300,
            "reportedResponses": 4,
            "complete": True,
        },
        "cachedInputTokens": {
            "value": 80,
            "reportedResponses": 4,
            "complete": True,
        },
        "cacheWriteInputTokens": {
            "value": 20,
            "reportedResponses": 4,
            "complete": True,
        },
        "reasoningTokens": {
            "value": 40,
            "reportedResponses": 4,
            "complete": True,
        },
    }
    assert report["metrics"]["cost"] == {
        "status": "unavailable",
        "amount": None,
        "currency": None,
        "reason": "No authoritative configured-model price metadata is available.",
    }
    assert report["metrics"]["latencyMs"]["total"] >= 0
    assert report["metrics"]["latencyMs"]["average"] >= 0
    assert report["metrics"]["latencyMs"]["maximum"] >= 0


def test_truncated_provider_output_is_classified_and_keeps_reported_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def truncated_provider(*_args, **kwargs):
        kwargs["on_provider_attempt"]()
        response = LlmAssistantMessage(
            content="partial",
            usage=LlmUsage(input_tokens=90, output_tokens=30, total_tokens=120),
            stop_reason="length",
        )
        yield LlmStreamEvent(type="text_delta", delta=response.content)
        yield LlmStreamEvent(type="done", message=response)

    monkeypatch.setattr(
        "app.services.agent.runtime.loop.async_stream_tool_call",
        truncated_provider,
    )
    case = ModelEvalCase(
        id="truncated",
        description="Provider output must reach a complete terminal boundary.",
        request=_request_data("truncated-current", "Rewrite the summary."),
        expect=CaseExpectation(
            minEdits=1,
            requiredEditTargets=["basic.summary"],
        ),
    )

    report = asyncio.run(run_suite([case], _config()))

    assert report["cases"][0]["failureReasons"][0]["code"] == ("output_truncated")
    assert report["cases"][0]["observed"] == {
        "truncated": True,
        "tokenUsage": {
            "requestAttempts": 1,
            "terminalResponses": 1,
            "inputTokens": {
                "value": 90,
                "reportedResponses": 1,
                "complete": True,
            },
            "outputTokens": {
                "value": 30,
                "reportedResponses": 1,
                "complete": True,
            },
            "totalTokens": {
                "value": 120,
                "reportedResponses": 1,
                "complete": True,
            },
            "cachedInputTokens": {
                "value": None,
                "reportedResponses": 0,
                "complete": False,
            },
            "cacheWriteInputTokens": {
                "value": None,
                "reportedResponses": 0,
                "complete": False,
            },
            "reasoningTokens": {
                "value": None,
                "reportedResponses": 0,
                "complete": False,
            },
        },
    }
    assert report["metrics"]["truncation"] == {
        "evaluatedCases": 1,
        "truncatedCases": 1,
        "rate": 1.0,
    }
    assert report["metrics"]["editAccuracy"] == {
        "evaluatedCases": 1,
        "passedCases": 0,
        "rate": 0.0,
    }
    assert report["metrics"]["tokenUsage"]["totalTokens"]["value"] == 120


def test_edit_execution_failure_counts_as_inaccurate() -> None:
    case = ModelEvalCase(
        id="edit-provider-failure",
        description="An edit case that cannot run is not an accurate edit.",
        request=_request_data("edit-provider-failure-current", "Rewrite summary."),
        expect=CaseExpectation(
            minEdits=1,
            requiredEditTargets=["basic.summary"],
        ),
    )

    async def failing_provider(_request, _selected_config):
        raise RuntimeError("provider failed")

    report = asyncio.run(
        run_suite([case], _config(), executor=failing_provider),
    )

    assert report["metrics"]["editAccuracy"] == {
        "evaluatedCases": 1,
        "passedCases": 0,
        "rate": 0.0,
    }


def test_edit_evidence_cannot_be_satisfied_by_response_text() -> None:
    case = ModelEvalCase(
        id="edit-domain",
        description="Required draft evidence must be present in the edit payload.",
        request=_request_data("edit-domain-current", "Create a grounded draft."),
        expect=CaseExpectation(
            minEdits=1,
            transactionState="committed",
            requiredEditStrings=["draft-evidence-marker"],
        ),
    )

    async def marker_only_in_response(_request, _selected_config):
        return EvaluationObservation(
            response_text="I used draft-evidence-marker.",
            edit_payloads=(json.dumps("unrelated final diff"),),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="committed",
            tool_names=("edit_execute",),
            tool_error_count=0,
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
        transactionState="committed",
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
        final_diff = (
            "Improved accessibility"
            if request.message.text.endswith("grounded-draft")
            else "Improved conversion by 50%"
        )
        return EvaluationObservation(
            response_text="I did not invent a 50% improvement.",
            edit_payloads=(json.dumps(final_diff),),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="committed",
            tool_names=("edit_execute",),
            tool_error_count=0,
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
            transactionState="committed",
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
            transaction_state="committed",
            tool_names=("edit_execute",),
            tool_error_count=1,
        )

    report = asyncio.run(run_suite([case], _config(), executor=unrelated_batch))

    assert report["cases"][0]["passed"] is False
    assert report["cases"][0]["failureReasons"][0]["code"] == (
        "required_edit_target_missing"
    )


def test_required_tool_sequence_allows_interleaved_material_steps() -> None:
    case = ModelEvalCase(
        id="repair-sequence",
        description="The failed batch must be repaired before the turn finishes.",
        request=_request_data("repair-sequence-current", "Repair the transaction."),
        expect=CaseExpectation(
            minEdits=2,
            transactionState="committed",
            requiredToolSequence=["edit_execute", "edit_execute"],
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
            transaction_state="committed",
            tool_names=("edit_execute", "resume_lookup", "edit_execute"),
            tool_error_count=1,
        )

    report = asyncio.run(
        run_suite([case], _config(), executor=out_of_order_repair),
    )

    assert report["cases"][0]["passed"] is True


def test_real_observation_uses_the_natural_completion_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_resume = {"basic": {"summary": "Original summary."}, "sections": []}
    edit = SimpleNamespace(
        title="The explanation-only-marker title",
        target="basic.summary",
        reason="Mention explanation-only-marker without writing it.",
        replacement="Actual grounded replacement.",
        operation={
            "type": "replace_field",
            "path": "basic.summary",
            "value": "Actual grounded replacement.",
        },
        status="executed",
        diffs=[{"path": "basic.summary"}],
    )
    result = _turn_result(
        edits=(edit,),
        tools=(
            SimpleNamespace(
                state="output-available",
                type="tool-edit_execute",
                output={"qualityIssues": []},
            ),
        ),
        transaction_state="committed",
    )

    async def fake_pipeline(
        _request,
        _config,
        runtime,
    ):
        runtime.record_tool_loop_event(AgentToolLoopCompleted(result=result))
        yield AgentCompleted(
            message=AgentChatMessage(
                id="evaluation-message",
                role="assistant",
                text="Draft ready.",
                transactionState="committed",
            ),
            persist=True,
        )

    monkeypatch.setattr(
        "app.services.agent.runtime.streaming.async_iter_resolved_agent_events",
        fake_pipeline,
    )
    request = AgentChatRequest.model_validate(
        _request_data(
            "real-observation-current",
            "Create a grounded draft.",
            resume=base_resume,
        ),
    )

    observation = asyncio.run(execute_real_agent(request, _config()))

    assert observation.tool_names == ("edit_execute",)
    assert observation.transaction_state == "committed"
    assert "Actual grounded replacement." in observation.edit_payloads[0]
    assert "explanation-only-marker" not in observation.edit_payloads[0]


def test_real_observation_reports_content_free_tool_error_codes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sensitive_marker = "candidate-private-error-detail"
    result = _turn_result(
        tools=(
            SimpleNamespace(
                state="output-error",
                type="tool-edit_execute",
                output={
                    "reason": "batch_rejected",
                    "rejectedEdits": [
                        {
                            "reason": sensitive_marker,
                            "qualityIssue": {"code": "fragmentary_highlight"},
                        },
                        {
                            "qualityIssue": {"code": "fragmentary_highlight"},
                        },
                        {
                            "qualityIssue": {
                                "code": "duplicate_item_field_in_highlight",
                            },
                        },
                    ],
                },
            ),
            SimpleNamespace(
                state="output-error",
                type="tool-edit_execute",
                output={"rejectedEdits": [{"reason": sensitive_marker}]},
            ),
        ),
    )

    async def fake_pipeline(
        _request,
        _config,
        runtime,
    ):
        runtime.record_tool_loop_event(AgentToolLoopCompleted(result=result))
        yield AgentCompleted(
            message=AgentChatMessage(
                id="evaluation-message",
                role="assistant",
                text="No draft was published.",
                transactionState="none",
            ),
            persist=True,
        )

    monkeypatch.setattr(
        "app.services.agent.runtime.streaming.async_iter_resolved_agent_events",
        fake_pipeline,
    )
    request = AgentChatRequest.model_validate(
        _request_data("tool-error-codes-current", "Create a grounded draft."),
    )

    observation = asyncio.run(execute_real_agent(request, _config()))
    summary = observation_summary(observation)

    assert observation.tool_error_count == 2
    assert observation.tool_error_code_sequence == (
        (
            "batch_rejected",
            "fragmentary_highlight",
            "duplicate_item_field_in_highlight",
        ),
        ("tool_error_without_code",),
    )
    assert summary["toolErrorCodeSequence"] == [
        [
            "batch_rejected",
            "fragmentary_highlight",
            "duplicate_item_field_in_highlight",
        ],
        ["tool_error_without_code"],
    ]
    assert summary["toolErrorCodeCounts"] == {
        "batch_rejected": 1,
        "duplicate_item_field_in_highlight": 1,
        "fragmentary_highlight": 1,
        "tool_error_without_code": 1,
    }
    assert sensitive_marker not in json.dumps(summary)


def test_real_observation_uses_only_final_edited_items_for_enrichment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    edits = [
        SimpleNamespace(
            target="sections.project.items.project-1",
            replacement="preview-only poison 99%",
            operation={
                "type": "update_item",
                "sectionId": "project",
                "itemId": "project-1",
                "patch": {"highlights": ["intermediate-a", "intermediate-b"]},
            },
            status="executed",
            diffs=[{"path": "sections.project.items.project-1.highlights"}],
        ),
        SimpleNamespace(
            target="sections.project.items.project-1",
            replacement="another preview-only poison",
            operation={
                "type": "update_item",
                "sectionId": "project",
                "itemId": "project-1",
                "patch": {"highlights": ["final-update"]},
            },
            status="executed",
            diffs=[{"path": "sections.project.items.project-1.highlights"}],
        ),
        SimpleNamespace(
            target="sections.project.items.project-2",
            replacement=None,
            operation={
                "type": "insert_item",
                "sectionId": "project",
                "item": {
                    "id": "project-2",
                    "name": "Inserted project",
                    "role": "Developer",
                    "techStack": [],
                    "period": "",
                    "url": "",
                    "description": "Inserted project description.",
                    "highlights": ["inserted-item-a", "inserted-item-b"],
                },
            },
            status="executed",
            diffs=[{"path": "sections.project.items.project-2"}],
        ),
        SimpleNamespace(
            target="sections.volunteer",
            replacement=None,
            operation={
                "type": "insert_section",
                "section": {
                    "id": "volunteer",
                    "kind": "project",
                    "title": "Volunteer projects",
                    "items": [
                        {
                            "id": "volunteer-1",
                            "name": "Volunteer project",
                            "role": "Developer",
                            "techStack": [],
                            "period": "",
                            "url": "",
                            "description": "Volunteer project description.",
                            "highlights": ["inserted-section"],
                        },
                    ],
                },
            },
            status="executed",
            diffs=[{"path": "sections.volunteer"}],
        ),
    ]
    base_resume = {
        "schemaVersion": 2,
        "basic": {
            "name": "",
            "headline": "",
            "phone": "",
            "email": "",
            "location": "",
            "avatar": "",
            "summary": "",
            "customFields": [],
        },
        "sections": [
            {
                "id": "project",
                "kind": "project",
                "title": "Projects",
                "items": [
                    {
                        "id": "project-1",
                        "name": "Existing project",
                        "role": "Developer",
                        "techStack": [],
                        "period": "",
                        "url": "",
                        "description": "Existing sourced result: 88%.",
                        "highlights": ["original"],
                    },
                ],
            },
            {
                "id": "untouched",
                "kind": "project",
                "title": "Untouched projects",
                "items": [
                    {
                        "id": "untouched-1",
                        "name": "Untouched project",
                        "role": "Developer",
                        "techStack": [],
                        "period": "",
                        "url": "",
                        "description": "Untouched description.",
                        "highlights": ["must-not-count"],
                    },
                ],
            },
        ],
    }
    result = _turn_result(
        edits=tuple(edits),
        tools=(
            SimpleNamespace(
                state="output-available",
                type="tool-edit_execute",
                output={"qualityIssues": []},
            ),
        ),
        transaction_state="committed",
    )

    async def fake_pipeline(_request, _config, runtime):
        runtime.record_tool_loop_event(AgentToolLoopCompleted(result=result))
        yield AgentCompleted(
            message=AgentChatMessage(
                id="evaluation-final-draft",
                role="assistant",
                text="Draft ready.",
                transactionState="committed",
            ),
            persist=True,
        )

    monkeypatch.setattr(
        "app.services.agent.runtime.streaming.async_iter_resolved_agent_events",
        fake_pipeline,
    )
    request = AgentChatRequest.model_validate(
        _request_data(
            "evaluation-final-draft",
            "Enrich the edited items.",
            resume=base_resume,
        ),
    )

    observation = asyncio.run(execute_real_agent(request, _config()))
    edit_text = "\n".join(observation.edit_payloads)

    assert observation.distinct_highlight_count == 4
    assert "final-update" in edit_text
    assert "inserted-item-a" in edit_text
    assert "inserted-section" in edit_text
    assert "intermediate-a" not in edit_text
    assert "preview-only" not in edit_text
    assert "must-not-count" not in edit_text
    assert (
        evaluate_observation(
            CaseExpectation(
                minDistinctHighlights=4,
                requiredEditStrings=["final-update", "inserted-section"],
                forbiddenEditStrings=[
                    "preview-only",
                    "intermediate-a",
                    "99%",
                    "Existing sourced result: 88%.",
                ],
            ),
            observation,
        )
        == []
    )


def test_accepted_controlled_rewording_warning_is_diagnostic_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_resume = {"basic": {"summary": "Original text."}, "sections": []}
    edit = SimpleNamespace(
        target="basic.summary",
        replacement="preview text",
        operation={
            "type": "replace_field",
            "path": "basic.summary",
            "value": "Final grounded-looking text.",
        },
        status="executed",
        diffs=[{"path": "basic.summary"}],
    )
    result = _turn_result(
        edits=(edit,),
        tools=(
            SimpleNamespace(
                state="output-available",
                type="tool-edit_execute",
                output={
                    "qualityIssues": [
                        {
                            "code": "unsupported_edit_claim",
                            "severity": "warning",
                        },
                    ],
                },
            ),
            SimpleNamespace(
                state="output-error",
                type="tool-edit_execute",
                output={
                    "qualityIssues": [
                        {
                            "code": "unsupported_edit_claim",
                            "severity": "warning",
                        },
                    ],
                },
            ),
        ),
        transaction_state="committed",
    )

    async def fake_pipeline(_request, _config, runtime):
        runtime.record_tool_loop_event(AgentToolLoopCompleted(result=result))
        yield AgentCompleted(
            message=AgentChatMessage(
                id="evaluation-warning",
                role="assistant",
                text="Draft ready.",
                transactionState="committed",
            ),
            persist=True,
        )

    monkeypatch.setattr(
        "app.services.agent.runtime.streaming.async_iter_resolved_agent_events",
        fake_pipeline,
    )
    request = AgentChatRequest.model_validate(
        _request_data(
            "evaluation-warning",
            "Create a draft.",
            resume=base_resume,
        ),
    )
    observation = asyncio.run(execute_real_agent(request, _config()))
    case = ModelEvalCase(
        id="accepted-unsupported-warning",
        description="Accepted controlled rewording remains a visible diagnostic.",
        request=_request_data("evaluation-warning", "Create a draft."),
        expect=CaseExpectation(
            minEdits=1,
            forbiddenEditStrings=["not-present"],
        ),
    )

    assert observation.unsupported_edit_claim_warning_count == 1
    assert evaluate_observation(case.expect, observation) == []

    async def provider(_request, _config):
        return observation

    report = asyncio.run(run_suite([case], _config(), executor=provider))
    assert report["metrics"]["editAccuracy"] == {
        "evaluatedCases": 1,
        "passedCases": 1,
        "rate": 1.0,
    }
    assert report["metrics"]["hallucination"] == {
        "evaluatedCases": 1,
        "violationCases": 0,
        "violationRate": 0.0,
    }


def test_real_observation_aggregates_provider_normalized_token_usage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _turn_result()

    async def fake_pipeline(_request, _config, runtime):
        runtime.record_llm_attempt()
        runtime.record_llm_response(
            LlmAssistantMessage(
                usage=LlmUsage(
                    input_tokens=120,
                    output_tokens=40,
                    total_tokens=160,
                    cached_input_tokens=80,
                    reasoning_tokens=25,
                ),
            ),
        )
        runtime.record_llm_attempt()
        runtime.record_llm_response(
            LlmAssistantMessage(
                usage=LlmUsage(
                    input_tokens=200,
                    output_tokens=60,
                    total_tokens=260,
                    cache_write_input_tokens=100,
                ),
            ),
        )
        runtime.record_tool_loop_event(AgentToolLoopCompleted(result=result))
        yield AgentCompleted(
            message=AgentChatMessage(
                id="evaluation-usage-message",
                role="assistant",
                text="Draft ready.",
            ),
            persist=True,
        )

    monkeypatch.setattr(
        "app.services.agent.runtime.streaming.async_iter_resolved_agent_events",
        fake_pipeline,
    )
    request = AgentChatRequest.model_validate(
        _request_data("usage-observation-current", "Create a grounded draft."),
    )

    observation = asyncio.run(execute_real_agent(request, _config()))

    assert observation.token_usage.request_attempts == 2
    assert observation.token_usage.terminal_responses == 2
    assert observation.token_usage.input_tokens == 320
    assert observation.token_usage.output_tokens == 100
    assert observation.token_usage.total_tokens == 420
    assert observation.token_usage.cached_input_tokens == 80
    assert observation.token_usage.cache_write_input_tokens == 100
    assert observation.token_usage.reasoning_tokens == 25
    assert observation.token_usage.input_tokens_reported_responses == 2
    assert observation.token_usage.total_tokens_reported_responses == 2
    assert observation.token_usage.cached_input_tokens_reported_responses == 1
    assert observation.token_usage.reasoning_tokens_reported_responses == 1
    response_summaries = observation_summary(observation)["modelResponses"]
    assert [item["outputTokens"] for item in response_summaries] == [40, 60]
    assert [item["reasoningTokens"] for item in response_summaries] == [25, None]
    assert all(item["durationMs"] >= 0 for item in response_summaries)


def test_real_execution_collects_usage_from_the_tool_loop_provider_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_provider(*_args, **kwargs):
        kwargs["on_provider_attempt"]()
        response = LlmAssistantMessage(
            content="The resume needs clearer project evidence.",
            usage=LlmUsage(total_tokens=90),
            stop_reason="stop",
        )
        yield LlmStreamEvent(type="text_delta", delta=response.content)
        yield LlmStreamEvent(type="done", message=response)

    monkeypatch.setattr(
        "app.services.agent.runtime.loop.async_stream_tool_call",
        fake_provider,
    )

    request = AgentChatRequest.model_validate(
        _request_data(
            "usage-provider-current",
            "Only explain the resume weaknesses. Do not edit the resume.",
        ),
    )

    observation = asyncio.run(
        execute_real_agent(
            request,
            replace(_config(), supports_streaming=False),
        ),
    )

    assert observation.response_text == "The resume needs clearer project evidence."
    assert observation.token_usage.request_attempts == 1
    assert observation.token_usage.terminal_responses == 1
    assert observation.token_usage.total_tokens == 90
    assert observation.token_usage.input_tokens_reported_responses == 0
    assert observation.token_usage.total_tokens_reported_responses == 1
    usage_report = observation_summary(observation)["tokenUsage"]
    assert usage_report["inputTokens"]["complete"] is False
    assert usage_report["totalTokens"]["complete"] is True


def test_real_execution_publishes_natural_completion_without_a_second_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_choice = LlmAssistantMessage(
        content="internal tool-loop answer",
        usage=LlmUsage(input_tokens=70, output_tokens=10, total_tokens=80),
        stop_reason="stop",
    )

    async def fake_tool_choice(*_args, **kwargs):
        kwargs["on_provider_attempt"]()
        yield LlmStreamEvent(type="text_delta", delta=tool_choice.content)
        yield LlmStreamEvent(type="done", message=tool_choice)

    monkeypatch.setattr(
        "app.services.agent.runtime.loop.async_stream_tool_call",
        fake_tool_choice,
    )
    request = AgentChatRequest.model_validate(
        _request_data(
            "production-final-current",
            "Answer this conversational question without editing the resume.",
        ),
    )

    observation = asyncio.run(
        execute_real_agent(
            request,
            replace(_config(), supports_streaming=False),
        ),
    )

    assert observation.response_text == "internal tool-loop answer"
    assert observation.token_usage.request_attempts == 1
    assert observation.token_usage.terminal_responses == 1
    assert observation.token_usage.total_tokens == 80


def test_environment_transaction_state_must_match_the_expected_commit() -> None:
    case = ModelEvalCase(
        id="environment-state",
        description="A naturally completed draft requires a committed transaction.",
        request=_request_data("environment-state-current", "Create the draft."),
        expect=CaseExpectation(
            minEdits=1,
            transactionState="committed",
        ),
    )

    async def rolled_back_environment(_request, _selected_config):
        return EvaluationObservation(
            response_text="Draft ready.",
            edit_payloads=("summary edit",),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="rolled_back",
            tool_names=("edit_execute",),
            tool_error_count=0,
        )

    report = asyncio.run(
        run_suite([case], _config(), executor=rolled_back_environment),
    )

    assert report["cases"][0]["passed"] is False
    assert report["cases"][0]["failureReasons"][0]["code"] == (
        "transaction_state_mismatch"
    )


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
            transaction_state="committed",
            tool_names=("edit_execute",),
            tool_error_count=0,
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
            edit_payloads=("generic final diff",),
            edit_targets=("basic.summary",),
            edit_count=1,
            rejected_edit_count=0,
            transaction_state="committed",
            tool_names=("edit_execute",),
            tool_error_count=0,
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
            transaction_state="committed",
            tool_names=("edit_execute",),
            tool_error_count=0,
        )

    report = asyncio.run(run_suite(cases, _config(), executor=provider))

    assert [case["passed"] for case in report["cases"]] == [True, False, False]
    assert report["cases"][1]["failureReasons"][0]["code"] == (
        "forbidden_response_string_present"
    )
    assert report["cases"][2]["failureReasons"][0]["code"] == (
        "forbidden_edit_string_present"
    )


def test_forbidden_response_patterns_are_enforced_as_output_quality() -> None:
    expectation = CaseExpectation(
        forbiddenResponseRegex=[r"\b(?:STAR|CAR|ATS)\b", "商业影响"],
    )
    observation = EvaluationObservation(
        response_text="建议使用 CAR 强调商业影响，再补充研究方法。",
        edit_payloads=(),
        edit_targets=(),
        edit_count=0,
        rejected_edit_count=0,
        transaction_state="none",
        tool_names=("resume_lookup",),
        tool_error_count=0,
    )

    failures = evaluate_observation(expectation, observation)

    assert {failure["code"] for failure in failures} == {
        "forbidden_response_pattern_present",
    }
    assert (
        sum(
            failure["code"] == "forbidden_response_pattern_present"
            for failure in failures
        )
        == 2
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
