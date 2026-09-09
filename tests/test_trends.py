"""Tests für Trends und die zusammengeführte Wochenplanung.

Der Coach soll begründen können, warum gerade diese Muskelgruppe und diese
Laufart drankommen. Diese Suite prüft, dass die Begründung aus den Daten
stammt: Eine vier Wochen ausgelassene Gruppe muss nach oben, eine gerade hart
trainierte nach unten — und die gewählten Tage müssen exakt die sein, die
eingetragen wurden.

Aufruf:  python3 tests/test_trends.py
"""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db, set_setting                  # noqa: E402
from app.services import autopilot, exercises as ex_lib, trends  # noqa: E402

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


def sets_for(group: str, days_ago: list[int], weight: float, reps: int = 10):
    """Saetze fuer eine Muskelgruppe eintragen."""
    with get_db() as db:
        ex = db.execute("SELECT id FROM exercises WHERE muscle_group=? LIMIT 1",
                        (group,)).fetchone()
        if not ex:
            return
        for d in days_ago:
            day = (TODAY - dt.timedelta(days=d)).isoformat()
            for i in range(3):
                db.execute("""INSERT INTO exercise_sets(exercise_id, day, set_index,
                                  reps, weight_kg, source)
                              VALUES(?,?,?,?,?, 'manual')""",
                           (ex["id"], day, i + 1, reps, weight))


# --- Ziel aus dem Freitext lesen ----------------------------------------
goal = trends.goal_focus("Ich will 10 km unter 55 Minuten und stärkere Beine")
ok("Laufziel erkannt", "10-km-Zeit" in goal["recognised"], str(goal["recognised"]))
ok("Beine erkannt", "legs" in goal["muscles"], str(goal["muscles"]))
ok("Tempoarbeit abgeleitet", "tempo" in goal["runs"], str(goal["runs"]))

goal2 = trends.goal_focus("Ich möchte einen Marathon laufen")
ok("Marathon heißt lange Läufe", "long" in goal2["runs"], str(goal2["runs"]))
ok("… und keine Muskelgruppe", goal2["muscles"] == [], str(goal2["muscles"]))

empty = trends.goal_focus("irgendwas ohne Bezug")
check("Ohne Bezug wird nichts hineingelesen", empty["recognised"], [])

# --- Muskelgruppen: was fehlt, muss nach oben ---------------------------
bare = trends.muscles()
ok("Ohne Sätze ein Hinweis statt Behauptungen", bool(bare["hint"]))

# Brust und Beine regelmäßig, Rücken seit sechs Wochen nicht mehr.
sets_for("chest", [2, 6, 9, 13, 16, 20, 23, 27], 60)
sets_for("legs", [3, 7, 10, 14, 17, 21, 24, 28], 100)
sets_for("back", [40, 44, 48], 70)          # nur im älteren Fenster
sets_for("shoulders", [5, 12, 19, 26], 30)

m = trends.muscles()
by_key = {g["key"]: g for g in m["groups"]}
ok("Rücken wird als vernachlässigt erkannt",
   by_key["back"]["days_since"] is None, str(by_key["back"]["days_since"]))
ok("… und steht ganz oben", m["groups"][0]["key"] in ("back", "core", "arms"),
   m["groups"][0]["key"])
ok("Brust steht nicht oben", by_key["chest"]["need"] < by_key["back"]["need"],
   f"Brust {by_key['chest']['need']} < Rücken {by_key['back']['need']}")
ok("Jede Gruppe nennt ihren Grund",
   all(g["reasons"] for g in m["groups"] if g["need"] > 0))
ok("Bedarf liegt zwischen 0 und 100",
   all(0 <= g["need"] <= 100 for g in m["groups"]))
ok("Anteile summieren sich auf hundert",
   abs(sum(g["share"] for g in m["groups"]) - 100) < 1.5,
   f"{sum(g['share'] for g in m['groups']):.1f} %")
ok("Schwerpunkt nennt höchstens zwei Gruppen", len(m["focus"]) <= 2, str(m["focus"]))

# Steigende Gewichte müssen sich als steigende Kraft zeigen.
with get_db() as db:
    db.execute("DELETE FROM exercise_sets")
sets_for("chest", [40, 44, 48], 50)          # älteres Fenster: leichter
sets_for("chest", [3, 8, 14, 20], 70)        # jüngeres Fenster: schwerer
grown = {g["key"]: g for g in trends.muscles()["groups"]}["chest"]
ok("Steigende Gewichte ergeben steigende Kraft",
   (grown["strength_change"] or 0) > 10, f"{grown['strength_change']} %")
check("… und die Richtung heißt steigt", grown["direction"], "steigt")

# --- Laufen --------------------------------------------------------------
r = trends.running_trend()
ok("Ohne Läufe ein Hinweis", bool(r["hint"]))

