"""Tests fuer die Koerperwerte.

Die Frage, an der sich alles entscheidet: Von den Kilos, die dazugekommen
sind, wie viel war Muskel? Eine Rechnung, die bei reinem Fettaufbau "so soll
ein Aufbau aussehen" sagt, waere schlimmer als gar keine.

Aufruf:  python3 tests/test_body_coach.py
"""
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import get_db, init_db, set_setting                 # noqa: E402
from app.services import body_coach                            # noqa: E402

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
set_setting("body_height_cm", "184")
set_setting("body_age", "24")
set_setting("body_sex", "male")


def clear():
    with get_db() as db:
        db.execute("DELETE FROM body_metrics")


def weigh(offset, kg, fat_pct=None, **extra):
    """Eine Messung ablegen. Muskel und Magermasse folgen aus Gewicht und Fett."""
    d = TODAY - dt.timedelta(days=offset)
    fields = dict(day=d.isoformat(), measured_at=d.isoformat() + "T07:10:00",
                  time_known=1, in_window=1, weight_kg=round(kg, 2),
                  weight_adj_kg=round(kg, 2), source="miscale", **extra)
    if fat_pct is not None:
        lean = kg * (1 - fat_pct / 100)
        fields.update(body_fat_pct=round(fat_pct, 1), lbm_kg=round(lean, 1),
                      muscle_kg=round(lean * 0.95, 1))
    keys = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    with get_db() as db:
        db.execute(f"INSERT INTO body_metrics ({keys}) VALUES ({marks})",
                   list(fields.values()))


def series(weeks, kg_from, kg_to, fat_from, fat_to, **extra):
    days = weeks * 7
    for i in range(days, -1, -3):
        share = (days - i) / days
        weigh(i, kg_from + (kg_to - kg_from) * share,
              fat_from + (fat_to - fat_from) * share, **extra)


# --------------------------------------------------------------- Leerlauf

clear()
view = body_coach.overview(TODAY)
check("Ohne Messungen kommt nichts heraus", view["measurements"], 0)
ok("… aber ein Hinweis", bool(view.get("hint")))


# ------------------------------------------- Muskel oder Fett: der Kernfall

# Sauberer Aufbau: +2,4 kg, davon der groessere Teil fettfrei.
clear()
series(12, 81.0, 83.4, 16.0, 16.6)
p = body_coach.partition(TODAY)
ok("Fettfreie Masse gestiegen", p["lean_kg"] > 0, str(p["lean_kg"]))
ok("Fett auch, aber weniger", 0 < p["fat_kg"] < p["lean_kg"],
   f"Fett {p['fat_kg']}, fettfrei {p['lean_kg']}")
ok("Der Grossteil war fettfrei", p["lean_share"] >= 55, f"{p['lean_share']} %")
ok("Und das wird auch gesagt", "So soll ein Aufbau aussehen" in p["sentence"],
   p["sentence"])
ok("Die Summe geht auf",
   abs((p["lean_kg"] + p["fat_kg"]) - p["weight_kg"]) < 0.05,
   f"{p['lean_kg']} + {p['fat_kg']} vs {p['weight_kg']}")

# Reiner Fettaufbau: gleiches Gewichtsplus, aber der Fettanteil zieht mit.
clear()
series(12, 81.0, 83.4, 16.0, 19.0)
p = body_coach.partition(TODAY)
ok("Reiner Fettaufbau wird erkannt",
   "Fettaufbau" in p["sentence"] or "Hälfte davon war Fett" in p["sentence"],
   p["sentence"])
ok("… und beschoenigt nichts",
   "So soll ein Aufbau aussehen" not in p["sentence"], p["sentence"])

# Abnehmen mit gehaltener Muskulatur.
clear()
series(12, 86.0, 83.0, 20.0, 17.0)
p = body_coach.partition(TODAY)
ok("Fett runter, Muskel gehalten", "Muskel gehalten" in p["sentence"],
   p["sentence"])

# Gewicht steht, innen bewegt sich trotzdem etwas — die Rekomposition, die
# eine reine Gewichtskurve komplett verschweigt.
clear()
series(12, 82.0, 82.1, 19.0, 16.5)
p = body_coach.partition(TODAY)
ok("Stillstand auf der Waage wird als solcher benannt",
   "praktisch still" in p["sentence"], p["sentence"])
ok("… und die Bewegung darunter gezeigt", p["lean_kg"] > 1.0,
   f"{p['lean_kg']} kg fettfrei")

# Ohne Fettanteil laesst sich nichts aufteilen — dann lieber nichts sagen.
clear()
for i in range(60, -1, -3):
    weigh(i, 82.0)
ok("Ohne Fettanteil keine Aufteilung", body_coach.partition(TODAY) is None)


# --------------------------------------------------------------- Zielgewicht

