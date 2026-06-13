from collections.abc import AsyncIterator
from sqlite3 import Connection

from app.schemas.agent import AgentChatMessage, AgentChatRequest

from .runtime import async_build_agent_message, async_stream_agent_response


class ResumeAgent:
    """Small facade for the resume agent service."""

    async def build_message(
        self,
        request: AgentChatRequest,
        conn: Connection,
    ) -> AgentChatMessage:
        return await async_build_agent_message(request, conn)

    async def stream_response(
        self,
        request: AgentChatRequest,
        conn: Connection,
    ) -> AsyncIterator[str]:
        async for chunk in async_stream_agent_response(request, conn):
            yield chunk
