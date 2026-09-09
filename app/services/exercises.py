"""Übungsbibliothek + Progressionslogik.

Kernidee: Die *Zahlen* (Gewicht, Wiederholungen) macht Code, nicht das LLM.
Das Modell darf auswählen und begründen — rechnen tut die doppelte Progression:

  1. Alle Sätze auf Zielwiederholungen geschafft und Ziel = rep_max?
     -> Gewicht + eine Stufe, Zielwiederholungen zurück auf rep_min.
  2. Alle Sätze geschafft, aber noch Luft nach oben?
     -> Zielwiederholungen + 1.
  3. Zwei Einheiten in Folge deutlich verfehlt?
     -> Deload: Gewicht - eine Stufe, Ziel zurück auf rep_min.
  4. Sonst: halten.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import re
import unicodedata
from typing import Any

from ..db import get_db, get_setting, rows_to_dicts, set_setting

log = logging.getLogger("puls.exercises")

MUSCLE_LABELS = {
    "legs": "Beine", "chest": "Brust", "back": "Rücken", "shoulders": "Schultern",
    "arms": "Arme", "core": "Rumpf", "cardio": "Cardio",
}
EQUIPMENT_LABELS = {
    "machine": "Maschine", "cable": "Kabelzug", "band": "Band", "dumbbell": "Kurzhantel",
    "barbell": "Langhantel", "kettlebell": "Kettlebell", "bodyweight": "Körpergewicht",
    "suspension": "Schlingentrainer", "cardio_machine": "Cardiogerät",
}
# Sinnvolle kleinste Steigerung je Gerätetyp (kg).
# Kettlebells gibt es meist nur in 4-kg-Sprüngen.
DEFAULT_INCREMENT = {
    "machine": 5.0, "cable": 2.5, "band": 2.5, "dumbbell": 2.0, "kettlebell": 4.0,
    "barbell": 2.5, "suspension": 2.5, "bodyweight": 0.0, "cardio_machine": 0.0,
}

SLOT_LABELS = {
    "cardio": "Aufwärmen", "kettlebell": "Kettlebell-Auftakt", "main": "Hauptteil",
    "pullup": "Klimmzug-Arbeit", "stretch": "Dehnen",
}

# Startbibliothek: Thomas' bestehender Maschinenplan plus Kettlebell-Auftakt,
# Klimmzug-Progression und Dehnblock. garmin_category/garmin_exercise stammen aus
# Garmins offizieller Übungsliste, damit die Uhr Name und Animation korrekt zeigt.
SEED_EXERCISES: list[dict[str, Any]] = [
    dict(name="Rudern (Aufwärmen)", muscle_group="cardio", equipment="cardio_machine",
         mode="time", target_duration_s=480, sets=1, rest_s=0, slot="cardio", priority=1,
         garmin_category="INDOOR_ROW", garmin_exercise="ROWING_MACHINE", sort_order=0,
         aliases=["rowing machine", "indoor row", "rudern"]),

    # ---- Kettlebell-Auftakt (ganzkörperlich, aktivierend) ----
    dict(name="Kettlebell Swings", muscle_group="legs", equipment="kettlebell",
         weight_kg=16, weight_increment=4, target_reps=15, rep_min=12, rep_max=20,
         sets=3, rest_s=60, slot="kettlebell", priority=1,
         garmin_category="HIP_SWING", garmin_exercise="SINGLE_ARM_KETTLEBELL_SWING",
         sort_order=1, aliases=["kettlebell swing", "swings", "kb swing"]),
    dict(name="Goblet Squat (Kettlebell)", muscle_group="legs", equipment="kettlebell",
         weight_kg=16, weight_increment=4, target_reps=12, rep_min=10, rep_max=15,
         sets=3, rest_s=60, slot="kettlebell", priority=2,
         garmin_category="SQUAT", garmin_exercise="GOBLET_SQUAT",
         sort_order=2, aliases=["goblet squat", "kettlebell squat"]),
    dict(name="Kettlebell Halo", muscle_group="shoulders", equipment="kettlebell",
         weight_kg=8, weight_increment=4, target_reps=10, rep_min=8, rep_max=12,
         sets=2, rest_s=45, slot="kettlebell", priority=3,
         garmin_category="WARM_UP", garmin_exercise="ARM_CIRCLES",
         sort_order=3, aliases=["halo", "kettlebell halo"]),
    dict(name="Kettlebell Farmer's Walk", muscle_group="core", equipment="kettlebell",
         mode="time", target_duration_s=45, weight_kg=16, weight_increment=4,
         sets=2, rest_s=60, slot="kettlebell", priority=3,
         garmin_category="CARRY", garmin_exercise="FARMERS_WALK",
         sort_order=4, aliases=["farmers walk", "farmer walk", "koffertragen"]),

    # ---- Klimmzug-Ziel: eigener Block, jede Gym-Einheit ----
    dict(name="Klimmzüge", muscle_group="back", equipment="bodyweight",
         target_reps=5, rep_min=3, rep_max=12, sets=4, rest_s=150,
         weight_increment=0, slot="pullup", priority=1,
         garmin_category="PULL_UP", garmin_exercise="PULL_UP", sort_order=5,
         aliases=["pull up", "klimmzug", "klimmzuege"],
         notes="Ziel: saubere Wiederholungen, im letzten Satz alles rausholen"),
    dict(name="Negative Klimmzüge", muscle_group="back", equipment="bodyweight",
         mode="time", target_duration_s=25, sets=3, rest_s=120, weight_increment=0,
         slot="pullup", priority=2,
         garmin_category="PULL_UP", garmin_exercise="JUMPING_PULL_UPS",
         sort_order=6, aliases=["negative pull up", "negative klimmzuege", "jumping pull ups"],
         notes="Hochspringen, 5 s langsam ablassen — Zeit unter Spannung zählt"),
    dict(name="Klimmzüge mit Band", muscle_group="back", equipment="band",
         target_reps=8, rep_min=6, rep_max=12, sets=3, rest_s=120, weight_increment=0,
         slot="pullup", priority=3,
         garmin_category="PULL_UP", garmin_exercise="BAND_ASSISTED_PULL_UP",
         sort_order=7, aliases=["band assisted pull up", "klimmzug mit band"],
         notes="Je stärker das Band, desto mehr Hilfe — Bandstärke notieren"),
    dict(name="Beinpresse", muscle_group="legs", equipment="machine",
         weight_kg=60, weight_increment=5, target_reps=12, rep_min=12, rep_max=15,
         garmin_category="SQUAT", garmin_exercise="LEG_PRESS", sort_order=10,
         aliases=["leg press", "beinpresse"]),
    dict(name="Hamstring-Curls mit Band", muscle_group="legs", equipment="band",
         weight_kg=22.5, weight_increment=2.5, target_reps=15, rep_min=12, rep_max=18,
         machine_setting="Stufe 7 bei Füße",
         garmin_category="LEG_CURL", garmin_exercise="LEG_CURL", sort_order=20,
         aliases=["leg curl", "hamstring curl", "beinbeuger"]),
    dict(name="Brustpresse mit Schlingentrainer", muscle_group="chest", equipment="suspension",
         weight_kg=25, weight_increment=2.5, target_reps=12, rep_min=12, rep_max=15,
         garmin_category="SUSPENSION", garmin_exercise="CHEST_PRESS", sort_order=30,
         aliases=["chest press", "brustpresse", "suspension chest press"]),
    dict(name="Aufrechtes Rudern mit Band", muscle_group="shoulders", equipment="band",
         weight_kg=35, weight_increment=2.5, target_reps=12, rep_min=12, rep_max=15,
         garmin_category="SHRUG", garmin_exercise="UPRIGHT_ROW", sort_order=40,
         aliases=["upright row", "aufrechtes rudern"]),
    dict(name="Flys", muscle_group="chest", equipment="machine",
         weight_kg=25, weight_increment=2.5, target_reps=12, rep_min=12, rep_max=15,
         garmin_category="FLYE", garmin_exercise="CABLE_CROSSOVER", sort_order=50,
         aliases=["flye", "fly", "butterfly", "cable crossover"]),
    dict(name="Latziehen", muscle_group="back", equipment="machine",
         weight_kg=50, weight_increment=5, target_reps=12, rep_min=12, rep_max=15,
         garmin_category="PULL_UP", garmin_exercise="LAT_PULLDOWN", sort_order=60,
         aliases=["lat pulldown", "latzug", "latziehen"]),
    dict(name="Klappmesser", muscle_group="core", equipment="bodyweight",
         mode="time", target_duration_s=30, weight_increment=0, sets=3, rest_s=60,
         garmin_category="CORE", garmin_exercise="SWISS_BALL_JACKKNIFE", sort_order=70,
         aliases=["jackknife", "klappmesser"], notes="So viel wie geht"),
    dict(name="Abwechselndes Seitheben mit statischem Halten", muscle_group="shoulders",
         equipment="dumbbell", weight_kg=4, weight_increment=1, target_reps=12,
         rep_min=12, rep_max=15, garmin_category="LATERAL_RAISE",
         garmin_exercise="ALTERNATING_LATERAL_RAISE_WITH_STATIC_HOLD", sort_order=80,
         aliases=["lateral raise", "seitheben"]),
    dict(name="Abwechselnde Bizeps-Curls mit Kurzhantel im Stehen", muscle_group="arms",
         equipment="dumbbell", weight_kg=6, weight_increment=2, target_reps=12,
         rep_min=12, rep_max=15, garmin_category="CURL",
         garmin_exercise="STANDING_ALTERNATING_DUMBBELL_CURLS", sort_order=90,
         aliases=["biceps curl", "bizeps curl", "dumbbell curl"]),
    dict(name="Reverse Fly positiv", muscle_group="back", equipment="machine",
         weight_kg=25, weight_increment=2.5, target_reps=12, rep_min=12, rep_max=15,
         garmin_category="FLYE", garmin_exercise="INCLINE_REVERSE_FLYE", sort_order=100,
         aliases=["reverse fly", "reverse flye"]),
    dict(name="Trizepsdrücken", muscle_group="arms", equipment="cable",
         weight_kg=15, weight_increment=2.5, target_reps=12, rep_min=12, rep_max=15,
         garmin_category="TRICEPS_EXTENSION", garmin_exercise="TRICEPS_PRESSDOWN",
         sort_order=110, aliases=["triceps pressdown", "trizepsdrücken", "tricep extension"]),

    # ---- Dehnblock nach jeder Gym-Einheit (ca. 5 Minuten) ----
    dict(name="Hüftbeuger-Dehnung", muscle_group="legs", equipment="bodyweight",
         mode="time", target_duration_s=45, sets=1, rest_s=0, weight_increment=0,
         slot="stretch", priority=1, garmin_category="WARM_UP",
         garmin_exercise="STRETCH_LUNGING_HIP_FLEXOR", sort_order=200,
         aliases=["hip flexor stretch", "hueftbeuger"], notes="Pro Seite"),
    dict(name="Hamstring-Dehnung", muscle_group="legs", equipment="bodyweight",
         mode="time", target_duration_s=45, sets=1, rest_s=0, weight_increment=0,
         slot="stretch", priority=1, garmin_category="WARM_UP",
         garmin_exercise="STRETCH_HAMSTRING", sort_order=201,
         aliases=["hamstring stretch"], notes="Pro Seite"),
    dict(name="Brust-Dehnung", muscle_group="chest", equipment="bodyweight",
         mode="time", target_duration_s=40, sets=1, rest_s=0, weight_increment=0,
         slot="stretch", priority=1, garmin_category="WARM_UP",
         garmin_exercise="STRETCH_PECTORAL", sort_order=202,
         aliases=["chest stretch", "brustdehnung"]),
    dict(name="Lat-Dehnung", muscle_group="back", equipment="bodyweight",
         mode="time", target_duration_s=40, sets=1, rest_s=0, weight_increment=0,
         slot="stretch", priority=2, garmin_category="WARM_UP",
         garmin_exercise="STRETCH_LAT", sort_order=203, aliases=["lat stretch"]),
    dict(name="Ausfallschritt mit Drehung", muscle_group="core", equipment="bodyweight",
         mode="time", target_duration_s=40, sets=1, rest_s=0, weight_increment=0,
         slot="stretch", priority=2, garmin_category="WARM_UP",
         garmin_exercise="STRETCH_LUNGE_WITH_SPINAL_TWIST", sort_order=204,
         aliases=["lunge with spinal twist"], notes="Pro Seite"),
    dict(name="Katze-Kuh", muscle_group="core", equipment="bodyweight",
         mode="time", target_duration_s=40, sets=1, rest_s=0, weight_increment=0,
         slot="stretch", priority=2, garmin_category="WARM_UP",
         garmin_exercise="STRETCH_CAT_COW", sort_order=205, aliases=["cat cow", "katze kuh"]),
    dict(name="Waden-Dehnung", muscle_group="legs", equipment="bodyweight",
         mode="time", target_duration_s=40, sets=1, rest_s=0, weight_increment=0,
         slot="stretch", priority=3, garmin_category="WARM_UP",
         garmin_exercise="STRETCH_CALF", sort_order=206, aliases=["calf stretch"],
         notes="Pro Seite — nach dem Laufen besonders sinnvoll"),
    dict(name="Gesäß-Dehnung", muscle_group="legs", equipment="bodyweight",
         mode="time", target_duration_s=40, sets=1, rest_s=0, weight_increment=0,
         slot="stretch", priority=3, garmin_category="WARM_UP",
         garmin_exercise="GLUTES_STRETCH", sort_order=207, aliases=["glutes stretch"],
         notes="Pro Seite"),
]

# Abend-Yoga: eigene Liste, weil es als Yoga-Workout auf die Uhr geht (nicht als
# Kraft). garmin_exercise stammt aus Garmins Yoga-Stellungen — damit zeigt die
# Fenix den richtigen Namen samt Abbildung statt eines namenlosen Zeitblocks.
# "how" ist die Anleitung: kurze Schritte, wie man in die Stellung kommt.
# "cue" ist der eine Satz, der auf die Uhr passt.
EVENING_YOGA_POOL: list[dict[str, Any]] = [
    dict(name="Kindhaltung", sanskrit="Balasana", duration_s=60,
         garmin_exercise="CHILDS", cue="Stirn ablegen, tief in den Bauch atmen",
         focus="Unterer Rücken, Hüfte",
         how=["Auf die Fersen setzen, große Zehen berühren sich, Knie hüftbreit.",
              "Oberkörper nach vorn ablegen, Stirn zum Boden oder auf eine Faust.",
              "Arme lang nach vorn strecken oder neben dem Körper ablegen.",
              "In den unteren Rücken atmen — mit jedem Ausatmen etwas tiefer sinken."]),
    dict(name="Katze-Kuh", sanskrit="Marjaryasana", duration_s=60,
         garmin_exercise="CAT", cue="Im Atemrhythmus bewegen, nicht zählen",
         focus="Wirbelsäule",
         how=["Vierfüßlerstand: Hände unter den Schultern, Knie unter der Hüfte.",
              "Einatmen: Bauch sinken lassen, Brust und Blick heben.",
              "Ausatmen: Rücken rundmachen, Kinn zur Brust, Bauchnabel einziehen.",
              "Langsam wechseln — die Bewegung folgt dem Atem, nicht umgekehrt."]),
    dict(name="Herabschauender Hund", sanskrit="Adho Mukha Svanasana",
         duration_s=60, garmin_exercise="DOWNWARD_FACING_DOG",
         cue="Knie dürfen gebeugt bleiben, Rücken lang", focus="Waden, Hamstrings, Schultern",
         how=["Aus dem Vierfüßlerstand die Zehen aufstellen und das Gesäß nach oben schieben.",
              "Körper bildet ein umgekehrtes V. Hände fest, Finger gespreizt.",
              "Knie ruhig gebeugt lassen — wichtiger ist ein langer, gerader Rücken.",
              "Fersen abwechselnd Richtung Boden schieben, als würdest du auf der Stelle gehen."]),
    dict(name="Taube", sanskrit="Eka Pada Rajakapotasana", duration_s=90,
         garmin_exercise="ONE_LEGGED_PIGEON", cue="Pro Seite — Hüfte gerade halten",
         focus="Hüftbeuger, Gesäß",
         how=["Aus dem herabschauenden Hund das rechte Knie nach vorn hinter das rechte Handgelenk.",
              "Rechter Unterschenkel liegt schräg vor dir, linkes Bein lang nach hinten.",
              "Beide Hüftknochen zeigen nach vorn — bei Bedarf ein Kissen unter die rechte Pobacke.",
              "Oberkörper aufrecht lassen oder langsam nach vorn ablegen. Nach der Hälfte Seite wechseln."]),
    dict(name="Sitzende Vorbeuge", sanskrit="Paschimottanasana", duration_s=60,
         garmin_exercise="SEATED_LONG_LEG_FORWARD_BEND",
         cue="Rücken lang lassen statt tief kommen", focus="Hamstrings, Rücken",
         how=["Aufrecht sitzen, beide Beine lang nach vorn, Füße aktiv angezogen.",
              "Einatmen: Arme lang nach oben, Wirbelsäule strecken.",
              "Ausatmen: aus der Hüfte nach vorn kippen — nicht aus dem Rücken einrollen.",
              "Hände greifen Schienbein, Knöchel oder Füße. Knie dürfen leicht gebeugt sein."]),
    dict(name="Liegende Drehung", sanskrit="Supta Matsyendrasana", duration_s=60,
         garmin_exercise="SUPINE_SPINAL_TWIST",
         cue="Pro Seite — beide Schultern bleiben am Boden",
         focus="Unterer Rücken, Brustwirbelsäule",
         how=["Auf den Rücken legen, Arme seitlich ausgestreckt wie ein T.",
              "Rechtes Knie anziehen und über die linke Körperseite ablegen.",
              "Blick nach rechts, beide Schultern bleiben am Boden — das ist wichtiger als tiefe Knie.",
              "Ruhig atmen, dann Seite wechseln."]),
    dict(name="Schmetterling", sanskrit="Baddha Konasana", duration_s=60,
         garmin_exercise="BOUND_ANGLE", cue="Knie locker sinken lassen, nicht drücken",
         focus="Innenschenkel, Hüfte",
         how=["Aufrecht sitzen, Fußsohlen aneinanderlegen, Fersen Richtung Becken.",
              "Hände umfassen die Füße, Ellenbogen ruhen locker auf den Oberschenkeln.",
              "Aufrichten und die Knie von selbst sinken lassen — nie nach unten drücken.",
              "Wenn du mehr willst: mit langem Rücken leicht nach vorn kippen."]),
    dict(name="Brücke", sanskrit="Setu Bandhasana", duration_s=45,
         garmin_exercise="BRIDGE", cue="Gesäß aktiv, Schultern bleiben unten",
         focus="Gesäß, Hüftbeuger, Brust",
         how=["Auf den Rücken, Knie gebeugt, Füße hüftbreit nah am Gesäß.",
              "Arme liegen neben dem Körper, Handflächen nach unten.",
              "Gesäß anspannen und das Becken heben, bis Oberschenkel und Rumpf eine Linie bilden.",
              "Schultern bleiben am Boden, Nacken lang. Langsam wieder ablegen."]),
    dict(name="Sphinx", sanskrit="Salamba Bhujangasana", duration_s=60,
         garmin_exercise="SPHINX", cue="Schultern weg von den Ohren",
         focus="Untere Wirbelsäule, Brust",
         how=["Auf den Bauch legen, Beine lang und hüftbreit.",
              "Unterarme parallel aufstellen, Ellenbogen direkt unter den Schultern.",
              "Brust heben, Schultern nach hinten unten ziehen.",
              "Der untere Rücken soll sich weit anfühlen, nicht eng — sonst Ellenbogen weiter nach vorn."]),
    dict(name="Nadelöhr", sanskrit="Sucirandhrasana", duration_s=60,
         garmin_exercise="THREAD_THE_NEEDLE", cue="Pro Seite — Gegenschulter sinken lassen",
         focus="Brustwirbelsäule, Schultern",
         how=["Vierfüßlerstand einnehmen.",
              "Rechten Arm unter dem linken hindurch nach links fädeln.",
              "Rechte Schulter und Schläfe auf dem Boden ablegen.",
              "Linke Hand vor dem Kopf aufstellen oder über den Kopf strecken. Dann Seite wechseln."]),
    dict(name="Beine hoch an der Wand", sanskrit="Viparita Karani", duration_s=120,
         garmin_exercise="CORPSE", cue="Klassiker nach Laufeinheiten — einfach liegen",
         focus="Beine, Regeneration",
         how=["Seitlich neben eine Wand setzen, Gesäß möglichst nah heran.",
              "Auf den Rücken rollen und dabei die Beine an der Wand nach oben schwingen.",
              "Gesäß berührt die Wand oder liegt ein paar Zentimeter davon entfernt.",
              "Arme locker ablegen, Augen schließen. Genau hier fließt das Blut aus den Beinen zurück."]),
    dict(name="Totenstellung", sanskrit="Savasana", duration_s=90,
         garmin_exercise="CORPSE", cue="Nichts mehr machen — nur liegen und atmen",
         focus="Nervensystem",
         how=["Flach auf den Rücken legen, Beine locker auseinanderfallen lassen.",
              "Arme neben dem Körper, Handflächen zeigen nach oben.",
              "Augen schließen, Kiefer und Zunge lösen.",
              "Nichts steuern — den Atem einfach laufen lassen. Das ist die Stellung, die den Rest wirken lässt."]),
]


# --------------------------------------------------------------------- CRUD

def seed_default_exercises() -> None:
    """Einmalig beim ersten Start: Thomas' Plan als Startbibliothek anlegen."""
    if get_setting("exercises_seeded") == "1":
        return
    with get_db() as db:
        existing = db.execute("SELECT COUNT(*) AS n FROM exercises").fetchone()["n"]
        if existing:
            set_setting("exercises_seeded", "1")
            return
        for ex in SEED_EXERCISES:
            row = {
                "name": ex["name"],
                "aliases": json.dumps(ex.get("aliases", []), ensure_ascii=False),
                "muscle_group": ex["muscle_group"],
                "equipment": ex["equipment"],
                "mode": ex.get("mode", "reps"),
                "weight_kg": ex.get("weight_kg"),
                "weight_increment": ex.get("weight_increment",
                                           DEFAULT_INCREMENT.get(ex["equipment"], 2.5)),
                "target_reps": ex.get("target_reps", 12),
                "rep_min": ex.get("rep_min", 12),
                "rep_max": ex.get("rep_max", 15),
                "target_duration_s": ex.get("target_duration_s"),
                "sets": ex.get("sets", 3),
                "rest_s": ex.get("rest_s", 90),
                "machine_setting": ex.get("machine_setting"),
                "slot": ex.get("slot", "main"),
                "priority": ex.get("priority", 2),
                "garmin_category": ex.get("garmin_category"),
                "garmin_exercise": ex.get("garmin_exercise"),
                "sort_order": ex.get("sort_order", 100),
                "notes": ex.get("notes"),
            }
            db.execute(
                """INSERT OR IGNORE INTO exercises
                   (name, aliases, muscle_group, equipment, mode, weight_kg,
                    weight_increment, target_reps, rep_min, rep_max, target_duration_s,
                    sets, rest_s, machine_setting, slot, priority, garmin_category,
                    garmin_exercise, sort_order, notes)
                   VALUES(:name,:aliases,:muscle_group,:equipment,:mode,:weight_kg,
                          :weight_increment,:target_reps,:rep_min,:rep_max,
                          :target_duration_s,:sets,:rest_s,:machine_setting,:slot,
                          :priority,:garmin_category,:garmin_exercise,:sort_order,
                          :notes)""", row)
    set_setting("exercises_seeded", "1")
    log.info("Übungsbibliothek mit %d Einträgen initialisiert.", len(SEED_EXERCISES))


