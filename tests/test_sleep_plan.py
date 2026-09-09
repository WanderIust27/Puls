"""Tests für die Schlafenszeit-Empfehlung und die Satz-Platzhalter.

Zwei Dinge, die aus demselben Grund zusammengehören: Beide rechnen rückwärts
aus Daten, die auch fehlen oder Unsinn enthalten können. Ein Platzhalter, der
wie ein Messwert aussieht (-1 Wiederholungen), war der teuerste Fehler davon.

Aufruf:  python3 tests/test_sleep_plan.py
"""
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db, set_setting                 # noqa: E402
from app.services import exercises as ex_lib, sleep             # noqa: E402

failures = []


def ok(name, condition, detail=""):
    print(f"{'OK  ' if condition else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def check(name, actual, expected):
    ok(name, actual == expected, f"{actual!r} (erwartet {expected!r})")


init_db()
ex_lib.seed_default_exercises()
TODAY = dt.date.today()

# --- Garmins -1 darf nie als Messwert durchgehen -------------------------
with get_db() as db:
    leg = db.execute("SELECT id, weight_kg FROM exercises "
                     "WHERE muscle_group='legs' LIMIT 1").fetchone()
plan_before = leg["weight_kg"]

for i in range(3):
    ex_lib.record_set(leg["id"], reps=-1, weight_kg=100.0,
                      day=TODAY.isoformat(), set_index=i + 1, source="garmin")
with get_db() as db:
    stored = db.execute("SELECT reps, weight_kg FROM exercise_sets "
                        "WHERE exercise_id=?", (leg["id"],)).fetchall()
check("Drei Sätze gespeichert", len(stored), 3)
ok("Aus -1 wird eine Lücke, keine Zahl",
   all(r["reps"] is None for r in stored), str([r["reps"] for r in stored]))
ok("Das Gewicht bleibt erhalten",
   all(r["weight_kg"] == 100.0 for r in stored))

result = ex_lib.apply_progression(leg["id"], TODAY.isoformat())
with get_db() as db:
    after = db.execute("SELECT weight_kg, fail_streak FROM exercises WHERE id=?",
                       (leg["id"],)).fetchone()
ok("Ohne gezählte Wiederholungen wird das Gewicht übernommen",
   after["weight_kg"] == 100.0, f"{plan_before} -> {after['weight_kg']}")
check("Kein Fehlversuch gezählt", after["fail_streak"], 0)
ok("… und das wird begründet", "nachgezogen" in (result or {}).get("reason", ""),
   (result or {}).get("reason", ""))

# Auch positive Werte müssen weiter funktionieren.
with get_db() as db:
    db.execute("DELETE FROM exercise_sets")
    db.execute("UPDATE exercises SET weight_kg=80, target_reps=10, fail_streak=0 "
               "WHERE id=?", (leg["id"],))
for i in range(3):
    ex_lib.record_set(leg["id"], reps=12, weight_kg=85.0,
                      day=TODAY.isoformat(), set_index=i + 1)
ex_lib.apply_progression(leg["id"], TODAY.isoformat())
with get_db() as db:
    after = db.execute("SELECT weight_kg FROM exercises WHERE id=?",
                       (leg["id"],)).fetchone()
ok("Tatsächlich bewegtes Gewicht schlägt die alte Vorgabe",
   after["weight_kg"] >= 85.0, f"{after['weight_kg']} kg")

# Null und negative Gewichte gehören ebenfalls nicht in die Datenbank.
ex_lib.record_set(leg["id"], reps=8, weight_kg=-5, duration_s=-3,
                  day=TODAY.isoformat(), set_index=9)
with get_db() as db:
    junk = db.execute("SELECT weight_kg, duration_s FROM exercise_sets "
                      "WHERE set_index=9").fetchone()
ok("Negatives Gewicht wird zur Lücke", junk["weight_kg"] is None)
ok("Negative Dauer wird zur Lücke", junk["duration_s"] is None)

# --- Schlafenszeit -------------------------------------------------------
set_setting("wake_target", "06:30")
bare = sleep.tonight()
ok("Ohne Nächte trotzdem eine Empfehlung", bool(bare["bedtime"]), bare["bedtime"])
check("Aufstehziel wird übernommen", bare["wake_target"], "06:30")
ok("Vorgabewert fürs Einschlafen", bare["fall_asleep_measured"] is False)

with get_db() as db:
    for d in range(1, 25):
        day = TODAY - dt.timedelta(days=d)
        start = dt.datetime.combine(day - dt.timedelta(days=1), dt.time(23, 15))
        end = start + dt.timedelta(hours=7.5)
        db.execute("""INSERT INTO daily_metrics(day, sleep_seconds, sleep_start,
                          sleep_end, sleep_awake_s, hrv_avg, resting_hr,
                          training_readiness)
                      VALUES(?,?,?,?,?,?,?,?)""",
                   (day.isoformat(), 7.5 * 3600 - 1200,
                    str(int(start.timestamp() * 1000)),
                    str(int(end.timestamp() * 1000)), 300, 58, 48, 70))

t = sleep.tonight()
ok("Einschlafdauer aus eigenen Nächten", t["fall_asleep_measured"],
   f"{t['fall_asleep_min']} min")
ok("… und plausibel", 5 <= t["fall_asleep_min"] <= 45, str(t["fall_asleep_min"]))

# Die Rechnung muss aufgehen: Zubettgehen + Einschlafen + Schlaf = Aufstehen.
bed_h, bed_m = (int(x) for x in t["bedtime"].split(":"))
bed = bed_h + bed_m / 60
wake = 6 + 30 / 60
total = (wake + 24 - bed) % 24
expected = t["need_hours"] + t["fall_asleep_min"] / 60
ok("Zubettgehen + Einschlafen + Schlaf ergibt das Aufstehziel",
   abs(total - expected) < 0.05, f"{total:.2f} h statt {expected:.2f} h")

ok("Übliche Zeit wird erkannt", t["usual_bedtime"] is not None, str(t["usual_bedtime"]))
ok("Regelmäßigkeit wird gemessen",
   t["regularity"]["bedtime_spread_h"] is not None,
   str(t["regularity"]["bedtime_spread_h"]))
ok("Bei immer gleicher Zeit ist die Schwankung klein",
   t["regularity"]["bedtime_spread_h"] < 0.3,
   str(t["regularity"]["bedtime_spread_h"]))
ok("Ein Hinweis wird formuliert", bool(t["note"]), t["note"][:70])

# Ein späteres Aufstehziel muss die Zubettgehzeit nach hinten schieben.
set_setting("wake_target", "08:00")
later = sleep.tonight()
b1 = sum(x * y for x, y in zip((int(v) for v in t["bedtime"].split(":")), (1, 1 / 60)))
b2 = sum(x * y for x, y in zip((int(v) for v in later["bedtime"].split(":")), (1, 1 / 60)))
ok("Später aufstehen heißt später ins Bett",
   abs((b2 - b1) - 1.5) < 0.1, f"{t['bedtime']} -> {later['bedtime']}")

# Schlechte Erholung muss mehr Schlaf ergeben, nicht weniger.
base_need = later["need_hours"]
with get_db() as db:
    db.execute("UPDATE daily_metrics SET training_readiness=30, hrv_avg=40 "
               "WHERE day=?", ((TODAY - dt.timedelta(days=1)).isoformat(),))
tired = sleep.tonight()
ok("Schlechte Erholung erhöht den Bedarf", tired["need_hours"] >= base_need,
   f"{base_need} -> {tired['need_hours']}")
ok("… und nennt den Grund", bool(tired["need_reasons"]),
   "; ".join(tired["need_reasons"]))
ok("Der Bedarf bleibt in sinnvollen Grenzen",
   sleep.MIN_NEED_H <= tired["need_hours"] <= sleep.MAX_NEED_H)

# Unsinnige Uhrzeit darf nicht durchschlagen.
set_setting("wake_target", "quatsch")
ok("Kaputtes Aufstehziel fällt auf die Vorgabe zurück",
   sleep.tonight()["wake_target"] == "06:30", sleep.tonight()["wake_target"])

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Tests bestanden.")
