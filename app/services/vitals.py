"""Laktatschwelle und Stress — die zwei Vitalwerte, die Handlung nach sich ziehen.

Die Schwelle ist das Tempo, das du noch etwa eine Stunde durchhältst. Darüber
sammelt sich Laktat schneller an, als der Körper es abbaut; darunter läuft es
im Gleichgewicht. Sie ist der wichtigste einzelne Wert für die Trainingsplanung
— und zugleich einer, den man ohne Labor nur schätzen kann.

PULS macht daraus keine Wissenschaft, die es nicht ist: Wenn die Uhr einen Wert
geliefert hat, gilt der. Sonst wird aus deinem kalibrierten Schwellentempo und
dem Puls, den du bei genau diesem Tempo tatsächlich läufst, geschätzt — und es
steht dabei, dass es eine Schätzung ist und woraus sie stammt.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts

log = logging.getLogger("puls.vitals")

# Wie weit ein Lauf vom Schwellentempo abweichen darf, um noch als
# Schwellenlauf zu zaehlen (Sekunden je Kilometer).
PACE_WINDOW_S = 20
MIN_RUNS = 3
MIN_DISTANCE_M = 2500


def threshold() -> dict[str, Any]:
    """Laktatschwelle: Puls und Tempo, mit Herkunft."""
    from . import running

    stored_hr = get_setting("lthr_bpm", "")
    paces = running.current_paces()
    pace_s = paces["tempo"] if paces else None

    # Laeufe im Schwellenbereich suchen: gleiches Tempo, echter Puls.
    matched: list[dict[str, Any]] = []
    if pace_s:
        since = (dt.date.today() - dt.timedelta(days=120)).isoformat()
        with get_db() as db:
            runs = rows_to_dicts(db.execute(
                """SELECT substr(start_time,1,10) AS day, distance_m, duration_s,
                          avg_hr, max_hr
                   FROM activities
                   WHERE sport='running' AND avg_hr IS NOT NULL
                     AND distance_m > ? AND substr(start_time,1,10) >= ?
                   ORDER BY start_time DESC""",
                (MIN_DISTANCE_M, since)).fetchall())
        for r in runs:
            if not r["duration_s"] or not r["distance_m"]:
                continue
            pace = r["duration_s"] / (r["distance_m"] / 1000)
            if abs(pace - pace_s) <= PACE_WINDOW_S:
                matched.append({"day": r["day"], "pace_s": round(pace),
                                "avg_hr": r["avg_hr"]})

    estimated_hr = None
    if len(matched) >= MIN_RUNS:
        hrs = sorted(m["avg_hr"] for m in matched)
        estimated_hr = round(hrs[len(hrs) // 2])

    hr = int(float(stored_hr)) if stored_hr else estimated_hr
    source = ("Uhr" if stored_hr else
              f"geschätzt aus {len(matched)} Läufen im Schwellentempo"
              if estimated_hr else None)

    zones = None
    if hr:
        # Trainingsbereiche an der Schwelle statt am Maximalpuls: Der
        # Maximalpuls ist eine Zahl, die man selten kennt und noch seltener
        # erreicht — die Schwelle laeuft man jede Woche.
        zones = [
            {"name": "Grundlage", "from": round(hr * 0.75), "to": round(hr * 0.85),
             "note": "Der Großteil des Laufens. Unterhaltung möglich."},
            {"name": "Mitteltempo", "from": round(hr * 0.85), "to": round(hr * 0.95),
             "note": "Zügig, aber noch lange durchzuhalten."},
            {"name": "Schwelle", "from": round(hr * 0.95), "to": round(hr * 1.02),
             "note": "Etwa eine Stunde haltbar. Hier wird das Renntempo gemacht."},
            {"name": "Darüber", "from": round(hr * 1.02), "to": round(hr * 1.10),
             "note": "Intervalle. Kurz, hart, selten."},
        ]

    return {
        "hr": hr,
        "pace_s": pace_s,
        "pace_text": running.pace_s_to_str(pace_s) if pace_s else None,
        "source": source,
        "measured": bool(stored_hr),
        "runs_used": len(matched),
        "recent": matched[:6],
        "zones": zones,
        "hint": None if hr else (
            "Für die Schwelle fehlen Läufe im Schwellentempo mit aufgezeichnetem "
            "Puls. Drei Tempoläufe reichen — oder trag den Wert deiner Uhr "
            "unter „Mehr“ ein."),
    }


def stress_pattern(days: int = 30) -> dict[str, Any]:
    """Wann Stress hoch ist — und was dagegen bei dir hilft."""
    from . import boosters

    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            """SELECT day, stress_avg, stress_max, stress_high_min, stress_rest_min,
                      body_battery_max, body_battery_min
               FROM daily_metrics WHERE day >= ? AND stress_avg IS NOT NULL
               ORDER BY day""", (since,)).fetchall())
        felt = rows_to_dicts(db.execute(
            "SELECT day, recorded_at, stress FROM mood_entries "
            "WHERE day >= ? AND stress IS NOT NULL", (since,)).fetchall())

    if not rows:
        return {"days": 0, "hint": "Noch keine Stresswerte von der Uhr.",
                "helpers": [], "worst_weekday": None}

    values = [r["stress_avg"] for r in rows]
    average = sum(values) / len(values)
    high_days = [r for r in rows if r["stress_avg"] > average * 1.2]

    # An welchem Wochentag ist es am schlimmsten? Nicht als Schicksal, sondern
    # als Hinweis, wann eine Gegenmassnahme eingeplant gehoert.
    by_weekday: dict[int, list[float]] = {}
    for r in rows:
        wd = dt.date.fromisoformat(r["day"]).weekday()
        by_weekday.setdefault(wd, []).append(r["stress_avg"])
    names = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag",
             "Samstag", "Sonntag"]
    ranked = sorted(((sum(v) / len(v), wd) for wd, v in by_weekday.items()
                     if len(v) >= 2), reverse=True)
    worst = {"weekday": names[ranked[0][1]], "value": round(ranked[0][0])} \
        if ranked else None
    calmest = {"weekday": names[ranked[-1][1]], "value": round(ranked[-1][0])} \
        if len(ranked) >= 3 else None

    # Gefuehlter gegen gemessener Stress: Wenn beides auseinanderlaeuft, ist
    # das die interessantere Information als jeder Einzelwert.
    felt_by_day = {}
    for f in felt:
        felt_by_day.setdefault(f["day"], []).append(f["stress"])
    pairs = [(r["stress_avg"], sum(felt_by_day[r["day"]]) / len(felt_by_day[r["day"]]))
             for r in rows if r["day"] in felt_by_day]
    agreement = None
    if len(pairs) >= 8:
        mx = sum(p[0] for p in pairs) / len(pairs)
        my = sum(p[1] for p in pairs) / len(pairs)
        num = sum((a - mx) * (b - my) for a, b in pairs)
        den = ((sum((a - mx) ** 2 for a, _b in pairs) ** 0.5)
               * (sum((b - my) ** 2 for _a, b in pairs) ** 0.5))
        agreement = round(num / den, 2) if den else None

    # Was bei dir gegen Stress geholfen hat — zur aktuellen Tageszeit zuerst.
    part = boosters.daypart()
    overall = boosters.effectiveness()
    here = boosters.effectiveness(part)
    helpers = []
    for b in boosters.BOOSTERS:
        if "stress" not in b["tags"] and "mood" not in b["tags"]:
            continue
        h = here.get(b["id"], {})
        o = overall.get(b["id"], {})
        if h.get("bewertet", 0) >= boosters.MIN_PART_RATINGS:
            helpers.append({**b, "gut": h["gut"], "von": h["bewertet"],
                            "score": h["score"], "when": part})
        elif o.get("bewertet", 0) >= boosters.MIN_RATINGS:
            helpers.append({**b, "gut": o["gut"], "von": o["bewertet"],
                            "score": o["score"], "when": None})
    helpers.sort(key=lambda h: (-h["score"], -h["von"]))

    return {
        "days": len(rows),
        "average": round(average),
        "high_days": len(high_days),
        "worst_weekday": worst,
        "calmest_weekday": calmest,
        "daypart": part,
        "helpers": helpers[:4],
        "agreement": agreement,
        "agreement_note": _agreement_note(agreement),
        "hint": None if helpers else (
            "Noch nichts gelernt: Bewerte die Vorschläge unter „Was jetzt hilft“ "
            "mit „hat geholfen“ oder „bringt mir nichts“, dann steht hier, was "
            "bei dir wirkt."),
    }


def _agreement_note(r: float | None) -> str | None:
    if r is None:
        return None
    if r >= 0.4:
        return ("Gemessener und gefühlter Stress laufen bei dir zusammen — die "
                "Uhr bestätigt, was du ohnehin merkst.")
    if r <= 0.1:
        return ("Gemessener und gefühlter Stress haben bei dir wenig miteinander "
                "zu tun. Das ist kein Fehler der Uhr: Sie misst die Belastung "
                "des Nervensystems, nicht die Laune.")
    return "Gemessener und gefühlter Stress hängen bei dir nur lose zusammen."
