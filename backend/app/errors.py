import logging
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any]


class ErrorEnvelope(BaseModel):
    error: ErrorBody


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    envelope = ErrorEnvelope(error=ErrorBody(code=code, message=message, details=details or {}))
    return JSONResponse(envelope.model_dump(), status_code=status_code, headers=headers)


def _status_phrase(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "HTTP error"


def _code_from_phrase(phrase: str) -> str:
    return phrase.lower().replace(" ", "_").replace("-", "_")


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        phrase = _status_phrase(exc.status_code)
        has_text_detail = isinstance(exc.detail, str)
        return error_response(
            exc.status_code,
            _code_from_phrase(phrase),
            exc.detail if isinstance(exc.detail, str) else phrase,
            details=None if has_text_detail else {"detail": exc.detail},
            headers=dict(exc.headers) if exc.headers else None,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {"location": list(error["loc"]), "message": error["msg"], "type": error["type"]}
            for error in exc.errors()
        ]
        return error_response(
            422, "validation_error", "Request validation failed", details={"fields": fields}
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception on %s %s", request.method, request.url.path, exc_info=exc)
        return error_response(500, "internal_error", "Internal server error")
