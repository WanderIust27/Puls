"""Tests für Schrittziel und Tagesverlauf.

Der Punkt ist nicht die Summe, sondern der Vergleich mit dir selbst: 6.000
Schritte sind um zehn Uhr viel und um zwanzig Uhr wenig. Diese Suite legt
einen bekannten Tagesrhythmus an und prüft, ob er wiedergefunden wird.

Aufruf:  python3 tests/test_steps.py
"""
import datetime as dt
import os
import random
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db, set_setting                      # noqa: E402
from app.services import steps                                       # noqa: E402

failures = []


def ok(name, condition, detail=""):
    print(f"{'OK  ' if condition else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def check(name, actual, expected):
    ok(name, actual == expected, f"{actual!r} (erwartet {expected!r})")


init_db()
TODAY = dt.date.today()

# Ein Rhythmus mit klarer Spitze um 18 Uhr und Hälfte gegen Mittag.
PROFIL = {7: 900, 8: 1400, 9: 400, 10: 300, 11: 350, 12: 900, 13: 600,
          14: 300, 15: 400, 16: 500, 17: 1200, 18: 1800, 19: 700,
          20: 400, 21: 200}

# --- Ohne Daten wird nichts behauptet ------------------------------------
bare = steps.typical()
ok("Ohne Tage kein typischer Tag", bare["hint"] is not None, str(bare["hint"]))
check("… und keine Stunden", bare["hours"], [])
first = steps.today()
ok("Trotzdem ein Stand", first["steps"] == 0 and first["goal"] > 0)
ok("… ohne Hochrechnung", first["projected"] is None)
ok("… und ein ehrlicher Hinweis", "fehlen" in first["note"], first["note"][:60])

# --- Mit Daten: der gelegte Rhythmus muss herauskommen -------------------
rnd = random.Random(4)
for d in range(1, 30):
    day = (TODAY - dt.timedelta(days=d)).isoformat()
    steps.record_day(day, {h: max(0, int(v * rnd.uniform(0.7, 1.3)))
                           for h, v in PROFIL.items()})

norm = steps.typical()
ok("Typischer Tag wird gebildet", norm["hint"] is None)
# typical() blickt 28 Tage zurueck — der 29. liegt ausserhalb.
check("Aus dem Rückblickfenster", norm["days"], 28)
check("Vierundzwanzig Stunden", len(norm["hours"]), 24)
ok("Die stärkste Stunde wird gefunden", norm["busiest_hour"] == 18,
   f"{norm['busiest_hour']} Uhr")
ok("Die Summe passt zum gelegten Profil",
   abs(norm["total"] - sum(PROFIL.values())) < sum(PROFIL.values()) * 0.15,
   f"{norm['total']} statt {sum(PROFIL.values())}")
ok("Die Hälfte ist gegen Mittag erreicht", 11 <= norm["half_by_hour"] <= 15,
   f"{norm['half_by_hour']} Uhr")
ok("Der Verlauf steigt nur an",
   all(norm["cumulative"][i]["steps"] <= norm["cumulative"][i + 1]["steps"]
       for i in range(23)))
ok("Tagesabschnitte summieren sich zum Ganzen",
   abs(norm["morning"] + norm["afternoon"] + norm["evening"] - norm["total"]) < 1,
   f"{norm['morning']}+{norm['afternoon']}+{norm['evening']} vs {norm['total']}")

# Nur ein Wochentag: weniger Tage, aber dieselbe Form.
mondays = steps.typical(weekday=0)
ok("Nach Wochentag gefiltert bleibt zu wenig übrig",
   mondays["hint"] is not None or mondays["days"] < norm["days"],
   str(mondays["days"]))

# --- Heute gegen den üblichen Tag ----------------------------------------
set_setting("step_goal", "10000")
steps.record_day(TODAY.isoformat(), {h: v for h, v in PROFIL.items() if h <= 14})
noon = dt.datetime.combine(TODAY, dt.time(14, 30))
t = steps.today(noon)
check("Ziel wird übernommen", t["goal"], 10000)
ok("Der Stand entspricht den Stunden bis 14 Uhr",
   t["steps"] == sum(v for h, v in PROFIL.items() if h <= 14), str(t["steps"]))
ok("Der übliche Stand um diese Zeit wird verglichen",
   t["expected_by_now"] is not None, str(t["expected_by_now"]))
ok("Die Differenz ist klein — der Tag läuft normal",
   abs(t["ahead_by"]) < 1500, f"{t['ahead_by']:+}")
ok("Es wird hochgerechnet", t["projected"] is not None, str(t["projected"]))
ok("Die Hochrechnung liegt über dem aktuellen Stand",
   t["projected"] > t["steps"], f"{t['steps']} -> {t['projected']}")
ok("Der Anteil passt zum Stand",
   t["percent"] == min(100, round(t["steps"] / t["goal"] * 100)), str(t["percent"]))
ok("Ein Satz erklärt den Stand", bool(t["note"]), t["note"][:70])

# Ein sehr aktiver Tag muss als voraus erkannt werden.
steps.record_day(TODAY.isoformat(), {h: v * 3 for h, v in PROFIL.items() if h <= 14})
busy = steps.today(noon)
ok("Ein aktiver Tag liegt voraus", busy["ahead_by"] > 2000, f"{busy['ahead_by']:+}")
ok("… und erreicht das Ziel", busy["reaches_goal"] is True)

# Erreichtes Ziel wird auch so genannt.
steps.record_day(TODAY.isoformat(), {8: 6000, 9: 6000})
done = steps.today(noon)
ok("Erreichtes Ziel wird gemeldet", "Ziel erreicht" in done["note"], done["note"][:50])
check("Der Anteil bleibt bei hundert", done["percent"], 100)
check("Nichts bleibt offen", done["remaining"], 0)

# --- Stundenwerte ersetzen, nicht anhäufen -------------------------------
steps.record_day(TODAY.isoformat(), {8: 100})
with get_db() as db:
    row = db.execute("SELECT steps FROM step_intervals WHERE day=? AND hour=8",
                     (TODAY.isoformat(),)).fetchone()
check("Ein erneuter Abruf überschreibt", row["steps"], 100)

# Ein unsinniges Ziel darf nicht durchschlagen.
set_setting("step_goal", "quatsch")
check("Kaputtes Ziel fällt auf die Vorgabe zurück", steps.goal(), 10000)

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Tests bestanden.")
