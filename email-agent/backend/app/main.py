"""FastAPI application entry point.

- Uses lifespan context manager (not deprecated startup/shutdown events)
- Registers security middleware stack
- Strict CORS allowlist
- Structured logging initialization
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import os
import structlog
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.database import close_database, init_database
from app.exceptions import register_exception_handlers
from app.middleware import RequestLoggingMiddleware, SecurityHeadersMiddleware
from app.routers import auth, emails, health
from app.security import limiter


def _configure_logging() -> None:
    """Configure structlog for JSON-formatted structured logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer()
            if get_settings().is_development
            else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.get_config().get("min_level", 0)
        ),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown."""
    logger = structlog.get_logger()

    # Startup
    _configure_logging()
    logger.info("app_starting", version="0.1.0")

    # Allow OAuth over HTTP for local development
    if get_settings().is_development:
        os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
        os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
        logger.info("oauth_insecure_transport_enabled")

    await init_database()
    logger.info("app_ready")

    yield

    # Shutdown
    await close_database()
    logger.info("app_shutdown")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="AI Email Agent",
        description="Production-grade AI email assistant — classifies, summarizes, and drafts replies",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.is_development else None,
        redoc_url="/redoc" if settings.is_development else None,
    )

    # --- Rate Limiter ---
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # --- Middleware Stack (order matters: last added = first executed) ---
    # 1. CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
    )
    # 2. Security Headers
    app.add_middleware(SecurityHeadersMiddleware)
    # 3. Request Logging
    app.add_middleware(RequestLoggingMiddleware)

    # --- Exception Handlers ---
    register_exception_handlers(app)

    # --- Routers ---
    app.include_router(auth.router)
    app.include_router(emails.router)
    app.include_router(health.router)

    # --- Root ---
    @app.get("/", tags=["Root"])
    async def root():
        return {
            "name": "AI Email Agent",
            "version": "0.1.0",
            "docs": "/docs" if settings.is_development else "disabled",
            "health": "/health",
        }

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon():
        # 1x1 transparent PNG
        content = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
            b"\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r"
            b"\n\x2e\xe4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return Response(content=content, media_type="image/png")

    return app


# Create app instance
app = create_app()
