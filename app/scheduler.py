"""APScheduler background polling."""

from __future__ import annotations

import logging
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler

from . import services
from .config import get_settings


logger = logging.getLogger(__name__)

_scheduler: Optional[BackgroundScheduler] = None
_JOB_ID = "poll_nvoids"


def _poll_job() -> None:
    try:
        summary = services.run_poll_once()
        logger.info("scheduled poll summary: %s", summary)
    except Exception:
        logger.exception("scheduled poll failed")


def start_scheduler(app=None) -> BackgroundScheduler:
    """Start the background scheduler (idempotent)."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler

    settings = get_settings()
    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        _poll_job,
        trigger="interval",
        minutes=max(1, int(settings.poll_interval_minutes)),
        id=_JOB_ID,
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "scheduler started; polling every %d minute(s)",
        settings.poll_interval_minutes,
    )
    return scheduler


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:
            logger.exception("error shutting down scheduler")
        _scheduler = None
