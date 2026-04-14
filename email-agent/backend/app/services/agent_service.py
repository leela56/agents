"""Agent Service — orchestrates email processing through the LangGraph pipeline.

Manages the full flow: fetch emails → store → process through AI → update database.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.draft_writer import draft_reply
from app.agents.graph import EmailAgentState, get_email_agent_graph
from app.database import DraftTone, EmailCategory, EmailRecord
from app.exceptions import AgentProcessingError
from app.services.gmail_service import get_gmail_service

logger = structlog.get_logger()


class AgentService:
    """Orchestrates email fetching, AI processing, and database storage."""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._gmail = get_gmail_service()
        self._graph = get_email_agent_graph()

    async def fetch_and_store_emails(self, max_emails: int = 20) -> list[EmailRecord]:
        """Fetch emails from Gmail and store new ones in the database."""
        raw_emails = await self._gmail.fetch_emails(max_results=max_emails)
        stored = []

        for email_data in raw_emails:
            # Check if email already exists
            existing = await self._db.execute(
                select(EmailRecord).where(EmailRecord.gmail_id == email_data["gmail_id"])
            )
            if existing.scalar_one_or_none():
                continue

            # Store new email
            record = EmailRecord(
                gmail_id=email_data["gmail_id"],
                thread_id=email_data.get("thread_id"),
                subject=email_data.get("subject", "(no subject)"),
                sender=email_data.get("sender", "unknown"),
                sender_name=email_data.get("sender_name"),
                recipients=email_data.get("recipients"),
                body_text=email_data.get("body_text"),
                snippet=email_data.get("snippet"),
                received_at=email_data.get("received_at"),
            )
            self._db.add(record)
            stored.append(record)

        await self._db.flush()
        logger.info("emails_stored", new_count=len(stored), total_fetched=len(raw_emails))
        return stored

    async def process_email(self, record: EmailRecord) -> EmailRecord:
        """Process a single email through the AI pipeline."""
        email_data = {
            "gmail_id": record.gmail_id,
            "subject": record.subject,
            "sender": record.sender,
            "sender_name": record.sender_name,
            "body_text": record.body_text,
            "received_at": str(record.received_at) if record.received_at else None,
        }

        try:
            # Run through LangGraph pipeline
            initial_state: EmailAgentState = {
                "email_data": email_data,
                "classification": None,
                "summary": None,
                "draft": None,
                "should_draft": False,
                "error": None,
            }

            result = await self._graph.ainvoke(initial_state)

            # Update record with results
            if result.get("classification"):
                cls = result["classification"]
                record.category = cls.get("category", EmailCategory.UNCATEGORIZED.value)
                record.category_confidence = cls.get("confidence", 0.0)

            if result.get("summary"):
                summary = result["summary"]
                record.summary = summary.get("tldr", "")
                record.key_points = json.dumps(summary.get("key_points", []))
                record.action_items = json.dumps(summary.get("action_items", []))
                record.sentiment = summary.get("sentiment", "neutral")

            if result.get("draft"):
                draft = result["draft"]
                record.draft_reply = draft.get("draft", "")
                record.draft_tone = draft.get("tone", DraftTone.PROFESSIONAL.value)

            record.is_processed = True
            record.processed_at = datetime.now(timezone.utc)

            logger.info(
                "email_processed",
                gmail_id=record.gmail_id,
                category=record.category,
                has_draft=record.draft_reply is not None,
            )
            return record

        except Exception as e:
            logger.error("email_processing_failed", gmail_id=record.gmail_id, error=str(e))
            raise AgentProcessingError(f"Failed to process email: {str(e)}") from e

    async def process_unprocessed_emails(self, max_emails: int = 20) -> list[EmailRecord]:
        """Process all unprocessed emails in the database."""
        result = await self._db.execute(
            select(EmailRecord)
            .where(EmailRecord.is_processed == False)  # noqa: E712
            .order_by(EmailRecord.received_at.desc())
            .limit(max_emails)
        )
        unprocessed = list(result.scalars().all())

        processed = []
        for record in unprocessed:
            try:
                await self.process_email(record)
                processed.append(record)
            except Exception as e:
                logger.warning("skip_email_processing", gmail_id=record.gmail_id, error=str(e))
                continue

        await self._db.flush()
        logger.info("batch_processing_complete", processed=len(processed), total=len(unprocessed))
        return processed

    async def redraft_email(
        self,
        record: EmailRecord,
        tone: DraftTone = DraftTone.PROFESSIONAL,
        additional_instructions: str | None = None,
    ) -> EmailRecord:
        """Regenerate a draft reply for an email with a different tone."""
        email_data = {
            "subject": record.subject,
            "sender": record.sender,
            "sender_name": record.sender_name,
            "body_text": record.body_text,
        }

        action_items = json.loads(record.action_items) if record.action_items else []

        draft = await draft_reply(
            email_data=email_data,
            summary=record.summary or "",
            action_items=action_items,
            tone=tone,
            additional_instructions=additional_instructions,
        )

        record.draft_reply = draft.get("draft", "")
        record.draft_tone = tone.value
        await self._db.flush()

        logger.info("email_redrafted", gmail_id=record.gmail_id, tone=tone.value)
        return record

    async def get_stats(self) -> dict:
        """Get email processing statistics."""
        total = await self._db.execute(select(func.count(EmailRecord.id)))
        processed = await self._db.execute(
            select(func.count(EmailRecord.id)).where(EmailRecord.is_processed == True)  # noqa: E712
        )

        # Category counts
        categories = {}
        for cat in EmailCategory:
            count = await self._db.execute(
                select(func.count(EmailRecord.id)).where(EmailRecord.category == cat.value)
            )
            categories[cat.value] = count.scalar() or 0

        return {
            "total_emails": total.scalar() or 0,
            "processed_emails": processed.scalar() or 0,
            "urgent_count": categories.get("urgent", 0),
            "action_required_count": categories.get("action_required", 0),
            "informational_count": categories.get("informational", 0),
            "spam_count": categories.get("spam", 0),
        }
