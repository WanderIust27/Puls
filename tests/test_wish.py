"""Tests für die Einheit auf Zuruf und die Aufteilung der Woche.

Der heikle Teil ist die Arbeitsteilung: Das Modell darf den Satz lesen, die
Übungen kommt aus der Bibliothek. Diese Suite läuft ohne Modell — sie prüft
also genau den Weg, der auch dann funktionieren muss, wenn Ollama nicht läuft.

Aufruf:  python3 tests/test_wish.py
"""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db, set_setting                       # noqa: E402
from app.services import (autopilot, exercises as ex_lib, planner,    # noqa: E402
                          session_request as sr)

failures = []


def ok(name, condition, detail=""):
    print(f"{'OK  ' if condition else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def check(name, actual, expected):
    ok(name, actual == expected, f"{actual!r} (erwartet {expected!r})")


init_db()
ex_lib.seed_default_exercises()


def names_of(workout):
    with get_db() as db:
        return [db.execute("SELECT name FROM exercises WHERE id=?", (i,)
                           ).fetchone()["name"] for i in workout["exercise_ids"]]


# --- Den Satz lesen -------------------------------------------------------
p = sr.parse("90 Minuten Ganzkörper")
check("Dauer erkannt", p["minutes"], 90)
check("Ohne Ortsangabe gilt das Studio", p["place"], "gym")
ok("Ganzkörper heißt alle Gruppen", len(p["groups"]) >= 6, str(p["groups"]))

p = sr.parse("30 Minuten zuhause mit Fokus auf Bauch und Rumpf")
check("Dauer", p["minutes"], 30)
check("Zuhause erkannt", p["place"], "home")
check("Rumpf erkannt", p["groups"], ["core"])

p = sr.parse("45 min Push im Studio")
check("Push wird aufgelöst", sorted(p["groups"]), ["arms", "chest", "shoulders"])
check("Studio erkannt", p["place"], "gym")

p = sr.parse("60 minuten training zuhause für die stärkung um einen handstand zu meistern")
ok("Ziel Handstand erkannt", p["goal"] and p["goal"]["label"] == "Handstand",
   str((p["goal"] or {}).get("label")))
check("… zuhause", p["place"], "home")
ok("… und die passenden Gruppen", "shoulders" in p["groups"], str(p["groups"]))

p = sr.parse("eine Stunde zuhause für den ersten Klimmzug")
check("Ausgeschriebene Stunde", p["minutes"], 60)
ok("Ziel Klimmzüge erkannt", p["goal"] and p["goal"]["label"] == "Klimmzüge")

p = sr.parse("mach was")
check("Ohne Angaben eine sinnvolle Vorgabe", p["minutes"], 45)
ok("… und irgendeine Auswahl", bool(p["groups"]))

# Unsinnige Zahlen dürfen nicht durchschlagen.
p = sr.parse("900 Minuten Ganzkörper")
ok("Unsinnige Dauer fällt auf die Vorgabe zurück", p["minutes"] == 45,
   str(p["minutes"]))

# --- Die Einheit bauen ----------------------------------------------------
w = sr.build("90 Minuten Ganzkörper")
real = planner.step_seconds(w["steps"]) / 60
ok("Ganzkörper trifft die Zeit", abs(real - 90) <= 9, f"{real:.0f} min")
ok("Es steht da, wie der Satz gelesen wurde", "Studio" in w["read_as"], w["read_as"])

w = sr.build("30 Minuten zuhause, Fokus Bauch")
ok("Zuhause trifft die Zeit",
   abs(planner.step_seconds(w["steps"]) / 60 - 30) <= 4)
with get_db() as db:
    kit = {db.execute("SELECT equipment FROM exercises WHERE id=?", (i,)
                      ).fetchone()["equipment"] for i in w["exercise_ids"]}
ok("Zuhause heißt keine Maschine", "machine" not in kit and "cable" not in kit,
   str(kit))

w = sr.build("60 Minuten zuhause für den Handstand")
namen = names_of(w)
ok("Der Handstand kommt vor", "Handstand an der Wand" in namen, " · ".join(namen[:5]))
ok("… und die Handgelenke zuerst", namen[0] == "Handgelenke vorbereiten",
   namen[0])
ok("… mit einer Begründung", bool(w.get("goal_note")))
check("… und einem passenden Namen", w["name"].startswith("Handstand"), True)

w = sr.build("eine Stunde zuhause für den ersten Klimmzug")
namen = names_of(w)
ok("Negative Klimmzüge kommen vor — auch aus einem anderen Block",
   "Negative Klimmzüge" in namen, " · ".join(namen[:4]))

# Fertigkeits-Übungen dürfen NICHT in eine beliebige Einheit rutschen.
w = sr.build("30 Minuten zuhause, Fokus Bauch und Rücken")
namen = names_of(w)
ok("Ohne Ziel kein Handstand", "Handstand an der Wand" not in namen,
   " · ".join(namen))
ok("… und keine Krähe", "Krähe" not in namen, " · ".join(namen))

# --- Ein Schwerpunkt muss die Einheit auch tragen ------------------------
# „Sixpack-Training" darf nicht eine Bauchübung von sechsen ergeben.
w = sr.build("90 minuten gym sixpack training")
namen = names_of(w)
with get_db() as db:
    gruppen = [db.execute("SELECT muscle_group FROM exercises WHERE id=?", (i,)
                          ).fetchone()["muscle_group"] for i in w["exercise_ids"]]
kern = sum(1 for g in gruppen if g == "core")
ok("Der Schwerpunkt trägt die Einheit", kern >= 6,
   f"{kern} von {len(gruppen)} Übungen für den Rumpf")
ok("Sit-ups sind dabei", "Sit-ups" in namen, " · ".join(namen))
ok("Planken sind dabei",
   "Unterarmstütz" in namen and "Seitstütz" in namen, " · ".join(namen))
ok("Maschinen sind auch dabei",
   any(n in namen for n in ("Negativ-Sit-ups (Schrägbank)",
                            "Rumpfrotation an der Maschine",
                            "Crunch am Kabelzug")), " · ".join(namen))

# Die Reihenfolge: erst Matte, dann Gerät — nach dem Aufwärmen liegt man
# ohnehin schon, und die Geräte sind später frei.
# Nur den Hauptteil betrachten: Der Kettlebell-Auftakt steht davor, das
# Dehnen dahinter — nach dem Block zu filtern ist verlässlicher, als
# Übungsnamen zu erraten.
with get_db() as db:
    rows = [db.execute("SELECT name, equipment, slot FROM exercises WHERE id=?",
                       (i,)).fetchone() for i in w["exercise_ids"]]
haupt = [(r["name"], r["equipment"]) for r in rows
         if r["slot"] in ("main", "mat")]
erste_maschine = next((i for i, (_n, g) in enumerate(haupt)
                       if g in ("machine", "cable")), len(haupt))
letzte_matte = max((i for i, (_n, g) in enumerate(haupt)
                    if g == "bodyweight"), default=-1)
ok("Matte vor Maschine", letzte_matte < erste_maschine or erste_maschine == len(haupt),
   " · ".join(f"{n} ({g})" for n, g in haupt))

# Ein breiter Wunsch bleibt ausgewogen.
w = sr.build("90 Minuten Ganzkörper")
with get_db() as db:
    gruppen = {db.execute("SELECT muscle_group FROM exercises WHERE id=?", (i,)
                          ).fetchone()["muscle_group"] for i in w["exercise_ids"]}
ok("Ganzkörper bleibt breit", len(gruppen) >= 5, str(sorted(gruppen)))

# --- Aufteilung der Woche -------------------------------------------------
set_setting("gym_days", json.dumps(["Mo", "Mi", "Fr"]))
set_setting("run_days", json.dumps(["Di", "Do"]))
monday = dt.date.today() + dt.timedelta(days=(7 - dt.date.today().weekday()) % 7 or 7)


def gym_labels(split):
    autopilot.save_settings({"split": split})
    week = autopilot.plan(monday)
    return [s.get("label") for d in week["days"] for s in d["sessions"]
            if s["sport"] == "strength"], week


labels, week = gym_labels("push_pull")
check("Push und Pull wechseln sich ab", labels, ["Push", "Pull", "Push"])
check("Die Aufteilung wird benannt", week["split_label"], "Push / Pull")
ok("… und begründet", bool(week["split_note"]))

labels, _ = gym_labels("push_pull_legs")
check("Dreiteilung", labels, ["Push", "Pull", "Beine"])

labels, _ = gym_labels("upper_lower")
check("Oberkörper und Beine", labels, ["Oberkörper", "Beine & Rumpf", "Oberkörper"])

labels, week = gym_labels("fullbody")
check("Ganzkörper bleibt Ganzkörper", labels, ["Ganzkörper"] * 3)

# Die Aufteilung muss auch in den Übungen ankommen, nicht nur im Namen.
autopilot.save_settings({"split": "push_pull"})
week = autopilot.plan(monday)
push = next(s for d in week["days"] for s in d["sessions"]
            if s["sport"] == "strength" and s.get("label") == "Push")
pull = next(s for d in week["days"] for s in d["sessions"]
            if s["sport"] == "strength" and s.get("label") == "Pull")
ok("Push zielt auf Drücken", set(push["emphasis"]) == {"chest", "shoulders", "arms"},
   str(push["emphasis"]))
ok("Pull zielt auf Ziehen", set(pull["emphasis"]) == {"back", "arms"},
   str(pull["emphasis"]))
ok("Jede Einheit erklärt ihre Rolle",
   "Push" in push["why"] and "Pull" in pull["why"])

# Eine unbekannte Aufteilung darf nicht durchschlagen.
autopilot.save_settings({"split": "quatsch"})
check("Unbekannte Aufteilung wird nicht übernommen",
      autopilot.settings()["split"], "push_pull")

# --- Neue Übungen erreichen auch eine bestehende Bibliothek --------------
# Gesät wird nur einmal. Kommen mit einem Update Übungen dazu, sähe sie sonst
# niemand, der PULS schon benutzt.
with get_db() as db:
    for n in ("Sit-ups", "Negativ-Sit-ups (Schrägbank)",
              "Rumpfrotation an der Maschine", "Rückenstrecker (Gerät)",
              "Hängendes Beinheben", "Crunch am Kabelzug"):
        db.execute("DELETE FROM exercises WHERE name=?", (n,))
    db.execute("UPDATE exercises SET slot='home' WHERE slot='mat'")
    db.execute("UPDATE exercises SET weight_kg=99 WHERE name='Beinpresse'")
    db.execute("""INSERT INTO exercises(name, muscle_group, equipment, slot)
                  VALUES('Meine eigene Übung', 'core', 'bodyweight', 'mat')""")
    vorher = db.execute("SELECT COUNT(*) c FROM exercises").fetchone()["c"]

r = ex_lib.sync_seed_library()
with get_db() as db:
    nachher = db.execute("SELECT COUNT(*) c FROM exercises").fetchone()["c"]
    bp = db.execute("SELECT weight_kg FROM exercises WHERE name='Beinpresse'"
                    ).fetchone()["weight_kg"]
    mat = db.execute("SELECT COUNT(*) c FROM exercises WHERE slot='mat'"
                     ).fetchone()["c"]
    eigen = db.execute("SELECT COUNT(*) c FROM exercises "
                       "WHERE name='Meine eigene Übung'").fetchone()["c"]
check("Sechs Übungen kommen dazu", r["added"], 6)
ok("… und landen wirklich in der Bibliothek", nachher == vorher + 6,
   f"{vorher} → {nachher}")
ok("Umsortierte Blöcke werden nachgezogen", r["moved"] >= 8, str(r["moved"]))
ok("Der Matten-Block ist danach gefüllt", mat >= 9, str(mat))
check("Eigene Gewichte bleiben unangetastet", bp, 99.0)
check("Selbst angelegte Übungen bleiben", eigen, 1)
check("Ein zweiter Lauf ändert nichts", ex_lib.sync_seed_library(),
      {"added": 0, "moved": 0})

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Tests bestanden.")
