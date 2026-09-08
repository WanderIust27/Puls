"""Kennzahlen für Dashboard und Coach-Kontext."""
from __future__ import annotations

import datetime as dt
import json
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts


def _week_start(day: dt.date) -> dt.date:
    return day - dt.timedelta(days=day.weekday())


def streak_weeks() -> int:
    """Wie viele Wochen in Folge (inkl. aktueller) das Wochenziel erreicht wurde.
    Die laufende Woche zählt schon, sobald mindestens 1 Training drin ist."""
    target = int(get_setting("weekly_workout_target", "4") or 4)
    with get_db() as db:
        rows = db.execute(
            "SELECT date(start_time) AS d FROM activities "
            "WHERE start_time >= date('now', '-365 days')"
        ).fetchall()
    days = [dt.date.fromisoformat(r["d"]) for r in rows if r["d"]]
    per_week: dict[dt.date, int] = {}
    for d in days:
        per_week[_week_start(d)] = per_week.get(_week_start(d), 0) + 1
    this_week = _week_start(dt.date.today())
    streak = 1 if per_week.get(this_week, 0) >= 1 else 0
    # rückwärts durch abgeschlossene Wochen; die laufende Woche zählt ab dem
    # ersten Training mit, eine leere laufende Woche bricht den Streak nicht ab
    week = this_week - dt.timedelta(days=7)
    while per_week.get(week, 0) >= target:
        streak += 1
        week -= dt.timedelta(days=7)
    return streak


def load_series(days: int = 42) -> list[dict[str, Any]]:
    """Tägliche Trainingslast (Garmin-Load, sonst grobe Schätzung aus Dauer+HF)."""
    since = (dt.date.today() - dt.timedelta(days=days - 1)).isoformat()
    with get_db() as db:
        rows = db.execute(
            "SELECT date(start_time) AS d, "
            "SUM(COALESCE(training_load, "
            "    (duration_s/60.0) * CASE WHEN avg_hr IS NULL THEN 0.6 "
            "        ELSE MAX(0.3, (avg_hr - 60) / 100.0) END)) AS load, "
            "COUNT(*) AS n, SUM(duration_s) AS dur "
            "FROM activities WHERE date(start_time) >= ? "
            "GROUP BY date(start_time)", (since,)
        ).fetchall()
    by_day = {r["d"]: r for r in rows}
    out = []
    for i in range(days):
        day = (dt.date.today() - dt.timedelta(days=days - 1 - i)).isoformat()
        r = by_day.get(day)
        out.append({
            "day": day,
            "load": round(r["load"], 1) if r and r["load"] else 0,
            "count": r["n"] if r else 0,
            "duration_s": r["dur"] if r else 0,
        })
    return out


def acwr() -> float | None:
    """Acute:Chronic Workload Ratio — 7-Tage-Last vs. 28-Tage-Schnitt."""
    series = load_series(28)
    loads = [p["load"] for p in series]
    acute = sum(loads[-7:]) / 7.0
    chronic = sum(loads) / 28.0
    if chronic <= 0:
        return None
    return round(acute / chronic, 2)


def week_summary() -> dict[str, Any]:
    monday = _week_start(dt.date.today()).isoformat()
    with get_db() as db:
        row = db.execute(
            "SELECT COUNT(*) AS n, COALESCE(SUM(duration_s),0) AS dur, "
            "COALESCE(SUM(distance_m),0) AS dist, COALESCE(SUM(calories),0) AS kcal "
            "FROM activities WHERE date(start_time) >= ?", (monday,)
        ).fetchone()
        by_sport = db.execute(
            "SELECT sport, COUNT(*) AS n FROM activities "
            "WHERE date(start_time) >= ? GROUP BY sport", (monday,)
        ).fetchall()
    target = int(get_setting("weekly_workout_target", "4") or 4)
    return {
        "workouts": row["n"], "target": target,
        "duration_s": row["dur"], "distance_m": row["dist"], "calories": row["kcal"],
        "by_sport": {r["sport"]: r["n"] for r in by_sport},
    }


def weight_series(days: int = 120) -> list[dict[str, Any]]:
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        rows = db.execute(
            "SELECT day, AVG(weight_kg) AS w, AVG(body_fat_pct) AS bf, "
            "AVG(muscle_kg) AS m "
            "FROM body_metrics WHERE day >= ? AND weight_kg IS NOT NULL "
            "GROUP BY day ORDER BY day", (since,)
        ).fetchall()
    return [{"day": r["day"], "weight_kg": round(r["w"], 1),
             "body_fat_pct": round(r["bf"], 1) if r["bf"] else None,
             "muscle_kg": round(r["m"], 1) if r["m"] else None} for r in rows]