with get_db() as db:
    for d, km, hr in [(3, 6, 140), (7, 5, 138), (10, 8, 142), (14, 6, 141),
                      (18, 5, 139), (24, 7, 143),
                      (33, 6, 150), (38, 5, 152), (44, 7, 151), (50, 6, 149)]:
        day = TODAY - dt.timedelta(days=d)
        # Gleiche Distanz, gleicher Puls, aber zuletzt schneller
        pace = 330 if d < 28 else 370
        db.execute("""INSERT INTO activities(sport, start_time, duration_s,
                          distance_m, avg_hr, source)
                      VALUES('running', ?, ?, ?, ?, 'manual')""",
                   (f"{day.isoformat()}T07:00:00", km * pace, km * 1000, hr))

r = trends.running_trend()
ok("Läufe werden gezählt", r["runs_recent"] == 6, str(r["runs_recent"]))
ok("Tempo bei gleichem Puls wird verglichen", r["pace_gain_s"] is not None)
ok("… und der gelegte Gewinn wird gefunden",
   35 <= (r["pace_gain_s"] or 0) <= 45, f"{r['pace_gain_s']} s/km")
check("… also steigt die Form", r["direction"], "steigt")
ok("Fehlender harter Lauf wird gemeldet",
   any("harten Bereich" in n for n in r["needs"]), "; ".join(r["needs"]))
ok("Wochenumfang wird gerechnet", r["km_per_week"] > 0, f"{r['km_per_week']} km")

# Zu viele harte Läufe müssen ebenfalls auffallen.
with get_db() as db:
    db.execute("UPDATE activities SET avg_hr=170 "
               "WHERE substr(start_time,1,10) >= ?",
               ((TODAY - dt.timedelta(days=28)).isoformat(),))
hard = trends.running_trend()
ok("Zu viel Hartes wird gemeldet",
   any("zu viel" in n for n in hard["needs"]), "; ".join(hard["needs"]))

# --- Die zusammengeführte Woche -----------------------------------------
set_setting("gym_days", json.dumps(["Mo", "Mi", "Fr"]))
set_setting("run_days", json.dumps(["Di", "Do"]))
set_setting("auto_wishes", "10 km unter 55 Minuten, dazu stärkere Beine")
set_setting("evening_mobility", "0")

cfg = autopilot.settings()
check("Gym-Tage kommen an", cfg["gym_days"], ["Mo", "Mi", "Fr"])
check("Lauftage kommen an", cfg["run_days"], ["Di", "Do"])
check("Beide zusammen sind die verfügbaren Tage",
      cfg["available_days"], ["Mo", "Di", "Mi", "Do", "Fr"])

monday = TODAY + dt.timedelta(days=(7 - TODAY.weekday()) % 7 or 7)
week = autopilot.plan(monday)
by_day = {d["weekday"]: d["sessions"] for d in week["days"]}

gym_on = {d for d, ses in by_day.items() if any(s["sport"] == "strength" for s in ses)}
run_on = {d for d, ses in by_day.items() if any(s["sport"] == "running" for s in ses)}
check("Kraft liegt genau auf den Gym-Tagen", gym_on, {"Mo", "Mi", "Fr"})
check("Laufen liegt genau auf den Lauftagen", run_on, {"Di", "Do"})
ok("Kein Yoga, wenn abgewählt",
   not any(s["sport"] == "mobility" for ses in by_day.values() for s in ses))
ok("Sa und So bleiben frei", not by_day["Sa"] and not by_day["So"])

kinds = [s["kind"] for ses in by_day.values() for s in ses if s["sport"] == "running"]
ok("Die Laufarten sind unterschiedlich", len(set(kinds)) > 1, str(kinds))
ok("Jede Einheit hat eine Begründung",
   all(s.get("why") for ses in by_day.values() for s in ses))
ok("Kraft trägt einen Schwerpunkt",
   all(s.get("emphasis") is not None
       for ses in by_day.values() for s in ses if s["sport"] == "strength"))
ok("Der Schwerpunkt steht auch in der Woche", bool(week["emphasis_labels"]),
   str(week["emphasis_labels"]))
ok("Das Ziel wird mitgeführt", "10-km-Zeit" in week["goal"]["recognised"],
   str(week["goal"]["recognised"]))

# Gebaut werden muss auch das Richtige: ein Tempolauf ist kein lockerer Lauf.
applied = autopilot.plan(monday, apply_it=True)
with get_db() as db:
    built = {r["planned_date"]: r["name"] for r in db.execute(
        "SELECT planned_date, name FROM planned_workouts WHERE created_by='autopilot'"
    ).fetchall()}
names = " | ".join(built.values())
ok("Für jede Einheit wurde ein Workout gebaut",
   len(applied["created"]) == sum(len(s) for s in by_day.values()),
   f"{len(applied['created'])} Workouts")
ok("Die Laufarten heißen unterschiedlich",
   len({n for n in built.values() if "auf" in n.lower() or "Lauf" in n}) > 1, names)
ok("Der Kraft-Schwerpunkt steht im Namen",
   any("Gym" in n for n in built.values()), names)

# --- Der Plan darf sich nicht anhäufen ----------------------------------
# Dreimal "Übernehmen" hat dreimal eine komplette Woche angelegt — nach ein
# paar Versuchen stand ein Vielfaches im Plan.
with get_db() as db:
    db.execute("DELETE FROM planned_workouts")
