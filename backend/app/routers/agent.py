from contextlib import closing
from functools import partial
from typing import Annotated

import anyio
from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from app.db.connection import connect
from app.exceptions import http_error_response
from app.routers.dependencies import AgentRunManagerDep
from app.routers.upload_route import LimitedUploadRoute
from app.schemas.agent import (
    AgentAttachmentResponse,
    AgentChatRequest,
    AgentDraftDecisionRequest,
    AgentDraftDecisionResponse,
    AgentRunResponse,
    AgentSessionRecoveryResponse,
    AgentSessionReplaceRequest,
    AgentSessionResponse,
)
from app.schemas.common import APP_MESSAGE_BAD_REQUEST, ApiResponse, ok_response
from app.schemas.resumes import ResumeDetailResponse, is_valid_resume_id
from app.services.agent.attachments import (
    MAX_AGENT_ATTACHMENT_BYTES,
    AgentAttachmentError,
    cleanup_expired_pending_attachments,
    delete_pending_agent_attachment,
    load_agent_attachment,
    store_resume_agent_attachment,
)
from app.services.agent.preferences import prepare_agent_request
from app.services.agent.resume_owner import (
    AgentResumeUnavailableError,
)
from app.services.agent_runs import (
    AgentRunCapacityError,
    AgentRunConflictError,
    AgentRunNotFoundError,
)
from app.services.agent_sessions import (
    AgentDraftDecisionConflictError,
    AgentDraftUnavailableConflictError,
    AgentResumeVersionConflictError,
    AgentSessionActiveRunConflictError,
    AgentSessionDataError,
    AgentSessionReplacementError,
    AgentSessionRevisionConflictError,
    AgentSessionTurnReplayError,
    apply_agent_draft_decision,
    load_agent_session,
    replace_agent_session_messages,
    update_agent_draft_decision,
)
from app.services.llm import LlmThinkingModeUnsupportedError
from app.services.user_preferences import load_agent_settings

router = APIRouter(prefix="/api/agent", tags=["agent"], route_class=LimitedUploadRoute)


def _agent_transport_error(
    status_code: int,
    code: str,
    **details: str,
) -> JSONResponse:
    """Return an Agent HTTP failure with its conflict or recovery metadata."""

    return http_error_response(
        status_code=status_code,
        message=code,
        data=details or None,
    )


def _agent_session_data_error() -> JSONResponse:
    """Hide corrupt stored message identifiers and contents from clients."""

    return _agent_transport_error(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "AGENT_SESSION_DATA_INVALID",
    )


@router.post(
    "/attachments",
    response_model=ApiResponse[AgentAttachmentResponse],
)
async def post_agent_attachment(
    background_tasks: BackgroundTasks,
    resume_id: Annotated[str, Form(alias="resumeId")],
    file: Annotated[UploadFile, File()],
) -> ApiResponse[AgentAttachmentResponse]:
    """Persist one original file inside the owning Agent session."""

    if not is_valid_resume_id(resume_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_BAD_REQUEST,
        )

    try:
        payload = await file.read(MAX_AGENT_ATTACHMENT_BYTES + 1)
        attachment = await anyio.to_thread.run_sync(
            partial(
                store_resume_agent_attachment,
                resume_id=resume_id,
                filename=file.filename or "attachment",
                media_type=file.content_type or "",
                payload=payload,
            ),
        )
    except AgentResumeUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except AgentAttachmentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_BAD_REQUEST,
        ) from exc
    finally:
        await file.close()

    # Cleanup is opportunistic and never delays the upload response.
    background_tasks.add_task(cleanup_expired_pending_attachments)
    return ok_response(attachment)


@router.get(
    "/resumes/{resume_id}/session",
    response_model=ApiResponse[AgentSessionResponse],
)
def get_agent_resume_session(
    resume_id: str,
    background_tasks: BackgroundTasks,
) -> ApiResponse[AgentSessionResponse] | JSONResponse:
    """Return persisted Agent messages attached to one resume."""

    if not is_valid_resume_id(resume_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_BAD_REQUEST,
        )

    try:
        with closing(connect()) as conn:
            session = load_agent_session(conn, resume_id)
    except AgentSessionDataError:
        return _agent_session_data_error()

    # Session entry is a convenient non-blocking maintenance point for uploads
    # abandoned before the user sends a message.
    background_tasks.add_task(cleanup_expired_pending_attachments)
    return ok_response(session)


