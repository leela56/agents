"""Business logic: polling, draft generation, resume management."""

from __future__ import annotations

import logging
import re
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select

from . import scraper
from .config import Settings, get_settings
from .db import get_session
from .gmail_client import (
    GmailClient,
    GmailDraftNoLongerValidError,
    GmailNotAuthenticatedError,
)
from .models import Draft, Job, RecruiterEmail, Resume, Setting


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------

def _set_kv(session, key: str, value: str) -> None:
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


def _get_kv(session, key: str) -> Optional[str]:
    row = session.get(Setting, key)
    return row.value if row else None


_TEMPLATE_KEYS = {
    "your_name": "template_your_name",
    "subject": "template_subject",
    "body": "template_body",
}


def get_template_overrides() -> dict:
    """Load template overrides from the DB."""
    with get_session() as session:
        return {
            "your_name": _get_kv(session, _TEMPLATE_KEYS["your_name"]) or "",
            "subject": _get_kv(session, _TEMPLATE_KEYS["subject"]) or "",
            "body": _get_kv(session, _TEMPLATE_KEYS["body"]) or "",
        }


def set_template_overrides(*, your_name: str, subject: str, body: str) -> None:
    with get_session() as session:
        _set_kv(session, _TEMPLATE_KEYS["your_name"], your_name.strip())
        _set_kv(session, _TEMPLATE_KEYS["subject"], subject.strip())
        _set_kv(session, _TEMPLATE_KEYS["body"], body.strip())


def set_your_name_override(your_name: str) -> None:
    """Update only the signature / ``{your_name}`` value in the template store."""
    settings = get_settings()
    o = get_template_overrides()
    set_template_overrides(
        your_name=your_name.strip(),
        subject=o["subject"] or settings.default_subject,
        body=o["body"] or settings.default_body,
    )


def should_autofill_name_from_google(settings: Settings) -> bool:
    """True when the user has not set a name in Settings DB and env still uses the default."""
    if get_template_overrides()["your_name"].strip():
        return False
    return is_placeholder_signoff_name(settings.your_name or "")


def resolved_template(settings: Settings) -> tuple[str, str, str]:
    """Return (your_name, subject, body_template), applying DB overrides."""
    overrides = get_template_overrides()
    your_name = overrides["your_name"] or settings.your_name
    subject = overrides["subject"] or settings.default_subject
    body = overrides["body"] or settings.default_body
    return your_name, subject, body


def _resolved_keywords(settings: Settings) -> list[str]:
    if settings.keywords:
        return settings.keywords
    return scraper.DEFAULT_KEYWORDS


def _render_body(settings: Settings, *, body_template: str, your_name: str) -> str:
    try:
        return body_template.format(your_name=your_name)
    except (KeyError, IndexError):
        # Template had stray braces - fall back to raw string.
        return body_template.replace("{your_name}", your_name)


def is_placeholder_signoff_name(name: str) -> bool:
    """True when the user has not set a real sign-off name (env default or empty)."""
    s = (name or "").strip().lower()
    return not s or s == "your name"


def resolve_signoff_for_draft_ui(
    settings: Settings, gmail: GmailClient | None = None
) -> tuple[str, str]:
    """Return ``(signoff_name, source)`` for rendering drafts.

    ``source`` is ``\"settings\"`` when the template has a real name, ``\"google\"`` when
    we filled it from the connected account, or ``\"default\"`` when still unset.
    """
    yn, _, _ = resolved_template(settings)
    yn = yn.strip()
    if not is_placeholder_signoff_name(yn):
        return yn, "settings"
    if gmail is not None and gmail.is_authenticated():
        fetched = (gmail.fetch_user_display_name() or "").strip()
        if fetched and not is_placeholder_signoff_name(fetched):
            return fetched, "google"
    return yn, "default"


def _line_is_placeholder_signoff(line: str) -> bool:
    """Match ``Your Name``, ``**Your Name**``, etc. on the sign-off line."""
    t = (line or "").strip()
    if t.lower() == "your name":
        return True
    core = re.sub(r"[\s*_`]+", "", t).lower().rstrip(".")
    return core == "yourname"


