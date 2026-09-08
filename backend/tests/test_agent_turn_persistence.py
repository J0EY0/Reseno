import json
from contextlib import closing
from datetime import UTC, datetime
from functools import partial
from sqlite3 import IntegrityError

import anyio
import pytest

from app.config import get_settings
from app.db.connection import connect
from app.db.schema import ensure_database_schema
from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentCommittedDraft,
    AgentConversationCheckpoint,
    AgentConversationItem,
)
from app.services.agent.runtime.compaction import prepare_agent_prompt
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.runtime.messages import (
    AgentPromptCompiler,
    agent_prompt_limits,
    estimate_agent_messages_tokens,
)
from app.services.agent_sessions import (
    AgentSessionPersistenceError,
    AgentTerminalOutcome,
    accept_agent_turn,
    load_agent_session,
    persist_agent_terminal_outcome,
)
from app.services.llm import AgentLlmConfig
from tests.agent_context import with_message_budget


@pytest.fixture
def agent_database(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("APP_STORAGE_DIR", str(tmp_path / "storage"))
    monkeypatch.setenv("APP_ENV_FILE", str(tmp_path / ".env"))
    get_settings.cache_clear()
    ensure_database_schema()
    try:
        yield
    finally:
        get_settings.cache_clear()


def _request(
    conn,
    *,
    resume_id: str,
    turn_id: str,
    text: str,
    history: list[AgentConversationItem] | None = None,
) -> AgentChatRequest:
    conn.execute(
        """
        INSERT OR IGNORE INTO resumes (id, title, saved_at)
        VALUES (?, 'Agent turn persistence test', ?)
        """,
        (resume_id, datetime.now(UTC).isoformat()),
    )
    return AgentChatRequest(
        resumeId=resume_id,
        expectedRevision=load_agent_session(conn, resume_id).revision,
        message=AgentConversationItem(id=turn_id, role="user", text=text),
        messages=history or [],
        resume={"basic": {}, "sections": []},
    )


def _assistant(message_id: str, *, draft: bool = False) -> AgentChatMessage:
    edit_id = f"edit-{message_id}"
    return AgentChatMessage(
        id=message_id,
        role="assistant",
        text="The requested change is ready.",
        edits=(
            [
                {
                    "id": edit_id,
                    "title": "Update summary",
                    "target": "basic.summary",
                    "reason": "Exercise durable draft persistence.",
                    "operation": {
                        "type": "replace_field",
                        "path": "basic.summary",
                        "value": "Updated summary",
                    },
                    "status": "executed",
                }
            ]
            if draft
            else []
        ),
        draft=(
            AgentCommittedDraft(
                baseResume={"basic": {}, "sections": []},
                reviewItems=[
                    {
                        "id": f"agent-review-{message_id}",
                        "editIds": [edit_id],
                        "status": "pending",
                    },
                ],
            )
            if draft
            else None
        ),
        transactionState="committed" if draft else "none",
    )


def _checkpoint_summary(text: str) -> dict[str, object]:
    return {
        "trust": "untrusted_history_data",
        "events": [{"role": "assistant", "text": text}],
    }


def _context_config() -> AgentLlmConfig:
    return AgentLlmConfig(
        client_id="checkpoint-persistence-model",
        name="Checkpoint persistence model",
        provider="openai",
        provider_kind="cloud",
        api_family="openai_responses",
        model="gpt-test",
        base_url="https://api.openai.com/v1",
        api_key="sk-test",
        temperature=0.2,
        top_p=0.9,
        max_tokens=512,
        timeout_seconds=30,
        context_window_tokens=6_000,
        supports_streaming=False,
    )


def test_accept_agent_turn_returns_explicit_authoritative_state(
    agent_database,
) -> None:
    del agent_database
    resume_id = "AcceptedTurnResume"

    with closing(connect()) as conn:
        accepted = accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-1",
                text="Use the durable transcript.",
                history=[
                    AgentConversationItem(
                        id="forged-message",
                        role="assistant",
                        text="Client supplied history",
                    ),
                ],
            ),
            run_id="run-1",
            resolved_config=None,
        )

    assert accepted.run_id == "run-1"
    assert accepted.session_id == resume_id
    assert accepted.turn_id == "turn-1"
    assert accepted.revision is not None
    assert accepted.request.messages == []
    assert accepted.request.message.id == "turn-1"
    assert accepted.conversation_state.loaded_checkpoint is None
    assert accepted.conversation_state.active_checkpoint is None


