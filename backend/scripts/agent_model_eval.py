"""Opt-in model-level evaluation for the resume Agent.

This script intentionally stays outside the pytest suite. It resolves one of
the application's configured models, runs synthetic requests through the real
Agent tool loop, and emits a redacted JSON report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.db.connection import connect
from app.schemas.agent import AgentChatRequest, AgentTransactionState
from app.services.llm import AgentLlmConfig
from app.services.llm.config import resolve_agent_llm_config

REPORT_SCHEMA_VERSION = 2
DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[1] / "tests" / "model_eval" / "scenarios.json"
)
MAX_ERROR_CHARS = 800
AUTHORIZATION_CREDENTIAL_RE = re.compile(
    r"\b(authorization)(\s*[:=]\s*)(?:(?:bearer|basic)\s+)?[^\s,;]+",
    flags=re.IGNORECASE,
)
BEARER_CREDENTIAL_RE = re.compile(
    r"\b(bearer)(?:\s*[:=]\s*|\s+)[^\s,;]+",
    flags=re.IGNORECASE,
)
API_KEY_CREDENTIAL_RE = re.compile(
    r"\b(api[_-]?key)(\s*[:=]\s*)[^\s,;]+",
    flags=re.IGNORECASE,
)


class AttachmentFixture(BaseModel):
    """Small text attachment materialized only for one evaluation case."""

    scope: Literal["current", "history"]
    filename: str
    media_type: str = Field(default="text/plain", alias="mediaType")
    content: str

    model_config = ConfigDict(populate_by_name=True)


class CaseExpectation(BaseModel):
    """Observable model behavior required for one scenario to pass."""

    min_edits: int = Field(default=0, alias="minEdits", ge=0)
    max_edits: int | None = Field(default=None, alias="maxEdits", ge=0)
    transaction_state: AgentTransactionState | None = Field(
        default=None,
        alias="transactionState",
    )
    runner_transaction_state: AgentTransactionState | None = Field(
        default=None,
        alias="runnerTransactionState",
    )
    finish_status: Literal["ready", "blocked"] | None = Field(
        default=None,
        alias="finishStatus",
    )
    min_response_chars: int = Field(default=0, alias="minResponseChars", ge=0)
    min_tool_errors: int = Field(default=0, alias="minToolErrors", ge=0)
    require_no_rejected_edits: bool = Field(
        default=True,
        alias="requireNoRejectedEdits",
    )
    required_edit_targets: list[str] = Field(
        default_factory=list,
        alias="requiredEditTargets",
    )
    required_tool_sequence: list[str] = Field(
        default_factory=list,
        alias="requiredToolSequence",
    )
    required_response_regex: list[str] = Field(
        default_factory=list,
        alias="requiredResponseRegex",
    )
    required_edit_strings: list[str] = Field(
        default_factory=list,
        alias="requiredEditStrings",
    )
    required_edit_regex: list[str] = Field(
        default_factory=list,
        alias="requiredEditRegex",
    )
    forbidden_response_strings: list[str] = Field(
        default_factory=list,
        alias="forbiddenResponseStrings",
    )
    forbidden_edit_strings: list[str] = Field(
        default_factory=list,
        alias="forbiddenEditStrings",
    )
    forbidden_edit_regex: list[str] = Field(
        default_factory=list,
        alias="forbiddenEditRegex",
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ModelEvalCase(BaseModel):
    """One synthetic request and its model-level assertions."""

    id: str
    description: str
    request: dict[str, Any]
    attachments: list[AttachmentFixture] = Field(default_factory=list)
    expect: CaseExpectation


class ModelEvalSuite(BaseModel):
    """Versioned fixture file consumed by this runner."""

    schema_version: int = Field(alias="schemaVersion")
    cases: list[ModelEvalCase]

    model_config = ConfigDict(populate_by_name=True)


@dataclass(frozen=True)
class EvaluationObservation:
    """Provider-independent facts collected from the Agent tool loop."""

    response_text: str
    edit_payloads: tuple[str, ...]
    edit_targets: tuple[str, ...]
    edit_count: int
    rejected_edit_count: int
    transaction_state: AgentTransactionState
    runner_transaction_state: AgentTransactionState
    tool_names: tuple[str, ...]
    tool_error_count: int
    finish_status: str


CaseExecutor = Callable[
    [AgentChatRequest, AgentLlmConfig],
    Awaitable[EvaluationObservation],
]


def load_suite(path: Path) -> ModelEvalSuite:
    """Load and validate a versioned model-evaluation fixture."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    suite = ModelEvalSuite.model_validate(raw)
    if suite.schema_version != REPORT_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported fixture schema version: {suite.schema_version}",
        )
    case_ids = [case.id for case in suite.cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Evaluation case ids must be unique.")
    return suite


async def execute_real_agent(
    request: AgentChatRequest,
    config: AgentLlmConfig,
) -> EvaluationObservation:
    """Call the configured provider through the production Agent tool loop."""

    # Keep the production Agent dependency behind the opt-in execution path.
    # Fixture validation and mock-provider tests must remain offline-safe.
    from app.services.agent.runtime.loop import async_iter_agent_tool_call_loop

    response_parts: list[str] = []
    public_transaction_state: AgentTransactionState = "none"
    runner = None

    async for event in async_iter_agent_tool_call_loop(request, config):
        if event.kind == "text" and event.text:
            response_parts.append(event.text)
        elif event.kind == "edits":
            public_transaction_state = event.transaction_state
        elif event.kind == "done":
            runner = event.runner

    if runner is None:
        raise RuntimeError("The Agent tool loop ended without a runner result.")

    message = runner.build_message()
    if message.text and message.text not in response_parts:
        response_parts.append(message.text)

    edit_payloads = tuple(
        json.dumps(
            {
                "replacement": edit.replacement,
                "operation": edit.operation,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        for edit in runner.edits
    )
    rejected_edit_count = sum(edit.status == "rejected" for edit in runner.edits)
    tool_error_count = sum(
        tool.state in {"output-error", "output-denied"} for tool in runner.tools
    )
    tool_names = [tool.type.removeprefix("tool-") for tool in runner.tools]
    # `finish` is a control boundary and is intentionally absent from the
    # user-visible tool timeline. The evaluation sequence must still record it
    # so a repaired transaction cannot pass without an explicit terminal call.
    if runner.finished:
        tool_names.append("finish")
    if runner.transaction_failed:
        public_transaction_state = "rolled_back"
    elif runner.edits and public_transaction_state == "none":
        # The public contract exposes edits as a draft even though the local
        # runner commits its internal atomic batch after a successful turn.
        public_transaction_state = "provisional"

    return EvaluationObservation(
        response_text="\n".join(response_parts).strip(),
        edit_payloads=edit_payloads,
        edit_targets=tuple(edit.target for edit in runner.edits),
        edit_count=len(runner.edits),
        rejected_edit_count=rejected_edit_count,
        transaction_state=public_transaction_state,
        runner_transaction_state=runner.transaction_state,
        tool_names=tuple(tool_names),
        tool_error_count=tool_error_count,
        finish_status=runner.finish_status,
    )


@contextmanager
def prepared_request(
    case: ModelEvalCase,
    config: AgentLlmConfig,
) -> Iterator[AgentChatRequest]:
    """Materialize current/history attachments and always remove them."""

    request_data = dict(case.request)
    message_data = dict(request_data.get("message") or {})
    message_text = str(message_data.get("text") or "")

    session_id = f"model-eval-{uuid4().hex}"
    stored_ids: list[str] = []
    current_files: list[dict[str, Any]] = []
    history_messages = list(request_data.get("messages") or [])
    delete_attachment: Callable[[str, str], bool] | None = None

    try:
        if case.attachments:
            # Attachment fixtures exercise the same persistence/evidence
            # boundary as a real turn, without importing it for offline cases.
            from app.services.agent.attachments import (
                delete_pending_agent_attachment,
                store_agent_attachment,
            )

            delete_attachment = delete_pending_agent_attachment

        for index, fixture in enumerate(case.attachments):
            stored = store_agent_attachment(
                session_id=session_id,
                filename=fixture.filename,
                media_type=fixture.media_type,
                payload=fixture.content.encode("utf-8"),
            )
            stored_ids.append(stored.id)
            reference = stored.model_dump(by_alias=True)
            if fixture.scope == "current":
                current_files.append(reference)
            else:
                history_messages.append(
                    {
                        "id": f"{case.id}-history-attachment-{index}",
                        "role": "user",
                        "text": "A file was attached in an earlier turn.",
                        "files": [reference],
                    },
                )

        request_data["resumeId"] = session_id if case.attachments else None
        # The eval calls the tool loop directly rather than persisting a chat
        # turn, but attachment ownership still gives the request a session id.
        # Supply a synthetic revision so the production request invariant stays
        # enforced instead of adding an eval-only exception to the schema.
        request_data["expectedRevision"] = (
            f"model-eval-{uuid4().hex}" if case.attachments else None
        )
        request_data["modelConfig"] = {"id": config.client_id}
        request_data["messages"] = history_messages
        configured_files = message_data.get("files") or []
        if not isinstance(configured_files, list):
            raise ValueError(
                f"Evaluation case {case.id!r} has invalid current files.",
            )
        message_data["files"] = [*configured_files, *current_files]
        if not message_text.strip() and not message_data["files"]:
            raise ValueError(
                f"Evaluation case {case.id!r} has an empty current message.",
            )
        request_data["message"] = message_data
        yield AgentChatRequest.model_validate(request_data)
    finally:
        if delete_attachment is not None:
            for attachment_id in stored_ids:
                delete_attachment(session_id, attachment_id)


async def run_suite(
    cases: Sequence[ModelEvalCase],
    config: AgentLlmConfig,
    *,
    executor: CaseExecutor = execute_real_agent,
) -> dict[str, Any]:
    """Run cases sequentially and return a key-safe machine-readable report."""

    started_at = datetime.now(UTC)
    results: list[dict[str, Any]] = []

    for case in cases:
        case_started = perf_counter()
        try:
            with prepared_request(case, config) as request:
                observation = await executor(request, config)
            failure_reasons = evaluate_observation(case.expect, observation)
            result = {
                "id": case.id,
                "description": case.description,
                "passed": not failure_reasons,
                "durationMs": round((perf_counter() - case_started) * 1000),
                "failureReasons": failure_reasons,
                "observed": observation_summary(observation),
            }
        except Exception as exc:
            result = {
                "id": case.id,
                "description": case.description,
                "passed": False,
                "durationMs": round((perf_counter() - case_started) * 1000),
                "failureReasons": [
                    {
                        "code": "execution_error",
                        "detail": redact_error(exc, config.api_key),
                    },
                ],
                "observed": None,
            }
        results.append(result)

    passed = sum(result["passed"] for result in results)
    total = len(results)
    completed_at = datetime.now(UTC)
    return {
        "schemaVersion": REPORT_SCHEMA_VERSION,
        "startedAt": started_at.isoformat(),
        "completedAt": completed_at.isoformat(),
        "provider": config.provider,
        "model": config.model,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "passRate": round(passed / total, 4) if total else 0.0,
        },
        "cases": results,
    }


def evaluate_observation(
    expect: CaseExpectation,
    observation: EvaluationObservation,
) -> list[dict[str, str]]:
    """Return stable failure codes with concise diagnostic details."""

    failures: list[dict[str, str]] = []
    if observation.edit_count < expect.min_edits:
        failures.append(
            _failure(
                "edit_count_too_low",
                f"Expected at least {expect.min_edits}; got {observation.edit_count}.",
            ),
        )
    if expect.max_edits is not None and observation.edit_count > expect.max_edits:
        failures.append(
            _failure(
                "edit_count_too_high",
                f"Expected at most {expect.max_edits}; got {observation.edit_count}.",
            ),
        )
    if (
        expect.transaction_state is not None
        and observation.transaction_state != expect.transaction_state
    ):
        failures.append(
            _failure(
                "transaction_state_mismatch",
                f"Expected {expect.transaction_state}; got "
                f"{observation.transaction_state}.",
            ),
        )
    if (
        expect.runner_transaction_state is not None
        and observation.runner_transaction_state != expect.runner_transaction_state
    ):
        failures.append(
            _failure(
                "runner_transaction_state_mismatch",
                f"Expected {expect.runner_transaction_state}; got "
                f"{observation.runner_transaction_state}.",
            ),
        )
    if (
        expect.finish_status is not None
        and observation.finish_status != expect.finish_status
    ):
        failures.append(
            _failure(
                "finish_status_mismatch",
                f"Expected {expect.finish_status}; got {observation.finish_status}.",
            ),
        )
    if len(observation.response_text) < expect.min_response_chars:
        failures.append(
            _failure(
                "response_too_short",
                f"Expected at least {expect.min_response_chars} response "
                f"characters; got {len(observation.response_text)}.",
            ),
        )
    if observation.tool_error_count < expect.min_tool_errors:
        failures.append(
            _failure(
                "tool_error_count_too_low",
                f"Expected at least {expect.min_tool_errors}; got "
                f"{observation.tool_error_count}.",
            ),
        )
    if expect.require_no_rejected_edits and observation.rejected_edit_count:
        failures.append(
            _failure(
                "rejected_edits_present",
                f"Observed {observation.rejected_edit_count} rejected edits.",
            ),
        )
    observed_targets = set(observation.edit_targets)
    for required_target in expect.required_edit_targets:
        if required_target not in observed_targets:
            failures.append(
                _failure(
                    "required_edit_target_missing",
                    f"Missing required edit target: {required_target!r}.",
                ),
            )
    if (
        expect.required_tool_sequence
        and tuple(expect.required_tool_sequence) != observation.tool_names
    ):
        failures.append(
            _failure(
                "tool_sequence_mismatch",
                f"Expected tool sequence {expect.required_tool_sequence!r}; got "
                f"{list(observation.tool_names)!r}.",
            ),
        )

    for pattern in expect.required_response_regex:
        if re.search(pattern, observation.response_text, flags=re.IGNORECASE) is None:
            failures.append(
                _failure(
                    "required_response_pattern_missing",
                    f"Missing required response pattern: {pattern!r}.",
                ),
            )
    response_text_folded = observation.response_text.casefold()
    for forbidden in expect.forbidden_response_strings:
        if forbidden.casefold() in response_text_folded:
            failures.append(
                _failure(
                    "forbidden_response_string_present",
                    f"Observed forbidden response string: {forbidden!r}.",
                ),
            )
    edit_text = "\n".join(observation.edit_payloads)
    edit_text_folded = edit_text.casefold()
    for required in expect.required_edit_strings:
        if required.casefold() not in edit_text_folded:
            failures.append(
                _failure(
                    "required_edit_string_missing",
                    f"Missing required edit string: {required!r}.",
                ),
            )
    for pattern in expect.required_edit_regex:
        if re.search(pattern, edit_text, flags=re.IGNORECASE) is None:
            failures.append(
                _failure(
                    "required_edit_pattern_missing",
                    f"Missing required edit pattern: {pattern!r}.",
                ),
            )
    for forbidden in expect.forbidden_edit_strings:
        if forbidden.casefold() in edit_text_folded:
            failures.append(
                _failure(
                    "forbidden_edit_string_present",
                    f"Observed forbidden edit string: {forbidden!r}.",
                ),
            )
    for pattern in expect.forbidden_edit_regex:
        if re.search(pattern, edit_text, flags=re.IGNORECASE) is not None:
            failures.append(
                _failure(
                    "forbidden_edit_pattern_present",
                    f"Observed forbidden edit pattern: {pattern!r}.",
                ),
            )
    return failures


def observation_summary(observation: EvaluationObservation) -> dict[str, Any]:
    """Expose diagnostics without embedding resume or model response content."""

    return {
        "editCount": observation.edit_count,
        "rejectedEditCount": observation.rejected_edit_count,
        "transactionState": observation.transaction_state,
        "runnerTransactionState": observation.runner_transaction_state,
        "toolNames": list(observation.tool_names),
        "toolErrorCount": observation.tool_error_count,
        "finishStatus": observation.finish_status,
        "responseChars": len(observation.response_text),
    }


def redact_error(error: Exception, api_key: str) -> str:
    """Redact the configured key and common credential-shaped fragments."""

    text = str(error).strip() or error.__class__.__name__
    if api_key:
        text = text.replace(api_key, "[REDACTED]")
    # Authorization must be handled as a whole before the standalone Bearer
    # form; otherwise only the scheme is removed and its token remains.
    text = AUTHORIZATION_CREDENTIAL_RE.sub(
        r"\1\2[REDACTED]",
        text,
    )
    text = BEARER_CREDENTIAL_RE.sub(
        r"\1 [REDACTED]",
        text,
    )
    text = API_KEY_CREDENTIAL_RE.sub(
        r"\1\2[REDACTED]",
        text,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", text)
    return text[:MAX_ERROR_CHARS]


def _failure(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _selected_cases(
    suite: ModelEvalSuite,
    selected_ids: Sequence[str],
) -> list[ModelEvalCase]:
    if not selected_ids:
        return suite.cases
    selected = set(selected_ids)
    cases = [case for case in suite.cases if case.id in selected]
    missing = selected.difference(case.id for case in cases)
    if missing:
        raise ValueError(f"Unknown evaluation case ids: {sorted(missing)}")
    return cases


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run opt-in resume Agent evaluation against a real model.",
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=DEFAULT_FIXTURE,
        help="Path to a versioned evaluation fixture.",
    )
    parser.add_argument(
        "--model-config-id",
        default="",
        help="Configured model client id; defaults to the enabled default model.",
    )
    parser.add_argument(
        "--case",
        action="append",
        default=[],
        dest="case_ids",
        help="Run one case id. Repeat to select multiple cases.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Also write the JSON report to this path.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point. A failing model case returns a non-zero status."""

    args = _build_parser().parse_args(argv)
    config: AgentLlmConfig | None = None
    try:
        suite = load_suite(args.fixture)
        cases = _selected_cases(suite, args.case_ids)
        with closing(connect()) as conn:
            selection = {"id": args.model_config_id} if args.model_config_id else None
            config = resolve_agent_llm_config(conn, selection)
        if config is None:
            raise RuntimeError("No enabled LLM configuration was found.")
        if not config.supports_tools:
            raise RuntimeError(
                "The selected model does not support Agent tool calls.",
            )
        report = asyncio.run(run_suite(cases, config))
        exit_code = 0 if report["summary"]["failed"] == 0 else 1
    except Exception as exc:
        report = {
            "schemaVersion": REPORT_SCHEMA_VERSION,
            "provider": config.provider if config else None,
            "model": config.model if config else None,
            "summary": {
                "total": 0,
                "passed": 0,
                "failed": 0,
                "passRate": 0.0,
            },
            "error": {
                "code": "runner_error",
                "detail": redact_error(exc, config.api_key if config else ""),
            },
            "cases": [],
        }
        exit_code = 2

    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(f"{serialized}\n", encoding="utf-8")
    sys.stdout.write(f"{serialized}\n")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
