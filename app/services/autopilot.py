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
    def _days(key: str) -> list[str]:
        try:
            value = json.loads(_get(key, "[]"))
        except ValueError:
            return []
        return [d for d in value if d in WEEKDAYS] if isinstance(value, list) else []

    # Die Wochenstruktur ist dieselbe, die auch sonst gilt — der Autopilot
    # erfindet keine zweite. Wer Mo/Mi/Fr ins Gym will, traegt das einmal ein.
    run_days, gym_days = _days("run_days"), _days("gym_days")
    available = sorted(set(run_days) | set(gym_days) or set(_days("auto_days")),
                       key=WEEKDAYS.index)
    return {
        "enabled": _get("autopilot", "0") == "1",
        "focus": _get("auto_focus", "balanced"),
        "run_days": run_days,
        "gym_days": gym_days,
        "available_days": available or list(WEEKDAYS),
        "session_minutes": int(float(_get("auto_session_minutes", "60"))),
        "gym_minutes": int(float(_get("gym_minutes", "75"))),
        "long_run_day": _get("auto_long_run_day", "So"),
        "evening_mobility": _get("evening_mobility", "1") == "1",
        "wishes": _get("auto_wishes", ""),
        "presets": {k: {"label": v["label"], "note": v["note"]}
                    for k, v in FOCUS_PRESETS.items()},
    }


def save_settings(data: dict[str, Any]) -> dict[str, Any]:
    if "enabled" in data:
        set_setting("autopilot", "1" if data["enabled"] else "0")
    if data.get("focus") in FOCUS_PRESETS:
        set_setting("auto_focus", data["focus"])
    for field, key in (("run_days", "run_days"), ("gym_days", "gym_days"),
                       ("available_days", "auto_days")):
        if isinstance(data.get(field), list):
            days = sorted({d for d in data[field] if d in WEEKDAYS},
                          key=WEEKDAYS.index)
            set_setting(key, json.dumps(days))
    if data.get("gym_minutes"):
        set_setting("gym_minutes", str(max(20, min(180, int(data["gym_minutes"])))))
    if "evening_mobility" in data:
        set_setting("evening_mobility", "1" if data["evening_mobility"] else "0")
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


def _run_kinds(count: int, quality: int, long_run: bool,
               trend: dict[str, Any], goal: dict[str, Any]) -> list[str]:
    """Welche Laufarten die Woche traegt — nach dem, was gerade fehlt.

    Die Reihenfolge ist die Rangfolge: Der lange Lauf zuerst, weil er am
    schwersten nachzuholen ist, dann die harten Reize, dann die lockeren.
    """
    kinds: list[str] = []
    if long_run:
        kinds.append("long")

    # Fehlt seit vier Wochen jeder harte Lauf, kommt einer dazu — auch bei
    # einem Schwerpunkt, der eigentlich keinen vorsieht. Umgekehrt faellt
    # Tempo weg, wenn ohnehin zu viel hart gelaufen wurde.
    hard_missing = trend.get("runs_recent") and not trend.get("hard_runs")
    too_hard = (trend.get("hard_runs") or 0) > (trend.get("runs_recent") or 0) * 0.4
    if hard_missing and not quality:
        quality = 1
    if too_hard:
        quality = 0

    wants_tempo = "tempo" in goal.get("runs", [])
    for i in range(quality):
        # Intervalle sind der haertere Reiz; hoechstens einer pro Woche.
        kinds.append("tempo" if (i == 0 or not wants_tempo) else "interval")

    while len(kinds) < count:
        kinds.append("easy")
    return kinds[:count]