@router.get("/resumes/{resume_id}/attachments/{attachment_id}")
def get_agent_attachment(
    resume_id: str,
    attachment_id: str,
) -> FileResponse:
    """Download a persisted original attachment from one Agent session."""

    if not is_valid_resume_id(resume_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    attachment = load_agent_attachment(resume_id, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    return FileResponse(
        attachment.path,
        media_type=attachment.media_type or "application/octet-stream",
        filename=attachment.filename,
    )


@router.delete(
    "/resumes/{resume_id}/attachments/{attachment_id}",
    response_model=ApiResponse[dict[str, str]],
)
def delete_agent_attachment(
    resume_id: str,
    attachment_id: str,
) -> ApiResponse[dict[str, str]]:
    """Delete an unsent upload without allowing chat history data loss."""

    if not is_valid_resume_id(resume_id) or not delete_pending_agent_attachment(
        resume_id,
        attachment_id,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return ok_response({"id": attachment_id})


@router.put(
    "/resumes/{resume_id}/session",
    response_model=ApiResponse[AgentSessionResponse],
)
def put_agent_resume_session(
    resume_id: str,
    request: AgentSessionReplaceRequest,
) -> ApiResponse[AgentSessionResponse] | JSONResponse:
    """Replace persisted Agent messages attached to one resume."""

    if not is_valid_resume_id(resume_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_BAD_REQUEST,
        )

    try:
        with closing(connect()) as conn:
            session = replace_agent_session_messages(
                conn,
                resume_id,
                locale=request.locale,
                messages=request.messages,
                revision=request.revision,
            )
    except AgentResumeUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except AgentSessionRevisionConflictError as exc:
        return _agent_transport_error(
            status.HTTP_409_CONFLICT,
            "AGENT_SESSION_REVISION_CONFLICT",
            revision=exc.current_revision,
        )
    except AgentSessionTurnReplayError as exc:
        return _agent_transport_error(
            status.HTTP_409_CONFLICT,
            "AGENT_SESSION_TURN_CONFLICT",
            revision=exc.current_revision,
        )
    except AgentSessionActiveRunConflictError as exc:
        return _agent_transport_error(
            status.HTTP_409_CONFLICT,
            "AGENT_RUN_CONFLICT",
            revision=exc.current_revision,
            runId=exc.run_id,
        )
    except AgentSessionDataError:
        return _agent_session_data_error()
    except AgentSessionReplacementError:
        return _agent_transport_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "AGENT_SESSION_REPLACEMENT_INVALID",
        )

    return ok_response(session)


@router.patch(
    "/resumes/{resume_id}/session/messages/{message_id}/draft",
    response_model=ApiResponse[AgentDraftDecisionResponse],
)
def patch_agent_resume_draft(
    resume_id: str,
    message_id: str,
    request: AgentDraftDecisionRequest,
) -> ApiResponse[AgentDraftDecisionResponse] | JSONResponse:
    """Durably resolve selected review items from one committed draft."""

    if not is_valid_resume_id(resume_id) or not message_id.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_BAD_REQUEST,
        )

    try:
        with closing(connect()) as conn:
            if request.status == "applied":
                if request.resume is None or request.expected_version_id is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=APP_MESSAGE_BAD_REQUEST,
                    )
                session, saved_resume = apply_agent_draft_decision(
                    conn,
                    resume_id,
                    message_id=message_id,
                    review_item_ids=request.review_item_ids,
                    resume=request.resume,
                    revision=request.revision,
                    expected_version_id=request.expected_version_id,
                )
            else:
                session = update_agent_draft_decision(
                    conn,
                    resume_id,
                    message_id=message_id,
                    review_item_ids=request.review_item_ids,
                    status=request.status,
                    revision=request.revision,
                )
                saved_resume = None
    except AgentResumeUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except AgentSessionRevisionConflictError as exc:
        return _agent_transport_error(
            status.HTTP_409_CONFLICT,
            "AGENT_SESSION_REVISION_CONFLICT",
            revision=exc.current_revision,
        )
    except AgentResumeVersionConflictError as exc:
        return _agent_transport_error(
            status.HTTP_409_CONFLICT,
            "RESUME_VERSION_CONFLICT",
            versionId=exc.current_version_id,
        )
    except AgentSessionActiveRunConflictError as exc:
        return _agent_transport_error(
            status.HTTP_409_CONFLICT,
            "AGENT_RUN_CONFLICT",
            revision=exc.current_revision,
            runId=exc.run_id,
        )
    except AgentDraftDecisionConflictError as exc:
        return _agent_transport_error(
            status.HTTP_409_CONFLICT,
            "AGENT_DRAFT_DECISION_CONFLICT",
            revision=exc.current_revision,
            status=exc.current_status,
        )
    except AgentDraftUnavailableConflictError as exc:
        return _agent_transport_error(
            status.HTTP_409_CONFLICT,
            "AGENT_DRAFT_DECISION_CONFLICT",
            revision=exc.current_revision,
        )
    except AgentSessionDataError:
        return _agent_session_data_error()
    return ok_response(
        AgentDraftDecisionResponse(
            session=session,
            resume=(
                ResumeDetailResponse.model_validate(saved_resume)
                if saved_resume is not None
                else None
            ),
        )
    )


