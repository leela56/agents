"""Custom exception classes and global exception handlers.

No stack traces are leaked to clients in production.
All errors return a consistent JSON schema.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Custom Exceptions
# ---------------------------------------------------------------------------
class EmailAgentError(Exception):
    """Base exception for the email agent."""

    def __init__(self, message: str, status_code: int = 500) -> None:
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class GmailAuthError(EmailAgentError):
    """Gmail authentication or authorization error."""

    def __init__(self, message: str = "Gmail authentication failed") -> None:
        super().__init__(message, status_code=401)


class GmailAPIError(EmailAgentError):
    """Gmail API call error."""

    def __init__(self, message: str = "Gmail API request failed") -> None:
        super().__init__(message, status_code=502)


class AgentProcessingError(EmailAgentError):
    """AI agent processing error."""

    def __init__(self, message: str = "AI processing failed") -> None:
        super().__init__(message, status_code=500)


class RateLimitError(EmailAgentError):
    """Rate limit exceeded."""

    def __init__(self, message: str = "Rate limit exceeded. Please try again later.") -> None:
        super().__init__(message, status_code=429)


class EmailNotFoundError(EmailAgentError):
    """Email not found in database."""

    def __init__(self, email_id: str) -> None:
        super().__init__(f"Email not found: {email_id}", status_code=404)


# ---------------------------------------------------------------------------
# Global Exception Handlers
# ---------------------------------------------------------------------------
def register_exception_handlers(app: FastAPI) -> None:
    """Register global exception handlers on the FastAPI app."""

    @app.exception_handler(EmailAgentError)
    async def handle_email_agent_error(request: Request, exc: EmailAgentError) -> JSONResponse:
        logger.warning(
            "handled_error",
            error_type=type(exc).__name__,
            message=exc.message,
            status_code=exc.status_code,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": type(exc).__name__,
                "message": exc.message,
                "status_code": exc.status_code,
            },
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        # Log the full exception for debugging, but don't leak it to client
        logger.exception("unhandled_error", error_type=type(exc).__name__)
        return JSONResponse(
            status_code=500,
            content={
                "error": "InternalServerError",
                "message": "An unexpected error occurred. Please try again later.",
                "status_code": 500,
            },
        )