def list_exercises(only_active: bool = False) -> list[dict[str, Any]]:
    q = "SELECT * FROM exercises"
    if only_active:
        q += " WHERE active = 1"
    q += " ORDER BY sort_order, name"
    with get_db() as db:
        rows = rows_to_dicts(db.execute(q).fetchall())
    for r in rows:
        r["aliases"] = json.loads(r.get("aliases") or "[]")
    return rows


def get_exercise(ex_id: int) -> dict[str, Any] | None:
    with get_db() as db:
        row = db.execute("SELECT * FROM exercises WHERE id=?", (ex_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["aliases"] = json.loads(d.get("aliases") or "[]")
    return d


EDITABLE = ("name", "muscle_group", "equipment", "mode", "weight_kg", "weight_increment",
            "target_reps", "rep_min", "rep_max", "target_duration_s", "sets", "rest_s",
            "machine_setting", "slot", "priority", "garmin_category", "garmin_exercise",
            "active", "sort_order", "notes")


def upsert_exercise(data: dict[str, Any], ex_id: int | None = None) -> int:
    """Übung anlegen oder ändern. Fehlende Felder werden sinnvoll vorbelegt."""
    equipment = data.get("equipment", "machine")
    if data.get("weight_increment") in (None, ""):
        data["weight_increment"] = DEFAULT_INCREMENT.get(equipment, 2.5)
    if not data.get("garmin_category") or not data.get("garmin_exercise"):
        guess = guess_garmin_mapping(data.get("name", ""), equipment,
                                     data.get("muscle_group", ""))
        data.setdefault("garmin_category", guess[0])
        data.setdefault("garmin_exercise", guess[1])
        data["garmin_category"] = data.get("garmin_category") or guess[0]
        data["garmin_exercise"] = data.get("garmin_exercise") or guess[1]
    if data.get("mode") == "time" and not data.get("target_duration_s"):
        data["target_duration_s"] = 30
    fields = {k: data.get(k) for k in EDITABLE if k in data}
    if "aliases" in data:
        fields["aliases"] = json.dumps(data["aliases"], ensure_ascii=False)
    with get_db() as db:
        if ex_id:
            if not fields:
                return ex_id
            sets = ", ".join(f"{k}=?" for k in fields)
            db.execute(f"UPDATE exercises SET {sets} WHERE id=?",
                       [*fields.values(), ex_id])
            return ex_id
        fields.setdefault("name", data.get("name", "Neue Übung"))
        fields.setdefault("muscle_group", data.get("muscle_group", "other"))
        fields.setdefault("equipment", equipment)
        fields.setdefault("aliases", json.dumps([]))
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cur = db.execute(f"INSERT INTO exercises({cols}) VALUES({marks})",
                         list(fields.values()))
        return int(cur.lastrowid or 0)


def delete_exercise(ex_id: int) -> None:
    with get_db() as db:
        db.execute("DELETE FROM exercises WHERE id=?", (ex_id,))


# ------------------------------------------------------- Garmin-Namensmatching

def normalize(text: str) -> str:
    t = unicodedata.normalize("NFKD", str(text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


# Stichwort -> (Garmin-Kategorie, Garmin-Übung); für neu angelegte Übungen
GARMIN_GUESS = [
    ("beinpresse|leg press", ("SQUAT", "LEG_PRESS")),
    ("kniebeuge|squat", ("SQUAT", "BARBELL_BACK_SQUAT")),
    ("beinbeuger|hamstring|leg curl", ("LEG_CURL", "LEG_CURL")),
    ("beinstrecker|leg extension", ("LEG_CURL", "LEG_EXTENSIONS")),
    ("wadenheben|calf", ("CALF_RAISE", "STANDING_CALF_RAISE")),
    ("ausfallschritt|lunge", ("LUNGE", "LUNGE")),
    ("kreuzheben|deadlift", ("DEADLIFT", "BARBELL_DEADLIFT")),
    ("hip thrust|hueftheben", ("HIP_RAISE", "BARBELL_HIP_THRUST")),
    ("latziehen|latzug|lat pulldown", ("PULL_UP", "LAT_PULLDOWN")),
    ("klimmzug|pull up", ("PULL_UP", "PULL_UP")),
    ("reverse fly", ("FLYE", "INCLINE_REVERSE_FLYE")),
    ("butterfly|flys|flye|fly", ("FLYE", "CABLE_CROSSOVER")),
    ("rudern.*band|aufrechtes rudern|upright row", ("SHRUG", "UPRIGHT_ROW")),
    ("rudermaschine|rudergeraet|rowing machine", ("INDOOR_ROW", "ROWING_MACHINE")),
    ("rudern|row", ("ROW", "CABLE_ROW_STANDING")),
    ("brustpresse.*schling|suspension chest", ("SUSPENSION", "CHEST_PRESS")),
    ("brustpresse|chest press|bankdruecken|bench press", ("BENCH_PRESS", "BARBELL_BENCH_PRESS")),
    ("liegestuetz|push up", ("PUSH_UP", "PUSH_UP")),
    ("schulterdruecken|shoulder press|overhead press", ("SHOULDER_PRESS", "OVERHEAD_BARBELL_PRESS")),
    ("seitheben.*halt", ("LATERAL_RAISE", "ALTERNATING_LATERAL_RAISE_WITH_STATIC_HOLD")),
    ("seitheben|lateral raise", ("LATERAL_RAISE", "DUMBBELL_LATERAL_RAISE")),
    ("nackenziehen|shrug", ("SHRUG", "BARBELL_SHRUG")),
    ("trizeps|triceps", ("TRICEPS_EXTENSION", "TRICEPS_PRESSDOWN")),
    ("bizeps.*abwechseln|alternating.*curl", ("CURL", "STANDING_ALTERNATING_DUMBBELL_CURLS")),
    ("bizeps|curl", ("CURL", "DUMBBELL_BICEPS_CURL")),
    ("klappmesser|jackknife", ("CORE", "SWISS_BALL_JACKKNIFE")),
    ("plank|unterarmstuetz", ("PLANK", "PLANK")),
    ("crunch|sit up|bauchpresse", ("CRUNCH", "CRUNCH")),
    ("beinheben|leg raise", ("LEG_RAISE", "HANGING_KNEE_RAISE")),
    ("hyperextension|rueckenstrecker", ("HYPEREXTENSION", "HYPEREXTENSION")),
]

EQUIPMENT_FALLBACK = {
    "cardio_machine": ("INDOOR_ROW", "ROWING_MACHINE"),
    "bodyweight": ("CORE", "CORE"),
}
MUSCLE_FALLBACK = {
    "legs": ("SQUAT", "LEG_PRESS"), "chest": ("BENCH_PRESS", "BARBELL_BENCH_PRESS"),
    "back": ("ROW", "CABLE_ROW_STANDING"), "shoulders": ("SHOULDER_PRESS", "OVERHEAD_BARBELL_PRESS"),
    "arms": ("CURL", "DUMBBELL_BICEPS_CURL"), "core": ("CORE", "CORE"),
    "cardio": ("INDOOR_ROW", "ROWING_MACHINE"),
}


def guess_garmin_mapping(name: str, equipment: str = "", muscle: str = "") -> tuple[str, str]:
    """Beste Vermutung für Garmins Übungsnamen — nur für neu angelegte Übungen."""
    n = normalize(name)
    for pattern, mapping in GARMIN_GUESS:
        if re.search(pattern, n):
            return mapping
    if equipment in EQUIPMENT_FALLBACK:
        return EQUIPMENT_FALLBACK[equipment]
    return MUSCLE_FALLBACK.get(muscle, ("TOTAL_BODY", "TOTAL_BODY"))


def match_exercise(garmin_name: str | None, garmin_category: str | None = None
                   ) -> dict[str, Any] | None:
    """Ordnet einen von der Uhr gemeldeten Satz einer Bibliotheks-Übung zu."""
    if not garmin_name and not garmin_category:
        return None
    exercises = list_exercises()
    gname = normalize(garmin_name or "")
    # 1. Exaktes Mapping über garmin_exercise
    if garmin_name:
        raw = str(garmin_name).upper()
        for ex in exercises:
            if ex.get("garmin_exercise") and ex["garmin_exercise"].upper() == raw:
                return ex
    # 2. Alias- und Namensvergleich
    if gname:
        for ex in exercises:
            candidates = [normalize(ex["name"]), *(normalize(a) for a in ex["aliases"])]
            if ex.get("garmin_exercise"):
                candidates.append(normalize(ex["garmin_exercise"].replace("_", " ")))
            for cand in candidates:
                if cand and (cand == gname or cand in gname or gname in cand):
                    return ex
    # 3. Kategorie als letzter Anker (nur wenn eindeutig)
    if garmin_category:
        cat = str(garmin_category).upper()
        hits = [e for e in exercises if (e.get("garmin_category") or "").upper() == cat]
        if len(hits) == 1:
            return hits[0]
    return None


# ------------------------------------------------------------- Satz-Erfassung

def _positive(value: Any) -> float | None:
    """Nur echte Messwerte durchlassen.

    Garmin schreibt -1 in repetitionCount, wenn die Uhr die Wiederholungen
    nicht gezaehlt hat — an Maschinen passiert das staendig. Als Zahl gelesen
    ist das kein "unbekannt", sondern "minus eine Wiederholung": Die
    Progression liest daraus ein verfehltes Ziel, haelt das Gewicht und legt
    beim zweiten Mal sogar einen Deload ein. Ein Platzhalter, der wie ein
    Messwert aussieht, ist schlimmer als eine Luecke.
    """
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def record_set(exercise_id: int, reps: int | None = None, weight_kg: float | None = None,
               duration_s: float | None = None, day: str | None = None,
               set_index: int = 1, feeling: str | None = None,
               source: str = "manual", activity_id: int | None = None,
               garmin_set_key: str | None = None) -> int | None:
    day = day or dt.date.today().isoformat()
    clean_reps = _positive(reps)
    reps = int(clean_reps) if clean_reps is not None else None
    weight_kg = _positive(weight_kg)
    duration_s = _positive(duration_s)
    with get_db() as db:
        try:
            cur = db.execute(
                """INSERT INTO exercise_sets
                   (exercise_id, activity_id, garmin_set_key, day, set_index, reps,
                    weight_kg, duration_s, feeling, source)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (exercise_id, activity_id, garmin_set_key, day, set_index, reps,
                 weight_kg, duration_s, feeling, source))
        except Exception as e:  # UNIQUE-Verstoß = Satz schon bekannt
            log.debug("Satz übersprungen (%s)", e)
            return None
        db.execute("UPDATE exercises SET last_performed=? WHERE id=?", (day, exercise_id))
        return int(cur.lastrowid or 0)


def sets_for_day(exercise_id: int, day: str) -> list[dict[str, Any]]:
    with get_db() as db:
        return rows_to_dicts(db.execute(
            "SELECT * FROM exercise_sets WHERE exercise_id=? AND day=? "
            "ORDER BY set_index", (exercise_id, day)).fetchall())


def last_session(exercise_id: int, before_day: str | None = None
                 ) -> tuple[str, list[dict[str, Any]]] | None:
    """Letzter Trainingstag dieser Übung samt aller Sätze."""
    q = "SELECT day FROM exercise_sets WHERE exercise_id=?"
    params: list[Any] = [exercise_id]
    if before_day:
        q += " AND day < ?"
        params.append(before_day)
    q += " ORDER BY day DESC LIMIT 1"
    with get_db() as db:
        row = db.execute(q, params).fetchone()
    if not row:
        return None
    return row["day"], sets_for_day(exercise_id, row["day"])


# ---------------------------------------------------------------- Progression

def round_to_increment(weight: float, increment: float) -> float:
    if not increment or increment <= 0:
        return round(weight, 1)
    return round(round(weight / increment) * increment, 2)


def epley_1rm(weight: float, reps: int) -> float:
    """Geschätztes 1RM nach Epley. Über ~12 Wdh. wird die Schätzung unsicher."""
    return weight * (1 + reps / 30.0)


def weight_for_reps(one_rm: float, reps: int) -> float:
    """Umkehrung: welches Gewicht passt zu einer Zielwiederholungszahl?"""
    return one_rm / (1 + reps / 30.0)


def apply_progression(exercise_id: int, day: str | None = None) -> dict[str, Any] | None:
    """Wertet die Sätze eines Trainingstags aus und schreibt die Progression fort."""
    ex = get_exercise(exercise_id)
    if not ex:
        return None
    session = last_session(exercise_id) if day is None else (day, sets_for_day(exercise_id, day))
    if not session or not session[1]:
        return None
    day, sets = session

    from_weight, from_reps = ex["weight_kg"], ex["target_reps"]
    action, reason = "hold", ""
    new_weight, new_reps = from_weight, from_reps
    fail_streak = ex["fail_streak"]

    if ex["mode"] == "time":
        # Zeitübungen: längste gehaltene Zeit steigert das Ziel um 5 s
        best = max((s["duration_s"] or 0) for s in sets)
        target = ex["target_duration_s"] or 30
        if best >= target:
            new_target = int(target + 5)
            with get_db() as db:
                db.execute("UPDATE exercises SET target_duration_s=?, fail_streak=0 "
                           "WHERE id=?", (new_target, exercise_id))
                db.execute("INSERT INTO progression_log(exercise_id, action, reason) "
                           "VALUES(?, 'reps_up', ?)",
                           (exercise_id, f"{int(best)} s gehalten → Ziel {new_target} s"))
            return {"action": "reps_up", "target_duration_s": new_target}
        return {"action": "hold"}

    work_sets = [s for s in sets if (s.get("reps") or 0) > 0]
    lifted = [s["weight_kg"] for s in sets if (s.get("weight_kg") or 0) > 0]

    if not work_sets:
        # Kein Zaehlwerk, aber Gewicht: Das kommt an jeder Maschine vor, an der
        # die Uhr die Wiederholungen nicht mitbekommt. Die Vorgabe darf dann
        # nicht stehenbleiben — was tatsaechlich aufgelegt war, ist die neue
        # Wahrheit, auch wenn niemand weiss, wie oft es bewegt wurde.
        if not lifted:
            return None
        return _adopt_weight(ex, max(lifted), from_weight, from_reps,
                             "ohne gezählte Wiederholungen")

    reps_done = [int(s["reps"]) for s in work_sets]
    weights = [s["weight_kg"] for s in work_sets if (s.get("weight_kg") or 0) > 0]
    session_weight = max(weights) if weights else from_weight
    feelings = [s.get("feeling") for s in work_sets if s.get("feeling")]
    felt_easy = feelings and all(f == "easy" for f in feelings)
    felt_hard = "hard" in feelings

    all_hit = all(r >= from_reps for r in reps_done)
    badly_missed = min(reps_done) < max(from_reps - 2, ex["rep_min"] - 2)

    if all_hit and from_reps >= ex["rep_max"]:
        increment = ex["weight_increment"] or 0
        new_weight = round_to_increment((session_weight or 0) + increment,
                                        increment) if increment else session_weight
        new_reps = ex["rep_min"]
        action = "weight_up"
        reason = (f"{ex['rep_max']} Wdh. in allen Sätzen geschafft → "
                  f"{new_weight} kg, zurück auf {new_reps} Wdh.")
    elif all_hit:
        step = 2 if felt_easy else 1
        new_reps = min(ex["rep_max"], from_reps + step)
        action = "reps_up"
        reason = (f"Alle Sätze mit {from_reps} Wdh. geschafft"
                  + (" und es war leicht" if felt_easy else "")
                  + f" → Ziel {new_reps} Wdh.")
    elif badly_missed or (felt_hard and min(reps_done) < from_reps):
        fail_streak += 1
        if fail_streak >= 2:
            increment = ex["weight_increment"] or 0
            new_weight = max(0, round_to_increment((session_weight or 0) - increment,
                                                   increment)) if increment else session_weight
            new_reps = ex["rep_min"]
            action = "deload"
            fail_streak = 0
            reason = (f"Zweimal in Folge unter dem Ziel → Deload auf {new_weight} kg, "
                      f"{new_reps} Wdh.")
        else:
            action = "hold"
            reason = "Ziel knapp verfehlt → gleiches Gewicht nochmal angehen"
    else:
        action = "hold"
        reason = "Nah dran → dieselbe Vorgabe nochmal"

    if action != "hold":
        fail_streak = 0 if action != "deload" else fail_streak

    # Wer den Stift umsteckt, hat entschieden. Was tatsaechlich bewegt wurde,
    # ist die Wirklichkeit — die Vorgabe hat ihr zu folgen, nicht umgekehrt.
    # "weight_up" und "deload" rechnen ohnehin schon vom bewegten Gewicht aus;
    # "hold" und "reps_up" liessen es frueher stehen und planten damit an der
    # Wirklichkeit vorbei.
    if action in ("hold", "reps_up") and session_weight and from_weight \
            and abs(session_weight - from_weight) >= 0.5:
        note = (f"{session_weight} kg tatsächlich bewegt statt "
                f"{from_weight} kg — Vorgabe nachgezogen")
        reason = f"{reason} ({note})" if reason else note
        new_weight = session_weight

    est = None
    if weights and reps_done:
        est = max(epley_1rm(w, r) for w, r in zip(weights, reps_done) if w and r) \
            if any(weights) else None

    with get_db() as db:
        db.execute(
            "UPDATE exercises SET weight_kg=?, target_reps=?, fail_streak=?, "
            "est_1rm=COALESCE(?, est_1rm) WHERE id=?",
            (new_weight, new_reps, fail_streak, est, exercise_id))
        db.execute(
            """INSERT INTO progression_log
               (exercise_id, action, from_weight, to_weight, from_reps, to_reps, reason)
               VALUES(?,?,?,?,?,?,?)""",
            (exercise_id, action, from_weight, new_weight, from_reps, new_reps, reason))
    return {"action": action, "weight_kg": new_weight, "target_reps": new_reps,
            "reason": reason}


def _adopt_weight(ex: dict[str, Any], lifted: float, from_weight: float | None,
                  from_reps: int | None, why: str) -> dict[str, Any]:
    """Die Vorgabe auf das tatsaechlich bewegte Gewicht setzen."""
    if from_weight and abs(lifted - from_weight) < 0.5:
        return {"action": "hold", "weight_kg": from_weight,
                "target_reps": from_reps,
                "reason": f"{lifted} kg bewegt, {why} — Vorgabe bleibt"}
    reason = (f"{lifted} kg bewegt {why} (Vorgabe war {from_weight} kg) → "
              f"Vorgabe nachgezogen")
    with get_db() as db:
        db.execute("UPDATE exercises SET weight_kg=? WHERE id=?", (lifted, ex["id"]))
        db.execute("""INSERT INTO progression_log
                      (exercise_id, action, from_weight, to_weight, reason)
                      VALUES(?, 'calibrate', ?, ?, ?)""",
                   (ex["id"], from_weight, lifted, reason))
    return {"action": "calibrate", "weight_kg": lifted, "target_reps": from_reps,
            "reason": reason}


def apply_progression_for_day(day: str) -> list[dict[str, Any]]:
    """Nach einem Trainingstag: Progression für alle beteiligten Übungen fortschreiben."""
    with get_db() as db:
        ids = [r["exercise_id"] for r in db.execute(
            "SELECT DISTINCT exercise_id FROM exercise_sets WHERE day=?", (day,)).fetchall()]
    out = []
    for ex_id in ids:
        res = apply_progression(ex_id, day)
        if res:
            ex = get_exercise(ex_id)
            out.append({"exercise": ex["name"] if ex else ex_id, **res})
    return out


# ------------------------------------------------------------- Vorschlaege

def _best_set(sets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Der Satz, der am meisten gesagt hat: schwerstes Gewicht, darin die
    meisten Wiederholungen."""
    real = [s for s in sets if (s.get("weight_kg") or 0) > 0 and (s.get("reps") or 0) > 0]
    if not real:
        return None
    top = max(s["weight_kg"] for s in real)
    at_top = [s for s in real if s["weight_kg"] == top]
    return max(at_top, key=lambda s: s["reps"])


def propose_for_day(day: str) -> list[dict[str, Any]]:
    """Aus einem Trainingstag Vorschlaege ableiten — ohne etwas zu aendern.

    Der Unterschied zur automatischen Fortschreibung ist nicht technisch,
    sondern eine Frage der Zustaendigkeit: Wer 35 kg statt der geplanten 20
    bewegt, hat eine Entscheidung getroffen, die PULS nachvollziehen, aber
    nicht stillschweigend uebernehmen sollte. Der Vorschlag steht da, mit dem
    Beleg daneben, und ein Tippen macht ihn zur neuen Vorgabe.
    """
    with get_db() as db:
        ids = [r["exercise_id"] for r in db.execute(
            "SELECT DISTINCT exercise_id FROM exercise_sets WHERE day=?",
            (day,)).fetchall()]

    made: list[dict[str, Any]] = []
    for ex_id in ids:
        ex = get_exercise(ex_id)
        if not ex or ex["mode"] == "time":
            continue
        sets = sets_for_day(ex_id, day)
        best = _best_set(sets)
        if not best:
            continue

        from_weight = ex["weight_kg"] or 0.0
        from_reps = ex["target_reps"] or ex["rep_min"] or 8
        lifted, reps = float(best["weight_kg"]), int(best["reps"])
        done = [int(s["reps"]) for s in sets if (s.get("reps") or 0) > 0]
        all_hit = bool(done) and all(r >= from_reps for r in done)

        # 1. Schwerer als geplant: Das Gewicht ist die neue Wahrheit. Die
        #    Wiederholungen richten sich nach dem, was dabei ging.
        if lifted > from_weight + 0.4:
            to_weight = lifted
            to_reps = max(ex["rep_min"], min(ex["rep_max"], reps))
            evidence = f"{reps}× {lifted:g} kg geschafft (Vorgabe {from_reps}× {from_weight:g} kg)"
            reason = (f"Du hast {lifted:g} kg bewegt, geplant waren "
                      f"{from_weight:g} kg — das ist die neue Grundlage.")
        # 2. Wie geplant, aber die Obergrenze erreicht: Gewicht hoch, Wieder-
        #    holungen zurueck auf den Anfang der Spanne.
        elif all_hit and from_reps >= ex["rep_max"]:
            step = ex["weight_increment"] or 2.5
            to_weight = round_to_increment(lifted + step, step)
            to_reps = ex["rep_min"]
            evidence = f"{ex['rep_max']}× {lifted:g} kg in allen Sätzen"
            reason = (f"Die Obergrenze von {ex['rep_max']} Wiederholungen sitzt "
                      f"— jetzt mehr Gewicht, dafür wieder {to_reps} Wiederholungen.")
        # 3. Mehr Wiederholungen als verlangt: Ziel anheben.
        elif done and max(done) > from_reps:
            to_weight = lifted
            to_reps = min(ex["rep_max"], max(done))
            evidence = f"{max(done)}× {lifted:g} kg statt der geplanten {from_reps}"
            reason = (f"Du hast mehr Wiederholungen geschafft als verlangt — "
                      f"das Ziel darf mitwachsen.")
        # 4. Alles wie geplant: eine Wiederholung mehr als naechster Schritt.
        elif all_hit and from_reps < ex["rep_max"]:
            to_weight = lifted or from_weight
            to_reps = from_reps + 1
            evidence = f"alle Sätze mit {from_reps}× {lifted:g} kg"
            reason = "Sauber durchgezogen — der nächste kleine Schritt."
        else:
            continue

        if abs(to_weight - from_weight) < 0.4 and to_reps == from_reps:
            continue

        with get_db() as db:
            db.execute(
                """INSERT INTO progression_proposals
                   (exercise_id, day, from_weight, to_weight, from_reps, to_reps,
                    evidence, reason)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(exercise_id, day) DO UPDATE SET
                     to_weight=excluded.to_weight, to_reps=excluded.to_reps,
                     evidence=excluded.evidence, reason=excluded.reason
                   WHERE progression_proposals.status='open'""",
                (ex_id, day, from_weight, round(to_weight, 1), from_reps,
                 int(to_reps), evidence, reason))
        made.append({"exercise_id": ex_id, "name": ex["name"],
                     "from_weight": from_weight, "to_weight": round(to_weight, 1),
                     "from_reps": from_reps, "to_reps": int(to_reps),
                     "evidence": evidence, "reason": reason})
    return made


def open_proposals(limit: int = 20) -> list[dict[str, Any]]:
    """Offene Vorschlaege, juengste zuerst."""
    with get_db() as db:
        return rows_to_dicts(db.execute(
            """SELECT p.*, e.name, e.muscle_group, e.rep_min, e.rep_max
               FROM progression_proposals p JOIN exercises e ON e.id = p.exercise_id
               WHERE p.status='open' ORDER BY p.day DESC, p.id DESC LIMIT ?""",
            (limit,)).fetchall())


def decide_proposal(proposal_id: int, accept: bool) -> dict[str, Any] | None:
    """Einen Vorschlag uebernehmen oder verwerfen."""
    with get_db() as db:
        row = db.execute("SELECT * FROM progression_proposals WHERE id=? AND status='open'",
                         (proposal_id,)).fetchone()
        if not row:
            return None
        db.execute("UPDATE progression_proposals SET status=?, decided_at=datetime('now') "
                   "WHERE id=?", ("accepted" if accept else "declined", proposal_id))
        if accept:
            db.execute(
                "UPDATE exercises SET weight_kg=?, target_reps=?, fail_streak=0 "
                "WHERE id=?", (row["to_weight"], row["to_reps"], row["exercise_id"]))
            db.execute(
                """INSERT INTO progression_log(exercise_id, action, from_weight,
                       to_weight, from_reps, to_reps, reason)
                   VALUES(?, 'accepted', ?, ?, ?, ?, ?)""",
                (row["exercise_id"], row["from_weight"], row["to_weight"],
                 row["from_reps"], row["to_reps"],
                 f"Vorschlag übernommen: {row['reason']}"))
    return {"id": proposal_id, "accepted": accept}


def decide_all(accept: bool = True) -> int:
    """Alle offenen Vorschlaege auf einmal."""
    count = 0
    for p in open_proposals(limit=100):
        if decide_proposal(p["id"], accept):
            count += 1
    return count


ACTION_WORDS = {
    "weight_up": "mehr Gewicht", "reps_up": "mehr Wiederholungen",
    "deload": "zurückgenommen", "hold": "unverändert",
    "calibrate": "an die Wirklichkeit angepasst",
}


def recent_changes(exercise_ids: list[int] | None = None,
                   days: int = 10) -> list[dict[str, Any]]:
    """Was seit dem letzten Mal an den Vorgaben geaendert wurde — und warum.

    Der Plan aendert sich nach jeder Einheit, aber bisher sah man nur das
    Ergebnis. Wer eine andere Zahl auf dem Zettel findet, ohne zu wissen
    warum, glaubt eher an einen Fehler als an eine Anpassung.
    """
    since = (dt.datetime.now() - dt.timedelta(days=days)).isoformat(timespec="seconds")
    query = """SELECT p.exercise_id, p.ts, p.action, p.from_weight, p.to_weight,
                      p.from_reps, p.to_reps, p.reason, e.name, e.muscle_group
               FROM progression_log p JOIN exercises e ON e.id = p.exercise_id
               WHERE p.ts >= ?"""
    params: list[Any] = [since]
    if exercise_ids:
        query += f" AND p.exercise_id IN ({','.join('?' * len(exercise_ids))})"
        params += list(exercise_ids)
    query += " ORDER BY p.ts DESC"
    with get_db() as db:
        rows = rows_to_dicts(db.execute(query, params).fetchall())

    # Je Uebung nur die juengste Aenderung — sonst steht dieselbe Uebung
    # dreimal da, weil sie dreimal fortgeschrieben wurde.
    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for r in rows:
        if r["exercise_id"] in seen or r["action"] == "hold":
            continue
        seen.add(r["exercise_id"])
        dw = (r["to_weight"] or 0) - (r["from_weight"] or 0)
        dr = (r["to_reps"] or 0) - (r["from_reps"] or 0)
        parts = []
        if abs(dw) >= 0.1:
            parts.append(f"{r['from_weight']:g} → {r['to_weight']:g} kg")
        if dr:
            parts.append(f"{r['from_reps']} → {r['to_reps']} Wdh.")
        out.append({
            "exercise_id": r["exercise_id"], "name": r["name"],
            "muscle_group": r["muscle_group"], "action": r["action"],
            "label": ACTION_WORDS.get(r["action"], r["action"]),
            "change": " · ".join(parts) or ACTION_WORDS.get(r["action"], ""),
            "delta_kg": round(dw, 1) if abs(dw) >= 0.1 else None,
            "delta_reps": dr or None,
            "reason": r["reason"], "when": r["ts"],
        })
    return out


def progression_history(exercise_id: int, limit: int = 20) -> list[dict[str, Any]]:
    with get_db() as db:
        return rows_to_dicts(db.execute(
            "SELECT * FROM progression_log WHERE exercise_id=? ORDER BY id DESC LIMIT ?",
            (exercise_id, limit)).fetchall())


def days_since(day_iso: str | None) -> int | None:
    if not day_iso:
        return None
    try:
        return (dt.date.today() - dt.date.fromisoformat(day_iso[:10])).days
    except ValueError:
        return None
