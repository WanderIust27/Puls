"""Naehrwertziele und einzelne Mahlzeiten.

Der Bedarf haengt an vier Dingen: Grundumsatz (Alter, Groesse, Gewicht),
Alltagsbewegung, Trainingsverbrauch und dem Ziel. Der Grundumsatz wird nach
Mifflin-St Jeor gerechnet — die Formel, die in Vergleichsstudien am besten
abschneidet.

Der Trainingsverbrauch kommt nicht aus einer Pauschale, sondern aus den
tatsaechlich verbrannten Kalorien der letzten Tage. Wer taeglich laeuft und
dreimal ins Gym geht, hat einen anderen Bedarf als der Durchschnitt derselben
Groesse und desselben Gewichts.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts

log = logging.getLogger("puls.nutrition")

# Zuschlag fuer Alltagsbewegung ohne Sport. 1,3 entspricht einem Tag mit
# Buerojob und etwas Bewegung — Training wird separat aufgeschlagen, sonst
# zaehlt man es doppelt.
BASE_ACTIVITY = 1.3

# Gramm je Kilogramm Koerpergewicht
PROTEIN_PER_KG = {"muscle": 2.0, "weight_loss": 2.2, "endurance": 1.7,
                  "weight_gain": 1.9, "default": 1.8}
FAT_PER_KG = 0.9

GOAL_ADJUST = {"weight_gain": 350, "weight_loss": -400}

SLOTS = {"breakfast": "Frühstück", "lunch": "Mittag", "dinner": "Abend",
         "snack": "Snack", "other": "Sonstiges"}


def _profile() -> dict[str, Any]:
    from . import body
    summary = body.summary(120)
    weight = summary.get("current_kg")
    if weight is None:
        latest = summary.get("latest") or {}
        weight = latest.get("weight_kg")
    def _num(key: str, fallback: float) -> float:
        try:
            return float(get_setting(key, str(fallback)) or fallback)
        except (TypeError, ValueError):
            return fallback
    return {
        "weight_kg": weight,
        "height_cm": _num("body_height_cm", 180),
        "age": _num("body_age", 30),
        "sex": (get_setting("body_sex", "male") or "male").lower(),
    }


def _training_burn(days: int = 14) -> dict[str, Any]:
    """Durchschnittlicher Trainingsverbrauch je Tag."""
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    with get_db() as db:
        row = db.execute(
            """SELECT SUM(calories) AS kcal, COUNT(*) AS n,
                      SUM(duration_s) AS seconds
               FROM activities WHERE substr(start_time,1,10) >= ?
                 AND calories IS NOT NULL""", (since,)).fetchone()
    total = row["kcal"] or 0
    if not total:
        return {"per_day": 0, "days": days, "sessions": 0, "estimated": True}
    return {"per_day": round(total / days), "days": days,
            "sessions": row["n"], "estimated": False}


def targets() -> dict[str, Any]:
    """Was du an einem durchschnittlichen Tag essen solltest."""
    p = _profile()
    weight = p["weight_kg"]
    if not weight:
        return {"ready": False,
                "hint": ("Für die Zielwerte fehlt dein Gewicht. Trag es unter "
                         "Mehr → Körperdaten ein oder stell dich auf die Waage.")}

    male = p["sex"].startswith("m")
    # Mifflin-St Jeor
    bmr = 10 * weight + 6.25 * p["height_cm"] - 5 * p["age"] + (5 if male else -161)
    burn = _training_burn()
    maintenance = bmr * BASE_ACTIVITY + burn["per_day"]

    import json
    try:
        goals = json.loads(get_setting("goals", "[]") or "[]")
    except ValueError:
        goals = []
    adjust = 0
    for g in ("weight_gain", "weight_loss"):
        if g in goals:
            adjust = GOAL_ADJUST[g]
            break
    kcal = maintenance + adjust

    protein_kg = PROTEIN_PER_KG["default"]
    for g in goals:
        if g in PROTEIN_PER_KG:
            protein_kg = PROTEIN_PER_KG[g]
            break
    protein = weight * protein_kg
    fat = weight * FAT_PER_KG
    carbs = max(0, (kcal - protein * 4 - fat * 9) / 4)

    # Vom Nutzer gesetzte Ziele haben Vorrang vor der Rechnung
    override_kcal = get_setting("kcal_target", "")
    override_protein = get_setting("protein_target", "")
    try:
        if override_kcal:
            kcal = float(override_kcal)
    except ValueError:
        pass
    try:
        if override_protein:
            protein = float(override_protein)
    except ValueError:
        pass

    return {
        "ready": True,
        "kcal": round(kcal), "protein_g": round(protein),
        "carbs_g": round(carbs), "fat_g": round(fat),
        "bmr": round(bmr), "maintenance": round(maintenance),
        "training_per_day": burn["per_day"], "sessions": burn["sessions"],
        "adjust": adjust,
        "profile": {**p, "weight_kg": round(weight, 1) if weight else None},
        "explain": (
            f"Grundumsatz {round(bmr)} kcal (Mifflin-St Jeor aus "
            f"{p['age']:.0f} Jahren, {p['height_cm']:.0f} cm, {weight:.1f} kg), "
            f"mal {BASE_ACTIVITY} für den Alltag, plus im Schnitt "
            f"{burn['per_day']} kcal aus deinem Training der letzten "
            f"{burn['days']} Tage"
            + (f", plus {adjust} kcal fürs Zunehmen" if adjust > 0 else
               f", minus {abs(adjust)} kcal fürs Abnehmen" if adjust < 0 else "")
            + f". Eiweiß mit {protein_kg} g je kg, Fett mit {FAT_PER_KG} g je kg, "
              f"der Rest Kohlenhydrate."),
    }


def add_meal(data: dict[str, Any]) -> dict[str, Any]:
    stamp = data.get("eaten_at")
    try:
        when = dt.datetime.fromisoformat(stamp) if stamp else dt.datetime.now()
    except ValueError:
        when = dt.datetime.now()
    portions = float(data.get("portions") or 1)

    def _num(key: str) -> float | None:
        v = data.get(key)
        if v in (None, ""):
            return None
        try:
            return round(float(v) * portions, 1)
        except (TypeError, ValueError):
            return None

    row = {
        "day": when.date().isoformat(),
        "eaten_at": when.isoformat(timespec="seconds"),
        "name": (data.get("name") or "Mahlzeit").strip()[:120],
        "slot": data.get("slot") if data.get("slot") in SLOTS else "other",
        "kcal": _num("kcal"), "protein_g": _num("protein_g"),
        "carbs_g": _num("carbs_g"), "fat_g": _num("fat_g"),
        "recipe_id": data.get("recipe_id"), "portions": portions,
    }
    with get_db() as db:
        cur = db.execute(
            f"INSERT INTO meals({', '.join(row)}) "
            f"VALUES({', '.join(':' + k for k in row)})", row)
        row["id"] = int(cur.lastrowid or 0)
    _sync_daily_total(row["day"])
    return row


def add_recipe(recipe_id: str, portions: float = 1, slot: str = "other",
               eaten_at: str | None = None) -> dict[str, Any]:
    """Ein Rezept als Mahlzeit uebernehmen — die Naehrwerte stehen dort schon."""
    from . import recipes
    r = recipes.get(recipe_id)
    if not r:
        raise ValueError("Dieses Rezept gibt es nicht.")
    return add_meal({
        "name": r["name"], "slot": slot, "portions": portions,
        "eaten_at": eaten_at, "recipe_id": recipe_id,
        "kcal": r["kcal"], "protein_g": r["protein"],
        "carbs_g": r["carbs"], "fat_g": r["fat"],
    })


def delete_meal(meal_id: int) -> bool:
    with get_db() as db:
        row = db.execute("SELECT day FROM meals WHERE id=?", (meal_id,)).fetchone()
        if not row:
            return False
        db.execute("DELETE FROM meals WHERE id=?", (meal_id,))
        day = row["day"]
    _sync_daily_total(day)
    return True


def _sync_daily_total(day: str) -> None:
    """Die Tagessumme in nutrition_log nachfuehren.

    Dashboard, Coach-Kontext und Rezeptauswahl lesen dort — sie muessen von
    den einzelnen Mahlzeiten nichts wissen.
    """
    with get_db() as db:
        t = db.execute(
            """SELECT SUM(kcal) AS kcal, SUM(protein_g) AS p,
                      SUM(carbs_g) AS c, SUM(fat_g) AS f, COUNT(*) AS n
               FROM meals WHERE day=?""", (day,)).fetchone()
        if not t or not t["n"]:
            db.execute("DELETE FROM nutrition_log WHERE day=? AND "
                       "(notes IS NULL OR notes = 'aus Mahlzeiten')", (day,))
            return
        db.execute(
            """INSERT INTO nutrition_log(day, kcal, protein_g, carbs_g, fat_g, notes)
               VALUES(?,?,?,?,?, 'aus Mahlzeiten')
               ON CONFLICT(day) DO UPDATE SET
                 kcal=excluded.kcal, protein_g=excluded.protein_g,
                 carbs_g=excluded.carbs_g, fat_g=excluded.fat_g,
                 notes='aus Mahlzeiten'""",
            (day, t["kcal"], t["p"], t["c"], t["f"]))


def day(day: str | None = None) -> dict[str, Any]:
    """Mahlzeiten des Tages, Summe und Abstand zum Ziel."""
    day = day or dt.date.today().isoformat()
    with get_db() as db:
        meals = rows_to_dicts(db.execute(
            "SELECT * FROM meals WHERE day=? ORDER BY eaten_at", (day,)).fetchall())
    total = {k: round(sum(m[k] or 0 for m in meals), 1)
             for k in ("kcal", "protein_g", "carbs_g", "fat_g")}
    goal = targets()
    remaining = {}
    if goal.get("ready"):
        for key, goal_key in (("kcal", "kcal"), ("protein_g", "protein_g"),
                              ("carbs_g", "carbs_g"), ("fat_g", "fat_g")):
            remaining[key] = round(goal[goal_key] - total[key])
    return {"day": day, "meals": meals, "total": total,
            "targets": goal, "remaining": remaining, "slots": SLOTS}
