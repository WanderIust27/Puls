"""Schlaf und Vitalwerte — das Wenige, das etwas entscheidet.

Die Uhr liefert vierzig Zahlen pro Tag. Die meisten davon sagen einem
Menschen nichts, und eine Zahl, die man nicht einordnen kann, ist keine
Information, sondern Beunruhigung. Deshalb stehen hier sechs Werte, und jeder
bringt drei Dinge mit:

* Was er heute ist — gegen die eigene Basislinie der letzten vier Wochen,
  nicht gegen einen Tabellenwert. 52 Schlaege Ruhepuls sind fuer den einen
  hoch und fuer den anderen niedrig.
* Wohin er sich bewegt — die letzten sieben Tage gegen die drei Wochen davor.
* Was er ueberhaupt bedeutet. Ein Satz, kein Lehrbuch.

Und die Frage, die abends zaehlt: Wann muss ich ins Bett?
"""
from __future__ import annotations

import datetime as dt
import logging
import statistics
from typing import Any

from ..constants import GAIN_RATE_RANGE, LOSS_RATE_RANGE
from ..db import get_db, get_setting, rows_to_dicts

log = logging.getLogger("puls.vital")

BASELINE_DAYS = 28        # Vergleichsfenster fuer die eigene Basislinie
MIN_DAYS = 5              # darunter ist eine Basislinie geraten
RECENT_DAYS = 7
SPIKE_SIGMA = 1.4         # ab hier "schlaegt aus"

# Die sechs, die etwas entscheiden. richtung: 1 = mehr ist besser.
METRICS: list[dict[str, Any]] = [
    dict(key="sleep_hours", column="sleep_seconds", label="Schlaf", unit="h",
         direction=1, scale=1 / 3600, digits=1,
         what="Wie lange du tatsächlich geschlafen hast — nicht, wie lange du "
              "im Bett warst.",
         why="Die einzige Erholungsmaßnahme, die nichts kostet und die keine "
             "andere ersetzt."),
    dict(key="hrv_avg", column="hrv_avg", label="Herzratenvariabilität",
         unit="ms", direction=1, scale=1.0, digits=0,
         what="Der Abstand zwischen zwei Herzschlägen schwankt. Je mehr, "
              "desto entspannter das Nervensystem.",
         why="Fällt sie deutlich unter deinen Schnitt, steckt der Körper "
             "etwas weg — Training, Infekt oder Stress."),
    dict(key="resting_hr", column="resting_hr", label="Ruhepuls", unit="bpm",
         direction=-1, scale=1.0, digits=0,
         what="Dein niedrigster Puls im Schlaf.",
         why="Über Wochen sinkend heißt: Die Ausdauer wächst. Plötzlich fünf "
             "Schläge höher heißt meistens: Erkältung im Anmarsch."),
    dict(key="body_battery_wake", column="body_battery_wake",
         label="Körperakku beim Aufwachen", unit="%", direction=1, scale=1.0,
         digits=0,
         what="Was die Uhr aus Puls, Schlaf und Stress als Ladestand rechnet.",
         why="Unter 60 beim Aufwachen heißt: Die Nacht hat nicht gereicht."),
    dict(key="stress_avg", column="stress_avg", label="Stress am Tag",
         unit="", direction=-1, scale=1.0, digits=0,
         what="Tagesmittel der Uhr, 0 bis 100.",
         why="Hoher Stress verbraucht dieselbe Erholung wie Training — nur "
             "ohne den Trainingsreiz."),
    dict(key="respiration_avg", column="respiration_avg", label="Atemfrequenz",
         unit="/min", direction=-1, scale=1.0, digits=1,
         what="Atemzüge pro Minute im Schlaf.",
         why="Steigt oft ein bis zwei Nächte vor spürbaren Symptomen — der "
             "leiseste Frühwarnwert, den die Uhr hat."),
]


def _fmt(value: float, digits: int) -> float | int:
    """Ganze Zahlen als ganze Zahlen. „34.0 ms" liest sich wie eine Messung
    mit Nachkommastelle, die es nicht gibt."""
    return int(round(value)) if digits == 0 else round(value, digits)


def _series(column: str, since: str, until: str) -> list[dict[str, Any]]:
    with get_db() as db:
        return rows_to_dicts(db.execute(
            f"SELECT day, {column} AS v FROM daily_metrics "
            f"WHERE day >= ? AND day <= ? AND {column} IS NOT NULL "
            f"ORDER BY day", (since, until)).fetchall())


