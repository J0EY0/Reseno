from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import cast

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.config import get_settings
from app.db.migrations import migrate_db
from app.exceptions import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from app.middleware.auth import jwt_auth_middleware
from app.routers import (
    agent,
    auth,
    exports,
    health,
    imports,
    model_configs,
    model_providers,
    resumes,
    section_registry,
    templates,
    workspace,
)
from app.services.model_metadata import ensure_model_metadata_cache

ExceptionHandler = Callable[[Request, Exception], Response | Awaitable[Response]]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Run startup database migrations before serving requests."""

    migrate_db()
    ensure_model_metadata_cache()
    yield


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
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(workspace.router)
    app.include_router(resumes.router)
    app.include_router(templates.router)
    app.include_router(imports.router)
    app.include_router(model_providers.router)
    app.include_router(model_configs.router)
    app.include_router(section_registry.router)
    app.include_router(agent.router)
    app.include_router(exports.router)

    return app


app = create_app()
