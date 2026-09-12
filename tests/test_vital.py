"""Tests fuer Schlaf und Vitalwerte.

Der Kern: Ein Wert wird gegen die eigene Basislinie gemessen, nicht gegen eine
Tabelle. Ein Ausschlag muss auffallen, und die Einschlafzeit muss nachrechenbar
sein — sonst haelt man eine Zahl, die von acht auf neuneinhalb springt, fuer
einen Fehler.

Aufruf:  python3 tests/test_vital.py
"""
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db, set_setting                  # noqa: E402
from app.services import vital                                   # noqa: E402

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
TODAY = dt.date.today()


def night(offset, **fields):
    day = (TODAY - dt.timedelta(days=offset)).isoformat()
    keys = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    with get_db() as db:
        db.execute(f"INSERT OR REPLACE INTO daily_metrics(day, {keys}) "
                   f"VALUES(?, {marks})", (day, *fields.values()))


def clear():
    with get_db() as db:
        db.execute("DELETE FROM daily_metrics")
        db.execute("DELETE FROM activities")


# ----------------------------------------------------------- Ohne Daten

clear()
empty = vital.metrics(TODAY)
check("Ohne Daten keine Werte", empty["metrics"], [])
ok("… aber ein Hinweis, woher sie kommen", bool(empty["hint"]))
check("Ohne Daten keine Ausschläge", empty["spikes"], [])
check("Ohne Nächte kein Rhythmus", vital.regularity(TODAY), None)


# ------------------------------------------------------- Eigene Basislinie

clear()
# Vier ruhige Wochen, dann eine Nacht, die aus der Reihe faellt.
for i in range(1, 28):
    night(i, sleep_seconds=int(7.2 * 3600), hrv_avg=55, resting_hr=52,
          body_battery_wake=85, stress_avg=28, respiration_avg=13.6,
          hrv_baseline_low=45, hrv_baseline_high=65)
night(0, sleep_seconds=int(5.9 * 3600), hrv_avg=34, resting_hr=61,
      body_battery_wake=48, stress_avg=46, respiration_avg=15.8,
      hrv_baseline_low=45, hrv_baseline_high=65, training_readiness=38)

data = vital.metrics(TODAY)
check("Sechs Werte", len(data["metrics"]), 6)
by_key = {m["key"]: m for m in data["metrics"]}

check("Der Schnitt ist der eigene", by_key["resting_hr"]["baseline"], 52)
check("… und der heutige Wert der heutige", by_key["resting_hr"]["value"], 61)
ok("Jeder Wert erklärt sich selbst",
   all(m["what"] and m["why"] for m in data["metrics"]))

# Richtung: Beim Ruhepuls ist weniger besser, bei der HRV mehr.
check("Hoher Ruhepuls ist die schlechte Richtung", by_key["resting_hr"]["good"], False)
check("Niedrige HRV auch", by_key["hrv_avg"]["good"], False)
ok("Beide schlagen aus",
   by_key["resting_hr"]["spike"] and by_key["hrv_avg"]["spike"])
ok("Die Ausschläge stehen vorn, der stärkste zuerst",
   abs(data["spikes"][0]["sigma"]) >= abs(data["spikes"][-1]["sigma"]),
   str([(m["key"], m["sigma"]) for m in data["spikes"]]))

satz = vital.spike_sentence(by_key["resting_hr"])
ok("Der Satz nennt Wert, Abstand und Richtung",
   "61" in satz and "52" in satz and "über" in satz, satz)

# Hoechstens drei — wer sechs Zeilen sieht, liest keine davon.
ok("Höchstens drei Ausschläge", len(data["spikes"]) <= 3, str(len(data["spikes"])))
lead = vital.spike_lead(data["spikes"])
ok("Ein Satz fasst sie zusammen", bool(lead), lead)
ok("… und die Bewertung steht nur dort",
   not any("Richtung" in vital.spike_sentence(m) for m in data["spikes"]))
check("Ohne Ausschläge kein Satz", vital.spike_lead([]), None)

# Ein ruhiger Tag darf nicht als Ausschlag gelten.
clear()
for i in range(0, 28):
    night(i, resting_hr=52 + (i % 3) - 1, hrv_avg=55, sleep_seconds=int(7.2 * 3600),
          body_battery_wake=85, stress_avg=28, respiration_avg=13.6)
quiet = vital.metrics(TODAY)
check("Ohne Auffälligkeiten keine Ausschläge", quiet["spikes"], [])


# --------------------------------------------------------- Einschlafzeit