def metrics(today: dt.date | None = None) -> dict[str, Any]:
    """Die sechs Werte mit Basislinie, Trend und Erklärung."""
    today = today or dt.date.today()
    floor = (today - dt.timedelta(days=BASELINE_DAYS)).isoformat()
    recent_from = (today - dt.timedelta(days=RECENT_DAYS)).isoformat()

    out: list[dict[str, Any]] = []
    for spec in METRICS:
        rows = _series(spec["column"], floor, today.isoformat())
        if len(rows) < MIN_DAYS:
            continue
        values = [r["v"] * spec["scale"] for r in rows]
        latest_row = rows[-1]
        latest = latest_row["v"] * spec["scale"]

        median = statistics.median(values)
        spread = statistics.pstdev(values) if len(values) > 2 else 0.0
        # Ohne Streuung gibt es keinen Ausschlag — dann ist jeder Wert normal.
        sigma = (latest - median) / spread if spread > 0.01 else 0.0

        recent = [r["v"] * spec["scale"] for r in rows if r["day"] >= recent_from]
        before = [r["v"] * spec["scale"] for r in rows if r["day"] < recent_from]
        change = None
        direction_word = "hält"
        better = None
        if len(recent) >= 3 and len(before) >= 3:
            now, then = statistics.mean(recent), statistics.mean(before)
            change = (now - then) / then if then else None
            if change is not None:
                if abs(change) < 0.02:
                    direction_word, better = "hält", None
                else:
                    direction_word = "steigt" if change > 0 else "fällt"
                    better = (change > 0) == (spec["direction"] > 0)

        out.append({
            "key": spec["key"], "label": spec["label"], "unit": spec["unit"],
            "value": _fmt(latest, spec["digits"]),
            "day": latest_row["day"],
            "baseline": _fmt(median, spec["digits"]),
            "sigma": round(sigma, 2),
            "spike": abs(sigma) >= SPIKE_SIGMA,
            "good": None if abs(sigma) < 0.6 else (sigma > 0) == (spec["direction"] > 0),
            "change_pct": round(change * 100, 1) if change is not None else None,
            "direction": direction_word,
            "better": better,
            "what": spec["what"], "why": spec["why"],
            "points": [{"day": r["day"],
                        "value": _fmt(r["v"] * spec["scale"], spec["digits"])}
                       for r in rows],
        })

    spikes = [m for m in out if m["spike"]]
    spikes.sort(key=lambda m: -abs(m["sigma"]))
    spikes = spikes[:MAX_SPIKES]
    return {"metrics": out, "spikes": spikes,
            "hint": None if out else
                    "Noch keine Vitaldaten. Sie kommen mit dem Garmin-Sync."}


def spike_sentence(metric: dict[str, Any]) -> str:
    """Ein Satz, der einen Ausschlag einordnet — nur der Ausschlag.

    Die Bewertung steht einmal ueber der Liste, nicht hinter jeder Zeile.
    Sechsmal "Das ist die Richtung, auf die man achten sollte" liest niemand
    zu Ende, und beim zweiten Mal glaubt es auch niemand mehr.
    """
    away = abs(metric["value"] - metric["baseline"])
    side = "über" if metric["value"] > metric["baseline"] else "unter"
    unit = f" {metric['unit']}" if metric["unit"] else ""
    return (f"{metric['label']}: {metric['value']:g}{unit} — "
            f"{away:g}{unit} {side} deinem Schnitt von "
            f"{metric['baseline']:g}{unit}.")


# Mehr als drei Ausschlaege sind keine Meldung mehr, sondern eine Liste.
# Wer sechs Zeilen sieht, liest keine davon.
MAX_SPIKES = 3


def spike_lead(spikes: list[dict[str, Any]]) -> str | None:
    """Ein Satz ueber die Liste — was die Ausschlaege zusammen bedeuten."""
    if not spikes:
        return None
    bad = [m for m in spikes if m["good"] is False]
    if not bad:
        return "Ungewöhnlich, aber in die gute Richtung."
    if len(bad) >= 3:
        return ("Mehrere Werte zeigen gleichzeitig nach unten. Das ist selten "
                "Zufall — meistens steckt eine harte Einheit, zu wenig Schlaf "
                "oder ein Infekt dahinter. Heute nichts erzwingen.")
    if len(bad) == 2:
        return ("Zwei Werte liegen deutlich neben deinem Schnitt. Einmal kann "
                "das ein Ausreißer sein — bleibt es morgen so, ist es keiner.")
    return ("Ein Wert liegt deutlich neben deinem Schnitt. Beobachten, noch "
            "nichts ändern.")


