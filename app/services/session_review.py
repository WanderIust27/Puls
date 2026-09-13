"""Was eine Einheit gebracht hat — nicht nur, dass sie stattgefunden hat.

Im Rückblick standen bisher drei Zahlen: Datum, Übungen, Sätze. Das ist ein
Beleg, kein Befund. Die Frage, die man sich beim Draufschauen stellt, ist eine
andere — **hat das etwas gebracht?** — und die beantwortet sich nur im
Vergleich:

* Gegen dieselbe Übung beim letzten Mal. Zwei Kilo mehr bei gleichen
  Wiederholungen sind ein Fortschritt; zwei Wiederholungen mehr beim gleichen
  Gewicht auch. Beides steht in den Sätzen, beides wurde nie gezeigt.
* Gegen die Woche. Zwölf bis zwanzig harte Sätze je Muskelgruppe sind der
  Korridor aus 01_Grundlagen_Muskelaufbau.md — eine Einheit ist gut, wenn sie
  eine Gruppe dorthin bringt, und nicht, wenn sie lang war.
* Gegen die letzte vergleichbare Einheit. Was an einem Push-Tag zählt, ist der
  vorige Push-Tag und nicht der Beintag dazwischen.

Gerechnet wird die Volumenlast als Sätze × Wiederholungen × Gewicht. Sie ist
grob — eine Wiederholung mit 60 kg ist nicht dasselbe wie drei mit 20 —, aber
sie ist die einzige Größe, die sich über verschiedene Übungen hinweg
aufaddieren lässt, und im Vergleich derselben Einheit mit sich selbst ist sie
ehrlich.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..constants import (INDIRECT_GROUPS, INDIRECT_SET_WEIGHT,
                         VOLUME_MAX_SETS, VOLUME_MIN_SETS)
from ..db import get_db, rows_to_dicts
from . import exercises as ex_lib
from . import split as split_svc

log = logging.getLogger("puls.session_review")

HISTORY_DAYS = 120        # so weit zurueck wird fuer Vergleiche gelesen
MIN_GAIN_KG = 0.1         # darunter ist es keine Steigerung, sondern Rundung


def _de(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}f}".replace(".", ",").rstrip("0").rstrip(",") \
        if digits else f"{value:.0f}"


def _read(today: dt.date) -> list[dict[str, Any]]:
    floor = (today - dt.timedelta(days=HISTORY_DAYS)).isoformat()
    with get_db() as db:
        return rows_to_dicts(db.execute(
            """SELECT s.day, s.reps, s.weight_kg, s.duration_s, s.set_index,
                      e.id AS exercise_id, e.name, e.muscle_group, e.slot,
                      e.equipment, e.assisted
               FROM exercise_sets s JOIN exercises e ON e.id = s.exercise_id
               WHERE s.day >= ? AND s.day <= ?
               ORDER BY s.day, e.id, s.set_index""",
            (floor, today.isoformat())).fetchall())


def _top_set(sets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Der schwerste Satz — und bei gleichem Gewicht der mit den meisten Wdh.

    Bei unterstuetzten Uebungen ist es umgekehrt: Weniger Unterstuetzung ist
    schwerer. Das steht schon in der Progression so und muss hier genauso
    gelten, sonst meldet PULS einen Fortschritt, wo einer weniger geschafft hat.
    """
    scored = [s for s in sets if s.get("reps")]
    if not scored:
        return None
    assisted = bool(sets[0].get("assisted"))
    sign = -1 if assisted else 1
    return max(scored, key=lambda s: (sign * (s.get("weight_kg") or 0),
                                      s.get("reps") or 0))


