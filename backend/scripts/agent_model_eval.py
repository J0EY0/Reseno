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
from collections import Counter
from collections.abc import Awaitable, Callable, Iterator, Sequence
from contextlib import closing, contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from app.db.connection import connect
from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentTransactionState,
)
from app.services.agent.draft import DraftTransaction
from app.services.agent.editing.operations import _apply_edit_operations
from app.services.agent.runtime.loop import (
    AgentToolLoopCompleted,
    AgentToolLoopEvent,
    AgentTurnResult,
)
from app.services.llm import AgentLlmConfig, LlmUsage
from app.services.llm.config import resolve_agent_llm_config
from app.services.llm.types import LlmStopReason
from app.services.resume_document_contract import (
    ResumeDocumentContractError,
    validate_resume_document,
)

REPORT_SCHEMA_VERSION = 5
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
    min_response_chars: int = Field(default=0, alias="minResponseChars", ge=0)
    min_tool_errors: int = Field(default=0, alias="minToolErrors", ge=0)
    min_sources: int = Field(default=0, alias="minSources", ge=0)
    min_distinct_highlights: int = Field(
        default=0,
        alias="minDistinctHighlights",
        ge=0,
    )
    require_no_rejected_edits: bool = Field(
        default=True,
        alias="requireNoRejectedEdits",
    )
    required_edit_targets: list[str] = Field(
        default_factory=list,
        alias="requiredEditTargets",
    )
    required_changed_paths: list[str] = Field(
        default_factory=list,
        alias="requiredChangedPaths",
    )
    required_changed_values: dict[str, Any] = Field(
        default_factory=dict,
        alias="requiredChangedValues",
    )
    required_tool_sequence: list[str] = Field(
        default_factory=list,
        alias="requiredToolSequence",
    )
    required_response_regex: list[str] = Field(
        default_factory=list,
        alias="requiredResponseRegex",
    )
    forbidden_response_regex: list[str] = Field(
        default_factory=list,
        alias="forbiddenResponseRegex",
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
    """Versioned fixture file consumed by this evaluator."""

    schema_version: int = Field(alias="schemaVersion")
    cases: list[ModelEvalCase]

    model_config = ConfigDict(populate_by_name=True)


@dataclass(frozen=True)
class EvaluationTokenUsage:
    """Usage summed across one Agent case without inventing missing values."""

    request_attempts: int = 0
    terminal_responses: int = 0
    input_tokens: int | None = None
    input_tokens_reported_responses: int = 0
    output_tokens: int | None = None
    output_tokens_reported_responses: int = 0
    total_tokens: int | None = None
    total_tokens_reported_responses: int = 0
    cached_input_tokens: int | None = None
    cached_input_tokens_reported_responses: int = 0
    cache_write_input_tokens: int | None = None
    cache_write_input_tokens_reported_responses: int = 0
    reasoning_tokens: int | None = None
    reasoning_tokens_reported_responses: int = 0


@dataclass
class _EvaluationCallCollector:
    """Collect only normalized usage and termination facts from LLM calls."""

    usages: list[LlmUsage | None] = field(default_factory=list)
    stop_reasons: list[LlmStopReason] = field(default_factory=list)
    request_attempts: int = 0
    result: AgentTurnResult | None = None
    response_durations_ms: list[int] = field(default_factory=list)
    _response_started_at: float | None = None

    def record_attempt(self) -> None:
        self.request_attempts += 1
        if self._response_started_at is None:
            self._response_started_at = perf_counter()

    def record(self, usage: LlmUsage | None, stop_reason: LlmStopReason) -> None:
        self.usages.append(usage)
        self.stop_reasons.append(stop_reason)
        started_at = self._response_started_at
        self.response_durations_ms.append(
            (
                round((perf_counter() - started_at) * 1000)
                if started_at is not None
                else 0
            ),
        )
        self._response_started_at = None

    def record_tool_loop_event(self, event: AgentToolLoopEvent) -> None:
        if isinstance(event, AgentToolLoopCompleted):
            self.result = event.result

    def token_usage(self) -> EvaluationTokenUsage:
        usages = [usage for usage in self.usages if usage is not None]
        return EvaluationTokenUsage(
            request_attempts=self.request_attempts,
            terminal_responses=len(self.usages),
            input_tokens=_sum_usage_field(usages, "input_tokens"),
            input_tokens_reported_responses=_usage_field_coverage(
                usages,
                "input_tokens",
            ),
            output_tokens=_sum_usage_field(usages, "output_tokens"),
            output_tokens_reported_responses=_usage_field_coverage(
                usages,
                "output_tokens",
            ),
            total_tokens=_sum_usage_field(usages, "total_tokens"),
            total_tokens_reported_responses=_usage_field_coverage(
                usages,
                "total_tokens",
            ),
            cached_input_tokens=_sum_usage_field(usages, "cached_input_tokens"),
            cached_input_tokens_reported_responses=_usage_field_coverage(
                usages,
                "cached_input_tokens",
            ),
            cache_write_input_tokens=_sum_usage_field(
                usages,
                "cache_write_input_tokens",
            ),
            cache_write_input_tokens_reported_responses=_usage_field_coverage(
                usages,
                "cache_write_input_tokens",
            ),
            reasoning_tokens=_sum_usage_field(usages, "reasoning_tokens"),
            reasoning_tokens_reported_responses=_usage_field_coverage(
                usages,
                "reasoning_tokens",
            ),
        )

    @property
    def truncated(self) -> bool:
        return "length" in self.stop_reasons


class _EvaluationExecutionFailure(RuntimeError):
    """Carry safe partial metrics when the real Agent case cannot complete."""

    def __init__(
        self,
        cause: Exception,
        *,
        token_usage: EvaluationTokenUsage,
        truncated: bool,
    ) -> None:
        super().__init__(str(cause))
        self.token_usage = token_usage
        self.truncated = truncated


def _sum_usage_field(
    usages: Sequence[LlmUsage],
    field_name: str,
) -> int | None:
    values = [
        value
        for usage in usages
        for value in [getattr(usage, field_name)]
        if value is not None
    ]
    return sum(values) if values else None


def _usage_field_coverage(
    usages: Sequence[LlmUsage],
    field_name: str,
) -> int:
    return sum(getattr(usage, field_name) is not None for usage in usages)


@dataclass(frozen=True)
class EvaluationObservation:
    """Provider-independent facts collected from the Agent tool loop."""

    response_text: str
    edit_payloads: tuple[str, ...]
    edit_targets: tuple[str, ...]
    edit_count: int
    rejected_edit_count: int
    transaction_state: AgentTransactionState
    tool_names: tuple[str, ...]
    tool_error_count: int
    changed_paths: tuple[str, ...] = ()
    changed_values: dict[str, Any] = field(default_factory=dict)
    source_count: int = 0
    tool_error_code_sequence: tuple[tuple[str, ...], ...] = ()
    distinct_highlight_count: int = 0
    unsupported_edit_claim_warning_count: int = 0
    token_usage: EvaluationTokenUsage = EvaluationTokenUsage()
    model_responses: tuple[tuple[LlmUsage | None, LlmStopReason, int], ...] = ()
    truncated: bool = False


CaseExecutor = Callable[
    [AgentChatRequest, AgentLlmConfig],
    Awaitable[EvaluationObservation],
]


@dataclass(frozen=True)
class _MetricCaseResult:
    expectation: CaseExpectation
    observation: EvaluationObservation | None
    failure_codes: frozenset[str]
    duration_ms: int
    token_usage: EvaluationTokenUsage
    truncated: bool


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
    for case in suite.cases:
        try:
            validate_resume_document(case.request.get("resume"))
        except ResumeDocumentContractError as exc:
            raise ValueError(
                f"Evaluation case {case.id!r} has an invalid resume: "
                f"{exc.code} at {exc.path}.",
            ) from exc
    return suite


async def execute_real_agent(
    request: AgentChatRequest,
    config: AgentLlmConfig,
) -> EvaluationObservation:
    """Call the configured provider through the production Agent tool loop."""

    # Keep the production Agent dependency behind the opt-in execution path.
    # Fixture validation and mock-provider tests must remain offline-safe.
    from app.services.agent.runtime.streaming import (
        AgentCompleted,
        AgentStreamError,
        async_iter_resolved_agent_events,
    )

    call_collector = _EvaluationCallCollector()

    from app.services.agent.runtime.context import AgentRuntimeContext

    runtime = AgentRuntimeContext(
        on_llm_attempt=call_collector.record_attempt,
        on_llm_response=call_collector.record,
        on_tool_loop_event=call_collector.record_tool_loop_event,
    )
    completed_messages: list[AgentChatMessage] = []
    provider_error = ""

    try:
        async for event in async_iter_resolved_agent_events(
            request,
            config,
            runtime=runtime,
        ):
            if isinstance(event, AgentCompleted):
                completed_messages.append(event.message)
            elif isinstance(event, AgentStreamError):
                provider_error = event.message
    except Exception as exc:
        raise _EvaluationExecutionFailure(
            exc,
            token_usage=call_collector.token_usage(),
            truncated=call_collector.truncated,
        ) from exc

    if provider_error:
        raise _EvaluationExecutionFailure(
            RuntimeError(provider_error),
            token_usage=call_collector.token_usage(),
            truncated=call_collector.truncated,
        )
    if not completed_messages:
        raise _EvaluationExecutionFailure(
            RuntimeError("The Agent pipeline ended without a completed message."),
            token_usage=call_collector.token_usage(),
            truncated=call_collector.truncated,
        )

    result = call_collector.result
    if result is None:
        raise RuntimeError("The Agent tool loop ended without an environment result.")
    message = completed_messages[-1]

    base_resume = DraftTransaction.from_request(request).active_resume
    draft_resume = deepcopy(base_resume)
    _apply_edit_operations(draft_resume, list(result.edits))
    edit_payloads, distinct_highlight_count, changed_values = _final_edit_evidence(
        base_resume,
        draft_resume,
        result.edits,
    )
    rejected_edit_count = sum(edit.status == "rejected" for edit in result.edits)
    tool_error_count = sum(
        tool.state in {"output-error", "output-denied"} for tool in result.tools
    )
    tool_error_code_sequence = _tool_error_code_sequence(result.tools)
    tool_names = [tool.type.removeprefix("tool-") for tool in result.tools]
    return EvaluationObservation(
        response_text=message.text.strip(),
        edit_payloads=edit_payloads,
        edit_targets=tuple(edit.target for edit in result.edits),
        edit_count=len(result.edits),
        rejected_edit_count=rejected_edit_count,
        transaction_state=result.transaction_state,
        tool_names=tuple(tool_names),
        tool_error_count=tool_error_count,
        changed_paths=tuple(sorted(changed_values)),
        changed_values=changed_values,
        source_count=len(message.sources),
        tool_error_code_sequence=tool_error_code_sequence,
        distinct_highlight_count=distinct_highlight_count,
        unsupported_edit_claim_warning_count=(
            _accepted_unsupported_edit_claim_warning_count(result.tools)
        ),
        token_usage=call_collector.token_usage(),
        model_responses=tuple(
            zip(
                call_collector.usages,
                call_collector.stop_reasons,
                call_collector.response_durations_ms,
                strict=True,
            ),
        ),
        truncated=call_collector.truncated,
    )


def _final_edit_evidence(
    base_resume: dict[str, Any],
    draft_resume: dict[str, Any],
    edits: Sequence[Any],
) -> tuple[tuple[str, ...], int, dict[str, Any]]:
    """Return final changed paths, their values, and distinct highlights.

    A model may revise the same target several times in one tool loop. Counting
    every operation patch would union discarded intermediate text, while the
    human reviews only the environment's final draft. We therefore use operation
    diffs solely to prove that a target was really mutated, then resolve that
    target once from the final draft and exclude targets reverted to base.
    """

    basic_fields: set[str] = set()
    inserted_sections: set[str] = set()
    updated_section_fields: set[tuple[str, str]] = set()
    inserted_items: set[tuple[str, str]] = set()
    updated_item_fields: set[tuple[str, str, str]] = set()

    for edit in edits:
        operation = getattr(edit, "operation", None)
        diffs = getattr(edit, "diffs", None)
        if (
            getattr(edit, "status", None) == "rejected"
            or not isinstance(operation, dict)
            or not isinstance(diffs, list)
            or not diffs
        ):
            continue

        diff_paths = {
            path
            for diff in diffs
            if isinstance(diff, dict) and isinstance((path := diff.get("path")), str)
        }
        operation_type = operation.get("type")
        if operation_type == "replace_field":
            path = operation.get("path")
            if (
                isinstance(path, str)
                and path.startswith("basic.")
                and path in diff_paths
            ):
                basic_fields.add(path.removeprefix("basic."))
            continue

        if operation_type == "insert_section":
            section = operation.get("section")
            section_id = section.get("id") if isinstance(section, dict) else None
            if (
                isinstance(section_id, str)
                and section_id
                and f"sections.{section_id}" in diff_paths
            ):
                inserted_sections.add(section_id)
            continue

        section_id = operation.get("sectionId")
        if not isinstance(section_id, str) or not section_id:
            continue
        if operation_type == "update_section":
            patch = operation.get("patch")
            if not isinstance(patch, dict):
                continue
            updated_section_fields.update(
                (section_id, field)
                for field in patch
                if isinstance(field, str)
                and f"sections.{section_id}.{field}" in diff_paths
            )
            continue
        if operation_type == "insert_item":
            item = operation.get("item")
            item_id = item.get("id") if isinstance(item, dict) else None
            if (
                isinstance(item_id, str)
                and item_id
                and f"sections.{section_id}.items.{item_id}" in diff_paths
            ):
                inserted_items.add((section_id, item_id))
            continue
        if operation_type == "update_item":
            item_id = operation.get("itemId")
            patch = operation.get("patch")
            if not (isinstance(item_id, str) and item_id and isinstance(patch, dict)):
                continue
            base_path = f"sections.{section_id}.items.{item_id}"
            updated_item_fields.update(
                (section_id, item_id, field)
                for field in patch
                if isinstance(field, str) and f"{base_path}.{field}" in diff_paths
            )

    payload_values: list[Any] = []
    changed_values: dict[str, Any] = {}
    base_basic = base_resume.get("basic")
    draft_basic = draft_resume.get("basic")
    if not isinstance(base_basic, dict):
        base_basic = {}
    if not isinstance(draft_basic, dict):
        draft_basic = {}
    for field_name in sorted(basic_fields):
        if field_name in draft_basic and draft_basic.get(field_name) != base_basic.get(
            field_name
        ):
            payload_values.append(draft_basic[field_name])
            changed_values[f"basic.{field_name}"] = draft_basic[field_name]

    changed_inserted_sections: set[str] = set()
    for section_id in sorted(inserted_sections):
        draft_section = _resume_section(draft_resume, section_id)
        base_section = _resume_section(base_resume, section_id)
        if draft_section is not None and draft_section != base_section:
            changed_inserted_sections.add(section_id)
            payload_values.append(draft_section)
            changed_values[f"sections.{section_id}"] = draft_section

    for section_id, field_name in sorted(updated_section_fields):
        if section_id in changed_inserted_sections:
            continue
        draft_section = _resume_section(draft_resume, section_id)
        base_section = _resume_section(base_resume, section_id)
        if (
            draft_section is not None
            and field_name in draft_section
            and (
                base_section is None
                or draft_section.get(field_name) != base_section.get(field_name)
            )
        ):
            payload_values.append(draft_section[field_name])
            changed_values[f"sections.{section_id}.{field_name}"] = draft_section[
                field_name
            ]

    changed_items: set[tuple[str, str]] = set()
    changed_inserted_items: set[tuple[str, str]] = set()
    for section_id, item_id in sorted(inserted_items):
        if section_id in changed_inserted_sections:
            continue
        draft_item = _resume_item(draft_resume, section_id, item_id)
        base_item = _resume_item(base_resume, section_id, item_id)
        if draft_item is not None and draft_item != base_item:
            changed_items.add((section_id, item_id))
            changed_inserted_items.add((section_id, item_id))
            payload_values.append(draft_item)
            changed_values[f"sections.{section_id}.items.{item_id}"] = draft_item

    for section_id, item_id, field_name in sorted(updated_item_fields):
        if (
            section_id in changed_inserted_sections
            or (section_id, item_id) in changed_inserted_items
        ):
            continue
        draft_item = _resume_item(draft_resume, section_id, item_id)
        base_item = _resume_item(base_resume, section_id, item_id)
        if (
            draft_item is not None
            and field_name in draft_item
            and (
                base_item is None
                or draft_item.get(field_name) != base_item.get(field_name)
            )
        ):
            changed_items.add((section_id, item_id))
            payload_values.append(draft_item[field_name])
            changed_values[f"sections.{section_id}.items.{item_id}.{field_name}"] = (
                draft_item[field_name]
            )

    # Every item inside a newly inserted section belongs to the final edit
    # scope, including items appended later by insert_item in the same turn.
    for section_id in changed_inserted_sections:
        section = _resume_section(draft_resume, section_id)
        items = section.get("items") if section is not None else None
        if not isinstance(items, list):
            continue
        changed_items.update(
            (section_id, item_id)
            for item in items
            if isinstance(item, dict) and isinstance((item_id := item.get("id")), str)
        )

    distinct_highlights: set[str] = set()
    for section_id, item_id in changed_items:
        item = _resume_item(draft_resume, section_id, item_id)
        highlights = item.get("highlights") if item is not None else None
        if not isinstance(highlights, list):
            continue
        distinct_highlights.update(
            value.strip().casefold()
            for value in highlights
            if isinstance(value, str) and value.strip()
        )

    return (
        tuple(
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for value in payload_values
        ),
        len(distinct_highlights),
        changed_values,
    )


def _resume_section(
    resume: dict[str, Any],
    section_id: str,
) -> dict[str, Any] | None:
    sections = resume.get("sections")
    if not isinstance(sections, list):
        return None
    return next(
        (
            section
            for section in sections
            if isinstance(section, dict) and section.get("id") == section_id
        ),
        None,
    )


def _resume_item(
    resume: dict[str, Any],
    section_id: str,
    item_id: str,
) -> dict[str, Any] | None:
    section = _resume_section(resume, section_id)
    items = section.get("items") if section is not None else None
    if not isinstance(items, list):
        return None
    return next(
        (
            item
            for item in items
            if isinstance(item, dict) and item.get("id") == item_id
        ),
        None,
    )


def _accepted_unsupported_edit_claim_warning_count(
    tools: Sequence[Any],
) -> int:
    """Count advisory evidence failures on edit batches the environment accepted."""

    count = 0
    for tool in tools:
        if getattr(tool, "state", None) != "output-available":
            continue
        output = getattr(tool, "output", None)
        quality_issues = (
            output.get("qualityIssues") if isinstance(output, dict) else None
        )
        if not isinstance(quality_issues, list):
            continue
        count += sum(
            isinstance(issue, dict)
            and issue.get("code") == "unsupported_edit_claim"
            and issue.get("severity") == "warning"
            for issue in quality_issues
        )
    return count


_SAFE_DIAGNOSTIC_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,79}$")