def body_for_display_with_signature(
    body: str,
    settings: Settings | None = None,
    *,
    signoff_name: str | None = None,
) -> str:
    """Show the correct sign-off when drafts still say ``Your Name`` or ``{your_name}``.

    Pass ``signoff_name`` from :func:`resolve_signoff_for_draft_ui` (with Gmail) so the
    Google profile name can replace the default before the user saves Settings.
    """
    settings = settings or get_settings()
    if signoff_name is not None:
        yn = signoff_name.strip()
    else:
        yn, _ = resolve_signoff_for_draft_ui(settings, None)
    if is_placeholder_signoff_name(yn):
        return body
    try:
        text = body.format(your_name=yn)
    except (KeyError, IndexError):
        text = body.replace("{your_name}", yn)
    lines = text.split("\n")
    i = len(lines) - 1
    while i >= 0 and lines[i].strip() == "":
        i -= 1
    if i >= 0 and _line_is_placeholder_signoff(lines[i]):
        lines[i] = yn
    return "\n".join(lines)


_GENERIC_EMAIL_LOCALS = {
    "hr",
    "recruiting",
    "recruiter",
    "jobs",
    "careers",
    "talent",
    "talentacquisition",
    "ta",
    "hiring",
    "staffing",
    "admin",
    "info",
    "hello",
    "support",
    "noreply",
    "no-reply",
}


def _infer_display_name_from_email(email: str) -> str:
    """Best-effort display name from the Gmail/email local-part (e.g. shivam.singh -> Shivam Singh)."""
    if not email or "@" not in email:
        return ""
    local = email.split("@", 1)[0].strip().lower()
    if not local:
        return ""
    if local in _GENERIC_EMAIL_LOCALS:
        return ""
    local = local.split("+", 1)[0]
    raw_parts = [p for p in re.split(r"[._\-]+", local) if p]
    if not raw_parts:
        return ""
    if raw_parts[0] in _GENERIC_EMAIL_LOCALS:
        return ""
    if any(ch.isdigit() for ch in raw_parts[0]):
        return ""

    display_parts: list[str] = []
    for i, p in enumerate(raw_parts):
        if not p:
            continue
        if len(p) == 1 and len(raw_parts) > 1:
            display_parts.append(p.upper())
            continue
        if len(p) < 2 and len(raw_parts) == 1:
            return ""
        if any(ch.isdigit() for ch in p):
            return ""
        display_parts.append(p[:1].upper() + p[1:].lower())

    if not display_parts:
        return ""
    return " ".join(display_parts)


def personalize_greeting_for_recruiter(body: str, recruiter_email: str) -> str:
    """Public wrapper: personalize leading Hi / Hi there when a name can be inferred."""
    return _maybe_personalize_greeting(body, recruiter_email)


def _maybe_personalize_greeting(body: str, recruiter_email: str) -> str:
    """Replace leading 'Hi,' with 'Hi <Name>,' when it looks safe."""
    name = _infer_display_name_from_email(recruiter_email)
    if not name:
        return body
    # Only touch the very first greeting line, and only for common variants.
    patterns = [
        r"^\s*Hi\s*,",
        r"^\s*Hi\s*$",
        r"^\s*Hi\s+there\s*,",
    ]
    for pat in patterns:
        if re.search(pat, body, flags=re.IGNORECASE | re.MULTILINE):
            return re.sub(
                pat,
                f"Hi {name},",
                body,
                count=1,
                flags=re.IGNORECASE | re.MULTILINE,
            )
    return body


