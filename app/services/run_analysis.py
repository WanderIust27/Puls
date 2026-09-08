"""Bewertet einzelne Laufeinheiten.

Vier Fragen, die eine Laufeinheit beantworten sollte:

  1. War das Tempo das, was es sein sollte? Der häufigste Fehler im Breitensport
     ist, die lockeren Läufe zu schnell zu laufen — dadurch fehlt die Erholung
     für die harten Einheiten, und die Grundlage baut sich trotzdem nicht auf.
  2. Wo lag der Puls? Als Faustregel sollten rund 80 % der Wochenkilometer im
     lockeren Bereich liegen (die viel zitierte 80/20-Regel).
  3. Wie war die Lauftechnik? Schrittfrequenz, Schrittlänge und — falls ein
     Brustgurt mitlief — Bodenkontaktzeit und vertikale Bewegung.
  4. Ist die Einheit zerfallen? Wird man auf der zweiten Hälfte bei gleichem
     Tempo deutlich hochpulsiger, war die Einheit zu hart oder zu lang
     (aerobe Entkopplung).

Alle Bewertungen sind Hinweise, keine Diagnosen — fehlende Daten werden
übersprungen statt geraten.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts
from . import running

log = logging.getLogger("puls.run_analysis")

# Bewertungsstufen für die Oberfläche
GOOD, OK, WARN = "good", "ok", "warn"


def _pace_s_per_km(distance_m: float | None, duration_s: float | None) -> int | None:
    if not distance_m or not duration_s or distance_m < 300:
        return None
    return int(round(duration_s / (distance_m / 1000.0)))


def _finding(kind: str, level: str, title: str, detail: str,
             value: str | None = None) -> dict[str, Any]:
    return {"kind": kind, "level": level, "title": title, "detail": detail,
            "value": value}


# ------------------------------------------------------------------ Bausteine

def check_pace(activity: dict[str, Any], intended: str | None) -> dict[str, Any] | None:
    """Tempo gegen die kalibrierten Zonen prüfen."""
    pace = _pace_s_per_km(activity.get("distance_m"), activity.get("duration_s"))
    if not pace:
        return None
    paces = running.current_paces()
    text = running.pace_s_to_str(pace)
    if not paces:
        return _finding("pace", OK, "Tempo",
                        f"{text}/km gelaufen. Für eine Einordnung fehlt noch der "
                        "Benchmark-Lauf.", text)

    easy = paces["easy"]
    # Der lockere Bereich reicht von easy+45 s (sehr ruhig) bis easy−20 s
    if intended in (None, "easy", "long"):
        if pace < easy - 20:
            return _finding(
                "pace", WARN, "Zu schnell für einen lockeren Lauf",
                f"{text}/km — dein lockeres Tempo liegt bei "
                f"{running.pace_s_to_str(easy)}/km. Genau hier verschenken die "
                "meisten ihre Erholung: Der Reiz ist zu klein für einen harten "
                "Tag und zu groß für einen leichten.", text)
        if pace > easy + 75:
            return _finding(
                "pace", OK, "Sehr ruhig unterwegs",
                f"{text}/km — deutlich ruhiger als deine "
                f"{running.pace_s_to_str(easy)}/km. Als Regeneration völlig in "
                "Ordnung.", text)
        return _finding("pace", GOOD, "Tempo passt",
                        f"{text}/km liegt im lockeren Bereich rund um "
                        f"{running.pace_s_to_str(easy)}/km. Genau richtig.", text)

    if intended == "interval":
        # Der Gesamtschnitt enthält Ein-, Aus- und Trabpausen und liegt darum
        # zwangsläufig weit über dem Intervalltempo. Ihn zu vergleichen wäre
        # irreführend — die einzelnen Intervalle bewertet die Uhr selbst.
        return _finding(
            "pace", OK, "Tempo über die ganze Einheit",
            f"{text}/km inklusive Aufwärmen und Trabpausen. Für die Bewertung "
            f"der Intervalle selbst zählt dein Zieltempo von "
            f"{running.pace_s_to_str(paces['interval'])}/km auf den schnellen "
            "Abschnitten.", text)

    target = paces.get(intended)
    if not target:
        return _finding("pace", OK, "Tempo", f"{text}/km", text)
    diff = pace - target
    if abs(diff) <= 15:
        return _finding("pace", GOOD, "Vorgabe getroffen",
                        f"{text}/km bei einer Vorgabe von "
                        f"{running.pace_s_to_str(target)}/km.", text)
    if diff > 0:
        return _finding("pace", OK, "Etwas langsamer als geplant",
                        f"{text}/km statt {running.pace_s_to_str(target)}/km — "
                        f"{diff} s pro Kilometer daneben.", text)
    return _finding("pace", WARN, "Schneller als geplant",
                    f"{text}/km statt {running.pace_s_to_str(target)}/km. "
                    "Schneller ist nicht automatisch besser — die Einheit soll "
                    "wiederholbar bleiben.", text)


def check_hr_zones(activity: dict[str, Any],
                   intended: str | None = None) -> dict[str, Any] | None:
    """Verteilung der Zeit auf die Herzfrequenzzonen bewerten.

    Was "richtig" ist, hängt von der Einheit ab: Bei einer Tempo- oder
    Intervalleinheit gehört Zeit in Zone 4 dazu, bei einem Grundlagenlauf nicht.
    """
    raw = activity.get("hr_zones_json")
    if not raw:
        return None
    try:
        zones = {int(k): float(v) for k, v in json.loads(raw).items()}
    except (ValueError, AttributeError, TypeError):
        return None
    total = sum(zones.values())
    if total < 300:
        return None

    easy_share = (zones.get(1, 0) + zones.get(2, 0)) / total
    hard_share = (zones.get(4, 0) + zones.get(5, 0)) / total
    breakdown = " · ".join(
        f"Z{z} {round(zones.get(z, 0) / total * 100)} %" for z in range(1, 6)
        if zones.get(z, 0) > 0)

    hard_intent = intended in ("interval", "tempo")

    if hard_intent:
        if hard_share >= 0.25:
            return _finding("hr", GOOD, "Reiz gesetzt",
                            f"{round(hard_share * 100)} % der Zeit in Zone 4–5 — "
                            f"für eine harte Einheit genau das Ziel. ({breakdown})")
        return _finding("hr", OK, "Wenig Zeit im harten Bereich",
                        f"Nur {round(hard_share * 100)} % in Zone 4–5. Bei einer "
                        "Tempoeinheit dürfen die schnellen Abschnitte ruhig "
                        f"fordernder sein. ({breakdown})")

    if easy_share >= 0.75:
        return _finding("hr", GOOD, "Puls im Grundlagenbereich",
                        f"{round(easy_share * 100)} % der Zeit in Zone 1–2. "
                        f"Genau so soll ein lockerer Lauf aussehen. ({breakdown})")
    if hard_share >= 0.4:
        return _finding("hr", WARN, "Zu hart für einen Grundlagenlauf",
                        f"{round(hard_share * 100)} % in Zone 4–5. Diese Einheit "
                        "war als lockerer Lauf gedacht — so wird sie zur harten "
                        f"und kostet dich Erholung. ({breakdown})")
    return _finding("hr", OK, "Gemischter Pulsbereich",
                    f"{round(easy_share * 100)} % locker, "
                    f"{round(hard_share * 100)} % hart. ({breakdown})")


def check_cadence(activity: dict[str, Any]) -> dict[str, Any] | None:
    """Schrittfrequenz einordnen.

    Um 170–180 Schritte pro Minute gelten als günstig, weil sich damit meist
    kürzere Schritte und weniger Bremswirkung beim Aufsetzen ergeben. Der Wert
    ist aber körpergrößenabhängig und kein Selbstzweck.
    """
    cad = activity.get("avg_cadence")
    if not cad:
        return None
    val = f"{round(cad)} spm"
    if cad < 160:
        return _finding("cadence", WARN, "Niedrige Schrittfrequenz",
                        f"{val}. Unter 160 deutet meist auf zu lange Schritte hin — "
                        "du landest weit vor dem Körper und bremst dich bei jedem "
                        "Schritt. Versuch mal, bei gleichem Tempo bewusst kürzer "
                        "und häufiger zu treten.", val)
    if cad > 190:
        return _finding("cadence", OK, "Sehr hohe Schrittfrequenz",
                        f"{val}. Ungewöhnlich hoch, aber solange es sich rund "
                        "anfühlt, ist daran nichts falsch.", val)
    if 168 <= cad <= 185:
        return _finding("cadence", GOOD, "Schrittfrequenz im guten Bereich",
                        f"{val} — daran musst du nichts ändern.", val)
    return _finding("cadence", OK, "Schrittfrequenz",
                    f"{val}. Etwas Luft nach oben, aber unkritisch.", val)


def check_form(activity: dict[str, Any]) -> dict[str, Any] | None:
    """Laufeffizienz aus den Werten des Brustgurts."""
    gct = activity.get("ground_contact_ms")
    vr = activity.get("vertical_ratio")
    osc = activity.get("vertical_osc_cm")
    if not any((gct, vr, osc)):
        return None

    parts, level = [], GOOD
    if gct:
        parts.append(f"Bodenkontakt {round(gct)} ms")
        if gct > 300:
            level = OK
    if osc:
        parts.append(f"vertikale Bewegung {osc:.1f} cm")
    if vr:
        parts.append(f"vertikales Verhältnis {vr:.1f} %")
        if vr > 10:
            level = OK

    detail = ", ".join(parts) + "."
    if level == GOOD:
        detail += " Saubere Werte — die Energie geht nach vorn statt nach oben."
    else:
        detail += (" Etwas viel Aufwärtsbewegung beziehungsweise langer "
                   "Bodenkontakt. Eine höhere Schrittfrequenz hilft meist von "
                   "selbst dagegen.")
    return _finding("form", level, "Lauftechnik", detail)


def check_decoupling(activity: dict[str, Any],
                     laps: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Aerobe Entkopplung: steigt der Puls bei gleichem Tempo über die Einheit?

    Verglichen wird das Verhältnis Tempo zu Puls in der ersten und zweiten
    Hälfte. Über etwa 5 % Abweichung spricht man von Entkopplung — ein Zeichen
    dafür, dass die Einheit an der Grenze der Grundlagenausdauer lag.
    """
    usable = [l for l in (laps or [])
              if l.get("distance") and l.get("duration") and l.get("averageHR")
              and float(l["distance"]) > 400]
    if len(usable) < 4:
        return None

    mid = len(usable) // 2
    def ratio(chunk):
        dist = sum(float(l["distance"]) for l in chunk)
        dur = sum(float(l["duration"]) for l in chunk)
        hr = sum(float(l["averageHR"]) * float(l["duration"]) for l in chunk) / dur
        speed = dist / dur
        return speed / hr if hr else None

    first, second = ratio(usable[:mid]), ratio(usable[mid:])
    if not first or not second:
        return None
    drift = (first - second) / first * 100

    if drift > 8:
        return _finding("decoupling", WARN, "Deutliche Ermüdung im Verlauf",
                        f"Auf der zweiten Hälfte brauchtest du bei gleichem Tempo "
                        f"rund {drift:.0f} % mehr Puls. Die Einheit war für deine "
                        "aktuelle Grundlage zu lang oder zu schnell.",
                        f"+{drift:.0f} %")
    if drift > 4:
        return _finding("decoupling", OK, "Leichte Ermüdung",
                        f"Etwa {drift:.0f} % Pulsanstieg bei gleichem Tempo — "
                        "normal am oberen Ende einer langen Einheit.",
                        f"+{drift:.0f} %")
    return _finding("decoupling", GOOD, "Gleichmäßig durchgelaufen",
                    f"Der Puls blieb im Verhältnis zum Tempo stabil "
                    f"({drift:+.0f} %). Die Länge war gut gewählt.",
                    f"{drift:+.0f} %")


