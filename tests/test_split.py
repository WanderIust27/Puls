"""Tests fuer Push, Pull und Beine.

Zwei Dinge muessen stimmen, sonst ist der Split schlimmer als kein Split:

* Jede Uebung muss auf der richtigen Seite landen. Die Beinpresse enthaelt
  "press" und der Hamstring-Curl "curl" — wer nur auf den Namen schaut, legt
  beide falsch.
* Die Reihenfolge muss dem folgen, was tatsaechlich trainiert wurde. Wer den
  Push-Tag hat ausfallen lassen, macht Push nach.

Aufruf:  python3 tests/test_split.py
"""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.constants import SPLIT_BY_DAYS                         # noqa: E402
from app.db import get_db, init_db, set_setting                 # noqa: E402
from app.services import exercises as ex_lib                    # noqa: E402
from app.services import planner, split                         # noqa: E402

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


def clear():
    with get_db() as db:
        db.execute("DELETE FROM exercise_sets")


def log(offset, name, sets=3, reps=10, weight=40.0):
    day = (TODAY - dt.timedelta(days=offset)).isoformat()
    for i in range(sets):
        ex_lib.record_set(LIB[name]["id"], reps=reps, weight_kg=weight,
                          day=day, set_index=i, source="manual")


# -------------------------------------------------- Druecken oder Ziehen

CASES = [
    # Die beiden, an denen eine reine Wortliste scheitert.
    ("Beinpresse", "legs"),
    ("Hamstring-Curls mit Band", "legs"),
    # Die Gruppe reicht nicht: "arms" ist beides.
    ("Trizepsdrücken", "push"),
    ("Abwechselnde Bizeps-Curls mit Kurzhantel im Stehen", "pull"),
    # Die Gruppe liegt daneben: Aufrechtes Rudern zaehlt zu den Schultern.
    ("Aufrechtes Rudern mit Band", "pull"),
    # Der Rest, der eindeutig ist.
    ("Klimmzüge", "pull"),
    ("Latziehen", "pull"),
    ("Kreuzheben (Langhantel)", "pull"),
    ("Bankdrücken (Langhantel)", "push"),
    ("Dips", "push"),
    ("Schulterdrücken (Maschine)", "push"),
    ("Kettlebell Swings", "legs"),
    ("Sit-ups", "legs"),
]
for name, want in CASES:
    check(f"{name}", split.pattern_of(LIB[name]), want)

ok("Aufwaermen gehoert in jeden Split",
   split.pattern_of({"name": "Armkreise", "muscle_group": "shoulders",
                     "slot": "warmup"}) is None)
ok("Dehnen auch",
   split.pattern_of({"name": "Lat-Dehnung", "muscle_group": "back",
                     "slot": "stretch"}) is None)


# ------------------------------------------------- Welcher Split bei wie vielen Tagen

set_setting("gym_split", "auto")
for days, want in ((2, "fullbody"), (3, "fullbody"), (4, "upper_lower"),
                   (6, "ppl")):
    got = split.chosen_split(["Mo"] * days)
    check(f"{days} Tage ergeben {want}", got["key"], want)
check("Die Tabelle kommt aus constants.py", SPLIT_BY_DAYS[3], "fullbody")

# Bei drei Tagen ist Ganzkoerper die Vorgabe — aber wer PPL will, bekommt PPL.
set_setting("gym_split", "ppl")
got = split.chosen_split(["Mo", "Mi", "Fr"])
check("Eingestellt schlaegt abgeleitet", got["key"], "ppl")
check("… und sagt das auch", got["mode"], "manuell")
ok("Der Grund steht dabei", "eingestellt" in got["why"], got["why"])


# ------------------------------------------------------------ Die Rotation

set_setting("gym_split", "ppl")
set_setting("gym_days", json.dumps(["Mo", "Mi", "Fr"]))

clear()
nxt = split.next_day(TODAY)
check("Ohne Verlauf geht es bei Push los", nxt["day"]["key"], "push")
ok("… und sagt warum", "zuordnen" in nxt["because"], nxt["because"])

clear()
log(3, "Bankdrücken (Langhantel)")
log(3, "Schulterdrücken (Maschine)")
nxt = split.next_day(TODAY)
check("Nach Push kommt Pull", nxt["day"]["key"], "pull")
ok("Die letzte Einheit wird benannt", "Push" in nxt["because"], nxt["because"])
check("… und sie ist bekannt", nxt["last"]["key"], "push")

clear()
log(5, "Bankdrücken (Langhantel)")
log(2, "Klimmzüge", weight=0.0)
log(2, "Rudern am Kabelzug")
check("Nach Pull kommen die Beine",
      split.next_day(TODAY)["day"]["key"], "legs")