def _compare(now: dict[str, Any], before: dict[str, Any] | None,
             assisted: bool) -> dict[str, Any] | None:
    """Zwei Spitzensaetze vergleichen — Gewicht zuerst, dann Wiederholungen."""
    if not before:
        return None
    w_now, w_was = now.get("weight_kg") or 0, before.get("weight_kg") or 0
    r_now, r_was = now.get("reps") or 0, before.get("reps") or 0
    d_w, d_r = round(w_now - w_was, 2), r_now - r_was
    if abs(d_w) >= MIN_GAIN_KG:
        # Bei unterstuetzten Uebungen ist weniger Gewicht am Band das
        # Schwerere — und damit der Fortschritt.
        better = (d_w < 0) if assisted else (d_w > 0)
        word = (("weniger" if d_w < 0 else "mehr") + " Unterstützung" if assisted
                else "mehr" if d_w > 0 else "weniger")
        return {"kind": "weight", "better": better, "delta_kg": d_w,
                "delta_reps": d_r,
                "text": f"{_de(abs(d_w), 1)} kg {word} als beim letzten Mal"}
    if d_r:
        return {"kind": "reps", "better": d_r > 0, "delta_kg": 0.0,
                "delta_reps": d_r,
                "text": (f"{abs(d_r)} Wiederholung{'en' if abs(d_r) != 1 else ''} "
                         f"{'mehr' if d_r > 0 else 'weniger'} bei gleichem Gewicht")}
    return {"kind": "same", "better": None, "delta_kg": 0.0, "delta_reps": 0,
            "text": "gleich wie beim letzten Mal"}


def _volume_by_group(sets: list[dict[str, Any]]) -> dict[str, float]:
    """Fraktionales Satzvolumen dieser Einheit — wie in facts.weekly_volume."""
    out: dict[str, float] = {}
    for s in sets:
        if not s.get("reps"):
            continue
        group = s.get("muscle_group")
        if not group:
            continue
        out[group] = out.get(group, 0.0) + 1
        for other in INDIRECT_GROUPS.get(group, ()):
            out[other] = out.get(other, 0.0) + INDIRECT_SET_WEIGHT
    return {g: round(v, 1) for g, v in out.items()}


def _week_start(day: str) -> str:
    d = dt.date.fromisoformat(day)
    return (d - dt.timedelta(days=d.weekday())).isoformat()