def body_composition() -> dict[str, Any]:
    """Neueste Körperwerte plus Veränderung über die letzten 30 Tage.

    Gewicht und Körperfett können aus verschiedenen Quellen kommen (Waage,
    Garmin, manuell) und nicht jede Messung enthält alles. Genommen wird
    deshalb je Feld der aktuellste Wert, der überhaupt gefüllt ist — sonst
    fehlt Körperfett nur, weil die letzte Messung ohne Impedanz lief.
    """
    fields = ("weight_kg", "body_fat_pct", "muscle_kg", "water_pct")
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT * FROM body_metrics WHERE day >= date('now','-180 days') "
            "ORDER BY day DESC, id DESC").fetchall())
    if not rows:
        return {"latest": None, "delta": {}}

    latest: dict[str, Any] = {"day": rows[0]["day"]}
    for f in fields:
        latest[f] = next((r[f] for r in rows if r.get(f) is not None), None)

    # Vergleichswert: ältester Eintrag innerhalb der letzten 30 Tage
    cutoff = (dt.date.today() - dt.timedelta(days=30)).isoformat()
    older = [r for r in rows if r["day"] <= cutoff] or rows[-1:]
    delta: dict[str, Any] = {}
    for f in fields:
        then = next((r[f] for r in older if r.get(f) is not None), None)
        now = latest.get(f)
        if then is not None and now is not None:
            delta[f] = round(now - then, 1)
    return {"latest": latest, "delta": delta}


def latest_daily() -> dict[str, Any] | None:
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM daily_metrics ORDER BY day DESC LIMIT 1"
        ).fetchone()
    return dict(row) if row else None


def coach_context() -> dict[str, Any]:
    """Kompakter Datenkontext, der dem LLM mitgegeben wird."""
    with get_db() as db:
        recent = rows_to_dicts(db.execute(
            "SELECT name, sport, start_time, duration_s, distance_m, avg_hr, "
            "training_load, notes FROM activities "
            "ORDER BY start_time DESC LIMIT 10").fetchall())
        nutrition = rows_to_dicts(db.execute(
            "SELECT day, kcal, protein_g FROM nutrition_log "
            "ORDER BY day DESC LIMIT 7").fetchall())
        daily = rows_to_dicts(db.execute(
            "SELECT day, sleep_seconds, sleep_score, hrv_avg, hrv_status, "
            "training_readiness FROM daily_metrics ORDER BY day DESC LIMIT 7").fetchall())
        planned = rows_to_dicts(db.execute(
            "SELECT name, sport, planned_date, status FROM planned_workouts "
            "WHERE status IN ('planned','pushed') AND "
            "(planned_date IS NULL OR planned_date >= date('now','-1 day')) "
            "ORDER BY planned_date LIMIT 7").fetchall())
    goals = json.loads(get_setting("goals", "[]") or "[]")
    profile = json.loads(get_setting("profile", "{}") or "{}")
    weights = weight_series(60)

    # Wochenstruktur, Laufzonen, Übungen mit aktuellen Arbeitsgewichten
    try:
        from . import exercises as ex_lib
        from . import planner
        overview = planner.week_overview()
        lib = [
            {"name": e["name"], "block": e.get("slot"),
             "muskel": e["muscle_group"], "geraet": e["equipment"],
             "aktuell": (f"{e['weight_kg']} kg × {e['target_reps']}"
                         if e["mode"] == "reps" and e.get("weight_kg")
                         else (f"{e['target_reps']} Wdh." if e["mode"] == "reps"
                               else f"{e.get('target_duration_s')} s")),
             "zuletzt_vor_tagen": ex_lib.days_since(e.get("last_performed"))}
            for e in ex_lib.list_exercises(only_active=True)
        ]
    except Exception:
        overview, lib = {}, []

    return {
        "week_structure": overview,
        "exercise_library": lib,
        "date": dt.date.today().isoformat(),
        "goals": goals,
        "profile": profile,
        "weekly_target": get_setting("weekly_workout_target", "4"),
        "kcal_target": get_setting("kcal_target", ""),
        "protein_target": get_setting("protein_target", ""),
        "week": week_summary(),
        "streak_weeks": streak_weeks(),
        "acwr": acwr(),
        "recent_activities": recent,
        "recent_nutrition": nutrition,
        "recent_daily_metrics": daily,
        "planned_workouts": planned,
        "weight_first": weights[0] if weights else None,
        "weight_last": weights[-1] if weights else None,
    }


# ------------------------------------------------------------- Erholung

# Ein Zusammenhang wird nur gemeldet, wenn er beides ist: deutlich genug und
# auf genug Tagen beobachtet. Sonst erzaehlt die Auswertung Zufall als Einsicht.
MIN_DAYS_FOR_LINK = 14
MIN_CORRELATION = 0.35

RECOVERY_FIELDS = (
    "sleep_seconds", "sleep_score", "sleep_deep_s", "sleep_light_s",
    "sleep_rem_s", "sleep_awake_s", "respiration_avg", "spo2_avg",
    "hrv_avg", "hrv_status", "hrv_weekly_avg", "hrv_baseline_low",
    "hrv_baseline_high", "stress_avg", "stress_max", "stress_rest_min",
    "stress_low_min", "stress_medium_min", "stress_high_min",
    "body_battery_min", "body_battery_max", "body_battery_wake",
    "body_battery_charged", "body_battery_drained", "hr_min", "hr_max",
    "resting_hr", "training_readiness", "steps",
)


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    """Pearson — bewusst schlicht, es geht nur um die Richtung eines Trends."""
    n = len(xs)
    if n < MIN_DAYS_FOR_LINK:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = (sum(d * d for d in dx) ** 0.5) * (sum(d * d for d in dy) ** 0.5)
    if denom == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / denom


