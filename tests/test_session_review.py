"""Tests fuer den Rueckblick auf die letzten Einheiten.

Der Rueckblick ist nur dann etwas wert, wenn der Vergleich stimmt. Die
Fallstricke stehen alle in diesen Tests: Verglichen wird mit dem letzten Mal
DIESER Uebung und nicht mit dem Vortag; mehr Wiederholungen bei gleichem
Gewicht sind auch ein Fortschritt; und bei unterstuetzten Klimmzuegen ist
weniger Gewicht am Band das Bessere, nicht das Schlechtere.

Aufruf:  python3 tests/test_session_review.py
"""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.constants import VOLUME_MIN_SETS                       # noqa: E402
from app.db import get_db, init_db, set_setting                 # noqa: E402
from app.services import exercises as ex_lib                    # noqa: E402
from app.services import session_review                         # noqa: E402

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
LIB = {e["name"]: e for e in ex_lib.list_exercises()}
set_setting("gym_split", "ppl")
set_setting("gym_days", json.dumps(["Mo", "Mi", "Fr"]))


def clear():
    with get_db() as db:
        db.execute("DELETE FROM exercise_sets")


def log(offset, name, sets):
    """sets ist eine Liste von (Wiederholungen, Gewicht)."""
    day = (TODAY - dt.timedelta(days=offset)).isoformat()
    for i, (reps, weight) in enumerate(sets):
        ex_lib.record_set(LIB[name]["id"], reps=reps, weight_kg=weight,
                          day=day, set_index=i, source="manual")


def find(reviews, day_offset, exercise):
    day = (TODAY - dt.timedelta(days=day_offset)).isoformat()
    entry = next(r for r in reviews if r["day"] == day)
    return entry, next(e for e in entry["exercises"] if e["name"] == exercise)


# ------------------------------------------------------------- Vergleiche

clear()
log(10, "Bankdrücken (Langhantel)", [(10, 50), (10, 50), (9, 50)])
log(3, "Bankdrücken (Langhantel)", [(10, 55), (10, 55), (8, 55)])
rv = session_review.reviews(5, TODAY)
_, ex = find(rv, 3, "Bankdrücken (Langhantel)")
check("Mehr Gewicht ist ein Fortschritt", ex["compare"]["better"], True)
check("… und die Differenz stimmt", ex["compare"]["delta_kg"], 5.0)
ok("… und steht im Klartext", "5 kg mehr" in ex["compare"]["text"],
   ex["compare"]["text"])
check("Der Vergleichstag ist der richtige", ex["last_day"],
      (TODAY - dt.timedelta(days=10)).isoformat())

# Mehr Wiederholungen bei gleichem Gewicht zaehlen genauso.
clear()
log(10, "Beinpresse", [(10, 60), (10, 60), (10, 60)])
log(3, "Beinpresse", [(12, 60), (12, 60), (11, 60)])
_, ex = find(session_review.reviews(5, TODAY), 3, "Beinpresse")
check("Mehr Wiederholungen zaehlen auch", ex["compare"]["kind"], "reps")
check("… als Fortschritt", ex["compare"]["better"], True)
ok("… mit der Zahl im Text", "2 Wiederholungen mehr" in ex["compare"]["text"],
   ex["compare"]["text"])

# Rueckschritt muss auch als solcher dastehen.
clear()
log(10, "Latziehen", [(12, 50), (12, 50)])
log(3, "Latziehen", [(12, 45), (11, 45)])
_, ex = find(session_review.reviews(5, TODAY), 3, "Latziehen")
check("Weniger Gewicht ist ein Rueckschritt", ex["compare"]["better"], False)

# Gleich ist gleich — und kein Rueckschritt.
clear()
log(10, "Dips", [(8, 0), (8, 0)])
log(3, "Dips", [(8, 0), (8, 0)])
entry, ex = find(session_review.reviews(5, TODAY), 3, "Dips")
check("Gleich bleibt gleich", ex["compare"]["kind"], "same")
ok("… und wird nicht als Rueckschritt gezaehlt", entry["lost"] == 0)
ok("Der Satz sagt: gehalten", "gehalten" in entry["verdict"], entry["verdict"])

# Der Kern bei unterstuetzten Uebungen: weniger Band ist schwerer.
clear()
log(10, "Klimmzüge mit Band", [(8, 30), (8, 30)])
log(3, "Klimmzüge mit Band", [(8, 20), (8, 20)])
_, ex = find(session_review.reviews(5, TODAY), 3, "Klimmzüge mit Band")
ok("Weniger Unterstuetzung ist ein Fortschritt", ex["compare"]["better"] is True,
   ex["compare"]["text"])
ok("… und heisst auch so", "10 kg weniger Unterstützung" in ex["compare"]["text"],
   ex["compare"]["text"])

# Beim ersten Mal gibt es nichts zu vergleichen — und das wird gesagt, statt
# eine Null hinzuschreiben.
clear()
log(2, "Flys", [(12, 25)])
entry, ex = find(session_review.reviews(5, TODAY), 2, "Flys")
ok("Beim ersten Mal kein Vergleich", ex["compare"] is None)
ok("… und der Satz sagt warum", "erste Einheit" in entry["verdict"],
   entry["verdict"])


# ------------------------------------------------- Einheit gegen Einheit

clear()
# Push, Pull, Push — die zweite Push-Einheit muss sich mit der ersten
# vergleichen und nicht mit dem Pull-Tag dazwischen.
log(12, "Bankdrücken (Langhantel)", [(10, 50), (10, 50), (10, 50)])
log(8, "Klimmzüge", [(6, 0), (5, 0), (5, 0)])
log(8, "Rudern am Kabelzug", [(12, 45), (12, 45)])
log(2, "Bankdrücken (Langhantel)", [(10, 55), (10, 55), (10, 55)])
rv = session_review.reviews(5, TODAY)
entry, _ = find(rv, 2, "Bankdrücken (Langhantel)")
check("Die Einheit wird als Push erkannt", entry["kind"], "push")
check("Verglichen wird mit der letzten Push-Einheit", entry["compared_with"],
      (TODAY - dt.timedelta(days=12)).isoformat())
check("Die Volumenlast stimmt", entry["volume"], 1650)
check("Die davor auch", entry["volume_before"], 1500)
check("Und die Veraenderung", entry["volume_change_pct"], 10)
ok("Sie steht im Satz", "10 % über" in entry["verdict"], entry["verdict"])


pull, _ = find(rv, 8, "Klimmzüge")
check("Der Pull-Tag heisst Pull", pull["kind"], "pull")
ok("… und hat keinen Vergleich", pull["compared_with"] is None)

# Die Satzverteilung: ein Satz zaehlt fuer die Gruppe voll, fuer die
# mitbelastete halb.
groups = {g["key"]: g["sets"] for g in entry["groups"]}
check("Drei Saetze Bankdruecken sind drei Saetze Brust", groups["chest"], 3.0)
check("… und anderthalb Saetze Arme", groups["arms"], 1.5)
# Eine zusaetzliche Uebung ist keine Mehrleistung. Verglichen wird nur ueber
# die Uebungen, die beide Einheiten gemeinsam haben — sonst meldet PULS
# "+122 %", wo schlicht eine Uebung dazukam.
clear()
log(12, "Bankdrücken (Langhantel)", [(10, 50)] * 3)
log(2, "Bankdrücken (Langhantel)", [(10, 55)] * 3)
log(2, "Flys", [(12, 30)] * 3)
entry, _ = find(session_review.reviews(5, TODAY), 2, "Bankdrücken (Langhantel)")
check("Eine neue Uebung wird gezaehlt", entry["new_exercises"], 1)
check("Der Vergleich laeuft nur ueber die gemeinsame Uebung",
      entry["volume_change_pct"], 10)
check("Die Gesamtlast ist trotzdem die ganze", entry["volume"], 2730)
ok("Und die neue Uebung wird erwaehnt",
   "neu dazu" in entry["verdict"], entry["verdict"])
ok("… ohne eine erfundene Steigerung",
   "122" not in entry["verdict"], entry["verdict"])


# ---------------------------------------------------------- Die Woche

clear()
monday = TODAY - dt.timedelta(days=TODAY.weekday())
for off in range(0, (TODAY - monday).days + 1):
    log(off, "Beinpresse", [(12, 60)] * 5)
w = session_review.week(TODAY)
legs = next(g for g in w["groups"] if g["key"] == "legs")
ok("Beine sammeln Saetze", legs["sets"] >= 5, str(legs["sets"]))
check("Der Korridor kommt aus constants.py", w["min"], VOLUME_MIN_SETS)
ok("Gruppen ohne Saetze fehlen nicht, sie stehen auf null",
   all(g["sets"] == 0 for g in w["groups"] if g["key"] in ("chest", "back")))
ok("Und werden als zu wenig markiert",
   all(g["band"] == "low" for g in w["groups"] if g["key"] == "chest"))
ok("Der Satz nennt sie", "Brust" in w["sentence"], w["sentence"])

clear()
w = session_review.week(TODAY)
ok("Ohne Saetze wird das gesagt", "noch keine Sätze" in w["sentence"],
   w["sentence"])
ok("Einzahl bleibt Einzahl", "1 Einheiten" not in w["sentence"], w["sentence"])

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Rueckblick-Tests bestanden.")
