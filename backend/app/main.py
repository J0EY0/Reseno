import hashlib
import hmac
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, closing
from typing import cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.exceptions import HTTPException

from app.config import JWT_SECRET_ENV_NAME, get_settings
from app.db.connection import connect
from app.db.schema import ensure_database_schema
from app.exceptions import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.middleware.auth import jwt_auth_middleware
from app.middleware.oauth_session import OAuthSessionMiddleware
from app.routers import (
    agent,
    auth,
    auth_oauth,
    exports,
    health,
    imports,
    model_configs,
    model_providers,
    resume_import_lexicon,
    resumes,
    section_registry,
    templates,
    workspace,
)
from app.services.agent_runs import AgentRunManager
from app.services.agent_sessions import fail_interrupted_agent_turn_executions
from app.services.auth_accounts import ensure_auth_database
from app.services.auth_oauth import OAUTH_SESSION_TTL_SECONDS
from app.services.model_metadata import ensure_model_metadata_cache
from app.services.pdf import cleanup_expired_exports
from app.services.storage_deletions import recover_pending_storage_deletions

ExceptionHandler = Callable[[Request, Exception], Response | Awaitable[Response]]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize or verify the current database before serving requests."""

    ensure_auth_database()
    ensure_database_schema()
    recover_pending_storage_deletions()
    with closing(connect()) as conn:
        fail_interrupted_agent_turn_executions(conn)
    ensure_model_metadata_cache()
    cleanup_expired_exports()
    app.state.agent_runs = AgentRunManager()
    try:
        yield
    finally:
        await app.state.agent_runs.shutdown()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application instance."""

    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )

    app.add_exception_handler(
        HTTPException,
        cast(ExceptionHandler, http_exception_handler),
    )
    app.add_exception_handler(
        RequestValidationError,
        cast(ExceptionHandler, validation_exception_handler),
    )
    app.add_exception_handler(Exception, unhandled_exception_handler)
    app.middleware("http")(jwt_auth_middleware)
    app.add_middleware(
        OAuthSessionMiddleware,
        secret_key=hmac.digest(
            os.environ[JWT_SECRET_ENV_NAME].encode(),
            b"reseno-oauth-session",
            hashlib.sha256,
        ).hex(),
        session_cookie="reseno-oauth",
        max_age=OAUTH_SESSION_TTL_SECONDS,
        path="/api/auth/oauth",
        same_site="lax",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(auth_oauth.router)
    app.include_router(workspace.router)
    app.include_router(resumes.router)
    app.include_router(templates.router)
    app.include_router(imports.router)
    app.include_router(model_providers.router)
    app.include_router(model_configs.router)
    app.include_router(resume_import_lexicon.router)
    app.include_router(section_registry.router)
    app.include_router(agent.router)
    app.include_router(exports.router)

    return app


app = create_app()