# ------------------------------------------------------------ Einschlafzeit

BASE_NEED_H = 8.0
MAX_EXTRA_H = 1.5
DEFAULT_LATENCY_MIN = 15


def _latency_minutes(today: dt.date) -> tuple[int, str]:
    """Wie lange du zum Einschlafen brauchst — aus deinen eigenen Naechten.

    Zeit im Bett minus tatsaechlich geschlafene Zeit. Erst ab fuenf Naechten,
    vorher ist es geraten und wird auch so genannt.
    """
    floor = (today - dt.timedelta(days=BASELINE_DAYS)).isoformat()
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT sleep_start, sleep_end, sleep_seconds FROM daily_metrics "
            "WHERE day >= ? AND sleep_start IS NOT NULL AND sleep_end IS NOT NULL "
            "AND sleep_seconds IS NOT NULL", (floor,)).fetchall())
    gaps = []
    for row in rows:
        try:
            start = dt.datetime.fromisoformat(str(row["sleep_start"])[:19])
            end = dt.datetime.fromisoformat(str(row["sleep_end"])[:19])
        except ValueError:
            continue
        in_bed = (end - start).total_seconds()
        gap = (in_bed - row["sleep_seconds"]) / 60.0
        if 0 <= gap <= 90:
            gaps.append(gap)
    if len(gaps) < MIN_DAYS:
        return DEFAULT_LATENCY_MIN, "Vorgabewert, noch zu wenige Nächte gemessen"
    return round(statistics.median(gaps)), f"aus {len(gaps)} deiner Nächte"


def _sleep_need(today: dt.date) -> dict[str, Any]:
    """Acht Stunden plus Zuschlaege — und jeder Zuschlag wird benannt.

    Eine Zahl, die von acht auf neuneinhalb springt, ohne dass jemand sagt
    warum, haelt man fuer einen Fehler.
    """
    reasons: list[str] = []
    extra = 0.0
    floor = (today - dt.timedelta(days=BASELINE_DAYS)).isoformat()

    with get_db() as db:
        latest = db.execute(
            "SELECT * FROM daily_metrics WHERE day <= ? ORDER BY day DESC LIMIT 1",
            (today.isoformat(),)).fetchone()
        nights = rows_to_dicts(db.execute(
            "SELECT sleep_seconds FROM daily_metrics WHERE day >= ? "
            "AND sleep_seconds IS NOT NULL ORDER BY day DESC LIMIT 3",
            (floor,)).fetchall())
        hard = db.execute(
            "SELECT MAX(duration_s) AS s FROM activities "
            "WHERE substr(start_time,1,10) = ?",
            ((today - dt.timedelta(days=1)).isoformat(),)).fetchone()

    row = dict(latest) if latest else {}
    if row.get("training_readiness") is not None and row["training_readiness"] < 40:
        extra += 0.5
        reasons.append("Trainingsbereitschaft niedrig")
    if row.get("hrv_avg") and row.get("hrv_baseline_low") \
            and row["hrv_avg"] < row["hrv_baseline_low"]:
        extra += 0.5
        reasons.append("HRV unter deiner Basislinie")
    if hard and hard["s"] and hard["s"] > 75 * 60:
        extra += 0.5
        reasons.append("lange Einheit gestern")

    # Schlafschuld der letzten Naechte, hoechstens eine halbe Stunde davon.
    if nights:
        debt = sum(max(0.0, BASE_NEED_H - n["sleep_seconds"] / 3600.0)
                   for n in nights)
        if debt > 0.5:
            add = min(0.5, debt / 3)
            extra += add
            reasons.append(f"{debt:.1f} h Rückstand aus den letzten Nächten")

    extra = min(extra, MAX_EXTRA_H)
    return {"hours": round(BASE_NEED_H + extra, 2), "base": BASE_NEED_H,
            "extra": round(extra, 2), "reasons": reasons}