def run_poll_once() -> dict:
    """Fetch the search page, upsert jobs, and create drafts for new matches.

    Idempotent: dedupes on ``Job.job_id`` and the (job_fk, email) unique
    constraint on ``RecruiterEmail``. Safe to call on a schedule.
    """
    settings = get_settings()
    keywords = _resolved_keywords(settings)
    your_name, subject, body_template = resolved_template(settings)

    summary = {"seen": 0, "new": 0, "matched": 0, "drafts_created": 0}
    now = datetime.utcnow()

    try:
        listings = scraper.fetch_search_results(
            settings.search_url, search_val=settings.search_val
        )
    except Exception:
        logger.exception("fetch_search_results failed")
        raise

    with get_session() as session:
        for listing in listings:
            summary["seen"] += 1
            is_new = False

            # "Hotlist" rows are recruiter bench postings, not job requirements.
            # Skip them outright so they never count as matches.
            if (listing.title or "").strip().lower().startswith("hotlist"):
                continue

            job = session.scalar(select(Job).where(Job.job_id == listing.job_id))
            if job is None:
                job = Job(
                    job_id=listing.job_id,
                    uid=listing.uid or "",
                    title=listing.title or "",
                    location=listing.location or "",
                    posted_at=listing.posted_at or "",
                    url=listing.url or "",
                    first_seen_at=now,
                    last_seen_at=now,
                )
                session.add(job)
                session.flush()
                is_new = True
                summary["new"] += 1
            else:
                job.last_seen_at = now
                # Keep metadata fresh in case anything changed.
                job.title = listing.title or job.title
                job.location = listing.location or job.location
                job.posted_at = listing.posted_at or job.posted_at
                job.url = listing.url or job.url

            if job.processed:
                continue

            if not scraper.is_match(job.title or "", keywords):
                continue

            job.matched = True

            # Fetch details for emails.
            try:
                details = scraper.fetch_job_details(job.url)
            except Exception as exc:
                logger.warning("fetch_job_details failed for %s: %s", job.url, exc)
                continue

            emails = _unique_preserve_order(details.emails or [])
            if not emails:
                # Still mark matched; no way to make a draft without a recipient.
                job.processed = True
                summary["matched"] += 1
                continue

            for email in emails:
                exists = session.scalar(
                    select(RecruiterEmail).where(
                        RecruiterEmail.job_fk == job.id,
                        RecruiterEmail.email == email,
                    )
                )
                if exists is None:
                    session.add(RecruiterEmail(job_fk=job.id, email=email))

            # Create a draft for the first email only (the rest are stored for reference).
            primary_email = emails[0]
            has_draft = session.scalar(
                select(Draft).where(
                    Draft.job_fk == job.id,
                    Draft.recruiter_email == primary_email,
                )
            )
            if has_draft is None:
                draft = Draft(
                    job_fk=job.id,
                    recruiter_email=primary_email,
                    subject=subject,
                    body=_maybe_personalize_greeting(
                        _render_body(
                            settings,
                            body_template=body_template,
                            your_name=your_name,
                        ),
                        recruiter_email=primary_email,
                    ),
                    status="pending",
                )
                session.add(draft)
                summary["drafts_created"] += 1

            job.matched = True
            job.processed = True
            summary["matched"] += 1

            if is_new:
                # new+matched already counted in "new"; no-op, kept explicit.
                pass

        _set_kv(session, "last_poll_at", now.isoformat(timespec="seconds") + "Z")
        _set_kv(session, "last_poll_summary", _fmt_summary(summary))

    logger.info("poll complete: %s", summary)
    return summary


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item.strip())
    return out


def _fmt_summary(s: dict) -> str:
    return ", ".join(f"{k}={v}" for k, v in s.items())


# ---------------------------------------------------------------------------
# Drafts -> Gmail
# ---------------------------------------------------------------------------


def update_draft_content(draft_id: int, to: str, subject: str, body: str) -> bool:
    """Update draft fields. Returns False if draft does not exist."""
    with get_session() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            return False
        draft.recruiter_email = to.strip()
        draft.subject = subject
        draft.body = personalize_greeting_for_recruiter(
            body.strip(), draft.recruiter_email
        )
        if draft.status == "error":
            draft.status = "pending"
            draft.error = None
    return True


