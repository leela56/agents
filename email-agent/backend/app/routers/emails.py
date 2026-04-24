"""Email API endpoints — list, detail, process, redraft, and stats.

All endpoints have input validation, pagination, and rate limiting.
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DraftTone, EmailCategory, EmailRecord, get_db_session
from app.exceptions import EmailNotFoundError
from app.models import (
    EmailListResponse,
    EmailResponse,
    EmailStatsResponse,
    ProcessEmailsRequest,
    RedraftRequest,
)
from app.security import limiter
from app.services.agent_service import AgentService

logger = structlog.get_logger()
router = APIRouter(prefix="/emails", tags=["Emails"])


def _record_to_response(record: EmailRecord) -> EmailResponse:
    """Convert a database record to an API response model."""
    return EmailResponse(
        id=record.id,
        gmail_id=record.gmail_id,
        thread_id=record.thread_id,
        subject=record.subject,
        sender=record.sender,
        sender_name=record.sender_name,
        snippet=record.snippet,
        body_text=record.body_text,
        received_at=record.received_at,
        category=EmailCategory(record.category) if record.category else EmailCategory.UNCATEGORIZED,
        category_confidence=record.category_confidence,
        summary=record.summary,
        key_points=json.loads(record.key_points) if record.key_points else None,
        action_items=json.loads(record.action_items) if record.action_items else None,
        sentiment=record.sentiment,
        draft_reply=record.draft_reply,
        draft_tone=record.draft_tone,
        is_processed=record.is_processed,
        processed_at=record.processed_at,
        created_at=record.created_at,
    )


@router.get("", response_model=EmailListResponse)
async def list_emails(
    category: EmailCategory | None = None,
    is_processed: bool | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db_session),
) -> EmailListResponse:
    """List emails with optional filtering and pagination."""
    query = select(EmailRecord).order_by(EmailRecord.received_at.desc())

    if category:
        query = query.where(EmailRecord.category == category.value)
    if is_processed is not None:
        query = query.where(EmailRecord.is_processed == is_processed)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Apply pagination
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    records = list(result.scalars().all())

    return EmailListResponse(
        emails=[_record_to_response(r) for r in records],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=EmailStatsResponse)
async def get_stats(
    db: AsyncSession = Depends(get_db_session),
) -> EmailStatsResponse:
    """Get email processing statistics for the dashboard."""
    service = AgentService(db)
    stats = await service.get_stats()
    return EmailStatsResponse(**stats)


@router.get("/{email_id}", response_model=EmailResponse)
async def get_email(
    email_id: int,
    db: AsyncSession = Depends(get_db_session),
) -> EmailResponse:
    """Get a single email with AI analysis results."""
    result = await db.execute(select(EmailRecord).where(EmailRecord.id == email_id))
    record = result.scalar_one_or_none()

    if not record:
        raise EmailNotFoundError(str(email_id))

    return _record_to_response(record)


@router.post("/process", response_model=EmailListResponse)
@limiter.limit("10/minute")
async def process_emails(
    request: Request,
    body: ProcessEmailsRequest | None = None,
    db: AsyncSession = Depends(get_db_session),
) -> EmailListResponse:
    """Fetch new emails from Gmail and process through AI pipeline.

    Rate limited: 10 requests/minute.
    """
    max_emails = body.max_emails if body else 20
    force = body.force_reprocess if body else False

    service = AgentService(db)

    # Step 1: Fetch and store new emails
    new_emails = await service.fetch_and_store_emails(max_emails=max_emails)
    logger.info("process_fetched", new_count=len(new_emails))

    # Step 2: Process unprocessed emails through AI
    processed = await service.process_unprocessed_emails(max_emails=max_emails)
    logger.info("process_completed", processed_count=len(processed))

    # Return processed emails
    return EmailListResponse(
        emails=[_record_to_response(r) for r in processed],
        total=len(processed),
        limit=max_emails,
        offset=0,
    )


@router.post("/{email_id}/redraft", response_model=EmailResponse)
@limiter.limit("20/minute")
async def redraft_email(
    request: Request,
    email_id: int,
    body: RedraftRequest,
    db: AsyncSession = Depends(get_db_session),
) -> EmailResponse:
    """Regenerate an AI draft reply with a different tone."""
    result = await db.execute(select(EmailRecord).where(EmailRecord.id == email_id))
    record = result.scalar_one_or_none()

    if not record:
        raise EmailNotFoundError(str(email_id))

    service = AgentService(db)
    updated = await service.redraft_email(
        record=record,
        tone=body.tone,
        additional_instructions=body.additional_instructions,
    )

    return _record_to_response(updated)