def plan(start: dt.date | None = None, apply_it: bool = False) -> dict[str, Any]:
    """Die kommende Woche zusammenstellen."""
    from . import mood, planner, running, trends
    cfg = settings()
    preset = FOCUS_PRESETS.get(cfg["focus"], FOCUS_PRESETS["balanced"])
    cond = _condition()
    adapt = mood.adaptations()
    trend = trends.summary()
    goal = trend["goal"]

    start = start or (dt.date.today() + dt.timedelta(days=1))

    # 1. Wo darf was liegen? Ausdrueckliche Tage schlagen jede Verteilung.
    run_days = list(cfg["run_days"])
    gym_days = list(cfg["gym_days"])
    available = [d for d in WEEKDAYS if d in (set(run_days) | set(gym_days))] \
        or [d for d in WEEKDAYS if d in cfg["available_days"]] or list(WEEKDAYS)

    # 2. Wie viel? Die Dosis wirkt auf Umfang UND Dauer, nicht nur auf eines.
    minutes = max(25, round(cfg["session_minutes"] * cond["dose"]))
    gym_minutes = max(25, round(cfg["gym_minutes"] * cond["dose"]))
    if run_days or gym_days:
        # Deine Tage sind die Vorgabe. Nur wenn die Erholung kippt, wird
        # gekuerzt — und dann sichtbar, nicht stillschweigend.
        runs = len(run_days) if run_days else max(2, round(preset["runs"] * cond["dose"]))
        gyms = len(gym_days) if gym_days else max(1, round(preset["gyms"] * cond["dose"]))
        dropped: list[str] = []
        if cond["state"] == "erschoepft" and len(run_days) > 2:
            dropped = run_days[len(run_days) - 1:]
            run_days, runs = run_days[:-1], runs - 1
        if cond["state"] == "erschoepft" and len(gym_days) > 1:
            dropped += gym_days[len(gym_days) - 1:]
            gym_days, gyms = gym_days[:-1], gyms - 1
    else:
        runs = max(2, round(preset["runs"] * cond["dose"]))
        gyms = max(1, round(preset["gyms"] * cond["dose"]))
        dropped = []
        step = max(1, len(available) // max(1, gyms))
        gym_days = list(dict.fromkeys(
            available[min(i * step, len(available) - 1)] for i in range(gyms)))
        run_days = [d for d in available if d not in gym_days][:runs] or available[:runs]

    quality = preset["quality_runs"] if cond["state"] in ("frisch", "normal") else 0
    long_run = preset["long_run"] and cond["state"] != "erschoepft"
    long_day = cfg["long_run_day"] if cfg["long_run_day"] in run_days else \
        (run_days[-1] if run_days else None)

    # 3. Was genau? Die Laufarten nach dem, was dem Training fehlt; die
    #    Muskelgruppen nach dem gerechneten Bedarf.
    kinds = _run_kinds(len(run_days), quality, long_run, trend["running"], goal)
    ordered_runs = ([long_day] if long_day and long_day in run_days else []) + \
        [d for d in run_days if d != long_day]
    kind_for = {}
    for day, kind in zip(ordered_runs, kinds):
        kind_for[day] = kind
    emphasis = trend["muscles"]["focus"]
    emphasis_labels = [g["label"] for g in trend["muscles"]["groups"]
                       if g["key"] in emphasis]

    days: list[dict[str, Any]] = []
    for offset in range(7):
        date = start + dt.timedelta(days=offset)
        name = WEEKDAYS[date.weekday()]
        entry: dict[str, Any] = {"date": date.isoformat(), "weekday": name,
                                 "sessions": []}

        if name in kind_for:
            kind = kind_for[name]
            entry["sessions"].append({
                "sport": "running", "kind": kind,
                "minutes": (min(95, round(minutes * 1.5)) if kind == "long"
                            else minutes if kind in ("tempo", "interval")
                            else max(20, round(minutes * 0.7))),
                "why": _run_why(kind, trend["running"], goal)})

        if name in gym_days:
            entry["sessions"].append({
                "sport": "strength", "kind": "gym", "minutes": gym_minutes,
                "emphasis": emphasis,
                "why": (f"Schwerpunkt {', '.join(emphasis_labels)} — "
                        + "; ".join(
                            r for g in trend["muscles"]["groups"]
                            if g["key"] in emphasis for r in g["reasons"][:1])
                        if emphasis_labels
                        else "Krafteinheit nach deiner Übungsbibliothek.")})

        if cfg["evening_mobility"]:
            entry["sessions"].append({
                "sport": "mobility", "kind": "yoga", "minutes": 12,
                "why": "Abends zum Runterkommen."})
        days.append(entry)

    created: list[int] = []
    replaced = 0
    if apply_it:
        # Erst aufraeumen, dann anlegen. Ohne das legt jeder Klick auf
        # "Übernehmen" eine weitere komplette Woche OBEN DRAUF — nach dreimal
        # Ausprobieren stehen einundzwanzig Einheiten im Plan. Entfernt wird
        # nur, was noch offen ist und von einem Planer stammt: Erledigtes,
        # bereits an die Uhr Geschicktes und selbst Angelegtes bleibt.
        last = (start + dt.timedelta(days=6)).isoformat()
        yesterday = (dt.date.today() - dt.timedelta(days=1)).isoformat()
        with get_db() as db:
            replaced = db.execute(
                "DELETE FROM planned_workouts "
                "WHERE status='planned' AND created_by IN ('autopilot','coach') "
                "AND planned_date BETWEEN ? AND ?",
                (start.isoformat(), last)).rowcount
            # Was vergangen und nie erledigt wurde, kann nicht mehr stattfinden.
            # Stehen lassen hiesse, den Plan mit Unerledigbarem zu fuellen.
            db.execute(
                "DELETE FROM planned_workouts "
                "WHERE status='planned' AND created_by IN ('autopilot','coach') "
                "AND planned_date IS NOT NULL AND planned_date <= ?", (yesterday,))
        for entry in days:
            for session in entry["sessions"]:
                workout = _build(session, planner, running)
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
        "run_days": run_days, "gym_days": gym_days, "dropped_days": dropped,
        "runs": len(kind_for), "gyms": len(gym_days),
        "mobility_count": sum(1 for d in days for s in d["sessions"]
                              if s["sport"] == "mobility"),
        "minutes_per_session": minutes, "gym_minutes": gym_minutes,
        "total_minutes": total_minutes,
        "emphasis": emphasis, "emphasis_labels": emphasis_labels,
        "run_needs": trend["running"]["needs"],
        "goal": goal,
        "adapted": adapt["summary"] if adapt["complaints"] else [],
        "applied": bool(apply_it),
        "created": created,
        "replaced": replaced,
        "wishes": cfg["wishes"],
    }