@router.post("/chat")
async def post_agent_chat(
    request: AgentChatRequest,
    manager: AgentRunManagerDep,
) -> Response:
    """Start one background Agent run and subscribe to its event stream."""

    # Freeze persisted preferences before handing the request to the background
    # run. A settings change during this run takes effect on the next turn.
    prepared_request = prepare_agent_request(request, load_agent_settings())
    try:
        run = await manager.start(prepared_request)
    except AgentResumeUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    except AgentSessionRevisionConflictError as exc:
        return _agent_transport_error(
            status.HTTP_409_CONFLICT,
            "AGENT_SESSION_REVISION_CONFLICT",
            revision=exc.current_revision,
        )
    except AgentSessionTurnReplayError as exc:
        return _agent_transport_error(
            status.HTTP_409_CONFLICT,
            "AGENT_SESSION_TURN_CONFLICT",
            revision=exc.current_revision,
        )
    except AgentRunCapacityError:
        return _agent_transport_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "AGENT_RUN_CAPACITY_EXCEEDED",
        )
    except AgentRunConflictError:
        return _agent_transport_error(
            status.HTTP_409_CONFLICT,
            "AGENT_RUN_CONFLICT",
        )
    except AgentAttachmentError:
        return _agent_transport_error(
            status.HTTP_400_BAD_REQUEST,
            "AGENT_ATTACHMENT_INVALID",
        )
    except LlmThinkingModeUnsupportedError:
        return _agent_transport_error(
            status.HTTP_400_BAD_REQUEST,
            "MODEL_CONFIG_THINKING_MODE_UNSUPPORTED",
        )
    except AgentSessionDataError:
        return _agent_session_data_error()

    return StreamingResponse(
        manager.subscribe(run.id),
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Agent-Run-Id": run.id,
        },
        media_type="text/event-stream",
    )


@router.get(
    "/resumes/{resume_id}/recovery",
    response_model=ApiResponse[AgentSessionRecoveryResponse],
)
async def get_agent_session_recovery(
    resume_id: str,
    manager: AgentRunManagerDep,
) -> ApiResponse[AgentSessionRecoveryResponse] | JSONResponse:
    """Restore durable history and its matching reconnectable run together."""

    if not is_valid_resume_id(resume_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_BAD_REQUEST,
        )
    try:
        recovery = await manager.recover_session(resume_id)
    except AgentRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE) from exc
    except AgentSessionDataError:
        return _agent_session_data_error()
    return ok_response(recovery)


@router.get("/runs/{run_id}/events")
async def get_agent_run_events(
    run_id: str,
    manager: AgentRunManagerDep,
    after: Annotated[int, Query(ge=0)] = 0,
) -> StreamingResponse:
    """Replay buffered events and continue following an in-process run."""

    try:
        await manager.get(run_id)
    except AgentRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    return StreamingResponse(
        manager.subscribe(run_id, after=after),
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Agent-Run-Id": run_id,
        },
        media_type="text/event-stream",
    )


@router.delete(
    "/runs/{run_id}",
    response_model=ApiResponse[AgentRunResponse],
)
async def delete_agent_run(
    run_id: str,
    manager: AgentRunManagerDep,
) -> ApiResponse[AgentRunResponse]:
    """Explicitly stop a run; subscriber disconnects never call this route."""

    try:
        run = await manager.stop(run_id)
    except AgentRunNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc
    return ok_response(run.response())