clear()
set_setting("wake_target", "06:30")
for i in range(1, 20):
    day = TODAY - dt.timedelta(days=i)
    night(i, sleep_seconds=int(8.0 * 3600),
          sleep_start=(day - dt.timedelta(days=1)).isoformat() + "T22:15:00",
          sleep_end=day.isoformat() + "T06:30:00")

bed = vital.bedtime(TODAY)
check("Ohne Anlass acht Stunden Bedarf", bed["need_h"], 8.0)
check("… und keine Zuschläge", bed["need_reasons"], [])
check("Einschlafdauer aus den eigenen Nächten", bed["latency_min"], 15)
check("Zubettgehzeit rückwärts vom Aufstehziel", bed["bedtime"], "22:15")
ok("Die Rechnung steht daneben",
   "06:30" in bed["formula"] and "8" in bed["formula"], bed["formula"])

# Schlechte Werte heben den Bedarf — und jeder Zuschlag wird benannt.
night(0, training_readiness=30, hrv_avg=34, hrv_baseline_low=45,
      hrv_baseline_high=65, sleep_seconds=int(5.5 * 3600))
with get_db() as db:
    db.execute("INSERT INTO activities(source, sport, start_time, duration_s) "
               "VALUES('garmin','strength',?,5400)",
               ((TODAY - dt.timedelta(days=1)).isoformat() + "T18:00:00",))
tired = vital.bedtime(TODAY)
ok("Schlechte Werte heben den Bedarf", tired["need_h"] > 8.0, str(tired["need_h"]))
ok("… und jeder Zuschlag wird benannt",
   len(tired["need_reasons"]) >= 3, str(tired["need_reasons"]))
ok("Früher ins Bett", tired["bedtime"] < bed["bedtime"],
   f"{tired['bedtime']} statt {bed['bedtime']}")

# Ein anderes Aufstehziel verschiebt alles mit.
set_setting("wake_target", "05:00")
early = vital.bedtime(TODAY)
ok("Ein früheres Aufstehziel zieht die Zubettgehzeit mit",
   early["bedtime"] < tired["bedtime"], early["bedtime"])
set_setting("wake_target", "06:30")

# Unsinn in der Einstellung darf nicht durchschlagen.
set_setting("wake_target", "quatsch")
ok("Eine kaputte Uhrzeit wirft nichts um", bool(vital.bedtime(TODAY)["bedtime"]))
set_setting("wake_target", "06:30")


# ------------------------------------------------------- Regelmäßigkeit

clear()
for i in range(1, 15):
    day = TODAY - dt.timedelta(days=i)
    night(i, sleep_seconds=int(7.5 * 3600),
          sleep_start=(day - dt.timedelta(days=1)).isoformat() + "T22:30:00",
          sleep_end=day.isoformat() + "T06:00:00")
steady = vital.regularity(TODAY)
check("Gleiche Zeit heisst sehr regelmäßig", steady["verdict"], "sehr regelmäßig")
check("… mit der typischen Uhrzeit", steady["typical"], "22:30")

clear()
for i in range(1, 15):
    day = TODAY - dt.timedelta(days=i)
    hour = 21 if i % 2 else 1          # mal neun Uhr abends, mal ein Uhr nachts
    start = (day - dt.timedelta(days=1)) if hour > 12 else day
    night(i, sleep_seconds=int(7.0 * 3600),
          sleep_start=start.isoformat() + f"T{hour:02d}:00:00",
          sleep_end=day.isoformat() + "T07:00:00")
wobbly = vital.regularity(TODAY)
ok("Springende Zeiten heissen unregelmäßig",
   wobbly["verdict"] in ("schwankend", "unregelmäßig"),
   f"{wobbly['verdict']}, ±{wobbly['spread_min']} min")
ok("… und Mitternacht macht keinen Sprung in der Rechnung",
   wobbly["spread_min"] < 24 * 60, str(wobbly["spread_min"]))


# ---------------------------------------------------------- Gesamtansicht

clear()
for i in range(0, 20):
    night(i, sleep_seconds=int(7.1 * 3600), hrv_avg=54, resting_hr=52,
          body_battery_wake=84, stress_avg=29, respiration_avg=13.5,
          training_readiness=70)
view = vital.overview(TODAY)
for key in ("readiness", "metrics", "spikes", "bedtime", "regularity"):
    ok(f"Die Ansicht liefert „{key}“", key in view)
ok("Die Erholung ist eine Zahl", view["readiness"]["score"] is not None,
   str(view["readiness"]["score"]))

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Vital-Tests bestanden.")
