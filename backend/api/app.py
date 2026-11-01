from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.errors import register_error_handlers
from backend.api.middleware import BodySizeLimitMiddleware, RequestIdMiddleware, SecurityHeadersMiddleware, ServerTimingMiddleware
from backend.api.routes import health, transactions, webhooks
from backend.container import Container


def create_app(container: Container) -> FastAPI:
    """Builds the HTTP app from an already-wired Container. Knows nothing about concrete implementations."""
    settings = container.settings

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        for hook in container.on_startup:
            await hook()
        yield
        for hook in container.on_shutdown:
            await hook()

    is_production = settings.env == "production"
    app = FastAPI(
        title="Payment Service",
        lifespan=lifespan,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )
    register_error_handlers(app)
    app.include_router(health.build_router())
    app.include_router(webhooks.build_router(container.ingestion, container.webhook_verifier))
    app.include_router(transactions.build_router(container.query, container.api_key_authenticator))
    # Added last = outermost: every response, including 413s, carries a request id and the security headers.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(ServerTimingMiddleware)
    app.add_middleware(RequestIdMiddleware)
    return app
