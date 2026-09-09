"""Wann du ins Bett solltest — und wie regelmäßig es tatsächlich ist.

Die Rechnung ist einfach genug, um sie im Kopf nachzuvollziehen, und genau
deshalb steht sie im Code und nicht im Modell:

    Zubettgehzeit = Aufstehziel − Schlafbedarf − Einschlafdauer

Der Schlafbedarf ist keine feste Zahl. Er wächst mit der Belastung: An Tagen
nach einer harten Einheit braucht der Körper mehr, bei schlechter Erholung
ebenfalls. Die Zuschläge sind klein und benannt — wer sie für falsch hält,
sieht sofort, woran es liegt.

Die Einschlafdauer kommt aus deinen eigenen Nächten, wenn genug vorliegen:
Garmin meldet Zubettgehen und Schlafbeginn, die Differenz ist deine übliche
Einschlafzeit. Sonst gilt ein Vorgabewert.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts

log = logging.getLogger("puls.sleep")

BASE_NEED_H = 8.0          # Grundbedarf, bevor Training und Erholung dazukommen
FALL_ASLEEP_MIN = 15       # Vorgabe, bis die eigenen Nächte etwas anderes sagen
MIN_NIGHTS = 5             # so viele Nächte braucht es für eigene Werte
MAX_NEED_H = 10.0
MIN_NEED_H = 6.5


def _wake_target() -> tuple[int, int]:
    """Aufstehziel als (Stunde, Minute)."""
    raw = (get_setting("wake_target", "06:30") or "06:30").strip()
    try:
        hour, minute = raw.split(":")
        return max(0, min(23, int(hour))), max(0, min(59, int(minute)))
    except ValueError:
        return 6, 30


def _fmt(hours: float) -> str:
    hours %= 24
    h, m = int(hours), int(round((hours - int(hours)) * 60))
    if m == 60:
        h, m = h + 1, 0
    return f"{h % 24:02d}:{m:02d}"


def need_hours() -> dict[str, Any]:
    """Wie viel Schlaf heute Nacht — mit Begruendung je Zuschlag."""
    from . import metrics
    need = BASE_NEED_H
    reasons: list[str] = []

    try:
        rec = metrics.recovery_series(21)
        latest, base = rec["latest"], rec["baselines"]
    except Exception as e:                                  # noqa: BLE001
        log.debug("Erholungswerte nicht verfuegbar: %s", e)
        latest, base = {}, {}

    readiness = latest.get("training_readiness")
    if readiness is not None and readiness < 50:
        need += 0.5
        reasons.append(f"Trainingsbereitschaft {readiness:.0f} von 100")

    hrv = base.get("hrv_avg") or {}
    if hrv.get("delta") is not None and hrv["delta"] < -3:
        need += 0.5
        reasons.append(f"HRV {hrv['delta']:.0f} ms unter deinem Schnitt")

    # Nach einer harten Einheit braucht die Erholung mehr Zeit, nicht weniger.
    today = dt.date.today().isoformat()
    with get_db() as db:
        load = db.execute(
            "SELECT SUM(COALESCE(training_load,0)) AS l, "
            "       SUM(COALESCE(duration_s,0)) AS s "
            "FROM activities WHERE substr(start_time,1,10)=?", (today,)).fetchone()
    minutes = round((load["s"] or 0) / 60)
    if minutes >= 90:
        need += 0.5
        reasons.append(f"{minutes} min trainiert")
    elif minutes >= 45:
        need += 0.25
        reasons.append(f"{minutes} min trainiert")

    # Schlafschuld der letzten drei Nächte, gedeckelt: Man holt nicht sechs
    # Stunden in einer Nacht nach, aber eine halbe schon.
    debt = 0.0
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT sleep_seconds FROM daily_metrics WHERE sleep_seconds IS NOT NULL "
            "ORDER BY day DESC LIMIT 3").fetchall())
    if len(rows) >= 2:
        short = sum(max(0.0, BASE_NEED_H - r["sleep_seconds"] / 3600) for r in rows)
        debt = min(0.5, short / 4)
        if debt >= 0.15:
            reasons.append(f"{short:.1f} h Rückstand aus den letzten Nächten")
    need += debt

    need = max(MIN_NEED_H, min(MAX_NEED_H, need))
    return {"hours": round(need, 2), "base": BASE_NEED_H, "reasons": reasons}


def fall_asleep_minutes() -> dict[str, Any]:
    """Wie lange du üblicherweise zum Einschlafen brauchst."""
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT sleep_start, sleep_end, sleep_seconds, sleep_awake_s "
            "FROM daily_metrics WHERE sleep_seconds IS NOT NULL "
            "ORDER BY day DESC LIMIT 30").fetchall())
    gaps = []
    for r in rows:
        # Zeit im Bett gegen tatsaechlich geschlafene Zeit: Die Differenz ist
        # Einschlafen plus naechtliches Wachliegen.
        total, slept = None, r["sleep_seconds"]
        if r["sleep_start"] and r["sleep_end"]:
            from .stats import _clock
            start = _clock(r["sleep_start"], night=True)
            end = _clock(r["sleep_end"])
            if start is not None and end is not None:
                total = (end + 24 - start) % 24 * 3600
        if total and slept and total > slept:
            gaps.append(min(60 * 60, total - slept - (r["sleep_awake_s"] or 0)))
    usable = [g / 60 for g in gaps if g > 0]
    if len(usable) < MIN_NIGHTS:
        return {"minutes": FALL_ASLEEP_MIN, "measured": False, "nights": len(usable)}
    usable.sort()
    median = usable[len(usable) // 2]
    return {"minutes": int(max(5, min(45, round(median)))), "measured": True,
            "nights": len(usable)}


def regularity(days: int = 21) -> dict[str, Any]:
    """Wie gleichmäßig deine Zeiten sind — und wie sie zum Ziel stehen."""
    from .stats import collect
    rows = [r for r in collect(days) if r.get("bedtime") is not None]
    beds = [r["bedtime"] for r in rows]
    wakes = [r["waketime"] for r in rows if r.get("waketime") is not None]

    def spread(values: list[float]) -> float | None:
        if len(values) < 3:
            return None
        mid = sorted(values)[len(values) // 2]
        return round(sum(abs(v - mid) for v in values) / len(values), 2)

    wake_h, wake_m = _wake_target()
    target = wake_h + wake_m / 60
    late = [w for w in wakes if w > target + 0.5]
    return {
        "nights": len(rows),
        "bedtime_median": round(sorted(beds)[len(beds) // 2], 2) if beds else None,
        "waketime_median": round(sorted(wakes)[len(wakes) // 2], 2) if wakes else None,
        "bedtime_spread_h": spread(beds),
        "waketime_spread_h": spread(wakes),
        "target": _fmt(target),
        "later_than_target": len(late),
        "of_nights": len(wakes),
    }


def tonight() -> dict[str, Any]:
    """Die Empfehlung für heute Abend."""
    need = need_hours()
    asleep = fall_asleep_minutes()
    wake_h, wake_m = _wake_target()
    target = wake_h + wake_m / 60

    # Rückwärts vom Aufstehziel: erst der Schlaf, dann das Einschlafen.
    bedtime = target - need["hours"] - asleep["minutes"] / 60
    reg = regularity()

    now = dt.datetime.now()
    hours_now = now.hour + now.minute / 60
    # Nach Mitternacht liegt die Zubettgehzeit hinter, nicht vor uns.
    until = (bedtime + 24 - hours_now) % 24
    soon = until <= 3

    usual = reg.get("bedtime_median")
    shift = None
    if usual is not None:
        shift = round(((bedtime + 24) % 24) - (usual % 24), 2)

    return {
        "wake_target": _fmt(target),
        "need_hours": need["hours"],
        "need_reasons": need["reasons"],
        "fall_asleep_min": asleep["minutes"],
        "fall_asleep_measured": asleep["measured"],
        "bedtime": _fmt(bedtime),
        "minutes_until": int(round(until * 60)),
        "due_soon": soon,
        "usual_bedtime": _fmt(usual) if usual is not None else None,
        "shift_h": shift,
        "regularity": reg,
        "note": _note(need, asleep, reg, shift),
    }


def _note(need: dict[str, Any], asleep: dict[str, Any],
          reg: dict[str, Any], shift: float | None) -> str:
    """Ein Satz, warum heute diese Zeit gilt — im Code formuliert."""
    parts = []
    if need["reasons"]:
        parts.append(f"{need['hours']:.2g} h Schlaf, weil "
                     + " und ".join(need["reasons"][:2]) + ".")
    else:
        parts.append(f"{need['hours']:.2g} h Schlaf — deine Werte sind unauffällig.")
    if asleep["measured"]:
        parts.append(f"Du brauchst üblicherweise {asleep['minutes']} min zum "
                     f"Einschlafen, das ist eingerechnet.")
    if shift is not None and abs(shift) >= 0.25:
        richtung = "früher" if shift < 0 else "später"
        parts.append(f"Das sind {abs(shift):.1f} h {richtung} als deine übliche Zeit.")
    if reg.get("bedtime_spread_h") is not None and reg["bedtime_spread_h"] > 1.0:
        parts.append(f"Deine Zubettgehzeit schwankt um ±{reg['bedtime_spread_h']:.1f} h — "
                     f"Regelmäßigkeit bringt hier mehr als eine einzelne lange Nacht.")
    return " ".join(parts)
