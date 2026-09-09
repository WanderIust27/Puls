"""Tests fuer Referenzfenster und Tagesgang-Korrektur.

Aufruf aus dem Projektordner:  python3 tests/test_body.py
Legt eine Wegwerf-Datenbank an und fasst deine echten Daten nicht an.
"""
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
_tmp = tempfile.mkdtemp(prefix="puls-test-")
os.environ["PULS_DATA_DIR"] = _tmp

from app.db import get_db, init_db, set_setting          # noqa: E402
from app.services import body                            # noqa: E402

failures = []


def check(name, actual, expected, tol=0.01):
    ok = (abs(actual - expected) <= tol) if isinstance(expected, (int, float)) \
        and isinstance(actual, (int, float)) and not isinstance(expected, bool) \
        else actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


init_db()
set_setting("weigh_window_start", "06:00")
set_setting("weigh_window_end", "09:00")

# --- Tagesgang-Modell -----------------------------------------------------
morning = body._diurnal_pct(6.0)
evening = body._diurnal_pct(21.0)
check("Morgens ist der Tiefpunkt", morning, 0.0)
check("Abends deutlich hoeher", evening > 1.4, True)
check("Interpolation dazwischen", morning < body._diurnal_pct(12.0) < evening, True)
check("Zyklisch ueber Mitternacht", body._diurnal_pct(24.5), body._diurnal_pct(0.5))

# --- Fensterzugehoerigkeit ------------------------------------------------
check("06:40 liegt im Fenster", body.in_window("2026-09-08T06:40:00"), True)
check("21:15 liegt nicht im Fenster", body.in_window("2026-09-08T21:15:00"), False)
check("Grenze 09:00 zaehlt noch", body.in_window("2026-09-08T09:00:00"), True)
check("Unbekannte Uhrzeit zaehlt nie",
      body.in_window("2026-09-08T07:00:00", time_known=False), False)

# Fenster ueber Mitternacht darf nicht kaputtgehen (Nachtschicht)
set_setting("weigh_window_start", "22:00")
set_setting("weigh_window_end", "02:00")
check("Fenster ueber Mitternacht: 23:30 drin", body.in_window("2026-09-08T23:30:00"), True)
check("Fenster ueber Mitternacht: 01:00 drin", body.in_window("2026-09-08T01:00:00"), True)
check("Fenster ueber Mitternacht: 12:00 draussen", body.in_window("2026-09-08T12:00:00"), False)
set_setting("weigh_window_start", "06:00")
set_setting("weigh_window_end", "09:00")

# --- Korrektur ------------------------------------------------------------
abend = body.adjust(79.6, "2026-09-08T21:15:00")
check("Abendwert wird nach unten korrigiert", abend < 79.6, True)
check("Korrektur bleibt im realistischen Rahmen (0,5-2,5 kg)",
      0.5 < (79.6 - abend) < 2.5, True)
morgen = body.adjust(78.2, "2026-09-08T07:30:00")
check("Wert im Fenster bleibt praktisch unveraendert", abs(78.2 - morgen) < 0.2, True)
check("Ohne bekannte Uhrzeit wird nicht korrigiert",
      body.adjust(80.0, "2026-09-08T21:00:00", time_known=False), 80.0)
check("Ohne Gewicht kein Ergebnis", body.adjust(None, "2026-09-08T21:00:00"), None)

# --- Mehrere Messungen pro Tag speichern und wieder loeschen --------------
body.record({"weight_kg": 78.2, "measured_at": "2026-09-08T06:42:00",
             "body_fat_pct": 15.1, "bone_kg": 3.2}, source="miscale")
body.record({"weight_kg": 79.6, "measured_at": "2026-09-08T21:15:00"}, source="miscale")
rows = body.measurements(30)
check("Zwei Messungen am selben Tag gespeichert", len(rows), 2)
check("Morgenmessung als Referenz markiert",
      [r for r in rows if r["measured_at"].endswith("06:42:00")][0]["in_window"], 1)
check("Abendmessung nicht als Referenz",
      [r for r in rows if r["measured_at"].endswith("21:15:00")][0]["in_window"], 0)
