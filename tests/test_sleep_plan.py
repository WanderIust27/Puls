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

# --- Was seit dem letzten Mal angepasst wurde ---------------------------
from app.services import gym_analysis, planner, vitals              # noqa: E402

changes = ex_lib.recent_changes(days=14)
ok("Anpassungen werden aufgelistet", bool(changes), f"{len(changes)} Einträge")
ok("Jede nennt Übung, Änderung und Grund",
   all(c["name"] and c["change"] and c["reason"] for c in changes))
ok("Je Übung nur die jüngste",
   len({c["exercise_id"] for c in changes}) == len(changes))
ok("Unveränderte tauchen nicht auf",
   all(c["action"] != "hold" for c in changes))
session = planner.build_gym_session(60)
ok("Die Einheit trägt den Hinweis mit sich",
   session["changes_note"] is None or "angepasst" in session["changes_note"],
   str(session["changes_note"])[:60])

# --- Der Vergleich zur letzten Einheit darf nicht wie ein Messwert klingen
with get_db() as db:
    db.execute("DELETE FROM exercise_sets")
    act = db.execute("INSERT INTO activities(sport, start_time, duration_s, source) "
                     "VALUES('strength', ?, 3600, 'manual')",
                     (TODAY.isoformat() + "T18:00:00",)).lastrowid
    ex_row = db.execute("SELECT id FROM exercises WHERE slot='main' LIMIT 1").fetchone()
for i in range(3):
    ex_lib.record_set(ex_row["id"], reps=16, weight_kg=60,
                      day=(TODAY - dt.timedelta(days=3)).isoformat(), set_index=i + 1)
for i in range(3):
    ex_lib.record_set(ex_row["id"], reps=15, weight_kg=60, day=TODAY.isoformat(),
                      set_index=i + 1, activity_id=act)
res = gym_analysis.analyse(act, TODAY.isoformat())
text = res["detail"][0]["change"]["text"]
ok("Weniger Wiederholungen werden als Vergleich benannt",
   text.startswith("1 Wiederholung weniger"), text)
ok("… und nicht als negative Zahl", not text.strip().startswith("-"), text)

# --- Laktatschwelle ------------------------------------------------------
set_setting("easy_pace_s_per_km", "330")
set_setting("tempo_pace_s_per_km", "285")
bare = vitals.threshold()
ok("Ohne Läufe ein Hinweis statt einer Zahl",
   bare["hr"] is None and bool(bare["hint"]))

with get_db() as db:
    for d in range(3, 40, 6):
        day = TODAY - dt.timedelta(days=d)
        db.execute("""INSERT INTO activities(sport, start_time, duration_s,
                          distance_m, avg_hr, source)
                      VALUES('running', ?, ?, 8000, 168, 'manual')""",
                   (day.isoformat() + "T07:00:00", 8 * 285))
t = vitals.threshold()
ok("Schwelle wird geschätzt", t["hr"] == 168, str(t["hr"]))
ok("… und die Herkunft benannt", "geschätzt" in (t["source"] or ""), t["source"])
ok("Vier Bereiche abgeleitet", len(t["zones"]) == 4)
ok("Die Bereiche steigen an",
   all(t["zones"][i]["to"] <= t["zones"][i + 1]["to"] for i in range(3)))
ok("Der Schwellenbereich enthält den Schwellenpuls",
   t["zones"][2]["from"] <= t["hr"] <= t["zones"][2]["to"],
   f"{t['zones'][2]['from']}–{t['zones'][2]['to']}")

set_setting("lthr_bpm", "175")
measured = vitals.threshold()
check("Der Wert der Uhr schlägt die Schätzung", measured["hr"], 175)
ok("… und wird als gemessen ausgewiesen", measured["measured"])

# --- Zielgewicht ---------------------------------------------------------
from app.services import body                                        # noqa: E402
import json as _json                                                 # noqa: E402
set_setting("body_height_cm", "184")
set_setting("goals", _json.dumps(["muscle", "weight_gain"]))
for d in range(90, -1, -1):
    day = TODAY - dt.timedelta(days=d)
    body.record({"weight_kg": 72.0 + (90 - d) * 0.02,
                 "measured_at": f"{day.isoformat()}T07:15:00"}, source="test")