def bedtime(today: dt.date | None = None) -> dict[str, Any]:
    """Wann du ins Bett solltest — rueckwaerts vom Aufstehziel gerechnet."""
    today = today or dt.date.today()
    target = get_setting("wake_target", "06:30") or "06:30"
    try:
        hour, minute = (int(x) for x in target.split(":"))
    except ValueError:
        hour, minute = 6, 30

    need = _sleep_need(today)
    latency, latency_from = _latency_minutes(today)

    wake = dt.datetime.combine(today + dt.timedelta(days=1),
                               dt.time(hour % 24, minute % 60))
    go_to_bed = wake - dt.timedelta(hours=need["hours"], minutes=latency)

    now = dt.datetime.now()
    minutes_left = int((go_to_bed - now).total_seconds() / 60)
    return {
        "bedtime": go_to_bed.strftime("%H:%M"),
        "wake_target": f"{hour % 24:02d}:{minute % 60:02d}",
        "need_h": need["hours"],
        "need_base": need["base"],
        "need_extra": need["extra"],
        "need_reasons": need["reasons"],
        "latency_min": latency,
        "latency_from": latency_from,
        "minutes_left": minutes_left,
        "formula": (f"{f'{hour % 24:02d}:{minute % 60:02d}'} Aufstehen "
                    f"− {need['hours']:g} h Schlaf "
                    f"− {latency} min Einschlafen"),
    }


# -------------------------------------------------------------- Regelmaessigkeit

def regularity(today: dt.date | None = None) -> dict[str, Any] | None:
    """Wie gleichmaessig du ins Bett gehst.

    Der Zeitpunkt zaehlt fast so viel wie die Dauer: Ein Koerper, der jeden
    Abend zu einer anderen Zeit schlafen geht, erholt sich schlechter als
    einer mit sieben ruhigen Stunden nach Plan.
    """
    today = today or dt.date.today()
    floor = (today - dt.timedelta(days=14)).isoformat()
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT day, sleep_start, sleep_end FROM daily_metrics "
            "WHERE day >= ? AND sleep_start IS NOT NULL ORDER BY day",
            (floor,)).fetchall())
    starts = []
    for row in rows:
        try:
            stamp = dt.datetime.fromisoformat(str(row["sleep_start"])[:19])
        except ValueError:
            continue
        # Minuten seit 18 Uhr, damit Mitternacht keinen Sprung macht.
        minutes = (stamp.hour * 60 + stamp.minute - 18 * 60) % (24 * 60)
        starts.append(minutes)
    if len(starts) < MIN_DAYS:
        return None

    spread = statistics.pstdev(starts) if len(starts) > 1 else 0.0
    middle = statistics.median(starts)
    hour = int((middle + 18 * 60) % (24 * 60)) // 60
    minute = int((middle + 18 * 60) % (24 * 60)) % 60
    return {
        "nights": len(starts),
        "typical": f"{hour:02d}:{minute:02d}",
        "spread_min": round(spread),
        "verdict": ("sehr regelmäßig" if spread <= 20 else
                    "regelmäßig" if spread <= 40 else
                    "schwankend" if spread <= 75 else "unregelmäßig"),
        "note": ("Der Zeitpunkt zählt fast so viel wie die Dauer."
                 if spread > 40 else
                 "Der Rhythmus sitzt — das ist die halbe Erholung."),
    }


def overview(today: dt.date | None = None) -> dict[str, Any]:
    """Alles für den Reiter: Erholung, Werte, Ausschläge, Einschlafzeit."""
    from . import today as today_svc

    today = today or dt.date.today()
    data = metrics(today)
    return {
        "readiness": today_svc.readiness(today),
        "metrics": data["metrics"],
        "spikes": [{**m, "sentence": spike_sentence(m)} for m in data["spikes"]],
        "spike_lead": spike_lead(data["spikes"]),
        "hint": data["hint"],
        "bedtime": bedtime(today),
        "regularity": regularity(today),
        "weight": weight(today),
    }


# ------------------------------------------------------------------ Gewicht
#
# Gerechnet wird auf der geglaetteten Reihe aus body.trend(): Dort sind die
# Messungen schon aufs Referenzfenster umgerechnet und ueber sieben Kalendertage
# geglaettet. Einzelwerte schwanken um mehr als jede sinnvolle woechentliche
# Veraenderung — aus ihnen einen Trend zu lesen hiesse, Rauschen zu deuten.

WEIGHT_WEEKS = 8          # so weit zurueck wird gezeigt
RATE_WEEKS = 4            # ueber so viele Wochen wird die Rate gelegt
HOLD_BAND_PCT = 0.15      # darunter gilt das Gewicht als stabil

GOAL_WORDS: list[tuple[tuple[str, ...], str]] = [
    (("abnehmen", "definieren", "diät", "diat", "cut", "sixpack", "leichter",
      "körperfett reduzieren", "fett verlieren"), "lose"),
    (("zunehmen", "aufbauen", "masse", "muskelaufbau", "bulk", "schwerer",
      "muskeln aufbauen"), "gain"),
]

