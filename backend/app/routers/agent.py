from collections.abc import Iterator
from contextlib import closing

from fastapi import APIRouter, Header, HTTPException, status
from fastapi.responses import StreamingResponse

from app.db.connection import connect
from app.schemas.agent import (
    AgentChatRequest,
    AgentChatResponse,
    AgentSessionResponse,
)
from app.schemas.common import APP_MESSAGE_BAD_REQUEST, ApiResponse, ok_response
from app.services.agent import build_agent_message, stream_agent_response
from app.services.agent_sessions import (
    append_agent_exchange,
    is_valid_resume_id,
    load_agent_session,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])


@router.get(
    "/resumes/{resume_id}/session",
    response_model=ApiResponse[AgentSessionResponse],
)
def get_agent_resume_session(resume_id: str) -> ApiResponse[AgentSessionResponse]:
    """Return persisted Agent messages attached to one resume."""

    if not is_valid_resume_id(resume_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_BAD_REQUEST,
        )

    with closing(connect()) as conn:
        session = load_agent_session(conn, resume_id)

    return ok_response(session)


@router.post("/chat", response_model=ApiResponse[AgentChatResponse])
def post_agent_chat(
    request: AgentChatRequest,
    accept: str | None = Header(default=None),
) -> ApiResponse[AgentChatResponse] | StreamingResponse:
    """Return an agent response as JSON or server-sent events."""

    if request.resume_id and not is_valid_resume_id(request.resume_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=APP_MESSAGE_BAD_REQUEST,
        )

    if request.stream and accept and "text/event-stream" in accept.lower():
        def event_stream() -> Iterator[str]:
            """Open DB resources for the lifetime of the streaming response."""

            with closing(connect()) as conn:
                yield from stream_agent_response(
                    request,
                    conn,
                    lambda message: append_agent_exchange(conn, request, message),
                )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
        )

    with closing(connect()) as conn:
        message = build_agent_message(request, conn)
        append_agent_exchange(conn, request, message)

    return ok_response(AgentChatResponse(message=message))
