# nvoids Job Agent

A small local web app (FastAPI + SQLite + APScheduler) that polls
[nvoids.com](https://nvoids.com) for new job listings matching your keywords,
extracts recruiter emails from each match, and generates **Gmail drafts** with
your resume attached. Nothing is sent automatically - you review and click
Send in Gmail.

## Setup (Windows / PowerShell)

1. **Install Python 3.11+** from [python.org](https://www.python.org/downloads/)
   or the Microsoft Store. Verify:

   ```powershell
   python --version
   ```

2. **Create a virtual environment and activate it:**

   ```powershell
   cd C:\Users\nls56\nvoids-job-agent
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

   If activation is blocked, run
   `Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned` once.

3. **Install dependencies:**

   ```powershell
   pip install -r requirements.txt
   ```

4. **Create a Google OAuth client** (one-time):

   1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
   2. Create (or pick) a project and enable the **Gmail API**
      (APIs & Services - Library - Gmail API - Enable).
   3. **APIs & Services - OAuth consent screen**: pick "External", add your
      Gmail address as a **Test user**, set the app name, and save. You can
      leave the app in "Testing" mode.
   4. **APIs & Services - Credentials - Create credentials - OAuth client ID**:
      - Application type: **Web application**
      - Authorized redirect URI: `http://localhost:8000/auth/callback`
   5. Download the JSON and save it as `credentials.json` in the project
      root (`C:\Users\nls56\nvoids-job-agent\credentials.json`).

5. **Run the server:**

   ```powershell
   uvicorn app.main:app --reload --port 8000
   ```

6. **Use it:**

   1. Open <http://localhost:8000>.
   2. Go to **Settings** and upload your resume (`.pdf`, `.doc`, or `.docx`).
   3. Click **Connect Gmail** and approve the requested scopes (`gmail.compose`,
      plus `openid` / **userinfo.profile** so your display name can fill the
      email sign-off). If you connected before those were added, use **Reconnect**
      on Settings once.
   4. Back on the dashboard, click **Run poll now** (or wait up to 5 minutes
      for the scheduled poll).
   5. Open a matched job's draft, edit `to` / `subject` / `body` if needed,
      then click **Push to Gmail**. The draft shows up in your Gmail Drafts
      folder with the resume attached.

## Configuration

Anything in `app/config.py` can be overridden via environment variables or a
`.env` file in the project root. Useful ones:

| Variable                 | Default                               | Notes                                   |
| ------------------------ | ------------------------------------- | --------------------------------------- |
| `POLL_INTERVAL_MINUTES`  | `5`                                   | Background scheduler interval           |
| `BASE_URL`               | `http://localhost:8000`               | Used to build the OAuth redirect URI    |
| `CREDENTIALS_PATH`       | `credentials.json`                    | Path to the Google OAuth client JSON    |
| `YOUR_NAME`              | `Your Name`                           | Substituted into the email body         |
| `DEFAULT_SUBJECT`        | Application for Data Engineer...      | Default subject for generated drafts    |
| `SEARCH_URL`             | `https://nvoids.com/search_sph.jsp`   | Listing page to scrape                  |

Example `.env`:

```
YOUR_NAME=Jane Doe
POLL_INTERVAL_MINUTES=10
```

## Data files

- `app/data/jobs.db` - SQLite database (jobs, drafts, OAuth token, etc.).
- `app/data/resume/` - uploaded resume files, timestamp-prefixed.
- `credentials.json` / `token.json` - Google OAuth; **never commit these**.

They are already in `.gitignore`.

## Safety and Terms of Service

- The tool produces **drafts only** - you must manually review and send every
  message. There is no auto-send path.
- Respect **nvoids.com's Terms of Service** and `robots.txt`. The default
  5-minute poll is gentle, but don't crank it down.
- Unsolicited recruitment email is regulated. Comply with **CAN-SPAM** (US),
  **CASL** (Canada), **GDPR/PECR** (EU/UK), and any local law that applies to
  you. Include a way for recipients to opt out.
- Credentials stay local: the OAuth token is stored in `app/data/jobs.db` on
  your machine; it is never uploaded anywhere.

## Project layout

```
app/
  main.py            FastAPI app + routes
  config.py          pydantic-settings
  db.py              SQLAlchemy engine / session
  models.py          ORM models
  token_store.py     DB-backed Gmail token store
  services.py        polling, draft generation, resume upload
  scheduler.py       APScheduler background polling
  scraper.py         nvoids.com scraping (interface described below)
  gmail_client.py    Gmail API wrapper (interface described below)
  templates/         Jinja2 templates
  data/              SQLite DB + uploaded resumes (gitignored)
```
