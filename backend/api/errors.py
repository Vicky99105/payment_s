"""Maps every error to an HTTP response in one place. Clients never see stack traces, SQL or secrets."""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api.schemas import ErrorOut
from backend.domain.errors import EnqueueError, PersistenceError
from backend.security.contract import AuthenticationError, AuthorizationError

logger = logging.getLogger("payment_service.api")


def _request_id(request: Request) -> str | None:
    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else None


def _error(request: Request, status: int, error: str, detail: str | None = None, headers: dict[str, str] | None = None) -> JSONResponse:
    body = ErrorOut(error=error, detail=detail, request_id=_request_id(request))
    return JSONResponse(status_code=status, content=body.model_dump(exclude_none=True), headers=headers)


def _validation_detail(errors: list[Any]) -> str:
    """Field paths and messages only; the offending input values are never echoed back."""
    parts = []
    for err in errors[:10]:
        loc = ".".join(str(p) for p in err.get("loc", ()) if p not in ("body",))
        parts.append(f"{loc or 'body'}: {err.get('msg', 'invalid')}")
    return "; ".join(parts)


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthenticationError)
    async def _authn(request: Request, exc: AuthenticationError) -> JSONResponse:
        return _error(request, 401, "unauthorized", str(exc), {"WWW-Authenticate": "Bearer"})

    @app.exception_handler(AuthorizationError)
    async def _authz(request: Request, exc: AuthorizationError) -> JSONResponse:
        return _error(request, 403, "forbidden", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(request, 422, "invalid_request", _validation_detail(list(exc.errors())))

    @app.exception_handler(PersistenceError)
    @app.exception_handler(EnqueueError)
    async def _unavailable(request: Request, exc: Exception) -> JSONResponse:
        logger.error("dependency unavailable", extra={"request_id": _request_id(request), "error_type": type(exc).__name__})
        return _error(request, 503, "service_unavailable", "temporarily unable to accept the request, retry later", {"Retry-After": "5"})

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        error = {404: "not_found", 405: "method_not_allowed", 413: "payload_too_large"}.get(exc.status_code, "http_error")
        return _error(request, exc.status_code, error, exc.detail if isinstance(exc.detail, str) else None)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled error", extra={"request_id": _request_id(request)})
        return _error(request, 500, "internal_error")
