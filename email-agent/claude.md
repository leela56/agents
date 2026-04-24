# AI Email Agent — Project Guide

## Overview

Production-grade agentic AI email assistant that connects to Gmail, classifies emails, generates summaries, and drafts intelligent replies. Powered by Google Gemini 2.0 Flash and orchestrated with LangGraph.

## Architecture

```
email-agent/
├── backend/           # FastAPI + Python 3.12+
│   ├── app/
│   │   ├── main.py           # FastAPI app with lifespan, middleware, CORS
│   │   ├── config.py         # Pydantic Settings from .env
│   │   ├── database.py       # Async SQLAlchemy + SQLite
│   │   ├── models.py         # Strict Pydantic schemas (request/response)
│   │   ├── security.py       # Fernet token encryption, rate limiting, sanitization
│   │   ├── middleware.py      # Security headers, structured request logging
│   │   ├── exceptions.py     # Custom exceptions + global handlers
│   │   ├── routers/
│   │   │   ├── auth.py       # Gmail OAuth2 (login, callback, status, revoke)
│   │   │   ├── emails.py     # CRUD + process + redraft endpoints
│   │   │   └── health.py     # Liveness + readiness checks
│   │   ├── services/
│   │   │   ├── gmail_service.py   # Gmail API wrapper (fetch, parse MIME)
│   │   │   └── agent_service.py   # Orchestrates fetch → store → AI process
│   │   └── agents/
│   │       ├── classifier.py      # Categorize: urgent/action/info/spam
│   │       ├── summarizer.py      # TL;DR, key points, action items, sentiment
│   │       ├── draft_writer.py    # Reply drafts (professional/friendly/brief)
│   │       └── graph.py           # LangGraph DAG: classify → summarize → draft
│   ├── pyproject.toml        # uv package manager config
│   ├── uv.lock               # Locked dependencies (deterministic)
│   ├── run.py                # Dev server entry (`uv run python run.py`)
│   └── .env.example          # Environment variable template
├── frontend/          # React + Vite
│   ├── src/
│   │   ├── App.jsx           # Main application layout
│   │   ├── main.jsx          # React root
│   │   ├── index.css         # Design system (CSS variables)
│   │   └── components/       # UI components (to be built)
│   ├── package.json
│   └── vite.config.js
└── .gitignore
```

## Tech Stack

| Layer              | Technology                              |
|--------------------|-----------------------------------------|
| **LLM**            | Google Gemini 2.0 Flash (via LangChain) |
| **Agent Framework**| LangChain + LangGraph                   |
| **Backend**        | FastAPI (async, Python 3.12+)           |
| **Email**          | Gmail API (OAuth2, encrypted tokens)    |
| **Frontend**       | React 19 + Vite 8                       |
| **Database**       | SQLite (async via aiosqlite)            |
| **Package Mgmt**   | `uv` (backend), `npm` (frontend)       |
| **Security**       | Fernet encryption, SlowAPI rate limits, CSP headers |

## Key Patterns

### Backend

- **Config**: All settings via `Pydantic Settings` from `.env` — never raw `os.getenv`
- **Security**: OAuth tokens encrypted at rest with Fernet (AES-128-CBC). Rate limiting via SlowAPI. Security headers on every response. Input sanitization on email bodies.
- **Database**: Async SQLAlchemy 2.0 with `mapped_column`. Session via `get_db_session()` dependency injection with auto-commit/rollback.
- **Logging**: `structlog` with JSON output (production) / console renderer (dev). Request IDs tracked via context vars.
- **Error handling**: Custom exception hierarchy (`EmailAgentError` base). Global handlers return consistent JSON — no stack traces leaked in production.
- **AI Pipeline**: LangGraph StateGraph: `classify → summarize → (conditional) draft → END`. Conditional edge: drafts only for `urgent` or `action_required` emails.
- **LLM calls**: All use `ChatGoogleGenerativeAI.ainvoke()` with JSON-only output prompts. Response cleaning strips markdown code fences. Results validated and bounded (max lengths, value clamping).

### Frontend

- **Framework**: React 19 with Vite 8, vanilla CSS
- **API**: Backend runs on `http://localhost:8000`, frontend on `http://localhost:5173`
- **Design**: Dark glassmorphism theme with Google-inspired gradient accents

## Running Locally

### Backend
```bash
cd backend
cp .env.example .env   # Fill in your API keys
uv sync                # Install dependencies
uv run python run.py   # Starts on http://localhost:8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev            # Starts on http://localhost:5173
```

## API Endpoints

| Method | Path                     | Description                        |
|--------|--------------------------|------------------------------------|
| GET    | `/auth/login`            | Initiate Gmail OAuth2 flow         |
| GET    | `/auth/callback`         | Handle OAuth2 callback             |
| GET    | `/auth/status`           | Check authentication status        |
| POST   | `/auth/revoke`           | Revoke Gmail access                |
| GET    | `/emails`                | List emails (filterable, paginated)|
| GET    | `/emails/{id}`           | Get email with AI analysis         |
| POST   | `/emails/process`        | Fetch + AI process new emails      |
| POST   | `/emails/{id}/redraft`   | Regenerate draft with new tone     |
| GET    | `/emails/stats`          | Dashboard statistics               |
| GET    | `/health`                | Liveness check                     |
| GET    | `/health/ready`          | Readiness check (all deps)         |

## Email Categories

- 🔴 `urgent` — Needs immediate action
- 🟡 `action_required` — Needs response, not time-critical
- 🔵 `informational` — FYI, newsletters, notifications
- ⚪ `spam` — Promotions, junk

## Draft Tones

- `professional` — Formal, business-appropriate
- `friendly` — Warm, personable
- `brief` — Ultra-concise, 2-3 sentences

## Environment Variables

See `backend/.env.example` for the full list. Required:
- `GEMINI_API_KEY` — From aistudio.google.com
- `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` — Google Cloud Console
- `ENCRYPTION_KEY` — Generate with: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`

## Current Status

- ✅ Backend fully built (Phases 1-4)
- 🔲 Frontend needs implementation (Phase 5) — currently default Vite scaffold
- 🔲 Docker configuration (Phase 6)
- 🔲 README.md
