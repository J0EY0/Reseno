from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.schemas.agent import (
    AgentChatRequest,
    AgentResumeEditSuggestion,
    AgentTransactionState,
)
from app.services.resume_document_contract import (
    ResumeDocumentContractError,
    validate_resume_document,
)

from ..editing.operations import (
    _apply_edit_operations,
    _edit_observations,
    _merge_edits,
    parse_edit_batch,
)
from ..evidence import ground_edit_evidence


@dataclass(frozen=True)
class DraftTransaction:
    """Immutable input state for one pending-draft transaction."""

    _active_resume: dict[str, Any]
    _base_resume: dict[str, Any]
    _prior_edits: tuple[AgentResumeEditSuggestion, ...]

    @classmethod
    def from_request(cls, request: AgentChatRequest) -> DraftTransaction:
        """Resolve the active candidate, immutable base, and durable edits once."""

        draft_state = request.draft_state
        has_pending_review = bool(
            draft_state
            and any(item.status == "pending" for item in draft_state.review_items)
        )
        active_resume = (
            draft_state.resume
            if has_pending_review and draft_state and draft_state.resume
            else request.resume
        )
        base_resume = request.resume
        prior_edits: tuple[AgentResumeEditSuggestion, ...] = ()

        response = _pending_transaction_response(request)
        draft = response.get("draft") if response else None
        if isinstance(draft, dict):
            stored_base = draft.get("baseResume")
            if isinstance(stored_base, dict):
                base_resume = stored_base

        pending_edit_ids = _pending_response_edit_ids(response)
        raw_prior_edits = response.get("edits") if response else None
        if isinstance(raw_prior_edits, list):
            prior_edits = tuple(
                AgentResumeEditSuggestion.model_validate(edit)
                for edit in raw_prior_edits
                if isinstance(edit, dict) and edit.get("id") in pending_edit_ids
            )

        return cls(
            _active_resume=deepcopy(active_resume),
            _base_resume=deepcopy(base_resume),
            _prior_edits=deepcopy(prior_edits),
        )

    @property
    def active_resume(self) -> dict[str, Any]:
        return deepcopy(self._active_resume)

    @property
    def base_resume(self) -> dict[str, Any]:
        return deepcopy(self._base_resume)

    @property
    def prior_edits(self) -> tuple[AgentResumeEditSuggestion, ...]:
        return tuple(deepcopy(self._prior_edits))

    def accumulate(
        self,
        edits: list[AgentResumeEditSuggestion] | tuple[AgentResumeEditSuggestion, ...],
    ) -> tuple[AgentResumeEditSuggestion, ...]:
        """Return the durable transaction history plus this turn's edits."""

        if not edits:
            return ()
        return tuple(deepcopy((*self._prior_edits, *edits)))


def _pending_transaction_response(
    request: AgentChatRequest,
) -> dict[str, Any] | None:
    draft_state = request.draft_state
    if not draft_state or not any(
        item.status == "pending" for item in draft_state.review_items
    ):
        return None

    source_message_id = draft_state.source_message_id
    if not source_message_id:
        return None

    for message in reversed(request.messages):
        if message.id != source_message_id or message.role != "assistant":
            continue
        response = message.response
        draft = response.get("draft") if response else None
        if isinstance(draft, dict) and _pending_response_edit_ids(response):
            return response
        return None

    return None


def _pending_response_edit_ids(response: dict[str, Any] | None) -> set[str]:
    """Return edit IDs that remain unresolved in one persisted response."""

    draft = response.get("draft") if response else None
    review_items = draft.get("reviewItems") if isinstance(draft, dict) else None
    if not isinstance(review_items, list):
        return set()
    pending_edit_ids: set[str] = set()
    for item in review_items:
        if not isinstance(item, dict) or item.get("status") != "pending":
            continue
        edit_ids = item.get("editIds")
        if isinstance(edit_ids, list):
            pending_edit_ids.update(
                edit_id for edit_id in edit_ids if isinstance(edit_id, str)
            )
    return pending_edit_ids


@dataclass(frozen=True)
class DraftBatchResult:
    """Immutable outcome of one atomic edit batch."""

    accepted: bool
    observation: dict[str, Any]
    draft_resume: dict[str, Any]
    edits: tuple[AgentResumeEditSuggestion, ...]
    issues: tuple[dict[str, Any], ...]
    revision: int


@dataclass(frozen=True)
class DraftTurnResult:
    """Final pending-draft transaction published at the end of one turn."""

    transaction_state: AgentTransactionState
    base_resume: dict[str, Any]
    draft_resume: dict[str, Any] | None
    edits: tuple[AgentResumeEditSuggestion, ...]
    revision: int


