"""Tests fuer Zusammenhaenge und Naehrwertziele.

Der kritische Punkt bei den Zusammenhaengen ist nicht, ob etwas gefunden wird —
sondern ob nichts gefunden wird, wo nichts ist. Zufall als Einsicht zu
verkaufen waere schlimmer als zu schweigen.

Aufruf:  python3 tests/test_insights.py
"""
import datetime as dt
import os
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db, set_setting          # noqa: E402
from app.services import insights, nutrition             # noqa: E402

failures = []


def check(name, actual, expected, tol=0.01):
    ok = (abs(actual - expected) <= tol) if isinstance(expected, (int, float)) \
        and isinstance(actual, (int, float)) and not isinstance(expected, bool) \
        else actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


init_db()

# --- Ohne Daten darf nichts behauptet werden -----------------------------
empty = insights.analyse()
check("Ohne Daten keine Funde", empty["findings"], [])
check("Stattdessen ein Hinweis", bool(empty["hint"]), True)

# --- Reines Rauschen darf ebenfalls nichts ergeben -----------------------
rnd = random.Random(11)
with get_db() as db:
    for i in range(45):
        day = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        db.execute("""INSERT INTO daily_metrics(day, sleep_seconds, hrv_avg,
                      resting_hr, training_readiness) VALUES(?,?,?,?,?)""",
                   (day, rnd.uniform(5.5, 8.5) * 3600, rnd.uniform(45, 70),
                    rnd.uniform(44, 55), rnd.uniform(30, 90)))
        db.execute("""INSERT INTO mood_entries(day, recorded_at, mood, energy)
                      VALUES(?,?,?,?)""",
                   (day, day + "T20:00:00", rnd.randint(1, 5), rnd.randint(1, 5)))

noise = insights.analyse()
check("Zufallsdaten ergeben keinen Zusammenhang mit der Stimmung",
      [f for f in noise["findings"] if f["target"] == "mood"], [])

# --- Ein echter Zusammenhang muss gefunden werden ------------------------
with get_db() as db:
    db.execute("DELETE FROM daily_metrics")
    db.execute("DELETE FROM mood_entries")
    for i in range(40):
        day = (dt.date.today() - dt.timedelta(days=i)).isoformat()
        good = i % 2 == 0
        db.execute("""INSERT INTO daily_metrics(day, sleep_seconds, hrv_avg,
                      resting_hr, training_readiness) VALUES(?,?,?,?,?)""",
                   (day, (8.1 if good else 5.6) * 3600 + rnd.uniform(-900, 900),
                    62 if good else 50, 46 if good else 53, 78 if good else 44))
        db.execute("""INSERT INTO mood_entries(day, recorded_at, mood, energy)
                      VALUES(?,?,?,?)""",
                   (day, day + "T20:00:00", 4 if good else 2, 4 if good else 2))

r = insights.analyse()
check("Zusammenhang wird gefunden", len(r["findings"]) > 0, True)
sleep_mood = [f for f in r["findings"]
              if f["driver"] == "sleep_hours" and f["target"] == "mood"]
check("Schlaf und Stimmung hängen zusammen", len(sleep_mood), 1)
check("Richtung stimmt", sleep_mood[0]["direction"], "helps")
check("Bei viel Schlaf bessere Stimmung",
      sleep_mood[0]["high"] > sleep_mood[0]["low"], True)
check("Beide Hälften ausreichend besetzt",
      min(sleep_mood[0]["n_low"], sleep_mood[0]["n_high"]) >= insights.MIN_PER_HALF,
      True)

rhr = [f for f in r["findings"] if f["driver"] == "resting_hr"]
check("Hoher Ruhepuls wird als ungünstig erkannt",
      all(f["direction"] == "hurts" for f in rhr), True)

check("Es gibt eine Liste dessen, was guttut", len(r["helps"]) > 0, True)
check("Und eine dessen, was dagegen spricht", len(r["hurts"]) > 0, True)
check("Stärkster Zusammenhang steht vorn",
      abs(r["findings"][0]["r"]) >= abs(r["findings"][-1]["r"]), True)