g = body.goal()
ok("Ein Ziel wird vorgeschlagen", g["suggested_kg"] is not None, str(g["suggested_kg"]))
ok("Der Vorschlag liegt über dem Ist (Ziel: zunehmen)",
   g["suggested_kg"] > g["current_kg"], f"{g['current_kg']} -> {g['suggested_kg']}")
ok("Der Vorschlag bleibt im gesunden Bereich",
   g["healthy_range_kg"][0] <= g["suggested_kg"] <= g["healthy_range_kg"][1])
ok("Die Rate wird gerechnet", g["rate_kg_week"] is not None, str(g["rate_kg_week"]))
ok("… und stimmt mit der gelegten überein",
   abs(g["rate_kg_week"] - 0.14) < 0.03, f"{g['rate_kg_week']} kg/Woche")
ok("Eine Ankunft wird geschätzt", g["eta"] is not None, str(g["eta"]))
ok("… und liegt in der Zukunft", g["eta"] > TODAY.isoformat())
ok("Das Tempo wird eingeordnet", g["pace"] in
   ("passend", "zügig", "zu schnell", "gemächlich"), str(g["pace"]))

# Ein Ziel in der Gegenrichtung darf nicht als erreichbar gelten.
from app.db import set_setting as _set                                # noqa: E402
_set("weight_target_kg", "68")
back = body.goal()
ok("Ziel gegen die Richtung wird als solches erkannt",
   back["on_track"] is False, str(back["on_track"]))
ok("… und es wird keine Ankunft versprochen", back["eta"] is None)
ok("… sondern gesagt, dass es so nicht klappt",
   "anderen Richtung" in back["note"], back["note"][-60:])

# --- Vorschläge statt stiller Änderungen --------------------------------
with get_db() as db:
    db.execute("DELETE FROM exercise_sets")
    db.execute("DELETE FROM progression_proposals")
    heavy = db.execute("SELECT id FROM exercises WHERE slot='main' LIMIT 1").fetchone()["id"]
    db.execute("UPDATE exercises SET weight_kg=20, target_reps=15, rep_min=10, "
               "rep_max=15 WHERE id=?", (heavy,))
for i in range(3):
    ex_lib.record_set(heavy, reps=15, weight_kg=35, day=TODAY.isoformat(), set_index=i + 1)

made = ex_lib.propose_for_day(TODAY.isoformat())
p = next((m for m in made if m["exercise_id"] == heavy), None)
ok("Aus 35 statt 20 kg wird ein Vorschlag", p is not None)
if p:
    check("… mit dem tatsächlich bewegten Gewicht", p["to_weight"], 35.0)
    # Fünfzehn Wiederholungen sind mehr als die Schwelle — also gilt dieses
    # Gewicht ab jetzt bei zehn Wiederholungen.
    check("… und dem oberen Wiederholungsziel", p["to_reps"], 10)
    ok("… mit Beleg", "35 kg" in p["evidence"], p["evidence"])
    ok("… und Begründung", bool(p["reason"]))

with get_db() as db:
    unchanged = db.execute("SELECT weight_kg FROM exercises WHERE id=?",
                           (heavy,)).fetchone()
check("Solange nichts entschieden ist, bleibt die Vorgabe", unchanged["weight_kg"], 20.0)

open_now = ex_lib.open_proposals()
ok("Der Vorschlag ist offen", any(o["exercise_id"] == heavy for o in open_now))
pid = next(o["id"] for o in open_now if o["exercise_id"] == heavy)

# Zweimal auswerten darf keinen zweiten Vorschlag ergeben.
ex_lib.propose_for_day(TODAY.isoformat())
check("Kein doppelter Vorschlag",
      len([o for o in ex_lib.open_proposals() if o["exercise_id"] == heavy]), 1)

ex_lib.decide_proposal(pid, True)
with get_db() as db:
    after_accept = db.execute("SELECT weight_kg, target_reps, fail_streak "
                              "FROM exercises WHERE id=?", (heavy,)).fetchone()
