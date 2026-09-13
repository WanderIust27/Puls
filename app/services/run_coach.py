"""Laufen im Detail — Puls, VO2max, Laufform und was daraus folgt.

Der Laufreiter zeigte bisher vier Kennzahlen und eine Liste. Das reicht, um
zu sehen, dass man gelaufen ist, aber nicht, um zu verstehen, ob es besser
wird. Die Uhr misst deutlich mehr, und drei Dinge davon entscheiden beim
Laufen wirklich etwas:

* **VO2max** — die Obergrenze. Sie sagt, was an Tempo ueberhaupt moeglich
  waere, und aus ihr laesst sich eine Rennzeit rechnen.
* **Der Puls** — die Anstrengung. Dieselbe Runde bei weniger Puls ist der
  ehrlichste Fortschritt, den es im Ausdauersport gibt.
* **Die Laufform** — wie teuer jeder Schritt ist. Kadenz, Bodenkontakt und
  vertikales Verhaeltnis kosten nichts extra, sie kommen ohnehin mit.

Wie ueberall in PULS gilt: Hier wird gerechnet, formuliert wird anderswo. Jede
Zahl in diesem Modul stammt aus der Datenbank oder aus einer benannten Formel,
und jeder Tipp nennt die Zahl, aus der er folgt — sonst ist es ein Ratschlag
aus dem Internet und kein Coaching.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from ..constants import (EASY_SHARE_TARGET, LONG_RUN_FACTOR,
                         LONG_RUN_WINDOW_DAYS)
from ..db import get_db, get_setting, rows_to_dicts
from . import running

log = logging.getLogger("puls.run_coach")

WINDOW_DAYS = 28          # "die letzten vier Wochen"
HISTORY_DAYS = 365        # so weit zurueck wird fuer Trends gelesen
VO2_TREND_WEEKS = 12      # Fenster fuer die VO2max-Entwicklung
MIN_TREND_M = 2000        # kuerzere Laeufe sagen ueber die Form wenig
MIN_ZONE_SECONDS = 300    # Zonendaten unter 5 Minuten sind Rauschen


# --------------------------------------------------------------- Datenzugriff

def _read(today: dt.date) -> dict[str, Any]:
    """Alles in einem Rutsch lesen.

    Eine einzige geoeffnete Verbindung, danach wird nur noch gerechnet. Der
    Datenbank-Lock in PULS ist nicht reentrant: Wer waehrend einer offenen
    Verbindung eine Funktion aufruft, die selbst wieder die Datenbank
    anfasst — und sei es nur get_setting — legt den Prozess still.
    """
    since = (today - dt.timedelta(days=HISTORY_DAYS)).isoformat()
    with get_db() as db:
        runs = rows_to_dicts(db.execute(
            """SELECT id, name, start_time, duration_s, distance_m, avg_hr,
                      max_hr, vo2max, avg_cadence, avg_stride_m,
                      ground_contact_ms, vertical_osc_cm, vertical_ratio,
                      avg_power, elevation_gain, hr_zones_json, analysis_json
               FROM activities
               WHERE sport='running' AND substr(start_time,1,10) >= ?
               ORDER BY start_time""", (since,)).fetchall())
        vitals = rows_to_dicts(db.execute(
            """SELECT day, resting_hr FROM daily_metrics
               WHERE day >= ? AND resting_hr IS NOT NULL
               ORDER BY day""", (since,)).fetchall())
    for r in runs:
        r["day"] = (r["start_time"] or "")[:10]
        r["km"] = round((r["distance_m"] or 0) / 1000, 2)
        r["pace_s"] = _pace(r["distance_m"], r["duration_s"])
    return {"runs": runs, "vitals": vitals}


def _pace(distance_m: float | None, duration_s: float | None) -> int | None:
    if not distance_m or not duration_s or distance_m < 100:
        return None
    return int(round(duration_s / (distance_m / 1000.0)))


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _de(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",")


def _day_text(day: str) -> str:
    try:
        d = dt.date.fromisoformat(day)
    except ValueError:
        return day
    return f"{d.day}.{d.month}.{d.year}"


def _fmt_time(seconds: float) -> str:
    s = int(round(seconds))
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d} h"
    return f"{s // 60}:{s % 60:02d} min"


# ------------------------------------------------------------------- VO2max

# Einordnung nach Alter und Geschlecht, in ml/kg/min. Die Grenzen folgen den
# Perzentiltabellen des Cooper Institute, wie sie in den ACSM-Guidelines
# stehen — gerundet, denn eine Nachkommastelle wuerde hier eine Genauigkeit
# vortaeuschen, die weder die Tabelle noch die Uhr hergibt.
# Reihenfolge: obere Grenze von schwach | durchschnittlich | gut | sehr gut.
VO2_NORMS: list[tuple[str, int, tuple[int, int, int, int]]] = [
    ("male", 29, (38, 44, 49, 55)),
    ("male", 39, (36, 42, 47, 53)),
    ("male", 49, (34, 40, 45, 50)),
    ("male", 59, (31, 36, 41, 46)),
    ("male", 200, (28, 33, 38, 43)),
    ("female", 29, (32, 37, 42, 47)),
    ("female", 39, (30, 35, 40, 45)),
    ("female", 49, (28, 33, 38, 43)),
    ("female", 59, (25, 30, 35, 40)),
    ("female", 200, (23, 27, 32, 37)),
]
VO2_BANDS = ("schwach", "durchschnittlich", "gut", "sehr gut", "ausgezeichnet")

# Distanzen, fuer die eine Prognose gestellt wird.
RACE_DISTANCES = [("5 km", 5000.0), ("10 km", 10000.0), ("Halbmarathon", 21097.0)]


def _norm_band(vo2: float, age: int, sex: str) -> str | None:
    for norm_sex, max_age, limits in VO2_NORMS:
        if norm_sex != sex or age > max_age:
            continue
        for i, limit in enumerate(limits):
            if vo2 < limit:
                return VO2_BANDS[i]
        return VO2_BANDS[4]
    return None


def _weekly_max(runs: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    """Wochenbestwerte, auf den Montag datiert.

    Beim VO2max-Wert der Uhr ist das Maximum der richtige Wochenwert und nicht
    der Mittelwert: Der Schaetzer braucht einen ausreichend langen Lauf mit
    stabilem Puls: kurze oder sehr huegelige Laeufe druecken ihn nach unten,
    ohne dass sich an der Ausdauer etwas geaendert haette.
    """
    buckets: dict[str, float] = {}
    for r in runs:
        value = r.get(field)
        if not value or not r.get("day"):
            continue
        try:
            d = dt.date.fromisoformat(r["day"])
        except ValueError:
            continue
        monday = (d - dt.timedelta(days=d.weekday())).isoformat()
        buckets[monday] = max(buckets.get(monday, 0.0), float(value))
    return [{"day": k, "value": round(v, 1)} for k, v in sorted(buckets.items())]


def vo2max(data: dict[str, Any], today: dt.date) -> dict[str, Any]:
    """Aktueller Wert, Einordnung, Entwicklung und was daraus an Zeit folgt."""
    runs = data["runs"]
    measured = [r for r in runs if r.get("vo2max")]
    points = _weekly_max(runs, "vo2max")[-VO2_TREND_WEEKS:]

    value: float | None = None
    source = day = None
    if measured:
        last = measured[-1]
        value, source, day = float(last["vo2max"]), "garmin", last["day"]
    else:
        cooper = get_setting("cooper_distance_m", "")
        if cooper:
            try:
                value = max(20.0, (float(cooper) - 504.9) / 44.73)
                source, day = "cooper", get_setting("last_run_benchmark", "") or None
            except ValueError:
                value = None

    if value is None:
        return {
            "value": None, "points": points,
            "hint": ("Noch kein VO2max-Wert. Die Uhr schätzt ihn nach einem "
                     "Lauf von mindestens zehn Minuten mit stabilem Puls im "
                     "Freien — oder du läufst den Cooper-Test aus dem Plan."),
        }

    age = int(float(get_setting("body_age", "30") or 30))
    sex = (get_setting("body_sex", "male") or "male").strip().lower()
    band = _norm_band(value, age, sex)

    # Entwicklung: erster gegen letzten Wochenbestwert im Fenster.
    change = None
    if len(points) >= 3:
        first, last_p = points[0]["value"], points[-1]["value"]
        change = {
            "from": first, "to": last_p, "delta": round(last_p - first, 1),
            "weeks": len(points),
        }

    predictions = []
    for label, metres in RACE_DISTANCES:
        seconds = running.predict_race_time(value, metres)
        if seconds <= 0:
            continue
        pace = int(round(seconds / (metres / 1000.0)))
        predictions.append({
            "label": label, "distance_m": metres, "time_s": int(seconds),
            "text": _fmt_time(seconds), "pace_s": pace,
            "pace_text": running.pace_s_to_str(pace),
        })

    goal_km = float(get_setting("run_goal_distance_km", "10") or 10)
    goal_min = float(get_setting("run_goal_time_min", "60") or 60)
    goal: dict[str, Any] | None = None
    if goal_km > 0:
        pred_s = running.predict_race_time(value, goal_km * 1000)
        gap = pred_s - goal_min * 60
        goal = {
            "distance_km": goal_km, "time_min": goal_min,
            "predicted_s": int(pred_s), "predicted_text": _fmt_time(pred_s),
            "required_pace": running.pace_s_to_str(int(goal_min * 60 / goal_km)),
            "gap_s": int(gap), "reached": gap <= 0,
        }

    return {
        "value": round(value, 1), "source": source, "day": day,
        "band": band, "age": age, "sex": sex,
        "points": points, "change": change,
        "predictions": predictions, "goal": goal,
        "lead": _vo2_lead(value, band, change, source),
        "what": ("Wie viel Sauerstoff dein Körper pro Minute und Kilo verwerten "
                 "kann. Die Obergrenze für alles, was länger als zwei Minuten "
                 "dauert."),
        "why": ("Der Wert steigt langsam und fällt langsam. Was er von Woche zu "
                "Woche macht, ist Messrauschen — was er über drei Monate macht, "
                "ist dein Trainingsstand."),
    }


def _vo2_lead(value: float, band: str | None, change: dict[str, Any] | None,
              source: str | None) -> str:
    head = f"{_de(value)} ml/kg/min"
    if band:
        head += f" — für dein Alter {band}"
    head += "."
    if source == "cooper":
        head += " Aus deinem Cooper-Test gerechnet, nicht von der Uhr geschätzt."
    if not change:
        return head
    delta = change["delta"]
    weeks = change["weeks"]
    if delta >= 1.0:
        return (f"{head} Über {weeks} Wochen um {_de(delta)} Punkte gestiegen — "
                "das ist eine echte Verbesserung und keine Tagesform.")
    if delta <= -1.0:
        return (f"{head} Über {weeks} Wochen um {_de(abs(delta))} Punkte gefallen. "
                "Das passiert bei weniger Umfang, langer Pause oder wenn die "
                "lockeren Läufe weggefallen sind.")
    return (f"{head} Über {weeks} Wochen praktisch unverändert "
            f"({_de(delta)} Punkte) — im Rahmen der Messgenauigkeit.")


# --------------------------------------------------------------------- Puls

def _zone_seconds(runs: list[dict[str, Any]]) -> dict[int, float]:
    total: dict[int, float] = {}
    for r in runs:
        raw = r.get("hr_zones_json")
        if not raw:
            continue
        try:
            zones = {int(k): float(v) for k, v in json.loads(raw).items()}
        except (ValueError, TypeError, AttributeError):
            continue
        if sum(zones.values()) < MIN_ZONE_SECONDS:
            continue
        for z, sec in zones.items():
            total[z] = total.get(z, 0.0) + sec
    return total


def _efficiency(r: dict[str, Any]) -> float | None:
    """Meter pro Minute je Pulsschlag — Tempo gemessen an der Anstrengung."""
    if not r.get("distance_m") or not r.get("duration_s") or not r.get("avg_hr"):
        return None
    if r["avg_hr"] < 60 or r["distance_m"] < MIN_TREND_M:
        return None
    return round((r["distance_m"] / (r["duration_s"] / 60.0)) / r["avg_hr"], 3)


def pulse(data: dict[str, Any], today: dt.date) -> dict[str, Any]:
    """Ruhepuls, Maximalpuls, Zonenverteilung und Effizienz."""
    runs = data["runs"]
    window_from = (today - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    prev_from = (today - dt.timedelta(days=WINDOW_DAYS * 2)).isoformat()
    recent = [r for r in runs if r["day"] >= window_from]
    previous = [r for r in runs if prev_from <= r["day"] < window_from]

    out: dict[str, Any] = {"runs_recent": len(recent)}

    # --- Ruhepuls: sieben Tage gegen die drei Wochen davor ----------------
    v_recent = [v["resting_hr"] for v in data["vitals"]
                if v["day"] >= (today - dt.timedelta(days=7)).isoformat()]
    v_base = [v["resting_hr"] for v in data["vitals"]
              if window_from <= v["day"] < (today - dt.timedelta(days=7)).isoformat()]
    now_hr, base_hr = _mean(v_recent), _mean(v_base)
    if now_hr is not None:
        delta = round(now_hr - base_hr, 1) if base_hr is not None else None
        out["resting"] = {
            "value": round(now_hr), "delta": delta, "days": len(v_recent),
            "sentence": _resting_sentence(now_hr, delta),
            "what": "Dein Puls im Schlaf, gemittelt über die letzten Tage.",
            "why": ("Sinkt er über Wochen, wird das Herz kräftiger. Steigt er "
                    "plötzlich um mehrere Schläge, steckt fast immer etwas "
                    "dahinter: zu wenig Schlaf, ein Infekt oder zu viel "
                    "Training."),
        }

    # --- Hoechster gemessener Puls ---------------------------------------
    with_max = [r for r in runs if r.get("max_hr")]
    if with_max:
        best = max(with_max, key=lambda r: r["max_hr"])
        seen = round(float(best["max_hr"]))
        out["max_seen"] = {
            "value": seen, "day": best["day"], "name": best.get("name"),
            "sentence": (f"{seen} Schläge, gemessen am "
                         f"{_day_text(best['day'])}"
                         + (f" bei „{best['name']}“." if best.get("name") else ".")),
            "what": ("Der höchste Puls, den die Uhr in den letzten zwölf "
                     "Monaten bei einem Lauf aufgezeichnet hat."),
            "why": ("Darauf beruhen alle Zonenangaben. Wenn dieser Wert aus "
                    "einem lockeren Lauf stammt, sind deine Zonen zu eng "
                    "gesetzt — dann fehlt ein harter Lauf als Referenz."),
        }

    # --- Zonenverteilung der letzten vier Wochen -------------------------
    zones = _zone_seconds(recent)
    total = sum(zones.values())
    if total >= MIN_ZONE_SECONDS:
        easy_s = zones.get(1, 0.0) + zones.get(2, 0.0)
        hard_s = zones.get(4, 0.0) + zones.get(5, 0.0)
        easy_share = round(easy_s / total * 100)
        out["zones"] = {
            "total_s": int(total),
            "easy_share": easy_share,
            "middle_share": round(zones.get(3, 0.0) / total * 100),
            "hard_share": round(hard_s / total * 100),
            "target": round(EASY_SHARE_TARGET * 100),
            "bars": [{"zone": z, "seconds": int(zones.get(z, 0.0)),
                      "percent": round(zones.get(z, 0.0) / total * 100)}
                     for z in range(1, 6)],
            "sentence": _zone_sentence(easy_share,
                                       round(zones.get(3, 0.0) / total * 100)),
        }

    # --- Effizienz: gleiche Strecke, weniger Puls ------------------------
    points = []
    for r in runs:
        ef = _efficiency(r)
        if ef:
            points.append({"day": r["day"], "value": ef, "km": r["km"],
                           "hr": round(r["avg_hr"]), "pace_s": r["pace_s"]})
    if len(points) >= 6:
        recent_ef = [p["value"] for p in points
                     if p["day"] >= window_from] or [points[-1]["value"]]
        prev_ef = [p["value"] for p in points if prev_from <= p["day"] < window_from]
        now_ef = _mean(recent_ef)
        was_ef = _mean(prev_ef)
        pct = round((now_ef - was_ef) / was_ef * 100, 1) if was_ef else None
        out["efficiency"] = {
            "value": round(now_ef, 3), "change_pct": pct, "points": points[-40:],
            "sentence": _efficiency_sentence(pct),
            "what": ("Zurückgelegte Meter je Minute, geteilt durch den Puls. "
                     "Tempo, gemessen an dem, was es dich kostet."),
            "why": ("Schneller werden ist leicht — schneller werden, ohne dass "
                    "der Puls mitgeht, ist der eigentliche Formgewinn. Deshalb "
                    "ist das die ehrlichste Zahl auf dieser Seite."),
        }

    # --- Puls im lockeren Lauf, als Anteil des Maximums -------------------
    easy_runs = [r for r in recent if r.get("avg_hr") and r["distance_m"]
                 and r["distance_m"] >= MIN_TREND_M]
    avg = _mean([r["avg_hr"] for r in easy_runs])
    if avg and out.get("max_seen"):
        share = round(avg / out["max_seen"]["value"] * 100)
        out["average"] = {"value": round(avg), "percent_of_max": share,
                          "runs": len(easy_runs)}

    out["volume"] = _volume(recent, previous)
    return out


def _resting_sentence(value: float, delta: float | None) -> str:
    head = f"{round(value)} Schläge pro Minute im Mittel der letzten Tage."
    if delta is None:
        return head
    if delta <= -2:
        return (f"{head} Das sind {_de(abs(delta))} Schläge weniger als im Monat "
                "davor — ein Zeichen, dass die Grundlage greift.")
    if delta >= 3:
        return (f"{head} Das sind {_de(delta)} Schläge mehr als im Monat davor. "
                "Bei so einem Sprung lohnt es sich, ein paar Tage lockerer zu "
                "machen und den Schlaf anzusehen.")
    return f"{head} Praktisch unverändert gegenüber dem Monat davor."


def _zone_sentence(easy_share: int, middle_share: int) -> str:
    target = round(EASY_SHARE_TARGET * 100)
    if easy_share >= target:
        return (f"{easy_share} % deiner Laufzeit lagen in Zone 1–2. Das ist die "
                f"Verteilung, die funktioniert — {target} % locker sind das Ziel.")
    if middle_share >= 35:
        return (f"Nur {easy_share} % locker, dafür {middle_share} % im mittleren "
                "Bereich. Das ist der häufigste Fehler im Breitensport: zu hart "
                "für Erholung, zu leicht für einen Reiz.")
    return (f"{easy_share} % deiner Laufzeit in Zone 1–2, angepeilt sind "
            f"{target} %. Die lockeren Läufe dürfen sich langsamer anfühlen, "
            "als dir lieb ist.")


def _efficiency_sentence(pct: float | None) -> str:
    if pct is None:
        return "Noch zu wenige vergleichbare Läufe für einen Verlauf."
    if pct >= 1.5:
        return (f"{_de(pct)} % besser als im Monat davor: gleiches Tempo bei "
                "weniger Puls. Genau darauf kommt es an.")
    if pct <= -1.5:
        return (f"{_de(abs(pct))} % schlechter als im Monat davor. Das kommt von "
                "zu viel Intensität, zu wenig Schlaf oder schlicht von Hitze — "
                "einzelne Wochen sagen noch nichts.")
    return f"Unverändert gegenüber dem Monat davor ({_de(pct)} %)."


def _volume(recent: list[dict[str, Any]], previous: list[dict[str, Any]]) -> dict[str, Any]:
    km_now = sum(r["km"] for r in recent)
    km_before = sum(r["km"] for r in previous)
    longest = max((r["km"] for r in recent), default=0.0)
    return {
        "km_4w": round(km_now, 1),
        "km_per_week": round(km_now / 4, 1),
        "km_before": round(km_before, 1),
        "runs": len(recent),
        "longest": round(longest, 1),
        # 04_Cardio_Laufen_HIIT.md: Die Obergrenze fuer den naechsten langen Lauf.
        "long_run_limit": round(longest * LONG_RUN_FACTOR, 1) if longest else 0.0,
        "limit_window_days": LONG_RUN_WINDOW_DAYS,
    }


# ----------------------------------------------------------------- Laufform

# Jede Kennzahl mit ihrem guenstigen Bereich. Die Grenzen sind bewusst grob:
# Bodenkontaktzeit und vertikales Verhaeltnis haengen vom Tempo ab, die Kadenz
# von der Koerpergroesse. Es geht um die Groessenordnung, nicht um einen
# Sollwert, den man treffen muss.
FORM_METRICS: list[dict[str, Any]] = [
    dict(key="avg_cadence", label="Schrittfrequenz", unit="spm", digits=0,
         good=(168, 185), ok=(160, 192), direction=1,
         what="Schritte pro Minute.",
         why="Kürzere, häufigere Schritte heißen: Du landest näher unter dem "
             "Körper statt weit davor. Das bremst weniger und belastet Knie "
             "und Schienbein spürbar geringer.",
         low="Unter 160 deutet auf zu lange Schritte hin. Nimm bei gleichem "
             "Tempo bewusst kürzere, schnellere Schritte — zehn Minuten pro "
             "Lauf reichen, der Rest kommt von selbst.",
         high="Ungewöhnlich hoch. Solange es sich rund anfühlt, ist daran "
              "nichts falsch."),
    dict(key="ground_contact_ms", label="Bodenkontakt", unit="ms", digits=0,
         good=(0, 250), ok=(0, 300), direction=-1,
         what="Wie lange ein Fuß pro Schritt am Boden bleibt.",
         why="Je kürzer der Kontakt, desto weniger Zeit zum Abbremsen. Der "
             "Wert folgt der Schrittfrequenz: Wer kürzer tritt, steht kürzer.",
         low="", high="Über 300 ms ist lang. Das bessert sich meist von allein, "
                      "wenn die Schrittfrequenz steigt."),
    dict(key="vertical_ratio", label="Vertikales Verhältnis", unit="%", digits=1,
         good=(0, 8), ok=(0, 10), direction=-1,
         what="Wie viel deiner Bewegung nach oben statt nach vorn geht.",
         why="Die aussagekräftigste Formzahl der Uhr, weil sie die Hoch-"
             "bewegung ins Verhältnis zur Schrittlänge setzt. Jeder Zentimeter "
             "nach oben ist Arbeit, die dich nicht ins Ziel bringt.",
         low="", high="Über 10 % geht viel Energie nach oben. Auch das hängt "
                      "an der Schrittfrequenz — länger und höher springen "
                      "kostet mehr als kürzer und flacher laufen."),
    dict(key="vertical_osc_cm", label="Vertikale Bewegung", unit="cm", digits=1,
         good=(0, 9), ok=(0, 11), direction=-1,
         what="Wie weit dein Schwerpunkt pro Schritt auf und ab geht.",
         why="Allein wenig aussagekräftig — große Läufer schwingen mehr. "
             "Deshalb zählt vor allem das vertikale Verhältnis darüber.",
         low="", high=""),
    dict(key="avg_stride_m", label="Schrittlänge", unit="m", digits=2,
         good=None, ok=None, direction=0,
         what="Wie weit du pro Schritt kommst.",
         why="Kein Wert zum Verbessern: Schrittlänge mal Schrittfrequenz ergibt "
             "das Tempo. Interessant nur im Vergleich — länger bei gleichem "
             "Tempo heißt niedrigere Frequenz.",
         low="", high=""),
    dict(key="avg_power", label="Laufleistung", unit="W", digits=0,
         good=None, ok=None, direction=0,
         what="Geschätzte mechanische Leistung in Watt.",
         why="Reagiert schneller als der Puls und ist von Hitze und Steigung "
             "unabhängig — nützlich, um am Berg gleichmäßig zu laufen.",
         low="", high=""),
]


def _band_for(value: float, spec: dict[str, Any]) -> str:
    if not spec["good"]:
        return "info"
    lo, hi = spec["good"]
    if lo <= value <= hi:
        return "good"
    ok_lo, ok_hi = spec["ok"]
    if ok_lo <= value <= ok_hi:
        return "ok"
    return "warn"


def form(data: dict[str, Any], today: dt.date) -> list[dict[str, Any]]:
    """Die Formkennzahlen: Schnitt der letzten vier Wochen gegen den Monat davor."""
    window_from = (today - dt.timedelta(days=WINDOW_DAYS)).isoformat()
    prev_from = (today - dt.timedelta(days=WINDOW_DAYS * 2)).isoformat()
    long_enough = [r for r in data["runs"] if (r["distance_m"] or 0) >= MIN_TREND_M]
    recent = [r for r in long_enough if r["day"] >= window_from]
    previous = [r for r in long_enough if prev_from <= r["day"] < window_from]

    out: list[dict[str, Any]] = []
    for spec in FORM_METRICS:
        now = _mean([float(r[spec["key"]]) for r in recent if r.get(spec["key"])])
        if now is None:
            continue
        was = _mean([float(r[spec["key"]]) for r in previous if r.get(spec["key"])])
        band = _band_for(now, spec)
        delta = round(now - was, spec["digits"]) if was is not None else None
        note = ""
        if band in ("ok", "warn") and spec["good"]:
            note = spec["high"] if now > spec["good"][1] else spec["low"]
        out.append({
            "key": spec["key"], "label": spec["label"], "unit": spec["unit"],
            "value": round(now, spec["digits"]) if spec["digits"] else round(now),
            "text": _de(now, spec["digits"]),
            "delta": delta, "band": band, "runs": len(recent),
            "reference": _reference_text(spec),
            "what": spec["what"], "why": spec["why"], "note": note,
        })
    return out


def _reference_text(spec: dict[str, Any]) -> str | None:
    if not spec["good"]:
        return None
    lo, hi = spec["good"]
    if lo <= 0:
        return f"günstig unter {_de(hi, spec['digits'])} {spec['unit']}"
    return f"günstig {_de(lo, spec['digits'])}–{_de(hi, spec['digits'])} {spec['unit']}"


# ------------------------------------------------------------------- Tipps

# Jeder Tipp traegt seine Dringlichkeit mit sich. Am Ende wird sortiert und
# abgeschnitten: Fuenf Hinweise liest man, zwoelf ueberliest man.
MAX_TIPS = 5


def tips(vo2: dict[str, Any], hr: dict[str, Any],
         form_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Was konkret zu tun ist — jeder Punkt mit der Zahl, aus der er folgt.

    Reihenfolge nach Wirkung: Erst die Verteilung der Intensitaet, dann der
    Umfang, dann der Reiz, dann die Form. Das ist auch die Reihenfolge, in der
    04_Cardio_Laufen_HIIT.md die Hebel nennt — an der Laufform zu arbeiten,
    solange die lockeren Laeufe zu schnell sind, bringt nichts.
    """
    found: list[dict[str, Any]] = []
    zones = hr.get("zones") or {}
    volume = hr.get("volume") or {}
    target = round(EASY_SHARE_TARGET * 100)

    easy_share = zones.get("easy_share")
    if easy_share is not None and easy_share < 70:
        found.append(dict(
            rank=10, level="warn", title="Lauf die lockeren Läufe langsamer",
            because=f"{easy_share} % deiner Laufzeit in Zone 1–2 statt {target} %",
            text=("Nimm bei den lockeren Läufen 30–45 Sekunden pro Kilometer "
                  "heraus, bis du in ganzen Sätzen reden könntest. Es fühlt sich "
                  "falsch langsam an — genau das ist der Punkt. Der Reiz kommt "
                  "aus dem einen harten Lauf pro Woche, nicht aus allen.")))
    elif easy_share is not None and easy_share < target:
        found.append(dict(
            rank=6, level="ok", title="Etwas mehr Zeit im lockeren Bereich",
            because=f"{easy_share} % in Zone 1–2, {target} % wären das Ziel",
            text=("Du bist nah dran. Ein einzelner Lauf pro Woche, bei dem du "
                  "bewusst langsamer bleibst, reicht meist, um die Verteilung "
                  "hinzubekommen.")))

    hard_share = zones.get("hard_share")
    if hard_share is not None and hard_share < 5 and (volume.get("runs") or 0) >= 4:
        found.append(dict(
            rank=9, level="ok", title="Ein harter Lauf pro Woche fehlt",
            because=f"{hard_share} % deiner Laufzeit in Zone 4–5",
            text=("Ohne Temporeiz bleibt das Renntempo stehen, auch wenn der "
                  "Umfang stimmt. Am besten belegt sind Intervalle: 4 × 4 "
                  "Minuten zügig mit 3 Minuten Traben dazwischen, einmal pro "
                  "Woche. Mehr als einmal bringt nichts und kostet Erholung.")))
    elif hard_share is not None and hard_share > 25:
        found.append(dict(
            rank=8, level="warn", title="Zu viel im harten Bereich",
            because=f"{hard_share} % deiner Laufzeit in Zone 4–5",
            text=("Mehr als ein Viertel hart ist auf Dauer nicht verdaulich. "
                  "Streich eine der harten Einheiten und lauf sie locker — der "
                  "Fortschritt entsteht in der Erholung danach, nicht im Reiz "
                  "selbst.")))

    change = vo2.get("change")
    if change and change["delta"] <= -1.0:
        found.append(dict(
            rank=7, level="warn", title="VO2max fällt — sieh dir den Umfang an",
            because=f"{_de(change['from'])} → {_de(change['to'])} ml/kg/min "
                    f"über {change['weeks']} Wochen",
            text=(f"Du läufst aktuell {_de(volume.get('km_per_week') or 0)} km "
                  "pro Woche. Der Wert reagiert vor allem auf regelmäßige "
                  "lockere Kilometer. Ein zusätzlicher lockerer Lauf pro Woche "
                  "wirkt hier mehr als eine härtere Einheit.")))

    if volume.get("km_before") and volume.get("km_4w", 0) < volume["km_before"] * 0.8:
        found.append(dict(
            rank=5, level="ok", title="Der Umfang ist zurückgegangen",
            because=f"{_de(volume['km_4w'])} km in vier Wochen, davor "
                    f"{_de(volume['km_before'])} km",
            text=("Bau die Kilometer wieder auf, aber über den nächsten langen "
                  f"Lauf nicht über {_de(volume.get('long_run_limit') or 0)} km "
                  "hinaus — das ist die Grenze aus deinem längsten Lauf der "
                  f"letzten {volume.get('limit_window_days')} Tage plus 10 %. "
                  "Der einzelne zu lange Lauf ist der Verletzungsgrund, nicht "
                  "die Wochensumme.")))

    eff = hr.get("efficiency") or {}
    if eff.get("change_pct") is not None and eff["change_pct"] <= -3:
        found.append(dict(
            rank=6, level="warn", title="Gleiches Tempo kostet dich mehr Puls",
            because=f"Effizienz {_de(eff['change_pct'])} % gegenüber dem Monat davor",
            text=("Das ist meist kein Formverlust, sondern Erschöpfung: zu wenig "
                  "Schlaf, zu viele harte Einheiten oder ein Infekt im Anmarsch. "
                  "Eine lockere Woche klärt das schneller als jede Analyse.")))

    resting = hr.get("resting") or {}
    if resting.get("delta") is not None and resting["delta"] >= 3:
        found.append(dict(
            rank=9, level="warn", title="Ruhepuls ist gestiegen",
            because=f"{resting['value']} bpm, {_de(resting['delta'])} Schläge "
                    "mehr als im Monat davor",
            text=("Drei Schläge und mehr sind selten Zufall. Lauf ein paar Tage "
                  "nur locker und sieh dir Schlaf und Stress an, bevor du die "
                  "nächste harte Einheit legst.")))

    for row in form_rows:
        if row["band"] == "warn" and row["note"]:
            found.append(dict(
                rank=4, level="ok", title=f"Laufform: {row['label']}",
                because=f"{row['label']} {row['text']} {row['unit']} "
                        f"({row['reference']})",
                text=row["note"]))

    goal = vo2.get("goal")
    if goal and not goal.get("reached") and goal.get("gap_s", 0) > 0:
        gap_min = goal["gap_s"] / 60
        found.append(dict(
            rank=3, level="info", title="Was bis zum Ziel fehlt",
            because=f"Prognose {goal['predicted_text']} auf "
                    f"{_de(goal['distance_km'], 0)} km, Ziel "
                    f"{_de(goal['time_min'], 0)} Minuten",
            text=(f"Rund {_de(gap_min, 0)} Minuten Rückstand. Das Renntempo "
                  f"dafür wäre {goal['required_pace']}/km — übe es in Blöcken "
                  "von 6 Minuten, damit du es im Rennen wiedererkennst.")))

    if not found:
        if not zones and not form_rows and not vo2.get("value"):
            found.append(dict(
                rank=0, level="info", title="Noch nichts zu bewerten",
                because=f"{volume.get('runs', 0)} Läufe in vier Wochen, "
                        "ohne Puls-, Zonen- oder Formdaten",
                text=("Die Läufe sind da, aber ohne die Daten der Uhr. Nach dem "
                      "nächsten Garmin-Sync stehen hier Zonenverteilung, "
                      "Laufform und die Tipps, die daraus folgen.")))
        else:
            found.append(dict(
                rank=0, level="good", title="Nichts zu korrigieren",
                because="Verteilung, Umfang und Form liegen im Rahmen",
                text=("Weitermachen. Der nächste Schritt ist schlicht: ein paar "
                      "Wochen dasselbe, nur etwas mehr davon.")))

    found.sort(key=lambda t: -t["rank"])
    return found[:MAX_TIPS]


# ------------------------------------------------------------------ Gesamt

def overview(today: dt.date | None = None) -> dict[str, Any]:
    """Alles zusammen — der Inhalt des Laufreiters unterhalb der Liste."""
    today = today or dt.date.today()
    data = _read(today)
    if not data["runs"]:
        return {"runs": 0,
                "hint": ("Noch keine Läufe aufgezeichnet. Nach dem ersten "
                         "Garmin-Sync steht hier die Auswertung.")}
    vo2 = vo2max(data, today)
    hr = pulse(data, today)
    form_rows = form(data, today)
    return {
        "runs": len(data["runs"]),
        "vo2max": vo2,
        "pulse": hr,
        "form": form_rows,
        "tips": tips(vo2, hr, form_rows),
    }
