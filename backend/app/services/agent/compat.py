def get_agent_api():
    """Return the package root so tests can monkeypatch legacy import paths."""

    import app.services.agent as agent_api

    return agent_api
