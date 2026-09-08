"""Wie gut laeuft es gerade — und wo liegt das meiste Potenzial.

Ein einzelner Punktwert waere leicht misszuverstehen, deshalb setzt er sich
aus fuenf Saeulen zusammen, die einzeln sichtbar bleiben. Wer 82 sieht, soll
danebenlesen koennen, woraus die 82 entstanden sind.

Gerechnet wird im Code. Das Modell darf den Wert hinterher kommentieren, aber
nicht bestimmen — sonst waere er von Tag zu Tag beliebig.

Die Saeulen:
  Beständigkeit  hältst du deine Wochenstruktur ein
  Fortschritt    werden Gewichte und Tempi tatsächlich besser
  Erholung       Schlaf, HRV und Ruhepuls gegenüber deiner Basislinie
  Belastung      ist die Steigerung gesund (ACWR) oder zu schnell
  Alltag         Supplements, Wiegen, Eintragen — die kleinen Dinge
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from ..db import get_db, get_setting

log = logging.getLogger("puls.score")

PILLARS = {
    "consistency": "Beständigkeit",
    "progress": "Fortschritt",
    "recovery": "Erholung",
    "load": "Belastung",
    "habits": "Alltag",
}
WEIGHTS = {"consistency": 0.30, "progress": 0.25, "recovery": 0.20,
           "load": 0.15, "habits": 0.10}

# Ab wann sich eine Aussage lohnt. Darunter wird die Saeule nicht bewertet,
# sondern als "noch keine Grundlage" ausgewiesen — ein geratener Wert waere
# schlimmer als eine Luecke.
MIN_DAYS = 10


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _week_targets() -> tuple[int, int]:
    try:
        runs = len(json.loads(get_setting("run_days", "[]") or "[]"))
        gyms = len(json.loads(get_setting("gym_days", "[]") or "[]"))
    except ValueError:
        runs, gyms = 0, 0
    return runs, gyms


def _consistency(days: int = 28) -> dict[str, Any]:
    """Wird die eigene Wochenstruktur eingehalten?"""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        rows = db.execute(
            "SELECT sport, COUNT(*) AS n FROM activities "
            "WHERE substr(start_time,1,10) >= ? GROUP BY sport", (since,)).fetchall()
    got = {r["sport"]: r["n"] for r in rows}
    weeks = days / 7
    run_target, gym_target = _week_targets()
    expected_runs = run_target * weeks
    expected_gyms = gym_target * weeks

    parts, detail = [], []
    for label, actual, expected in (
            ("Läufe", got.get("running", 0), expected_runs),
            ("Gym-Einheiten", got.get("strength", 0), expected_gyms)):
        if expected <= 0:
            continue
        share = min(1.3, actual / expected)      # Übererfüllung zählt begrenzt
        parts.append(min(1.0, share) * 100)
        detail.append(f"{actual} von {expected:.0f} {label}")

    if not parts:
        return {"value": None, "why": "Keine Wochenstruktur hinterlegt."}
    return {"value": round(sum(parts) / len(parts)), "why": ", ".join(detail),
            "counts": got}


def _progress(days: int = 56) -> dict[str, Any]:
    """Werden Gewichte schwerer und Läufe schneller?"""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    mid = (dt.date.today() - dt.timedelta(days=days // 2)).isoformat()
    notes, scores = [], []

    with get_db() as db:
        moves = db.execute(
            "SELECT action, COUNT(*) AS n FROM progression_log "
            "WHERE ts >= ? GROUP BY action", (since,)).fetchall()
        early = db.execute(
            """SELECT AVG(duration_s * 1000.0 / distance_m) AS pace, AVG(avg_hr) AS hr,
                      COUNT(*) AS n FROM activities
               WHERE sport='running' AND distance_m > 1500
                 AND substr(start_time,1,10) BETWEEN ? AND ?""",
            (since, mid)).fetchone()
        late = db.execute(
            """SELECT AVG(duration_s * 1000.0 / distance_m) AS pace, AVG(avg_hr) AS hr,
                      COUNT(*) AS n FROM activities
               WHERE sport='running' AND distance_m > 1500
                 AND substr(start_time,1,10) > ?""", (mid,)).fetchone()

    by_action = {r["action"]: r["n"] for r in moves}
    ups = by_action.get("weight_up", 0) + by_action.get("reps_up", 0)
    downs = by_action.get("deload", 0)
    if ups or downs:
        # Ein Deload ist kein Versagen, aber viele hintereinander sind ein Zeichen
        ratio = ups / max(1, ups + downs * 2)
        scores.append(_clamp(40 + ratio * 60))
        notes.append(f"{ups} Steigerungen, {downs} Deloads")

    if (early and late and early["n"] and late["n"]
            and early["pace"] and late["pace"]):
        # Schneller bei gleichem oder niedrigerem Puls ist der ehrliche Vergleich
        gain = (early["pace"] - late["pace"]) / early["pace"] * 100
        hr_shift = ((late["hr"] or 0) - (early["hr"] or 0)) if early["hr"] else 0
        adjusted = gain - max(0.0, hr_shift) * 0.4
        scores.append(_clamp(50 + adjusted * 8))
        notes.append(f"Tempo {'+' if gain > 0 else ''}{gain:.1f} % "
                     f"gegenüber den Wochen davor")

    if not scores:
        return {"value": None, "why": "Noch zu wenige Einheiten für einen Vergleich."}
    return {"value": round(sum(scores) / len(scores)), "why": ", ".join(notes)}


def _recovery() -> dict[str, Any]:
    """Schlaf, HRV und Ruhepuls im Verhältnis zur eigenen Basislinie."""
    from . import metrics
    rec = metrics.recovery_series(30)
    base = rec["baselines"]
    scores, notes = [], []

    hrv = base.get("hrv_avg") or {}
    if hrv.get("last7") and hrv.get("baseline"):
        delta = (hrv["last7"] - hrv["baseline"]) / hrv["baseline"] * 100
        scores.append(_clamp(70 + delta * 2.5))
        notes.append(f"HRV {hrv['last7']:.0f} ms (Schnitt {hrv['baseline']:.0f})")

    rhr = base.get("resting_hr") or {}
    if rhr.get("last7") and rhr.get("baseline"):
        delta = rhr["baseline"] - rhr["last7"]      # niedriger ist besser
        scores.append(_clamp(70 + delta * 6))
        notes.append(f"Ruhepuls {rhr['last7']:.0f}")

    sleep = base.get("sleep_seconds") or {}
    if sleep.get("last7"):
        hours = sleep["last7"] / 3600
        # Unter 6 h wird es deutlich, ab 7,5 h gibt es nichts mehr obendrauf
        scores.append(_clamp((hours - 5.0) / 2.5 * 100))
        notes.append(f"{hours:.1f} h Schlaf")

    if not scores:
        return {"value": None,
                "why": "Noch keine Erholungsdaten — Verlauf nachladen hilft."}
    return {"value": round(sum(scores) / len(scores)), "why": ", ".join(notes)}


def _load() -> dict[str, Any]:
    """Steigt die Belastung gesund oder zu schnell?"""
    from . import metrics
    acwr = metrics.acwr()
    if acwr is None:
        return {"value": None, "why": "Noch zu wenig Trainingshistorie."}
    # 0,8 bis 1,3 gilt als der Bereich, in dem Aufbau ohne erhöhtes
    # Verletzungsrisiko stattfindet.
    if 0.8 <= acwr <= 1.3:
        value = 100.0
        why = f"Belastungsverhältnis {acwr:.2f} — im guten Bereich"
    elif acwr < 0.8:
        value = _clamp(60 + (acwr / 0.8) * 40)
        why = f"Belastungsverhältnis {acwr:.2f} — zuletzt eher wenig"
    else:
        value = _clamp(100 - (acwr - 1.3) * 90)
        why = f"Belastungsverhältnis {acwr:.2f} — Steigerung geht schnell"
    return {"value": round(value), "why": why, "acwr": acwr}


def _habits(days: int = 21) -> dict[str, Any]:
    """Die kleinen Dinge: Einnahme, Wiegen, Eintragen."""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    scores, notes = [], []

    from . import supplements
    streak = supplements.streak(days)
    if streak["items"]:
        share = sum(i["share"] for i in streak["items"]) / len(streak["items"])
        scores.append(share * 100)
        notes.append(f"Supplements an {share * 100:.0f} % der Tage")

    with get_db() as db:
        weigh = db.execute(
            "SELECT COUNT(DISTINCT day) AS n FROM body_metrics "
            "WHERE day >= ? AND in_window = 1", (since,)).fetchone()["n"]
        moods = db.execute(
            "SELECT COUNT(DISTINCT day) AS n FROM mood_entries WHERE day >= ?",
            (since,)).fetchone()["n"]
    # Dreimal die Woche wiegen reicht voellig für einen belastbaren Trend
    scores.append(_clamp(weigh / (days * 3 / 7) * 100))
    notes.append(f"{weigh}× im Referenzfenster gewogen")
    scores.append(_clamp(moods / (days / 2) * 100))
    notes.append(f"{moods} Befinden-Einträge")

    return {"value": round(sum(scores) / len(scores)), "why": ", ".join(notes)}


def _potential(pillars: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Wo der naechste Schritt am meisten bringt.

    Sortiert nach dem, was rechnerisch am meisten Punkte liegen laesst — die
    schwaechste Saeule mit dem groessten Gewicht zuerst. Jeder Eintrag sagt,
    was konkret zu tun ist, nicht nur was fehlt.
    """
    advice = {
        "consistency": ("Einheiten durchziehen",
                        "Die Struktur steht, sie wird nur nicht ganz gelebt. "
                        "Eine ausgefallene Einheit pro Woche kostet mehr als "
                        "jede Feinjustierung am Plan."),
        "progress": ("Progression ernst nehmen",
                     "Trag nach dem Satz ein, wie er sich angefühlt hat — "
                     "PULS steigert nur, wenn es die Rückmeldung hat. Und lauf "
                     "die lockeren Läufe wirklich locker, damit die harten hart sein können."),
        "recovery": ("Schlaf und Erholung",
                     "Der billigste Fortschritt, den es gibt. Eine halbe Stunde "
                     "früher ins Bett bringt mehr als eine zusätzliche Einheit."),
        "load": ("Steigerung dosieren",
                 "Die Belastung wächst schneller als der Körper mitkommt. "
                 "Eine ruhige Woche jetzt ist billiger als eine Verletzungspause später."),
        "habits": ("Kleinkram mitnehmen",
                   "Wiegen im Referenzfenster, Supplements abhaken, Befinden "
                   "eintragen — das kostet zwei Minuten am Tag und ist die "
                   "Grundlage für alles, was der Coach sonst sagen kann."),
    }
    out = []
    for key, data in pillars.items():
        value = data.get("value")
        if value is None:
            out.append({
                "pillar": key, "label": PILLARS[key], "missing": True,
                "gain": 0.0, "title": f"{PILLARS[key]}: Datenlage",
                "text": data.get("why", ""),
            })
            continue
        gain = (100 - value) * WEIGHTS[key]
        title, text = advice[key]
        out.append({"pillar": key, "label": PILLARS[key], "value": value,
                    "gain": round(gain, 1), "title": title, "text": text,
                    "why": data.get("why", "")})
    return sorted(out, key=lambda o: (-o["gain"], o["label"]))