check("Nach dem Übernehmen gilt der neue Wert", after_accept["weight_kg"], 35.0)
check("… und die neuen Wiederholungen", after_accept["target_reps"], 10)
ok("Ein übernommener Vorschlag ist nicht mehr offen",
   not any(o["id"] == pid for o in ex_lib.open_proposals()))
ok("Zweimal entscheiden geht nicht", ex_lib.decide_proposal(pid, True) is None)

# Ablehnen darf nichts ändern.
with get_db() as db:
    other = db.execute("SELECT id, weight_kg FROM exercises WHERE slot='main' "
                       "AND id != ? LIMIT 1", (heavy,)).fetchone()
before_decline = other["weight_kg"]
for i in range(3):
    ex_lib.record_set(other["id"], reps=25, weight_kg=before_decline,
                      day=TODAY.isoformat(), set_index=i + 1)
ex_lib.propose_for_day(TODAY.isoformat())
pid2 = next((o["id"] for o in ex_lib.open_proposals()
             if o["exercise_id"] == other["id"]), None)
ok("Auch mehr Wiederholungen ergeben einen Vorschlag", pid2 is not None)
if pid2:
    ex_lib.decide_proposal(pid2, False)
    with get_db() as db:
        still = db.execute("SELECT weight_kg FROM exercises WHERE id=?",
                           (other["id"],)).fetchone()
    check("Abgelehnt heißt unverändert", still["weight_kg"], before_decline)
    ok("… und der Vorschlag ist weg",
       not any(o["id"] == pid2 for o in ex_lib.open_proposals()))

# --- Das Fortschreibungsschema ------------------------------------------
# Schwerster Satz über der Schwelle → dieses Gewicht gilt, bei "oben" Wdh.
# Darunter → um den Abschlag zurück, bei "unten" Wdh.
def probe(saetze, target_w, target_r, rep_min=12, rep_max=18, inc=2.5):
    with get_db() as db:
        db.execute("DELETE FROM exercise_sets")
        db.execute("DELETE FROM progression_proposals")
        eid = db.execute("SELECT id FROM exercises WHERE slot='main' LIMIT 1"
                         ).fetchone()["id"]
        db.execute("""UPDATE exercises SET weight_kg=?, target_reps=?, rep_min=?,
                          rep_max=?, weight_increment=? WHERE id=?""",
                   (target_w, target_r, rep_min, rep_max, inc, eid))
    for i, (r, w) in enumerate(saetze):
        ex_lib.record_set(eid, reps=r, weight_kg=w, day=TODAY.isoformat(),
                          set_index=i + 1)
    made = ex_lib.propose_for_day(TODAY.isoformat())
    return (made[0] if made else None), eid


cfg = ex_lib._scheme()
check("Vorgabe: Schwelle", cfg["schwelle"], 10)
check("Vorgabe: oberes Ziel", cfg["oben"], 10)
check("Vorgabe: unteres Ziel", cfg["unten"], 15)
check("Vorgabe: Abschlag", cfg["runter_kg"], 5.0)

# Der gemeldete Fall: 15×25, 15×30, 15×35 bei einer Vorgabe von 22,5 × 16.
p, eid = probe([(15, 25), (15, 30), (15, 35)], 22.5, 16)
ok("Der schwerste Satz zählt, nicht der erste", p is not None)
if p:
    check("Das Gewicht des schwersten Satzes gilt", p["to_weight"], 35.0)
    check("… bei zehn Wiederholungen", p["to_reps"], 10)
    ok("… mit dem Satz als Beleg", "35 kg" in p["evidence"], p["evidence"])
    ex_lib.decide_proposal(ex_lib.open_proposals()[0]["id"], True)
    with get_db() as db:
        a = db.execute("SELECT weight_kg, target_reps, rep_min FROM exercises "
                       "WHERE id=?", (eid,)).fetchone()
    check("Übernommen steht es auch so da", a["weight_kg"], 35.0)
    check("… mit dem neuen Ziel", a["target_reps"], 10)
    ok("Die Spanne zieht mit, wenn das Ziel darunter liegt",
       a["rep_min"] <= 10, f"rep_min {a['rep_min']}")