def test_execution_persists_only_the_resolved_model_identity(
    agent_database,
) -> None:
    del agent_database
    resume_id = "ModelSnapshotResume"
    config = _context_config()

    with closing(connect()) as conn:
        accepted = accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-model-snapshot",
                text="Attribute this run to the resolved model.",
            ),
            run_id="run-model-snapshot",
            resolved_config=config,
        )
        session = load_agent_session(conn, resume_id)
        stored_columns = conn.execute(
            """
            SELECT model_config_id, model_provider, model_id
            FROM agent_turn_executions
            WHERE run_id = 'run-model-snapshot'
            """
        ).fetchone()

    expected = {
        "configId": config.client_id,
        "provider": config.provider,
        "model": config.model,
    }
    assert accepted.model_snapshot is not None
    assert accepted.model_snapshot.model_dump(mode="json", by_alias=True) == expected
    assert session.executions[0].model_snapshot is not None
    assert (
        session.executions[0].model_snapshot.model_dump(
            mode="json",
            by_alias=True,
        )
        == expected
    )
    assert dict(stored_columns) == {
        "model_config_id": config.client_id,
        "model_provider": config.provider,
        "model_id": config.model,
    }
    serialized = session.model_dump_json(by_alias=True)
    assert config.api_key not in serialized
    assert config.base_url not in serialized
    assert config.api_key not in repr(config)


def test_execution_rejects_a_partial_model_identity(agent_database) -> None:
    del agent_database
    resume_id = "PartialModelSnapshotResume"

    with closing(connect()) as conn:
        accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-partial-model-snapshot",
                text="Reject a model identity that cannot be attributed.",
            ),
            run_id="run-partial-model-snapshot",
            resolved_config=None,
        )
        with pytest.raises(IntegrityError):
            conn.execute(
                """
                UPDATE agent_turn_executions
                SET
                    model_config_id = ?,
                    model_provider = NULL,
                    model_id = ?
                WHERE run_id = ?
                """,
                (
                    "config-with-missing-provider",
                    "gpt-test",
                    "run-partial-model-snapshot",
                ),
            )


def test_terminal_outcome_atomically_persists_changed_checkpoint_and_new_draft(
    agent_database,
) -> None:
    del agent_database
    resume_id = "TerminalOutcomeResume"
    checkpoint = AgentConversationCheckpoint(
        throughMessageId="turn-2",
        summary=_checkpoint_summary("Keep claims grounded in supplied evidence."),
    )
    original = _assistant("assistant-1", draft=True).model_dump(by_alias=True)
    for status in ("applied", "discarded"):
        edit_id = f"edit-{status}"
        original["edits"].append({**original["edits"][0], "id": edit_id})
        original["draft"]["reviewItems"].append(
            {"id": f"review-{status}", "editIds": [edit_id], "status": status},
        )

    with closing(connect()) as conn:
        first = accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-1",
                text="Prepare the first draft.",
            ),
            run_id="run-1",
            resolved_config=None,
        )
        persist_agent_terminal_outcome(
            conn,
            first,
            AgentTerminalOutcome(
                status="succeeded",
                error_code=None,
                assistant=AgentChatMessage.model_validate(original),
                checkpoint=first.conversation_state.active_checkpoint,
            ),
        )

        second = accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-2",
                text="Prepare a replacement draft.",
            ),
            run_id="run-2",
            resolved_config=None,
        )
        second.conversation_state.active_checkpoint = checkpoint
        persist_agent_terminal_outcome(
            conn,
            second,
            AgentTerminalOutcome(
                status="succeeded",
                error_code=None,
                assistant=_assistant("assistant-2", draft=True),
                checkpoint=second.conversation_state.active_checkpoint,
            ),
        )

        session = load_agent_session(conn, resume_id)
        stored_payload = conn.execute(
            "SELECT response_json FROM agent_messages WHERE id = 'assistant-2'"
        ).fetchone()["response_json"]

    assert session.messages[1].response is not None
    assert session.messages[1].response.draft is not None
    assert [
        item.status for item in session.messages[1].response.draft.review_items
    ] == ["superseded", "applied", "discarded"]
    assert session.messages[1].response.draft.base_resume == (
        original["draft"]["baseResume"]
    )
    assert session.messages[-1].response is not None
    assert session.messages[-1].response.draft is not None
    assert session.messages[-1].response.draft.review_items[0].status == "pending"
    execution_states = [
        (execution.run_id, execution.status) for execution in session.executions
    ]
    assert execution_states == [
        ("run-1", "succeeded"),
        ("run-2", "succeeded"),
    ]
    assert json.loads(stored_payload)["_conversationCheckpoint"] == (
        checkpoint.model_dump(mode="json", by_alias=True)
    )