def reviews(limit: int = 8, today: dt.date | None = None) -> list[dict[str, Any]]:
    """Die letzten Einheiten, jede mit dem, was sie gebracht hat."""
    today = today or dt.date.today()
    rows = _read(today)
    if not rows:
        return []

    by_day: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_day.setdefault(r["day"], []).append(r)
    days = sorted(by_day, reverse=True)

    # Je Uebung die Reihenfolge der Tage, damit "das letzte Mal" nicht der
    # vorletzte Kalendertag ist, sondern das letzte Mal DIESE Uebung.
    per_exercise: dict[int, dict[str, list[dict[str, Any]]]] = {}
    for r in rows:
        per_exercise.setdefault(r["exercise_id"], {}).setdefault(r["day"], []).append(r)

    split = split_svc.chosen_split()
    out: list[dict[str, Any]] = []

    for day in days[:limit]:
        sets = by_day[day]
        exercises: list[dict[str, Any]] = []
        gained = held = lost = 0

        grouped: dict[int, list[dict[str, Any]]] = {}
        for s in sets:
            grouped.setdefault(s["exercise_id"], []).append(s)

        for ex_id, ex_sets in grouped.items():
            history = per_exercise.get(ex_id, {})
            earlier = [d for d in sorted(history, reverse=True) if d < day]
            top = _top_set(ex_sets)
            prev_top = _top_set(history[earlier[0]]) if earlier else None
            assisted = bool(ex_sets[0].get("assisted"))
            cmp = _compare(top, prev_top, assisted) if top else None
            if cmp:
                if cmp["better"] is True:
                    gained += 1
                elif cmp["better"] is False:
                    lost += 1
                else:
                    held += 1
            exercises.append({
                "exercise_id": ex_id, "name": ex_sets[0]["name"],
                "group": ex_sets[0]["muscle_group"],
                "sets": len(ex_sets),
                "summary": _summary(ex_sets),
                "top": top,
                "compare": cmp,
                "last_day": earlier[0] if earlier else None,
            })
        exercises.sort(key=lambda e: e["name"])

        volume_kg = sum((s.get("reps") or 0) * (s.get("weight_kg") or 0)
                        for s in sets)
        groups = _volume_by_group(sets)
        kind = split_svc._classify(
            [{"name": e["name"], "muscle_group": e["group"], "slot": None,
              "sets": e["sets"]} for e in exercises], split)
        label = next((d["label"] for d in split["days"] if d["key"] == kind), None)

        # Die letzte vergleichbare Einheit: dieselbe Art, nicht der Vortag.
        prev_day = None
        for other in days:
            if other >= day:
                continue
            other_ex = {}
            for s in by_day[other]:
                other_ex.setdefault(s["exercise_id"], []).append(s)
            other_kind = split_svc._classify(
                [{"name": v[0]["name"], "muscle_group": v[0]["muscle_group"],
                  "slot": None, "sets": len(v)} for v in other_ex.values()], split)
            if other_kind == kind:
                prev_day = other
                break
        # Verglichen wird nur ueber die Uebungen, die in beiden Einheiten
        # vorkamen. Sonst meldet eine zusaetzliche Uebung "+122 % Volumenlast"
        # — was stimmt und trotzdem das Falsche sagt: Es war nicht mehr
        # Leistung, es war eine Uebung mehr.
        prev_volume = shared_now = None
        added = 0
        if prev_day:
            prev_ids = {s["exercise_id"] for s in by_day[prev_day]}
            both = prev_ids & set(grouped)
            added = len(set(grouped) - prev_ids)
            if both:
                shared_now = sum((s.get("reps") or 0) * (s.get("weight_kg") or 0)
                                 for s in sets if s["exercise_id"] in both)
                prev_volume = sum((s.get("reps") or 0) * (s.get("weight_kg") or 0)
                                  for s in by_day[prev_day]
                                  if s["exercise_id"] in both)

        change_pct = (round((shared_now - prev_volume) / prev_volume * 100)
                      if prev_volume else None)

        out.append({
            "day": day,
            "sets": len(sets),
            "exercises": exercises,
            "volume": round(volume_kg),
            "volume_before": round(prev_volume) if prev_volume else None,
            "volume_shared": round(shared_now) if shared_now else None,
            "volume_change_pct": change_pct,
            "new_exercises": added,
            "compared_with": prev_day,
            "kind": kind, "kind_label": label,
            "groups": [{"key": g, "label": ex_lib.MUSCLE_LABELS.get(g, g),
                        "sets": v}
                       for g, v in sorted(groups.items(), key=lambda kv: -kv[1])],
            "gained": gained, "held": held, "lost": lost,
            "verdict": _verdict(gained, held, lost, change_pct, added, label),
        })
    return out


def _summary(sets: list[dict[str, Any]]) -> str:
    """„3 × 12 @ 45 kg" oder, wenn es abweicht, jeder Satz einzeln."""
    reps = [s.get("reps") for s in sets]
    weights = [s.get("weight_kg") for s in sets]
    if len(set(reps)) == 1 and len(set(weights)) == 1 and reps[0]:
        w = weights[0]
        return (f"{len(sets)} × {reps[0]}"
                + (f" @ {_de(w, 1)} kg" if w else " (Eigengewicht)"))
    parts = []
    for s in sets:
        if s.get("reps") and s.get("weight_kg"):
            parts.append(f"{s['reps']}×{_de(s['weight_kg'], 1)}")
        elif s.get("reps"):
            parts.append(str(s["reps"]))
        elif s.get("duration_s"):
            parts.append(f"{s['duration_s']} s")
    return " · ".join(parts)


