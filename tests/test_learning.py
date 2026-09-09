"""Tests fuer Schwung-Massnahmen, Coach-Gedaechtnis und Aktivitaets-Feedback.

Der Kern: Lernt die Auswahl wirklich aus den Rueckmeldungen — kommt also das,
was geholfen hat, oefter und das andere seltener?

Aufruf:  python3 tests/test_learning.py
"""
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db                              # noqa: E402
from app.services import boosters, feedback, memory, mood       # noqa: E402

failures = []


def check(name, actual, expected, tol=0.01):
    ok = (abs(actual - expected) <= tol) if isinstance(expected, (int, float)) \
        and isinstance(actual, (int, float)) and not isinstance(expected, bool) \
        else actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


init_db()

# --- Lage erkennen --------------------------------------------------------
check("Ohne Einträge keine Lage", boosters.situation()["tags"], [])

mood.record({"mood": 2, "energy": 2, "stress": 4, "note": "Zäher Tag"})
sit = boosters.situation()
check("Gedrückte Stimmung erkannt", "low_mood" in sit["tags"], True)
check("Wenig Energie erkannt", "low_energy" in sit["tags"], True)
check("Hoher Stress erkannt", "high_stress" in sit["tags"], True)
check("Lage wird begründet", len(sit["reasons"]) >= 3, True)

# --- Vorschläge passen zur Lage ------------------------------------------
d = boosters.suggest(3)
check("Drei Maßnahmen vorgeschlagen", len(d["boosters"]), 3)
check("Alle passen zur Lage",
      all(set(b["tags"]) & set(sit["tags"]) for b in d["boosters"]), True)
check("Jede Maßnahme ist konkret",
      all(b["text"] and b["name"] for b in d["boosters"]), True)
check("Vorschläge werden protokolliert",
      len(boosters.effectiveness()) >= 3, True)

# --- Und jetzt der Punkt: lernt die Auswahl? -----------------------------
# Eine Maßnahme wird dreimal als hilflos bewertet, eine andere dreimal als gut.
useless = "hydrate"
useful = "kettlebell_short"
today = dt.date.today()
with get_db() as db:
    for i in range(3):
        day = (today - dt.timedelta(days=i + 1)).isoformat()
        db.execute("INSERT INTO tip_log(tip_id, day, helpful, rated_at) "
                   "VALUES(?,?,-1, datetime('now'))", (useless, day))
        db.execute("INSERT INTO tip_log(tip_id, day, helpful, rated_at) "
                   "VALUES(?,?,1, datetime('now'))", (useful, day))

stats = boosters.effectiveness()
check("Wirkungslose Maßnahme hat schlechten Wert", stats[useless]["score"], 0.0)
check("Hilfreiche Maßnahme hat guten Wert", stats[useful]["score"], 1.0)

works = boosters.what_works()
check("Bewährtes wird ausgewiesen", works[0]["id"], useful)
check("Wirkungsloses steht hinten",
      [w["id"] for w in works].index(useless) > 0, True)

# Bei gleicher Passung muss das Bewährte vorn stehen
with get_db() as db:
    db.execute("DELETE FROM tip_log WHERE day = ?", (today.isoformat(),))
fresh = boosters.suggest(5)
ids = [b["id"] for b in fresh["boosters"]]
check("Bewährte Maßnahme wird vorgezogen", ids[0], useful)
check("Wirkungslose Maßnahme rutscht nach hinten",
      useless not in ids[:2], True)

# --- Bewerten ------------------------------------------------------------
check("Bewerten funktioniert", boosters.rate("walk_daylight", True), True)
check("Unbekannte Maßnahme wird abgelehnt", boosters.rate("gibtsnicht", True), False)

# --- Gedächtnis ----------------------------------------------------------
mid = memory.remember("Knie", "Linkes Knie ist bei Kniebeugen empfindlich", "user", True)
check("Merkposten angelegt", mid > 0, True)
check("Merkposten abrufbar", len(memory.all_facts()), 1)
check("Als Kontext formuliert",
      memory.as_context()[0].startswith("Knie:"), True)

