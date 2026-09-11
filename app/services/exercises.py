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
         # Nicht "rudern": Das Wort steht in jeder Rudervariante, und der
         # Alias zog sie alle hierher — auch das Kabelrudern mit 50 kg.
         aliases=["rowing machine", "indoor row", "rudergerät", "rudergeraet",
                  "ruderergometer", "ergometer"]),

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
         aliases=["pull up", "pullup", "pull-up", "klimmzug", "klimmzuege"],
         notes="Ziel: saubere Wiederholungen, im letzten Satz alles rausholen"),
    dict(name="Negative Klimmzüge", muscle_group="back", equipment="bodyweight",
         mode="time", target_duration_s=25, sets=3, rest_s=120, weight_increment=0,
         slot="pullup", priority=2,
         garmin_category="PULL_UP", garmin_exercise="JUMPING_PULL_UPS",
         sort_order=6, aliases=["negative pull up", "negative klimmzuege", "jumping pull ups"],
         notes="Hochspringen, 5 s langsam ablassen — Zeit unter Spannung zählt"),
    dict(name="Klimmzüge mit Band", muscle_group="back", equipment="band",
         # Auch hier hilft das Band, statt zu belasten: weniger Band heisst
         # mehr eigene Arbeit. Wer eine Zahl dafuer notiert, meint die Hilfe.
         assisted=True,
         target_reps=8, rep_min=6, rep_max=12, sets=3, rest_s=120, weight_increment=0,
         slot="pullup", priority=3,
         garmin_category="PULL_UP", garmin_exercise="BAND_ASSISTED_PULL_UP",
         sort_order=7, aliases=["band assisted pull up", "klimmzug mit band",
                  "klimmzug mit gummiband"],
         notes="Je stärker das Band, desto mehr Hilfe — Bandstärke notieren"),
    dict(name="Klimmzüge an der Maschine", muscle_group="back", equipment="machine",
         # Das Gewicht ist hier die Hilfe, nicht die Last: 60 kg heisst, die
         # Maschine nimmt dir 60 kg ab. Deshalb assisted=1 — sonst liefe die
         # Fortschreibung genau verkehrt herum.
         assisted=True, weight_kg=60, weight_increment=5, target_reps=10,
         rep_min=8, rep_max=15, sets=3, rest_s=120, slot="pullup", priority=2,
         garmin_category="PULL_UP", garmin_exercise="ASSISTED_PULL_UP",
         sort_order=8, aliases=["assisted pull up", "unterstützter klimmzug",
                                "unterstützte klimmzüge", "klimmzug unterstützt",
                                "klimmzugmaschine", "klimmzug an der maschine",
                                "klimmzug maschine"]),

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
    dict(name="Kreuzheben (Langhantel)", muscle_group="back", equipment="barbell",
         weight_kg=60, weight_increment=5, target_reps=8, rep_min=5, rep_max=12,
         sets=3, rest_s=150, slot="main", priority=2,
         garmin_category="DEADLIFT", garmin_exercise="BARBELL_DEADLIFT",
         sort_order=21, aliases=["deadlift", "deadlifts", "kreuzheben",
                                 "langhantel kreuzheben", "kreuzheben langhantel"]),

    dict(name="Rudern am Kabelzug", muscle_group="back", equipment="cable",
         weight_kg=40, weight_increment=5, target_reps=12, rep_min=10, rep_max=15,
         sets=3, rest_s=90, slot="main", priority=2,
         garmin_category="ROW", garmin_exercise="CABLE_ROW_STANDING",
         sort_order=22, aliases=["cable row", "kabelrudern", "sitzendes rudern",
                                 "rudern kabel", "seated row"]),

    dict(name="Dips", muscle_group="chest", equipment="bodyweight",
         target_reps=8, rep_min=5, rep_max=15, sets=3, rest_s=120,
         slot="main", priority=2,
         garmin_category="TRICEPS_EXTENSION", garmin_exercise="BENCH_DIP",
         sort_order=23, aliases=["dip", "barrenstütz", "trizeps dips",
                                 "dips am barren"]),

    dict(name="Latziehen", muscle_group="back", equipment="machine",
         weight_kg=50, weight_increment=5, target_reps=12, rep_min=12, rep_max=15,
         garmin_category="PULL_UP", garmin_exercise="LAT_PULLDOWN", sort_order=60,
         aliases=["lat pulldown", "lat pull down", "latzug", "latziehen",
                  "latzug am kabel"]),
    dict(name="Sit-ups", muscle_group="core", equipment="bodyweight",
         target_reps=20, rep_min=12, rep_max=30, weight_increment=0, sets=3, rest_s=45,
         slot="mat", garmin_category="SIT_UP", garmin_exercise="SIT_UP",
         sort_order=71, notes="Auf der Matte, Füße locker — nicht reißen",
         aliases=["situp", "sit up", "sit-ups", "bauchpresse frei"]),
    dict(name="Negativ-Sit-ups (Schrägbank)", muscle_group="core", equipment="machine",
         weight_kg=0, weight_increment=2.5, target_reps=12, rep_min=8, rep_max=20,
         sets=3, rest_s=60, slot="main",
         garmin_category="SIT_UP", garmin_exercise="DECLINE_SIT_UP",
         sort_order=72, notes="Schrägbank; Gewicht erst, wenn 20 sauber gehen",
         aliases=["decline situp", "negativ situps", "schraegbank situps"]),
    dict(name="Rumpfrotation an der Maschine", muscle_group="core", equipment="machine",
         weight_kg=25, weight_increment=5, target_reps=12, rep_min=10, rep_max=18,
         sets=3, rest_s=60, slot="main",
         garmin_category="CHOP", garmin_exercise="CABLE_WOOD_CHOP",
         sort_order=73, notes="Aus dem Rumpf drehen, Hüfte bleibt ruhig",
         aliases=["rotation", "torso rotation", "holzhacker", "wood chop",
                  "rumpfrotation"]),
    dict(name="Rückenstrecker (Gerät)", muscle_group="back", equipment="machine",
         weight_kg=0, weight_increment=5, target_reps=15, rep_min=10, rep_max=20,
         sets=3, rest_s=60, slot="main",
         garmin_category="HYPEREXTENSION", garmin_exercise="HYPEREXTENSION",
         sort_order=74, notes="Nur bis zur Geraden, nicht ins Hohlkreuz",
         aliases=["rueckenstrecker", "rückenstrecker", "hyperextension",
                  "back extension", "rückenstrecken am gerät"]),
    dict(name="Hängendes Beinheben", muscle_group="core", equipment="bodyweight",
         target_reps=10, rep_min=6, rep_max=18, weight_increment=0, sets=3, rest_s=60,
         slot="main", garmin_category="LEG_RAISE", garmin_exercise="HANGING_LEG_RAISE",
         sort_order=75, notes="An der Klimmzugstange, ohne Schwung",
         aliases=["hanging leg raise", "beinheben", "knieheben"]),
    dict(name="Crunch am Kabelzug", muscle_group="core", equipment="cable",
         weight_kg=25, weight_increment=5, target_reps=15, rep_min=10, rep_max=20,
         sets=3, rest_s=50, slot="main",
         garmin_category="CRUNCH", garmin_exercise="CABLE_CRUNCH",
         sort_order=76, notes="Kniend, mit dem Brustbein Richtung Becken",
         aliases=["cable crunch", "kabelcrunch", "seilzug crunch"]),
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

    # ---------------------------------------------------------- Zuhause
    # Alles hier braucht nichts als eine Matte und eine kleine Hantel. Der
    # Block "home" taucht in der Gym-Einheit nicht auf — er ist die Grundlage
    # fuer die Einheit, die man abends im Wohnzimmer macht, wenn das Studio
    # nicht in Frage kommt.
    dict(name="Unterarmstütz", muscle_group="core", equipment="bodyweight",
         mode="time", target_duration_s=45, weight_increment=0, sets=3, rest_s=45,
         slot="mat", garmin_category="PLANK", garmin_exercise="FRONT_PLANK",
         sort_order=300, notes="Becken bewusst nicht durchhängen lassen",
         aliases=["plank", "planke", "unterarmstuetz"]),
    dict(name="Seitstütz", muscle_group="core", equipment="bodyweight",
         mode="time", target_duration_s=30, weight_increment=0, sets=4, rest_s=30,
         slot="mat", garmin_category="PLANK", garmin_exercise="SIDE_PLANK",
         sort_order=305, notes="Je Seite zwei Sätze",
         aliases=["side plank", "seitstuetz", "seitliche planke"]),
    dict(name="Käfer", muscle_group="core", equipment="bodyweight",
         target_reps=12, rep_min=8, rep_max=20, weight_increment=0, sets=3, rest_s=45,
         slot="mat", garmin_category="CORE", garmin_exercise="DEAD_BUG",
         sort_order=310, notes="Langsam, der untere Rücken bleibt am Boden",
         aliases=["dead bug", "kaefer", "totenkaefer"]),
    dict(name="Vierfüßlerstand diagonal", muscle_group="core", equipment="bodyweight",
         target_reps=10, rep_min=8, rep_max=16, weight_increment=0, sets=3, rest_s=40,
         slot="mat", garmin_category="CORE", garmin_exercise="BIRD_DOG",
         sort_order=315, notes="Arm und gegenüberliegendes Bein, kurz halten",
         aliases=["bird dog", "vierfuesslerstand", "birddog"]),
    dict(name="Beckenheben", muscle_group="core", equipment="bodyweight",
         target_reps=15, rep_min=10, rep_max=25, weight_increment=0, sets=3, rest_s=45,
         slot="mat", garmin_category="HIP_RAISE", garmin_exercise="GLUTE_BRIDGE",
         sort_order=320, notes="Oben eine Sekunde halten",
         aliases=["glute bridge", "brücke", "beckenheben", "hip raise"]),
    dict(name="Rückenstrecken am Boden", muscle_group="back", equipment="bodyweight",
         target_reps=12, rep_min=8, rep_max=20, weight_increment=0, sets=3, rest_s=45,
         slot="mat", garmin_category="HYPEREXTENSION",
         garmin_exercise="BACK_EXTENSION_WITH_OPPOSITE_ARM_AND_LEG_REACH",
         sort_order=325, notes="Aus dem Rücken heben, nicht aus dem Nacken",
         aliases=["superman", "rueckenstrecken", "back extension"]),
    dict(name="Schwimmer", muscle_group="back", equipment="bodyweight",
         mode="time", target_duration_s=40, weight_increment=0, sets=3, rest_s=40,
         slot="mat", garmin_category="HYPEREXTENSION",
         garmin_exercise="SUPERMAN_ON_SWISS_BALL", sort_order=330,
         notes="Arme und Beine wechselseitig, klein und schnell",
         aliases=["swimmer", "schwimmer"]),
    dict(name="Kurzhantel-Rudern einarmig", muscle_group="back", equipment="dumbbell",
         weight_kg=10, weight_increment=2, target_reps=12, rep_min=8, rep_max=15,
         sets=3, rest_s=60, slot="home", garmin_category="ROW",
         garmin_exercise="SINGLE_ARM_BENT_OVER_ROW", sort_order=335,
         notes="Rücken flach, Ellbogen eng am Körper",
         aliases=["one arm row", "kurzhantelrudern", "rudern einarmig"]),
    dict(name="Kurzhantel-Kreuzheben", muscle_group="back", equipment="dumbbell",
         weight_kg=10, weight_increment=2, target_reps=12, rep_min=8, rep_max=15,
         sets=3, rest_s=60, slot="home", garmin_category="DEADLIFT",
         garmin_exercise="DUMBBELL_DEADLIFT", sort_order=340,
         notes="Beine fast gestreckt, Bewegung aus der Hüfte",
         aliases=["romanian deadlift", "kreuzheben kurzhantel",
                  "rumänisches kreuzheben"]),
    dict(name="Kurzhantel-Seitheben", muscle_group="shoulders", equipment="dumbbell",
         weight_kg=6, weight_increment=2, target_reps=12, rep_min=10, rep_max=18,
         sets=3, rest_s=45, slot="home", garmin_category="LATERAL_RAISE",
         garmin_exercise="LATERAL_RAISE", sort_order=345,
         aliases=["lateral raise", "seitheben"]),
    dict(name="Kurzhantel-Überzüge", muscle_group="back", equipment="dumbbell",
         weight_kg=8, weight_increment=2, target_reps=12, rep_min=10, rep_max=16,
         sets=3, rest_s=45, slot="home", garmin_category="CHOP",
         garmin_exercise="DUMBBELL_PULLOVER", sort_order=350,
         notes="Nur so weit, wie der untere Rücken flach bleibt",
         aliases=["pullover", "ueberzuege"]),
    dict(name="Russischer Twist mit Hantel", muscle_group="core", equipment="dumbbell",
         weight_kg=6, weight_increment=2, target_reps=16, rep_min=10, rep_max=24,
         sets=3, rest_s=45, slot="mat", garmin_category="CHOP",
         garmin_exercise="WEIGHTED_RUSSIAN_TWIST_ON_SWISS_BALL", sort_order=355,
         notes="Aus dem Rumpf drehen, nicht aus den Armen",
         aliases=["russian twist", "russischer twist"]),
    dict(name="Liegestütz", muscle_group="chest", equipment="bodyweight",
         target_reps=12, rep_min=6, rep_max=25, weight_increment=0, sets=3, rest_s=60,
         slot="home", garmin_category="PUSH_UP", garmin_exercise="PUSH_UP",
         sort_order=360, aliases=["push up", "liegestuetz", "liegestütze"]),
    dict(name="Ausfallschritte", muscle_group="legs", equipment="bodyweight",
         target_reps=12, rep_min=8, rep_max=20, weight_increment=0, sets=3, rest_s=50,
         slot="home", garmin_category="LUNGE", garmin_exercise="WALKING_LUNGE",
         sort_order=365, notes="Je Seite; das hintere Knie sinkt tief",
         aliases=["lunge", "ausfallschritt"]),
    dict(name="Katze-Kuh zum Abschluss", muscle_group="back", equipment="bodyweight",
         mode="time", target_duration_s=60, weight_increment=0, sets=1, rest_s=0,
         slot="home", garmin_category="UNKNOWN", garmin_exercise="UNKNOWN",
         sort_order=370, notes="Ruhig atmen, Wirbel für Wirbel",
         aliases=["cat cow"]),

    # Uebungen, die auf eine Fertigkeit hinarbeiten. Sie stehen im selben Block
    # "home", tauchen aber nur auf, wenn ein Ziel sie verlangt — ein
    # Handstand-Halt gehoert nicht in eine beliebige Bauch-Einheit.
    dict(name="Handstand an der Wand", muscle_group="shoulders", equipment="bodyweight",
         mode="time", target_duration_s=30, weight_increment=0, sets=4, rest_s=90,
         slot="home", garmin_category="SHOULDER_STABILITY",
         garmin_exercise="HANDSTAND_PUSH_UP", sort_order=400,
         notes="Bauch zur Wand, Schultern über den Händen, Rippen geschlossen",
         aliases=["handstand", "wandhandstand", "handstand hold"]),
    dict(name="Pike-Liegestütz", muscle_group="shoulders", equipment="bodyweight",
         target_reps=8, rep_min=5, rep_max=15, weight_increment=0, sets=3, rest_s=75,
         slot="home", garmin_category="PUSH_UP", garmin_exercise="PIKE_PUSH_UP",
         sort_order=405, notes="Hüfte hoch, Kopf zwischen den Händen absenken",
         aliases=["pike push up", "pike liegestuetz"]),
    dict(name="Hohlkörper halten", muscle_group="core", equipment="bodyweight",
         mode="time", target_duration_s=30, weight_increment=0, sets=3, rest_s=60,
         slot="mat", garmin_category="CORE", garmin_exercise="HOLLOW_HOLD",
         sort_order=410, notes="Unterer Rücken bleibt am Boden — davon hängt alles ab",
         aliases=["hollow body", "hohlkoerper", "hollow hold"]),
    dict(name="Krähe", muscle_group="arms", equipment="bodyweight",
         mode="time", target_duration_s=20, weight_increment=0, sets=4, rest_s=60,
         slot="home", garmin_category="PLANK", garmin_exercise="FRONT_PLANK",
         sort_order=415, notes="Knie auf die Oberarme, Blick nach vorn",
         aliases=["crow", "kraehe", "crow pose", "bakasana"]),
    dict(name="Schulterdrücken mit Kurzhantel", muscle_group="shoulders",
         equipment="dumbbell", weight_kg=8, weight_increment=2, target_reps=10,
         rep_min=6, rep_max=15, sets=3, rest_s=75, slot="home",
         garmin_category="SHOULDER_PRESS", garmin_exercise="DUMBBELL_SHOULDER_PRESS",
         sort_order=420, aliases=["shoulder press", "schulterdruecken"]),
    dict(name="Handgelenke vorbereiten", muscle_group="arms", equipment="bodyweight",
         mode="time", target_duration_s=60, weight_increment=0, sets=1, rest_s=0,
         slot="home", garmin_category="UNKNOWN", garmin_exercise="UNKNOWN",
         sort_order=425, notes="Kreisen, Beugen, Strecken — vor jeder Stützarbeit",
         aliases=["handgelenke", "wrist prep"]),
    dict(name="Bär-Kriechen", muscle_group="core", equipment="bodyweight",
         mode="time", target_duration_s=40, weight_increment=0, sets=3, rest_s=60,
         slot="home", garmin_category="TOTAL_BODY", garmin_exercise="BEAR_CRAWL",
         sort_order=430, notes="Knie knapp über dem Boden, Rücken ruhig",
         aliases=["bear crawl", "baer kriechen"])
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

