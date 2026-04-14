"""Pydantic models (strict) for API request/response schemas.

All string fields have max length validation.
Categories use enums instead of raw strings.
"""

from __future__ import annotations

import datetime

from pydantic import BaseModel, Field

from app.database import DraftTone, EmailCategory


# ---------------------------------------------------------------------------
# Email Schemas
# ---------------------------------------------------------------------------
class EmailBase(BaseModel):
    """Base email fields."""
    gmail_id: str = Field(..., max_length=64)
    thread_id: str | None = Field(None, max_length=64)
    subject: str = Field(default="(no subject)", max_length=500)
    sender: str = Field(..., max_length=320)
    sender_name: str | None = Field(None, max_length=200)
    snippet: str | None = Field(None, max_length=500)
    received_at: datetime.datetime | None = None


class EmailClassification(BaseModel):
    """AI classification result."""
    category: EmailCategory
    confidence: float = Field(..., ge=0.0, le=1.0)
    reasoning: str = Field(..., max_length=500)


class EmailSummary(BaseModel):
    """AI summary result."""
    tldr: str = Field(..., max_length=500)
    key_points: list[str] = Field(default_factory=list, max_length=10)
    action_items: list[str] = Field(default_factory=list, max_length=10)
    sentiment: str = Field(..., max_length=20)
    deadlines: list[str] = Field(default_factory=list, max_length=5)


class DraftReply(BaseModel):
    """AI draft reply result."""
    draft: str = Field(..., max_length=5000)
    tone: DraftTone = DraftTone.PROFESSIONAL
    suggested_subject: str | None = Field(None, max_length=200)


class EmailResponse(BaseModel):
    """Full email response with AI analysis."""
    id: int
    gmail_id: str
    thread_id: str | None = None
    subject: str
    sender: str
    sender_name: str | None = None
    snippet: str | None = None
    body_text: str | None = None
    received_at: datetime.datetime | None = None

    # AI results
    category: EmailCategory = EmailCategory.UNCATEGORIZED
    category_confidence: float | None = None
    summary: str | None = None
    key_points: list[str] | None = None
    action_items: list[str] | None = None
    sentiment: str | None = None
    draft_reply: str | None = None
    draft_tone: str | None = None

    is_processed: bool = False
    processed_at: datetime.datetime | None = None
    created_at: datetime.datetime | None = None

    model_config = {"from_attributes": True}


class EmailListResponse(BaseModel):
    """Paginated email list."""
    emails: list[EmailResponse]
    total: int
    limit: int
    offset: int


class EmailStatsResponse(BaseModel):
    """Dashboard statistics."""
    total_emails: int = 0
    processed_emails: int = 0
    urgent_count: int = 0
    action_required_count: int = 0
    informational_count: int = 0
    spam_count: int = 0


# ---------------------------------------------------------------------------
# Request Schemas
# ---------------------------------------------------------------------------
class ProcessEmailsRequest(BaseModel):
    """Request to process emails."""
    max_emails: int = Field(default=20, ge=1, le=100)
    force_reprocess: bool = False


class RedraftRequest(BaseModel):
    """Request to regenerate a draft reply."""
    tone: DraftTone = DraftTone.PROFESSIONAL
    additional_instructions: str | None = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Auth Schemas
# ---------------------------------------------------------------------------
class AuthStatusResponse(BaseModel):
    """Gmail authentication status."""
    is_authenticated: bool
    email: str | None = None
    scopes: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "healthy"
    database: str = "connected"
    gmail: str = "unknown"
    gemini: str = "unknown"
    version: str = "0.1.0"