clear()
log(1, "Beinpresse")
log(1, "Sit-ups", weight=0.0)
check("Nach den Beinen wieder Push",
      split.next_day(TODAY)["day"]["key"], "push")

# Der Kern: Eine ausgefallene Einheit darf nicht uebersprungen werden. Nach
# einem Push-Tag ist Pull dran — auch wenn seither zwei Wochen vergangen sind.
clear()
log(12, "Bankdrücken (Langhantel)")
nxt = split.next_day(TODAY)
check("Ein verpasster Tag wird nicht uebersprungen", nxt["day"]["key"], "pull")
ok("Der Abstand steht im Satz", "12 Tagen" in nxt["because"], nxt["because"])

# Eine halb/halb-Einheit sagt ueber die Rotation nichts — dann lieber von vorn.
clear()
log(2, "Bankdrücken (Langhantel), ".rstrip(", "))
log(2, "Klimmzüge", weight=0.0)
log(2, "Beinpresse")
nxt = split.next_day(TODAY)
ok("Eine gemischte Einheit ordnet sich nicht zu",
   nxt["last"] is None or nxt["day"]["key"] == "push", str(nxt["last"]))

# Zu wenige Saetze sind keine Einheit.
clear()
log(1, "Bankdrücken (Langhantel)", sets=1)
nxt = split.next_day(TODAY)
ok("Ein einzelner Satz zaehlt nicht als Einheit", nxt["last"] is None)

# Ganzkoerper hat nichts zu rotieren.
set_setting("gym_split", "fullbody")
nxt = split.next_day(TODAY)
check("Ganzkoerper hat genau einen Tag", nxt["day"]["key"], "full")
ok("… und keine Rotation", len(nxt["days"]) == 1)


# ------------------------------------------------------- Die gebaute Einheit

clear()
for key, day in (("ppl", 0), ("ppl", 1), ("ppl", 2)):
    d = split.SPLITS[key]["days"][day]
    session = planner.build_gym_session(75, split_day=d)
    names = []

    def walk(steps):
        for st in steps:
            if st.get("steps"):
                walk(st["steps"])
            elif st.get("name"):
                names.append(st["name"])
    walk(session["steps"])
    check(f"{d['label']}: die Einheit heisst danach",
          session["split"], d["label"])
    ok(f"{d['label']}: die Dauer stimmt ungefaehr",
       abs(session["minutes"] - 75) <= 8, f"{session['minutes']} min")
    # Die Probe: keine Uebung der anderen Seite darf drin sein.
    wrong = [n for n in names if n in LIB
             and split.pattern_of(LIB[n]) not in (None, *d["patterns"])]
    check(f"{d['label']}: nichts von der anderen Seite", wrong, [])

# Klimmzugarbeit gehoert an den Zugtag und nirgends sonst.
push = planner.build_gym_session(75, split_day=split.SPLITS["ppl"]["days"][0])
pull = planner.build_gym_session(75, split_day=split.SPLITS["ppl"]["days"][1])


def has(session, needle):
    return needle in json.dumps(session["steps"], ensure_ascii=False)


ok("Am Push-Tag keine Klimmzuege", not has(push, "Klimmzüge"))
ok("Am Pull-Tag schon", has(pull, "Klimmzüge"))

# Ohne Split bleibt alles, wie es war.
full = planner.build_gym_session(75)
ok("Ganzkoerper traegt keinen Split-Namen", full["split"] is None)
ok("… und heisst weiterhin Ganzkoerper", "Ganzkörper" in full["name"],
   full["name"])

# Der Hauptteil darf nicht bei fuenf Uebungen aufhoeren, egal wie viele
# angefordert sind — das war der Fehler, der die Push-Einheit verkuerzte.
pool = [e for e in ex_lib.list_exercises(only_active=True)
        if (e.get("slot") or "main") == "main"]
for want in (5, 7, 9):
    got = planner._balance_main(pool, want, ["chest", "shoulders", "arms"])
    check(f"Hauptteil liefert {want} Uebungen", len(got), want)
ok("Und nie dieselbe zweimal",
   len({e["id"] for e in planner._balance_main(pool, 9, [])}) == 9)


# ----------------------------------------------------------- Der Wochenplan

set_setting("gym_split", "ppl")
set_setting("gym_days", json.dumps(["Mo", "Mi", "Fr"]))
clear()
week = [w for w in planner.plan_week(TODAY) if w["sport"] == "strength"]
labels = [w.get("split") for w in week]
check("Die Woche bekommt drei verschiedene Tage",
      len(set(labels)), min(3, len(week)) if week else 0)
ok("… und keiner heisst gleich wie der davor",
   all(labels[i] != labels[i - 1] for i in range(1, len(labels))), str(labels))

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Split-Tests bestanden.")
