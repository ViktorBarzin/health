from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


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


def register_exception_handlers(app: FastAPI) -> None:
    """Register custom exception handlers on the FastAPI application."""

    @app.exception_handler(AppError)
    async def app_error_handler(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.message},
        )
