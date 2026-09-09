"""Hintergrundjobs: Auto-Sync, tägliche Coach-Nachricht, Wochen-Forschungstipp."""
from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import (RESEARCH_TIP_CRON_DOW, RESEARCH_TIP_CRON_HOUR,
                      SYNC_INTERVAL_HOURS, TZ)
from ..db import get_setting
from . import coach_ai, garmin_sync

log = logging.getLogger("puls.scheduler")
scheduler = BackgroundScheduler(timezone=TZ)


def _sync_job() -> None:
    if get_setting("garmin_linked") == "1":
        garmin_sync.full_sync()
    # Nach jedem Sync prüfen, ob sich ein Vorschlag ergibt — die Regeln
    # brauchen die frischen Daten.
    try:
        from . import suggestions
        suggestions.generate()
    except Exception as e:
        log.debug("Vorschläge übersprungen: %s", e)

def _daily_message_job() -> None:
    try:
        coach_ai.daily_message()
    except Exception as e:
        log.warning("Tagesnachricht fehlgeschlagen: %s", e)


def _research_job() -> None:
    try:
        coach_ai.research_tip()
    except Exception as e:
        log.warning("Forschungstipp fehlgeschlagen: %s", e)


def start() -> None:
    scheduler.add_job(_sync_job, IntervalTrigger(hours=SYNC_INTERVAL_HOURS),
                      id="garmin_sync", max_instances=1, coalesce=True)
    scheduler.add_job(_daily_message_job,
                      CronTrigger(hour=7, minute=30, timezone=TZ),
                      id="daily_message", max_instances=1, coalesce=True)
    scheduler.add_job(_research_job,
                      CronTrigger(day_of_week=RESEARCH_TIP_CRON_DOW,
                                  hour=RESEARCH_TIP_CRON_HOUR, timezone=TZ),
                      id="research_tip", max_instances=1, coalesce=True)
    scheduler.start()
    log.info("Scheduler gestartet (Sync alle %s h).", SYNC_INTERVAL_HOURS)


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
