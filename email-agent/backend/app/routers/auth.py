"""Gmail OAuth2 authentication router.

Handles the OAuth2 flow with encrypted token storage and CSRF state validation.
"""

from __future__ import annotations

import secrets

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config import Settings, get_settings
from app.models import AuthStatusResponse
from app.security import TokenEncryptor

logger = structlog.get_logger()
router = APIRouter(prefix="/auth", tags=["Authentication"])

# In-memory CSRF state store with PKCE verifier (per-session in production, use Redis)
_oauth_states: dict[str, str | None] = {}


def _get_encryptor(settings: Settings = Depends(get_settings)) -> TokenEncryptor:
    return TokenEncryptor(settings.encryption_key)


def _build_flow(settings: Settings) -> Flow:
    """Build Google OAuth2 flow from settings."""
    client_config = {
        "web": {
            "client_id": settings.gmail_client_id,
            "client_secret": settings.gmail_client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [settings.gmail_redirect_uri],
        }
    }
    flow = Flow.from_client_config(
        client_config,
        scopes=settings.gmail_scopes,
        redirect_uri=settings.gmail_redirect_uri,
    )
    return flow


@router.get("/login")
async def login(settings: Settings = Depends(get_settings)) -> dict:
    """Initiate Gmail OAuth2 flow. Returns the authorization URL."""
    flow = _build_flow(settings)

    # Generate CSRF state token
    state = secrets.token_urlsafe(32)

    # Store the PKCE code verifier with the state
    # Google Auth library generates this automatically in authorization_url()
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        state=state,
        prompt="consent",
    )

    # Store state -> code_verifier mapping for callback
    _oauth_states[state] = flow.code_verifier

    logger.info("oauth_login_initiated", state_prefix=state[:8])
    return {"authorization_url": authorization_url}


@router.get("/callback")
async def callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    settings: Settings = Depends(get_settings),
) -> dict:
    """Handle OAuth2 callback. Encrypts and stores the token."""
    if error:
        logger.warning("oauth_callback_error", error=error)
        raise HTTPException(status_code=400, detail=f"OAuth error: {error}")

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing code or state parameter")

    # Validate CSRF state and retrieve code verifier
    if state not in _oauth_states:
        logger.warning("oauth_csrf_validation_failed")
        raise HTTPException(status_code=400, detail="Invalid state parameter (CSRF protection)")

    code_verifier = _oauth_states.pop(state)

    # Exchange code for token with PKCE verifier
    flow = _build_flow(settings)
    if code_verifier:
        flow.code_verifier = code_verifier
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        logger.exception("oauth_token_exchange_failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Token exchange failed. Make sure your GMAIL_CLIENT_SECRET is correct in .env. Error: {e}")
        
    credentials = flow.credentials

    # Encrypt and save token
    token_data = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": list(credentials.scopes) if credentials.scopes else [],
    }

    encryptor = TokenEncryptor(settings.encryption_key)
    encryptor.save_encrypted_token(token_data, settings.token_file)

    logger.info("oauth_callback_success")
    return {
        "status": "authenticated",
        "message": "Gmail connected successfully. You can close this window.",
    }


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(settings: Settings = Depends(get_settings)) -> AuthStatusResponse:
    """Check current Gmail authentication status."""
    encryptor = TokenEncryptor(settings.encryption_key)
    token_data = encryptor.load_encrypted_token(settings.token_file)

    if not token_data:
        return AuthStatusResponse(is_authenticated=False)

    try:
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
            creds.refresh(GoogleAuthRequest())
            # Re-save refreshed token
            token_data["token"] = creds.token
            encryptor.save_encrypted_token(token_data, settings.token_file)

        return AuthStatusResponse(
            is_authenticated=creds.valid,
            scopes=list(creds.scopes) if creds.scopes else [],
        )
    except Exception as e:
        logger.warning("auth_status_check_failed", error=str(e))
        return AuthStatusResponse(is_authenticated=False)


@router.post("/revoke")
async def revoke(settings: Settings = Depends(get_settings)) -> dict:
    """Revoke Gmail access and delete encrypted tokens."""
    encryptor = TokenEncryptor(settings.encryption_key)
    encryptor.delete_token(settings.token_file)
    logger.info("oauth_tokens_revoked")
    return {"status": "revoked", "message": "Gmail access revoked and tokens deleted."}