def _tool_error_code_sequence(
    tools: Sequence[Any],
) -> tuple[tuple[str, ...], ...]:
    """Return content-free error codes grouped by failed tool invocation."""

    sequence: list[tuple[str, ...]] = []
    for tool in tools:
        if getattr(tool, "state", None) not in {"output-error", "output-denied"}:
            continue

        output = getattr(tool, "output", None)
        codes: list[str] = []
        if isinstance(output, dict):
            _append_diagnostic_code(codes, output.get("code"))
            _append_diagnostic_code(codes, output.get("reason"))
            rejected_edits = output.get("rejectedEdits")
            if isinstance(rejected_edits, list):
                for rejected_edit in rejected_edits:
                    if not isinstance(rejected_edit, dict):
                        continue
                    _append_diagnostic_code(codes, rejected_edit.get("code"))
                    quality_issue = rejected_edit.get("qualityIssue")
                    if isinstance(quality_issue, dict):
                        _append_diagnostic_code(codes, quality_issue.get("code"))

        sequence.append(tuple(codes) or ("tool_error_without_code",))
    return tuple(sequence)


def _append_diagnostic_code(codes: list[str], value: object) -> None:
    """Keep only stable internal identifiers and de-duplicate per invocation."""

    if (
        isinstance(value, str)
        and _SAFE_DIAGNOSTIC_CODE_RE.fullmatch(value)
        and value not in codes
    ):
        codes.append(value)


