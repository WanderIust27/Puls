"""Alle Messwerte gegen alle — mit ehrlicher Bewertung.

Rund dreissig Groessen ergeben ueber vierhundert Paare. Prueft man die alle
gegen die uebliche Schwelle p < 0,05, sind rein rechnerisch etwa zwanzig davon
"signifikant", ohne dass irgendein Zusammenhang bestuende. Wer die Liste dann
von oben liest, findet Muster, die es nicht gibt.

Deshalb wird hier zweierlei gerechnet: der p-Wert des einzelnen Paares (ueber
die Fisher-z-Transformation, ohne Fremdbibliothek) und zusaetzlich eine
Korrektur nach Benjamini-Hochberg, die beruecksichtigt, wie viele Paare
insgesamt geprueft wurden. Nur was auch danach standhaelt, wird als belastbar
ausgewiesen — der Rest steht weiter unten und ist als schwach gekennzeichnet.

Und immer gilt: Ein Zusammenhang ist keine Ursache. Dass an Tagen mit mehr
Schlaf die Stimmung besser ist, kann heissen, dass Schlaf der Stimmung hilft —
oder dass man bei guter Stimmung besser schlaeft.
"""
from __future__ import annotations

import datetime as dt
import logging
import math
from typing import Any

from ..db import get_db, rows_to_dicts

log = logging.getLogger("puls.stats")

MIN_PAIRS = 12            # unter zwölf gemeinsamen Tagen sagt nichts etwas
FDR_LEVEL = 0.10          # erlaubte Rate falscher Funde unter den gemeldeten

# Alle Groessen, die je Tag vorliegen. (Schluessel, Anzeigename, Gruppe,
# Einheit, hoeher_ist_besser oder None wenn neutral)
METRICS: list[tuple[str, str, str, str, bool | None]] = [
    ("sleep_hours", "Schlafdauer", "Schlaf", " h", True),
    ("sleep_score", "Schlafscore", "Schlaf", "", True),
    ("sleep_deep_hours", "Tiefschlaf", "Schlaf", " h", True),
    ("sleep_rem_hours", "REM-Schlaf", "Schlaf", " h", True),
    ("sleep_light_hours", "Leichtschlaf", "Schlaf", " h", None),
    ("sleep_awake_hours", "Wachzeit nachts", "Schlaf", " h", False),
    ("sleep_efficiency", "Schlafeffizienz", "Schlaf", " %", True),
    ("respiration_avg", "Atemfrequenz", "Schlaf", "/min", None),
    ("spo2_avg", "Sauerstoffsättigung", "Schlaf", " %", True),

    ("resting_hr", "Ruhepuls", "Herz", " bpm", False),
    ("hrv_avg", "HRV", "Herz", " ms", True),
    ("hr_max", "Maximalpuls", "Herz", " bpm", None),
    ("hr_min", "Minimalpuls", "Herz", " bpm", None),

    ("stress_avg", "Stress Ø", "Stress", "", False),
    ("stress_max", "Stress Spitze", "Stress", "", False),
    ("stress_high_min", "Minuten hoher Stress", "Stress", " min", False),
    ("stress_rest_min", "Erholungsminuten", "Stress", " min", True),
    ("body_battery_max", "Body Battery hoch", "Stress", "", True),
    ("body_battery_min", "Body Battery tief", "Stress", "", True),
    ("body_battery_wake", "Body Battery früh", "Stress", "", True),
    ("body_battery_drained", "Body Battery verbraucht", "Stress", "", False),

    ("steps", "Schritte", "Bewegung", "", True),
    ("training_load", "Trainingslast", "Bewegung", "", None),
    ("training_minutes", "Trainingsdauer", "Bewegung", " min", None),
    ("run_km", "Laufkilometer", "Bewegung", " km", None),
    ("calories_burned", "Verbrannte Kalorien", "Bewegung", "", None),
    ("training_readiness", "Trainingsbereitschaft", "Bewegung", "", True),

    ("weight_kg", "Gewicht", "Körper", " kg", None),
    ("body_fat_pct", "Körperfett", "Körper", " %", False),
    ("muscle_kg", "Muskelmasse", "Körper", " kg", True),
    ("water_pct", "Wasseranteil", "Körper", " %", True),

    ("mood", "Stimmung", "Befinden", "", True),
    ("energy", "Energie", "Befinden", "", True),
    ("stress_felt", "Stress (gefühlt)", "Befinden", "", False),

    ("kcal", "Kalorien gegessen", "Ernährung", "", None),
    ("protein_g", "Eiweiß", "Ernährung", " g", True),
    ("carbs_g", "Kohlenhydrate", "Ernährung", " g", None),
]
LABELS = {k: (label, group, unit, better) for k, label, group, unit, better in METRICS}


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _p_value(r: float, n: int) -> float:
    """Wahrscheinlichkeit, diesen Zusammenhang bei reinem Zufall zu sehen.

    Ueber die Fisher-z-Transformation: Sie macht aus dem Korrelations-
    koeffizienten eine annaehernd normalverteilte Groesse, womit sich der
    p-Wert ohne Fremdbibliothek berechnen laesst.
    """
    if n < 4 or abs(r) >= 0.999999:
        return 0.0 if abs(r) >= 0.999999 else 1.0
    z = 0.5 * math.log((1 + r) / (1 - r))
    se = 1.0 / math.sqrt(n - 3)
    return max(0.0, min(1.0, 2 * (1 - _norm_cdf(abs(z / se)))))


