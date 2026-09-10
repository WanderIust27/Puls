"""Tests für die Einheit ohne Geräte.

Auf der Matte gilt dasselbe wie im Studio: Die Dauer muss stimmen, und was
angesagt ist, muss auch ohne Studio machbar sein.

Aufruf:  python3 tests/test_home.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db                            # noqa: E402
from app.services import exercises as ex_lib, mood, planner   # noqa: E402

failures = []


def ok(name, condition, detail=""):
    print(f"{'OK  ' if condition else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def check(name, actual, expected):
    ok(name, actual == expected, f"{actual!r} (erwartet {expected!r})")


init_db()
ex_lib.seed_default_exercises()

# "home" und "mat" sind beides Übungen ohne Studio. Matten-Übungen tauchen
# zusätzlich im Gym auf — deshalb der eigene Block, nicht weil sie zuhause
# nicht zählten.
home = [e for e in ex_lib.list_exercises() if e.get("slot") in ("home", "mat")]
ok("Es gibt Übungen für zuhause", len(home) >= 12, f"{len(home)} Übungen")
ok("Rumpf und Rücken sind gut vertreten",
   sum(1 for e in home if e["muscle_group"] == "core") >= 4
   and sum(1 for e in home if e["muscle_group"] == "back") >= 4,
   str({g: sum(1 for e in home if e["muscle_group"] == g)
        for g in {e["muscle_group"] for e in home}}))
ok("Nichts davon braucht ein Gerät",
   all(e["equipment"] in ("bodyweight", "dumbbell", "band") for e in home),
   str({e["equipment"] for e in home}))
ok("Jede hat eine Garmin-Zuordnung",
   all(e.get("garmin_exercise") for e in home))

# --- Dauer treffen -------------------------------------------------------
for wanted in (15, 20, 30, 45):
    s = planner.build_home_session(wanted, ["core", "back"])
    real = planner.step_seconds(s["steps"]) / 60
    ok(f"{wanted}-Minuten-Einheit trifft die Zeit",
       abs(real - wanted) <= max(3, wanted * 0.15), f"{real:.0f} min")
    ok(f"… und der Name sagt es ({wanted})", str(s["minutes"]) in s["name"], s["name"])

kurz = planner.build_home_session(15, ["core"])
lang = planner.build_home_session(45, ["core", "back"])
ok("Mehr Zeit heißt mehr Übungen",
   len(lang["exercise_ids"]) > len(kurz["exercise_ids"]),
   f"{len(kurz['exercise_ids'])} vs {len(lang['exercise_ids'])}")

# --- Nur die gewünschten Gruppen ----------------------------------------
s = planner.build_home_session(30, ["core", "back"])
groups = set()
with get_db() as db:
    for eid in s["exercise_ids"]:
        groups.add(db.execute("SELECT muscle_group FROM exercises WHERE id=?",
                              (eid,)).fetchone()["muscle_group"])
ok("Es kommen nur die gewünschten Gruppen", groups <= {"core", "back"}, str(groups))
ok("… und beide auch wirklich", groups == {"core", "back"}, str(groups))

# Reihum, nicht sechsmal dasselbe.
with get_db() as db:
    seq = [db.execute("SELECT muscle_group FROM exercises WHERE id=?",
                      (eid,)).fetchone()["muscle_group"] for eid in s["exercise_ids"]]
ok("Die Gruppen wechseln sich ab",
   not any(seq[i] == seq[i + 1] == seq[i + 2] for i in range(len(seq) - 2)),
   " → ".join(seq))

# --- Ohne Hantel --------------------------------------------------------
ohne = planner.build_home_session(30, ["core", "back"], with_dumbbell=False)
with get_db() as db:
    kit = {db.execute("SELECT equipment FROM exercises WHERE id=?",
                      (eid,)).fetchone()["equipment"] for eid in ohne["exercise_ids"]}
ok("Ohne Hantel kommt keine Hantel vor", "dumbbell" not in kit, str(kit))
ok("… und es bleibt trotzdem eine Einheit",
   len(ohne["exercise_ids"]) >= 3, str(len(ohne["exercise_ids"])))

# --- Beschwerden gelten auch zuhause ------------------------------------
mood.record({"mood": 3, "energy": 3, "stress": 3,
             "complaints": [{"region": "back_low", "kind": "pain", "severity": 3}]})
geschont = planner.build_home_session(30, ["core", "back"])
with get_db() as db:
    gs = {db.execute("SELECT muscle_group FROM exercises WHERE id=?",
                     (eid,)).fetchone()["muscle_group"]
          for eid in geschont["exercise_ids"]}
ok("Bei Rückenschmerzen fällt der Rücken weg", "back" not in gs, str(gs))
ok("… und es kommt trotzdem eine Einheit heraus",
   len(geschont["exercise_ids"]) >= 2, str(len(geschont["exercise_ids"])))
ok("… und das wird gesagt", geschont.get("adapted") is not None)

# Warmlaufen und Ausklang gehören dazu.
ok("Die Einheit beginnt mit Aufwärmen", s["steps"][0]["type"] == "warmup")
ok("… und endet mit Dehnen", s["steps"][-1]["type"] == "cooldown")

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Tests bestanden.")
