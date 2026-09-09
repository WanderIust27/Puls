"""Tests für die Freitext-Mahlzeit und die Nährwerttabelle.

Der heikle Teil ist die Arbeitsteilung: Das Modell darf zerlegen, rechnen darf
es nicht. Diese Suite läuft ohne Modell — sie prüft also genau den Weg, der
auch dann funktionieren muss, wenn Ollama gerade nicht läuft.

Aufruf:  python3 tests/test_food.py
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.db import init_db                                  # noqa: E402
from app.services import food_table, nutrition              # noqa: E402

failures = []


def ok(name, condition, detail=""):
    print(f"{'OK  ' if condition else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def check(name, actual, expected):
    ok(name, actual == expected, f"{actual!r} (erwartet {expected!r})")


init_db()

# --- Die Tabelle ---------------------------------------------------------
check("Genauer Treffer", food_table.lookup("Haferflocken"), "Haferflocken")
check("Groß- und Kleinschreibung egal", food_table.lookup("haferflocken"), "Haferflocken")
check("Umlaute umschrieben", food_table.lookup("muesli"), "Müsli")
check("Synonym", food_table.lookup("hähnchen"), "Hähnchenbrust")
check("Wortbestandteil", food_table.lookup("Hähnchenbrustfilet"), "Hähnchenbrust")
check("Das längere Wort gewinnt", food_table.lookup("vollkornbrot"), "Vollkornbrot")
ok("Unbekanntes bleibt unbekannt", food_table.lookup("Mondgestein") is None)
ok("Leeres ergibt nichts", food_table.lookup("") is None)

hundred = food_table.nutrients("Hähnchenbrust", 100)
check("100 g sind der Tabellenwert", hundred["kcal"], 165)
half = food_table.nutrients("Hähnchenbrust", 50)
ok("Die Hälfte ist die Hälfte", abs(half["kcal"] - hundred["kcal"] / 2) <= 1,
   f"{half['kcal']} statt {hundred['kcal'] / 2}")
ok("Unbekanntes liefert nichts", food_table.nutrients("Mondgestein", 100) is None)

# Jeder Tabelleneintrag muss in sich stimmig sein: Eiweiß und Kohlenhydrate
# 4 kcal/g, Fett 9. Ein Tippfehler in einer Spalte fällt so auf.
schief = []
for name, ((kcal, p, c, f), _syn) in food_table.FOODS.items():
    from_macros = p * 4 + c * 4 + f * 9
    # Alkohol trägt 7 kcal/g und steht in keiner Spalte — daher ausgenommen.
    if name in ("Bier", "Wein"):
        continue
    if abs(from_macros - kcal) > max(45, kcal * 0.2):
        schief.append(f"{name}: {from_macros:.0f} statt {kcal}")
check(f"Alle {len(food_table.FOODS)} Einträge sind in sich stimmig", schief, [])

ok("Keine unsinnigen Werte",
   all(0 <= k <= 900 and 0 <= p <= 100 and 0 <= c <= 100 and 0 <= f <= 100
       for (k, p, c, f), _ in food_table.FOODS.values()))

# --- Freitext ohne Modell ------------------------------------------------
r = nutrition.estimate_from_text("150 g Hähnchenbrust, 80 g Reis und Gemüse")
check("Drei Bestandteile erkannt", len(r["items"]), 3)
check("Menge übernommen", r["items"][0]["grams"], 150.0)
ok("Kalorien gerechnet", 350 < r["total"]["kcal"] < 450, str(r["total"]["kcal"]))
ok("Eiweiß gerechnet", 45 < r["total"]["protein_g"] < 55, str(r["total"]["protein_g"]))
ok("Keine Warnung nötig", r["hint"] is None, str(r["hint"]))
ok("Als stimmig ausgewiesen", r["plausible"])

r = nutrition.estimate_from_text("zwei Eier und ein Vollkornbrot")
names = {i["matched"] for i in r["items"]}
check("Stückzahlen verstanden", names, {"Ei", "Vollkornbrot"})
ei = next(i for i in r["items"] if i["matched"] == "Ei")
check("Zwei Eier sind zwei Portionen", ei["grams"], 120.0)

r = nutrition.estimate_from_text("Pizza")
check("Ein Wort genügt", len(r["items"]), 1)
ok("Übliche Portion angesetzt", r["items"][0]["grams"] == 350.0,
   str(r["items"][0]["grams"]))

r = nutrition.estimate_from_text("Mondgestein mit Sternenstaub")
check("Unbekanntes ergibt keine Zahlen", r["total"]["kcal"], 0)
ok("… und sagt das auch", bool(r["hint"]))
check("Nichts erfunden", r["items"], [])

r = nutrition.estimate_from_text("100 g Reis und Mondgestein")
ok("Teilweise Unbekanntes wird benannt", "Mondgestein" in " ".join(r["unknown"]),
   str(r["unknown"]))
ok("… und der Rest trotzdem gerechnet", r["total"]["kcal"] > 0)
ok("… mit Hinweis, dass etwas fehlt", "Nicht gefunden" in (r["hint"] or ""))

check("Leerer Text ergibt nichts", nutrition.estimate_from_text("")["items"], [])
ok("… mit Hinweis", bool(nutrition.estimate_from_text("")["hint"]))

# Kilogramm und Liter müssen umgerechnet werden.
r = nutrition.estimate_from_text("0,5 kg Kartoffeln")
ok("Kilogramm werden umgerechnet", r["items"][0]["grams"] == 500.0,
   str(r["items"][0]["grams"]))

# Die Summe muss die Summe der Teile sein — nicht eine zweite Schätzung.
r = nutrition.estimate_from_text("100 g Reis, 100 g Hähnchenbrust")
hand = sum(i["kcal"] for i in r["items"])
check("Die Summe ist die Summe der Teile", r["total"]["kcal"], hand)

# --- Buchen --------------------------------------------------------------
r = nutrition.estimate_from_text("150 g Hähnchenbrust und 80 g Reis")
meal = nutrition.add_meal({"name": r["name"], "slot": "lunch", **{
    k: r["total"][k] for k in ("kcal", "protein_g", "carbs_g", "fat_g")}})
day = nutrition.day()
ok("Die Mahlzeit steht im Tag", any(m["id"] == meal["id"] for m in day["meals"]))
ok("… und zählt in die Tagessumme",
   abs(day["total"]["kcal"] - r["total"]["kcal"]) < 1,
   f"{day['total']['kcal']} statt {r['total']['kcal']}")

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Tests bestanden.")