def _benjamini_hochberg(items: list[dict[str, Any]], level: float = FDR_LEVEL) -> None:
    """Markiert, welche Funde die Mehrfachpruefung ueberstehen.

    Bei vierhundert Paaren waeren rund zwanzig allein durch Zufall unter
    p < 0,05. Dieses Verfahren zieht die Grenze so, dass unter den gemeldeten
    Funden hoechstens der eingestellte Anteil zufaellig ist.
    """
    ranked = sorted(items, key=lambda i: i["p"])
    m = len(ranked)
    cutoff_rank = 0
    for rank, item in enumerate(ranked, start=1):
        if item["p"] <= level * rank / m:
            cutoff_rank = rank
    for rank, item in enumerate(ranked, start=1):
        item["robust"] = rank <= cutoff_rank
        item["p_adjusted"] = round(min(1.0, item["p"] * m / rank), 4)


def collect(days: int = 365) -> list[dict[str, Any]]:
    """Ein Datensatz je Tag, aus allen Quellen zusammengefuehrt."""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        daily = {r["day"]: dict(r) for r in db.execute(
            "SELECT * FROM daily_metrics WHERE day >= ?", (since,)).fetchall()}
        moods = rows_to_dicts(db.execute(
            "SELECT day, mood, energy, stress FROM mood_entries WHERE day >= ?",
            (since,)).fetchall())
        acts = rows_to_dicts(db.execute(
            """SELECT substr(start_time,1,10) AS day, sport,
                      SUM(COALESCE(training_load, 0)) AS load,
                      SUM(COALESCE(duration_s,0)) AS seconds,
                      SUM(COALESCE(distance_m,0)) AS metres,
                      SUM(COALESCE(calories,0)) AS kcal
               FROM activities WHERE substr(start_time,1,10) >= ?
               GROUP BY day, sport""", (since,)).fetchall())
        body = rows_to_dicts(db.execute(
            "SELECT day, weight_kg, body_fat_pct, muscle_kg, water_pct "
            "FROM body_metrics WHERE day >= ? ORDER BY measured_at", (since,)).fetchall())
        food = {r["day"]: dict(r) for r in db.execute(
            "SELECT day, kcal, protein_g, carbs_g, fat_g FROM nutrition_log "
            "WHERE day >= ?", (since,)).fetchall()}

    mood_by_day: dict[str, dict[str, list[float]]] = {}
    for m in moods:
        b = mood_by_day.setdefault(m["day"], {"mood": [], "energy": [], "stress": []})
        for key in b:
            if m.get(key) is not None:
                b[key].append(m[key])

    act_by_day: dict[str, dict[str, float]] = {}
    for a in acts:
        b = act_by_day.setdefault(a["day"], {"load": 0.0, "seconds": 0.0,
                                             "run_m": 0.0, "kcal": 0.0})
        b["load"] += a["load"] or 0
        b["seconds"] += a["seconds"] or 0
        b["kcal"] += a["kcal"] or 0
        if a["sport"] == "running":
            b["run_m"] += a["metres"] or 0

    body_by_day: dict[str, dict[str, Any]] = {}
    for r in body:
        body_by_day.setdefault(r["day"], {}).update(
            {k: v for k, v in r.items() if v is not None and k != "day"})

    rows = []
    for i in range(days):
        day = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        d = daily.get(day) or {}
        m = mood_by_day.get(day) or {}
        a = act_by_day.get(day) or {}
        b = body_by_day.get(day) or {}
        f = food.get(day) or {}

        def avg(key: str) -> float | None:
            v = m.get(key) or []
            return sum(v) / len(v) if v else None

        def hours(key: str) -> float | None:
            v = d.get(key)
            return round(v / 3600, 2) if v else None

        sleep_total = d.get("sleep_seconds")
        awake = d.get("sleep_awake_s") or 0
        row = {
            "day": day,
            "sleep_hours": hours("sleep_seconds"),
            "sleep_deep_hours": hours("sleep_deep_s"),
            "sleep_rem_hours": hours("sleep_rem_s"),
            "sleep_light_hours": hours("sleep_light_s"),
            "sleep_awake_hours": hours("sleep_awake_s"),
            "sleep_efficiency": (round((sleep_total - awake) / sleep_total * 100, 1)
                                 if sleep_total else None),
            "sleep_score": d.get("sleep_score"),
            "respiration_avg": d.get("respiration_avg"),
            "spo2_avg": d.get("spo2_avg"),
            "resting_hr": d.get("resting_hr"),
            "hrv_avg": d.get("hrv_avg"),
            "hr_max": d.get("hr_max"),
            "hr_min": d.get("hr_min"),
            "stress_avg": d.get("stress_avg"),
            "stress_max": d.get("stress_max"),
            "stress_high_min": d.get("stress_high_min"),
            "stress_rest_min": d.get("stress_rest_min"),
            "body_battery_max": d.get("body_battery_max"),
            "body_battery_min": d.get("body_battery_min"),
            "body_battery_wake": d.get("body_battery_wake"),
            "body_battery_drained": d.get("body_battery_drained"),
            "training_readiness": d.get("training_readiness"),
            "steps": d.get("steps"),
            "training_load": a.get("load") or None,
            "training_minutes": round(a["seconds"] / 60) if a.get("seconds") else None,
            "run_km": round(a["run_m"] / 1000, 2) if a.get("run_m") else None,
            "calories_burned": a.get("kcal") or None,
            "weight_kg": b.get("weight_kg"),
            "body_fat_pct": b.get("body_fat_pct"),
            "muscle_kg": b.get("muscle_kg"),
            "water_pct": b.get("water_pct"),
            "mood": avg("mood"),
            "energy": avg("energy"),
            "stress_felt": avg("stress"),
            "kcal": f.get("kcal"),
            "protein_g": f.get("protein_g"),
            "carbs_g": f.get("carbs_g"),
        }
        if sum(1 for k, v in row.items() if k != "day" and v is not None) >= 2:
            rows.append(row)
    return rows


