"""Tests fuer die Laufauswertung — Puls, VO2max, Laufform, Tipps.

Der Kern ist ueberall derselbe: Jede Zahl muss aus den Daten folgen, und jeder
Tipp muss die Zahl nennen, aus der er folgt. Ein Tipp ohne Zahl ist ein
Ratschlag aus dem Internet; ein Tipp mit falscher Zahl ist schlimmer als
keiner.

Aufruf:  python3 tests/test_run_coach.py
"""
import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

from app.constants import EASY_SHARE_TARGET                      # noqa: E402
from app.db import get_db, init_db, set_setting                  # noqa: E402
from app.services import run_coach                               # noqa: E402

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


def clear():
    with get_db() as db:
        db.execute("DELETE FROM activities")
        db.execute("DELETE FROM daily_metrics")


def run(offset, km=8.0, pace_s=330, hr=140, *, zones=None, name="Lauf", **extra):
    """Einen Lauf ablegen. Tempo in Sekunden je Kilometer, damit die Dauer passt."""
    day = TODAY - dt.timedelta(days=offset)
    fields = dict(sport="running", source="test", name=name,
                  start_time=f"{day.isoformat()}T07:00:00",
                  distance_m=km * 1000, duration_s=int(km * pace_s), avg_hr=hr,
                  **extra)
    if zones:
        fields["hr_zones_json"] = json.dumps({str(k): v for k, v in zones.items()})
    keys = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    with get_db() as db:
        db.execute(f"INSERT INTO activities ({keys}) VALUES ({marks})",
                   list(fields.values()))


def metric(offset, **fields):
    day = (TODAY - dt.timedelta(days=offset)).isoformat()
    keys = ", ".join(fields)
    marks = ", ".join("?" for _ in fields)
    with get_db() as db:
        db.execute(
            f"INSERT INTO daily_metrics (day, {keys}) VALUES (?, {marks}) "
            f"ON CONFLICT(day) DO UPDATE SET "
            + ", ".join(f"{k}=excluded.{k}" for k in fields),
            [day, *fields.values()])


# ------------------------------------------------------------------ Leerlauf

clear()
view = run_coach.overview(TODAY)
check("Ohne Laeufe kommt nichts heraus", view["runs"], 0)
ok("Ohne Laeufe steht ein Hinweis da", bool(view.get("hint")))


# -------------------------------------------------------------------- VO2max

clear()
# Zwoelf Wochen mit steigender Schaetzung. Je Woche zwei Laeufe, der zweite
# jeweils schwaecher — der Wochenbestwert muss den hoeheren nehmen.
for week in range(12):
    base = 44.0 + week * 0.4
    run(week * 7 + 1, vo2max=base)
    run(week * 7 + 4, vo2max=base - 2.0)
set_setting("body_age", "24")
set_setting("body_sex", "male")

data = run_coach._read(TODAY)
v = run_coach.vo2max(data, TODAY)
check("Aktueller Wert ist der letzte gemessene", v["value"], 44.0)
check("Er kommt von der Uhr", v["source"], "garmin")
check("44 gilt fuer einen 24-Jaehrigen als gut", v["band"], "gut")
weekly = [p["value"] for p in v["points"]]
ok("Der Wochenwert ist der bessere der beiden Laeufe",
   all(abs(weekly[i] - (44.0 + (11 - i) * 0.4)) < 0.05 for i in range(len(weekly))),
   str(weekly))
ok("Der Verlauf zeigt einen Rueckgang", v["change"]["delta"] < 0,
   str(v["change"]))
ok("Ein fallender Wert wird als solcher benannt", "gefallen" in v["lead"], v["lead"])

# Die Einordnung muss mit dem Alter wandern: derselbe Wert, aelterer Mensch.
check("44 gilt fuer einen 55-Jaehrigen als sehr gut",
      run_coach._norm_band(44.0, 55, "male"), "sehr gut")
check("Unter der untersten Grenze ist schwach",
      run_coach._norm_band(30.0, 24, "male"), "schwach")
check("Ueber der obersten Grenze ist ausgezeichnet",
      run_coach._norm_band(62.0, 24, "male"), "ausgezeichnet")

# Prognosen: laenger darf nie schneller sein als kuerzer.
paces = [p["pace_s"] for p in v["predictions"]]
ok("Je laenger die Distanz, desto langsamer das Tempo",
   paces == sorted(paces), str(paces))
labels = [p["label"] for p in v["predictions"]]
check("Drei Distanzen werden prognostiziert", labels,
      ["5 km", "10 km", "Halbmarathon"])