@contextmanager
def prepared_request(
    case: ModelEvalCase,
    config: AgentLlmConfig,
) -> Iterator[AgentChatRequest]:
    """Materialize current/history attachments and always remove them."""

    request_data = dict(case.request)
    message_data = dict(request_data.get("message") or {})
    message_text = str(message_data.get("text") or "")

    session_id = f"modeleval{uuid4().hex}"
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
            f"modeleval{uuid4().hex}" if case.attachments else None
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
    repeat: int = 1,
) -> dict[str, Any]:
    """Run cases sequentially and return a key-safe machine-readable report."""

    if repeat < 1:
        raise ValueError("repeat must be a positive integer.")

    started_at = datetime.now(UTC)
    results: list[dict[str, Any]] = []
    metric_cases: list[_MetricCaseResult] = []

    for case in cases:
        runs: list[dict[str, Any]] = []
        case_metric_runs: list[_MetricCaseResult] = []
        for run_number in range(1, repeat + 1):
            case_started = perf_counter()
            observation: EvaluationObservation | None = None
            token_usage = EvaluationTokenUsage()
            truncated = False
            try:
                with prepared_request(case, config) as request:
                    observation = await executor(request, config)
                failure_reasons = evaluate_observation(case.expect, observation)
                token_usage = observation.token_usage
                truncated = observation.truncated
                duration_ms = round((perf_counter() - case_started) * 1000)
                run_result = {
                    "run": run_number,
                    "passed": not failure_reasons,
                    "durationMs": duration_ms,
                    "failureReasons": failure_reasons,
                    "observed": observation_summary(observation),
                }
            except Exception as exc:
                duration_ms = round((perf_counter() - case_started) * 1000)
                if isinstance(exc, _EvaluationExecutionFailure):
                    token_usage = exc.token_usage
                    truncated = exc.truncated
                failure_code = "output_truncated" if truncated else "execution_error"
                failure_reasons = [
                    {
                        "code": failure_code,
                        "detail": redact_error(exc, config.api_key),
                    },
                ]
                run_result = {
                    "run": run_number,
                    "passed": False,
                    "durationMs": duration_ms,
                    "failureReasons": failure_reasons,
                    "observed": (
                        {
                            "truncated": truncated,
                            "tokenUsage": _token_usage_payload(token_usage),
                        }
                        if truncated
                        or token_usage.request_attempts
                        or token_usage.terminal_responses
                        else None
                    ),
                }
            runs.append(run_result)
            case_metric_runs.append(
                _MetricCaseResult(
                    expectation=case.expect,
                    observation=observation,
                    failure_codes=frozenset(
                        failure["code"] for failure in failure_reasons
                    ),
                    duration_ms=duration_ms,
                    token_usage=token_usage,
                    truncated=truncated,
                ),
            )

        pass_count = sum(run["passed"] for run in runs)
        durations = [metric.duration_ms for metric in case_metric_runs]
        tool_name_counts = Counter(
            tool_name
            for metric in case_metric_runs
            if metric.observation is not None
            for tool_name in metric.observation.tool_names
        )
        results.append(
            {
                "id": case.id,
                "description": case.description,
                "passed": pass_count == repeat,
                "passCount": pass_count,
                "runCount": repeat,
                "passRate": _rate(pass_count, repeat),
                "durationMs": sum(durations),
                "durationStatsMs": _count_statistics(durations),
                "modelAttempts": _count_statistics(
                    [
                        metric.token_usage.request_attempts
                        for metric in case_metric_runs
                    ],
                ),
                "modelResponses": _count_statistics(
                    [
                        metric.token_usage.terminal_responses
                        for metric in case_metric_runs
                    ],
                ),
                "toolCalls": {
                    **_count_statistics(
                        [
                            len(metric.observation.tool_names)
                            if metric.observation is not None
                            else 0
                            for metric in case_metric_runs
                        ],
                    ),
                    "byName": dict(sorted(tool_name_counts.items())),
                },
                "failureReasons": [
                    failure
                    for run in runs
                    for failure in run["failureReasons"]
                ],
                "observed": runs[-1]["observed"],
                "runs": runs,
            },
        )
        metric_cases.extend(case_metric_runs)

    passed = sum(result["passed"] for result in results)
    total = len(results)
    run_count = total * repeat
    passed_runs = sum(result["passCount"] for result in results)
    pass_at_n = sum(result["passCount"] > 0 for result in results)
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
            "runCount": run_count,
            "passedRuns": passed_runs,
            "failedRuns": run_count - passed_runs,
            "runPassRate": _rate(passed_runs, run_count),
            "passAtN": {
                "n": repeat,
                "passedCases": pass_at_n,
                "rate": _rate(pass_at_n, total),
            },
            "stablePass": {
                "n": repeat,
                "passedCases": passed,
                "rate": _rate(passed, total),
            },
        },
        "metrics": _evaluation_metrics(metric_cases),
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
    if observation.source_count < expect.min_sources:
        failures.append(
            _failure(
                "source_count_too_low",
                f"Expected at least {expect.min_sources}; got "
                f"{observation.source_count}.",
            ),
        )
    if observation.distinct_highlight_count < expect.min_distinct_highlights:
        failures.append(
            _failure(
                "distinct_highlight_count_too_low",
                f"Expected at least {expect.min_distinct_highlights} distinct "
                f"highlights; got {observation.distinct_highlight_count}.",
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
    observed_paths = set(observation.changed_paths)
    for required_path in expect.required_changed_paths:
        if required_path not in observed_paths:
            failures.append(
                _failure(
                    "required_changed_path_missing",
                    f"Missing required changed path: {required_path!r}.",
                ),
            )
    missing_value = object()
    for path, expected_value in expect.required_changed_values.items():
        if observation.changed_values.get(path, missing_value) != expected_value:
            failures.append(
                _failure(
                    "required_changed_value_mismatch",
                    f"Changed value mismatch at required path: {path!r}.",
                ),
            )
    if expect.required_tool_sequence and not _contains_ordered_actions(
        observation.tool_names,
        expect.required_tool_sequence,
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
    for pattern in expect.forbidden_response_regex:
        if (
            re.search(pattern, observation.response_text, flags=re.IGNORECASE)
            is not None
        ):
            failures.append(
                _failure(
                    "forbidden_response_pattern_present",
                    f"Observed forbidden response pattern: {pattern!r}.",
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


def _contains_ordered_actions(
    observed: Sequence[str],
    required: Sequence[str],
) -> bool:
    if not required:
        return True
    required_index = 0
    for tool_name in observed:
        if tool_name == required[required_index]:
            required_index += 1
            if required_index == len(required):
                return True
    return False


def observation_summary(observation: EvaluationObservation) -> dict[str, Any]:
    """Expose diagnostics without embedding resume or model response content."""

    tool_error_code_counts = Counter(
        code
        for invocation_codes in observation.tool_error_code_sequence
        for code in invocation_codes
    )
    return {
        "editCount": observation.edit_count,
        "rejectedEditCount": observation.rejected_edit_count,
        "distinctHighlightCount": observation.distinct_highlight_count,
        "unsupportedEditClaimWarningCount": (
            observation.unsupported_edit_claim_warning_count
        ),
        "transactionState": observation.transaction_state,
        "toolNames": list(observation.tool_names),
        "toolErrorCount": observation.tool_error_count,
        "sourceCount": observation.source_count,
        "changedPaths": list(observation.changed_paths),
        "toolErrorCodeSequence": [
            list(codes) for codes in observation.tool_error_code_sequence
        ],
        "toolErrorCodeCounts": dict(sorted(tool_error_code_counts.items())),
        "responseChars": len(observation.response_text),
        "truncated": observation.truncated,
        "tokenUsage": _token_usage_payload(observation.token_usage),
        "modelResponses": [
            {
                "durationMs": duration_ms,
                "stopReason": stop_reason,
                "inputTokens": usage.input_tokens if usage is not None else None,
                "outputTokens": usage.output_tokens if usage is not None else None,
                "reasoningTokens": (
                    usage.reasoning_tokens if usage is not None else None
                ),
                "cachedInputTokens": (
                    usage.cached_input_tokens if usage is not None else None
                ),
            }
            for usage, stop_reason, duration_ms in observation.model_responses
        ],
    }


EDIT_ACCURACY_FAILURE_CODES = frozenset(
    {
        "distinct_highlight_count_too_low",
        "edit_count_too_low",
        "edit_count_too_high",
        "rejected_edits_present",
        "required_edit_target_missing",
        "required_changed_path_missing",
        "required_changed_value_mismatch",
        "required_edit_string_missing",
        "required_edit_pattern_missing",
        "transaction_state_mismatch",
        "execution_error",
        "output_truncated",
    },
)
TOOL_COMPLETION_FAILURE_CODES = frozenset(
    {
        "source_count_too_low",
        "transaction_state_mismatch",
        "tool_error_count_too_low",
        "tool_sequence_mismatch",
        "execution_error",
        "output_truncated",
    },
)
HALLUCINATION_FAILURE_CODES = frozenset(
    {
        "forbidden_response_pattern_present",
        "forbidden_response_string_present",
        "forbidden_edit_string_present",
        "forbidden_edit_pattern_present",
    },
)


def _evaluation_metrics(cases: Sequence[_MetricCaseResult]) -> dict[str, Any]:
    edit_cases = [case for case in cases if _evaluates_edit_accuracy(case.expectation)]
    tool_cases = [
        case for case in cases if _evaluates_tool_completion(case.expectation)
    ]
    hallucination_cases = [
        case
        for case in cases
        if case.observation is not None and _evaluates_hallucination(case.expectation)
    ]
    truncated_cases = sum(case.truncated for case in cases)
    durations = [case.duration_ms for case in cases]
    usage = _aggregate_token_usage(
        [case.token_usage for case in cases],
    )

    return {
        "editAccuracy": _passing_metric(edit_cases, EDIT_ACCURACY_FAILURE_CODES),
        "toolCompletion": _passing_metric(
            tool_cases,
            TOOL_COMPLETION_FAILURE_CODES,
        ),
        "hallucination": {
            "evaluatedCases": len(hallucination_cases),
            "violationCases": sum(
                bool(case.failure_codes & HALLUCINATION_FAILURE_CODES)
                for case in hallucination_cases
            ),
            "violationRate": _rate(
                sum(
                    bool(case.failure_codes & HALLUCINATION_FAILURE_CODES)
                    for case in hallucination_cases
                ),
                len(hallucination_cases),
            ),
        },
        "truncation": {
            "evaluatedCases": len(cases),
            "truncatedCases": truncated_cases,
            "rate": _rate(truncated_cases, len(cases)),
        },
        "latencyMs": _count_statistics(durations),
        "tokenUsage": _token_usage_payload(usage),
        # Providers normalize token counts, but the configured model does not
        # carry authoritative, effective-dated prices. A guessed model-name
        # table would silently produce wrong comparisons, so cost stays
        # explicitly unavailable until the provider supplies trusted pricing.
        "cost": {
            "status": "unavailable",
            "amount": None,
            "currency": None,
            "reason": "No authoritative configured-model price metadata is available.",
        },
    }


def _passing_metric(
    cases: Sequence[_MetricCaseResult],
    failure_codes: frozenset[str],
) -> dict[str, int | float]:
    passed = sum(not (case.failure_codes & failure_codes) for case in cases)
    return {
        "evaluatedCases": len(cases),
        "passedCases": passed,
        "rate": _rate(passed, len(cases)),
    }


def _count_statistics(values: Sequence[int]) -> dict[str, int]:
    """Summarize repeated integer observations with nearest-rank percentiles."""

    ordered = sorted(values)
    total = sum(ordered)
    return {
        "total": total,
        "average": round(total / len(ordered)) if ordered else 0,
        "p50": _nearest_rank_percentile(ordered, 50),
        "p95": _nearest_rank_percentile(ordered, 95),
        "maximum": ordered[-1] if ordered else 0,
    }


def _nearest_rank_percentile(ordered: Sequence[int], percentile: int) -> int:
    if not ordered:
        return 0
    rank = (percentile * len(ordered) + 99) // 100
    return ordered[max(rank - 1, 0)]


def _rate(count: int, total: int) -> float:
    return round(count / total, 4) if total else 0.0


def _evaluates_edit_accuracy(expectation: CaseExpectation) -> bool:
    return bool(
        expectation.min_edits
        or expectation.min_distinct_highlights
        or expectation.required_edit_targets
        or expectation.required_changed_paths
        or expectation.required_changed_values
        or expectation.required_edit_strings
        or expectation.required_edit_regex
    )


def _evaluates_tool_completion(expectation: CaseExpectation) -> bool:
    return bool(
        expectation.transaction_state is not None
        or expectation.min_tool_errors
        or expectation.min_sources
        or expectation.required_tool_sequence
    )


def _evaluates_hallucination(expectation: CaseExpectation) -> bool:
    return bool(
        expectation.forbidden_response_strings
        or expectation.forbidden_response_regex
        or expectation.forbidden_edit_strings
        or expectation.forbidden_edit_regex
    )


def _aggregate_token_usage(
    usages: Sequence[EvaluationTokenUsage],
) -> EvaluationTokenUsage:
    return EvaluationTokenUsage(
        request_attempts=sum(usage.request_attempts for usage in usages),
        terminal_responses=sum(usage.terminal_responses for usage in usages),
        input_tokens=_sum_evaluation_usage(usages, "input_tokens"),
        input_tokens_reported_responses=sum(
            usage.input_tokens_reported_responses for usage in usages
        ),
        output_tokens=_sum_evaluation_usage(usages, "output_tokens"),
        output_tokens_reported_responses=sum(
            usage.output_tokens_reported_responses for usage in usages
        ),
        total_tokens=_sum_evaluation_usage(usages, "total_tokens"),
        total_tokens_reported_responses=sum(
            usage.total_tokens_reported_responses for usage in usages
        ),
        cached_input_tokens=_sum_evaluation_usage(usages, "cached_input_tokens"),
        cached_input_tokens_reported_responses=sum(
            usage.cached_input_tokens_reported_responses for usage in usages
        ),
        cache_write_input_tokens=_sum_evaluation_usage(
            usages,
            "cache_write_input_tokens",
        ),
        cache_write_input_tokens_reported_responses=sum(
            usage.cache_write_input_tokens_reported_responses for usage in usages
        ),
        reasoning_tokens=_sum_evaluation_usage(usages, "reasoning_tokens"),
        reasoning_tokens_reported_responses=sum(
            usage.reasoning_tokens_reported_responses for usage in usages
        ),
    )


def _sum_evaluation_usage(
    usages: Sequence[EvaluationTokenUsage],
    field_name: str,
) -> int | None:
    values = [
        value
        for usage in usages
        for value in [getattr(usage, field_name)]
        if value is not None
    ]
    return sum(values) if values else None


def _token_usage_payload(usage: EvaluationTokenUsage) -> dict[str, Any]:
    return {
        "requestAttempts": usage.request_attempts,
        "terminalResponses": usage.terminal_responses,
        "inputTokens": _token_field_payload(
            usage.input_tokens,
            usage.input_tokens_reported_responses,
            usage.terminal_responses,
        ),
        "outputTokens": _token_field_payload(
            usage.output_tokens,
            usage.output_tokens_reported_responses,
            usage.terminal_responses,
        ),
        "totalTokens": _token_field_payload(
            usage.total_tokens,
            usage.total_tokens_reported_responses,
            usage.terminal_responses,
        ),
        "cachedInputTokens": _token_field_payload(
            usage.cached_input_tokens,
            usage.cached_input_tokens_reported_responses,
            usage.terminal_responses,
        ),
        "cacheWriteInputTokens": _token_field_payload(
            usage.cache_write_input_tokens,
            usage.cache_write_input_tokens_reported_responses,
            usage.terminal_responses,
        ),
        "reasoningTokens": _token_field_payload(
            usage.reasoning_tokens,
            usage.reasoning_tokens_reported_responses,
            usage.terminal_responses,
        ),
    }


def _token_field_payload(
    value: int | None,
    reported_responses: int,
    terminal_responses: int,
) -> dict[str, int | bool | None]:
    return {
        "value": value,
        "reportedResponses": reported_responses,
        "complete": bool(
            terminal_responses and reported_responses == terminal_responses
        ),
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


def _positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


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
        "--repeat",
        type=_positive_integer,
        default=1,
        help="Run every selected case this many times sequentially.",
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
        report = asyncio.run(run_suite(cases, config, repeat=args.repeat))
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
                "code": "evaluation_error",
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