def _correlate(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < MIN_PAIRS:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = (sum(d * d for d in dx) ** 0.5) * (sum(d * d for d in dy) ** 0.5)
    if denom == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / denom


def matrix(days: int = 365, min_abs_r: float = 0.0) -> dict[str, Any]:
    """Jede Groesse gegen jede andere."""
    rows = collect(days)
    keys = [k for k, *_ in METRICS]
    available = {k: [r[k] for r in rows if r.get(k) is not None] for k in keys}
    usable = [k for k in keys if len(available[k]) >= MIN_PAIRS]

    pairs: list[dict[str, Any]] = []
    for i, a in enumerate(usable):
        for b in usable[i + 1:]:
            xs, ys = [], []
            for r in rows:
                if r.get(a) is not None and r.get(b) is not None:
                    xs.append(float(r[a]))
                    ys.append(float(r[b]))
            r_value = _correlate(xs, ys)
            if r_value is None or abs(r_value) < min_abs_r:
                continue
            p = _p_value(r_value, len(xs))
            la, ga, ua, ba = LABELS[a]
            lb, gb, ub, bb = LABELS[b]
            pairs.append({
                "a": a, "b": b, "a_label": la, "b_label": lb,
                "a_group": ga, "b_group": gb, "a_unit": ua, "b_unit": ub,
                "r": round(r_value, 3), "n": len(xs), "p": p,
                "strength": ("stark" if abs(r_value) >= 0.6 else
                             "deutlich" if abs(r_value) >= 0.4 else
                             "schwach" if abs(r_value) >= 0.25 else "kaum"),
                "direction": "gleichläufig" if r_value > 0 else "gegenläufig",
            })

    if pairs:
        _benjamini_hochberg(pairs)
    # Belastbares zuerst, darin das Stärkste; der Rest folgt nach Staerke
    pairs.sort(key=lambda x: (not x.get("robust", False), -abs(x["r"])))

    covered = sorted({k for p in pairs for k in (p["a"], p["b"])})
    return {
        "days": days,
        "rows": len(rows),
        "metrics_used": len(usable),
        "metrics_missing": [LABELS[k][0] for k in keys if k not in usable],
        "pairs": pairs,
        "robust": [p for p in pairs if p.get("robust")],
        "tested": len(pairs),
        "covered": len(covered),
        "hint": None if pairs else (
            f"Noch zu wenig Daten. Für einen Vergleich braucht es mindestens "
            f"{MIN_PAIRS} Tage, an denen beide Werte vorliegen — aktuell reichen "
            f"{len(usable)} von {len(keys)} Größen dafür aus."),
    }


def for_metric(key: str, days: int = 365, limit: int = 12) -> dict[str, Any]:
    """Alles, was mit einer bestimmten Groesse zusammenhaengt."""
    if key not in LABELS:
        raise ValueError("Diese Größe gibt es nicht.")
    data = matrix(days)
    related = [p for p in data["pairs"] if key in (p["a"], p["b"])]
    for p in related:
        other = p["b"] if p["a"] == key else p["a"]
        p["other"] = other
        p["other_label"] = LABELS[other][0]
    label, group, unit, better = LABELS[key]
    return {"key": key, "label": label, "group": group, "unit": unit,
            "related": related[:limit], "days": days}


def series(key: str, days: int = 180) -> list[dict[str, Any]]:
    """Verlauf einer einzelnen Groesse."""
    if key not in LABELS:
        raise ValueError("Diese Größe gibt es nicht.")
    return [{"day": r["day"], "value": r[key]}
            for r in reversed(collect(days)) if r.get(key) is not None]
