"""Gmail API client for OAuth and draft management.

Provides :class:`GmailClient` for performing the OAuth 2.0 Web-style
authorization code flow (suitable for a FastAPI redirect callback) and for
creating or updating Gmail drafts with optional file attachments.

Token persistence is abstracted via the :class:`TokenStore` Protocol so the
host application can plug in a DB-backed implementation. A
:class:`FileTokenStore` is included for convenience / local development.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)


class TokenStore(Protocol):
    """Minimal persistence contract for serialized OAuth credentials."""

    def save_token(self, token_json: str) -> None: ...

    def load_token(self) -> str | None: ...

    def clear_token(self) -> None:
        """Remove stored credentials (disconnect / before scope upgrade exchange)."""
        ...


class FileTokenStore:
    """Convenience :class:`TokenStore` that persists the token JSON to disk.

    The host application is expected to provide its own DB-backed
    implementation; this class exists as a fallback for local development
    and tests.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def save_token(self, token_json: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(token_json, encoding="utf-8")

    def load_token(self) -> str | None:
        if not self._path.exists():
            return None
        return self._path.read_text(encoding="utf-8")

    def clear_token(self) -> None:
        try:
            if self._path.exists():
                self._path.unlink()
        except OSError:
            logger.warning("Could not remove token file %s", self._path)


class GmailNotAuthenticatedError(Exception):
    """Raised when a Gmail API call is attempted without a usable token."""


class GmailDraftNoLongerValidError(Exception):
    """Raised when ``drafts.send`` fails because the id is not a draft (e.g. already sent in Gmail)."""


def _http_error_status_code(resp: object) -> int:
    raw = getattr(resp, "status", None)
    if raw is None and hasattr(resp, "get"):
        raw = resp.get("status")  # type: ignore[union-attr]
    try:
        return int(raw) if raw is not None else 0
    except (TypeError, ValueError):
        return 0


def _gmail_draft_send_failed_because_stale(exc: HttpError) -> bool:
    """True if Gmail rejected ``drafts.send`` because the draft id is gone or not a draft."""
    code = _http_error_status_code(exc.resp)
    reason = (getattr(exc, "reason", "") or "").lower()
    raw = getattr(exc, "content", b"") or b""
    body = raw.decode("utf-8", errors="ignore").lower() if isinstance(raw, bytes) else str(raw).lower()
    blob = f"{reason} {body}"
    if "message not a draft" in blob:
        return True
    if "not a draft" in blob and code in (400, 404):
        return True
    if code == 404 and ("not found" in blob or "invalid" in blob):
        return True
    return False


class GmailClient:
    """Thin wrapper around the Gmail API for OAuth + draft management."""

    # gmail.compose + openid + userinfo (name, picture, email for header profile)
    SCOPES = [
        "https://www.googleapis.com/auth/gmail.compose",
        "openid",
        "https://www.googleapis.com/auth/userinfo.profile",
        "https://www.googleapis.com/auth/userinfo.email",
    ]

    def __init__(self, credentials_path: Path, token_store: TokenStore) -> None:
        self._credentials_path = Path(credentials_path)
        self._token_store = token_store
        self._userinfo_cache: tuple[float, dict[str, str] | None] | None = None

    def clear_cached_userinfo(self) -> None:
        """Clear cached Google userinfo (e.g. after logout or reconnect)."""
        self._userinfo_cache = None

    def _build_flow(self, redirect_uri: str, state: str | None = None) -> Flow:
        flow = Flow.from_client_secrets_file(
            str(self._credentials_path),
            scopes=self.SCOPES,
            state=state,
        )
        flow.redirect_uri = redirect_uri
        return flow

    def get_authorization_url(self, redirect_uri: str) -> tuple[str, str, str]:
        """Return ``(auth_url, state, code_verifier)``.

        Callers must persist both ``state`` and ``code_verifier`` across the
        redirect and pass them to :meth:`exchange_code`. ``state`` prevents
        CSRF; ``code_verifier`` is required by PKCE (which
        ``google-auth-oauthlib`` enables by default for Web flows).
        """
        flow = self._build_flow(redirect_uri)
        auth_url, state = flow.authorization_url(
            access_type="offline",
            prompt="consent",
            include_granted_scopes="true",
        )
        code_verifier = getattr(flow, "code_verifier", None) or ""
        logger.debug("Generated Gmail authorization URL (state=%s)", state)
        return auth_url, state, code_verifier

    def exchange_code(
        self,
        code: str,
        redirect_uri: str,
        state: str,
        code_verifier: str | None = None,
    ) -> None:
        """Complete the OAuth flow and persist refreshable credentials."""
        # google-auth merges with any stored credentials; if the saved token list
        # scopes that no longer match SCOPES (e.g. after adding userinfo.*),
        # fetch_token raises "Scope has changed ...". Clearing first is safe here
        # because we replace the refresh token entirely with this exchange.
        self._token_store.clear_token()

        flow = self._build_flow(redirect_uri, state=state)
        if code_verifier:
            flow.code_verifier = code_verifier
        flow.fetch_token(code=code)
        creds: Credentials = flow.credentials
        self._token_store.save_token(creds.to_json())
        self._userinfo_cache = None
        logger.info("Gmail OAuth flow completed and credentials persisted")

    def _load_credentials(self) -> Credentials | None:
        token_json = self._token_store.load_token()
        if not token_json:
            return None
        try:
            info = json.loads(token_json)
        except json.JSONDecodeError:
            logger.warning("Stored Gmail token is not valid JSON")
            return None
        try:
            return Credentials.from_authorized_user_info(info, scopes=self.SCOPES)
        except Exception as exc:  # noqa: BLE001 — bad or stale token JSON
            logger.warning(
                "Stored OAuth token could not be loaded (use Log out, then connect again): %s",
                exc,
            )
            return None

    def is_authenticated(self) -> bool:
        """True if a token with a refresh token is stored."""
        creds = self._load_credentials()
        return bool(creds and creds.refresh_token)

    def _credentials_with_fresh_access_token(self) -> Credentials | None:
        creds = self._load_credentials()
        if creds is None or not creds.refresh_token:
            return None
        if creds.expired:
            logger.debug("Refreshing expired Gmail credentials")
            creds.refresh(Request())
            self._token_store.save_token(creds.to_json())
        return creds

    def _oauth2_userinfo_raw(self) -> dict | None:
        creds = self._credentials_with_fresh_access_token()
        if creds is None or not creds.token:
            return None
        try:
            resp = requests.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {creds.token}"},
                timeout=15,
            )
        except requests.RequestException as exc:
            logger.warning("userinfo request failed: %s", exc)
            return None
        if not resp.ok:
            if resp.status_code == 401:
                logger.debug(
                    "userinfo 401 (token revoked, missing scopes, or invalid); "
                    "header profile will be empty until Gmail is reconnected."
                )
            else:
                logger.warning(
                    "userinfo HTTP %s: %s", resp.status_code, (resp.text or "")[:300]
                )
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    def fetch_user_info(self) -> dict[str, str] | None:
        """Return ``name``, ``email``, and ``picture`` (avatar URL) from Google userinfo.

        Returns ``None`` if not authenticated or userinfo fails. Reconnect Gmail after
        scope changes if this stays empty. Cached briefly to avoid calling Google on
        every HTTP request (e.g. header middleware).
        """
        now = time.monotonic()
        if self._userinfo_cache is not None:
            ts, cached = self._userinfo_cache
            if now - ts < 120.0:
                return cached
        data = self._oauth2_userinfo_raw()
        if not data:
            self._userinfo_cache = (now, None)
            return None
        name = (data.get("name") or "").strip()
        if not name:
            given = (data.get("given_name") or "").strip()
            family = (data.get("family_name") or "").strip()
            name = f"{given} {family}".strip()
        out: dict[str, str] = {
            "name": name,
            "email": (data.get("email") or "").strip(),
            "picture": (data.get("picture") or "").strip(),
        }
        self._userinfo_cache = (time.monotonic(), out)
        return out

    def fetch_user_display_name(self) -> str | None:
        """Return the Google account display name from userinfo, if authorized."""
        info = self.fetch_user_info()
        if not info:
            return None
        n = (info.get("name") or "").strip()
        return n or None

    def fetch_gmail_me_email(self) -> str | None:
        """Primary Gmail address via ``users.getProfile`` (works with ``gmail.compose`` only).

        Use when OAuth userinfo omits ``email`` (missing ``userinfo.email`` scope on the token).
        """
        if not self.is_authenticated():
            return None
        try:
            service = self._get_service()
            prof = service.users().getProfile(userId="me").execute()
        except Exception as exc:  # noqa: BLE001
            logger.debug("Gmail users.getProfile failed: %s", exc)
            return None
        addr = (prof.get("emailAddress") or "").strip()
        return addr or None

    def _get_service(self):
        creds = self._credentials_with_fresh_access_token()
        if creds is None or not creds.refresh_token:
            raise GmailNotAuthenticatedError(
                "No Gmail credentials available; complete OAuth first."
            )
        return build("gmail", "v1", credentials=creds, cache_discovery=False)

    def create_or_update_draft(
        self,
        to: str,
        subject: str,
        body: str,
        attachment_path: Path | None = None,
        attachment_filename: str | None = None,
        existing_draft_id: str | None = None,
    ) -> str:
        """Create a new draft or update an existing one. Returns the draft id."""
        if not self.is_authenticated():
            raise GmailNotAuthenticatedError(
                "Cannot create draft: Gmail client is not authenticated."
            )

        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        if attachment_path is not None:
            attachment_path = Path(attachment_path)
            if attachment_path.exists():
                fname = (attachment_filename or "").strip() or attachment_path.name
                fname = Path(fname).name  # never allow path components
                mime_type, _ = mimetypes.guess_type(fname)
                if mime_type is None:
                    mime_type, _ = mimetypes.guess_type(attachment_path.name)
                if mime_type is None:
                    mime_type = "application/octet-stream"
                maintype, _, subtype = mime_type.partition("/")
                if not subtype:
                    maintype, subtype = "application", "octet-stream"
                data = attachment_path.read_bytes()
                msg.add_attachment(
                    data,
                    maintype=maintype,
                    subtype=subtype,
                    filename=fname,
                )
            else:
                logger.warning(
                    "Attachment path %s does not exist; skipping", attachment_path
                )

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service = self._get_service()
        drafts = service.users().drafts()
        request_body = {"message": {"raw": raw}}

        if existing_draft_id:
            logger.info("Updating Gmail draft %s", existing_draft_id)
            response = drafts.update(
                userId="me", id=existing_draft_id, body=request_body
            ).execute()
        else:
            logger.info("Creating new Gmail draft")
            response = drafts.create(userId="me", body=request_body).execute()

        draft_id = response.get("id")
        if not draft_id:
            raise RuntimeError(f"Gmail API response missing draft id: {response!r}")
        return draft_id

    def send_draft(self, draft_id: str) -> str:
        """Send an existing Gmail draft. Returns the sent message id."""
        if not self.is_authenticated():
            raise GmailNotAuthenticatedError(
                "Cannot send: Gmail client is not authenticated."
            )
        service = self._get_service()
        drafts = service.users().drafts()
        logger.info("Sending Gmail draft %s", draft_id)
        try:
            resp = drafts.send(userId="me", body={"id": draft_id}).execute()
        except HttpError as e:
            if _gmail_draft_send_failed_because_stale(e):
                raise GmailDraftNoLongerValidError(
                    "That Gmail draft was already sent or removed; nothing left to send."
                ) from e
            raise
        msg_id = (resp or {}).get("id")
        if not msg_id:
            raise RuntimeError(f"Gmail API response missing message id: {resp!r}")
        return msg_id

    def send_message(
        self,
        to: str,
        subject: str,
        body: str,
        attachment_path: Path | None = None,
        attachment_filename: str | None = None,
    ) -> str:
        """Send an email immediately. Returns the sent message id."""
        if not self.is_authenticated():
            raise GmailNotAuthenticatedError(
                "Cannot send: Gmail client is not authenticated."
            )

        msg = EmailMessage()
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)

        if attachment_path is not None:
            attachment_path = Path(attachment_path)
            if attachment_path.exists():
                fname = (attachment_filename or "").strip() or attachment_path.name
                fname = Path(fname).name
                mime_type, _ = mimetypes.guess_type(fname)
                if mime_type is None:
                    mime_type, _ = mimetypes.guess_type(attachment_path.name)
                if mime_type is None:
                    mime_type = "application/octet-stream"
                maintype, _, subtype = mime_type.partition("/")
                if not subtype:
                    maintype, subtype = "application", "octet-stream"
                data = attachment_path.read_bytes()
                msg.add_attachment(
                    data,
                    maintype=maintype,
                    subtype=subtype,
                    filename=fname,
                )
            else:
                logger.warning(
                    "Attachment path %s does not exist; skipping", attachment_path
                )

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service = self._get_service()
        messages = service.users().messages()
        logger.info("Sending Gmail message to=%s", to)
        resp = messages.send(userId="me", body={"raw": raw}).execute()
        msg_id = (resp or {}).get("id")
        if not msg_id:
            raise RuntimeError(f"Gmail API response missing message id: {resp!r}")
        return msg_id
