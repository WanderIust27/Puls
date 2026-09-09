"""Schritte: Tagesziel, Tagesverlauf und wann du dich üblicherweise bewegst.

Ein Schrittziel allein sagt am Nachmittag wenig: 6.000 von 10.000 sind um
zehn Uhr sehr viel und um zwanzig Uhr sehr wenig. Interessant wird die Zahl
erst im Vergleich mit dir selbst — mit dem, was zu dieser Stunde üblich ist.

Deshalb wird der Tagesverlauf stundenweise gespeichert und daraus ein
typischer Tag gebildet (Median über die letzten Wochen, nicht Mittelwert: Ein
einzelner Wandertag soll den Normalfall nicht verschieben).
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts

log = logging.getLogger("puls.steps")

TYPICAL_DAYS = 28        # Zeitraum, aus dem der typische Tag gebildet wird
MIN_DAYS = 5             # darunter gibt es keinen "typischen Tag"


def goal() -> int:
    try:
        return max(1000, int(float(get_setting("step_goal", "10000") or 10000)))
    except (TypeError, ValueError):
        return 10000


def record_day(day: str, per_hour: dict[int, int]) -> int:
    """Stundenwerte eines Tages ablegen — vorhandene werden ersetzt."""
    rows = [(day, int(h), int(v)) for h, v in per_hour.items() if v and v > 0]
    if not rows:
        return 0
    with get_db() as db:
        db.executemany(
            """INSERT INTO step_intervals(day, hour, steps) VALUES(?,?,?)
               ON CONFLICT(day, hour) DO UPDATE SET
                 steps=excluded.steps, updated_at=datetime('now')""", rows)
    return len(rows)


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if not n:
        return 0.0
    mid = n // 2
    return ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def typical(days: int = TYPICAL_DAYS, weekday: int | None = None
            ) -> dict[str, Any]:
    """Der typische Tagesverlauf: je Stunde der Median über die letzten Wochen."""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT day, hour, steps FROM step_intervals WHERE day >= ? AND day < ?",
            (since, dt.date.today().isoformat())).fetchall())

    by_day: dict[str, dict[int, int]] = {}
    for r in rows:
        if weekday is not None and dt.date.fromisoformat(r["day"]).weekday() != weekday:
            continue
        by_day.setdefault(r["day"], {})[r["hour"]] = r["steps"]

    if len(by_day) < MIN_DAYS:
        return {"days": len(by_day), "hours": [], "cumulative": [],
                "total": None, "hint":
                f"Für einen typischen Tag braucht es mindestens {MIN_DAYS} "
                f"aufgezeichnete Tage — bisher sind es {len(by_day)}."}

    hours = []
    for h in range(24):
        values = [d.get(h, 0) for d in by_day.values()]
        hours.append({"hour": h, "steps": round(_median(values))})

    running = 0
    cumulative = []
    for h in hours:
        running += h["steps"]
        cumulative.append({"hour": h["hour"], "steps": running})

    active = [h for h in hours if h["steps"] > 0]
    busiest = max(hours, key=lambda h: h["steps"]) if active else None
    # Wann ist die Hälfte des Tagespensums erreicht? Das sagt mehr über den
    # Rhythmus als jede Einzelstunde.
    half = running / 2
    half_hour = next((c["hour"] for c in cumulative if c["steps"] >= half), None)

    return {
        "days": len(by_day),
        "hours": hours,
        "cumulative": cumulative,
        "total": running,
        "busiest_hour": busiest["hour"] if busiest else None,
        "busiest_steps": busiest["steps"] if busiest else None,
        "half_by_hour": half_hour,
        "morning": sum(h["steps"] for h in hours if 5 <= h["hour"] < 12),
        "afternoon": sum(h["steps"] for h in hours if 12 <= h["hour"] < 18),
        "evening": sum(h["steps"] for h in hours if 18 <= h["hour"] < 24),
        "hint": None,
    }


def today(now: dt.datetime | None = None) -> dict[str, Any]:
    """Wo du heute stehst — im Vergleich zu dir selbst um diese Uhrzeit."""
    now = now or dt.datetime.now()
    day = now.date().isoformat()
    target = goal()

    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT hour, steps FROM step_intervals WHERE day=? ORDER BY hour",
            (day,)).fetchall())
        total_row = db.execute(
            "SELECT steps FROM daily_metrics WHERE day=?", (day,)).fetchone()

    from_hours = sum(r["steps"] for r in rows)
    # Der Tagesgesamtwert von Garmin ist der verlaesslichere; die Stundenwerte
    # koennen hinterherhinken, wenn die Uhr laenger nicht synchronisiert hat.
    done = max(from_hours, (total_row["steps"] if total_row else 0) or 0)

    norm = typical()
    expected = None
    if norm["hint"] is None:
        upto = [c for c in norm["cumulative"] if c["hour"] <= now.hour]
        expected = upto[-1]["steps"] if upto else 0

    remaining = max(0, target - done)
    ahead = (done - expected) if expected is not None else None

    # Hochrechnung: Was kommt bis Mitternacht noch, wenn der Tag normal
    # weiterlaeuft? Ohne typischen Tag wird nicht hochgerechnet.
    projected = None
    if norm["hint"] is None and norm["total"]:
        rest = norm["total"] - (expected or 0)
        projected = round(done + max(0, rest))

    return {
        "day": day, "goal": target, "steps": done,
        "percent": min(100, round(done / target * 100)) if target else 0,
        "remaining": remaining,
        "expected_by_now": expected,
        "ahead_by": ahead,
        "projected": projected,
        "reaches_goal": None if projected is None else projected >= target,
        "hours": rows,
        "typical": norm,
        "note": _note(done, target, expected, ahead, projected, norm, now),
    }


def _note(done, target, expected, ahead, projected, norm, now) -> str:
    """Ein Satz zum Stand — gerechnet, nicht formuliert vom Modell."""
    if done >= target:
        return (f"Ziel erreicht: {done:,} Schritte.".replace(",", ".")
                + (" Alles darüber ist Zugabe." if done < target * 1.3 else ""))
    if expected is None:
        return (f"{done:,}".replace(",", ".") + f" von {target:,}".replace(",", ".")
                + f" Schritten. Für einen Vergleich mit deinem üblichen Tag "
                  f"fehlen noch ein paar aufgezeichnete Tage.")
    parts = [f"{done:,}".replace(",", ".") + f" von {target:,}".replace(",", ".")
             + " Schritten."]
    if ahead is not None and abs(ahead) >= 300:
        richtung = "vor" if ahead > 0 else "hinter"
        parts.append(f"Das sind {abs(ahead):,}".replace(",", ".")
                     + f" Schritte {richtung} deinem üblichen Stand um "
                       f"{now.hour} Uhr.")
    else:
        parts.append(f"Damit liegst du genau in deinem üblichen Rahmen für "
                     f"{now.hour} Uhr.")
    if projected is not None:
        if projected >= target:
            parts.append("Läuft der Tag normal weiter, reicht das fürs Ziel.")
        else:
            fehlt = target - projected
            minuten = max(5, round(fehlt / 100))
            parts.append(f"Normal weiter fehlen am Ende rund {fehlt:,}".replace(",", ".")
                         + f" Schritte — etwa {minuten} Minuten Gehen.")
    return " ".join(parts)
