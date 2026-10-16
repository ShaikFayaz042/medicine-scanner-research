"""Auth error responses compatible with the mobile client contract."""

from __future__ import annotations

import uuid
import logging

from fastapi import FastAPI, Request, status
from fastapi.exception_handlers import http_exception_handler, request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from slowapi.errors import RateLimitExceeded
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID") or uuid.uuid4().hex


def _auth_error(request: Request, detail: str, status_code: int) -> JSONResponse:
    request_id = _request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "requestId": request_id},
        headers={"X-Request-ID": request_id},
    )


def register_auth_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> Response:
        if request.url.path.startswith("/auth"):
            return _auth_error(request, str(exc.detail), exc.status_code)
        return await http_exception_handler(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> Response:
        if not request.url.path.startswith("/auth"):
            return await request_validation_exception_handler(request, exc)

        problems = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'][1:]) or 'body'}: {error['msg']}"
            for error in exc.errors()
        )
        return _auth_error(
            request,
            f"Invalid request. {problems}",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limited(request: Request, exc: RateLimitExceeded) -> Response:
        if request.url.path.startswith("/auth"):
            return _auth_error(request, str(exc.detail), status.HTTP_429_TOO_MANY_REQUESTS)
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": str(exc.detail)},
        )

    @app.exception_handler(Exception)
    async def _unexpected_error(request: Request, exc: Exception) -> Response:
        if not request.url.path.startswith("/auth"):
            raise exc
        logger.exception("mobile auth request failed")
        return _auth_error(
            request,
            "Something went wrong. Please try again.",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )