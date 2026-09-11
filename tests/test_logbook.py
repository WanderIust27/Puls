"""Tests fuer das Nachtragen von Trainings in Worten.

Der Kern: Was jemand hinschreibt, muss als dieselben Saetze in der Datenbank
landen — und keine Zahl darf dabei entstehen, die im Text nicht steht.

Aufruf:  python3 tests/test_logbook.py
"""
import datetime as dt
import os
import re
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


# -------------------------------------------- Zuordnung: der harte Fall
#
# Genau dieser Satz kam frueher vollstaendig falsch an: „Rückenstrecker" wurde
# zu „Ausfallschritte" (deren Alias „lunge" steckt in „wiederho-lunge-n"),
# „Rudern am Kabelzug" landete beim Rudergeraet, und aus „drei Sätze 40 kg 15"
# wurde eine Uebung namens „Deadlifts langhantel 15" mit einem Satz.

HARD = ("Gestern habe ich deadlifts mit der langhantel drei sätze 40 kg 15, "
        "Rückenstrecker 3 mal 15 wiederholungen mit eigenkörpergewicht, dazu "
        "unterstützter Klimzug mit 3 mal 60 kg, 10 wiederholungen, und Rudern "
        "am Kabelzug mit 50 kg 15 wdh. Dazu noch Dips 3 sätze a 7 wiederholungen.")

hard = logbook.preview(HARD, TODAY)
got = [(i["name"], i["summary"]) for i in hard["items"]]
check("Fünf Übungen erkannt", len(got), 5)
check("Zuordnung stimmt", [name for name, _ in got],
      ["Kreuzheben (Langhantel)", "Rückenstrecker (Gerät)",
       "Klimmzüge an der Maschine",
       "Rudern am Kabelzug", "Dips"])
check("Kreuzheben: drei Sätze zu 15 mit 40 kg", got[0][1],
      "15× 40 kg · 15× 40 kg · 15× 40 kg")
check("Rückenstrecker ohne Gewicht", got[1][1], "15× · 15× · 15×")
check("Klimmzug mit Unterstützung", got[2][1], "10× 60 kg · 10× 60 kg · 10× 60 kg")
check("Dips dreimal sieben", got[4][1], "7× · 7× · 7×")
check("Nichts unverstanden", hard["unread"], [])
ok("Keine Zahl steht im Namen",
   not any(re.search(r"\d", name) for name, _ in got), str([n for n, _ in got]))
ok("Kein Einheitenwort steht im Namen",
   not any(re.search(r"wiederholung|sätze|wdh|kilo", name, re.I) for name, _ in got))
ok("Eigenkörpergewicht ist kein Namensteil",
   "gewicht" not in got[1][0].lower(), got[1][0])

# Teilwörter dürfen nicht mehr greifen: Das war die Ursache des schlimmsten
# Fehlgriffs.
lunge = logbook.find_exercise("wiederholungen")
ok("„wiederholungen“ ist keine Übung", lunge is None,
   lunge["name"] if lunge else "—")

# Ein genanntes Gerät widerspricht: Kabelzug ist nicht Kurzhantel.
for phrase, expected in (("Rudern am Kabelzug", "Rudern am Kabelzug"),
                         ("Kurzhantel-Rudern", "Kurzhantel-Rudern einarmig"),
                         ("Latzug", "Latziehen"),
                         ("Bankdrücken", None)):
    hit = logbook.find_exercise(phrase)
    check(f"„{phrase}“", hit["name"] if hit else None, expected)

# Tippfehler dürfen sein.
typo = logbook.find_exercise("Klimzüge")
ok("Ein Tippfehler bleibt erkennbar", typo is not None and "Klimmzüge" in typo["name"],
   typo["name"] if typo else "—")

# Umlaut oder ue — beides muss denselben Alias finden.
check("„ü“ und „ue“ sind dasselbe Wort", logbook.canon("Rückenstrecker"),
      logbook.canon("Rueckenstrecker"))


