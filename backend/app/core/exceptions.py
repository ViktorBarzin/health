from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# Replacement for the request value a validation error would otherwise echo.
_REDACTED = "[redacted]"


class AppError(Exception):
    """Base application error."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class NotFoundError(AppError):
    """Resource not found."""

    def __init__(self, message: str = "Resource not found") -> None:
        super().__init__(message=message, status_code=404)


class AuthenticationError(AppError):
    """Authentication failed."""

    def __init__(self, message: str = "Authentication required") -> None:
        super().__init__(message=message, status_code=401)


class AuthorizationError(AppError):
    """Insufficient permissions."""

    def __init__(self, message: str = "Forbidden") -> None:
        super().__init__(message=message, status_code=403)


class ConflictError(AppError):
    """Resource conflict (e.g. duplicate)."""

    def __init__(self, message: str = "Resource already exists") -> None:
        super().__init__(message=message, status_code=409)


class ValidationError(AppError):
    """Custom validation error."""

    def __init__(self, message: str = "Validation error") -> None:
        super().__init__(message=message, status_code=422)


def _redact_validation_errors(errors: list[Any]) -> list[dict]:
    """Strip the echoed request value from each validation error.

    FastAPI/Pydantic v2's default ``RequestValidationError`` handler serializes
    the offending ``input`` for every error. For a ``"missing"`` error on a
    required field, that ``input`` is the **whole request object** — so a request
    that carries a secret (e.g. a Connection token) alongside a missing sibling
    field would echo the secret in plaintext in the 422 body, and into any
    access-log/APM that captures 4xx bodies. We keep the useful, non-sensitive
    parts (``type`` / ``loc`` / ``msg``) so clients still get actionable feedback,
    and replace ``input`` with a redaction marker. App-wide, because the ``input``
    echo is a general secret-leak vector — not specific to one endpoint.
    """
    cleaned: list[dict] = []
    for err in errors:
        item = dict(err)
        if "input" in item:
            item["input"] = _REDACTED
        # ``ctx`` can carry the original exception object / echoed values from a
        # custom validator — drop it too (it can mirror the input and isn't
        # needed by clients).
        item.pop("ctx", None)
        cleaned.append(item)
    return cleaned


def register_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers on the FastAPI application."""

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        """Return a 422 whose errors never echo the (possibly secret) request value.

        Same status + ``{"detail": [...]}`` shape as FastAPI's default handler, so
        clients are unaffected — only the per-error ``input`` is redacted.
        """
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=jsonable_encoder(
                {"detail": _redact_validation_errors(exc.errors())}
            ),
        )
