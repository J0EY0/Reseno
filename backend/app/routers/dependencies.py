from typing import Annotated

from fastapi import Depends, Request

from app.services.agent_runs import AgentRunManager


async def get_agent_run_manager(request: Request) -> AgentRunManager:
    """Return the application-owned Agent runtime."""

    manager = getattr(request.app.state, "agent_runs", None)
    if not isinstance(manager, AgentRunManager):
        raise RuntimeError("Agent run manager is not initialized.")
    return manager


AgentRunManagerDep = Annotated[AgentRunManager, Depends(get_agent_run_manager)]