def test_rollover_checkpoint_is_restored_without_hiding_visible_history(
    agent_database,
) -> None:
    del agent_database
    resume_id = "RolloverPersistenceResume"
    config = _context_config()

    with closing(connect()) as conn:
        first = accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-1",
                text="Verified project fact. " + ("detail " * 1_000),
            ),
            run_id="run-1",
            resolved_config=None,
        )
        persist_agent_terminal_outcome(
            conn,
            first,
            AgentTerminalOutcome(
                status="succeeded",
                error_code=None,
                assistant=_assistant("assistant-1"),
                checkpoint=None,
            ),
        )

        second = accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-2",
                text="Continue with the current resume.",
            ),
            run_id="run-2",
            resolved_config=None,
        )
        config = with_message_budget(second.request, config, input_tokens=2_500)
        limits = agent_prompt_limits(second.request, config)
        assert limits is not None
        exact = AgentPromptCompiler(second.request, config).build()
        assert estimate_agent_messages_tokens(exact.messages) > limits.trigger_tokens
        second_prompt = anyio.run(
            partial(
                prepare_agent_prompt,
                second.request,
                config,
                AgentRuntimeContext(
                    conversation_state=second.conversation_state,
                ),
            ),
        )
        checkpoint = second.conversation_state.active_checkpoint
        assert checkpoint is not None
        assert checkpoint.through_message_id == "assistant-1"
        assert (
            estimate_agent_messages_tokens(second_prompt.messages)
            <= limits.input_tokens
        )

        persist_agent_terminal_outcome(
            conn,
            second,
            AgentTerminalOutcome(
                status="succeeded",
                error_code=None,
                assistant=_assistant("assistant-2"),
                checkpoint=checkpoint,
            ),
        )

        third = accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-3",
                text="Use the previous decisions.",
            ),
            run_id="run-3",
            resolved_config=None,
        )
        restored_prompt = anyio.run(
            partial(
                prepare_agent_prompt,
                third.request,
                config,
                AgentRuntimeContext(
                    conversation_state=third.conversation_state,
                ),
            ),
        )
        session = load_agent_session(conn, resume_id)

    assert third.conversation_state.loaded_checkpoint == checkpoint
    assert third.conversation_state.active_checkpoint == checkpoint
    assert "conversationCheckpoint" in json.dumps(restored_prompt.messages)
    assert restored_prompt.messages[-1] == {
        "role": "user",
        "content": "Use the previous decisions.",
    }
    assert [message.id for message in session.messages] == [
        "turn-1",
        "assistant-1",
        "turn-2",
        "assistant-2",
        "turn-3",
    ]


def test_terminal_outcome_cas_failure_rolls_back_assistant_and_checkpoint(
    agent_database,
) -> None:
    del agent_database
    resume_id = "TerminalRollbackResume"
    checkpoint = AgentConversationCheckpoint(
        throughMessageId="turn-1",
        summary=_checkpoint_summary(
            "This checkpoint must roll back with the assistant.",
        ),
    )

    with closing(connect()) as conn:
        accepted = accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-1",
                text="Persist this only if the run still owns the turn.",
            ),
            run_id="run-1",
            resolved_config=None,
        )
        accepted.conversation_state.active_checkpoint = checkpoint
        conn.execute(
            "UPDATE agent_turn_executions SET status = 'failed' WHERE run_id = 'run-1'"
        )

        with pytest.raises(AgentSessionPersistenceError):
            persist_agent_terminal_outcome(
                conn,
                accepted,
                AgentTerminalOutcome(
                    status="succeeded",
                    error_code=None,
                    assistant=_assistant("assistant-1"),
                    checkpoint=accepted.conversation_state.active_checkpoint,
                ),
            )

        session = load_agent_session(conn, resume_id)
        assistant_count = conn.execute(
            "SELECT COUNT(*) AS count FROM agent_messages WHERE role = 'assistant'"
        ).fetchone()["count"]

    assert assistant_count == 0
    assert [message.id for message in session.messages] == ["turn-1"]
    execution_states = [
        (execution.run_id, execution.status) for execution in session.executions
    ]
    assert execution_states == [("run-1", "failed")]