def _pairs(rows: list[dict[str, Any]], left: str, right: str,
           shift: int = 0) -> tuple[list[float], list[float]]:
    """Wertepaare zweier Spalten. shift=1 vergleicht mit dem Folgetag."""
    xs, ys = [], []
    for i, row in enumerate(rows):
        j = i + shift
        if j >= len(rows):
            break
        a, b = row.get(left), rows[j].get(right)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            xs.append(float(a))
            ys.append(float(b))
    return xs, ys


def recovery_series(days: int = 30) -> dict[str, Any]:
    """Erholungswerte als Zeitreihe, mit Basislinien und belegbaren Bezuegen."""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    long_since = (dt.date.today() - dt.timedelta(days=max(days, 90))).isoformat()
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT * FROM daily_metrics WHERE day >= ? ORDER BY day",
            (since,)).fetchall())
        history = rows_to_dicts(db.execute(
            "SELECT day, hrv_avg, resting_hr, sleep_seconds, body_battery_max "
            "FROM daily_metrics WHERE day >= ? ORDER BY day",
            (long_since,)).fetchall())

    def _recent(field: str, n: int) -> float | None:
        values = [r[field] for r in history[-n:]
                  if isinstance(r.get(field), (int, float))]
        return _mean(values)

    baselines: dict[str, Any] = {}
    for field in ("hrv_avg", "resting_hr", "sleep_seconds", "body_battery_max"):
        short, long = _recent(field, 7), _recent(field, 60)
        baselines[field] = {
            "last7": round(short, 1) if short is not None else None,
            "baseline": round(long, 1) if long is not None else None,
            "delta": round(short - long, 1)
            if short is not None and long is not None else None,
        }

    latest = rows[-1] if rows else {}
    observations: list[dict[str, str]] = []

    # HRV gegen die von Garmin gelieferte persoenliche Basislinie
    hrv, low = latest.get("hrv_avg"), latest.get("hrv_baseline_low")
    if isinstance(hrv, (int, float)) and isinstance(low, (int, float)) and hrv < low:
        observations.append({
            "kind": "hrv", "level": "warn",
            "text": (f"Deine HRV liegt mit {hrv:.0f} ms unter deiner Basislinie "
                     f"({low:.0f} ms). Das ist das Zeichen, auf das es sich zu "
                     f"achten lohnt: heute lieber locker.")})

    rhr = baselines["resting_hr"]
    if rhr["delta"] is not None and rhr["delta"] >= 3:
        observations.append({
            "kind": "resting_hr", "level": "warn",
            "text": (f"Dein Ruhepuls liegt diese Woche {rhr['delta']:.0f} Schläge "
                     f"über deinem Schnitt. Typisch nach harten Wochen — oder "
                     f"wenn sich etwas anbahnt.")})
    elif rhr["delta"] is not None and rhr["delta"] <= -2:
        observations.append({
            "kind": "resting_hr", "level": "good",
            "text": (f"Dein Ruhepuls ist um {abs(rhr['delta']):.0f} Schläge "
                     f"gesunken. Das ist der ehrlichste Fortschrittsanzeiger, "
                     f"den du hast.")})

    # Schlaf heute -> HRV morgen. Nur melden, wenn der Zusammenhang belastbar ist.
    xs, ys = _pairs(rows, "sleep_seconds", "hrv_avg", shift=1)
    r = _correlation(xs, ys)
    if r is not None and r >= MIN_CORRELATION:
        observations.append({
            "kind": "sleep_hrv", "level": "info",
            "text": (f"In den letzten {len(xs)} Tagen ging längerer Schlaf bei dir "
                     f"mit besserer HRV am Folgetag einher. Kein Naturgesetz, "
                     f"aber bei dir gut sichtbar.")})

    xs, ys = _pairs(rows, "stress_avg", "sleep_score")
    r = _correlation(xs, ys)
    if r is not None and r <= -MIN_CORRELATION:
        observations.append({
            "kind": "stress_sleep", "level": "info",
            "text": ("Tage mit hohem Stressmittel enden bei dir messbar häufiger "
                     "in schlechterem Schlaf.")})

    return {
        "days": days,
        "series": [{k: r.get(k) for k in ("day",) + RECOVERY_FIELDS} for r in rows],
        "latest": latest,
        "baselines": baselines,
        "observations": observations,
        "hint": None if rows else
        ("Noch keine Erholungsdaten. Sie kommen mit dem nächsten Garmin-Sync — "
         "für die Vergangenheit hilft Mehr → Garmin → Verlauf nachladen."),
    }