# Ohne Uhrenwert muss der Cooper-Test einspringen.
clear()
run(3, km=8.0)
set_setting("cooper_distance_m", "2600")
set_setting("last_run_benchmark", (TODAY - dt.timedelta(days=20)).isoformat())
v2 = run_coach.vo2max(run_coach._read(TODAY), TODAY)
check("Ohne Uhrenwert rechnet der Cooper-Test", v2["source"], "cooper")
ok("Der Cooper-Wert stimmt mit der Formel ueberein",
   abs(v2["value"] - (2600 - 504.9) / 44.73) < 0.1, str(v2["value"]))
ok("Die Herkunft steht im Satz", "Cooper" in v2["lead"], v2["lead"])

set_setting("cooper_distance_m", "")
clear()
run(3, km=8.0)
v3 = run_coach.vo2max(run_coach._read(TODAY), TODAY)
check("Ohne jede Grundlage bleibt der Wert leer", v3["value"], None)
ok("Stattdessen steht da, wie man zu einem kommt", "Cooper-Test" in v3["hint"])


# ---------------------------------------------------------------------- Puls

clear()
# Vier Wochen ueberwiegend locker: 80 % der Zeit in Zone 1-2.
for i in range(1, 25, 2):
    run(i, zones={1: 600, 2: 1800, 3: 480, 4: 120, 5: 0})
p = run_coach.pulse(run_coach._read(TODAY), TODAY)
check("Der lockere Anteil wird richtig gerechnet", p["zones"]["easy_share"], 80)
check("Der harte Anteil auch", p["zones"]["hard_share"], 4)
check("Das Ziel kommt aus constants.py", p["zones"]["target"],
      round(EASY_SHARE_TARGET * 100))
ok("Bei erreichtem Ziel wird das gesagt",
   "funktioniert" in p["zones"]["sentence"], p["zones"]["sentence"])

clear()
# Der klassische Fehler: alles im mittleren Bereich.
for i in range(1, 25, 2):
    run(i, zones={1: 120, 2: 480, 3: 1800, 4: 600, 5: 0})
p = run_coach.pulse(run_coach._read(TODAY), TODAY)
ok("Der Mitteltempo-Fehler wird benannt",
   "häufigste Fehler" in p["zones"]["sentence"], p["zones"]["sentence"])

# Ruhepuls: sieben Tage gegen die drei Wochen davor.
clear()
run(2, km=8.0)
for i in range(8, 29):
    metric(i, resting_hr=50)
for i in range(0, 8):
    metric(i, resting_hr=55)
p = run_coach.pulse(run_coach._read(TODAY), TODAY)
check("Der Ruhepuls ist der Schnitt der letzten Tage", p["resting"]["value"], 55)
check("Der Vergleich zum Monat davor stimmt", p["resting"]["delta"], 5.0)
ok("Ein Sprung nach oben wird als Warnung formuliert",
   "lockerer" in p["resting"]["sentence"], p["resting"]["sentence"])

clear()
run(2, km=8.0)
for i in range(8, 29):
    metric(i, resting_hr=55)
for i in range(0, 8):
    metric(i, resting_hr=50)
p = run_coach.pulse(run_coach._read(TODAY), TODAY)
ok("Ein Rueckgang wird als Fortschritt gelesen",
   "Grundlage greift" in p["resting"]["sentence"], p["resting"]["sentence"])

# Hoechster gemessener Puls.
clear()
run(5, km=8.0, max_hr=178)
run(12, km=8.0, max_hr=191)
run(40, km=8.0, max_hr=185)
p = run_coach.pulse(run_coach._read(TODAY), TODAY)
check("Der hoechste Puls ist der hoechste", p["max_seen"]["value"], 191)
check("Und er kennt seinen Tag", p["max_seen"]["day"],
      (TODAY - dt.timedelta(days=12)).isoformat())
ok("Auch diese Zeile hat einen Satz — sonst steht ein leerer Pfeil da",
   "191" in (p["max_seen"].get("sentence") or ""), p["max_seen"].get("sentence"))

# Effizienz: gleiches Tempo bei weniger Puls muss besser sein.
clear()
for i in range(30, 56, 3):
    run(i, km=8.0, pace_s=330, hr=150)
for i in range(2, 28, 3):
    run(i, km=8.0, pace_s=330, hr=140)
p = run_coach.pulse(run_coach._read(TODAY), TODAY)
ok("Weniger Puls bei gleichem Tempo ist ein Plus",
   p["efficiency"]["change_pct"] > 5, str(p["efficiency"]["change_pct"]))