def _seed_row(ex: dict[str, Any]) -> dict[str, Any]:
    """Einen Eintrag der Startbibliothek in eine Datenbankzeile uebersetzen."""
    return {
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
        "assisted": 1 if ex.get("assisted") else 0,
        "priority": ex.get("priority", 2),
        "garmin_category": ex.get("garmin_category"),
        "garmin_exercise": ex.get("garmin_exercise"),
        "sort_order": ex.get("sort_order", 100),
        "notes": ex.get("notes"),
    }


# Aliase, die sich als zu grob erwiesen haben. Sie werden bei bestehenden
# Bibliotheken entfernt, nicht nur in der Startbibliothek weggelassen.
RETIRED_ALIASES: list[tuple[str, str]] = [
    ("Rudern (Aufwärmen)", "rudern"),
    # Die unterstuetzten Klimmzuege haben eine eigene Uebung bekommen: An der
    # Maschine ist das Gewicht die Hilfe, am Band gibt es gar keins.
    ("Klimmzüge mit Band", "unterstützter klimmzug"),
    ("Klimmzüge mit Band", "unterstützte klimmzüge"),
    ("Klimmzüge mit Band", "assisted pull up"),
    ("Klimmzüge mit Band", "klimmzugmaschine"),
]


def sync_seed_library() -> dict[str, int]:
    """Neue Uebungen aus der Startbibliothek nachtragen.

    Gesaet wird nur einmal, beim ersten Start. Kommen mit einem Update neue
    Uebungen dazu — etwa Sit-ups und Planken fuers Studio —, saehe sie sonst
    niemand, der PULS schon benutzt. Angefasst wird nichts Bestehendes:
    Gewichte, Zielwerte und selbst angelegte Uebungen bleiben, wie sie sind.
    Nur der Block wird nachgezogen, wenn eine Uebung umgeraeumt wurde.
    """
    added = moved = renamed = 0
    with get_db() as db:
        known = {r["name"]: dict(r) for r in db.execute(
            "SELECT name, slot, aliases, assisted FROM exercises").fetchall()}
        if not known:
            return {"added": 0, "moved": 0, "aliases": 0}
        for ex in SEED_EXERCISES:
            if ex["name"] not in known:
                row = _seed_row(ex)
                db.execute(
                    f"INSERT OR IGNORE INTO exercises({', '.join(row)}) "
                    f"VALUES({', '.join(':' + k for k in row)})", row)
                added += 1
                continue
            current = known[ex["name"]]
            if ex.get("slot", "main") != current["slot"]:
                db.execute("UPDATE exercises SET slot=? WHERE name=?",
                           (ex.get("slot", "main"), ex["name"]))
                moved += 1
            # Ob das Gewicht hilft oder belastet, ist eine Eigenschaft der
            # Uebung, keine Einstellung des Nutzers — sie wird nachgezogen.
            want_assist = 1 if ex.get("assisted") else 0
            if want_assist != (current["assisted"] or 0):
                db.execute("UPDATE exercises SET assisted=? WHERE name=?",
                           (want_assist, ex["name"]))
                moved += 1
            # Aliase sind das, woran die Texterkennung haengt. Kommen mit
            # einem Update neue dazu, muessen sie auch bei einer bestehenden
            # Bibliothek ankommen — sonst findet "unterstützter Klimmzug"
            # weiterhin nichts. Selbst angelegte Aliase bleiben erhalten.
            #
            # Ergaenzen und Entfernen passieren in einem Zug und werden einmal
            # geschrieben. Zwei getrennte Durchlaeufe ueber denselben Stand
            # wuerden sich gegenseitig ueberschreiben — der zweite Lauf haette
            # dann nie Ruhe gegeben.
            try:
                have = json.loads(current["aliases"] or "[]")
            except ValueError:
                have = []
            retired = {drop for name, drop in RETIRED_ALIASES if name == ex["name"]}
            kept = [a for a in have if str(a).lower() not in retired]
            lower = {str(a).lower() for a in kept}
            fresh = [a for a in ex.get("aliases", []) if a.lower() not in lower]
            final = kept + fresh
            if final != have:
                db.execute("UPDATE exercises SET aliases=? WHERE name=?",
                           (json.dumps(final, ensure_ascii=False), ex["name"]))
                renamed += len(fresh) + (len(have) - len(kept))

    if added or moved or renamed:
        log.info("Bibliothek ergänzt: %d neu, %d umsortiert, %d Aliase.",
                 added, moved, renamed)
    return {"added": added, "moved": moved, "aliases": renamed}


