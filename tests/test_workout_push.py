"""Tests fuer die Workouts, die an die Uhr gehen.

Garmin prueft die Uebungskategorie gegen die Sportart des Workouts und lehnt
bei einem Missklang das GANZE Workout ab ("400 - invalid category"). Genau das
passierte, als ausgleichende Yoga-Stellungen an eine Krafteinheit angehaengt
wurden. Diese Tests halten den Fall fest.

Aufruf:  python3 tests/test_workout_push.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import init_db                                       # noqa: E402
from app.services import exercises as ex_lib                     # noqa: E402
from app.services import mood, planner, workout_builder as wb    # noqa: E402

failures = []


def ok(name, condition, detail=""):
    print(f"{'OK  ' if condition else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def flatten(steps):
    """Alle Schritte, auch die in Wiederholungsgruppen."""
    out = []
    for s in steps:
        out.append(s)
        out.extend(flatten(s.get("workoutSteps", [])))
    return out


init_db()

# --- Die Regel selbst ----------------------------------------------------
yoga_step = {"type": "cooldown", "name": "Kindhaltung", "duration_s": 60,
             "garmin_category": "YOGA", "garmin_exercise": "CHILDS_POSE"}

as_strength = wb._build_step(dict(yoga_step), [1], "strength")
ok("Yoga-Kategorie faellt in der Krafteinheit weg",
   "category" not in as_strength, str(as_strength.get("category")))
ok("Der Schritt bleibt trotzdem benannt",
   "Kindhaltung" in (as_strength.get("description") or ""))
ok("… und behaelt seine Dauer", as_strength.get("endConditionValue") == 60)

as_yoga = wb._build_step(dict(yoga_step), [1], "mobility")
ok("In der Yogaeinheit bleibt die Kategorie",
   as_yoga.get("category") == "YOGA" and as_yoga.get("exerciseName") == "CHILDS_POSE")

squat = {"type": "work", "name": "Kniebeuge", "reps": 8,
         "garmin_category": "SQUAT", "garmin_exercise": "BARBELL_BACK_SQUAT"}
ok("Passende Kraftkategorie bleibt erhalten",
   wb._build_step(dict(squat), [1], "strength").get("category") == "SQUAT")

# Eine Sportart ohne Liste wird nicht eingeschraenkt.
ok("Unbekannte Sportart wird nicht beschnitten",
   wb._build_step(dict(squat), [1], "cardio").get("category") == "SQUAT")

# --- Die ganze Krafteinheit mit Beschwerde -------------------------------
# Rueckenschmerzen melden: der Planer haengt ausgleichende Stellungen an.
mood.record({"mood": 3, "energy": 3, "stress": 3,
             "note": "Rückenschmerzen seit gestern",
             "complaints": [{"region": "back_low", "kind": "pain", "severity": 3}]})
adapt = mood.adaptations()
ok("Die Beschwerde ist angekommen", bool(adapt["complaints"]))
ok("Ausgleichende Stellungen werden vorgeschlagen", bool(adapt["relief_poses"]),
   ", ".join(adapt["relief_poses"][:3]))

session = planner.build_gym_session(45)
pose_names = {p["name"] for p in ex_lib.EVENING_YOGA_POOL}
appended = [s for s in session["steps"] if s.get("name") in pose_names]
ok("Die Dehnung haengt an der Krafteinheit", bool(appended))
ok("… und traegt keine Yoga-Kategorie im Rohplan",
   all("garmin_category" not in s for s in appended))

dto = wb.build_garmin_workout(session["name"], session["sport"], session["steps"],
                              session.get("description"))
steps = flatten(dto["workoutSegments"][0]["workoutSteps"])
allowed = wb.ALLOWED_CATEGORIES["strength"]
bad = [s for s in steps if s.get("category") and s["category"] not in allowed]
ok("Kein Schritt der Krafteinheit hat eine unzulaessige Kategorie",
   not bad, ", ".join(f"{s.get('description')}={s['category']}" for s in bad))
ok("Die Einheit hat ueberhaupt Schritte", len(steps) > 5, f"{len(steps)} Schritte")
ok("Die Sportart ist Kraft",
   dto["sportType"]["sportTypeKey"] in ("strength_training", "strength"))

# Die Dehnung darf durch die Kuerzung nicht namenlos werden.
named = [s for s in steps if s.get("description")]
ok("Jeder Kuehlschritt bleibt benannt", len(named) >= len(appended))

# --- Die Abendeinheit darf ihre Stellungen behalten ----------------------
yoga = planner.build_evening_yoga(12)
ydto = wb.build_garmin_workout(yoga["name"], yoga["sport"], yoga["steps"])
ysteps = flatten(ydto["workoutSegments"][0]["workoutSteps"])
with_cat = [s for s in ysteps if s.get("category")]
ok("Die Yogaeinheit behaelt Stellungen", bool(with_cat), f"{len(with_cat)} Stellungen")
ok("… und nur erlaubte",
   all(s["category"] in wb.ALLOWED_CATEGORIES.get(yoga["sport"], set())
       for s in with_cat))

# --- Kein Workout darf eine fremde Kategorie tragen ----------------------
# Gegenprobe ueber die Uebungsbibliothek: was der Namensabgleich findet, muss
# in der Krafteinheit ebenfalls durch die Pruefung gehen.
for pose in ex_lib.EVENING_YOGA_POOL[:5]:
    step = {"type": "cooldown", "name": pose["name"], "duration_s": 40}
    built = wb._build_step(step, [1], "strength")
    if built.get("category") and built["category"] not in allowed:
        failures.append("Bibliothekstreffer")
        print(f"FAIL Bibliothekstreffer: {pose['name']} → {built['category']}")
        break
else:
    print("OK   Namensabgleich liefert keine fremde Kategorie")

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Tests bestanden.")