def overall() -> dict[str, Any]:
    """Der Gesamtwert samt Saeulen und Potenzial."""
    pillars = {
        "consistency": _consistency(),
        "progress": _progress(),
        "recovery": _recovery(),
        "load": _load(),
        "habits": _habits(),
    }

    # Nur bewertbare Säulen zählen; ihre Gewichte werden neu normiert, damit
    # eine fehlende Datenquelle den Wert nicht künstlich drückt.
    usable = {k: v for k, v in pillars.items() if v.get("value") is not None}
    if usable:
        total_weight = sum(WEIGHTS[k] for k in usable)
        value = sum(v["value"] * WEIGHTS[k] for k, v in usable.items()) / total_weight
        score = round(value)
    else:
        score = None

    if score is None:
        mood_word, verdict = "abwartend", (
            "Noch keine Grundlage für ein Urteil. Verbinde Garmin und lade den "
            "Verlauf nach — danach kann ich etwas dazu sagen.")
    elif score >= 85:
        mood_word, verdict = "sehr zufrieden", (
            "Das läuft. Struktur, Fortschritt und Erholung passen zusammen — "
            "genau der Zustand, in dem man nichts ändern sollte.")
    elif score >= 70:
        mood_word, verdict = "zufrieden", (
            "Solide. Die Grundlage steht, an einer Stelle ist noch spürbar "
            "Luft — siehe unten.")
    elif score >= 55:
        mood_word, verdict = "wohlwollend", (
            "Es geht voran, aber unrund. Eine Sache konsequent anzugehen "
            "bringt gerade mehr als an dreien gleichzeitig zu drehen.")
    elif score >= 40:
        mood_word, verdict = "kritisch", (
            "Da liegt einiges brach. Nicht schlimm — aber die Zahlen sagen "
            "gerade deutlich, wo es hakt.")
    else:
        mood_word, verdict = "besorgt", (
            "Zwischen Plan und Wirklichkeit klafft eine Lücke. Fang mit einer "
            "einzigen Sache an, nicht mit allen.")

    return {
        "score": score,
        "mood": mood_word,
        "verdict": verdict,
        "pillars": [{"key": k, "label": PILLARS[k], "weight": WEIGHTS[k], **v}
                    for k, v in pillars.items()],
        "potential": _potential(pillars),
        "updated": dt.datetime.now().isoformat(timespec="seconds"),
    }