def seed_default_exercises() -> None:
    """Einmalig beim ersten Start: Thomas' Plan als Startbibliothek anlegen."""
    if get_setting("exercises_seeded") == "1":
        sync_seed_library()
        return
    with get_db() as db:
        existing = db.execute("SELECT COUNT(*) AS n FROM exercises").fetchone()["n"]
    if existing:
        # Bibliothek da, Haekchen fehlte nur: nachtragen und weiter.
        # set_setting oeffnet die Datenbank selbst — innerhalb eines offenen
        # get_db() blockiert das dauerhaft, die Sperre ist nicht reentrant.
        set_setting("exercises_seeded", "1")
        sync_seed_library()
        return
    with get_db() as db:
        for ex in SEED_EXERCISES:
            # Spaltenliste aus der Zeile selbst, nicht von Hand gepflegt: Eine
            # neu hinzugekommene Spalte fehlte hier sonst stillschweigend und
            # stuende in jeder frischen Bibliothek auf ihrem Vorgabewert.
            row = _seed_row(ex)
            db.execute(
                f"INSERT OR IGNORE INTO exercises({', '.join(row)}) "
                f"VALUES({', '.join(':' + k for k in row)})", row)
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
            "active", "sort_order", "notes", "assisted")


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


# Die Spanne, in der ein Gewicht richtig sitzt (Doppelprogression).
#
#   Schaffst du MEHR als REP_MAX Wiederholungen, ist das Gewicht zu leicht:
#   einen Schritt hoch, Ziel wieder REP_MIN.
#   Schaffst du WENIGER als REP_MIN, ist es zu schwer: einen Schritt runter,
#   Ziel wieder REP_MIN.
#   Dazwischen ist alles in Ordnung — dann gibt es keinen Vorschlag.
#
# Der Schritt ist die kleinste sinnvolle Aenderung der jeweiligen Uebung
# (weight_increment): 2,5 kg an der Maschine, 5 kg an der Langhantel.
#
# Bewusst als Zahlen und nicht als Formel: Das ist eine Trainingsentscheidung,
# keine Rechnung, und sie soll nachlesbar und aenderbar sein.
PROG = {"rep_min": 8, "rep_max": 12}