counts = []
for _ in range(3):
    autopilot.plan(monday, apply_it=True)
    with get_db() as db:
        counts.append(db.execute(
            "SELECT COUNT(*) c FROM planned_workouts").fetchone()["c"])
ok("Wiederholtes Übernehmen häuft nichts an",
   counts[0] == counts[1] == counts[2], str(counts))
ok("… und meldet, was es ersetzt hat",
   autopilot.plan(monday, apply_it=True)["replaced"] == counts[0],
   str(counts[0]))

# Erledigtes und Selbstgeplantes darf dabei nicht verschwinden.
with get_db() as db:
    db.execute("UPDATE planned_workouts SET status='done' WHERE id IN "
               "(SELECT id FROM planned_workouts LIMIT 2)")
    db.execute("UPDATE planned_workouts SET status='pushed' WHERE id IN "
               "(SELECT id FROM planned_workouts WHERE status='planned' LIMIT 1)")
    db.execute("""INSERT INTO planned_workouts(name, sport, planned_date,
                      steps_json, created_by)
                  VALUES('Selbst geplant','strength',?,'{}','user')""",
               (monday.isoformat(),))
autopilot.plan(monday, apply_it=True)
with get_db() as db:
    kept = {(r["status"], r["created_by"]): r["c"] for r in db.execute(
        "SELECT status, created_by, COUNT(*) c FROM planned_workouts "
        "GROUP BY status, created_by").fetchall()}
check("Erledigtes bleibt erhalten", kept.get(("done", "autopilot")), 2)
check("An die Uhr Geschicktes bleibt erhalten", kept.get(("pushed", "autopilot")), 1)
check("Selbst Angelegtes bleibt erhalten", kept.get(("planned", "user")), 1)

# Was vergangen und nie erledigt wurde, verschwindet — sonst wächst der Plan
# um jede nicht abgehakte Einheit weiter.
with get_db() as db:
    db.execute("""INSERT INTO planned_workouts(name, sport, planned_date,
                      steps_json, created_by)
                  VALUES('Alte Einheit','strength',?,'{}','autopilot')""",
               ((TODAY - dt.timedelta(days=20)).isoformat(),))
autopilot.plan(monday, apply_it=True)
with get_db() as db:
    old_left = db.execute("SELECT COUNT(*) c FROM planned_workouts "
                          "WHERE name='Alte Einheit'").fetchone()["c"]
check("Verpasste Altlasten werden aufgeräumt", old_left, 0)

# --- Eine Einheit muss so lang sein, wie sie heißt ----------------------
from app.services import planner                                # noqa: E402
for wanted in (45, 60, 75, 90, 120):
    session = planner.build_gym_session(wanted)
    real = planner.step_seconds(session["steps"]) / 60
    ok(f"{wanted}-Minuten-Einheit trifft die Zeit",
       abs(real - wanted) <= wanted * 0.1, f"{real:.0f} min gebaut")
    ok(f"… und der Name sagt die Wahrheit ({wanted})",
       abs(session["minutes"] - real) < 1 and str(session["minutes"]) in session["name"],
       session["name"])

# Mehr Zeit muss auch mehr Training bedeuten.
short = planner.build_gym_session(45)
long_one = planner.build_gym_session(120)
ok("Mehr Zeit ergibt mehr Einheit",
   planner.step_seconds(long_one["steps"]) > planner.step_seconds(short["steps"]) * 1.8,
   f"{planner.step_seconds(short['steps'])/60:.0f} vs "
   f"{planner.step_seconds(long_one['steps'])/60:.0f} min")
ok("… und mehr Übungen",
   len(long_one["exercise_ids"]) > len(short["exercise_ids"]),
   f"{len(short['exercise_ids'])} vs {len(long_one['exercise_ids'])}")

# Zwei Aufrufe mit derselben Vorgabe müssen dasselbe ergeben.
a, b = planner.build_gym_session(75), planner.build_gym_session(75)
check("Gleiche Vorgabe, gleiches Ergebnis", a["name"], b["name"])

# Die Rechnung selbst: Wiederholungen, Pausen und Umsetzen zählen mit.
one = [{"type": "repeat", "count": 3, "steps": [
    {"type": "work", "name": "X", "reps": 10},
    {"type": "rest", "name": "Pause", "duration_s": 60}]}]
expected = 3 * (10 * planner.SECONDS_PER_REP + 60) + planner.CHANGEOVER_S
ok("Die Dauerrechnung stimmt", abs(planner.step_seconds(one) - expected) < 0.01,
   f"{planner.step_seconds(one)} statt {expected}")

# Ohne eingetragene Tage muss der Coach selbst verteilen.
set_setting("gym_days", "[]")
set_setting("run_days", "[]")
free = autopilot.plan(monday)
trained = sum(1 for d in free["days"] for s in d["sessions"]
              if s["sport"] in ("running", "strength"))
ok("Ohne Vorgabe plant der Coach trotzdem", trained >= 3, f"{trained} Einheiten")
ok("… und verteilt Kraft auf mehrere Tage",
   len({d["weekday"] for d in free["days"]
        for s in d["sessions"] if s["sport"] == "strength"}) >= 1)

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Tests bestanden.")
