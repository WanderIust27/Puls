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
    ("bedtime", "Zubettgehzeit", "Schlaf", " Uhr", None),
    ("waketime", "Aufstehzeit", "Schlaf", " Uhr", None),
    ("sleep_midpoint", "Schlafmitte", "Schlaf", " Uhr", None),
    ("bedtime_shift", "Abweichung Zubettgehzeit", "Schlaf", " h", False),
    ("wake_shift", "Abweichung Aufstehzeit", "Schlaf", " h", False),

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
    ("train_hour", "Trainingsuhrzeit", "Bewegung", " Uhr", None),

    ("weight_kg", "Gewicht", "Körper", " kg", None),
    ("body_fat_pct", "Körperfett", "Körper", " %", False),
    ("muscle_kg", "Muskelmasse", "Körper", " kg", True),
    ("water_pct", "Wasseranteil", "Körper", " %", True),

    ("mood", "Stimmung Ø", "Befinden", "", True),
    ("energy", "Energie Ø", "Befinden", "", True),
    ("stress_felt", "Stress (gefühlt)", "Befinden", "", False),
    ("mood_morning", "Stimmung morgens", "Befinden", "", True),
    ("mood_evening", "Stimmung abends", "Befinden", "", True),
    ("energy_morning", "Energie morgens", "Befinden", "", True),
    ("energy_evening", "Energie abends", "Befinden", "", True),
    ("mood_change", "Stimmungsverlauf über den Tag", "Befinden", "", True),

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


# Kennzahlen, die eine Uhrzeit sind. Sie werden als Dezimalstunde gerechnet
# und ohne Umbruch bei Mitternacht: 23:30 ist 23.5, 00:30 ist 24.5. Sonst
# laegen zwei Abende, die eine Stunde auseinanderliegen, rechnerisch 23 Stunden
# auseinander und jeder Zusammenhang waere zerstoert.
CLOCK_METRICS = {"bedtime", "waketime", "sleep_midpoint", "train_hour"}

# Groessen, an denen du direkt drehen kannst. Nur aus diesen werden
# Empfehlungen abgeleitet — "schlafe besser, dann ist dein Ruhepuls tiefer"
# waere keine Empfehlung, sondern eine Umformulierung des Befunds.
LEVERS = {
    "bedtime", "waketime", "sleep_midpoint", "bedtime_shift", "wake_shift",
    "sleep_hours", "steps", "training_minutes", "training_load", "run_km",
    "train_hour", "kcal", "protein_g", "carbs_g",
}


def _clock(stamp: Any, night: bool = False) -> float | None:
    """Zeitstempel in Dezimalstunden. Garmin liefert Millisekunden seit 1970,
    aeltere Eintraege eine ISO-Zeichenkette — beides muss hier ankommen.

    night=True heisst: Zeiten am fruehen Morgen gehoeren zum Abend davor und
    werden als 24 bis 30 Uhr gefuehrt, damit 23:30 und 00:30 benachbart sind.
    """
    if stamp is None or stamp == "":
        return None
    when: dt.datetime | None = None
    try:
        value = float(stamp)
        # Millisekunden von Sekunden unterscheiden
        when = dt.datetime.fromtimestamp(value / 1000 if value > 1e11 else value)
    except (TypeError, ValueError):
        try:
            when = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            return None
    hours = when.hour + when.minute / 60 + when.second / 3600
    if night and hours < 12:
        hours += 24
    return round(hours, 3)


def fmt_clock(hours: float) -> str:
    """22.75 wird zu 22:45, 25.25 zu 01:15."""
    hours = hours % 24
    h, m = int(hours), int(round((hours - int(hours)) * 60))
    if m == 60:
        h, m = h + 1, 0
    return f"{h % 24:02d}:{m:02d}"