check("Knochenmasse gespeichert",
      [r for r in rows if r["bone_kg"]][0]["bone_kg"], 3.2)

# Dieselbe Messung erneut melden darf keine Dublette erzeugen
body.record({"weight_kg": 78.3, "measured_at": "2026-09-08T06:42:00"}, source="miscale")
check("Erneute Meldung aktualisiert statt zu duplizieren", len(body.measurements(30)), 2)

target = body.measurements(30)[0]["id"]
check("Messung loeschbar", body.delete(target), True)
check("Nach dem Loeschen eine weniger", len(body.measurements(30)), 1)
check("Unbekannte id meldet sauber Fehlschlag", body.delete(999999), False)

# --- Messung ohne Uhrzeit (Altbestand, CSV-Import) ------------------------
body.record({"weight_kg": 77.0, "day": "2026-09-01"}, source="import")
alt = [r for r in body.measurements(30) if r["source"] == "import"][0]
check("Import ohne Uhrzeit: time_known=0", alt["time_known"], 0)
check("Import ohne Uhrzeit: nicht im Fenster", alt["in_window"], 0)
check("Import ohne Uhrzeit: unkorrigiert uebernommen", alt["weight_adj_kg"], 77.0)

# --- Persoenliche Kalibrierung -------------------------------------------
with get_db() as db:
    db.execute("DELETE FROM body_metrics")

check("Ohne Messpaare bleibt es beim Standardmodell", body.personal_factor(), 1.0)

# Zwoelf Tage mit Morgen- und Abendmessung; der Koerper schwankt doppelt so
# stark wie das Standardmodell annimmt.
base = dt.date.today() - dt.timedelta(days=12)
model_delta = (body._diurnal_pct(21.0) - body._diurnal_pct(7.5)) / 100 * 78.0
for i in range(12):
    day = (base + dt.timedelta(days=i)).isoformat()
    body.record({"weight_kg": 78.0, "measured_at": f"{day}T07:00:00"}, source="miscale")
    body.record({"weight_kg": 78.0 + model_delta * 2,
                 "measured_at": f"{day}T21:00:00"}, source="miscale")
factor = body.personal_factor()
check("Kalibrierung erkennt die staerkere Schwankung",
      factor > 1.2, True)
# Nach oben gedeckelt, und das mit Absicht: Ein Koerper, der zweieinhalbmal so
# stark schwankt wie das Modell, ist keine Eigenheit, sondern ein Artefakt aus
# verrauschten Messpaaren — und eine Umrechnung, die groesser ist als der
# Unterschied, den man messen wollte, schadet mehr als sie nutzt.
check("Der Faktor bleibt im plausiblen Rahmen",
      body.FACTOR_RANGE[0] <= factor <= body.FACTOR_RANGE[1], True)
check("Die Umrechnung selbst ist gedeckelt",
      abs(body.adjust(78.0, f"{dt.date.today().isoformat()}T23:30:00", factor=99) - 78.0)
      <= 78.0 * body.MAX_ADJUST_PCT / 100 + 0.01, True)

# --- Trend und Zusammenfassung -------------------------------------------
s = body.summary()
check("Aktuelles Gewicht ermittelt", s["current_kg"] is not None, True)
check("Trend nutzt Referenzmessungen",
      all(p["measured"] for p in s["points"] if p["weight_kg"]), True)
check("Trendwert entspricht der Morgenmessung", s["current_kg"], 78.0, tol=0.3)
d = s["discipline"]
check("Messdisziplin gezaehlt", d["total"], 24)
check("Haelfte im Fenster", d["in_window"], 12)
check("Hinweis bei schlechter Disziplin", bool(d["hint"]), True)
check("Fenster wird lesbar ausgegeben", d["window"], "06:00–09:00")

# --- Neuberechnung nach Fensteraenderung ---------------------------------
set_setting("weigh_window_start", "20:00")
set_setting("weigh_window_end", "22:00")
body.recompute()
d2 = body.discipline()
check("Nach Fensterwechsel zaehlen die Abendmessungen", d2["in_window"], 12)

if failures:
    print(f"\n{len(failures)} Test(s) fehlgeschlagen:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\nAlle Koerperdaten-Tests bestanden.")
