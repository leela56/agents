"""Security utilities: token encryption, rate limiting, and input sanitization."""

from __future__ import annotations

import json
import re
from pathlib import Path

import structlog
from cryptography.fernet import Fernet, InvalidToken
from slowapi import Limiter
from slowapi.util import get_remote_address

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Rate Limiter (shared instance)
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)


# ---------------------------------------------------------------------------
# Token Encryption (Fernet — AES-128-CBC + HMAC-SHA256)
# ---------------------------------------------------------------------------
class TokenEncryptor:
    """Encrypts and decrypts OAuth tokens at rest using Fernet symmetric encryption.

    Fernet guarantees that a message encrypted using it cannot be manipulated
    or read without the key. It uses AES-128-CBC with PKCS7 padding and
    HMAC-SHA256 for authentication.
    """

    def __init__(self, encryption_key: str) -> None:
        try:
            self._fernet = Fernet(encryption_key.encode())
        except (ValueError, Exception) as e:
            msg = "Invalid encryption key. Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            raise ValueError(msg) from e

    def encrypt_token(self, token_data: dict) -> bytes:
        """Encrypt a token dictionary to bytes."""
        json_bytes = json.dumps(token_data).encode("utf-8")
        return self._fernet.encrypt(json_bytes)

    def decrypt_token(self, encrypted_data: bytes) -> dict:
        """Decrypt encrypted bytes back to a token dictionary."""
        try:
            decrypted = self._fernet.decrypt(encrypted_data)
            return json.loads(decrypted.decode("utf-8"))
        except InvalidToken:
            logger.error("token_decryption_failed", reason="invalid_key_or_corrupted_data")
            raise
        except json.JSONDecodeError:
            logger.error("token_decryption_failed", reason="invalid_json")
            raise

    def save_encrypted_token(self, token_data: dict, path: Path) -> None:
        """Encrypt and save token to file."""
        encrypted = self.encrypt_token(token_data)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(encrypted)
        logger.info("token_saved", path=str(path), encrypted=True)

    def load_encrypted_token(self, path: Path) -> dict | None:
        """Load and decrypt token from file. Returns None if file doesn't exist."""
        if not path.exists():
            logger.info("token_not_found", path=str(path))
            return None
        encrypted = path.read_bytes()
        token = self.decrypt_token(encrypted)
        logger.info("token_loaded", path=str(path))
        return token

    def delete_token(self, path: Path) -> None:
        """Securely delete token file."""
        if path.exists():
            # Overwrite with random bytes before deleting
            path.write_bytes(Fernet.generate_key())
            path.unlink()
            logger.info("token_deleted", path=str(path))


# ---------------------------------------------------------------------------
# Input Sanitization
# ---------------------------------------------------------------------------
def sanitize_html(text: str) -> str:
    """Strip HTML tags from text to prevent injection."""
    clean = re.sub(r"<[^>]+>", "", text)
    return clean.strip()


def truncate_string(text: str, max_length: int = 10000) -> str:
    """Truncate a string to a maximum length."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "... [truncated]"


def sanitize_email_body(body: str, max_length: int = 50000) -> str:
    """Sanitize and truncate email body text."""
    cleaned = sanitize_html(body)
    return truncate_string(cleaned, max_length)
