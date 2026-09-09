"""Was dir guttut — und was nicht.

Die Frage ist nicht, wie hoch deine HRV ist, sondern ob es dir an Tagen mit
hoher HRV besser geht. Das laesst sich beantworten, aber nur vorsichtig: Bei
genug Daten wird jeder Zusammenhang irgendwann "signifikant", und die meisten
davon sind Zufall.

Deshalb hier ein bewusst grobes Verfahren. Die Tage werden am Median eines
Einflusses in zwei Haelften geteilt, und die Zielgroesse in beiden Haelften
verglichen. Gemeldet wird nur, was drei Bedingungen erfuellt: genug Tage in
beiden Haelften, ein Unterschied ueber der Schwelle, und ein Zusammenhang, der
auch als Korrelation sichtbar ist. Ein Balkenpaar zeigt das Ergebnis — das ist
ehrlicher als eine Korrelationszahl, die niemand einordnen kann.

Zusammenhang ist keine Ursache. Die Texte sagen deshalb "ging einher mit",
nicht "fuehrt zu".
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..db import get_db, rows_to_dicts

log = logging.getLogger("puls.insights")

MIN_PER_HALF = 5          # Tage je Haelfte
MIN_CORRELATION = 0.3
MIN_REL_DIFF = 0.12       # 12 % Unterschied zwischen den Haelften

# Was untersucht wird. (Schluessel, Anzeigename, Einheit, hoeher_ist_besser)
DRIVERS = [
    ("sleep_hours", "Schlafdauer", " h", True),
    ("sleep_deep_hours", "Tiefschlaf", " h", True),
    ("sleep_score", "Schlafscore", "", True),
    ("hrv_avg", "HRV", " ms", True),
    ("resting_hr", "Ruhepuls", " bpm", False),
    ("stress_avg", "Stress am Vortag", "", False),
    ("load_yesterday", "Trainingslast am Vortag", "", None),
    ("steps", "Schritte am Vortag", "", True),
]
TARGETS = [
    ("mood", "Stimmung", " von 5"),
    ("energy", "Energie", " von 5"),
    ("training_readiness", "Trainingsbereitschaft", " von 100"),
]


def _median(values: list[float]) -> float:
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def _correlation(xs: list[float], ys: list[float]) -> float | None:
    n = len(xs)
    if n < MIN_PER_HALF * 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    dx = [x - mx for x in xs]
    dy = [y - my for y in ys]
    denom = (sum(d * d for d in dx) ** 0.5) * (sum(d * d for d in dy) ** 0.5)
    if denom == 0:
        return None
    return sum(a * b for a, b in zip(dx, dy)) / denom


def collect(days: int = 120) -> list[dict[str, Any]]:
    """Ein Datensatz je Tag, aus allen Quellen zusammengefuehrt."""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        daily = {r["day"]: dict(r) for r in db.execute(
            "SELECT * FROM daily_metrics WHERE day >= ?", (since,)).fetchall()}
        moods = rows_to_dicts(db.execute(
            "SELECT day, mood, energy, stress FROM mood_entries WHERE day >= ?",
            (since,)).fetchall())
        loads = {r["day"]: r["last"] for r in db.execute(
            """SELECT substr(start_time,1,10) AS day,
                      SUM(COALESCE(training_load, duration_s / 60.0)) AS last
               FROM activities WHERE substr(start_time,1,10) >= ?
               GROUP BY day""", (since,)).fetchall()}

    per_day: dict[str, dict[str, list[float]]] = {}
    for m in moods:
        bucket = per_day.setdefault(m["day"], {"mood": [], "energy": [], "stress": []})
        for key in ("mood", "energy", "stress"):
            if m.get(key) is not None:
                bucket[key].append(m[key])

    rows = []
    for i in range(days):
        day = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        prev = (dt.date.today() - dt.timedelta(days=i + 1)).isoformat()
        d = daily.get(day) or {}
        pd = daily.get(prev) or {}
        m = per_day.get(day) or {}

        def avg(key: str) -> float | None:
            values = m.get(key) or []
            return sum(values) / len(values) if values else None

        row = {
            "day": day,
            "sleep_hours": (d.get("sleep_seconds") or 0) / 3600 or None,
            "sleep_deep_hours": (d.get("sleep_deep_s") or 0) / 3600 or None,
            "sleep_score": d.get("sleep_score"),
            "hrv_avg": d.get("hrv_avg"),
            "resting_hr": d.get("resting_hr"),
            # Der Stress von gestern erklaert den heutigen Zustand, nicht der
            # von heute — der ist teils dessen Folge.
            "stress_avg": pd.get("stress_avg"),
            "steps": pd.get("steps"),
            "load_yesterday": loads.get(prev),
            "training_readiness": d.get("training_readiness"),
            "mood": avg("mood"),
            "energy": avg("energy"),
        }
        if any(v is not None for k, v in row.items() if k != "day"):
            rows.append(row)
    return rows


def _compare(rows: list[dict[str, Any]], driver: str, target: str
             ) -> dict[str, Any] | None:
    """Zielgroesse in der oberen gegen die untere Haelfte des Einflusses."""
    pairs = [(r[driver], r[target]) for r in rows
             if r.get(driver) is not None and r.get(target) is not None]
    if len(pairs) < MIN_PER_HALF * 2:
        return None

    cut = _median([p[0] for p in pairs])
    low = [t for d, t in pairs if d <= cut]
    high = [t for d, t in pairs if d > cut]
    if len(low) < MIN_PER_HALF or len(high) < MIN_PER_HALF:
        return None

    low_avg, high_avg = sum(low) / len(low), sum(high) / len(high)
    base = max(abs(low_avg), abs(high_avg), 1e-6)
    if abs(high_avg - low_avg) / base < MIN_REL_DIFF:
        return None

    r = _correlation([p[0] for p in pairs], [p[1] for p in pairs])
    if r is None or abs(r) < MIN_CORRELATION:
        return None

    return {"driver": driver, "target": target, "cut": round(cut, 2),
            "low": round(low_avg, 2), "high": round(high_avg, 2),
            "n_low": len(low), "n_high": len(high), "r": round(r, 2),
            "days": len(pairs)}


def analyse(days: int = 120) -> dict[str, Any]:
    """Alle Paare durchgehen und die deutlichsten Zusammenhaenge melden."""
    rows = collect(days)
    driver_labels = {k: (label, unit, better) for k, label, unit, better in DRIVERS}
    target_labels = {k: (label, unit) for k, label, unit in TARGETS}

    found = []
    for driver, d_label, d_unit, _ in DRIVERS:
        for target, t_label, t_unit in TARGETS:
            result = _compare(rows, driver, target)
            if not result:
                continue
            helps = result["high"] > result["low"]
            found.append({
                **result,
                "driver_label": d_label, "driver_unit": d_unit,
                "target_label": t_label, "target_unit": t_unit,
                "direction": "helps" if helps else "hurts",
                # Kein .lower(): "HRV" bliebe sonst "hrv", und deutsche
                # Substantive werden großgeschrieben.
                "text": (
                    f"An Tagen mit mehr als {result['cut']:g}{d_unit} "
                    f"{d_label}: {t_label} {result['high']:g}{t_unit} — "
                    f"sonst {result['low']:g}{t_unit}."),
            })

    # Der stärkste Zusammenhang zuerst
    found.sort(key=lambda f: -abs(f["r"]))

    good = [f for f in found if f["direction"] == "helps"][:4]
    bad = [f for f in found if f["direction"] == "hurts"][:4]

    usable = sum(1 for r in rows if r.get("mood") is not None)
    return {
        "days_with_mood": usable,
        "days_total": len(rows),
        "findings": found[:8],
        "helps": good,
        "hurts": bad,
        "hint": None if found else (
            f"Noch kein Zusammenhang deutlich genug. Dafür braucht es "
            f"mindestens {MIN_PER_HALF * 2} Tage mit Befinden-Einträgen — "
            f"aktuell sind es {usable}. Trag beim Gemüt einfach weiter ein, "
            f"das ist die Zutat, die Garmin nicht liefert."),
    }