RUN_WHY = {
    "long": "Die lange Einheit macht die Grundlage breit.",
    "tempo": "Tempoblock an der Schwelle — ohne harten Reiz bleibt das Tempo stehen.",
    "interval": "Kurze harte Abschnitte — der stärkste Reiz für die Ausdauer.",
    "easy": "Locker. Der Großteil des Laufens gehört hierhin.",
}


def _run_why(kind: str, trend: dict[str, Any], goal: dict[str, Any]) -> str:
    """Begruendung aus den Zahlen, nicht aus einer festen Liste allein."""
    why = RUN_WHY.get(kind, RUN_WHY["easy"])
    if kind == "long" and trend.get("longest_recent") is not None:
        why += f" Deine längste der letzten vier Wochen: {trend['longest_recent']} km."
    elif kind in ("tempo", "interval") and not trend.get("hard_runs"):
        why += " In vier Wochen lag kein Lauf im harten Bereich."
    elif kind == "easy" and trend.get("hard_runs"):
        why += (f" Von {trend.get('runs_recent', 0)} Läufen waren "
                f"{trend['hard_runs']} hart.")
    if goal.get("recognised"):
        why += f" Ziel: {', '.join(goal['recognised'][:2])}."
    return why


def _build(session: dict[str, Any], planner: Any, running: Any) -> dict[str, Any] | None:
    """Aus einer geplanten Einheit das fertige Workout bauen."""
    kind, minutes = session["kind"], session["minutes"]
    if session["sport"] == "running":
        # Jede Laufart hat einen eigenen Bauplan. Sie alle als lockeren Lauf
        # zu bauen und nur das Tempofenster zu wechseln, waere kein Tempolauf.
        if kind == "long":
            return running.build_long_run(minutes)
        if kind == "tempo":
            return running.build_tempo_run(minutes)
        if kind == "interval":
            return running.build_interval_run(minutes)
        return running.build_easy_run(minutes, "easy")
    if session["sport"] == "strength":
        return planner.build_gym_session(minutes, emphasis=session.get("emphasis"))
    if session["sport"] == "mobility":
        return planner.build_evening_yoga(minutes)
    return None


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