clear()
series(12, 81.0, 83.0, 16.5, 16.8)
set_setting("goal_text", "Muskeln aufbauen und 10 km unter 60 Minuten")
t = body_coach.target(TODAY)
check("Das Ziel wird aus dem Freitext gelesen", t["goal"], "gain")
lo, hi = t["range_kg"]
ok("Der Korridor ist eine Spanne", lo < hi, f"{lo}–{hi}")
want_hi = round(t["lean_kg"] / (1 - 17 / 100), 1)
ok("Magermasse plus Zielfett ergibt die Obergrenze", abs(hi - want_hi) < 0.2,
   f"{hi} vs {want_hi} (aus {t['lean_kg']} kg fettfrei)")
ok("BMI wird gerechnet", t["bmi"] and 18 < t["bmi"] < 32, str(t.get("bmi")))
ok("FFMI auch", t["ffmi"] and 15 < t["ffmi"] < 28, str(t.get("ffmi")))
ok("Und eingeordnet", "FFMI" in t["ffmi_note"], t["ffmi_note"])
ok("Ein Satz fasst es zusammen", len(t["sentence"]) > 40, t["sentence"])

# Wer deutlich unter dem Korridor liegt und aufbauen will, bekommt eine Dauer.
clear()
series(12, 70.0, 70.4, 12.0, 12.2)
t = body_coach.target(TODAY)
ok("Unter dem Korridor gibt es eine Hochrechnung", t.get("eta") is not None,
   str(t.get("eta")))
if t.get("eta"):
    ok("… mit einer Spanne in Wochen", t["eta"]["weeks"][0] < t["eta"]["weeks"][1],
       str(t["eta"]["weeks"]))
    ok("… und der Rate, aus der sie kommt", "pro Woche" in t["eta"]["text"],
       t["eta"]["text"])

# Die Groesse entscheidet den BMI, nicht das Zielgewicht: Der Korridor kommt
# aus der Magermasse und muss ohne Groessenangabe trotzdem stehen.
set_setting("body_height_cm", "0")
t = body_coach.target(TODAY)
ok("Ohne Groesse trotzdem ein Korridor", t["range_kg"][0] > 0, str(t["range_kg"]))
ok("… aber kein BMI", "bmi" not in t)
set_setting("body_height_cm", "184")


# ------------------------------------------------------------- Die Werte

clear()
series(12, 81.0, 83.0, 16.0, 16.4, water_pct=57.0, bone_kg=3.3, visceral_fat=6.0)
rows = {m["key"]: m for m in body_coach.composition(TODAY)}
for key in ("body_fat_pct", "muscle_kg", "water_pct"):
    ok(f"„{key}" + "“ ist dabei", key in rows, str(sorted(rows)))
check("Ein Fettanteil von 16 gilt als normal", rows["body_fat_pct"]["band"], "good")
ok("Die Referenz steht dabei", "üblich" in rows["body_fat_pct"]["reference"],
   rows["body_fat_pct"]["reference"])
ok("Vier- und Zwoelfwochenvergleich",
   rows["muscle_kg"]["change_4w"] is not None
   and rows["muscle_kg"]["change_12w"] is not None)
ok("Der Verlauf sind Wochenmittel, keine Einzelmessungen",
   all(p["n"] >= 1 for p in rows["muscle_kg"]["points"])
   and len(rows["muscle_kg"]["points"]) <= 14,
   f"{len(rows['muscle_kg']['points'])} Punkte")
# Prozentpunkte, nicht Prozent: "0,4 % mehr Körperfett" waere etwas anderes.
ok("Prozentwerte heissen Prozentpunkte",
   "Prozentpunkte" in rows["body_fat_pct"]["sentence"],
   rows["body_fat_pct"]["sentence"])
# Beim Aufbauen ist ein leicht steigender Fettanteil normal und keine Warnung.
ok("Beim Aufbauen keine Panik wegen 0,4 Punkten",
   "normal" in rows["body_fat_pct"]["sentence"],
   rows["body_fat_pct"]["sentence"])

set_setting("goal_text", "abnehmen und definieren")
rows = {m["key"]: m for m in body_coach.composition(TODAY)}
ok("Beim Abnehmen ist dieselbe Bewegung die falsche Richtung",
   "andere Richtung" in rows["body_fat_pct"]["sentence"],
   rows["body_fat_pct"]["sentence"])
set_setting("goal_text", "Muskeln aufbauen")

# Ein zu hoher Wert muss auffallen.
clear()
series(12, 95.0, 96.0, 29.0, 29.4, water_pct=45.0, visceral_fat=14.0)
rows = {m["key"]: m for m in body_coach.composition(TODAY)}
check("29 % Koerperfett faellt auf", rows["body_fat_pct"]["band"], "warn")
check("Viszeralfett 14 auch", rows["visceral_fat"]["band"], "warn")


# ------------------------------------------------------------ Gesamtansicht

clear()
series(12, 81.0, 83.0, 16.0, 16.5, water_pct=57.0, bone_kg=3.3, visceral_fat=6.0)
view = body_coach.overview(TODAY)
for key in ("composition", "partition", "target", "discipline"):
    ok(f"Die Ansicht liefert „{key}“", view.get(key) is not None)

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Koerperwert-Tests bestanden.")
