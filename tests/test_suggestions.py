"""Tests fuer die Coach-Vorschlaege.

Der Punkt: Loest die Regel wirklich aus, wenn die Lage danach ist — und
schweigt sie, wenn alles passt? Und wird aus einem uebernommenen Vorschlag
tatsaechlich ein Workout?

Aufruf:  python3 tests/test_suggestions.py
"""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db, set_setting     # noqa: E402
from app.services import planner, suggestions       # noqa: E402

failures = []


def check(name, actual, expected, tol=0.01):
    ok = (abs(actual - expected) <= tol) if isinstance(expected, (int, float)) \
        and isinstance(actual, (int, float)) and not isinstance(expected, bool) \
        else actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


init_db()


def add_run(days_ago, minutes, distance_m, zones=None):
    day = (dt.date.today() - dt.timedelta(days=days_ago)).isoformat()
    with get_db() as db:
        db.execute("""INSERT INTO activities(source,name,sport,start_time,
                      duration_s,distance_m,avg_hr,hr_zones_json)
                      VALUES('garmin','Lauf','running',?,?,?,148,?)""",
                   (day + "T07:00:00", minutes * 60, distance_m,
                    json.dumps(zones) if zones else None))


def clear_suggestions():
    with get_db() as db:
        db.execute("DELETE FROM coach_adaptations")


# --- Langer Lauf fehlt ----------------------------------------------------
for i in range(10):
    add_run(i + 1, 25, 4800, {"1": 300, "2": 1000, "3": 200, "4": 0, "5": 0})

suggestions.generate()
kinds = [s["kind"] for s in suggestions.list_open()]
check("Fehlender langer Lauf wird bemerkt", "long_run" in kinds, True)

long_run = [s for s in suggestions.list_open() if s["kind"] == "long_run"][0]
check("Vorschlag nennt einen Sonntag",
      dt.date.fromisoformat(long_run["payload"]["planned_date"]).weekday(), 6)
check("Vorschlag nennt seinen Anlass", bool(long_run["trigger"]), True)

# --- Übernehmen erzeugt ein echtes Workout -------------------------------
result = suggestions.apply(long_run["id"])
check("Workout wurde angelegt", "workout_id" in result, True)
with get_db() as db:
    w = db.execute("SELECT * FROM planned_workouts WHERE id=?",
                   (result["workout_id"],)).fetchone()
check("Workout ist ein Lauf", w["sport"], "running")
check("Workout hat ein Datum", w["planned_date"], long_run["payload"]["planned_date"])
check("Workout hat Schritte", len(json.loads(w["steps_json"])["steps"]) > 0, True)
check("Vom Coach angelegt", w["created_by"], "coach")
check("Vorschlag gilt als erledigt",
      [s["kind"] for s in suggestions.list_open()].count("long_run"), 0)
try:
    suggestions.apply(long_run["id"])
    check("Zweimal übernehmen wird abgelehnt", False, True)
except ValueError:
    check("Zweimal übernehmen wird abgelehnt", True, True)

# --- Mit langem Lauf schweigt die Regel ----------------------------------
clear_suggestions()
add_run(3, 55, 10500, {"1": 800, "2": 2200, "3": 300, "4": 0, "5": 0})
suggestions.generate()
check("Mit langem Lauf kein Vorschlag mehr",
      "long_run" in [s["kind"] for s in suggestions.list_open()], False)

# --- Keine Tempoeinheit --------------------------------------------------
check("Fehlende Tempoeinheit wird bemerkt",
      "tempo_run" in [s["kind"] for s in suggestions.list_open()], True)

clear_suggestions()
add_run(2, 30, 6000, {"1": 200, "2": 400, "3": 300, "4": 600, "5": 300})
suggestions.generate()
check("Mit harter Einheit kein Tempo-Vorschlag",
      "tempo_run" in [s["kind"] for s in suggestions.list_open()], False)

# --- Zu viel Intensität --------------------------------------------------
clear_suggestions()
with get_db() as db:
    db.execute("DELETE FROM activities")
for i in range(10):
    # Nur ein Drittel locker — das ist deutlich zu hart
    add_run(i + 1, 30, 6000, {"1": 100, "2": 500, "3": 700, "4": 500, "5": 0})
