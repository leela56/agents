"""Health check and readiness endpoints."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.database import get_db_session
from app.models import HealthResponse
from app.security import TokenEncryptor

logger = structlog.get_logger()
router = APIRouter(prefix="/health", tags=["Health"])


@router.get("", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    """Liveness check — is the server running?"""
    return HealthResponse(status="healthy")


@router.get("/ready", response_model=HealthResponse)
async def readiness(
    db: AsyncSession = Depends(get_db_session),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """Readiness check — are all dependencies available?"""
    response = HealthResponse(status="healthy")

    # Check database
    try:
        await db.execute(text("SELECT 1"))
        response.database = "connected"
    except Exception as e:
        response.database = f"error: {str(e)[:50]}"
        response.status = "degraded"
        logger.warning("health_db_check_failed", error=str(e))

    # Check Gmail auth
    try:
        encryptor = TokenEncryptor(settings.encryption_key)
        token_data = encryptor.load_encrypted_token(settings.token_file)
        response.gmail = "authenticated" if token_data else "not_authenticated"
    except Exception:
        response.gmail = "error"
        response.status = "degraded"

    # Check Gemini (basic key validation)
    response.gemini = "configured" if settings.gemini_api_key else "not_configured"

    return response
