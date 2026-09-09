"""Rueckmeldung nach einer Einheit — und was der Coach daraus lernt.

Die Uhr misst Puls und Tempo, aber nicht, ob sich eine Einheit gut angefuehlt
hat. Genau das ist die Groesse, die fehlt: zwei Laeufe mit identischen Daten
koennen sich voellig unterschiedlich anfuehlen, und der Unterschied liegt in
Schlaf, Stress und Ernaehrung davor.

Deshalb fragt PULS nach jeder Einheit kurz nach — zwei Regler und ein Feld.
Aus genug solchen Rueckmeldungen laesst sich sagen, unter welchen Bedingungen
deine Einheiten gut laufen.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..db import get_db, rows_to_dicts

log = logging.getLogger("puls.feedback")

MIN_FOR_PATTERN = 6


def save(activity_id: int, rating: int | None = None, effort: int | None = None,
         note: str | None = None) -> dict[str, Any]:
    def _scale(v: Any) -> int | None:
        if v is None:
            return None
        try:
            return max(1, min(5, int(v)))
        except (TypeError, ValueError):
            return None

    with get_db() as db:
        exists = db.execute("SELECT 1 FROM activities WHERE id=?",
                            (activity_id,)).fetchone()
        if not exists:
            raise ValueError("Diese Aktivität gibt es nicht.")
        db.execute(
            """INSERT INTO activity_feedback(activity_id, rating, effort, note)
               VALUES(?,?,?,?)
               ON CONFLICT(activity_id) DO UPDATE SET
                 rating=excluded.rating, effort=excluded.effort,
                 note=excluded.note, created_at=datetime('now')""",
            (activity_id, _scale(rating), _scale(effort),
             (note or "").strip() or None))
    return {"activity_id": activity_id, "rating": _scale(rating),
            "effort": _scale(effort)}


def get(activity_id: int) -> dict[str, Any] | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM activity_feedback WHERE activity_id=?",
                         (activity_id,)).fetchone()
    return dict(row) if row else None


def pending(limit: int = 3) -> list[dict[str, Any]]:
    """Einheiten der letzten Tage, zu denen noch nichts gesagt wurde."""
    since = (dt.date.today() - dt.timedelta(days=3)).isoformat()
    with get_db() as db:
        return rows_to_dicts(db.execute(
            """SELECT a.id, a.name, a.sport, a.start_time, a.duration_s,
                      a.distance_m
               FROM activities a
               LEFT JOIN activity_feedback f ON f.activity_id = a.id
               WHERE f.id IS NULL AND substr(a.start_time,1,10) >= ?
               ORDER BY a.start_time DESC LIMIT ?""", (since, limit)).fetchall())


def patterns() -> dict[str, Any]:
    """Unter welchen Bedingungen fuehlen sich deine Einheiten gut an?

    Verglichen werden die Tage vor gut bewerteten Einheiten mit denen vor
    schlecht bewerteten. Gemeldet wird nur, was deutlich auseinanderliegt —
    sonst waere es Kaffeesatz.
    """
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            """SELECT f.rating, f.effort, substr(a.start_time,1,10) AS day,
                      a.sport
               FROM activity_feedback f JOIN activities a ON a.id = f.activity_id
               WHERE f.rating IS NOT NULL""").fetchall())
        daily = {r["day"]: dict(r) for r in db.execute(
            "SELECT day, sleep_seconds, hrv_avg, resting_hr, stress_avg, "
            "body_battery_wake FROM daily_metrics").fetchall()}

    if len(rows) < MIN_FOR_PATTERN:
        return {"count": len(rows), "needed": MIN_FOR_PATTERN, "findings": [],
                "hint": (f"Noch {MIN_FOR_PATTERN - len(rows)} Rückmeldungen, dann "
                         f"kann ich sagen, unter welchen Bedingungen es bei dir "
                         f"gut läuft.")}

    good = [r for r in rows if r["rating"] >= 4]
    poor = [r for r in rows if r["rating"] <= 2]
    findings = []

    def mean(sample: list[dict[str, Any]], key: str) -> float | None:
        values = [daily[r["day"]][key] for r in sample
                  if r["day"] in daily and daily[r["day"]].get(key) is not None]
        return sum(values) / len(values) if values else None

    if len(good) >= 3 and len(poor) >= 3:
        for key, label, unit, factor, threshold in (
                ("sleep_seconds", "Schlaf", " h", 1 / 3600, 0.4),
                ("hrv_avg", "HRV", " ms", 1, 3),
                ("resting_hr", "Ruhepuls", " bpm", 1, 2),
                ("stress_avg", "Stressmittel", "", 1, 5)):
            a, b = mean(good, key), mean(poor, key)
            if a is None or b is None:
                continue
            diff = (a - b) * factor
            if abs(diff) < threshold:
                continue
            better = "mehr" if diff > 0 else "weniger"
            findings.append({
                "key": key,
                "text": (f"Vor guten Einheiten hattest du im Schnitt "
                         f"{abs(diff):.1f}{unit} {better} {label} als vor "
                         f"schlechten ({a * factor:.1f} gegenüber "
                         f"{b * factor:.1f}{unit}).")})

    return {"count": len(rows), "good": len(good), "poor": len(poor),
            "findings": findings,
            "hint": None if findings else
            ("Noch kein deutlicher Unterschied zwischen guten und schlechten "
             "Einheiten erkennbar — das ist auch eine Antwort.")}
