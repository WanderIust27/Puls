"""Was entwickelt sich — und was nicht.

Der Coach soll nicht nur planen, sondern begruenden koennen, warum er gerade
diese Muskelgruppe und diese Laufart vorschlaegt. Dafuer braucht er drei
Antworten, und alle drei stehen in deinen eigenen Daten:

* Wo geht es voran, wo steht es? Volumen und geschaetztes Maximalgewicht der
  letzten vier Wochen gegen die vier davor.
* Was kommt zu kurz? Anteil am Gesamtvolumen, Tage seit der letzten Belastung.
* Was fehlt dem Ziel? Aus dem Freitext-Ziel wird abgeleitet, worauf es
  ankommt — und das gewichtet die Reihenfolge.

Gerechnet wird hier alles, formuliert nichts. Das Modell bekommt die fertige
Rangfolge und darf sie erklaeren; es entscheidet sie nicht. Sonst haette man
jede Woche eine andere Meinung ohne neue Daten.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts
from . import exercises as ex_lib

log = logging.getLogger("puls.trends")

WINDOW = 28               # Vergleichsfenster in Tagen: vier Wochen gegen vier
MIN_SETS = 6              # darunter ist ein Vergleich nur Rauschen

# Was ein ausgewogenes Krafttraining ungefaehr auf die Gruppen verteilt.
# Beine und Ruecken tragen mehr Muskelmasse, sie duerfen mehr Volumen haben.
BALANCED_SHARE = {
    "legs": 0.26, "back": 0.22, "chest": 0.18,
    "shoulders": 0.13, "arms": 0.11, "core": 0.10,
}

# Aus dem Freitext-Ziel abgeleitete Schwerpunkte. Bewusst knapp gehalten:
# lieber nichts erkennen als das Falsche hineinlesen.
GOAL_KEYWORDS: list[tuple[tuple[str, ...], dict[str, Any]]] = [
    (("10 km", "10km", "zehn kilometer", "10-km"),
     {"sport": "running", "run": "tempo", "note": "10-km-Zeit"}),
    (("halbmarathon", "21 km", "21km"),
     {"sport": "running", "run": "long", "note": "Halbmarathon"}),
    (("marathon",), {"sport": "running", "run": "long", "note": "Marathon"}),
    (("schneller", "tempo", "bestzeit", "pace"),
     {"sport": "running", "run": "tempo", "note": "Tempo"}),
    (("ausdauer", "grundlage", "durchhalten"),
     {"sport": "running", "run": "long", "note": "Ausdauer"}),
    (("klimmzug", "klimmzüge", "pull-up", "pullup"),
     {"sport": "strength", "muscles": ["back", "arms"], "note": "Klimmzüge"}),
    (("bankdrücken", "brust", "bank drücken"),
     {"sport": "strength", "muscles": ["chest", "arms"], "note": "Brust"}),
    (("kniebeuge", "beine", "squat", "bein"),
     {"sport": "strength", "muscles": ["legs"], "note": "Beine"}),
    (("kreuzheben", "rücken", "ruecken", "latzug"),
     {"sport": "strength", "muscles": ["back"], "note": "Rücken"}),
    (("schulter", "nacken"),
     {"sport": "strength", "muscles": ["shoulders"], "note": "Schultern"}),
    (("arme", "bizeps", "trizeps"),
     {"sport": "strength", "muscles": ["arms"], "note": "Arme"}),
    (("bauch", "rumpf", "core", "sixpack"),
     {"sport": "strength", "muscles": ["core"], "note": "Rumpf"}),
    (("muskel", "masse", "kraft", "stärker", "staerker", "aufbau"),
     {"sport": "strength", "muscles": [], "note": "Kraftaufbau"}),
    (("abnehmen", "gewicht verlieren", "definition", "fett"),
     {"sport": "both", "run": "easy", "note": "Abnehmen"}),
    (("haltung", "beweglich", "mobilität", "mobilitaet"),
     {"sport": "strength", "muscles": ["back", "core"], "note": "Haltung"}),
]


def _change(recent: float, before: float) -> float | None:
    """Veraenderung in Prozent — ohne Division durch null."""
    if not before:
        return None
    return round((recent - before) / before * 100, 1)


def goal_focus(text: str | None = None) -> dict[str, Any]:
    """Aus dem Freitext-Ziel ablesen, worauf es ankommt."""
    if text is None:
        text = get_setting("auto_wishes", "") or ""
        text = f"{text} {get_setting('goal_text', '') or ''}"
    low = text.lower()
    muscles: list[str] = []
    runs: list[str] = []
    notes: list[str] = []
    sports: set[str] = set()
    for words, hit in GOAL_KEYWORDS:
        if not any(w in low for w in words):
            continue
        notes.append(hit["note"])
        sports.add(hit["sport"])
        for m in hit.get("muscles", []):
            if m not in muscles:
                muscles.append(m)
        if hit.get("run") and hit["run"] not in runs:
            runs.append(hit["run"])
    sport = ("both" if len(sports) != 1 else sports.pop()) if sports else None
    return {"text": text.strip(), "muscles": muscles, "runs": runs,
            "sport": sport, "recognised": notes}


# ------------------------------------------------------------ Muskelgruppen

def muscles(as_of: dt.date | None = None) -> dict[str, Any]:
    """Entwicklung je Muskelgruppe — und was am ehesten dran waere."""
    today = as_of or dt.date.today()
    recent_from = (today - dt.timedelta(days=WINDOW)).isoformat()
    before_from = (today - dt.timedelta(days=WINDOW * 2)).isoformat()

    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            """SELECT s.day, s.reps, s.weight_kg, e.muscle_group, e.id AS ex_id,
                      e.name AS ex_name
               FROM exercise_sets s JOIN exercises e ON e.id = s.exercise_id
               WHERE s.day >= ? AND e.muscle_group IS NOT NULL""",
            (before_from,)).fetchall())

    groups: dict[str, dict[str, Any]] = {}
    for g in BALANCED_SHARE:
        groups[g] = {"volume_recent": 0.0, "volume_before": 0.0,
                     "sets_recent": 0, "sets_before": 0, "days": set(),
                     "last_day": None, "best_recent": {}, "best_before": {}}

    for r in rows:
        g = groups.get(r["muscle_group"])
        if g is None:
            continue
        reps = r["reps"] or 0
        weight = r["weight_kg"] or 0.0
        volume = reps * weight
        window = "recent" if r["day"] >= recent_from else "before"
        g[f"volume_{window}"] += volume
        g[f"sets_{window}"] += 1
        if window == "recent":
            g["days"].add(r["day"])
            if g["last_day"] is None or r["day"] > g["last_day"]:
                g["last_day"] = r["day"]
        # Bestes geschaetztes Maximalgewicht je Uebung, nicht je Satz —
        # sonst schlaegt ein einzelner schwerer Dreiersatz alles andere.
        if reps and weight:
            one_rm = ex_lib.epley_1rm(weight, reps)
            best = g[f"best_{window}"]
            best[r["ex_id"]] = max(best.get(r["ex_id"], 0.0), one_rm)

    total_recent = sum(g["volume_recent"] for g in groups.values()) or 1.0
    out: list[dict[str, Any]] = []
    for key, g in groups.items():
        share = g["volume_recent"] / total_recent
        target = BALANCED_SHARE[key]
        since = (dt.date.fromisoformat(g["last_day"]) if g["last_day"] else None)
        days_since = (today - since).days if since else None

        # Kraftentwicklung: nur Uebungen, die in beiden Fenstern vorkommen
        shared = set(g["best_recent"]) & set(g["best_before"])
        strength = None
        if shared:
            now = sum(g["best_recent"][i] for i in shared) / len(shared)
            then = sum(g["best_before"][i] for i in shared) / len(shared)
            strength = _change(now, then)

        volume_change = _change(g["volume_recent"], g["volume_before"]) \
            if g["sets_before"] >= MIN_SETS else None

        # Bedarf: je hoeher, desto eher gehoert die Gruppe in die naechste
        # Einheit. Vier Gruende, jeder mit eigener Obergrenze, damit keiner
        # allein die Rangfolge bestimmt.
        need = 0.0
        reasons: list[str] = []
        if days_since is None:
            need += 40
            reasons.append("in vier Wochen nicht trainiert")
        elif days_since >= 10:
            need += min(30.0, days_since * 2.0)
            reasons.append(f"seit {days_since} Tagen nicht dran")
        elif days_since >= 6:
            need += 12
            reasons.append(f"seit {days_since} Tagen nicht dran")

        gap = target - share
        if gap > 0.04:
            need += min(25.0, gap * 250)
            reasons.append(f"nur {share * 100:.0f} % des Volumens statt "
                           f"{target * 100:.0f} %")

        if strength is not None and strength < 1.0:
            need += 20 if strength < -2 else 12
            reasons.append("Maximalkraft steht" if strength >= -2
                           else f"Maximalkraft {strength:.0f} %")

        if volume_change is not None and volume_change < -15:
            need += 12
            reasons.append(f"Volumen {volume_change:.0f} %")

        out.append({
            "key": key, "label": ex_lib.MUSCLE_LABELS.get(key, key),
            "volume_recent": round(g["volume_recent"]),
            "volume_before": round(g["volume_before"]),
            "volume_change": volume_change,
            "strength_change": strength,
            "sets_recent": g["sets_recent"], "sessions": len(g["days"]),
            "share": round(share * 100, 1), "target_share": round(target * 100, 1),
            "last_day": g["last_day"], "days_since": days_since,
            "need": round(min(100.0, need)), "reasons": reasons,
            "direction": ("steigt" if (strength or 0) > 1 else
                          "fällt" if (strength or 0) < -2 else "hält"),
        })

    out.sort(key=lambda x: -x["need"])
    trained = [g for g in out if g["sets_recent"]]
    return {
        "groups": out,
        "focus": [g["key"] for g in out[:2] if g["need"] >= 20],
        "total_sets": sum(g["sets_recent"] for g in out),
        "hint": None if trained else (
            "Noch keine Sätze aufgezeichnet. Sobald die Uhr eine Krafteinheit "
            "übertragen hat, steht hier, welche Gruppe zu kurz kommt."),
    }


# ------------------------------------------------------------------ Laufen

def running_trend(as_of: dt.date | None = None) -> dict[str, Any]:
    """Entwicklung beim Laufen — Umfang, Tempo, laengste Einheit, Intensitaet."""
    today = as_of or dt.date.today()
    recent_from = (today - dt.timedelta(days=WINDOW)).isoformat()
    before_from = (today - dt.timedelta(days=WINDOW * 2)).isoformat()

    with get_db() as db:
        runs = rows_to_dicts(db.execute(
            """SELECT substr(start_time,1,10) AS day, distance_m, duration_s,
                      avg_hr, training_load
               FROM activities
               WHERE sport='running' AND substr(start_time,1,10) >= ?
               ORDER BY start_time""", (before_from,)).fetchall())

    recent = [r for r in runs if r["day"] >= recent_from]
    before = [r for r in runs if r["day"] < recent_from]

    def km(rows: list[dict[str, Any]]) -> float:
        return sum((r["distance_m"] or 0) for r in rows) / 1000

    def longest(rows: list[dict[str, Any]]) -> float:
        return max((r["distance_m"] or 0) for r in rows) / 1000 if rows else 0.0

    def pace_at_hr(rows: list[dict[str, Any]]) -> float | None:
        """Sekunden je Kilometer bei lockerem Puls. Der ehrlichste Fortschritts-
        massstab: gleiche Anstrengung, mehr Tempo."""
        usable = [r for r in rows if r["avg_hr"] and r["distance_m"]
                  and r["duration_s"] and 120 <= r["avg_hr"] <= 155
                  and r["distance_m"] > 2000]
        if len(usable) < 2:
            return None
        return sum(r["duration_s"] / (r["distance_m"] / 1000)
                   for r in usable) / len(usable)

    km_recent, km_before = km(recent), km(before)
    pace_recent, pace_before = pace_at_hr(recent), pace_at_hr(before)
    long_recent, long_before = longest(recent), longest(before)

    # Harte Einheiten erkennen wir am Puls, nicht am Namen — der Name sagt
    # nur, was geplant war, der Puls, was gelaufen wurde.
    hard = [r for r in recent if (r["avg_hr"] or 0) >= 160]
    last_day = recent[-1]["day"] if recent else None
    days_since = (today - dt.date.fromisoformat(last_day)).days if last_day else None

    needs: list[str] = []
    if not recent:
        needs.append("In vier Wochen kein Lauf aufgezeichnet.")
    else:
        if long_recent < 8 and long_recent < long_before:
            needs.append(f"Die längste Einheit ist auf {long_recent:.1f} km "
                         f"geschrumpft (vorher {long_before:.1f} km).")
        elif long_recent < 8:
            needs.append(f"Die längste Einheit liegt bei {long_recent:.1f} km — "
                         "für die Grundlage darf sie wachsen.")
        if not hard:
            needs.append("In vier Wochen kein Lauf im harten Bereich. "
                         "Ohne Tempoanteil bleibt das Renntempo stehen.")
        elif len(hard) > len(recent) * 0.4:
            needs.append(f"{len(hard)} von {len(recent)} Läufen im harten "
                         "Bereich — das ist zu viel, der Großteil sollte locker sein.")
        if km_before and km_recent < km_before * 0.8:
            needs.append(f"Umfang von {km_before:.0f} auf {km_recent:.0f} km "
                         "gefallen.")

    return {
        "runs_recent": len(recent), "runs_before": len(before),
        "km_recent": round(km_recent, 1), "km_before": round(km_before, 1),
        "km_change": _change(km_recent, km_before),
        "km_per_week": round(km_recent / (WINDOW / 7), 1),
        "longest_recent": round(long_recent, 1),
        "longest_before": round(long_before, 1),
        "pace_recent": round(pace_recent) if pace_recent else None,
        "pace_before": round(pace_before) if pace_before else None,
        # Schneller bei gleichem Puls heisst: die Sekunden werden weniger
        "pace_gain_s": (round(pace_before - pace_recent)
                        if pace_recent and pace_before else None),
        "hard_runs": len(hard), "days_since": days_since,
        "needs": needs,
        "direction": ("steigt" if pace_recent and pace_before
                      and pace_before - pace_recent > 3 else
                      "fällt" if pace_recent and pace_before
                      and pace_recent - pace_before > 3 else "hält"),
        "hint": None if runs else (
            "Noch keine Läufe in den letzten acht Wochen."),
    }


def summary(as_of: dt.date | None = None) -> dict[str, Any]:
    """Alles zusammen — die Grundlage, auf der der Coach die Woche baut."""
    goal = goal_focus()
    m = muscles(as_of)
    r = running_trend(as_of)

    # Das Ziel schiebt die genannten Gruppen nach oben, ersetzt aber nicht den
    # gerechneten Bedarf: Wer aufs Bankdruecken zielt und vier Wochen keine
    # Beine gemacht hat, braucht trotzdem Beine.
    if goal["muscles"]:
        for g in m["groups"]:
            if g["key"] in goal["muscles"]:
                g["need"] = min(100, g["need"] + 15)
                g["reasons"] = g["reasons"] + ["steht in deinem Ziel"]
        m["groups"].sort(key=lambda x: -x["need"])
        m["focus"] = [g["key"] for g in m["groups"][:2] if g["need"] >= 20]

    return {"goal": goal, "muscles": m, "running": r,
            "generated": dt.date.today().isoformat()}