def test_unchanged_checkpoint_is_not_duplicated_on_terminal_message(
    agent_database,
) -> None:
    del agent_database
    resume_id = "UnchangedCheckpointResume"
    checkpoint = AgentConversationCheckpoint(
        throughMessageId="turn-1",
        summary=_checkpoint_summary("Persist this checkpoint once."),
    )

    with closing(connect()) as conn:
        first = accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-1",
                text="Create the checkpoint.",
            ),
            run_id="run-1",
            resolved_config=None,
        )
        first.conversation_state.active_checkpoint = checkpoint
        persist_agent_terminal_outcome(
            conn,
            first,
            AgentTerminalOutcome(
                status="succeeded",
                error_code=None,
                assistant=_assistant("assistant-1"),
                checkpoint=first.conversation_state.active_checkpoint,
            ),
        )
        second = accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-2",
                text="Continue without changing the checkpoint.",
            ),
            run_id="run-2",
            resolved_config=None,
        )
        persist_agent_terminal_outcome(
            conn,
            second,
            AgentTerminalOutcome(
                status="succeeded",
                error_code=None,
                assistant=_assistant("assistant-2"),
                checkpoint=second.conversation_state.active_checkpoint,
            ),
        )
        response_json = conn.execute(
            "SELECT response_json FROM agent_messages WHERE id = 'assistant-2'"
        ).fetchone()["response_json"]

    assert second.conversation_state.loaded_checkpoint == checkpoint
    assert second.conversation_state.active_checkpoint == checkpoint
    assert "_conversationCheckpoint" not in json.loads(response_json)


@pytest.mark.parametrize(
    ("status", "error_code", "assistant_id"),
    [
        ("failed", "AGENT_INTERNAL_ERROR", None),
        ("cancelled", "AGENT_RUN_CANCELLED", "assistant-cancelled"),
    ],
)
def test_non_success_terminal_outcome_uses_the_same_atomic_seam(
    agent_database,
    status,
    error_code,
    assistant_id,
) -> None:
    del agent_database
    resume_id = f"Terminal{status.title()}Resume"

    with closing(connect()) as conn:
        accepted = accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-1",
                text="Finish this accepted turn.",
            ),
            run_id="run-1",
            resolved_config=None,
        )
        assistant = _assistant(assistant_id) if assistant_id is not None else None
        persist_agent_terminal_outcome(
            conn,
            accepted,
            AgentTerminalOutcome(
                status=status,
                error_code=error_code,
                assistant=assistant,
                checkpoint=accepted.conversation_state.active_checkpoint,
            ),
        )
        session = load_agent_session(conn, resume_id)

    assert session.executions[0].status == status
    assert session.executions[0].error_code == error_code
    assert [message.id for message in session.messages] == [
        "turn-1",
        *([assistant_id] if assistant_id is not None else []),
    ]


@pytest.mark.parametrize(
    ("status", "error_code", "assistant_id"),
    [
        ("failed", "AGENT_INTERNAL_ERROR", None),
        ("cancelled", "AGENT_RUN_CANCELLED", "assistant-cancelled"),
        ("succeeded", None, "assistant-no-edits"),
    ],
)
def test_terminal_without_new_draft_preserves_previous_pending_draft(
    agent_database,
    status,
    error_code,
    assistant_id,
) -> None:
    del agent_database
    resume_id = f"PreservedDraft{status.title()}Resume"
    original = _assistant("assistant-pending", draft=True)

    with closing(connect()) as conn:
        first = accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-pending",
                text="Prepare the first draft.",
            ),
            run_id="run-pending",
            resolved_config=None,
        )
        persist_agent_terminal_outcome(
            conn,
            first,
            AgentTerminalOutcome(
                status="succeeded",
                error_code=None,
                assistant=original,
                checkpoint=None,
            ),
        )
        second = accept_agent_turn(
            conn,
            _request(
                conn,
                resume_id=resume_id,
                turn_id="turn-follow-up",
                text="Continue reviewing the draft.",
            ),
            run_id="run-follow-up",
            resolved_config=None,
        )
        persist_agent_terminal_outcome(
            conn,
            second,
            AgentTerminalOutcome(
                status=status,
                error_code=error_code,
                assistant=_assistant(assistant_id) if assistant_id else None,
                checkpoint=None,
            ),
        )
        session = load_agent_session(conn, resume_id)

    assert session.messages[1].response == original
    assert session.executions[-1].status == status
