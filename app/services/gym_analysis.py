"""Auswertung einer Krafteinheit: was war drin, was hat sich bewegt.

Die Fenix protokolliert bei Kraft-Workouts jeden Satz mit Wiederholungen und
Gewicht, und der Sync holt diese Saetze zurueck. Damit laesst sich nach der
Einheit mehr sagen als "75 Minuten trainiert": welche Uebung sich gegenueber
dem letzten Mal bewegt hat, wo es haengt, und was daraus folgt.

Gerechnet wird auch hier im Code. Das Modell darf die Einheit hinterher in
Worte fassen, aber die Zahlen und die Hinweise stehen vorher fest.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..db import get_db, rows_to_dicts

log = logging.getLogger("puls.gym")

# Ab welchem Unterschied eine Veraenderung eine Erwaehnung wert ist
VOLUME_NOTE_PCT = 12
STALE_DAYS = 21


def _sets_of(activity_id: int, day: str) -> list[dict[str, Any]]:
    """Saetze der Einheit — ueber die Aktivitaet, sonst ueber den Tag.

    Manuell eingetragene Saetze haengen an keiner Aktivitaet; sie gehoeren
    trotzdem zur Einheit desselben Tages.
    """
    with get_db() as db:
        rows = db.execute(
            """SELECT s.*, e.name, e.muscle_group, e.equipment, e.slot,
                      e.target_reps, e.rep_max, e.weight_kg AS target_weight,
                      e.fail_streak, e.mode
               FROM exercise_sets s JOIN exercises e ON e.id = s.exercise_id
               WHERE s.activity_id = ? OR (s.activity_id IS NULL AND s.day = ?)
               ORDER BY s.exercise_id, s.set_index""",
            (activity_id, day)).fetchall()
    return rows_to_dicts(rows)


def _volume(sets: list[dict[str, Any]]) -> float:
    """Tonnage: Wiederholungen mal Gewicht. Koerpergewichtsuebungen zaehlen
    hier nicht mit — sonst haengt die Zahl an einer Schaetzung."""
    return sum((s["reps"] or 0) * (s["weight_kg"] or 0) for s in sets)


def _previous_session(exercise_id: int, before_day: str) -> list[dict[str, Any]]:
    with get_db() as db:
        prev = db.execute(
            "SELECT day FROM exercise_sets WHERE exercise_id=? AND day<? "
            "ORDER BY day DESC LIMIT 1", (exercise_id, before_day)).fetchone()
        if not prev:
            return []
        rows = db.execute(
            "SELECT * FROM exercise_sets WHERE exercise_id=? AND day=? "
            "ORDER BY set_index", (exercise_id, prev["day"])).fetchall()
    return rows_to_dicts(rows)


def _best(sets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Der aussagekraeftigste Satz: schwerstes Gewicht, bei gleichem Gewicht
    die meisten Wiederholungen."""
    scored = [s for s in sets if s.get("reps")]
    if not scored:
        return None
    return max(scored, key=lambda s: ((s.get("weight_kg") or 0), s["reps"]))


def analyse(activity_id: int, day: str) -> dict[str, Any] | None:
    """Zusammenfassung einer Krafteinheit."""
    sets = _sets_of(activity_id, day)
    if not sets:
        return None

    by_exercise: dict[int, list[dict[str, Any]]] = {}
    for s in sets:
        by_exercise.setdefault(s["exercise_id"], []).append(s)

    exercises: list[dict[str, Any]] = []
    improved, stalled = [], []
    for ex_id, ex_sets in by_exercise.items():
        first = ex_sets[0]
        best = _best(ex_sets)
        prev = _previous_session(ex_id, day)
        prev_best = _best(prev)

        change = None
        if best and prev_best:
            dw = (best.get("weight_kg") or 0) - (prev_best.get("weight_kg") or 0)
            dr = (best.get("reps") or 0) - (prev_best.get("reps") or 0)
            if dw > 0.01:
                change = {"kind": "weight", "delta": round(dw, 1),
                          "text": f"+{dw:.1f} kg gegenüber dem letzten Mal"}
                improved.append(first["name"])
            elif dw < -0.01:
                change = {"kind": "weight_down", "delta": round(dw, 1),
                          "text": f"{dw:.1f} kg gegenüber dem letzten Mal"}
            elif dr > 0:
                change = {"kind": "reps", "delta": dr,
                          "text": f"+{dr} Wiederholung{'en' if dr > 1 else ''}"}
                improved.append(first["name"])
            elif dr < 0:
                change = {"kind": "reps_down", "delta": dr,
                          "text": f"{dr} Wiederholungen"}
            else:
                change = {"kind": "hold", "delta": 0, "text": "unverändert"}

        if first.get("fail_streak"):
            stalled.append(first["name"])

        exercises.append({
            "exercise_id": ex_id,
            "name": first["name"],
            "muscle_group": first["muscle_group"],
            "slot": first["slot"],
            "sets": len(ex_sets),
            "reps": [s["reps"] for s in ex_sets],
            "weights": [s["weight_kg"] for s in ex_sets],
            "volume_kg": round(_volume(ex_sets), 1),
            "best": best,
            "change": change,
            "hard": sum(1 for s in ex_sets if s.get("feeling") == "hard"),
            "easy": sum(1 for s in ex_sets if s.get("feeling") == "easy"),
        })
    exercises.sort(key=lambda e: (e["slot"] != "kettlebell", e["name"]))

    volume = _volume(sets)
    groups: dict[str, float] = {}
    for e in exercises:
        groups[e["muscle_group"]] = groups.get(e["muscle_group"], 0) + e["volume_kg"]

    return {
        "sets": len(sets),
        "exercises": len(exercises),
        "volume_kg": round(volume, 1),
        "muscle_groups": groups,
        "detail": exercises,
        "improved": improved,
        "stalled": stalled,
        "tips": _tips(exercises, volume, day),
    }


