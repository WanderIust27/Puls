"""Tests fuer die Auswertung einer Krafteinheit.

Aufruf:  python3 tests/test_gym_analysis.py
"""
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db          # noqa: E402
from app.services import gym_analysis       # noqa: E402

failures = []


def check(name, actual, expected, tol=0.01):
    ok = (abs(actual - expected) <= tol) if isinstance(expected, (int, float)) \
        and isinstance(actual, (int, float)) and not isinstance(expected, bool) \
        else actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


init_db()
today = dt.date.today().isoformat()
last_week = (dt.date.today() - dt.timedelta(days=7)).isoformat()

with get_db() as db:
    db.execute("INSERT INTO activities(source, name, sport, start_time, duration_s) "
               "VALUES('garmin','Gym','strength',?,4500)", (today + "T18:00:00",))
    act_id = db.execute("SELECT id FROM activities").fetchone()["id"]
    ex = {}
    for name, group in (("Testgerät Beine", "legs"), ("Testgerät Rücken", "back"),
                        ("Testgerät Schulter", "shoulders")):
        db.execute("INSERT INTO exercises(name, muscle_group, equipment, slot) "
                   "VALUES(?,?,'machine','main')", (name, group))
        ex[name] = db.execute("SELECT id FROM exercises WHERE name=?", (name,)).fetchone()["id"]

    def add(name, day, sets, activity=None):
        for i, (reps, weight, feeling) in enumerate(sets, start=1):
            db.execute("""INSERT INTO exercise_sets(exercise_id, activity_id, day,
                          set_index, reps, weight_kg, feeling, source)
                          VALUES(?,?,?,?,?,?,?, 'garmin')""",
                       (ex[name], activity, day, i, reps, weight, feeling))

    # Letzte Woche
    add("Testgerät Beine", last_week, [(12, 80, None), (12, 80, None), (11, 80, None)])
    add("Testgerät Rücken", last_week, [(12, 45, None), (12, 45, None), (12, 45, None)])
    add("Testgerät Schulter", last_week, [(10, 25, None), (9, 25, None)])
    # Heute: Beinpresse schwerer, Latzug gleich (aber leicht), Schulter schwer
    add("Testgerät Beine", today, [(12, 85, None), (12, 85, None), (12, 85, None)], act_id)
    add("Testgerät Rücken", today, [(12, 45, "easy"), (12, 45, "easy"), (12, 45, "easy")], act_id)
    add("Testgerät Schulter", today, [(8, 25, "hard"), (7, 25, "hard")], act_id)

r = gym_analysis.analyse(act_id, today)
check("Einheit ausgewertet", r is not None, True)
check("Saetze gezaehlt", r["sets"], 8)
check("Uebungen gezaehlt", r["exercises"], 3)
# 3*12*85 + 3*12*45 + 8*25 + 7*25 = 3060 + 1620 + 200 + 175
check("Volumen gerechnet", r["volume_kg"], 5055.0)
check("Muskelgruppen aufgeschluesselt", set(r["muscle_groups"]),
      {"legs", "back", "shoulders"})

beine = [e for e in r["detail"] if e["name"] == "Testgerät Beine"][0]
check("Steigerung erkannt", beine["change"]["kind"], "weight")
check("Steigerung beziffert", beine["change"]["delta"], 5.0)
check("Als Fortschritt gefuehrt", "Testgerät Beine" in r["improved"], True)

ruecken = [e for e in r["detail"] if e["name"] == "Testgerät Rücken"][0]
check("Unveraenderte Uebung erkannt", ruecken["change"]["kind"], "hold")
check("Leichte Saetze gezaehlt", ruecken["easy"], 3)

schulter = [e for e in r["detail"] if e["name"] == "Testgerät Schulter"][0]
check("Rueckgang erkannt", schulter["change"]["kind"], "reps_down")
check("Schwere Saetze gezaehlt", schulter["hard"], 2)

texts = " ".join(t["text"] for t in r["tips"])
check("Hinweis zur zu leichten Uebung", "Testgerät Rücken" in texts, True)
check("Hinweis zur schweren Uebung", "Testgerät Schulter" in texts, True)
check("Hinweise sind nicht leer", len(r["tips"]) > 0, True)

# Ohne Saetze darf nichts behauptet werden
with get_db() as db:
    db.execute("INSERT INTO activities(source, name, sport, start_time) "
               "VALUES('manual','Leer','strength','2020-01-01T10:00:00')")
    empty_id = db.execute("SELECT id FROM activities WHERE name='Leer'").fetchone()["id"]
check("Einheit ohne Saetze liefert nichts",
      gym_analysis.analyse(empty_id, "2020-01-01"), None)

if failures:
    print(f"\n{len(failures)} Test(s) fehlgeschlagen:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\nAlle Gym-Tests bestanden.")