# Abkürzungen dürfen nicht kleingeschrieben werden
hrv = [f for f in r["findings"] if f["driver"] == "hrv_avg"]
if hrv:
    check("HRV bleibt großgeschrieben", "HRV" in hrv[0]["text"], True)
check("Zielgröße bleibt großgeschrieben",
      "Stimmung" in sleep_mood[0]["text"], True)

# --- Naehrwertziele -------------------------------------------------------
check("Ohne Gewicht keine Zielwerte", nutrition.targets()["ready"], False)

set_setting("body_height_cm", "184")
set_setting("body_age", "24")
set_setting("body_sex", "male")
today = dt.date.today().isoformat()
with get_db() as db:
    db.execute("""INSERT INTO body_metrics(day, measured_at, weight_kg, source)
                  VALUES(?,?,80.0,'miscale')""", (today, today + "T07:00:00"))

t = nutrition.targets()
check("Zielwerte berechenbar", t["ready"], True)
# Mifflin-St Jeor: 10*80 + 6.25*184 - 5*24 + 5 = 1835
check("Grundumsatz nach Mifflin-St Jeor", t["bmr"], 1835)
check("Erhaltungsbedarf über dem Grundumsatz", t["maintenance"] > t["bmr"], True)
check("Eiweiß im sinnvollen Bereich (1,6–2,2 g/kg)",
      1.6 <= t["protein_g"] / 80 <= 2.2, True)
check("Makros ergeben die Kalorien",
      abs(t["protein_g"] * 4 + t["carbs_g"] * 4 + t["fat_g"] * 9 - t["kcal"]) < 25,
      True)
check("Rechenweg wird erklärt", "Mifflin" in t["explain"], True)

# --- Mahlzeiten -----------------------------------------------------------
m = nutrition.add_meal({"name": "Skyr mit Beeren", "slot": "breakfast",
                        "kcal": 480, "protein_g": 42, "carbs_g": 48, "fat_g": 13})
check("Mahlzeit gespeichert", m["id"] > 0, True)
check("Auf heute datiert", m["day"], today)

d = nutrition.day()
check("Mahlzeit erscheint im Tag", len(d["meals"]), 1)
check("Summe gerechnet", d["total"]["kcal"], 480.0)
check("Rest zum Ziel gerechnet", d["remaining"]["kcal"], round(t["kcal"] - 480))

# Portionen müssen die Nährwerte skalieren
double = nutrition.add_meal({"name": "Doppelt", "kcal": 100, "protein_g": 10,
                             "portions": 2})
check("Portionen skalieren die Kalorien", double["kcal"], 200.0)
check("Portionen skalieren das Eiweiß", double["protein_g"], 20.0)

# Aus einem Rezept übernehmen
r_meal = nutrition.add_recipe("skyr_beeren", portions=1, slot="breakfast")
check("Rezept als Mahlzeit übernommen", r_meal["kcal"], 480.0)
try:
    nutrition.add_recipe("gibtsnicht")
    check("Unbekanntes Rezept wird abgelehnt", False, True)
except ValueError:
    check("Unbekanntes Rezept wird abgelehnt", True, True)

# Die Tagessumme muss auch in nutrition_log stehen — dort lesen Dashboard
# und Coach.
with get_db() as db:
    row = db.execute("SELECT kcal FROM nutrition_log WHERE day=?", (today,)).fetchone()
# Skyr 480 + doppelte Portion 200 + Rezept 480
check("Tagessumme in nutrition_log geführt", row["kcal"], 1160.0)

check("Mahlzeit löschbar", nutrition.delete_meal(double["id"]), True)
check("Summe nach dem Löschen kleiner", nutrition.day()["total"]["kcal"], 960.0)
check("Unbekannte Mahlzeit meldet Fehlschlag", nutrition.delete_meal(999999), False)

if failures:
    print(f"\n{len(failures)} Test(s) fehlgeschlagen:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\nAlle Zusammenhangs- und Nährwert-Tests bestanden.")
