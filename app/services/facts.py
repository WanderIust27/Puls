"""Was feststeht, bevor das Modell etwas sagt.

Das lokale Modell rechnet unzuverlaessig. Alles Deterministische wird deshalb
hier in Python bestimmt und dem Modell als fertiges Ergebnis uebergeben — es
formuliert, es rechnet nicht.

Die Formeln stehen in 11_Coach_Playbook.md, Abschnitt 5. Die Zahlen dazu
stehen in app/constants.py, an genau einer Stelle.

Eine Groesse, die nicht vorliegt, faellt weg. Keine Platzhalter, keine
Nullwerte: Eine Zeile "Protein: 0 g" liest das Modell als Messwert und
empfiehlt darauf hin, mehr zu essen.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..constants import (EASY_SHARE_TARGET, INDIRECT_GROUPS,
                         INDIRECT_SET_WEIGHT, LONG_RUN_FACTOR,
                         LONG_RUN_WINDOW_DAYS,
                         PROTEIN_PER_KG, SLEEP_TARGET_H, STAGNATION_SESSIONS,
                         VOLUME_MAX_SETS, VOLUME_MIN_SETS)
from ..db import get_db, rows_to_dicts
from . import exercises as ex_lib

log = logging.getLogger("puls.facts")


def _de(value: float) -> str:
    """Zahl mit Komma. Der Block wird vorgelesen, nicht geparst."""
    return f"{value:g}".replace(".", ",")


def _week_start(today: dt.date) -> dt.date:
    return today - dt.timedelta(days=today.weekday())


# ----------------------------------------------------------- Satzvolumen

def weekly_volume(today: dt.date | None = None) -> dict[str, float]:
    """Harte Saetze je Muskelgruppe in der laufenden Woche, fraktional.

    Ein Satz zaehlt fuer die trainierte Gruppe voll und fuer die mitbelasteten
    Gruppen halb (Playbook Schritt 3). Saetze ohne Wiederholungen zaehlen
    nicht — die Uhr hat sie nicht gezaehlt, und ein Satz, von dem niemand
    weiss, ob er stattfand, ist kein Volumen.
    """
    today = today or dt.date.today()
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            """SELECT e.muscle_group AS grp, COUNT(*) AS n
               FROM exercise_sets s JOIN exercises e ON e.id = s.exercise_id
               WHERE s.day >= ? AND s.reps IS NOT NULL AND s.reps > 0
               GROUP BY e.muscle_group""", (_week_start(today).isoformat(),)
        ).fetchall())

    volume: dict[str, float] = {}
    for row in rows:
        group = row["grp"]
        if not group:
            continue
        volume[group] = volume.get(group, 0.0) + row["n"]
        for other in INDIRECT_GROUPS.get(group, ()):
            volume[other] = volume.get(other, 0.0) + row["n"] * INDIRECT_SET_WEIGHT
    return {g: round(v, 1) for g, v in volume.items() if v}


# -------------------------------------------------------------- Laufen

def run_limit(today: dt.date | None = None) -> dict[str, float] | None:
    """Laengster Lauf der letzten 30 Tage und das Limit fuer den naechsten."""
    today = today or dt.date.today()
    floor = (today - dt.timedelta(days=LONG_RUN_WINDOW_DAYS)).isoformat()
    with get_db() as db:
        row = db.execute(
            "SELECT MAX(distance_m) AS m FROM activities "
            "WHERE sport='running' AND substr(start_time,1,10) >= ? "
            "AND distance_m IS NOT NULL", (floor,)).fetchone()
    if not row or not row["m"]:
        return None
    longest = row["m"] / 1000.0
    return {"longest_km": round(longest, 1),
            "limit_km": round(longest * LONG_RUN_FACTOR, 1)}


# -------------------------------------------------------- Koerpergewicht

def weight_trend(today: dt.date | None = None) -> dict[str, Any] | None:
    """Gewicht und Veraenderungsrate — aus derselben Rechnung wie der Reiter.

    Frueher stand hier eine eigene Mittelung ueber die rohen Messwerte. Die
    ignorierte das Referenzfenster und die Tageszeit-Korrektur, und damit stand
    im Reiter eine andere Zahl als im Block, den das Modell zu lesen bekam.
    Zwei Zahlen fuer dasselbe sind schlimmer als eine ungenaue.
    """
    from . import vital

    data = vital.weight(today or dt.date.today())
    if not data.get("weeks") or data.get("rate_pct") is None:
        return None
    return {"now_kg": data["current_kg"], "rate_pct": data["rate_pct"],
            "rate_kg": data["rate_kg"], "goal": data["goal"]["label"],
            "verdict": data["verdict"], "weeks": data["weeks_used"]}


# --------------------------------------------- Laufen: Puls und VO2max

def running_state(today: dt.date | None = None) -> dict[str, Any] | None:
    """VO2max und Intensitaetsverteilung — aus derselben Rechnung wie der Reiter.

    Ohne das hier raet das Modell bei jeder Laufrage. Es erzaehlt dann etwas
    ueber Intervalle, ohne zu wissen, dass schon dreissig Prozent der Laufzeit
    hart sind — und widerspricht damit dem, was im Laufreiter steht.
    """
    from . import run_coach

    data = run_coach._read(today or dt.date.today())
    if not data["runs"]:
        return None
    vo2 = run_coach.vo2max(data, today or dt.date.today())
    hr = run_coach.pulse(data, today or dt.date.today())
    out: dict[str, Any] = {}
    if vo2.get("value"):
        out["vo2max"] = vo2["value"]
        out["vo2_band"] = vo2.get("band")
        out["vo2_change"] = (vo2["change"] or {}).get("delta")
        out["vo2_weeks"] = (vo2["change"] or {}).get("weeks")
    if hr.get("zones"):
        out["easy_share"] = hr["zones"]["easy_share"]
        out["hard_share"] = hr["zones"]["hard_share"]
    if hr.get("resting"):
        out["resting_hr"] = hr["resting"]["value"]
        out["resting_delta"] = hr["resting"]["delta"]
    return out or None


# ------------------------------------------------------------- Protein

def protein(today: dt.date | None = None) -> dict[str, float] | None:
    """Protein-Ist gegen Soll der letzten sieben Tage.

    Die Ernaehrungserfassung ist beim Umbau auf vier Reiter entfallen; die
    Tabelle meals gibt es noch, gefuellt wird sie nicht mehr. Solange dort
    nichts steht, faellt diese Zeile weg, statt eine Null zu melden.
    """
    today = today or dt.date.today()
    floor = (today - dt.timedelta(days=7)).isoformat()
    with get_db() as db:
        row = db.execute(
            "SELECT AVG(daily) AS ist FROM (SELECT day, SUM(protein_g) AS daily "
            "FROM meals WHERE day >= ? AND protein_g IS NOT NULL GROUP BY day)",
            (floor,)).fetchone()
        weight = db.execute(
            "SELECT weight_kg FROM body_metrics WHERE weight_kg IS NOT NULL "
            "ORDER BY measured_at DESC LIMIT 1").fetchone()
    if not row or not row["ist"] or not weight:
        return None
    return {"ist_g": round(row["ist"]),
            "soll_min_g": round(weight["weight_kg"] * PROTEIN_PER_KG[0]),
            "soll_max_g": round(weight["weight_kg"] * PROTEIN_PER_KG[1])}


# ----------------------------------------------------------- Stagnation

def stagnating(today: dt.date | None = None) -> list[dict[str, Any]]:
    """Uebungen, die seit mehreren Einheiten auf demselben Gewicht stehen."""
    today = today or dt.date.today()
    floor = (today - dt.timedelta(days=56)).isoformat()
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            """SELECT e.name, e.id, s.day, MAX(s.weight_kg) AS top
               FROM exercise_sets s JOIN exercises e ON e.id = s.exercise_id
               WHERE s.day >= ? AND s.weight_kg IS NOT NULL AND s.weight_kg > 0
               GROUP BY e.id, s.day ORDER BY e.id, s.day DESC""",
            (floor,)).fetchall())

    by_exercise: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        by_exercise.setdefault(row["id"], []).append(row)

    out = []
    for days in by_exercise.values():
        if len(days) < STAGNATION_SESSIONS:
            continue
        recent = days[:STAGNATION_SESSIONS]
        if len({d["top"] for d in recent}) == 1:
            out.append({"name": recent[0]["name"], "weight_kg": recent[0]["top"],
                        "sessions": len(recent)})
    return sorted(out, key=lambda x: x["name"])


# --------------------------------------------------------------- Schlaf

def sleep_average(today: dt.date | None = None) -> dict[str, float] | None:
    today = today or dt.date.today()
    with get_db() as db:
        row = db.execute(
            "SELECT AVG(sleep_seconds) AS s, COUNT(*) AS n FROM daily_metrics "
            "WHERE day >= ? AND sleep_seconds IS NOT NULL",
            ((today - dt.timedelta(days=7)).isoformat(),)).fetchone()
    if not row or not row["s"] or row["n"] < 3:
        return None
    return {"hours": round(row["s"] / 3600.0, 1), "nights": row["n"]}


# ------------------------------------------------------- Der Textblock

def computed_block(today: dt.date | None = None) -> str:
    """Alles Gerechnete als kompakter Text fuer den Prompt.

    Reihenfolge nach Wichtigkeit: Was das Training steuert, steht oben.
    """
    today = today or dt.date.today()
    lines: list[str] = []

    volume = weekly_volume(today)
    if volume:
        parts = []
        for group, sets in sorted(volume.items(), key=lambda kv: -kv[1]):
            label = ex_lib.MUSCLE_LABELS.get(group, group)
            mark = ("unter dem Korridor" if sets < VOLUME_MIN_SETS else
                    "über dem Korridor" if sets > VOLUME_MAX_SETS else "im Korridor")
            parts.append(f"{label} {_de(sets)} ({mark})")
        lines.append(
            f"- Harte Sätze diese Woche, indirekte zu {_de(INDIRECT_SET_WEIGHT)} "
            f"gezählt (Korridor {VOLUME_MIN_SETS}–{VOLUME_MAX_SETS}): "
            + ", ".join(parts))

    runs = run_limit(today)
    if runs:
        lines.append(
            f"- Längster Lauf der letzten {LONG_RUN_WINDOW_DAYS} Tage: "
            f"{_de(runs['longest_km'])} km. Der nächste lange Lauf darf höchstens "
            f"{_de(runs['limit_km'])} km lang sein "
            f"({_de(LONG_RUN_FACTOR)} × längster Lauf).")

    weight = weight_trend(today)
    if weight:
        way = ("steigend" if weight["rate_pct"] > 0 else "fallend"
               if weight["rate_pct"] < 0 else "unverändert")
        lines.append(
            f"- Körpergewicht: {_de(weight['now_kg'])} kg, über "
            f"{weight['weeks']} Wochen {way} mit "
            f"{_de(abs(weight['rate_pct']))} % pro Woche "
            f"({_de(abs(weight['rate_kg']))} kg). Ziel {weight['goal']} — "
            f"Einordnung: {weight['verdict']}.")

    run = running_state(today)
    if run:
        if "vo2max" in run:
            trend = ""
            if run.get("vo2_change") is not None and run.get("vo2_weeks"):
                delta = run["vo2_change"]
                way = ("gestiegen" if delta > 0 else "gefallen" if delta < 0
                       else "unverändert")
                trend = (f", über {run['vo2_weeks']} Wochen "
                         + (f"um {_de(abs(delta))} Punkte {way}" if delta
                            else way))
            lines.append(
                f"- VO2max: {_de(run['vo2max'])} ml/kg/min"
                + (f" (für Alter und Geschlecht {run['vo2_band']})"
                   if run.get("vo2_band") else "") + trend + ".")
        if "easy_share" in run:
            lines.append(
                f"- Intensität der letzten vier Wochen: {run['easy_share']} % der "
                f"Laufzeit locker (Zone 1–2), {run['hard_share']} % hart "
                f"(Zone 4–5). Ziel: {round(EASY_SHARE_TARGET * 100)} % locker.")
        if run.get("resting_delta") is not None:
            way = ("gestiegen" if run["resting_delta"] > 0 else "gesunken"
                   if run["resting_delta"] < 0 else "unverändert")
            lines.append(
                f"- Ruhepuls: {run['resting_hr']} bpm, gegenüber dem Monat "
                f"davor um {_de(abs(run['resting_delta']))} Schläge {way}.")

    prot = protein(today)
    if prot:
        lines.append(
            f"- Protein im Schnitt der letzten sieben Tage: {_de(prot['ist_g'])} g "
            f"gegen ein Ziel von {_de(prot['soll_min_g'])}–{_de(prot['soll_max_g'])} g.")

    stuck = stagnating(today)
    if stuck:
        named = ", ".join(f"{s['name']} ({_de(s['weight_kg'])} kg)" for s in stuck[:5])
        lines.append(
            f"- Seit {STAGNATION_SESSIONS} Einheiten unverändert: {named}.")

    sleep = sleep_average(today)
    if sleep:
        judgement = ("unter dem Ziel" if sleep["hours"] < SLEEP_TARGET_H[0]
                     else "im Zielbereich")
        lines.append(
            f"- Schlaf im Schnitt der letzten {sleep['nights']} Nächte: "
            f"{_de(sleep['hours'])} h ({judgement}, Ziel "
            f"{_de(SLEEP_TARGET_H[0])}–{_de(SLEEP_TARGET_H[1])} h).")

    return "\n".join(lines)