def collect(days: int = 365) -> list[dict[str, Any]]:
    """Ein Datensatz je Tag, aus allen Quellen zusammengefuehrt."""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        daily = {r["day"]: dict(r) for r in db.execute(
            "SELECT * FROM daily_metrics WHERE day >= ?", (since,)).fetchall()}
        moods = rows_to_dicts(db.execute(
            "SELECT day, recorded_at, mood, energy, stress FROM mood_entries "
            "WHERE day >= ? ORDER BY recorded_at", (since,)).fetchall())
        acts = rows_to_dicts(db.execute(
            """SELECT substr(start_time,1,10) AS day, sport,
                      SUM(COALESCE(training_load, 0)) AS load,
                      SUM(COALESCE(duration_s,0)) AS seconds,
                      SUM(COALESCE(distance_m,0)) AS metres,
                      SUM(COALESCE(calories,0)) AS kcal,
                      MIN(start_time) AS first_start
               FROM activities WHERE substr(start_time,1,10) >= ?
               GROUP BY day, sport""", (since,)).fetchall())
        body = rows_to_dicts(db.execute(
            "SELECT day, weight_kg, body_fat_pct, muscle_kg, water_pct "
            "FROM body_metrics WHERE day >= ? ORDER BY measured_at", (since,)).fetchall())
        food = {r["day"]: dict(r) for r in db.execute(
            "SELECT day, kcal, protein_g, carbs_g, fat_g FROM nutrition_log "
            "WHERE day >= ?", (since,)).fetchall()}

    # Stimmung nicht nur als Tagesmittel: Morgens sagt sie etwas ueber die
    # Nacht, abends ueber den Tag. Wer beides in einen Mittelwert wirft,
    # verliert genau den Unterschied, auf den es ankommt.
    mood_by_day: dict[str, dict[str, list[float]]] = {}
    mood_parts: dict[str, dict[str, list[float]]] = {}
    for m in moods:
        b = mood_by_day.setdefault(m["day"], {"mood": [], "energy": [], "stress": []})
        for key in b:
            if m.get(key) is not None:
                b[key].append(m[key])
        hour = _clock(m.get("recorded_at"))
        part = "morning" if hour is not None and hour < 12 else "evening"
        p = mood_parts.setdefault(m["day"], {})
        for key in ("mood", "energy"):
            if m.get(key) is not None:
                p.setdefault(f"{key}_{part}", []).append(m[key])

    act_by_day: dict[str, dict[str, Any]] = {}
    for a in acts:
        b = act_by_day.setdefault(a["day"], {"load": 0.0, "seconds": 0.0,
                                             "run_m": 0.0, "kcal": 0.0,
                                             "start": None})
        hour = _clock(a.get("first_start"))
        if hour is not None and (b["start"] is None or hour < b["start"]):
            b["start"] = hour
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

        mp = mood_parts.get(day) or {}

        def avg(key: str) -> float | None:
            v = m.get(key) or []
            return sum(v) / len(v) if v else None

        def part(key: str) -> float | None:
            v = mp.get(key) or []
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
            "mood_morning": part("mood_morning"),
            "mood_evening": part("mood_evening"),
            "energy_morning": part("energy_morning"),
            "energy_evening": part("energy_evening"),
            "bedtime": _clock(d.get("sleep_start"), night=True),
            "waketime": _clock(d.get("sleep_end")),
            "train_hour": a.get("start"),
            "kcal": f.get("kcal"),
            "protein_g": f.get("protein_g"),
            "carbs_g": f.get("carbs_g"),
        }
        if row["mood_morning"] is not None and row["mood_evening"] is not None:
            row["mood_change"] = round(row["mood_evening"] - row["mood_morning"], 2)
        else:
            row["mood_change"] = None

        # Schlafmitte: der Punkt, um den herum du schlaefst. Aussagekraeftiger
        # als Zubettgehzeit allein, weil sie Dauer und Lage zusammenfasst.
        if row["bedtime"] is not None and row["sleep_hours"]:
            row["sleep_midpoint"] = round(row["bedtime"] + row["sleep_hours"] / 2, 3)
        else:
            row["sleep_midpoint"] = None

        row["bedtime_shift"] = None
        row["wake_shift"] = None
        if sum(1 for k, v in row.items() if k != "day" and v is not None) >= 2:
            rows.append(row)

    # Regelmaessigkeit erst danach: Sie misst die Abweichung von DEINER
    # ueblichen Zeit, und die kennt man erst, wenn alle Tage vorliegen.
    for key, target in (("bedtime", "bedtime_shift"), ("waketime", "wake_shift")):
        values = [r[key] for r in rows if r.get(key) is not None]
        if len(values) >= MIN_PAIRS:
            usual = sorted(values)[len(values) // 2]      # Median, nicht Mittel
            for r in rows:
                if r.get(key) is not None:
                    r[target] = round(abs(r[key] - usual), 2)
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


MIN_GROUP = 6             # so viele Tage muss jede Haelfte des Vergleichs haben


def _fmt(key: str, value: float) -> str:
    """Einen Wert so schreiben, wie man ihn liest — Uhrzeit als Uhrzeit."""
    if key in CLOCK_METRICS:
        return fmt_clock(value)
    unit = LABELS[key][2]
    digits = 0 if abs(value) >= 100 or key in ("steps", "kcal") else 1
    return f"{value:,.{digits}f}".replace(",", ".") + unit


def recommendations(days: int = 365, limit: int = 8) -> dict[str, Any]:
    """Aus den belastbaren Funden konkrete Empfehlungen ableiten.

    Ein Korrelationskoeffizient ist keine Empfehlung. Deshalb wird hier fuer
    jeden belastbaren Fund, bei dem eine Seite etwas ist, woran du drehen
    kannst, das Drittel deiner besten Tage gegen das Drittel deiner
    schlechtesten gestellt — und der Unterschied in echten Einheiten
    ausgerechnet. Aus "r = 0,52" wird so "an deinen 30 fruehesten Abenden lag
    die HRV im Schnitt 6 ms hoeher".

    Die Richtung bleibt offen und wird auch so benannt: Dass an fruehen Abenden
    die HRV hoeher ist, kann am fruehen Zubettgehen liegen — oder daran, dass
    man an erholten Tagen frueher muede wird.
    """
    data = matrix(days)
    rows = collect(days)
    out: list[dict[str, Any]] = []

    for pair in data["robust"]:
        for lever, outcome in ((pair["a"], pair["b"]), (pair["b"], pair["a"])):
            if lever not in LEVERS or outcome in LEVERS:
                continue
            better = LABELS[outcome][3]
            if better is None:            # ohne "besser oder schlechter" keine Empfehlung
                continue

            paired = [(r[lever], r[outcome]) for r in rows
                      if r.get(lever) is not None and r.get(outcome) is not None]
            if len(paired) < MIN_GROUP * 3:
                continue
            paired.sort(key=lambda t: t[0])
            cut = len(paired) // 3
            low, high = paired[:cut], paired[-cut:]
            if len(low) < MIN_GROUP or len(high) < MIN_GROUP:
                continue

            low_mean = sum(v for _, v in low) / len(low)
            high_mean = sum(v for _, v in high) / len(high)
            # Welches Drittel ist das bessere — gemessen am Ergebnis, nicht am Hebel
            high_is_better = (high_mean > low_mean) if better else (high_mean < low_mean)
            good, bad = (high, low) if high_is_better else (low, high)
            good_mean = high_mean if high_is_better else low_mean
            bad_mean = low_mean if high_is_better else high_mean
            gain = abs(good_mean - bad_mean)
            if gain < 1e-9:
                continue

            threshold = good[0][0] if high_is_better else good[-1][0]
            direction = "ab" if high_is_better else "bis"
            if lever in CLOCK_METRICS:
                direction = "ab" if high_is_better else "vor"

            unit = LABELS[outcome][2]
            share = round(gain / abs(bad_mean) * 100) if bad_mean else None
            advice = (
                f"{LABELS[lever][0]} {direction} {_fmt(lever, threshold)}: "
                f"An diesen {len(good)} Tagen lag {LABELS[outcome][0]} bei "
                f"{_fmt(outcome, good_mean)} statt {_fmt(outcome, bad_mean)} — "
                f"ein Unterschied von {gain:.1f}{unit}"
                + (f" ({share} %)." if share else "."))

            out.append({
                "lever": lever, "lever_label": LABELS[lever][0],
                "outcome": outcome, "outcome_label": LABELS[outcome][0],
                "threshold": round(threshold, 3),
                "threshold_text": _fmt(lever, threshold),
                "direction": direction,
                "good_mean": round(good_mean, 2), "bad_mean": round(bad_mean, 2),
                "good_text": _fmt(outcome, good_mean), "bad_text": _fmt(outcome, bad_mean),
                "gain": round(gain, 2), "gain_pct": share,
                "days_good": len(good), "days_bad": len(bad),
                "n": len(paired), "r": pair["r"], "p_adjusted": pair["p_adjusted"],
                "group": LABELS[outcome][1],
                "text": advice,
                # Nach Wirkung sortieren, gemessen am eigenen Streubereich der
                # Zielgroesse — sonst gewaenne immer die Groesse mit den
                # groessten Zahlen, nicht die mit dem groessten Effekt.
                "_weight": gain / (_spread(rows, outcome) or 1),
            })

    out.sort(key=lambda x: -x["_weight"])
    for item in out:
        item.pop("_weight", None)

    # Je Hebel nur die staerkste Empfehlung — sonst steht dreimal dasselbe da
    seen: set[str] = set()
    unique, rest = [], []
    for item in out:
        if item["lever"] in seen:
            rest.append(item)
        else:
            seen.add(item["lever"])
            unique.append(item)

    return {
        "days": days,
        "recommendations": unique[:limit],
        "also": rest[:limit],
        "checked": data["tested"],
        "robust": len(data["robust"]),
        "hint": None if unique else (
            "Noch keine Empfehlung ableitbar. Dafür braucht es einen belastbaren "
            "Zusammenhang zwischen etwas, woran du drehen kannst (Schlafenszeit, "
            "Schritte, Trainingsumfang, Ernährung), und einem Wert, bei dem klar "
            "ist, was besser wäre."),
    }


def _spread(rows: list[dict[str, Any]], key: str) -> float:
    values = [r[key] for r in rows if r.get(key) is not None]
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((v - mean) ** 2 for v in values) / (len(values) - 1)) ** 0.5


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