def _scheme() -> dict[str, int]:
    def num(key: str, fallback: int) -> int:
        try:
            return int(float(get_setting(f"prog_{key}", str(fallback)) or fallback))
        except (TypeError, ValueError):
            return fallback
    low = max(1, num("rep_min", PROG["rep_min"]))
    high = max(low + 1, num("rep_max", PROG["rep_max"]))
    return {"rep_min": low, "rep_max": high}


def propose_for_day(day: str) -> list[dict[str, Any]]:
    """Aus einem Trainingstag Vorschlaege ableiten — ohne etwas zu aendern.

    Massgeblich ist der schwerste Satz des Tages. Wer sich innerhalb einer
    Einheit hocharbeitet (25, dann 30, dann 35 kg), hat mit dem letzten Satz
    gezeigt, was geht — und nicht mit dem ersten. Der Durchschnitt waere hier
    die falsche Zusammenfassung: Er beschreibt eine Belastung, die so nie
    stattgefunden hat.

    Geaendert wird nichts. Der Vorschlag steht mit seinem Beleg da, und ein
    Tippen macht ihn zur neuen Vorgabe.
    """
    cfg = _scheme()
    low, high = cfg["rep_min"], cfg["rep_max"]
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
        from_weight = ex["weight_kg"] or 0.0
        from_reps = ex["target_reps"] or low

        best = _best_set(sets)
        if not best:
            # Kein Zaehlwerk, aber Gewicht: Das kommt an jeder Maschine vor, an
            # der die Uhr die Wiederholungen nicht mitbekommt.
            lifted = [s["weight_kg"] for s in sets if (s.get("weight_kg") or 0) > 0]
            if not lifted or abs(max(lifted) - from_weight) < 0.4:
                continue
            top = max(lifted)
            made.append(_store_proposal(
                ex, day, from_weight, from_reps, top, from_reps,
                f"{top:g} kg bewegt, Wiederholungen nicht gezählt",
                f"{ex['name']}: Die Uhr hat nichts gezählt, aber {top:g} kg "
                f"lagen auf — die Vorgabe zieht nach."))
            continue

        heaviest, reps = float(best["weight_kg"]), int(best["reps"])
        step = ex["weight_increment"] or 2.5

        # Bei unterstuetzten Uebungen hilft das Gewicht, statt zu belasten:
        # 60 kg an der Klimmzugmaschine heisst, sie nimmt dir 60 kg ab, und am
        # Band gilt dasselbe. Mehr Kilo sind dort weniger Anstrengung — die
        # Richtung dreht sich also um.
        assisted = bool(ex.get("assisted"))
        harder = -step if assisted else step
        unit = " Hilfe" if assisted else ""

        if reps > high:
            to_weight = max(0.0, round_to_increment(heaviest + harder, step))
            to_reps = low
            evidence = f"schwerster Satz: {reps}× {heaviest:g} kg{unit}"
            reason = (f"{ex['name']}: {reps} Wiederholungen bei {heaviest:g} kg"
                      f"{unit} — mehr als {high}, also noch Luft. "
                      + (f"Mit {to_weight:g} kg Unterstützung wird es wieder "
                         f"fordernd" if assisted else
                         f"Ab jetzt {to_weight:g} kg")
                      + f", Ziel {to_reps} Wiederholungen.")
        elif reps < low:
            to_weight = max(0.0, round_to_increment(heaviest - harder, step))
            to_reps = low
            evidence = f"schwerster Satz: {reps}× {heaviest:g} kg{unit}"
            reason = (f"{ex['name']}: Nur {reps} Wiederholungen bei "
                      f"{heaviest:g} kg{unit} — weniger als {low}, also zu schwer. "
                      + (f"Mit {to_weight:g} kg Unterstützung" if assisted else
                         f"Mit {to_weight:g} kg")
                      + f" kommst du sauber durch {to_reps} Wiederholungen.")
        else:
            # Die Spanne ist getroffen: Das Gewicht sitzt. Der einzige Grund,
            # trotzdem etwas zu melden, ist eine Vorgabe, die nicht zu dem
            # passt, was tatsaechlich auf der Maschine lag.
            if abs(heaviest - from_weight) < 0.4:
                continue
            to_weight = heaviest
            to_reps = max(low, min(high, reps))
            evidence = f"schwerster Satz: {reps}× {heaviest:g} kg{unit}"
            reason = (f"{ex['name']}: {reps} Wiederholungen bei {heaviest:g} kg"
                      f"{unit} liegen in der Spanne {low}–{high} — das Gewicht "
                      f"passt. In der Bibliothek stehen noch {from_weight:g} kg; "
                      f"der Vorschlag zieht sie nach.")

        if abs(to_weight - from_weight) < 0.4 and to_reps == from_reps:
            continue
        made.append(_store_proposal(ex, day, from_weight, from_reps,
                                    round(to_weight, 1), int(to_reps),
                                    evidence, reason))
    return made


