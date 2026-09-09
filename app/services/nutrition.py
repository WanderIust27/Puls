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
import re
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts
from . import food_table

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


def estimate_from_text(text: str) -> dict[str, Any]:
    """Aus einer Beschreibung Nährwerte rechnen.

    Arbeitsteilung wie überall hier: Das Modell zerlegt den Satz in
    Bestandteile und Mengen ("zwei Eier und ein Vollkornbrot" → Ei 120 g,
    Vollkornbrot 50 g), die Nährwerte kommen aus der Tabelle. Ein lokales
    Modell auf der CPU schätzt Kalorien jedes Mal anders; eine Tabelle schätzt
    auch, aber gleichbleibend und nachschlagbar.

    Ohne laufendes Modell wird der Text selbst zerlegt — gröber, aber besser
    als gar nichts.
    """
    text = (text or "").strip()
    if not text:
        return {"items": [], "total": _empty_total(), "unknown": [],
                "hint": "Schreib auf, was du gegessen hast."}

    parts = _model_split(text) or _plain_split(text)
    items, unknown = [], []
    for part in parts:
        name = str(part.get("name") or "").strip()
        if not name:
            continue
        try:
            grams = float(part.get("grams") or 0)
        except (TypeError, ValueError):
            grams = 0.0
        if grams <= 0:
            try:
                pieces = float(part.get("pieces") or 1)
            except (TypeError, ValueError):
                pieces = 1.0
            grams = food_table.piece_grams(name) * max(0.25, min(20.0, pieces))
        grams = max(1.0, min(2000.0, grams))
        found = food_table.nutrients(name, grams)
        if found:
            found["name"] = name
            items.append(found)
        else:
            unknown.append(name)

    total = _empty_total()
    for i in items:
        for key in total:
            total[key] = round(total[key] + i[key], 1)
    total["kcal"] = round(total["kcal"])

    # Gegenprobe: Eiweiß und Kohlenhydrate 4 kcal/g, Fett 9. Weicht die Summe
    # stark ab, stimmt etwas nicht — dann lieber sagen als still ausliefern.
    from_macros = total["protein_g"] * 4 + total["carbs_g"] * 4 + total["fat_g"] * 9
    plausible = (not total["kcal"]) or abs(from_macros - total["kcal"]) <= \
        max(60.0, total["kcal"] * 0.25)

    hint = None
    if not items:
        hint = ("Daraus konnte nichts berechnet werden. Nenne die Lebensmittel "
                "einzeln, gern mit Menge — etwa „150 g Hähnchen, 80 g Reis“.")
    elif unknown:
        hint = ("Nicht gefunden: " + ", ".join(unknown[:4])
                + ". Diese Anteile fehlen in der Summe.")
    elif not plausible:
        hint = "Die Summe wirkt unstimmig — bitte vor dem Speichern prüfen."

    return {"text": text, "items": items, "total": total, "unknown": unknown,
            "plausible": plausible, "hint": hint,
            "name": _short_name(text)}


def _empty_total() -> dict[str, float]:
    return {"kcal": 0.0, "protein_g": 0.0, "carbs_g": 0.0, "fat_g": 0.0}


def _short_name(text: str) -> str:
    first = text.strip().splitlines()[0]
    return (first[:57] + "…") if len(first) > 58 else first


def _model_split(text: str) -> list[dict[str, Any]]:
    """Das Modell den Satz zerlegen lassen — Mengen ja, Nährwerte nein."""
    try:
        from .ollama_client import generate_json
        data = generate_json(
            prompt=(
                "Zerlege die folgende Mahlzeitenbeschreibung in einzelne "
                "Lebensmittel mit Mengen. Antworte als JSON-Objekt mit dem "
                "Schlüssel \"items\": eine Liste aus Objekten mit \"name\" "
                "(das Lebensmittel, einzelnes deutsches Wort wenn möglich), "
                "\"grams\" (geschätzte Menge in Gramm, Zahl) und optional "
                "\"pieces\" (Stückzahl). Schätze Mengen realistisch, wenn "
                "keine dabeisteht. Nenne KEINE Kalorien oder Nährwerte — die "
                "werden woanders berechnet. Erfinde keine Zutaten, die nicht "
                "genannt sind.\n\n"
                f"Beschreibung: {text[:500]}"),
            system="Du extrahierst Daten. Du antwortest ausschliesslich mit JSON.")
        items = (data or {}).get("items")
        return items if isinstance(items, list) else []
    except Exception as e:                                      # noqa: BLE001
        log.debug("Mahlzeit ohne Modell zerlegt: %s", e)
        return []


# "150 g Reis", "2 Eier", "eine Banane"
_AMOUNT = re.compile(
    r"(?P<num>\d+(?:[.,]\d+)?)\s*(?P<unit>g|gramm|kg|ml|l|stück|stk|x)?\s*"
    r"(?P<name>[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s-]{2,40})", re.I)
_WORDS = {"ein": 1, "eine": 1, "einen": 1, "zwei": 2, "drei": 3, "vier": 4,
          "fünf": 5, "sechs": 6, "halbe": 0.5, "halber": 0.5}


def _plain_split(text: str) -> list[dict[str, Any]]:
    """Notnagel ohne Modell: Mengen und Namen aus dem Text klauben."""
    out: list[dict[str, Any]] = []
    # Nicht an einem Komma trennen, das in einer Zahl steht: "0,5 kg" ist eine
    # Menge, keine zwei Bestandteile.
    for chunk in re.split(r"(?<!\d),(?!\d)|[;\n]| und | mit ", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        m = _AMOUNT.search(chunk)
        if m:
            num = float(m.group("num").replace(",", "."))
            unit = (m.group("unit") or "").lower()
            name = m.group("name").strip()
            if unit in ("g", "gramm", "ml"):
                out.append({"name": name, "grams": num})
            elif unit in ("kg", "l"):
                out.append({"name": name, "grams": num * 1000})
            else:
                out.append({"name": name, "pieces": num})
            continue
        words = chunk.split()
        count = _WORDS.get(words[0].lower()) if words else None
        name = " ".join(words[1:]) if count else chunk
        out.append({"name": name, "pieces": count or 1})
    return out


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
