"""FastAPI entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlencode

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from . import scraper, services
from .config import get_settings
from .db import get_session, init_db
from .gmail_client import GmailClient
from .models import Draft, Job, Resume, Setting
from .scheduler import start_scheduler, stop_scheduler
from .token_store import DBTokenStore


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _default_nav_user_dict() -> dict:
    return {"authed": False, "name": "", "email": "", "picture": ""}


def _nav_user_for_template(request: Request) -> dict:
    """Safe read for base layout (Starlette ``State`` has no ``.get()``)."""
    return getattr(request.state, "nav_user", _default_nav_user_dict())


templates.env.globals["nav_user_for_template"] = _nav_user_for_template


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()

    app.state.settings = settings
    app.state.gmail = GmailClient(
        credentials_path=Path(settings.credentials_path),
        token_store=DBTokenStore(),
    )

    try:
        start_scheduler(app)
    except Exception:
        logger.exception("failed to start scheduler")

    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title="nvoids Job Agent", lifespan=lifespan)

# Register before /static mount so this path always wins. GET + HEAD (some clients probe HEAD).
_FAVICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    b'<rect width="32" height="32" rx="6" fill="#5aa9ff"/>'
    b'<text x="16" y="22" text-anchor="middle" fill="#0b0e14" font-size="14" '
    b'font-family="system-ui,sans-serif" font-weight="700">N</text></svg>'
)


@app.api_route("/favicon.ico", methods=["GET", "HEAD"], include_in_schema=False)
def favicon(request: Request) -> Response:
    headers = {
        "Cache-Control": "public, max-age=86400",
        "Content-Length": str(len(_FAVICON_SVG)),
    }
    if request.method == "HEAD":
        return Response(status_code=200, media_type="image/svg+xml", headers=headers)
    return Response(content=_FAVICON_SVG, media_type="image/svg+xml", headers=headers)


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flash_redirect(path: str, msg: str, level: str = "info") -> RedirectResponse:
    qs = urlencode({"msg": msg, "level": level})
    sep = "&" if "?" in path else "?"
    return RedirectResponse(url=f"{path}{sep}{qs}", status_code=303)


def _flash_from_request(request: Request) -> Optional[dict]:
    msg = request.query_params.get("msg")
    if not msg:
        return None
    return {"msg": msg, "level": request.query_params.get("level", "info")}


def _gmail(request: Request) -> GmailClient:
    """Return the app-scoped Gmail client, or a fresh instance if lifespan did not run.

    Some ASGI hosts / tests call routes without executing ``lifespan``, which leaves
    ``app.state.gmail`` unset and would otherwise raise ``AttributeError`` (500).
    """
    client = getattr(request.app.state, "gmail", None)
    if client is not None:
        return client
    settings = get_settings()
    return GmailClient(
        credentials_path=Path(settings.credentials_path),
        token_store=DBTokenStore(),
    )


@app.middleware("http")
async def nav_profile_middleware(request: Request, call_next):
    """Expose Gmail / Google profile for the header (avatar, Settings menu)."""
    nav: dict = {"authed": False, "name": "", "email": "", "picture": ""}
    try:
        g = _gmail(request)
        if g.is_authenticated():
            nav["authed"] = True
            info = g.fetch_user_info()
            if info:
                nav["name"] = (info.get("name") or "").strip()
                nav["email"] = (info.get("email") or "").strip()
                nav["picture"] = (info.get("picture") or "").strip()
            # OAuth tokens sometimes lack userinfo.email; Gmail API still returns address.
            if not nav["email"]:
                gmail_email = g.fetch_gmail_me_email()
                if gmail_email:
                    nav["email"] = gmail_email
    except Exception:  # noqa: BLE001 — header must not break the app
        pass
    request.state.nav_user = nav
    return await call_next(request)


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    settings = get_settings()
    gmail = _gmail(request)

    with get_session() as session:
        total_jobs = session.scalar(select(func.count(Job.id))) or 0
        matched_jobs = session.scalar(
            select(func.count(Job.id)).where(Job.matched == True)  # noqa: E712
        ) or 0
        pending_drafts = session.scalar(
            select(func.count(Draft.id)).where(Draft.status == "pending")
        ) or 0
        pushed_drafts = session.scalar(
            select(func.count(Draft.id)).where(Draft.status == "pushed")
        ) or 0

        last_poll_row = session.get(Setting, "last_poll_at")
        last_summary_row = session.get(Setting, "last_poll_summary")
        last_poll = last_poll_row.value if last_poll_row else None
        last_summary = last_summary_row.value if last_summary_row else None

        if not last_poll:
            latest = session.scalar(select(func.max(Job.last_seen_at)))
            last_poll = latest.isoformat(timespec="seconds") + "Z" if latest else None

        active_resume = session.scalar(
            select(Resume).where(Resume.active == True)  # noqa: E712
        )
        resume_info = None
        if active_resume is not None:
            resume_info = {
                "filename": services.friendly_resume_attachment_name(
                    active_resume.filename
                ),
                "uploaded_at": active_resume.uploaded_at,
            }

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "flash": _flash_from_request(request),
            "settings": settings,
            "total_jobs": total_jobs,
            "matched_jobs": matched_jobs,
            "pending_drafts": pending_drafts,
            "pushed_drafts": pushed_drafts,
            "last_poll": last_poll,
            "last_summary": last_summary,
            "resume_info": resume_info,
            "gmail_authed": gmail.is_authenticated(),
        },
    )


@app.post("/run-now")
def run_now():
    try:
        summary = services.run_poll_once()
        msg = (
            f"Poll complete - seen {summary['seen']}, new {summary['new']}, "
            f"matched {summary['matched']}, drafts {summary['drafts_created']}"
        )
        return _flash_redirect("/", msg, level="success")
    except Exception as exc:  # noqa: BLE001
        logger.exception("manual poll failed")
        return _flash_redirect("/", f"Poll failed: {exc}", level="error")


# ---------------------------------------------------------------------------
# Jobs
# ---------------------------------------------------------------------------

@app.get("/jobs", response_class=HTMLResponse)
def jobs_list(request: Request):
    with get_session() as session:
        rows = (
            session.execute(
                select(Job)
                .where(Job.matched == True)  # noqa: E712
                .order_by(Job.job_id.desc(), Job.first_seen_at.desc())
                .limit(200)
            )
            .scalars()
            .all()
        )
        jobs_view = []
        for job in rows:
            drafts = session.execute(
                select(Draft).where(Draft.job_fk == job.id).order_by(Draft.created_at.desc())
            ).scalars().all()
            jobs_view.append(
                {
                    "id": job.id,
                    "title": job.title,
                    "location": job.location,
                    "posted_at": job.posted_at,
                    "url": job.url,
                    "last_seen_at": job.last_seen_at,
                    "drafts": [
                        {
                            "id": d.id,
                            "recruiter_email": d.recruiter_email,
                            "status": d.status,
                        }
                        for d in drafts
                    ],
                }
            )

    return templates.TemplateResponse(
        request,
        "jobs.html",
        {
            "flash": _flash_from_request(request),
            "jobs": jobs_view,
            "gmail_authed": _gmail(request).is_authenticated(),
            "has_resume": services.get_active_resume_path() is not None,
        },
    )


class DraftJsonUpdate(BaseModel):
    to: str
    subject: str
    body: str


@app.get("/api/drafts/{draft_id}", name="draft_api_get")
def draft_api_get(request: Request, draft_id: int) -> JSONResponse:
    with get_session() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        job = session.get(Job, draft.job_fk)
        job_title = job.title if job else ""
        job_id = job.id if job else None
        jd_url = (
            str(request.url_for("job_description", job_id=job.id))
            if job is not None
            else None
        )
        settings = get_settings()
        sn_name, sn_src = services.resolve_signoff_for_draft_ui(
            settings, _gmail(request)
        )
        body_display = services.body_for_display_with_signature(
            draft.body, settings, signoff_name=sn_name
        )
        payload = {
            "id": draft.id,
            "to": draft.recruiter_email,
            "subject": draft.subject,
            "body": body_display,
            "status": draft.status,
            "job_title": job_title,
            "job_id": job_id,
            "job_description_url": jd_url,
            "gmail_draft_id": draft.gmail_draft_id,
            "error": draft.error,
            "signoff_source": sn_src,
        }
    return JSONResponse(payload)


@app.patch("/api/drafts/{draft_id}", name="draft_api_patch")
def draft_api_patch(draft_id: int, payload: DraftJsonUpdate) -> JSONResponse:
    ok = services.update_draft_content(
        draft_id, payload.to, payload.subject, payload.body
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Draft not found")
    return JSONResponse({"ok": True})


@app.post("/api/drafts/{draft_id}/push", name="draft_api_push")
async def draft_api_push(
    request: Request,
    draft_id: int,
    to: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    resume: UploadFile | None = File(None),
) -> JSONResponse:
    settings = get_settings()
    gmail = _gmail(request)

    has_file = resume is not None and bool((resume.filename or "").strip())
    if not has_file and services.get_active_resume_path() is None:
        return JSONResponse(
            {
                "ok": False,
                "error": "No resume on file. Upload one in Settings or attach a file below.",
            },
            status_code=400,
        )

    tmp_path: Path | None = None
    override: tuple[Path, str] | None = None
    try:
        if has_file:
            raw = await resume.read()
            try:
                path, display = services.save_temporary_resume_bytes(
                    raw, resume.filename or "resume"
                )
            except ValueError as exc:
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
            tmp_path = path
            override = (path, display)

        if not services.update_draft_content(draft_id, to, subject, body):
            return JSONResponse({"ok": False, "error": "Draft not found."}, status_code=404)

        services.push_draft_to_gmail(
            draft_id, settings, gmail, override_resume=override
        )
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    with get_session() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            return JSONResponse({"ok": False, "error": "Draft not found."}, status_code=404)
        if draft.status == "pushed":
            return JSONResponse(
                {
                    "ok": True,
                    "status": draft.status,
                    "message": f"Pushed to Gmail (draft id={draft.gmail_draft_id})",
                    "gmail_draft_id": draft.gmail_draft_id,
                }
            )
        if draft.error == "not_authenticated":
            return JSONResponse(
                {
                    "ok": False,
                    "status": draft.status,
                    "error": "Gmail not connected — open Settings and connect.",
                },
                status_code=401,
            )
        return JSONResponse(
            {
                "ok": False,
                "status": draft.status,
                "error": draft.error or "Push failed",
            },
            status_code=502,
        )


@app.post("/api/drafts/{draft_id}/send", name="draft_api_send")
async def draft_api_send(
    request: Request,
    draft_id: int,
    to: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    resume: UploadFile | None = File(None),
) -> JSONResponse:
    settings = get_settings()
    gmail = _gmail(request)

    with get_session() as session:
        existing = session.get(Draft, draft_id)
        if existing is None:
            return JSONResponse({"ok": False, "error": "Draft not found."}, status_code=404)
        if existing.status == "sent":
            return JSONResponse(
                {"ok": False, "error": "This draft was already sent."},
                status_code=400,
            )

    has_file = resume is not None and bool((resume.filename or "").strip())
    if not has_file and services.get_active_resume_path() is None:
        return JSONResponse(
            {
                "ok": False,
                "error": "No resume on file. Upload one in Settings or attach a file below.",
            },
            status_code=400,
        )

    tmp_path: Path | None = None
    override: tuple[Path, str] | None = None
    try:
        if has_file:
            raw = await resume.read()
            try:
                path, display = services.save_temporary_resume_bytes(
                    raw, resume.filename or "resume"
                )
            except ValueError as exc:
                return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
            tmp_path = path
            override = (path, display)

        if not services.update_draft_content(draft_id, to, subject, body):
            return JSONResponse({"ok": False, "error": "Draft not found."}, status_code=404)

        services.send_draft_via_gmail(
            draft_id, settings, gmail, override_resume=override
        )
    finally:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass

    with get_session() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            return JSONResponse({"ok": False, "error": "Draft not found."}, status_code=404)
        if draft.status == "sent":
            return JSONResponse(
                {
                    "ok": True,
                    "status": draft.status,
                    "message": "Email sent via Gmail.",
                }
            )
        if draft.error == "not_authenticated":
            return JSONResponse(
                {
                    "ok": False,
                    "status": draft.status,
                    "error": "Gmail not connected — open Settings and connect.",
                },
                status_code=401,
            )
        return JSONResponse(
            {
                "ok": False,
                "status": draft.status,
                "error": draft.error or "Send failed",
            },
            status_code=502,
        )


def _job_description_payload(job_id: int) -> JSONResponse:
    """Fetch live job text from nvoids for the jobs page side panel."""
    with get_session() as session:
        job = session.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        url = (job.url or "").strip()
        title_fb = job.title or ""
        location_fb = job.location or ""

    if not url:
        return JSONResponse(
            {
                "title": title_fb,
                "location": location_fb,
                "body": "",
                "url": "",
                "error": "This job has no listing URL.",
            },
            status_code=200,
        )

    try:
        details = scraper.fetch_job_details(url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("fetch_job_details failed for job %s: %s", job_id, exc)
        return JSONResponse(
            {
                "title": title_fb,
                "location": location_fb,
                "body": "",
                "url": url,
                "error": f"Could not load listing: {exc}",
            },
            status_code=502,
        )

    body = (details.raw_text or "").strip()
    return JSONResponse(
        {
            "title": details.title or title_fb,
            "location": details.location or location_fb,
            "body": body,
            "url": url,
            "error": None,
        }
    )


@app.get("/api/jobs/{job_id}/description", name="job_description")
def job_description_api(job_id: int) -> JSONResponse:
    return _job_description_payload(job_id)


@app.get("/jobs/{job_id}/preview", name="job_preview")
def job_preview_json(job_id: int) -> JSONResponse:
    """Same JSON as /api/...; alternate path if /api is blocked or misrouted."""
    return _job_description_payload(job_id)


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------

@app.get("/drafts/{draft_id}", response_class=HTMLResponse)
def draft_view(request: Request, draft_id: int):
    with get_session() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        job = session.get(Job, draft.job_fk)
        jd_url = (
            str(request.url_for("job_description", job_id=job.id))
            if job is not None
            else None
        )
        settings = get_settings()
        sn_name, sn_src = services.resolve_signoff_for_draft_ui(
            settings, _gmail(request)
        )
        body_display = services.body_for_display_with_signature(
            draft.body, settings, signoff_name=sn_name
        )
        view = {
            "id": draft.id,
            "to": draft.recruiter_email,
            "subject": draft.subject,
            "body": body_display,
            "status": draft.status,
            "gmail_draft_id": draft.gmail_draft_id,
            "error": draft.error,
            "created_at": draft.created_at,
            "updated_at": draft.updated_at,
            "signoff_source": sn_src,
            "job": {
                "id": job.id if job else None,
                "title": job.title if job else "",
                "url": job.url if job else "",
            },
        }
    return templates.TemplateResponse(
        request,
        "draft.html",
        {
            "flash": _flash_from_request(request),
            "draft": view,
            "job_description_url": jd_url,
            "gmail_authed": _gmail(request).is_authenticated(),
            "has_resume": services.get_active_resume_path() is not None,
        },
    )


@app.post("/drafts/{draft_id}")
def draft_save(
    draft_id: int,
    to: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
):
    if not services.update_draft_content(draft_id, to, subject, body):
        raise HTTPException(status_code=404, detail="Draft not found")
    return _flash_redirect(f"/drafts/{draft_id}", "Draft saved", level="success")


@app.post("/drafts/{draft_id}/push")
def draft_push(request: Request, draft_id: int):
    settings = get_settings()
    gmail = _gmail(request)

    services.push_draft_to_gmail(draft_id, settings, gmail)

    with get_session() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        if draft.status == "pushed":
            msg = f"Pushed to Gmail (id={draft.gmail_draft_id})"
            level = "success"
        elif draft.error == "not_authenticated":
            msg = "Gmail not connected - visit Settings to connect."
            level = "error"
        else:
            msg = f"Push failed: {draft.error}"
            level = "error"

    return _flash_redirect(f"/drafts/{draft_id}", msg, level=level)


@app.post("/drafts/{draft_id}/send")
def draft_send(request: Request, draft_id: int):
    settings = get_settings()
    gmail = _gmail(request)

    if services.get_active_resume_path() is None:
        return _flash_redirect(
            f"/drafts/{draft_id}",
            "No resume uploaded yet - upload one on Settings before sending.",
            level="error",
        )

    services.send_draft_via_gmail(draft_id, settings, gmail)

    with get_session() as session:
        draft = session.get(Draft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail="Draft not found")
        if draft.status == "sent":
            msg = "Email sent via Gmail."
            level = "success"
        elif draft.error == "not_authenticated":
            msg = "Gmail not connected - visit Settings to connect."
            level = "error"
        else:
            msg = f"Send failed: {draft.error}"
            level = "error"

    return _flash_redirect(f"/drafts/{draft_id}", msg, level=level)

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@app.get("/settings", response_class=HTMLResponse)
def settings_view(request: Request):
    settings = get_settings()
    gmail = _gmail(request)

    with get_session() as session:
        active = session.scalar(select(Resume).where(Resume.active == True))  # noqa: E712
        resume = None
        if active is not None:
            resume = {
                "filename": services.friendly_resume_attachment_name(active.filename),
                "uploaded_at": active.uploaded_at,
                "mime_type": active.mime_type,
            }

    your_name, subject, body_template = services.resolved_template(settings)
    try:
        rendered_body = body_template.format(your_name=your_name)
    except (KeyError, IndexError):
        rendered_body = body_template

    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "flash": _flash_from_request(request),
            "settings": settings,
            "resume": resume,
            "gmail_authed": gmail.is_authenticated(),
            "rendered_body": rendered_body,
            "template": {
                "your_name": your_name,
                "subject": subject,
                "body": body_template,
            },
        },
    )


@app.post("/settings/template")
def settings_template_save(
    your_name: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
):
    if not subject.strip():
        return _flash_redirect("/settings", "Subject cannot be empty.", level="error")
    if not body.strip():
        return _flash_redirect("/settings", "Body cannot be empty.", level="error")

    services.set_template_overrides(
        your_name=your_name,
        subject=subject,
        body=body,
    )
    return _flash_redirect("/settings", "Email template updated.", level="success")


@app.post("/settings/fill-name-from-google")
def settings_fill_name_from_google(request: Request):
    gmail = _gmail(request)
    if not gmail.is_authenticated():
        return _flash_redirect("/settings", "Connect Gmail first.", level="error")
    name = gmail.fetch_user_display_name()
    if not name:
        return _flash_redirect(
            "/settings",
            "Could not read your name from Google. Click Reconnect Gmail so this app "
            "can request your profile, then try again—or type your name in the field.",
            level="error",
        )
    services.set_your_name_override(name)
    return _flash_redirect(
        "/settings",
        f"Your name was set to {name!r} (from your Google account).",
        level="success",
    )


@app.post("/settings/resume")
async def settings_resume(file: UploadFile):
    try:
        resume = services.save_uploaded_resume(file)
    except ValueError as exc:
        return _flash_redirect("/settings", str(exc), level="error")
    except Exception as exc:  # noqa: BLE001
        logger.exception("resume upload failed")
        return _flash_redirect("/settings", f"Upload failed: {exc}", level="error")

    return _flash_redirect(
        "/settings", f"Resume uploaded: {resume.filename}", level="success"
    )


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------

@app.get("/auth/google")
def auth_google(request: Request):
    settings = get_settings()
    gmail = _gmail(request)

    try:
        auth_url, state, code_verifier = gmail.get_authorization_url(
            redirect_uri=settings.oauth_redirect_uri
        )
    except FileNotFoundError as exc:
        return _flash_redirect(
            "/settings",
            f"credentials.json not found at {settings.credentials_path!r}: {exc}",
            level="error",
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("get_authorization_url failed")
        return _flash_redirect("/settings", f"OAuth start failed: {exc}", level="error")

    with get_session() as session:
        for key, value in (("oauth_state", state), ("oauth_code_verifier", code_verifier)):
            row = session.get(Setting, key)
            if row is None:
                session.add(Setting(key=key, value=value))
            else:
                row.value = value

    return RedirectResponse(url=auth_url, status_code=303)


@app.api_route("/auth/logout", methods=["GET", "POST"], include_in_schema=False)
def auth_logout(request: Request):
    """Disconnect Gmail by deleting stored OAuth tokens.

    Supports GET so opening ``/auth/logout`` in the browser works; the profile menu uses POST.
    """
    try:
        DBTokenStore().clear_token()
    except Exception as exc:  # noqa: BLE001
        logger.exception("logout: failed to clear OAuth token")
        return _flash_redirect(
            "/settings",
            f"Could not sign out (database error): {exc}",
            level="error",
        )
    client = getattr(request.app.state, "gmail", None)
    if client is not None:
        client.clear_cached_userinfo()
    return _flash_redirect("/settings", "Signed out of Gmail.", level="success")


@app.get("/auth/callback")
def auth_google_callback(request: Request):
    settings = get_settings()
    gmail = _gmail(request)

    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")

    if error:
        return _flash_redirect("/settings", f"OAuth error: {error}", level="error")
    if not code or not state:
        return _flash_redirect(
            "/settings", "OAuth callback missing code or state", level="error"
        )

    with get_session() as session:
        state_row = session.get(Setting, "oauth_state")
        verifier_row = session.get(Setting, "oauth_code_verifier")
        expected = state_row.value if state_row else None
        code_verifier = verifier_row.value if verifier_row else None

    if not expected or expected != state:
        return _flash_redirect(
            "/settings", "OAuth state mismatch - please try again.", level="error"
        )

    try:
        gmail.exchange_code(
            code=code,
            redirect_uri=settings.oauth_redirect_uri,
            state=state,
            code_verifier=code_verifier,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("exchange_code failed")
        return _flash_redirect("/settings", f"OAuth exchange failed: {exc}", level="error")

    msg = "Gmail connected."
    if services.should_autofill_name_from_google(settings):
        gname = gmail.fetch_user_display_name()
        if gname:
            services.set_your_name_override(gname)
            msg += f" Your signature name was set to {gname!r} from your Google account."
        else:
            msg += (
                " Open Email template below and use “Fill from Google account”, "
                "or set your name manually."
            )
    return _flash_redirect("/settings", msg, level="success")
