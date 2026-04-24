# Project: nvoids Job Agent

## What this is

Local web app for a single user: it polls **nvoids.com** job search results, matches listings to configured keywords, scrapes recruiter emails, stores jobs in SQLite, and builds **application email drafts**. Gmail OAuth is used to **push drafts** or **send** with a resume attachment. The user reviews everything in the UI before anything leaves their account.

## Tech stack

- **Language:** Python 3.11+
- **Framework:** FastAPI (server-rendered HTML with Jinja2; no SPA)
- **Database:** SQLite via SQLAlchemy 2.0 (`app/data/jobs.db` by default)
- **Key libraries:** `uvicorn`, `requests` + `beautifulsoup4` (scraper), `google-api-python-client` + OAuth (Gmail), `apscheduler` (polling), `pydantic-settings` (config / `.env`)

## Folder structure

```
app/
  main.py           # FastAPI routes, flash redirects, template wiring
  services.py       # Polling, draft generation, resume paths, greeting personalization
  scraper.py        # HTTP fetch + HTML parse for nvoids listings
  gmail_client.py   # Gmail API: drafts, send, auth checks
  models.py         # SQLAlchemy ORM: Job, Draft, RecruiterEmail, Resume, Setting, …
  db.py             # Engine, sessions, init_db
  config.py         # Settings (env / .env); search URL, templates, DB path
  scheduler.py      # APScheduler: periodic poll
  token_store.py    # Persist OAuth tokens (DB-backed)
  templates/        # Jinja: base.html, dashboard, jobs, draft, settings
tests/              # pytest: scraper, gmail_client (not full mirror of app/)
requirements.txt
README.md           # Human setup: OAuth, Windows notes, env table
```

There is no `src/` split; the installable package root is **`app/`**.

## How to run

- **Dev server:** `uvicorn app.main:app --reload --port 8000` (from project root, venv active)
- **Tests:** `python -m pytest tests -q`
- **Build:** N/A (interpreted app; deploy = run uvicorn with deps + `credentials.json`)

## Key conventions

- **Routes and HTTP concerns** live in `app/main.py`; **domain behavior** in `app/services.py` (keep new business logic there unless it is inherently HTTP).
- **ORM models** use `snake_case` columns; Python code follows PEP 8 (`snake_case` functions, `PascalCase` models).
- **Templates** extend `base.html`; shared styles live in `base.html` (e.g. `.draft-row`, `.row.nowrap`).
- **Settings:** use `get_settings()` / env vars documented in `README.md` and `app/config.py`.
- **Sessions:** use `get_session()` context manager from `app/db.py` for DB work.

## Current task context

_Update this section whenever you start or finish a chunk of work so the next session stays cheap._

- **Working on:** _(e.g. scraper robustness / Gmail send flow / UI tweak)_
- **Relevant files:** _(2–6 paths, e.g. `app/services.py`, `app/templates/jobs.html`)_
- **Already decided:** _(short bullets: product or tech choices)_
- **Next step:** _(one concrete action)_

## Do not touch

- **`credentials.json`** (project root): Google OAuth client secret; never commit; path configurable via `CREDENTIALS_PATH`.
- **`.venv/`**: local environment; not part of source control.
- **`app/data/jobs.db`** (default): runtime SQLite DB with jobs, drafts, tokens; treat as user data, not a migration artifact to hand-edit without care.

## Known gotchas

- **Scraper is HTML-coupled:** `app/scraper.py` assumes nvoids markup. Site changes can break parsing or test fixtures; `tests/test_scraper.py::test_parse_search_results_from_html` may fail if mock HTML no longer matches production shape or result counts.
- **SQLite + scheduler:** `db.py` uses `check_same_thread=False` so background scheduler threads can share the engine; do not remove without rethinking session/thread usage.
- **Gmail:** Push/send require OAuth + uploaded resume; errors surface as draft `status` / `error` and flash messages.
- **OAuth redirect:** `BASE_URL` (default `http://localhost:8000`) must match the redirect URI configured in Google Cloud Console.
