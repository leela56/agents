"""Tests for :mod:`app.gmail_client`. No real network calls are made."""

from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.gmail_client import (
    FileTokenStore,
    GmailClient,
    GmailNotAuthenticatedError,
)


class InMemoryTokenStore:
    def __init__(self, initial: str | None = None):
        self._data = initial

    def save_token(self, token_json: str) -> None:
        self._data = token_json

    def load_token(self) -> str | None:
        return self._data

    def clear_token(self) -> None:
        self._data = None


def _make_client(token: str | None = None) -> tuple[GmailClient, InMemoryTokenStore]:
    store = InMemoryTokenStore(initial=token)
    client = GmailClient(credentials_path=Path("credentials.json"), token_store=store)
    return client, store


def _decode_raw(raw_b64url: str) -> bytes:
    padding = "=" * (-len(raw_b64url) % 4)
    return base64.urlsafe_b64decode(raw_b64url + padding)


def test_file_token_store_roundtrip(tmp_path: Path) -> None:
    token_path = tmp_path / "nested" / "token.json"
    store = FileTokenStore(token_path)

    assert store.load_token() is None

    payload = '{"refresh_token": "abc", "token": "xyz"}'
    store.save_token(payload)

    assert token_path.exists()
    assert store.load_token() == payload


def test_is_authenticated_false_when_no_token() -> None:
    client, _ = _make_client(token=None)
    assert client.is_authenticated() is False


def test_create_draft_builds_correct_mime() -> None:
    client, _ = _make_client(token='{"refresh_token": "r"}')

    mock_service = MagicMock()
    created = {"id": "draft-123"}
    mock_service.users.return_value.drafts.return_value.create.return_value.execute.return_value = (
        created
    )

    with patch.object(GmailClient, "_get_service", return_value=mock_service), patch.object(
        GmailClient, "is_authenticated", return_value=True
    ):
        draft_id = client.create_or_update_draft(
            to="x@y.com",
            subject="Hi",
            body="Hello",
            attachment_path=None,
        )

    assert draft_id == "draft-123"

    create_call = mock_service.users.return_value.drafts.return_value.create
    create_call.assert_called_once()
    kwargs = create_call.call_args.kwargs
    assert kwargs["userId"] == "me"
    body = kwargs["body"]
    raw_b64 = body["message"]["raw"]
    mime_bytes = _decode_raw(raw_b64)
    mime_text = mime_bytes.decode("utf-8", errors="replace")
    assert "To: x@y.com" in mime_text
    assert "Subject: Hi" in mime_text
    assert "Hello" in mime_text


def test_create_draft_with_attachment(tmp_path: Path) -> None:
    client, _ = _make_client(token='{"refresh_token": "r"}')

    attachment = tmp_path / "greeting.txt"
    attachment.write_bytes(b"hello")

    mock_service = MagicMock()
    mock_service.users.return_value.drafts.return_value.create.return_value.execute.return_value = {
        "id": "draft-attach"
    }

    with patch.object(GmailClient, "_get_service", return_value=mock_service), patch.object(
        GmailClient, "is_authenticated", return_value=True
    ):
        draft_id = client.create_or_update_draft(
            to="a@b.com",
            subject="With attachment",
            body="See attached",
            attachment_path=attachment,
        )

    assert draft_id == "draft-attach"

    create_call = mock_service.users.return_value.drafts.return_value.create
    body = create_call.call_args.kwargs["body"]
    mime_bytes = _decode_raw(body["message"]["raw"])
    mime_text = mime_bytes.decode("utf-8", errors="replace")

    assert "greeting.txt" in mime_text
    assert "Content-Disposition: attachment" in mime_text


def test_update_uses_update_endpoint_when_id_given() -> None:
    client, _ = _make_client(token='{"refresh_token": "r"}')

    mock_service = MagicMock()
    drafts_ep = mock_service.users.return_value.drafts.return_value
    drafts_ep.update.return_value.execute.return_value = {"id": "abc"}

    with patch.object(GmailClient, "_get_service", return_value=mock_service), patch.object(
        GmailClient, "is_authenticated", return_value=True
    ):
        draft_id = client.create_or_update_draft(
            to="x@y.com",
            subject="Hi",
            body="Hello",
            existing_draft_id="abc",
        )

    assert draft_id == "abc"
    drafts_ep.update.assert_called_once()
    drafts_ep.create.assert_not_called()
    update_kwargs = drafts_ep.update.call_args.kwargs
    assert update_kwargs["userId"] == "me"
    assert update_kwargs["id"] == "abc"
    assert "raw" in update_kwargs["body"]["message"]


def test_create_draft_raises_when_not_authenticated() -> None:
    client, _ = _make_client(token=None)
    with pytest.raises(GmailNotAuthenticatedError):
        client.create_or_update_draft(to="x@y.com", subject="Hi", body="Hello")
