from collections.abc import Iterator
from sqlite3 import Connection

from app.schemas.agent import AgentChatMessage, AgentChatRequest

from .runtime import build_agent_message, stream_agent_response


class ResumeAgent:
    """Small facade for the resume agent service."""

    def build_message(
        self,
        request: AgentChatRequest,
        conn: Connection,
    ) -> AgentChatMessage:
        return build_agent_message(request, conn)

    def stream_response(
        self,
        request: AgentChatRequest,
        conn: Connection,
    ) -> Iterator[str]:
        yield from stream_agent_response(request, conn)