# --------------------------------------- Eine Korrektur bleibt eine Korrektur

pv2 = logbook.preview("Heute Rückenstrecker 3x15", TODAY)
first = pv2["items"][0]
check("Erst das Gerät", first["name"], "Rückenstrecker (Gerät)")
ok("Die Auswahl steht daneben", len(first["alternatives"]) >= 2,
   str([a["name"] for a in first["alternatives"]]))
boden = next(a for a in first["alternatives"] if "Boden" in a["name"])
first["exercise_id"] = boden["id"]
learned = logbook.commit(pv2["day"], [first], [])
ok("Die Schreibweise wird gemerkt", bool(learned["learned"]), str(learned["learned"]))
after = logbook.preview("Heute Rückenstrecker 3x15", TODAY)["items"][0]
check("Beim nächsten Mal sitzt sie", after["name"], "Rückenstrecken am Boden")
check("… und gilt als sicher", after["confidence"], "sicher")


# ------------------------------- Unterstuetzte Uebungen laufen andersherum
#
# An der Klimmzugmaschine ist das Gewicht die Hilfe: 60 kg heisst, sie nimmt
# dir 60 kg ab. Mehr Kilo sind dort weniger Anstrengung — die Fortschreibung
# muss die Richtung drehen, sonst schlaegt sie nach einem zu schweren Satz
# noch mehr Hilfe als Steigerung vor.

assist = logbook.find_exercise("unterstützter Klimmzug")
ok("Die Klimmzugmaschine ist eine eigene Übung",
   assist is not None and assist["name"] == "Klimmzüge an der Maschine",
   assist["name"] if assist else "—")
check("… und ist als unterstützt gekennzeichnet", bool(assist["assisted"]), True)
check("Das Band bleibt davon unberührt",
      bool(logbook.find_exercise("Klimmzüge mit Band")["assisted"]), False)

hard_day = (TODAY - dt.timedelta(days=5)).isoformat()
easy_day = (TODAY - dt.timedelta(days=4)).isoformat()
for index, (day, reps, weight) in enumerate(((hard_day, 10, 60.0),
                                             (easy_day, 14, 45.0))):
    for set_index in range(1, 4):
        ex_lib.record_set(assist["id"], reps=reps, weight_kg=weight, day=day,
                          set_index=set_index, source="text")

too_hard = ex_lib.propose_for_day(hard_day)[0]
check("Zu schwer heisst: mehr Hilfe", too_hard["to_weight"], 65.0)
ok("… und sagt das auch so", "Unterstützung" in too_hard["reason"],
   too_hard["reason"])
easy = ex_lib.propose_for_day(easy_day)[0]
check("Locker geschafft heisst: diese Hilfe gilt ab jetzt", easy["to_weight"], 45.0)
check("… bei zehn Wiederholungen", easy["to_reps"], 10)

# Zur Gegenprobe: ohne das Kennzeichen laeuft es wie gewohnt herum.
normal = logbook.find_exercise("Beinpresse")
for set_index in range(1, 4):
    ex_lib.record_set(normal["id"], reps=9, weight_kg=100.0, day=hard_day,
                      set_index=set_index, source="text")
plain = next(p for p in ex_lib.propose_for_day(hard_day)
             if p["name"] == "Beinpresse")
check("Bei normalen Übungen bleibt es beim Minus", plain["to_weight"], 95.0)


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
mine = next((s for s in sessions if s["day"] == pv["day"]), None)
ok("Am richtigen Tag", mine is not None, str([s["day"] for s in sessions]))
check("Mit allen Übungen", len(mine["exercises"]), 5)
ok("Jede Übung fasst ihre Sätze zusammen",
   all(e["summary"] for e in mine["exercises"]),
   mine["exercises"][0]["summary"])
ok("Die Tage stehen neueste zuerst",
   [s["day"] for s in sessions] == sorted((s["day"] for s in sessions), reverse=True))


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