memory.remember("Knie", "Linkes Knie: seit Physio wieder gut", "user")
check("Gleiches Thema wird aktualisiert, nicht verdoppelt", len(memory.all_facts()), 1)
check("Neuer Inhalt übernommen",
      "Physio" in memory.all_facts()[0]["fact"], True)
check("Angeheftet bleibt angeheftet", memory.all_facts()[0]["pinned"], 1)

try:
    memory.remember("", "leer")
    check("Leeres Thema wird abgelehnt", False, True)
except ValueError:
    check("Leeres Thema wird abgelehnt", True, True)

check("Vergessen funktioniert", memory.forget(memory.all_facts()[0]["id"]), True)
check("Danach leer", len(memory.all_facts()), 0)
check("Unbekanntes Vergessen meldet Fehlschlag", memory.forget(999999), False)

# Angeheftete Merkposten dürfen nicht verdrängt werden
memory.remember("Wichtig", "Bleibt immer", "user", pinned=True)
for i in range(memory.MAX_FACTS + 6):
    memory.remember(f"Thema {i}", f"Inhalt {i}")
facts = memory.all_facts()
check("Liste bleibt begrenzt", len(facts) <= memory.MAX_FACTS + 1, True)
check("Angeheftetes überlebt",
      any(f["topic"] == "Wichtig" for f in facts), True)

# --- Aktivitäts-Feedback -------------------------------------------------
with get_db() as db:
    db.execute("DELETE FROM coach_memory")
    for i in range(8):
        day = (today - dt.timedelta(days=i)).isoformat()
        db.execute("""INSERT INTO activities(source,name,sport,start_time,
                      duration_s,distance_m,avg_hr)
                      VALUES('garmin','Lauf','running',?,1800,5000,148)""",
                   (day + "T07:00:00",))
        # Gut bewertete Tage hatten mehr Schlaf
        good = i % 2 == 0
        db.execute("""INSERT INTO daily_metrics(day, sleep_seconds, hrv_avg,
                      resting_hr) VALUES(?,?,?,?)""",
                   (day, 28800 if good else 19800, 62 if good else 52,
                    46 if good else 51))
    ids = [r["id"] for r in db.execute(
        "SELECT id FROM activities ORDER BY start_time DESC").fetchall()]

check("Offene Rückmeldungen werden gefunden", len(feedback.pending()) > 0, True)

for n, aid in enumerate(ids):
    feedback.save(aid, rating=5 if n % 2 == 0 else 2, effort=3, note=None)
check("Rückmeldung gespeichert", feedback.get(ids[0])["rating"], 5)
check("Erneutes Speichern überschreibt",
      feedback.save(ids[0], rating=4)["rating"], 4)
check("Beantwortetes taucht nicht mehr auf",
      any(a["id"] == ids[0] for a in feedback.pending()), False)
try:
    feedback.save(999999, 3)
    check("Unbekannte Aktivität meldet Fehler", False, True)
except ValueError:
    check("Unbekannte Aktivität meldet Fehler", True, True)

pat = feedback.patterns()
check("Genug Rückmeldungen für ein Muster", pat["count"] >= 6, True)
check("Zusammenhang mit Schlaf erkannt",
      any("Schlaf" in f["text"] for f in pat["findings"]), True)

# Ohne Rückmeldungen darf nichts behauptet werden
with get_db() as db:
    db.execute("DELETE FROM activity_feedback")
empty = feedback.patterns()
check("Ohne Rückmeldungen keine Aussage", empty["findings"], [])
check("Stattdessen ein Hinweis", bool(empty["hint"]), True)

if failures:
    print(f"\n{len(failures)} Test(s) fehlgeschlagen:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\nAlle Lern-Tests bestanden.")
