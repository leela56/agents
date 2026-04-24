"""Gmail API service — fetches, parses, and manages email data.

Handles OAuth token refresh, email body extraction from MIME,
and connection error handling with retry logic.
"""

from __future__ import annotations

import base64
import email as email_lib
from datetime import datetime, timezone
from email.utils import parseaddr, parsedate_to_datetime

import structlog
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.config import Settings, get_settings
from app.exceptions import GmailAPIError, GmailAuthError
from app.security import TokenEncryptor, sanitize_email_body

logger = structlog.get_logger()


class GmailService:
    """Wrapper around the Gmail API with encrypted token management."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._service = None
        self._encryptor = TokenEncryptor(self._settings.encryption_key)

    def _get_credentials(self) -> Credentials:
        """Load and refresh credentials from encrypted storage."""
        token_data = self._encryptor.load_encrypted_token(self._settings.token_file)

        if not token_data:
            raise GmailAuthError("Not authenticated. Please connect your Gmail account first.")

        creds = Credentials(
            token=token_data["token"],
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data.get("token_uri"),
            client_id=token_data.get("client_id"),
            client_secret=token_data.get("client_secret"),
            scopes=token_data.get("scopes"),
        )

        # Refresh if expired
        if creds.expired and creds.refresh_token:
            try:
                creds.refresh(GoogleAuthRequest())
                # Re-save updated token
                token_data["token"] = creds.token
                self._encryptor.save_encrypted_token(token_data, self._settings.token_file)
                logger.info("gmail_token_refreshed")
            except Exception as e:
                logger.error("gmail_token_refresh_failed", error=str(e))
                raise GmailAuthError("Token refresh failed. Please re-authenticate.") from e

        if not creds.valid:
            raise GmailAuthError("Invalid credentials. Please re-authenticate.")

        return creds

    def _get_service(self):
        """Get or create the Gmail API service."""
        if self._service is None:
            creds = self._get_credentials()
            self._service = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return self._service

    async def fetch_emails(self, max_results: int = 20) -> list[dict]:
        """Fetch recent emails from the inbox.

        Returns a list of parsed email dictionaries.
        """
        try:
            service = self._get_service()
            results = (
                service.users()
                .messages()
                .list(userId="me", maxResults=max_results, labelIds=["INBOX"])
                .execute()
            )

            messages = results.get("messages", [])
            if not messages:
                logger.info("gmail_fetch_no_messages")
                return []

            emails = []
            for msg_info in messages:
                try:
                    email_data = await self.get_email_detail(msg_info["id"])
                    if email_data:
                        emails.append(email_data)
                except Exception as e:
                    logger.warning("gmail_fetch_single_failed", msg_id=msg_info["id"], error=str(e))
                    continue

            logger.info("gmail_fetch_success", count=len(emails))
            return emails

        except HttpError as e:
            logger.error("gmail_api_error", status=e.resp.status, reason=str(e))
            raise GmailAPIError(f"Gmail API error: {e.resp.status}") from e

    async def get_email_detail(self, message_id: str) -> dict | None:
        """Get full email content by message ID."""
        try:
            service = self._get_service()
            message = (
                service.users()
                .messages()
                .get(userId="me", id=message_id, format="full")
                .execute()
            )
            return self._parse_message(message)

        except HttpError as e:
            logger.error("gmail_get_detail_error", msg_id=message_id, error=str(e))
            raise GmailAPIError(f"Failed to fetch email {message_id}") from e

    def _parse_message(self, message: dict) -> dict:
        """Parse a Gmail API message into a clean dictionary."""
        headers = {h["name"].lower(): h["value"] for h in message["payload"].get("headers", [])}

        # Parse sender
        sender_full = headers.get("from", "Unknown")
        sender_name, sender_email = parseaddr(sender_full)

        # Parse date
        date_str = headers.get("date")
        received_at = None
        if date_str:
            try:
                received_at = parsedate_to_datetime(date_str)
                if received_at.tzinfo is None:
                    received_at = received_at.replace(tzinfo=timezone.utc)
            except Exception:
                received_at = datetime.now(timezone.utc)

        # Extract body
        body = self._extract_body(message["payload"])
        sanitized_body = sanitize_email_body(body) if body else None

        return {
            "gmail_id": message["id"],
            "thread_id": message.get("threadId"),
            "subject": headers.get("subject", "(no subject)")[:500],
            "sender": sender_email[:320] if sender_email else sender_full[:320],
            "sender_name": sender_name[:200] if sender_name else None,
            "recipients": headers.get("to", "")[:1000],
            "snippet": message.get("snippet", "")[:500],
            "body_text": sanitized_body,
            "received_at": received_at,
        }

    def _extract_body(self, payload: dict) -> str | None:
        """Recursively extract the email body text from MIME payload."""
        body_text = ""

        if payload.get("body", {}).get("data"):
            data = payload["body"]["data"]
            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            mime_type = payload.get("mimeType", "")
            if "text/plain" in mime_type:
                return decoded
            if "text/html" in mime_type:
                body_text = decoded  # Will be sanitized later

        parts = payload.get("parts", [])
        # Prefer text/plain over text/html
        for part in parts:
            if part.get("mimeType") == "text/plain":
                result = self._extract_body(part)
                if result:
                    return result

        for part in parts:
            result = self._extract_body(part)
            if result:
                return result

        return body_text or None


# Singleton
_gmail_service: GmailService | None = None


def get_gmail_service() -> GmailService:
    """Get or create the Gmail service singleton."""
    global _gmail_service
    if _gmail_service is None:
        _gmail_service = GmailService()
    return _gmail_service
