from collections.abc import AsyncIterator
from contextlib import closing

import anyio
from fastapi import APIRouter, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from app.db.connection import connect
from app.schemas.agent import (
    AgentChatMessage,
    AgentChatRequest,
    AgentChatResponse,
    AgentSessionResponse,
)
from app.schemas.common import APP_MESSAGE_BAD_REQUEST, ApiResponse, ok_response
from app.services.agent import build_agent_message
from app.services.agent.runtime.context import AgentRuntimeContext
from app.services.agent.runtime.streaming import async_stream_agent_response
from app.services.agent_sessions import (
    append_agent_exchange,
    is_valid_resume_id,
    load_agent_session,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])
DISCONNECT_POLL_SECONDS = 0.25


def _build_and_store_message(request: AgentChatRequest) -> AgentChatMessage:
    """Build and persist one non-streaming assistant message."""

    with closing(connect()) as conn:
        message = build_agent_message(request, conn)
        append_agent_exchange(conn, request, message)

    return message


async def _close_async_iterator(iterator: AsyncIterator[str]) -> None:
    """Close an async generator-like iterator when the client aborts the stream."""

    close = getattr(iterator, "aclose", None)
    if callable(close):
        await close()


async def _cancel_on_disconnect(
    request: Request,
    cancel_scope: anyio.CancelScope,
) -> None:
    """Cancel the active streaming task as soon as the client disconnects."""

    while True:
        if await request.is_disconnected():
            cancel_scope.cancel()
            return

        await anyio.sleep(DISCONNECT_POLL_SECONDS)


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
async def post_agent_chat(
    http_request: Request,
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
        async def event_stream() -> AsyncIterator[str]:
            """Open DB resources for the lifetime of the streaming response."""

            runtime = AgentRuntimeContext(is_aborted=http_request.is_disconnected)
            async with anyio.create_task_group() as task_group:
                with anyio.CancelScope() as stream_scope:
                    task_group.start_soon(
                        _cancel_on_disconnect,
                        http_request,
                        stream_scope,
                    )
                    with closing(connect()) as conn:
                        iterator = async_stream_agent_response(
                            request,
                            conn,
                            lambda message: append_agent_exchange(
                                conn,
                                request,
                                message,
                            ),
                            runtime,
                        )
                        try:
                            async for chunk in iterator:
                                yield chunk
                        finally:
                            task_group.cancel_scope.cancel()
                            with anyio.CancelScope(shield=True):
                                await _close_async_iterator(iterator)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
        )

    message = await anyio.to_thread.run_sync(_build_and_store_message, request)

    return ok_response(AgentChatResponse(message=message))