def check_progress(activity: dict[str, Any]) -> dict[str, Any] | None:
    """Vergleich mit ähnlichen Läufen der letzten Wochen."""
    pace = _pace_s_per_km(activity.get("distance_m"), activity.get("duration_s"))
    hr = activity.get("avg_hr")
    if not pace or not hr:
        return None
    with get_db() as db:
        rows = db.execute(
            "SELECT distance_m, duration_s, avg_hr FROM activities "
            "WHERE sport='running' AND id != ? AND avg_hr IS NOT NULL "
            "AND distance_m > 1000 AND date(start_time) >= date('now','-56 days') "
            "ORDER BY start_time DESC LIMIT 12", (activity["id"],)).fetchall()
    others = []
    for r in rows:
        p = _pace_s_per_km(r["distance_m"], r["duration_s"])
        if p and r["avg_hr"]:
            others.append((p, float(r["avg_hr"])))
    if len(others) < 3:
        return None

    avg_pace = sum(p for p, _ in others) / len(others)
    avg_hr = sum(h for _, h in others) / len(others)
    # Schneller bei gleichem oder niedrigerem Puls = echter Fortschritt
    faster = avg_pace - pace
    hr_diff = hr - avg_hr
    if faster > 8 and hr_diff <= 3:
        return _finding("progress", GOOD, "Das ist Fortschritt",
                        f"{running.pace_s_to_str(pace)}/km bei {round(hr)} bpm — "
                        f"im Schnitt der letzten Wochen warst du "
                        f"{running.pace_s_to_str(int(avg_pace))}/km bei "
                        f"{round(avg_hr)} bpm. Schneller bei gleichem Puls ist "
                        "genau das, worauf es ankommt.")
    if faster < -15 and hr_diff > 5:
        return _finding("progress", OK, "Schwächerer Tag",
                        "Langsamer und höherpulsig als zuletzt. Einzelne solche "
                        "Tage sind normal — Schlaf, Stress und Wetter schlagen "
                        "durch.")
    return None


