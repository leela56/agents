"""DB-backed token storage for the Gmail OAuth client."""

from __future__ import annotations

from typing import Optional

from sqlalchemy import select

from .db import get_session
from .models import OAuthToken


class DBTokenStore:
    """Persists a single Google OAuth token JSON blob in the ``oauth_tokens`` table.

    Implements the ``TokenStore`` Protocol expected by ``app.gmail_client.GmailClient``.
    """

    def __init__(self, provider: str = "google") -> None:
        self.provider = provider

    def save_token(self, token_json: str) -> None:
        with get_session() as session:
            row = session.scalar(
                select(OAuthToken).where(OAuthToken.provider == self.provider)
            )
            if row is None:
                row = OAuthToken(provider=self.provider, token_json=token_json)
                session.add(row)
            else:
                row.token_json = token_json

    def load_token(self) -> Optional[str]:
        with get_session() as session:
            row = session.scalar(
                select(OAuthToken).where(OAuthToken.provider == self.provider)
            )
            return row.token_json if row else None

    def clear_token(self) -> None:
        """Remove the stored OAuth token (disconnect Gmail)."""
        with get_session() as session:
            row = session.scalar(
                select(OAuthToken).where(OAuthToken.provider == self.provider)
            )
            if row is not None:
                session.delete(row)