def push_draft_to_gmail(
    draft_id: int,
    settings: Settings,
    gmail: GmailClient,
    *,
    override_resume: tuple[Path, str] | None = None,
) -> None:
    """Push a local Draft up to Gmail as a real draft message.

    ``override_resume`` is ``(path, attachment_filename)`` for a one-off attachment
    (e.g. from the jobs-page modal). Otherwise the active Settings resume is used.

    Updates status/error in place. Never raises - all errors are captured on the row.
    """
    with get_session() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            return

        if override_resume is not None:
            attachment, attach_name = override_resume
            attachment = Path(attachment)
            if not attachment.exists():
                draft.status = "error"
                draft.error = "Temporary resume file missing"
                return
        else:
            resume_row = get_active_resume()
            attachment = get_active_resume_path()
            attach_name = None
            if resume_row and (resume_row.filename or "").strip():
                attach_name = friendly_resume_attachment_name(resume_row.filename)

        try:
            gmail_id = gmail.create_or_update_draft(
                to=draft.recruiter_email,
                subject=draft.subject,
                body=draft.body,
                attachment_path=attachment,
                attachment_filename=attach_name,
                existing_draft_id=draft.gmail_draft_id,
            )
            draft.gmail_draft_id = gmail_id
            draft.status = "pushed"
            draft.error = None
        except GmailNotAuthenticatedError:
            draft.status = "error"
            draft.error = "not_authenticated"
        except Exception as exc:  # noqa: BLE001 - we want to persist any error text
            draft.status = "error"
            draft.error = str(exc)


def _gmail_draft_obsolete_or_already_sent(exc: BaseException) -> bool:
    """Gmail returns this when the stored draft id was sent or deleted outside our app."""
    try:
        from googleapiclient.errors import HttpError as GmailHttpError
    except ImportError:  # pragma: no cover
        GmailHttpError = None  # type: ignore

    if GmailHttpError is not None and isinstance(exc, GmailHttpError) and exc.resp is not None:
        try:
            status = int(getattr(exc.resp, "status", 0) or 0)
        except (TypeError, ValueError):
            status = 0
        if status in (400, 404):
            raw = getattr(exc, "content", b"") or b""
            blob = raw.decode("utf-8", errors="ignore").lower() if isinstance(raw, bytes) else str(raw).lower()
            if "not a draft" in blob or "message not a draft" in blob:
                return True
            if status == 404 and "not found" in blob:
                return True
    low = str(exc).lower()
    if "message not a draft" in low:
        return True
    if "not a draft" in low and "400" in low:
        return True
    return False


def send_draft_via_gmail(
    draft_id: int,
    settings: Settings,
    gmail: GmailClient,
    *,
    override_resume: tuple[Path, str] | None = None,
) -> None:
    """Send a draft email via Gmail.

    If the draft has already been pushed to Gmail, we send that Gmail draft.
    Otherwise we send the message directly.

    When ``override_resume`` is set, always sends a fresh message with that
    attachment (bypasses any existing Gmail draft id).
    """
    with get_session() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            return

        try:
            if override_resume is not None:
                path, display = override_resume
                attachment = Path(path)
                if not attachment.exists():
                    draft.status = "error"
                    draft.error = "Temporary resume file missing"
                    return
                gmail.send_message(
                    to=draft.recruiter_email,
                    subject=draft.subject,
                    body=draft.body,
                    attachment_path=attachment,
                    attachment_filename=display,
                )
            elif draft.gmail_draft_id:
                gmail.send_draft(draft.gmail_draft_id)
            else:
                resume_row = get_active_resume()
                attachment = get_active_resume_path()
                attach_name = None
                if resume_row and (resume_row.filename or "").strip():
                    attach_name = friendly_resume_attachment_name(resume_row.filename)
                gmail.send_message(
                    to=draft.recruiter_email,
                    subject=draft.subject,
                    body=draft.body,
                    attachment_path=attachment,
                    attachment_filename=attach_name,
                )
            draft.status = "sent"
            draft.error = None
        except GmailNotAuthenticatedError:
            draft.status = "error"
            draft.error = "not_authenticated"
        except GmailDraftNoLongerValidError:
            draft.status = "sent"
            draft.error = None
            draft.gmail_draft_id = None
            logger.info(
                "draft %s: Gmail draft already sent or removed; marked sent.",
                draft_id,
            )
        except Exception as exc:  # noqa: BLE001
            if _gmail_draft_obsolete_or_already_sent(exc):
                # Draft was sent or removed in Gmail; our id is stale — align local state.
                draft.status = "sent"
                draft.error = None
                draft.gmail_draft_id = None
                logger.info(
                    "draft %s: Gmail draft no longer sendable (%s); marked sent.",
                    draft_id,
                    type(exc).__name__,
                )
            else:
                draft.status = "error"
                draft.error = str(exc)

# ---------------------------------------------------------------------------
# Resume management
# ---------------------------------------------------------------------------

