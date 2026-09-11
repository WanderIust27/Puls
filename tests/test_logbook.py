"""Tests fuer das Nachtragen von Trainings in Worten.

Der Kern: Was jemand hinschreibt, muss als dieselben Saetze in der Datenbank
landen — und keine Zahl darf dabei entstehen, die im Text nicht steht.

Aufruf:  python3 tests/test_logbook.py
"""
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db                                   # noqa: E402
from app.services import exercises as ex_lib                         # noqa: E402
from app.services import logbook                                     # noqa: E402

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


def ok(name, condition, detail=""):
    print(f"{'OK  ' if condition else 'FAIL'} {name}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(name)


init_db()
TODAY = dt.date(2026, 3, 12)          # ein Donnerstag


# --------------------------------------------------------- Schreibweisen

def read(text):
    return logbook.read_segment(logbook._segments(text)[0])


cases = [
    ("Beinpresse 3x15 mit 60 kg", {"sets": 3, "reps": 15, "weight": 60.0}),
    ("Beinpresse 3 Sätze à 15 Wdh mit 60 kg", {"sets": 3, "reps": 15, "weight": 60.0}),
    ("Beinpresse 3x15 60kg", {"sets": 3, "reps": 15, "weight": 60.0}),
    ("dreimal fünfzehn Beinpresse mit sechzig Kilo",
     {"sets": 3, "reps": 15, "weight": 60.0}),
    ("Latzug 12/10/8 bei 45 kg", {"rep_list": [12, 10, 8], "weight": 45.0}),
    ("Unterarmstütz 3x60s", {"sets": 3, "seconds": 60.0}),
]
for text, expected in cases:
    got = read(text)
    ok(f"gelesen: „{text}“",
       all(got.get(k) == v for k, v in expected.items()),
       str({k: got.get(k) for k in expected}))

# Die Wiederholungsliste darf nicht an Kommas zerbrechen, die Uebungen trennen.
parsed = read("Beinpresse 15, 12, 10 mit 60 kg")
check("Kommaliste bleibt eine Übung", parsed.get("rep_list"), [15, 12, 10])

# Steigendes Gewicht bei gleicher Wiederholungszahl: drei Saetze, drei Gewichte.
parsed = read("Hamstring-Curls 15 Wdh @ 25 / 30 / 35")
check("Gewichtsliste erkannt", parsed.get("weight_list"), [25.0, 30.0, 35.0])
check("Name ohne Zahlen und Zeichen", parsed.get("name"), "hamstring-curls")

# Ein Dezimalkomma trennt nicht.
runs = logbook.preview("5,2 km in 30 min gelaufen", TODAY)["runs"]
check("Dezimalkomma bleibt eine Zahl", [r["km"] for r in runs], [5.2])


# ------------------------------------------------------------------ Datum

for text, expected in (("gestern Beinpresse 3x15", (TODAY - dt.timedelta(days=1))),
                       ("vorgestern Beinpresse 3x15", (TODAY - dt.timedelta(days=2))),
                       ("Beinpresse 3x15", TODAY),
                       ("am 9.3. Beinpresse 3x15", dt.date(2026, 3, 9))):
    check(f"Datum aus „{text}“", logbook.read_day(text, TODAY)["day"],
          expected.isoformat())

# Ein Datum ohne Jahr, das in der Zukunft laege, meint das Vorjahr.
check("Datum ohne Jahr geht zurück", logbook.read_day("am 20.12. Beinpresse", TODAY)["day"],
      "2025-12-20")


# ---------------------------------------------------- Vorschau und Eintrag

text = ("Gestern im Gym: Beinpresse 3x15 mit 60 kg, dann Latzug 12/10/8 bei 45 kg, "
        "Hamstring-Curls 15 Wdh @ 25 / 30 / 35, Wadenheben stehend 3x20 mit 30 kg "
        "und Unterarmstütz 3x60s. Danach 5,2 km in 30 min gelaufen.")
pv = logbook.preview(text, TODAY)

check("Trainingstag", pv["day"], (TODAY - dt.timedelta(days=1)).isoformat())
check("Übungen erkannt", len(pv["items"]), 5)
check("Ein Lauf erkannt", len(pv["runs"]), 1)
check("Nichts unverstanden", pv["unread"], [])

by_name = {i["read_name"]: i for i in pv["items"]}
ok("Bekannte Übung wiedergefunden", by_name["beinpresse"]["known"],
   by_name["beinpresse"]["name"])
ok("„Plank“ findet den Unterarmstütz",
   by_name.get("unterarmstütz", {}).get("known", False))
ok("Unbekannte Übung wird als neu gemeldet",
   not by_name["wadenheben stehend"]["known"])
check("Neue Übung bekommt die richtige Gruppe",
      by_name["wadenheben stehend"]["muscle_group"], "legs")
check("Steigende Gewichte werden zu drei Sätzen",
      [s["weight_kg"] for s in by_name["hamstring-curls"]["sets"]], [25.0, 30.0, 35.0])

before = len(ex_lib.list_exercises())
res = logbook.commit(pv["day"], pv["items"], pv["runs"])
check("Sätze eingetragen", res["sets"], 15)
check("Eine neue Übung angelegt", res["created"], ["Wadenheben stehend"])
check("Bibliothek gewachsen", len(ex_lib.list_exercises()), before + 1)
check("Lauf eingetragen", res["runs"], 1)

# Der Kern des Ganzen: Aus dem Geschafften wird die neue Vorgabe.
props = {p["name"]: p for p in res["proposals"]}
ok("Vorschlag für die Hamstring-Curls", "Hamstring-Curls mit Band" in props,
   str(sorted(props)))
curls = props["Hamstring-Curls mit Band"]
check("Schwerster Satz wird zur neuen Grenze", curls["to_weight"], 35.0)
check("… bei zehn Wiederholungen", curls["to_reps"], 10)

# Zweimal dieselbe Beschreibung darf die Saetze nicht verdoppeln.
again = logbook.commit(pv["day"], pv["items"], pv["runs"])
check("Erneutes Eintragen ersetzt statt zu verdoppeln", again["sets"], 15)
with get_db() as db:
    total = db.execute("SELECT COUNT(*) AS n FROM exercise_sets WHERE day=?",
                       (pv["day"],)).fetchone()["n"]
check("Sätze in der Datenbank", total, 15)
check("Der Lauf bleibt einer", again["runs"], 0)


# ------------------------------------------------- Das Modell erfindet nichts

# Zerlegt das Modell den Text falsch und nennt eine Zahl, die nirgends steht,
# darf sie nicht in die Datenbank wandern.
faked = logbook.read_segment("Beinpresse 3x15 mit 95 kg")
ok("Erfundene Zahl wird verworfen",
   not logbook._numbers_occur(faked, "Beinpresse dreimal fünfzehn mit 60 Kilo"))
ok("Vorhandene Zahl wird durchgelassen",
   logbook._numbers_occur(logbook.read_segment("Beinpresse 3x15 mit 60 kg"),
                          "Beinpresse 3x15 mit 60 kg"))


# ---------------------------------------------------------- Letzte Einheiten

sessions = logbook.recent_sessions(5)
ok("Die Einheit taucht im Rückblick auf", bool(sessions), str(len(sessions)))
check("Am richtigen Tag", sessions[0]["day"], pv["day"])
check("Mit allen Übungen", len(sessions[0]["exercises"]), 5)
ok("Jede Übung fasst ihre Sätze zusammen",
   all(e["summary"] for e in sessions[0]["exercises"]),
   sessions[0]["exercises"][0]["summary"])


# ----------------------------------------------------------- Grenzfaelle

empty = logbook.preview("", TODAY)
check("Leerer Text bleibt leer", empty["items"], [])
ok("… und sagt, was zu tun ist", bool(empty["hint"]))

wirr = logbook.preview("war heute richtig anstrengend", TODAY)
check("Text ohne Zahlen ergibt keine Sätze", wirr["items"], [])
ok("… und meldet das ehrlich", bool(wirr["hint"]))

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Logbuch-Tests bestanden.")
