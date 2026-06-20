from collections.abc import AsyncIterator
from sqlite3 import Connection

from app.schemas.agent import AgentChatRequest

from .runtime import async_stream_agent_response


class ResumeAgent:
    """Small facade for the resume agent service."""

    async def stream_response(
        self,
        request: AgentChatRequest,
        conn: Connection,
    ) -> AsyncIterator[str]:
        async for chunk in async_stream_agent_response(request, conn):
            yield chunk
