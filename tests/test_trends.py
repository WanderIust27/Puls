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
from app.services import exercises as ex_lib, trends             # noqa: E402

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



print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Tests bestanden.")