GOAL_LABEL = {"gain": "Aufbau", "lose": "Abnehmen", "hold": "Halten"}


def weight_goal() -> dict[str, str]:
    """Aufbau, Abnehmen oder Halten — gelesen aus dem Freitext-Ziel.

    Kein eigener Schalter: Das Ziel steht schon irgendwo, und zwei Stellen,
    die dasselbe sagen sollen, sagen irgendwann Verschiedenes. Was gelesen
    wurde, steht in der Anzeige — wer nicht einverstanden ist, aendert das Ziel.
    """
    text = (get_setting("goal_text", "") or "").lower()
    for words, direction in GOAL_WORDS:
        if any(w in text for w in words):
            return {"direction": direction, "label": GOAL_LABEL[direction],
                    "from": "aus deinem Ziel gelesen"}
    return {"direction": "hold", "label": GOAL_LABEL["hold"],
            "from": "im Ziel steht nichts zum Gewicht — angenommen: halten"}


def _weekly(points: list[dict[str, Any]], field: str) -> list[dict[str, Any]]:
    """Tageswerte zu Wochenmitteln zusammenfassen."""
    buckets: dict[str, list[float]] = {}
    days: dict[str, str] = {}
    for p in points:
        value = p.get(field)
        if value is None:
            continue
        day = dt.date.fromisoformat(p["day"])
        monday = (day - dt.timedelta(days=day.weekday())).isoformat()
        buckets.setdefault(monday, []).append(value)
        days[monday] = max(days.get(monday, ""), p["day"])
    return [{"week": week, "day": days[week],
             "value": round(sum(v) / len(v), 2), "count": len(v)}
            for week, v in sorted(buckets.items())]


def _slope_per_week(weeks: list[dict[str, Any]]) -> float | None:
    """Steigung je Woche, kleinste Quadrate ueber die Wochenmittel.

    Woche gegen Vorwoche waere anfaelliger: Eine einzelne schwere Woche kippte
    die Aussage, obwohl sich ueber einen Monat nichts bewegt hat.
    """
    if len(weeks) < 3:
        return None
    xs = list(range(len(weeks)))
    ys = [w["value"] for w in weeks]
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    denominator = sum((x - mx) ** 2 for x in xs)
    if denominator == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denominator


def _pct(value: float, digits: int = 2) -> str:
    """Prozentangabe mit Komma. Der Satz wird gelesen, nicht geparst."""
    return f"{value:.{digits}f}".replace(".", ",")


def _band(value: float) -> str:
    """Eine Korridorgrenze ohne unnoetige Null: 0,5 statt 0,50."""
    return f"{value:g}".replace(".", ",")


def _verdict(rate_pct: float | None, direction: str) -> tuple[str, str]:
    """Die Einordnung: Ist die Veraenderung die, die du wolltest?"""
    if rate_pct is None:
        return "offen", ("Noch zu wenige Wochen für einen Trend. Ab drei "
                         "Wochen steht hier eine Einordnung.")
    speed = abs(rate_pct)

    if direction == "hold":
        if speed <= HOLD_BAND_PCT:
            return "stabil", ("Das Gewicht steht. Genau das ist gemeint, wenn "
                              "im Ziel nichts vom Gewicht steht.")
        way = "nach oben" if rate_pct > 0 else "nach unten"
        return "driftet", (
            f"Das Gewicht driftet {way} — {_pct(speed)} % pro Woche. Über ein "
            "Vierteljahr sind das rund "
            f"{_pct(speed * 13, 0)} % Körpergewicht. Das passiert nicht aus "
            "Versehen zweimal; entweder ist es gewollt, dann gehört es ins "
            "Ziel, oder die Kalorien stimmen nicht.")

    if direction == "gain":
        low, high = GAIN_RATE_RANGE
        if rate_pct < 0:
            return "falsche Richtung", (
                f"Du willst aufbauen, das Gewicht fällt aber um "
                f"{_pct(speed)} % pro Woche. So geht kein Muskel dazu — "
                "da fehlen schlicht Kalorien.")
        if rate_pct < low * 0.8:
            return "zu langsam", (
                f"{_pct(rate_pct)} % pro Woche ist wenig für einen Aufbau. "
                f"Der Korridor liegt bei {_band(low)}–{_band(high)} %. Etwa 150 kcal "
                "mehr am Tag, dann zwei Wochen abwarten.")
        if rate_pct > high * 1.4:
            return "zu schnell", (
                f"{_pct(rate_pct)} % pro Woche ist mehr als der Korridor von "
                f"{_band(low)}–{_band(high)} %. Schneller heißt nicht mehr Muskel, "
                "sondern mehr Fett — der Muskel wächst nicht schneller, nur "
                "weil mehr Energie da ist.")
        return "im Korridor", (
            f"{_pct(rate_pct)} % pro Woche liegt im Korridor von {_band(low)}–{_band(high)} %. "
            "Genau so soll ein Aufbau aussehen.")

    low, high = LOSS_RATE_RANGE
    if rate_pct > 0:
        return "falsche Richtung", (
            f"Du willst abnehmen, das Gewicht steigt aber um {_pct(speed)} % "
            "pro Woche.")
    if speed < low * 0.6:
        return "steht", (
            f"{_pct(speed)} % pro Woche ist kaum Bewegung. Der Korridor liegt "
            f"bei {_band(low)}–{_band(high)} %. Entweder mehr Geduld oder weniger "
            "Kalorien — aber nicht beides gleichzeitig ändern.")
    if speed > high * 1.2:
        return "zu schnell", (
            f"{_pct(speed)} % pro Woche ist mehr als der Korridor von "
            f"{_band(low)}–{_band(high)} %. Ab hier geht ein nennenswerter Teil davon "
            "als Muskel weg, nicht als Fett.")
    return "im Korridor", (
        f"{_pct(speed)} % pro Woche liegt im Korridor von {_band(low)}–{_band(high)} %. "
        "Das ist das Tempo, bei dem der Muskel bleibt.")


