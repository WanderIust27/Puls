"""Tests fuer die Tagesempfehlung.

Der Kern: Die Entscheidung muss aus den Daten folgen und nicht aus Laune. Wer
erschoepft ist, bekommt keine harte Einheit; wer vier Wochen keine Beine
gemacht hat, bekommt Beine; und jede Empfehlung nennt ihren Grund.

Aufruf:  python3 tests/test_today.py
"""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db, set_setting                      # noqa: E402
from app.services import today as td                                 # noqa: E402

failures = []


def check(name, actual, expected):
    ok_ = actual == expected
    print(f"{'OK  ' if ok_ else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok_:
        failures.append(name)


def ok(name, condition, detail=""):
    print(f"{'OK  ' if condition else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(name)


init_db()
# Die Tage werden relativ zu heute gewaehlt, nicht fest gesetzt: Beschwerden
# verfallen nach wenigen Tagen, ein fest verdrahtetes Datum waere je nach
# Testlauf mal frisch und mal abgelaufen.
WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
GYM_DAY = dt.date.today()
RUN_DAY = GYM_DAY - dt.timedelta(days=1)
set_setting("gym_days", json.dumps([WEEKDAYS[GYM_DAY.weekday()]]))
set_setting("run_days", json.dumps([WEEKDAYS[RUN_DAY.weekday()]]))


def clear():
    with get_db() as db:
        db.execute("DELETE FROM daily_metrics")
        db.execute("DELETE FROM mood_entries")
        db.execute("DELETE FROM planned_workouts")


def vitals(day, **fields):
    keys = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    with get_db() as db:
        db.execute(f"INSERT OR REPLACE INTO daily_metrics(day, {keys}) "
                   f"VALUES(?, {marks})", (day.isoformat(), *fields.values()))


def baseline(day, rhr=54, n=20):
    for i in range(4, 4 + n):
        vitals(day - dt.timedelta(days=i), resting_hr=rhr)


# ------------------------------------------------------- Die Belastbarkeit

clear()
ok("Ohne Daten keine Zahl", td.readiness(GYM_DAY)["score"] is None)
ok("… aber ein Hinweis, was fehlt", bool(td.readiness(GYM_DAY)["hint"]))

clear()
baseline(GYM_DAY)
vitals(GYM_DAY, training_readiness=82, hrv_avg=62, hrv_baseline_low=45,
       hrv_baseline_high=65, sleep_seconds=8 * 3600, resting_hr=51,
       body_battery_wake=90)
fit = td.readiness(GYM_DAY)
ok("Gute Werte ergeben eine hohe Zahl", fit["score"] >= 72, str(fit["score"]))
check("… und ein Wort dafür", fit["label"], "erholt")
ok("Jedes Signal nennt seinen Messwert",
   all(p["detail"] for p in fit["parts"]), str(len(fit["parts"])))

clear()
baseline(GYM_DAY)
vitals(GYM_DAY, training_readiness=18, hrv_avg=30, hrv_baseline_low=45,
       hrv_baseline_high=65, sleep_seconds=4 * 3600, resting_hr=63,
       body_battery_wake=25)
tired = td.readiness(GYM_DAY)
ok("Schlechte Werte ergeben eine niedrige Zahl", tired["score"] < 35, str(tired["score"]))
check("… und heissen so", tired["label"], "leer")

# Ein einzelnes Signal darf die Zahl nicht allein bestimmen.
clear()
vitals(GYM_DAY, sleep_seconds=8 * 3600)
only_sleep = td.readiness(GYM_DAY)
ok("Ein einziges Signal reicht für eine Zahl", only_sleep["score"] is not None,
   str(only_sleep["score"]))
check("… und wird als einziges ausgewiesen", len(only_sleep["parts"]), 1)


# --------------------------------------------------------- Die Entscheidung

clear()
baseline(GYM_DAY)
vitals(GYM_DAY, training_readiness=15, hrv_avg=28, hrv_baseline_low=45,
       hrv_baseline_high=65, sleep_seconds=4 * 3600, resting_hr=64,
       body_battery_wake=20)
rest = td.decide(GYM_DAY)
check("Erschöpft heisst Pause — auch am Gym-Tag", rest["kind"], "rest")
check("… und das steht so da", rest["intensity"], "ruhe")
ok("… mit Begründung", any("Belastbarkeit" in r["label"] for r in rest["reasons"]))

clear()
baseline(GYM_DAY)
vitals(GYM_DAY, training_readiness=85, hrv_avg=64, hrv_baseline_low=45,
       hrv_baseline_high=65, sleep_seconds=8 * 3600, resting_hr=50,
       body_battery_wake=92)
gym = td.decide(GYM_DAY)
check("Der Gym-Tag bringt Krafttraining", gym["kind"], "gym")
check("… und erholt heisst hart", gym["intensity"], "hart")
ok("… mit einem Schwerpunkt", bool(gym["focus"]), str(gym["focus_labels"]))
ok("… und dem Wochentag als Grund",
   any("Gym-Tag" in r["label"] for r in gym["reasons"]),
   str([r["label"] for r in gym["reasons"]]))

clear()
baseline(RUN_DAY)
vitals(RUN_DAY, training_readiness=80, hrv_avg=60, hrv_baseline_low=45,
       hrv_baseline_high=65, sleep_seconds=7.5 * 3600, resting_hr=52,
       body_battery_wake=88)
run = td.decide(RUN_DAY)
check("Der Lauftag bringt einen Lauf", run["kind"], "run")

# Mittelmaessige Werte erlauben eine Einheit, aber keine harte.
clear()
baseline(GYM_DAY)
vitals(GYM_DAY, training_readiness=45, hrv_avg=44, hrv_baseline_low=45,
       hrv_baseline_high=65, sleep_seconds=5.5 * 3600, resting_hr=57,
       body_battery_wake=48)
soft = td.decide(GYM_DAY)
check("Angeschlagen heisst leicht", soft["intensity"], "leicht")
ok("… und kürzer", soft["minutes"] < gym["minutes"],
   f"{soft['minutes']} < {gym['minutes']}")

# Was im Plan steht, geht vor.
clear()
baseline(GYM_DAY)
vitals(GYM_DAY, training_readiness=80, sleep_seconds=8 * 3600, resting_hr=52)
with get_db() as db:
    db.execute("""INSERT INTO planned_workouts(name, sport, planned_date, steps_json)
                  VALUES('Langer Lauf','running',?,'{}')""", (GYM_DAY.isoformat(),))
planned = td.decide(GYM_DAY)
check("Der Plan geht vor dem Wochentag", planned["kind"], "run")
ok("… und sagt es", any("Plan" in r["label"] for r in planned["reasons"]))


# ---------------------------------------------------------- Die Beschwerde

clear()
baseline(GYM_DAY)
vitals(GYM_DAY, training_readiness=85, hrv_avg=64, hrv_baseline_low=45,
       hrv_baseline_high=65, sleep_seconds=8 * 3600, resting_hr=50,
       body_battery_wake=92)
with get_db() as db:
    db.execute("""INSERT INTO mood_entries(day, recorded_at, mood, energy, complaints)
                  VALUES(?,?,4,4,?)""",
               (GYM_DAY.isoformat(), GYM_DAY.isoformat() + "T08:00:00",
                json.dumps([{"region": "knee", "kind": "pain", "severity": 3}])))
hurt = td.decide(GYM_DAY)
ok("Schmerz drosselt die Einheit", hurt["intensity"] == "leicht", hurt["intensity"])
ok("… und wird benannt",
   any("Beschwerden" in r["label"] for r in hurt["reasons"]),
   str([r["label"] for r in hurt["reasons"]]))
ok("Die betroffene Gruppe fällt aus dem Schwerpunkt",
   "legs" not in hurt["focus"], str(hurt["focus"]))


# ------------------------------------------------------------ Die Einheit

clear()
baseline(GYM_DAY)
vitals(GYM_DAY, training_readiness=85, hrv_avg=64, hrv_baseline_low=45,
       hrv_baseline_high=65, sleep_seconds=8 * 3600, resting_hr=50,
       body_battery_wake=92)
rec = td.recommendation(GYM_DAY, phrase=False)
ok("Zur Empfehlung gehört eine Einheit", bool(rec["session"]),
   (rec["session"] or {}).get("name", ""))
ok("… mit Schritten", len(rec["session"]["steps"]) > 3,
   str(len(rec["session"]["steps"])))
check("Die genannte Dauer ist die der Einheit", rec["minutes"],
      int(rec["session"]["minutes"]))
ok("Es gibt einen Satz dazu", len(rec["plain"]) > 30, rec["plain"])
ok("Und eine Überschrift", bool(rec["headline"]), rec["headline"])

# Pause heisst Pause: keine Einheit, aber ein Satz.
clear()
baseline(GYM_DAY)
vitals(GYM_DAY, training_readiness=10, hrv_avg=25, hrv_baseline_low=45,
       hrv_baseline_high=65, sleep_seconds=3.5 * 3600, resting_hr=66,
       body_battery_wake=15)
pause = td.recommendation(GYM_DAY, phrase=False)
check("Pause hat keine Einheit", pause["session"], None)
ok("… aber einen Satz", "Heute nichts" in pause["plain"], pause["plain"])


# Was heute schon war, steht nicht noch einmal an.
clear()
baseline(GYM_DAY)
vitals(GYM_DAY, training_readiness=85, hrv_avg=64, hrv_baseline_low=45,
       hrv_baseline_high=65, sleep_seconds=8 * 3600, resting_hr=50,
       body_battery_wake=92)
with get_db() as db:
    db.execute("DELETE FROM exercise_sets")
    db.execute("""INSERT INTO exercise_sets(exercise_id, day, set_index, reps,
                      weight_kg, source)
                  SELECT id, ?, 1, 12, 40, 'manual' FROM exercises LIMIT 1""",
               (GYM_DAY.isoformat(),))
already = td.decide(GYM_DAY)
check("Erledigtes wird nicht wiederholt", already["kind"], "done")
ok("… und die Begründung widerspricht sich nicht",
   not any("Gym-Tag" in r["label"] for r in already["reasons"]),
   str([r["label"] for r in already["reasons"]]))
with get_db() as db:
    db.execute("DELETE FROM exercise_sets")


# ------------------------------------------------------------------- Last

clear()
with get_db() as db:
    for i in range(1, 4):
        db.execute("""INSERT INTO activities(source, sport, start_time, training_load)
                      VALUES('garmin','running',?,100)""",
                   ((GYM_DAY - dt.timedelta(days=i)).isoformat() + "T07:00:00",))
worked = td.load(GYM_DAY)
check("Tage seit dem letzten Lauf", worked["days_since_run"], 1)
ok("Aus drei Einheiten wird kein Belastungsverhältnis", worked["acwr"] is None,
   str(worked["acwr"]))

with get_db() as db:
    for i in range(4, 24):
        db.execute("""INSERT INTO activities(source, sport, start_time, training_load)
                      VALUES('garmin','running',?,100)""",
                   ((GYM_DAY - dt.timedelta(days=i)).isoformat() + "T07:00:00",))
worked = td.load(GYM_DAY)
ok("Mit genug Einheiten schon", worked["acwr"] is not None, str(worked["acwr"]))
ok("… und im gewohnten Rahmen", 0.8 <= worked["acwr"] <= 1.4, str(worked["acwr"]))

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Tests der Tagesempfehlung bestanden.")