ok("Und wird auch so benannt",
   "weniger Puls" in p["efficiency"]["sentence"], p["efficiency"]["sentence"])

# Umfang und die Grenze fuer den naechsten langen Lauf.
clear()
run(3, km=10.0)
run(9, km=6.0)
p = run_coach.pulse(run_coach._read(TODAY), TODAY)
check("Der laengste Lauf der vier Wochen", p["volume"]["longest"], 10.0)
check("Die Grenze sind 110 % davon", p["volume"]["long_run_limit"], 11.0)
check("Kilometer pro Woche", p["volume"]["km_per_week"], 4.0)

# Zonendaten unter fuenf Minuten sind Rauschen und zaehlen nicht mit.
clear()
run(3, km=8.0, zones={1: 60, 2: 60})
p = run_coach.pulse(run_coach._read(TODAY), TODAY)
ok("Zu kurze Zonendaten werden verworfen", "zones" not in p)


# ------------------------------------------------------------------ Laufform

clear()
for i in range(1, 25, 2):
    run(i, km=8.0, avg_cadence=176, ground_contact_ms=235, vertical_ratio=7.2,
        vertical_osc_cm=8.4, avg_stride_m=1.32, avg_power=265)
rows = {r["key"]: r for r in run_coach.form(run_coach._read(TODAY), TODAY)}
check("Die Kadenz kommt an", rows["avg_cadence"]["value"], 176)
check("Eine gute Kadenz ist gruen", rows["avg_cadence"]["band"], "good")
check("Ein kurzer Bodenkontakt auch", rows["ground_contact_ms"]["band"], "good")
check("Ein niedriges vertikales Verhaeltnis auch",
      rows["vertical_ratio"]["band"], "good")
check("Schrittlaenge hat keinen Sollwert", rows["avg_stride_m"]["band"], "info")
ok("Und deshalb auch keine Referenz", rows["avg_stride_m"]["reference"] is None)
ok("Bei gutem Wert steht keine Ermahnung", rows["avg_cadence"]["note"] == "")

clear()
for i in range(1, 25, 2):
    run(i, km=8.0, avg_cadence=152, ground_contact_ms=330, vertical_ratio=11.5)
rows = {r["key"]: r for r in run_coach.form(run_coach._read(TODAY), TODAY)}
check("Eine zu niedrige Kadenz faellt auf", rows["avg_cadence"]["band"], "warn")
ok("Und bekommt einen konkreten Rat",
   "kürzere" in rows["avg_cadence"]["note"], rows["avg_cadence"]["note"])
check("Langer Bodenkontakt faellt auf", rows["ground_contact_ms"]["band"], "warn")
ok("Der Rat dazu zeigt auf die Schrittfrequenz",
   "Schrittfrequenz" in rows["ground_contact_ms"]["note"])

# Laeufe unter zwei Kilometern dominieren sonst den Schnitt.
clear()
run(2, km=1.0, avg_cadence=140)
run(4, km=8.0, avg_cadence=178)
rows = {r["key"]: r for r in run_coach.form(run_coach._read(TODAY), TODAY)}
check("Kurze Laeufe zaehlen nicht in die Form", rows["avg_cadence"]["value"], 178)


# ------------------------------------------------------------------- Tipps

def tips_for(view):
    return {t["title"]: t for t in view["tips"]}


clear()
for i in range(1, 25, 2):
    run(i, zones={1: 120, 2: 480, 3: 1800, 4: 600, 5: 0}, avg_cadence=176)
view = run_coach.overview(TODAY)
titles = list(tips_for(view))
ok("Zu schnelle lockere Laeufe stehen ganz oben",
   "langsamer" in titles[0], str(titles))
first = view["tips"][0]
ok("Der Tipp nennt die gemessene Zahl", "%" in first["because"], first["because"])
ok("Es sind nie mehr als fuenf", len(view["tips"]) <= run_coach.MAX_TIPS,
   str(len(view["tips"])))

# Kein harter Lauf in vier Wochen.
clear()
for i in range(1, 25, 2):
    run(i, zones={1: 1200, 2: 1800, 3: 0, 4: 0, 5: 0})
view = run_coach.overview(TODAY)
ok("Der fehlende Temporeiz wird angesprochen",
   any("harter Lauf" in t for t in tips_for(view)), str(list(tips_for(view))))

# Zu viel hart.
clear()
for i in range(1, 25, 2):
    run(i, zones={1: 300, 2: 300, 3: 400, 4: 1000, 5: 500})