COMPOSITION = [
    dict(field="body_fat_pct", label="Körperfett", unit="%", digits=1,
         what="Aus der Impedanz der Waage geschätzt, nicht gemessen."),
    dict(field="muscle_kg", label="Muskelmasse", unit="kg", digits=1,
         what="Ebenfalls geschätzt — gut für die Richtung, nicht als Wahrheit."),
]


def _composition(today: dt.date) -> list[dict[str, Any]]:
    """Koerperfett und Muskelmasse als Wochenmittel, mit Veraenderung."""
    from . import body

    floor = (today - dt.timedelta(days=WEIGHT_WEEKS * 7)).isoformat()
    rows = [r for r in body.measurements(WEIGHT_WEEKS * 7) if r["day"] >= floor]
    out = []
    for spec in COMPOSITION:
        weeks = _weekly([{"day": r["day"], spec["field"]: r.get(spec["field"])}
                         for r in rows], spec["field"])
        if len(weeks) < 2:
            continue
        change = weeks[-1]["value"] - weeks[0]["value"]
        out.append({
            "key": spec["field"], "label": spec["label"], "unit": spec["unit"],
            "value": round(weeks[-1]["value"], spec["digits"]),
            "change": round(change, spec["digits"]),
            "weeks": len(weeks), "what": spec["what"],
            "points": [{"day": w["day"], "value": round(w["value"], spec["digits"])}
                       for w in weeks],
        })
    return out


def weight(today: dt.date | None = None) -> dict[str, Any]:
    """Gewichtsverlauf als Wochenmittel — und was der Trend bedeutet."""
    from . import body

    today = today or dt.date.today()
    points = body.trend(WEIGHT_WEEKS * 7)
    weeks = _weekly(points, "smooth_kg")
    goal = weight_goal()

    if not weeks:
        return {"weeks": [], "goal": goal, "verdict": "offen",
                "hint": "Noch keine Messungen. Sie kommen über die Waage."}

    recent = weeks[-RATE_WEEKS:]
    slope = _slope_per_week(recent)
    current = recent[-1]["value"]
    rate_pct = (slope / current * 100) if slope is not None and current else None
    verdict, sentence = _verdict(rate_pct, goal["direction"])

    last = body.latest(("weight_kg", "measured_at"))
    return {
        "current_kg": round(current, 1),
        "last_measurement": last,
        "weeks": [{"day": w["day"], "value": round(w["value"], 1)} for w in weeks],
        "rate_kg": round(slope, 2) if slope is not None else None,
        "rate_pct": round(rate_pct, 2) if rate_pct is not None else None,
        "weeks_used": len(recent),
        "span_weeks": len(weeks),
        "goal": goal,
        "verdict": verdict,
        "sentence": sentence,
        "composition": _composition(today),
        "hint": None,
    }
