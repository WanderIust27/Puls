"""Benchmark: kalibriert das System auf den aktuellen Leistungsstand.

Drei Tests:
  1. Kraft   — pro Übung ein Satz bis zum sauberen Maximum (AMRAP) beim aktuellen
               Gewicht. Daraus 1RM nach Epley und die Arbeitsgewichte.
  2. Klimmzug— maximale saubere Wiederholungen; bestimmt, ob PULS mit negativen,
               Band-unterstützten oder freien Klimmzügen weiterarbeitet.
  3. Lauf    — Cooper-Test (12 min), siehe running.py.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts, set_setting
from . import exercises as ex_lib
from . import running

log = logging.getLogger("puls.benchmark")


def build_strength_benchmark(max_exercises: int = 8) -> dict[str, Any]:
    """Test-Workout: pro Übung ein Aufwärmsatz plus ein Satz bis zum Maximum."""
    lib = [e for e in ex_lib.list_exercises(only_active=True)
           if e.get("slot") in ("main", "pullup", "kettlebell") and e["mode"] == "reps"]
    lib.sort(key=lambda e: (e.get("slot") != "pullup", e["sort_order"]))
    lib = lib[:max_exercises]

    steps: list[dict[str, Any]] = [
        {"type": "warmup", "name": "Locker aufwärmen", "duration_s": 480,
         "notes": "Gut warm werden — der Test ist nur so gut wie dein Aufwärmen"},
    ]
    for e in lib:
        w = e.get("weight_kg")
        if w:
            steps.append({"type": "work", "name": f"{e['name']} (Aufwärmsatz)",
                          "reps": 8, "weight_kg": round(w * 0.6, 1),
                          "notes": "Locker, nur zum Reinkommen"})
            steps.append({"type": "rest", "name": "Pause", "duration_s": 90})
        steps.append({
            "type": "work", "name": e["name"],
            "reps": e.get("rep_max", 15) + 5,   # Obergrenze, damit die Uhr nicht abbricht
            "weight_kg": w,
            "notes": ("MAXTEST: so viele saubere Wiederholungen wie möglich, "
                      "dann Runden-Taste"),
        })
        steps.append({"type": "rest", "name": "Volle Pause", "duration_s": 180,
                      "notes": "Wirklich ausruhen — sonst verfälscht der nächste Test"})

    return {
        "name": "Benchmark: Kraft-Test",
        "sport": "strength",
        "description": ("Pro Übung ein Satz bis zum sauberen Maximum. PULS rechnet "
                        "daraus dein Leistungsniveau aus und setzt alle Arbeitsgewichte "
                        "neu. Wichtig: saubere Technik zählt, nicht die letzte "
                        "gezittere Wiederholung."),
        "steps": steps,
        "exercise_ids": [e["id"] for e in lib],
        "is_benchmark": True,
    }


def calibrate_exercise(exercise_id: int, reps: int, weight_kg: float | None = None
                       ) -> dict[str, Any] | None:
    """Aus einem Maximaltest die Arbeitswerte einer Übung neu setzen."""
    ex = ex_lib.get_exercise(exercise_id)
    if not ex:
        return None
    weight = weight_kg if weight_kg is not None else ex.get("weight_kg")

    if not weight:
        # Körpergewichtsübung (z. B. Klimmzüge): Zielwiederholungen aus dem Test
        target = max(ex["rep_min"], min(ex["rep_max"], max(1, int(reps * 0.7))))
        with get_db() as db:
            db.execute("UPDATE exercises SET target_reps=?, fail_streak=0 WHERE id=?",
                       (target, exercise_id))
            db.execute("INSERT INTO progression_log"
                       "(exercise_id, action, from_reps, to_reps, reason) "
                       "VALUES(?, 'calibrate', ?, ?, ?)",
                       (exercise_id, ex["target_reps"], target,
                        f"Maximaltest: {reps} Wdh. → Arbeitssätze mit {target}"))
        return {"exercise": ex["name"], "max_reps": reps, "target_reps": target,
                "weight_kg": None}

    one_rm = ex_lib.epley_1rm(weight, reps)
    target_reps = ex["rep_min"]
    # 95 % Sicherheitsabschlag: Arbeitssätze sollen nicht am Limit liegen
    work_weight = ex_lib.weight_for_reps(one_rm, target_reps) * 0.95
    work_weight = ex_lib.round_to_increment(work_weight, ex["weight_increment"] or 2.5)

    with get_db() as db:
        db.execute("UPDATE exercises SET weight_kg=?, target_reps=?, est_1rm=?, "
                   "fail_streak=0 WHERE id=?",
                   (work_weight, target_reps, one_rm, exercise_id))
        db.execute("""INSERT INTO progression_log
                      (exercise_id, action, from_weight, to_weight, from_reps, to_reps, reason)
                      VALUES(?, 'calibrate', ?, ?, ?, ?, ?)""",
                   (exercise_id, ex["weight_kg"], work_weight, ex["target_reps"],
                    target_reps,
                    f"Maximaltest: {reps} Wdh. mit {weight} kg → 1RM ≈ "
                    f"{one_rm:.1f} kg → Arbeitsgewicht {work_weight} kg"))
    return {"exercise": ex["name"], "max_reps": reps, "test_weight": weight,
            "est_1rm": round(one_rm, 1), "weight_kg": work_weight,
            "target_reps": target_reps}


def calibrate_from_sets(day: str | None = None) -> list[dict[str, Any]]:
    """Nach dem Benchmark-Sync: den jeweils besten Satz je Übung auswerten."""
    day = day or dt.date.today().isoformat()
    with get_db() as db:
        rows = rows_to_dicts(db.execute(
            "SELECT exercise_id, MAX(reps) AS best_reps, MAX(weight_kg) AS weight "
            "FROM exercise_sets WHERE day=? AND reps IS NOT NULL "
            "GROUP BY exercise_id", (day,)).fetchall())
    out = []
    for r in rows:
        res = calibrate_exercise(r["exercise_id"], int(r["best_reps"]), r["weight"])
        if res:
            out.append(res)
    if out:
        set_setting("last_benchmark", day)
    return out


def record_pullup_max(reps: int) -> dict[str, Any]:
    """Klimmzug-Maximum festhalten und die Progression darauf ausrichten."""
    set_setting("pullup_best", str(reps))
    lib = {e["name"]: e for e in ex_lib.list_exercises()}
    result: dict[str, Any] = {"max_reps": reps}

    free = lib.get("Klimmzüge")
    negative = lib.get("Negative Klimmzüge")
    banded = lib.get("Klimmzüge mit Band")

    # Unter 3 sauberen Klimmzügen bringen freie Sätze wenig — erst Vorstufen
    if reps < 3:
        plan = "negative"
        result["focus"] = ("Noch keine 3 sauberen Klimmzüge — PULS setzt auf negative "
                           "und bandunterstützte Klimmzüge, bis die Basis steht.")
    elif reps < 8:
        plan = "mixed"
        result["focus"] = (f"{reps} saubere Klimmzüge — freie Sätze plus Band als "
                           "Auffüller. Das ist der schnellste Weg nach oben.")
    else:
        plan = "free"
        result["focus"] = (f"{reps} Klimmzüge — stark. Ab hier zählen Volumen und "
                           "später Zusatzgewicht.")

    with get_db() as db:
        if free:
            target = max(1, int(reps * 0.6)) if reps >= 3 else 1
            db.execute("UPDATE exercises SET target_reps=?, rep_max=?, active=?, "
                       "priority=1 WHERE id=?",
                       (target, max(reps + 3, 8), 1 if reps >= 3 else 0, free["id"]))
        if negative:
            db.execute("UPDATE exercises SET active=?, priority=? WHERE id=?",
                       (1 if plan in ("negative", "mixed") else 0,
                        1 if plan == "negative" else 3, negative["id"]))
        if banded:
            db.execute("UPDATE exercises SET active=?, priority=? WHERE id=?",
                       (1 if plan in ("negative", "mixed") else 0,
                        1 if plan == "negative" else 2, banded["id"]))
    result["plan"] = plan
    return result


def status() -> dict[str, Any]:
    """Wann wurde zuletzt kalibriert, steht ein neuer Test an?"""
    interval_weeks = int(get_setting("benchmark_interval_weeks", "10") or 10)
    last_str = get_setting("last_benchmark", "")
    last_run_str = get_setting("last_run_benchmark", "")

    def _due(day_str: str) -> tuple[int | None, bool]:
        if not day_str:
            return None, True
        days = ex_lib.days_since(day_str)
        return days, (days is None or days >= interval_weeks * 7)

    strength_days, strength_due = _due(last_str)
    run_days, run_due = _due(last_run_str)
    paces = running.current_paces()
    return {
        "interval_weeks": interval_weeks,
        "strength": {"last": last_str or None, "days_ago": strength_days,
                     "due": strength_due},
        "run": {"last": last_run_str or None, "days_ago": run_days, "due": run_due,
                "calibrated": bool(paces),
                "paces": {k: running.pace_s_to_str(v) for k, v in (paces or {}).items()},
                "cooper_distance_m": get_setting("cooper_distance_m", "") or None},
        "pullup_best": get_setting("pullup_best", "") or None,
    }