# Zu schwer: zurück und mehr Wiederholungen.
p, _ = probe([(12, 30), (8, 40)], 35, 10)
ok("Zu schwer ergibt einen Rückschritt", p is not None)
if p:
    check("Fünf Kilo zurück vom schwersten Satz", p["to_weight"], 35.0)
    check("… und fünfzehn Wiederholungen", p["to_reps"], 15)

# Genau die Schwelle zählt noch als zu schwer ("mehr als zehn").
p, _ = probe([(10, 40)], 40, 10)
ok("Genau zehn ist nicht mehr als zehn", p and p["to_reps"] == 15,
   f"{p['to_reps'] if p else '–'}")
p, _ = probe([(11, 40)], 35, 12)
ok("Elf ist mehr als zehn", p and p["to_weight"] == 40.0 and p["to_reps"] == 10,
   f"{p['to_weight'] if p else '–'} kg × {p['to_reps'] if p else '–'}")

# Ohne gezählte Wiederholungen bleibt es bei der Gewichtsübernahme.
p, _ = probe([(None, 50)], 40, 10)
ok("Ohne Wiederholungen zählt das Gewicht",
   p and p["to_weight"] == 50.0, f"{p['to_weight'] if p else '–'}")

# Kein Gewicht darf unter null rutschen.
p, _ = probe([(6, 2.5)], 5, 10, inc=2.5)
ok("Der Rückschritt bleibt bei null stehen",
   p is None or p["to_weight"] >= 0, str(p["to_weight"] if p else "–"))

# --- Der Referenzwert muss zur Waage passen -----------------------------
from app.services import body as body_svc                            # noqa: E402
with get_db() as db:
    db.execute("DELETE FROM body_metrics")

# Der gemeldete Fall: lange nicht gewogen, dann mehrfach abends. Der
# "7-Tage-Median" lief früher über die letzten sieben EINTRÄGE — bei
# unregelmäßigem Wiegen also über Monate, und oben stand ein Gewicht von vor
# einem Vierteljahr.
for back, kg, hour in [(120, 78.0, 7), (95, 78.4, 7), (60, 79.5, 7),
                       (30, 81.0, 7), (10, 82.0, 21), (3, 82.5, 21),
                       (0, 82.9, 21)]:
    d = TODAY - dt.timedelta(days=back)
    body_svc.record({"weight_kg": kg,
                     "measured_at": f"{d.isoformat()}T{hour:02d}:40:00"},
                    source="test")

sm = body_svc.summary(180)
lm = sm["last_measurement"]
ok("Die letzte Messung wird mitgeliefert", lm is not None)
check("… mit dem Rohwert der Waage", lm["weight_kg"], 82.9)
ok("Der Referenzwert liegt nahe an der letzten Messung",
   abs(sm["current_kg"] - lm["adjusted_kg"]) < 1.0,
   f"{sm['current_kg']} vs {lm['adjusted_kg']}")
ok("… und nicht mehr Kilos darunter",
   sm["current_kg"] > 80.0, f"{sm['current_kg']} kg")
check("Die Glättung ist auf Tage bezogen", sm["current_from_days"], body_svc.SMOOTH_DAYS)

# Die Umrechnung darf nie größer sein als plausibel.
ok("Die Umrechnung bleibt im Rahmen",
   abs(lm["delta_kg"]) <= lm["weight_kg"] * body_svc.MAX_ADJUST_PCT / 100 + 0.01,
   f"{lm['delta_kg']} kg")
extreme = body_svc.adjust(82.9, f"{TODAY.isoformat()}T23:59:00", factor=99)
ok("Auch ein entgleister Faktor korrigiert nicht mehr als erlaubt",
   abs(extreme - 82.9) <= 82.9 * body_svc.MAX_ADJUST_PCT / 100 + 0.01,
   f"{extreme} kg")
ok("Der persönliche Faktor bleibt in Grenzen",
   body_svc.FACTOR_RANGE[0] <= body_svc.personal_factor() <= body_svc.FACTOR_RANGE[1],
   str(body_svc.personal_factor()))

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Tests bestanden.")