suggestions.generate()
check("Zu viel Intensität wird bemerkt",
      "too_hard" in [s["kind"] for s in suggestions.list_open()], True)

# --- Verworfene Vorschläge kommen nicht sofort wieder --------------------
open_now = suggestions.list_open()
victim = [s for s in open_now if s["kind"] == "too_hard"][0]
check("Verwerfen funktioniert", suggestions.dismiss(victim["id"]), True)
check("Zweites Verwerfen schlägt fehl", suggestions.dismiss(victim["id"]), False)
suggestions.generate()
check("Verworfener Vorschlag kommt nicht sofort wieder",
      "too_hard" in [s["kind"] for s in suggestions.list_open()], False)
check("Verworfenes steht im Verlauf",
      any(h["kind"] == "too_hard" for h in suggestions.history()), True)

# --- Vernachlässigte Muskelgruppe wirkt sich auf den Plan aus ------------
clear_suggestions()
with get_db() as db:
    db.execute("UPDATE exercises SET active=1")
    # Für alle Hauptgruppen ausser "back" kürzlich Sätze anlegen. Dann ist
    # genau eine Gruppe vernachlässigt — der Fall, um den es geht.
    recent = (dt.date.today() - dt.timedelta(days=2)).isoformat()
    rows = db.execute("""SELECT id, muscle_group FROM exercises
                         WHERE slot='main' AND active=1""").fetchall()
    seen = set()
    for r in rows:
        if r["muscle_group"] == "back" or r["muscle_group"] in seen:
            continue
        seen.add(r["muscle_group"])
        db.execute("""INSERT INTO exercise_sets(exercise_id, day, set_index,
                      reps, weight_kg, source) VALUES(?,?,1,12,40,'manual')""",
                   (r["id"], recent))

suggestions.generate()
neglected = [s for s in suggestions.list_open() if s["kind"] == "neglected"]
check("Vernachlässigte Gruppe wird erkannt", len(neglected), 1)
check("Die richtige Gruppe wird genannt",
      neglected[0]["payload"]["groups"], ["back"])

suggestions.apply(neglected[0]["id"])
check("Schwerpunkt ist hinterlegt", suggestions.active_focus(), ["back"])


def step_names(steps):
    """Übungen stecken in verschachtelten repeat-Schritten."""
    found = []
    for x in steps:
        if x.get("name"):
            found.append(x["name"])
        if isinstance(x.get("steps"), list):
            found += step_names(x["steps"])
    return found


with get_db() as db:
    back_names = {r["name"] for r in db.execute(
        "SELECT name FROM exercises WHERE muscle_group='back' AND slot='main'"
    ).fetchall()}

# Kurze Einheit: hier ist nicht für jede Muskelgruppe Platz. Genau dann muss
# sich zeigen, ob der Schwerpunkt etwas bewirkt.
short = planner.build_gym_session(minutes=45)
check("Kurze Einheit wurde gebaut", len(short["steps"]) > 3, True)
check("Rücken ist trotz knapper Zeit dabei",
      bool(back_names & set(step_names(short["steps"]))), True)

# Ohne Schwerpunkt zum Vergleich
set_setting("gym_focus_until", "")
plain = planner.build_gym_session(minutes=45)
check("Ohne Schwerpunkt wird normal geplant", len(plain["steps"]) > 3, True)

# --- Abgelaufener Schwerpunkt zählt nicht mehr ---------------------------
set_setting("gym_focus_groups", json.dumps(["legs"]))
set_setting("gym_focus_until",
            (dt.date.today() - dt.timedelta(days=1)).isoformat())
check("Abgelaufener Schwerpunkt wird ignoriert", suggestions.active_focus(), [])

# --- Unbekannter Vorschlag ------------------------------------------------
try:
    suggestions.apply(999999)
    check("Unbekannter Vorschlag wird abgelehnt", False, True)
except ValueError:
    check("Unbekannter Vorschlag wird abgelehnt", True, True)

if failures:
    print(f"\n{len(failures)} Test(s) fehlgeschlagen:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\nAlle Vorschlags-Tests bestanden.")