class DraftEditEngine:
    """Own one atomic, user-confirmed resume draft transaction."""

    def __init__(
        self,
        request: AgentChatRequest,
        transaction: DraftTransaction | None = None,
    ) -> None:
        self._request = request
        self._transaction = transaction or DraftTransaction.from_request(request)
        self._active_resume = self._transaction.active_resume
        self._draft_resume = deepcopy(self._active_resume)
        self._edits: list[AgentResumeEditSuggestion] = []
        self._materials: dict[str, str] = {}
        self._revision = 0
        self._retry_pending = False
        self._transaction_failed = False
        self._transaction_committed = False

    @classmethod
    def open(
        cls,
        request: AgentChatRequest,
        transaction: DraftTransaction | None = None,
    ) -> DraftEditEngine:
        """Open a detached transaction for the request's active draft."""

        return cls(request, transaction)

    @property
    def active_resume(self) -> dict[str, Any]:
        return deepcopy(self._active_resume)

    @property
    def base_resume(self) -> dict[str, Any]:
        return self._transaction.base_resume

    @property
    def draft_resume(self) -> dict[str, Any]:
        return deepcopy(self._draft_resume)

    @property
    def edits(self) -> tuple[AgentResumeEditSuggestion, ...]:
        return self._transaction.accumulate(self._edits)

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def transaction_state(self) -> AgentTransactionState:
        return self._transaction_state()

    def add_material(self, reference: str, text: str) -> None:
        """Make one model-observed material passage available to evidence checks."""

        if not text:
            return
        current = self._materials.get(reference)
        if current is None:
            self._materials[reference] = text
        elif text not in current:
            self._materials[reference] = f"{current}\n{text}"

    def execute(self, entries: object) -> DraftBatchResult:
        """Validate and stage one complete edit batch without partial mutation."""

        before_resume = deepcopy(self._draft_resume)
        model_edits, rejected_edits = parse_edit_batch(
            before_resume,
            entries,
            locale=self._request.locale,
        )
        if rejected_edits or not model_edits:
            return self._reject(
                rejected_edits
                or [{"index": 1, "reason": "No executable edit was supplied."}],
            )

        grounded_edits, evidence_issues = ground_edit_evidence(
            before_resume,
            self._request,
            model_edits,
            materials=self._materials,
        )
        candidate_resume = deepcopy(before_resume)
        _apply_edit_operations(candidate_resume, grounded_edits)
        try:
            validate_resume_document(candidate_resume)
        except ResumeDocumentContractError as exc:
            return self._reject(
                [{"index": 1, "reason": f"{exc.code} at {exc.path}."}],
            )

        issues = evidence_issues
        blocking_issues = [
            issue for issue in issues if issue.get("severity") == "error"
        ]
        if blocking_issues:
            return self._reject(
                [
                    {
                        "index": int(issue.get("operationIndex") or 1),
                        "reason": (
                            "Draft invariant check failed: "
                            f"{issue.get('code', 'unknown_draft_issue')}."
                        ),
                        "qualityIssue": issue,
                    }
                    for issue in blocking_issues
                ],
                issues=issues,
            )

        observations, diffs_by_edit = _edit_observations(
            before_resume,
            grounded_edits,
            locale=self._request.locale,
        )
        edits_with_diffs = [
            edit.model_copy(update={"diffs": diffs})
            for edit, diffs in zip(grounded_edits, diffs_by_edit, strict=True)
        ]

        self._draft_resume = candidate_resume
        self._edits = _merge_edits(self._edits, edits_with_diffs)
        self._revision += 1
        self._retry_pending = False
        self._transaction_failed = False
        self._transaction_committed = False
        return DraftBatchResult(
            accepted=True,
            observation={
                "status": "accepted",
                "editCount": len(edits_with_diffs),
                "observations": observations,
                "qualityIssues": issues,
            },
            draft_resume=deepcopy(self._draft_resume),
            edits=tuple(deepcopy(self._edits)),
            issues=tuple(deepcopy(issues)),
            revision=self._revision,
        )

    def finalize(self, completed: bool) -> DraftTurnResult:
        """Publish accepted edits on completion or roll back an unfinished turn."""

        if not completed and (self._edits or self._retry_pending):
            self._draft_resume = deepcopy(self._active_resume)
            self._edits = []
            self._transaction_failed = True
            self._transaction_committed = False
        elif self._edits:
            self._retry_pending = False
            self._transaction_committed = True
        elif self._retry_pending:
            self._transaction_failed = True
            self._transaction_committed = False

        state = self._transaction_state()
        return DraftTurnResult(
            transaction_state=state,
            base_resume=self._transaction.base_resume,
            draft_resume=(
                deepcopy(self._draft_resume) if state == "committed" else None
            ),
            edits=self._transaction.accumulate(self._edits),
            revision=self._revision,
        )

    def _reject(
        self,
        rejected_edits: list[dict[str, Any]],
        *,
        issues: list[dict[str, Any]] | None = None,
    ) -> DraftBatchResult:
        self._retry_pending = True
        self._transaction_failed = False
        self._transaction_committed = False
        return DraftBatchResult(
            accepted=False,
            observation={
                "status": "rejected",
                "editCount": 0,
                "rejectedEditCount": len(rejected_edits),
                "rejectedEdits": deepcopy(rejected_edits),
                "retryable": True,
            },
            draft_resume=deepcopy(self._draft_resume),
            edits=tuple(deepcopy(self._edits)),
            issues=tuple(deepcopy(issues or [])),
            revision=self._revision,
        )

    def _transaction_state(self) -> AgentTransactionState:
        if self._transaction_failed:
            return "rolled_back"
        if self._transaction_committed:
            return "committed"
        if self._edits:
            return "provisional"
        return "none"


__all__ = [
    "DraftBatchResult",
    "DraftEditEngine",
    "DraftTransaction",
    "DraftTurnResult",
]