def _store_proposal(ex: dict[str, Any], day: str, from_weight: float,
                    from_reps: int, to_weight: float, to_reps: int,
                    evidence: str, reason: str) -> dict[str, Any]:
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
            (ex["id"], day, from_weight, to_weight, from_reps, to_reps,
             evidence, reason))
        # Aeltere offene Vorschlaege derselben Uebung sind ueberholt: Der
        # juengere Trainingstag weiss mehr. Sonst staende dieselbe Uebung
        # dreimal mit drei Zahlen da, und man muesste raten, welche gilt.
        db.execute(
            "UPDATE progression_proposals SET status='superseded', "
            "decided_at=datetime('now') "
            "WHERE exercise_id=? AND day < ? AND status='open'",
            (ex["id"], day))
    return {"exercise_id": ex["id"], "name": ex["name"],
            "from_weight": from_weight, "to_weight": to_weight,
            "from_reps": from_reps, "to_reps": to_reps,
            "evidence": evidence, "reason": reason}


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
    # Vor der Verbindung holen: _scheme() liest Einstellungen und oeffnet dafuer
    # selbst die Datenbank. Die Sperre ist nicht reentrant — innerhalb eines
    # offenen get_db() blockiert das dauerhaft, ohne Fehlermeldung.
    cfg = _scheme()
    with get_db() as db:
        row = db.execute("SELECT * FROM progression_proposals WHERE id=? AND status='open'",
                         (proposal_id,)).fetchone()
        if not row:
            return None
        db.execute("UPDATE progression_proposals SET status=?, decided_at=datetime('now') "
                   "WHERE id=?", ("accepted" if accept else "declined", proposal_id))
        if accept:
            # Die Spanne mitziehen: Sonst stuende "8 Wiederholungen" bei einer
            # Spanne von 12 bis 18, und die naechste Fortschreibung rechnete
            # gegen die eigene Vorgabe.
            db.execute(
                """UPDATE exercises SET weight_kg=?, target_reps=?, fail_streak=0,
                       rep_min=?, rep_max=?
                   WHERE id=?""",
                (row["to_weight"], row["to_reps"], cfg["rep_min"], cfg["rep_max"],
                 row["exercise_id"]))
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