view = run_coach.overview(TODAY)
ok("Zu viel Intensitaet wird angesprochen",
   any("harten Bereich" in t for t in tips_for(view)), str(list(tips_for(view))))

# Gestiegener Ruhepuls.
clear()
for i in range(1, 25, 2):
    run(i, zones={1: 1200, 2: 1800, 3: 200, 4: 200, 5: 0})
for i in range(8, 29):
    metric(i, resting_hr=48)
for i in range(0, 8):
    metric(i, resting_hr=54)
view = run_coach.overview(TODAY)
t = tips_for(view).get("Ruhepuls ist gestiegen")
ok("Der gestiegene Ruhepuls wird zum Thema", t is not None,
   str(list(tips_for(view))))
if t:
    ok("Mit dem gemessenen Wert im Beleg", "54 bpm" in t["because"], t["because"])

# Passt alles, muss auch das gesagt werden — und nicht irgendein Tipp erfunden.
clear()
for i in range(1, 25, 2):
    run(i, zones={1: 900, 2: 1500, 3: 200, 4: 300, 5: 100},
        avg_cadence=176, ground_contact_ms=238, vertical_ratio=7.4)
for i in range(0, 29):
    metric(i, resting_hr=50)
view = run_coach.overview(TODAY)
ok("Ohne Befund wird nichts erfunden",
   any("Nichts zu korrigieren" in t or "Was bis zum Ziel fehlt" in t
       for t in tips_for(view)), str(list(tips_for(view))))

# Jeder Tipp traegt seinen Beleg.
for t in view["tips"]:
    ok(f"Tipp „{t['title']}“ nennt seine Zahl", bool(t["because"]))


# --------------------------------------------------------------- Gesamtsicht

clear()
for i in range(1, 40, 3):
    run(i, km=8.0, vo2max=47.0, avg_cadence=174, ground_contact_ms=245,
        vertical_ratio=7.8, max_hr=180,
        zones={1: 900, 2: 1500, 3: 300, 4: 200, 5: 0})
for i in range(0, 29):
    metric(i, resting_hr=51)
view = run_coach.overview(TODAY)
for key in ("vo2max", "pulse", "form", "tips"):
    ok(f"Die Ansicht liefert „{key}“", key in view)
ok("Die Laufzahl stimmt", view["runs"] == 13, str(view["runs"]))
ok("Die Prognose ist eine Zeit",
   view["vo2max"]["predictions"][1]["time_s"] > 0)
ok("Das Ziel wird eingeordnet", view["vo2max"]["goal"] is not None)

# Laeufe ohne Uhrendaten sind kein Befund, sondern ein fehlender. "Nichts zu
# korrigieren" waere hier gelogen.
clear()
for i in range(1, 25, 3):
    run(i, km=8.0, hr=None)
view = run_coach.overview(TODAY)
t = view["tips"][0]
check("Ohne Uhrendaten wird nichts bewertet", t["title"], "Noch nichts zu bewerten")
ok("… und der Grund steht dabei", "ohne Puls" in t["because"], t["because"])


# ------------------------------------ Derselbe Wert im Reiter und im Prompt

# Das Modell bekommt die Zahlen als fertigen Text. Wenn dort eine andere
# VO2max steht als im Reiter, widerspricht PULS sich in derselben Antwort.
from app.services import facts                                   # noqa: E402

clear()
for i in range(1, 60, 3):
    run(i, km=8.0, vo2max=47.0 + (60 - i) / 40, max_hr=175,
        zones={1: 600, 2: 1200, 3: 500, 4: 100, 5: 0})
for i in range(0, 29):
    metric(i, resting_hr=54 if i < 7 else 50)

view = run_coach.overview(TODAY)
block = facts.computed_block(TODAY)
vo2_text = str(view["vo2max"]["value"]).replace(".", ",")
ok("Reiter und Prompt nennen dieselbe VO2max", vo2_text in block,
   [l for l in block.split(chr(10)) if "VO2max" in l])
share = f"{view['pulse']['zones']['easy_share']} %"
ok("… und dieselbe Intensitätsverteilung", share in block,
   [l for l in block.split(chr(10)) if "Intensität" in l])
ok("… und denselben Ruhepuls",
   f"{view['pulse']['resting']['value']} bpm" in block,
   [l for l in block.split(chr(10)) if "Ruhepuls" in l])

# Ohne Laeufe darf keine Zeile entstehen — eine Null liest das Modell als
# Messwert und raet darauf hin.
clear()
ok("Ohne Läufe steht nichts im Prompt", facts.running_state(TODAY) is None)


print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Lauf-Tests bestanden.")