_ALLOWED_RESUME_MIME = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}
_ALLOWED_RESUME_EXT = {".pdf", ".doc", ".docx"}

_MAX_EPHEMERAL_RESUME_BYTES = 15 * 1024 * 1024


def save_temporary_resume_bytes(content: bytes, original_filename: str) -> tuple[Path, str]:
    """Write bytes to a temp file under ``resume_dir/_tmp``. Caller must delete the path.

    Returns ``(path, attachment_filename)`` for Gmail. Raises ``ValueError`` if invalid type/size.
    """
    if len(content) > _MAX_EPHEMERAL_RESUME_BYTES:
        raise ValueError("Resume file too large (max 15 MB).")

    name = Path(original_filename or "resume").name
    ext = Path(name).suffix.lower()
    if ext not in _ALLOWED_RESUME_EXT:
        raise ValueError(f"Unsupported resume type: {name!r}")

    settings = get_settings()
    tmp_dir = Path(settings.resume_dir) / "_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    dest = tmp_dir / f"{uuid.uuid4().hex}{ext}"
    dest.write_bytes(content)
    display = friendly_resume_attachment_name(name)
    return dest, display


def get_active_resume_path() -> Optional[Path]:
    with get_session() as session:
        row = session.scalar(select(Resume).where(Resume.active == True))  # noqa: E712
        if row is None:
            return None
        path = Path(row.stored_path)
        return path if path.exists() else None


def get_active_resume() -> Optional[Resume]:
    with get_session() as session:
        row = session.scalar(select(Resume).where(Resume.active == True))  # noqa: E712
        if row is None:
            return None
        session.expunge(row)
        return row


def save_uploaded_resume(upload_file) -> Resume:
    """Persist a FastAPI ``UploadFile`` to disk and mark it as the active resume.

    Raises ``ValueError`` for unsupported file types.
    """
    settings = get_settings()

    original_name = Path(upload_file.filename or "resume").name
    ext = Path(original_name).suffix.lower()
    mime = (getattr(upload_file, "content_type", "") or "").lower()

    if ext not in _ALLOWED_RESUME_EXT and mime not in _ALLOWED_RESUME_MIME:
        raise ValueError(f"Unsupported resume type: {original_name!r} ({mime})")

    resume_dir = Path(settings.resume_dir)
    resume_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    safe_name = _safe_filename(original_name)
    stored_path = resume_dir / f"{ts}_{safe_name}"

    with stored_path.open("wb") as out:
        # UploadFile has an underlying file-like object at ``.file``.
        src = getattr(upload_file, "file", None)
        if src is not None:
            src.seek(0)
            shutil.copyfileobj(src, out)
        else:  # pragma: no cover - defensive
            out.write(upload_file.read())

    with get_session() as session:
        for other in session.scalars(select(Resume).where(Resume.active == True)):  # noqa: E712
            other.active = False

        resume = Resume(
            filename=friendly_resume_attachment_name(original_name),
            stored_path=str(stored_path),
            mime_type=mime or _guess_mime(ext),
            active=True,
        )
        session.add(resume)
        session.flush()
        session.refresh(resume)
        session.expunge(resume)
        return resume


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-")
    return cleaned or "resume"


# Our on-disk uploads look like: 20260423-185648_Leela_Kiran_Resume.docx
_INTERNAL_RESUME_STEM_PREFIX = re.compile(r"^\d{8}-\d{6}_")


def friendly_resume_attachment_name(name: str) -> str:
    """Filename shown in Gmail / Settings: drop internal timestamp prefix and un-mangle underscores.

    If the user re-uploads a file from our resume folder, the browser often sends
    the disk basename; this turns it back into a human attachment name.
    """
    n = (name or "").strip()
    if not n:
        return ""
    n = Path(n).name
    if _INTERNAL_RESUME_STEM_PREFIX.match(n):
        n = _INTERNAL_RESUME_STEM_PREFIX.sub("", n)
    stem, suf = Path(n).stem, Path(n).suffix
    if "_" in stem and " " not in stem:
        stem = stem.replace("_", " ")
    return f"{stem}{suf}"


def _guess_mime(ext: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".doc": "application/msword",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }.get(ext, "application/octet-stream")
