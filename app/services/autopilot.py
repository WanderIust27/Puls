"""Der Coach plant die Woche selbst — aus groben Wuenschen.

Statt Lauftage, Gym-Tage und Minuten einzeln einzustellen, gibst du an, was du
willst und was du an Zeit hast. Den Rest legt der Planer fest: welcher Tag
welche Einheit traegt, wie lang sie ist, welche Laufart, welche Uebungen mit
welchen Gewichten.

Gerechnet wird das im Code, aus deinen Zahlen: Trainingsbereitschaft und
Erholung entscheiden ueber die Dosis, die Belastung der Vorwochen ueber die
Steigerung, gemeldete Beschwerden ueber die Auswahl. Das Modell begruendet die
Woche hinterher, es legt sie nicht fest — sonst saehe jede Woche anders aus,
ohne dass sich etwas geaendert haette.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from ..db import get_db, get_setting, set_setting

log = logging.getLogger("puls.autopilot")

WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]

# Wie viel Prozent der Wunschdauer je nach Zustand geplant werden.
DOSE = {"frisch": 1.0, "normal": 0.9, "muede": 0.75, "erschoepft": 0.55}

FOCUS_PRESETS = {
    "run_faster": {
        "label": "Schneller laufen",
        "runs": 5, "gyms": 2, "long_run": True, "quality_runs": 2,
        "note": "Mehr Laufeinheiten, davon zwei mit Tempoanteil. Das Gym haelt "
                "die Kraft, es ist nicht der Schwerpunkt.",
    },
    "build_muscle": {
        "label": "Muskeln aufbauen",
        "runs": 3, "gyms": 4, "long_run": False, "quality_runs": 0,
        "note": "Vier Krafteinheiten, Laufen nur locker — harte Laeufe und "
                "Muskelaufbau ziehen an derselben Erholung.",
    },
    "balanced": {
        "label": "Beides halten",
        "runs": 4, "gyms": 3, "long_run": True, "quality_runs": 1,
        "note": "Die Aufteilung, mit der sich Ausdauer und Kraft nebeneinander "
                "entwickeln lassen, ohne dass eines leidet.",
    },
    "recover": {
        "label": "Ruhiger werden",
        "runs": 3, "gyms": 2, "long_run": False, "quality_runs": 0,
        "note": "Deutlich weniger, alles locker. Fuer Wochen nach einer harten "
                "Phase, im Urlaub oder wenn die Erholungswerte kippen.",
    },
}


def settings() -> dict[str, Any]:
    """Die Wuensche, die der Autopilot bekommt."""
    def _get(key: str, fallback: str) -> str:
        return get_setting(key, fallback) or fallback
    try:
        available = json.loads(_get("auto_days", json.dumps(WEEKDAYS)))
    except ValueError:
        available = list(WEEKDAYS)
    return {
        "enabled": _get("autopilot", "0") == "1",
        "focus": _get("auto_focus", "balanced"),
        "available_days": available if isinstance(available, list) else list(WEEKDAYS),
        "session_minutes": int(float(_get("auto_session_minutes", "60"))),
        "long_run_day": _get("auto_long_run_day", "So"),
        "wishes": _get("auto_wishes", ""),
        "presets": {k: {"label": v["label"], "note": v["note"]}
                    for k, v in FOCUS_PRESETS.items()},
    }


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    if "enabled" in data:
        set_setting("autopilot", "1" if data["enabled"] else "0")
    if data.get("focus") in FOCUS_PRESETS:
        set_setting("auto_focus", data["focus"])
    if isinstance(data.get("available_days"), list):
        days = [d for d in data["available_days"] if d in WEEKDAYS]
        set_setting("auto_days", json.dumps(days or WEEKDAYS))
    if data.get("session_minutes"):
        set_setting("auto_session_minutes",
                    str(max(20, min(180, int(data["session_minutes"])))))
    if data.get("long_run_day") in WEEKDAYS:
        set_setting("auto_long_run_day", data["long_run_day"])
    if data.get("wishes") is not None:
        set_setting("auto_wishes", str(data["wishes"])[:600])
    return settings()


def _condition() -> dict[str, Any]:
    """Wie belastbar bist du gerade? Entscheidet ueber die Dosis."""
    from . import metrics
    rec = metrics.recovery_series(21)
    latest, base = rec["latest"], rec["baselines"]
    reasons: list[str] = []
    penalty = 0

    readiness = latest.get("training_readiness")
    if readiness is not None:
        if readiness < 35:
            penalty += 2
            reasons.append(f"Trainingsbereitschaft {readiness:.0f} von 100")
        elif readiness < 55:
            penalty += 1
            reasons.append(f"Trainingsbereitschaft {readiness:.0f} von 100")

    hrv = base.get("hrv_avg") or {}
    if hrv.get("delta") is not None and hrv["delta"] < -3:
        penalty += 1
        reasons.append(f"HRV {hrv['delta']:.0f} ms unter deinem Schnitt")

    rhr = base.get("resting_hr") or {}
    if rhr.get("delta") is not None and rhr["delta"] > 2:
        penalty += 1
        reasons.append(f"Ruhepuls {rhr['delta']:.0f} Schläge darüber")

    sleep = base.get("sleep_seconds") or {}
    if sleep.get("last7") and sleep["last7"] < 6.5 * 3600:
        penalty += 1
        reasons.append(f"im Schnitt nur {sleep['last7'] / 3600:.1f} h Schlaf")

    acwr = metrics.acwr()
    if acwr is not None and acwr > 1.4:
        penalty += 1
        reasons.append(f"Belastungsverhältnis {acwr:.2f}")

    state = ("frisch" if penalty == 0 else "normal" if penalty == 1
             else "muede" if penalty <= 3 else "erschoepft")
    return {"state": state, "dose": DOSE[state], "reasons": reasons,
             "penalty": penalty}


def plan(start: dt.date | None = None, apply_it: bool = False) -> dict[str, Any]:
    """Die kommende Woche zusammenstellen."""
    from . import mood, planner, running
    cfg = settings()
    preset = FOCUS_PRESETS.get(cfg["focus"], FOCUS_PRESETS["balanced"])
    cond = _condition()
    adapt = mood.adaptations()

    start = start or (dt.date.today() + dt.timedelta(days=1))
    available = [d for d in WEEKDAYS if d in cfg["available_days"]]
    if not available:
        available = list(WEEKDAYS)

    # Dosis wirkt auf Umfang und Dauer, nicht nur auf eine der beiden Groessen
    runs = max(2, round(preset["runs"] * cond["dose"]))
    gyms = max(1, round(preset["gyms"] * cond["dose"]))
    minutes = max(25, round(cfg["session_minutes"] * cond["dose"]))
    quality = preset["quality_runs"] if cond["state"] in ("frisch", "normal") else 0
    long_run = preset["long_run"] and cond["state"] != "erschoepft"

    # Gym-Tage moeglichst gleichmaessig verteilen, damit zwischen zwei
    # Einheiten ein Tag liegt
    gym_days: list[str] = []
    if gyms:
        step = max(1, len(available) // gyms)
        gym_days = [available[min(i * step, len(available) - 1)] for i in range(gyms)]
        gym_days = list(dict.fromkeys(gym_days))

    long_day = cfg["long_run_day"] if cfg["long_run_day"] in available else \
        (available[-1] if available else "So")

    days: list[dict[str, Any]] = []
    run_left, quality_left = runs, quality
    for offset in range(7):
        date = start + dt.timedelta(days=offset)
        name = WEEKDAYS[date.weekday()]
        entry: dict[str, Any] = {"date": date.isoformat(), "weekday": name,
                                 "sessions": []}

        if name in available and run_left > 0:
            if long_run and name == long_day:
                entry["sessions"].append({
                    "sport": "running", "kind": "long",
                    "minutes": min(90, round(minutes * 1.5)),
                    "why": "Die lange Einheit macht die Grundlage breit."})
                long_run = False
            elif quality_left > 0 and name not in gym_days:
                entry["sessions"].append({
                    "sport": "running", "kind": "tempo", "minutes": minutes,
                    "why": "Tempoanteil — ohne harten Reiz bleibt das Tempo stehen."})
                quality_left -= 1
            else:
                entry["sessions"].append({
                    "sport": "running", "kind": "easy",
                    "minutes": max(20, round(minutes * 0.7)),
                    "why": "Locker. Der Großteil des Laufens gehört hierhin."})
            run_left -= 1

        if name in gym_days:
            entry["sessions"].append({
                "sport": "strength", "kind": "gym", "minutes": minutes,
                "why": "Krafteinheit nach deiner Übungsbibliothek."})

        if get_setting("evening_mobility", "1") == "1":
            entry["sessions"].append({
                "sport": "mobility", "kind": "yoga", "minutes": 12,
                "why": "Abends zum Runterkommen."})
        days.append(entry)

    created: list[int] = []
    if apply_it:
        for entry in days:
            for session in entry["sessions"]:
                workout = None
                if session["sport"] == "running":
                    workout = running.build_easy_run(session["minutes"], session["kind"])
                elif session["sport"] == "strength":
                    workout = planner.build_gym_session(session["minutes"])
                elif session["sport"] == "mobility":
                    workout = planner.build_evening_yoga(session["minutes"])
                if not workout:
                    continue
                with get_db() as db:
                    cur = db.execute(
                        """INSERT INTO planned_workouts(name, sport, planned_date,
                               description, steps_json, created_by)
                           VALUES(?,?,?,?,?, 'autopilot')""",
                        (workout.get("name", "Einheit"), session["sport"],
                         entry["date"], session["why"],
                         json.dumps({"steps": workout.get("steps", [])},
                                    ensure_ascii=False)))
                    created.append(int(cur.lastrowid or 0))
                session["workout_id"] = created[-1]

    total_minutes = sum(s["minutes"] for d in days for s in d["sessions"])
    return {
        "start": start.isoformat(),
        "focus": preset["label"],
        "focus_note": preset["note"],
        "condition": cond,
        "days": days,
        "runs": runs, "gyms": gyms, "minutes_per_session": minutes,
        "total_minutes": total_minutes,
        "adapted": adapt["summary"] if adapt["complaints"] else [],
        "applied": bool(apply_it),
        "created": created,
        "wishes": cfg["wishes"],
    }


def explain(week: dict[str, Any]) -> str:
    """Das Modell die Woche begruenden lassen — die Zahlen stehen fest."""
    lines = []
    for d in week["days"]:
        if d["sessions"]:
            what = ", ".join(f"{s['kind']} {s['minutes']} min" for s in d["sessions"])
            lines.append(f"{d['weekday']}: {what}")
    prompt = (
        f"Schwerpunkt: {week['focus']} — {week['focus_note']}\n"
        f"Zustand: {week['condition']['state']}"
        + (f" ({'; '.join(week['condition']['reasons'])})"
           if week["condition"]["reasons"] else "")
        + (f"\nBeschwerden: {'; '.join(week['adapted'])}" if week["adapted"] else "")
        + (f"\nWünsche: {week['wishes']}" if week["wishes"] else "")
        + "\nGeplant:\n" + "\n".join(lines)
        + "\n\nSchreibe drei bis vier Sätze, warum die Woche so aussieht. "
          "Sprich ihn direkt an, nenne den Zustand als Grund für die Dosis, "
          "keine Aufzählung — der Plan steht ohnehin darunter.")
    try:
        from .ollama_client import generate
        return generate(prompt, system=(
            "Du bist ein nüchterner Trainingscoach. Du erklärst knapp und "
            "ohne Motivationsfloskeln."))
    except Exception as e:
        log.debug("Ohne Modell begruendet: %s", e)
        return (f"{week['focus']}: {week['runs']} Läufe, {week['gyms']} Gym-Einheiten. "
                + ("Dosis reduziert, weil " + "; ".join(week["condition"]["reasons"])
                   if week["condition"]["reasons"] else "Volle Dosis, die Werte passen."))
