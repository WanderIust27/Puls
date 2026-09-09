"""Tests fuer die Statistikseite und den Autopiloten.

Bei der Statistik zaehlt vor allem, dass nichts behauptet wird, was nicht da
ist: Bei sechshundert Paaren faende man rein zufaellig dutzende "Zusammen-
haenge". Die Mehrfachpruefung muss diese aussortieren und den echten
stehenlassen.

Aufruf:  python3 tests/test_stats.py
"""
import datetime as dt
import math
import os
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db, set_setting          # noqa: E402
from app.services import autopilot, stats                # noqa: E402

failures = []


def check(name, actual, expected, tol=0.01):
    ok = (abs(actual - expected) <= tol) if isinstance(expected, (int, float)) \
        and isinstance(actual, (int, float)) and not isinstance(expected, bool) \
        else actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


def ok(name, condition, detail=""):
    print(f"{'OK  ' if condition else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


init_db()

# --- Der p-Wert selbst ---------------------------------------------------
# Bei perfektem Zusammenhang null, bei keinem Zusammenhang eins nahe.
ok("p-Wert: perfekter Zusammenhang", stats._p_value(1.0, 30) == 0.0)
ok("p-Wert: zu wenige Punkte", stats._p_value(0.9, 3) == 1.0)
ok("p-Wert faellt mit der Staerke",
   stats._p_value(0.8, 30) < stats._p_value(0.3, 30),
   f"{stats._p_value(0.8, 30):.5f} < {stats._p_value(0.3, 30):.5f}")
ok("p-Wert faellt mit der Menge",
   stats._p_value(0.4, 100) < stats._p_value(0.4, 15),
   f"{stats._p_value(0.4, 100):.5f} < {stats._p_value(0.4, 15):.5f}")
# Gegenprobe an einem Lehrbuchwert: r = 0,5 bei n = 30 liegt knapp unter 0,01
p = stats._p_value(0.5, 30)
ok("p-Wert plausibel (r=0,5, n=30)", 0.002 < p < 0.02, f"p = {p:.4f}")

# --- Mehrfachpruefung ----------------------------------------------------
# Reines Rauschen: Von hundert Paaren mit gleichverteilten p-Werten duerfen
# einige unter 0,05 liegen — belastbar sein darf davon (fast) keines.
rnd = random.Random(7)
noise = [{"p": rnd.random()} for _ in range(200)]
stats._benjamini_hochberg(noise)
robust_noise = sum(1 for i in noise if i["robust"])
naive_noise = sum(1 for i in noise if i["p"] < 0.05)
ok("Rauschen: naiv faende man etwas", naive_noise >= 5, f"{naive_noise} Paare p<0,05")
ok("Rauschen: belastbar bleibt (fast) nichts", robust_noise <= 1,
   f"{robust_noise} von {len(noise)}")

# Ein echter Fund inmitten des Rauschens muss ueberleben.
mixed = [{"p": rnd.random()} for _ in range(199)] + [{"p": 1e-9}]
stats._benjamini_hochberg(mixed)
ok("Echter Fund ueberlebt die Korrektur", mixed[-1]["robust"])
ok("Korrigierter p-Wert ist nie kleiner",
   all(i["p_adjusted"] >= i["p"] - 1e-9 for i in mixed))

# --- Korrelation ---------------------------------------------------------
xs = [float(i) for i in range(20)]
check("Korrelation mit sich selbst", stats._correlate(xs, xs), 1.0)
check("Korrelation mit dem Gegenteil", stats._correlate(xs, [-x for x in xs]), -1.0)
ok("Zu wenige Paare ergeben nichts", stats._correlate(xs[:5], xs[:5]) is None)
ok("Konstante Reihe ergibt nichts", stats._correlate(xs, [3.0] * 20) is None)

# --- Ohne Daten wird nichts behauptet ------------------------------------
empty = stats.matrix(90)
check("Ohne Daten keine Paare", empty["pairs"], [])
ok("Stattdessen ein Hinweis", bool(empty["hint"]))

# --- Mit Daten: ein gelegter Zusammenhang wird gefunden ------------------
# Schlaf und HRV haengen zusammen, der Rest ist Rauschen.
rnd = random.Random(23)
with get_db() as db:
    for i in range(1, 90):
        day = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        sleep_h = rnd.uniform(5.0, 9.0)
        hrv = 20 + 5.5 * sleep_h + rnd.gauss(0, 2)     # klarer Zusammenhang
        db.execute("""INSERT INTO daily_metrics(day, sleep_seconds, hrv_avg,
                          resting_hr, steps, stress_avg, training_readiness)
                      VALUES(?,?,?,?,?,?,?)""",
                   (day, sleep_h * 3600, hrv, rnd.uniform(44, 56),
                    rnd.uniform(4000, 14000), rnd.uniform(20, 60),
                    rnd.uniform(30, 90)))
        db.execute("""INSERT INTO mood_entries(day, recorded_at, mood, energy, stress)
                      VALUES(?,?,?,?,?)""",
                   (day, f"{day}T20:00:00", rnd.randint(1, 5),
                    rnd.randint(1, 5), rnd.randint(1, 5)))

data = stats.matrix(120)
ok("Paare werden geprueft", data["tested"] > 10, f"{data['tested']} Paare")
found = [p for p in data["pairs"]
         if {p["a"], p["b"]} == {"sleep_hours", "hrv_avg"}]
ok("Schlaf und HRV werden gefunden", bool(found))
if found:
    ok("… und als belastbar markiert", found[0]["robust"], f"r = {found[0]['r']}")
    ok("… mit richtiger Richtung", found[0]["direction"] == "gleichläufig")
    ok("… und richtiger Staerke", found[0]["strength"] == "stark", found[0]["strength"])

# Das Belastbare steht oben.
first_weak = next((i for i, p in enumerate(data["pairs"]) if not p["robust"]), None)
last_robust = max((i for i, p in enumerate(data["pairs"]) if p["robust"]), default=-1)
ok("Belastbares steht oben", first_weak is None or last_robust < first_weak,
   f"letztes belastbares #{last_robust}, erstes unsicheres #{first_weak}")

# Zufallspaare duerfen nicht massenhaft als belastbar durchgehen.
share = len(data["robust"]) / max(1, data["tested"])
ok("Nicht alles gilt als belastbar", share < 0.5, f"{share:.0%} belastbar")

# --- Einzelne Groesse ----------------------------------------------------
one = stats.for_metric("hrv_avg", 120)
check("Bezeichnung stimmt", one["label"], "HRV")
ok("Bezug nur zu anderen Groessen",
   all(p["other"] != "hrv_avg" for p in one["related"]))
ok("Verlauf hat Punkte", len(stats.series("hrv_avg", 120)) > 50)
try:
    stats.series("gibtsnicht")
    ok("Unbekannte Groesse wird abgelehnt", False)
except ValueError:
    ok("Unbekannte Groesse wird abgelehnt", True)

# Jede Groesse in der Liste muss auch aus den Tagesdaten kommen koennen.
row_keys = set(stats.collect(5)[0].keys()) if stats.collect(5) else set()
missing = [k for k, *_ in stats.METRICS if k not in row_keys]
check("Alle Kennzahlen werden erhoben", missing, [])

# --- Autopilot -----------------------------------------------------------
cfg = autopilot.save_settings({"enabled": True, "focus": "run_faster",
                               "session_minutes": 60, "long_run_day": "So",
                               "available_days": ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"],
                               "wishes": "Bergläufe wären schön"})
check("Autopilot merkt sich den Schwerpunkt", cfg["focus"], "run_faster")
check("Dauer wird uebernommen", cfg["session_minutes"], 60)

week = autopilot.plan(dt.date.today() + dt.timedelta(days=1))
check("Sieben Tage geplant", len(week["days"]), 7)
runs = [s for d in week["days"] for s in d["sessions"] if s["sport"] == "running"]
gyms = [s for d in week["days"] for s in d["sessions"] if s["sport"] == "strength"]
ok("Laeufe geplant", len(runs) >= 2, f"{len(runs)} Läufe")
ok("Krafteinheiten geplant", len(gyms) >= 1, f"{len(gyms)} Gym")
ok("Jede Einheit hat eine Begruendung",
   all(s.get("why") for d in week["days"] for s in d["sessions"]))
ok("Kein Tag traegt zwei Laeufe",
   all(sum(1 for s in d["sessions"] if s["sport"] == "running") <= 1
       for d in week["days"]))
ok("Zustand wird benannt", week["condition"]["state"] in autopilot.DOSE)

# Weniger verfuegbare Tage duerfen nicht mehr Training ergeben.
autopilot.save_settings({"available_days": ["Di", "Do", "Sa"]})
small = autopilot.plan(dt.date.today() + dt.timedelta(days=1))
sessions_small = sum(len(d["sessions"]) for d in small["days"])
ok("Weniger Tage, nicht mehr Einheiten",
   sessions_small <= sum(len(d["sessions"]) for d in week["days"]))
trained = {d["weekday"] for d in small["days"]
           for s in d["sessions"] if s["sport"] in ("running", "strength")}
ok("Nur an verfuegbaren Tagen wird trainiert",
   trained <= {"Di", "Do", "Sa"}, f"{sorted(trained)}")

# Ein muerber Zustand muss die Dosis senken, nicht heben.
autopilot.save_settings({"available_days": list(autopilot.WEEKDAYS),
                         "focus": "recover"})
calm = autopilot.plan(dt.date.today() + dt.timedelta(days=1))
ok("Ruhiger Schwerpunkt plant weniger",
   calm["total_minutes"] < week["total_minutes"],
   f"{calm['total_minutes']} < {week['total_minutes']} min")

# Anwenden legt Einheiten an — genau so viele wie geplant.
autopilot.save_settings({"focus": "balanced"})
applied = autopilot.plan(dt.date.today() + dt.timedelta(days=1), apply_it=True)
with get_db() as db:
    stored = db.execute(
        "SELECT COUNT(*) c FROM planned_workouts WHERE created_by='autopilot'"
    ).fetchone()["c"]
ok("Angelegte Einheiten stehen in der Datenbank",
   stored == len(applied["created"]) and stored > 0,
   f"{stored} angelegt")
ok("Jede angelegte Einheit hat eine Kennung",
   all(i > 0 for i in applied["created"]))

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Tests bestanden.")
