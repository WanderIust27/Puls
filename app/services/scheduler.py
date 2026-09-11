"""Hintergrundjobs — nur noch zwei, und beide tun etwas Nachvollziehbares.

Der Sync holt, was die Uhr aufgezeichnet hat. Danach werden aus den neuen
Saetzen die Gewichtsvorschlaege abgeleitet — sie brauchen genau diese frischen
Daten, und wer morgens die App oeffnet, soll sie schon vorfinden.
"""
from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from ..config import SYNC_INTERVAL_HOURS, TZ
from ..db import get_setting
from . import garmin_sync

log = logging.getLogger("puls.scheduler")
scheduler = BackgroundScheduler(timezone=TZ)


def _sync_job() -> None:
    if get_setting("garmin_linked") != "1":
        return
    garmin_sync.full_sync()
    try:
        from . import exercises as ex_lib
        today = dt.date.today()
        for back in range(0, 3):
            ex_lib.propose_for_day((today - dt.timedelta(days=back)).isoformat())
    except Exception as e:                                      # noqa: BLE001
        log.debug("Vorschläge übersprungen: %s", e)


def start() -> None:
    scheduler.add_job(_sync_job, IntervalTrigger(hours=SYNC_INTERVAL_HOURS),
                      id="garmin_sync", max_instances=1, coalesce=True)
    scheduler.start()
    log.info("Scheduler gestartet (Sync alle %s h).", SYNC_INTERVAL_HOURS)


def shutdown() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
