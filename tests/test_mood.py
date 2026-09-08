"""Tests fuer Gemuetszustand, Beschwerden und die Anpassung des Trainings.

Der Kern: Wer "Rueckenschmerzen" eintraegt, soll beim naechsten Training
etwas anderes vorgeschlagen bekommen — nachweisbar, nicht nur behauptet.

Aufruf:  python3 tests/test_mood.py
"""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db                        # noqa: E402
from app.services import mood, planner, supplements       # noqa: E402

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

# --- Eintragen, mehrfach am Tag ------------------------------------------
mood.record({"mood": 4, "energy": 3, "stress": 2,
             "recorded_at": f"{today}T08:00:00", "note": "Gut geschlafen"})
mood.record({"mood": 2, "energy": 2, "stress": 4,
             "recorded_at": f"{today}T20:00:00", "note": "Langer Tag",
             "complaints": [{"region": "back_low", "kind": "pain", "severity": 3}]})
rows = mood.entries(7)
check("Zwei Eintraege am selben Tag", len(rows), 2)
check("Neueste zuerst", rows[0]["recorded_at"].endswith("20:00:00"), True)
check("Beschwerde gespeichert", rows[0]["complaints"][0]["region"], "back_low")
check("Beschwerde lesbar beschriftet",
      rows[0]["complaint_labels"][0], "Unterer Rücken: Schmerz")
check("Regler begrenzt", mood.record({"mood": 99})["mood"], 5)
check("Unsinnige Beschwerde wird verworfen",
      mood.record({"complaints": [{"region": "mond", "kind": "pain"}]})["complaints"], [])

# --- Nachwirkung ----------------------------------------------------------
active = mood.active_complaints()
check("Beschwerde ist aktiv", len(active), 1)
check("Region richtig", active[0]["region_label"], "Unterer Rücken")

with get_db() as db:                       # Muskelkater von vor 10 Tagen
    old_day = (dt.date.today() - dt.timedelta(days=10)).isoformat()
    db.execute("""INSERT INTO mood_entries(day, recorded_at, complaints)
                  VALUES(?,?,?)""",
               (old_day, f"{old_day}T09:00:00",
                json.dumps([{"region": "thigh", "kind": "soreness", "severity": 2}])))
check("Alter Muskelkater zaehlt nicht mehr",
      any(c["region"] == "thigh" for c in mood.active_complaints()), False)

with get_db() as db:                       # Muskelkater von gestern
    y = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    db.execute("""INSERT INTO mood_entries(day, recorded_at, complaints)
                  VALUES(?,?,?)""",
               (y, f"{y}T21:00:00",
                json.dumps([{"region": "calf", "kind": "soreness", "severity": 2}])))
check("Frischer Muskelkater zaehlt",
      any(c["region"] == "calf" for c in mood.active_complaints()), True)

# --- Ableitung ------------------------------------------------------------
a = mood.adaptations()
check("Ruecken schont Ruecken und Beine",
      set(a["spare_groups"]) >= {"back"}, True)
check("Entlastende Stellungen vorgeschlagen",
      "Kindhaltung" in a["relief_poses"], True)
check("Ernaehrungshinweis bei Muskelkater",
      any("Eiweiß" in n for n in a["nutrition"]), True)
check("Zusammenfassung in Worten", len(a["summary"]) > 0, True)

# --- Freitext ohne Modell -------------------------------------------------
kw = mood.keyword_complaints("Seit gestern zieht mein Nacken beim Drehen")
check("Nacken im Freitext erkannt", kw[0]["region"], "neck")
check("Nichts erfinden bei harmlosem Text",
      mood.keyword_complaints("Schöner Tag, gut gelaufen"), [])

# --- Und jetzt der eigentliche Punkt: aendert sich das Training? ---------
session = planner.build_gym_session(minutes=75)
check("Einheit wurde als angepasst markiert", session["adapted"] is not None, True)
check("Grund wird genannt", "Rücken" in session["adapted"]["reason"], True)
names = [s.get("name") for s in session["steps"]]
check("Entlastende Dehnung im Plan",
      any(n in names for n in a["relief_poses"]), True)

yoga = planner.build_evening_yoga(minutes=12)
ynames = [s.get("name") for s in yoga["steps"]]
check("Yoga enthaelt die passende Stellung", "Kindhaltung" in ynames, True)
check("Yoga als angepasst markiert", yoga["adapted"] is not None, True)

# Ohne Beschwerden darf nichts umgebaut werden
with get_db() as db:
    db.execute("DELETE FROM mood_entries")
plain = planner.build_gym_session(minutes=75)
check("Ohne Beschwerden keine Anpassung", plain["adapted"], None)
check("Ohne Beschwerden trotzdem ein voller Plan", len(plain["steps"]) > 5, True)

# --- Supplements ----------------------------------------------------------
supplements.seed_defaults()
state = supplements.today()
names = [i["name"] for i in state["items"]]
check("Kreatin angelegt", "Kreatin" in names, True)
check("Zink angelegt", "Zink" in names, True)
kreatin = [i for i in state["items"] if i["name"] == "Kreatin"][0]
check("Kreatin morgens", kreatin["at_time"], "08:00")
check("Kreatin mit Dosis", kreatin["dose"], "5 g")
zink = [i for i in state["items"] if i["name"] == "Zink"][0]
check("Zink abends", zink["at_time"], "21:00")

shake = [i for i in state["items"] if i["trigger_kind"] == "after_gym"][0]
check("Eiweiss wartet auf die Einheit", shake["waiting_for"], "nach der Gym-Einheit")
check("Wartendes gilt nicht als ueberfaellig", shake["overdue"], False)

supplements.mark(kreatin["id"])
after = supplements.today()
check("Als genommen vermerkt",
      [i for i in after["items"] if i["id"] == kreatin["id"]][0]["taken"], True)
check("Offene Zahl sinkt", after["open"] < state["open"], True)
supplements.mark(kreatin["id"], taken=False)
check("Haken wieder entfernbar",
      [i for i in supplements.today()["items"]
       if i["id"] == kreatin["id"]][0]["taken"], False)

# Nach einer Gym-Einheit wird der Shake faellig
with get_db() as db:
    db.execute("""INSERT INTO activities(source, name, sport, start_time, duration_s)
                  VALUES('garmin','Gym','strength',?,4500)""", (f"{today}T17:00:00",))
shake2 = [i for i in supplements.today()["items"]
          if i["trigger_kind"] == "after_gym"][0]
check("Nach dem Training faellig", shake2["waiting_for"], None)
check("Faelligkeit steht auf dem Ende der Einheit",
      shake2["due_at"].startswith(f"{today}T18:15"), True)

check("Zeile fuer die Tagesnachricht", bool(supplements.context_line()), True)

if failures:
    print(f"\n{len(failures)} Test(s) fehlgeschlagen:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\nAlle Gemuetszustand- und Supplement-Tests bestanden.")