# ---------------------------------------------------------------- Gesamturteil

INTENT_FROM_NAME = [
    ("interval", ("intervall", "interval")),
    ("tempo", ("tempo", "schwelle", "threshold")),
    ("long", ("lang", "long")),
    ("easy", ("locker", "easy", "grundlage", "dauerlauf")),
]


def guess_intent(name: str | None) -> str | None:
    n = (name or "").lower()
    for intent, keys in INTENT_FROM_NAME:
        if any(k in n for k in keys):
            return intent
    return None


def analyse(activity: dict[str, Any],
            laps: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Alle Prüfungen laufen lassen und zu einem Urteil verdichten."""
    intent = guess_intent(activity.get("name"))
    findings = [f for f in (
        check_pace(activity, intent),
        check_hr_zones(activity, intent),
        check_decoupling(activity, laps),
        check_cadence(activity),
        check_form(activity),
        check_progress(activity),
    ) if f]

    warns = sum(1 for f in findings if f["level"] == WARN)
    goods = sum(1 for f in findings if f["level"] == GOOD)
    if warns == 0 and goods >= 2:
        verdict, level = "Saubere Einheit — genau so weiter.", GOOD
    elif warns >= 2:
        verdict, level = ("Da gibt es zwei Stellschrauben — siehe unten.", WARN)
    elif warns == 1:
        verdict, level = ("Solide Einheit mit einem Punkt zum Nachjustieren.", OK)
    else:
        verdict, level = ("Einheit erfasst.", OK)

    pace = _pace_s_per_km(activity.get("distance_m"), activity.get("duration_s"))
    return {
        "intent": intent,
        "verdict": verdict,
        "level": level,
        "pace_s_per_km": pace,
        "pace_text": running.pace_s_to_str(pace) if pace else None,
        "findings": findings,
    }


def analyse_and_store(activity_id: int,
                      laps: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM activities WHERE id=?", (activity_id,)).fetchone()
    if not row:
        return None
    activity = dict(row)
    if activity.get("sport") not in ("running", "cardio"):
        return None
    result = analyse(activity, laps)
    with get_db() as db:
        db.execute("UPDATE activities SET analysis_json=? WHERE id=?",
                   (json.dumps(result, ensure_ascii=False), activity_id))
    return result


def get_analysis(activity_id: int) -> dict[str, Any] | None:
    with get_db() as db:
        row = db.execute("SELECT analysis_json FROM activities WHERE id=?",
                         (activity_id,)).fetchone()
    if not row or not row["analysis_json"]:
        return None
    return json.loads(row["analysis_json"])


def recent_summary(limit: int = 8) -> dict[str, Any]:
    """Verdichtung der letzten Läufe — auch als Kontext für den Coach."""
    with get_db() as db:
        rows = db.execute(
            "SELECT id, name, start_time, distance_m, duration_s, avg_hr, "
            "avg_cadence, hr_zones_json, analysis_json FROM activities "
            "WHERE sport='running' ORDER BY start_time DESC LIMIT ?",
            (limit,)).fetchall()

    runs, easy_s, hard_s = [], 0.0, 0.0
    for r in rows:
        a = json.loads(r["analysis_json"]) if r["analysis_json"] else {}
        runs.append({
            "datum": (r["start_time"] or "")[:10],
            "name": r["name"],
            "km": round((r["distance_m"] or 0) / 1000, 2),
            "tempo": a.get("pace_text"),
            "puls": round(r["avg_hr"]) if r["avg_hr"] else None,
            "schrittfrequenz": round(r["avg_cadence"]) if r["avg_cadence"] else None,
            "urteil": a.get("verdict"),
        })
        if r["hr_zones_json"]:
            try:
                z = {int(k): float(v) for k, v in json.loads(r["hr_zones_json"]).items()}
                easy_s += z.get(1, 0) + z.get(2, 0)
                hard_s += z.get(3, 0) + z.get(4, 0) + z.get(5, 0)
            except (ValueError, TypeError):
                pass

    total = easy_s + hard_s
    return {
        "letzte_laeufe": runs,
        "anteil_locker_prozent": round(easy_s / total * 100) if total else None,
        "gesamt_km": round(sum(r["km"] for r in runs), 1),
    }


# ------------------------------------------------------------- Formtrend

# Unter dieser Distanz sagt ein Lauf ueber die Form wenig — Ein- und
# Auslaufen wiegen dann zu schwer.
MIN_TREND_DISTANCE_M = 2000
MIN_RUNS_FOR_TREND = 4


def efficiency(distance_m: float | None, duration_s: float | None,
               avg_hr: float | None) -> float | None:
    """Effizienzfaktor: zurueckgelegte Meter je Minute, geteilt durch den Puls.

    Der ehrlichste Fortschrittsanzeiger im Ausdauersport. Schneller zu werden
    ist leicht — schneller zu werden, ohne dass der Puls mitsteigt, ist der
    eigentliche Formgewinn. Steigt der Wert ueber Wochen, wird die Grundlage
    besser, ganz gleich wie sich das Tempo einzelner Laeufe anfuehlt.
    """
    if not distance_m or not duration_s or not avg_hr or avg_hr < 60:
        return None
    speed_m_per_min = distance_m / (duration_s / 60.0)
    return round(speed_m_per_min / avg_hr, 3)


def _iso_week(day: str) -> str:
    try:
        d = dt.date.fromisoformat(day)
    except ValueError:
        return day
    year, week, _ = d.isocalendar()
    return f"{year}-KW{week:02d}"


def form_trend(days: int = 365) -> dict[str, Any]:
    """Entwicklung ueber alle Laeufe: Effizienz, Umfang, Intensitaet, Bestwerte."""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            """SELECT id, name, start_time, distance_m, duration_s, avg_hr,
                      avg_cadence, elevation_gain, hr_zones_json, analysis_json
               FROM activities
               WHERE sport='running' AND substr(start_time,1,10) >= ?
                 AND distance_m IS NOT NULL AND duration_s > 0
               ORDER BY start_time""", (since,)).fetchall())

    runs: list[dict[str, Any]] = []
    for r in rows:
        day = (r["start_time"] or "")[:10]
        ef = efficiency(r["distance_m"], r["duration_s"], r["avg_hr"])
        pace = _pace_s_per_km(r["distance_m"], r["duration_s"])
        analysis = {}
        if r["analysis_json"]:
            try:
                analysis = json.loads(r["analysis_json"])
            except (ValueError, TypeError):
                analysis = {}
        runs.append({
            "id": r["id"], "day": day, "name": r["name"],
            "km": round((r["distance_m"] or 0) / 1000, 2),
            "duration_s": r["duration_s"], "pace_s": pace,
            "avg_hr": round(r["avg_hr"]) if r["avg_hr"] else None,
            "efficiency": ef,
            "cadence": round(r["avg_cadence"]) if r["avg_cadence"] else None,
            "intent": analysis.get("intent") or guess_intent(r["name"]),
            "zones": r["hr_zones_json"],
        })

    # --- Effizienz: einzelne Laeufe und ein ruhiger Verlauf darueber ------
    usable = [r for r in runs
              if r["efficiency"] and (r["km"] * 1000) >= MIN_TREND_DISTANCE_M]
    eff_points = []
    for i, r in enumerate(usable):
        window = [x["efficiency"] for x in usable[max(0, i - 4):i + 1]]
        eff_points.append({
            "day": r["day"], "value": r["efficiency"],
            "smooth": round(sum(window) / len(window), 3),
            "km": r["km"], "hr": r["avg_hr"], "pace_s": r["pace_s"],
        })

    change = None
    if len(usable) >= MIN_RUNS_FOR_TREND * 2:
        half = len(usable) // 2
        early = [r["efficiency"] for r in usable[:half]]
        late = [r["efficiency"] for r in usable[half:]]
        a, b = sum(early) / len(early), sum(late) / len(late)
        change = {
            "from": round(a, 3), "to": round(b, 3),
            "percent": round((b - a) / a * 100, 1),
            "runs": len(usable),
        }

    # --- Wochenumfang -----------------------------------------------------
    per_week: dict[str, dict[str, float]] = {}
    for r in runs:
        w = per_week.setdefault(_iso_week(r["day"]), {"km": 0.0, "runs": 0,
                                                      "seconds": 0.0})
        w["km"] += r["km"]
        w["runs"] += 1
        w["seconds"] += r["duration_s"] or 0
    weeks = [{"week": k, "km": round(v["km"], 1), "runs": int(v["runs"]),
              "seconds": int(v["seconds"])} for k, v in sorted(per_week.items())]

    # --- Intensitaetsverteilung ------------------------------------------
    easy_s = hard_s = 0.0
    for r in runs:
        if not r["zones"]:
            continue
        try:
            z = {int(k): float(v) for k, v in json.loads(r["zones"]).items()}
        except (ValueError, TypeError):
            continue
        easy_s += z.get(1, 0) + z.get(2, 0)
        hard_s += z.get(3, 0) + z.get(4, 0) + z.get(5, 0)
    total_z = easy_s + hard_s
    easy_share = round(easy_s / total_z * 100) if total_z else None

    # --- Bestwerte je Distanz --------------------------------------------
    bests = []
    for label, metres in (("1 km", 1000), ("5 km", 5000), ("10 km", 10000),
                          ("Halbmarathon", 21097)):
        candidates = [r for r in runs if (r["km"] * 1000) >= metres * 0.97
                      and r["pace_s"]]
        if not candidates:
            continue
        best = min(candidates, key=lambda r: r["pace_s"])
        bests.append({
            "label": label, "pace_s": best["pace_s"], "day": best["day"],
            "id": best["id"], "km": best["km"],
            # Auf die Distanz hochgerechnet, nicht als gelaufene Zeit
            "time_s": round(best["pace_s"] * metres / 1000),
        })

    hints = []
    if change and change["percent"] >= 1.5:
        hints.append({
            "level": "good",
            "text": (f"Deine Laufeffizienz ist über {change['runs']} Läufe um "
                     f"{change['percent']} % gestiegen. Das heißt: gleiches Tempo "
                     f"bei niedrigerem Puls — der Fortschritt, auf den es ankommt.")})
    elif change and change["percent"] <= -1.5:
        hints.append({
            "level": "warn",
            "text": (f"Deine Laufeffizienz ist um {abs(change['percent'])} % "
                     f"gesunken. Das passiert bei zu viel Intensität, zu wenig "
                     f"Schlaf oder beidem — oft auch nur vorübergehend bei Hitze.")})
    if easy_share is not None and easy_share < 70:
        hints.append({
            "level": "warn",
            "text": (f"Nur {easy_share} % deiner Laufzeit lagen in Zone 1–2. "
                     f"Der häufigste Fehler im Breitensport ist, die lockeren "
                     f"Läufe zu schnell zu laufen. 75–80 % wären das Ziel.")})
    elif easy_share is not None and easy_share >= 80:
        hints.append({
            "level": "good",
            "text": (f"{easy_share} % deiner Laufzeit in Zone 1–2 — die "
                     f"Verteilung stimmt. Genau so wird die Grundlage breiter.")})

    return {
        "runs": len(runs),
        "efficiency": eff_points,
        "change": change,
        "weeks": weeks[-26:],
        "easy_share": easy_share,
        "bests": bests,
        "hints": hints,
        "recent": list(reversed(runs[-10:])),
        "hint": None if runs else
        ("Noch keine Läufe im Zeitraum. Nach dem Garmin-Sync erscheint hier "
         "die Entwicklung."),
    }