def _average_volume(day: str, weeks: int = 4) -> float | None:
    """Mittleres Volumen der Krafteinheiten davor — als Bezugsgroesse."""
    since = (dt.date.fromisoformat(day) - dt.timedelta(weeks=weeks)).isoformat()
    with get_db() as db:
        rows = db.execute(
            """SELECT day, SUM(COALESCE(reps,0) * COALESCE(weight_kg,0)) AS v
               FROM exercise_sets WHERE day >= ? AND day < ?
               GROUP BY day HAVING v > 0""", (since, day)).fetchall()
    values = [r["v"] for r in rows]
    return sum(values) / len(values) if values else None


def _tips(exercises: list[dict[str, Any]], volume: float,
          day: str) -> list[dict[str, str]]:
    """Hinweise, die sich aus den Zahlen ergeben — keine allgemeinen Weisheiten."""
    tips: list[dict[str, str]] = []

    stalled = [e for e in exercises if e["name"] in
               [x["name"] for x in exercises if x.get("change")
                and x["change"]["kind"] in ("hold", "reps_down", "weight_down")]]
    for e in stalled[:2]:
        tips.append({
            "kind": "stall", "level": "info",
            "text": (f"{e['name']} steht seit der letzten Einheit still. Wenn das "
                     f"noch einmal passiert, nimm eine Stufe zurück und arbeite "
                     f"dich sauber wieder hoch — das geht schneller als es klingt.")})

    too_easy = [e for e in exercises if e["easy"] >= 2 and not e["hard"]]
    for e in too_easy[:2]:
        tips.append({
            "kind": "easy", "level": "good",
            "text": (f"{e['name']} lief durchgehend leicht. Beim nächsten Mal eine "
                     f"Stufe höher — dafür ist die Rückmeldung da.")})

    hard = [e for e in exercises if e["hard"] >= 2]
    for e in hard[:1]:
        tips.append({
            "kind": "hard", "level": "warn",
            "text": (f"{e['name']} war über mehrere Sätze schwer. Einmal auf der "
                     f"Stelle bleiben statt weiter zu steigern ist hier kein "
                     f"Rückschritt, sondern die Voraussetzung dafür.")})

    average = _average_volume(day)
    if average and volume > 0:
        change = (volume - average) / average * 100
        if change > VOLUME_NOTE_PCT:
            tips.append({
                "kind": "volume", "level": "good",
                "text": (f"Das Volumen lag {change:.0f} % über deinem Schnitt der "
                         f"letzten Wochen. Achte heute auf Schlaf und Eiweiß — "
                         f"gewachsen wird nach dem Training, nicht währenddessen.")})
        elif change < -VOLUME_NOTE_PCT:
            tips.append({
                "kind": "volume", "level": "info",
                "text": (f"Das Volumen lag {abs(change):.0f} % unter deinem Schnitt. "
                         f"Als Entlastungseinheit sinnvoll — zweimal hintereinander "
                         f"wäre es eher ein Zeichen für fehlende Erholung.")})

    with get_db() as db:
        stale = db.execute(
            """SELECT name, last_performed FROM exercises
               WHERE active=1 AND slot IN ('main','pullup')
                 AND (last_performed IS NULL OR last_performed < ?)
               ORDER BY last_performed IS NOT NULL, last_performed LIMIT 2""",
            ((dt.date.fromisoformat(day) - dt.timedelta(days=STALE_DAYS)).isoformat(),)
        ).fetchall()
    for row in stale:
        tips.append({
            "kind": "stale", "level": "info",
            "text": (f"{row['name']} war seit über {STALE_DAYS} Tagen nicht dran. "
                     f"Wenn die Übung noch zu deinem Plan gehört, gehört sie auch "
                     f"wieder in eine Einheit.")})

    return tips