def _verdict(gained: int, held: int, lost: int, change_pct: int | None,
             added: int, label: str | None) -> str:
    """Ein Satz zu der Einheit — aus den Zahlen, nicht aus Zuspruch."""
    head = f"{label}-Einheit. " if label else ""
    if gained and not lost:
        core = (f"Bei {gained} von {gained + held + lost} Übungen mehr geschafft "
                f"als beim letzten Mal.")
    elif gained and lost:
        core = (f"{gained} Übungen besser, {lost} schlechter als beim letzten "
                "Mal — an einem einzelnen Tag ist das normal.")
    elif lost and not gained:
        core = (f"Bei {lost} Übungen weniger geschafft als beim letzten Mal. "
                "Ein Tag sagt wenig; zwei in Folge heißen, dass die Erholung "
                "nicht reicht.")
    elif held:
        core = (f"Überall dasselbe wie beim letzten Mal gehalten. Das ist die "
                "Ausgangslage für den nächsten Schritt, kein Rückschritt.")
    else:
        core = "Die erste Einheit mit diesen Übungen — ab jetzt gibt es einen "\
               "Vergleich."
    tail = ""
    if change_pct is not None and abs(change_pct) >= 8:
        tail = (f" Auf den gemeinsamen Übungen lag die Volumenlast "
                f"{abs(change_pct)} % "
                f"{'über' if change_pct > 0 else 'unter'} der letzten "
                f"vergleichbaren Einheit.")
    if added:
        tail += (f" {added} Übung{'en' if added != 1 else ''} kam"
                 f"{'en' if added != 1 else ''} neu dazu.")
    return head + core + tail


# ------------------------------------------------------- Die Woche darüber

def week(today: dt.date | None = None) -> dict[str, Any]:
    """Was die Einheiten dieser Woche zusammen ergeben.

    Die einzelne Einheit sagt wenig — der Korridor aus
    01_Grundlagen_Muskelaufbau.md gilt pro Woche und Muskelgruppe. Hier steht
    deshalb, welche Gruppe drin liegt und welche noch Sätze braucht.
    """
    today = today or dt.date.today()
    start = (today - dt.timedelta(days=today.weekday())).isoformat()
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            """SELECT s.day, s.reps, e.muscle_group
               FROM exercise_sets s JOIN exercises e ON e.id = s.exercise_id
               WHERE s.day >= ? AND s.day <= ? AND s.reps IS NOT NULL
                 AND s.reps > 0""", (start, today.isoformat())).fetchall())
    volume = _volume_by_group(rows)
    groups = []
    for key in ("legs", "chest", "back", "shoulders", "arms", "core"):
        sets = volume.get(key, 0.0)
        groups.append({
            "key": key, "label": ex_lib.MUSCLE_LABELS.get(key, key),
            "sets": sets,
            "band": ("low" if sets < VOLUME_MIN_SETS else
                     "high" if sets > VOLUME_MAX_SETS else "ok"),
            "missing": round(max(0.0, VOLUME_MIN_SETS - sets), 1),
        })
    def _units(n: int) -> str:
        return "1 Einheit" if n == 1 else f"{n} Einheiten"

    low = [g for g in groups if g["band"] == "low"]
    high = [g for g in groups if g["band"] == "high"]
    days = len({r["day"] for r in rows})
    if not rows:
        sentence = ("Diese Woche noch keine Sätze. Der Korridor sind "
                    f"{VOLUME_MIN_SETS}–{VOLUME_MAX_SETS} harte Sätze je "
                    "Muskelgruppe.")
    elif not low:
        sentence = (f"{_units(days)} diese Woche, alle Muskelgruppen im "
                    f"Korridor von {VOLUME_MIN_SETS}–{VOLUME_MAX_SETS} Sätzen."
                    + (f" Über dem Korridor: "
                       f"{', '.join(g['label'] for g in high)} — mehr bringt "
                       "ab hier nichts mehr." if high else ""))
    else:
        names = ", ".join(f"{g['label']} ({_de(g['sets'], 1)})" for g in low[:3])
        sentence = (f"{_units(days)} diese Woche. Unter dem Korridor von "
                    f"{VOLUME_MIN_SETS} Sätzen: {names}"
                    + (f" und {len(low) - 3} weitere" if len(low) > 3 else "")
                    + ".")
    return {"from": start, "days": days, "groups": groups,
            "min": VOLUME_MIN_SETS, "max": VOLUME_MAX_SETS,
            "sentence": sentence}
