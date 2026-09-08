"""Smoke-Test der API: sprechen alle Endpunkte, und stimmen die Daten?

Startet die echte FastAPI-Anwendung gegen eine Wegwerf-Datenbank. Deine
Daten werden nicht angefasst. Nicht installierte Bibliotheken (garminconnect,
fit-tool) werden durch Attrappen ersetzt — sie sind nur im Container noetig.

Aufruf:  python3 tests/test_api.py
"""
import logging
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")
logging.disable(logging.INFO)     # Anwendungs- und HTTP-Logs stoeren hier nur

for name, attrs in (("garminconnect", {"Garmin": type("Garmin", (), {})}),
                    ("garmin_fit_sdk", {"Decoder": object, "Stream": object}),
                    ("fit_tool", {})):
    if name not in sys.modules:
        try:
            __import__(name)
        except ImportError:
            mod = types.ModuleType(name)
            for k, v in attrs.items():
                setattr(mod, k, v)
            sys.modules[name] = mod

from fastapi.testclient import TestClient    # noqa: E402
from app.main import app                     # noqa: E402

failures = []


def check(name, actual, expected, tol=0.01):
    ok = (abs(actual - expected) <= tol) if isinstance(expected, (int, float)) \
        and isinstance(actual, (int, float)) and not isinstance(expected, bool) \
        else actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


with TestClient(app) as client:
    # --- Messungen anlegen, mehrere am selben Tag ------------------------
    r = client.post("/api/body", json={"weight_kg": 78.2,
                                       "measured_at": "2026-09-08T06:42:00",
                                       "body_fat_pct": 15.1, "bone_kg": 3.2})
    check("Morgenmessung angenommen", r.status_code, 200)
    check("Als Referenz erkannt", r.json()["in_window"], 1)

    r = client.post("/api/body", json={"weight_kg": 79.6,
                                       "measured_at": "2026-09-08T21:15:00"})
    check("Abendmessung angenommen", r.status_code, 200)
    check("Nicht als Referenz", r.json()["in_window"], 0)
    check("Abendwert nach unten korrigiert", r.json()["weight_adj_kg"] < 79.6, True)

    rows = client.get("/api/body").json()
    check("Beide Messungen abrufbar", len(rows), 2)

    s = client.get("/api/body/summary").json()
    check("Zusammenfassung liefert Gewicht", s["current_kg"] is not None, True)
    check("Knochenmasse in den letzten Werten", s["latest"]["bone_kg"], 3.2)
    check("Schaetzwerte sind als solche gekennzeichnet",
          "bone_kg" in s["estimated_fields"], True)
    check("Messdisziplin ausgewiesen", s["discipline"]["in_window"], 1)

    # --- Loeschen --------------------------------------------------------
    victim = rows[0]["id"]
    check("Messung loeschbar", client.delete(f"/api/body/{victim}").status_code, 200)
    check("Danach eine weniger", len(client.get("/api/body").json()), 1)
    check("Unbekannte Messung meldet 404",
          client.delete("/api/body/999999").status_code, 404)

    # --- Referenzfenster --------------------------------------------------
    r = client.post("/api/body/window", json={"start": "05:30", "end": "08:30"})
    check("Fenster aenderbar", r.status_code, 200)
    check("Fenster wird zurueckgemeldet", r.json()["window"], "05:30–08:30")
    check("Unsinnige Uhrzeit abgelehnt",
          client.post("/api/body/window",
                      json={"start": "25:99", "end": "08:00"}).status_code, 400)
    check("Uhrzeit ohne Doppelpunkt abgelehnt",
          client.post("/api/body/window",
                      json={"start": "0730", "end": "08:00"}).status_code, 400)

    # --- Waagen-Webhook ---------------------------------------------------
    check("Webhook ohne Token abgewiesen",
          client.post("/api/body/webhook", json={"weight_kg": 78.0}).status_code, 401)
    token = client.get("/api/settings").json().get("api_token")
    r = client.post("/api/body/webhook",
                    json={"weight_kg": 78.0, "bone_kg": 3.1, "visceral_fat": 7.0,
                          "measured_at": "2026-09-09T06:50:00"},
                    headers={"X-Puls-Token": token})
    check("Webhook mit Token angenommen", r.status_code, 200)
    check("Webhook erkennt das Referenzfenster", r.json()["in_window"], 1)

    # --- Erholung ---------------------------------------------------------
    r = client.get("/api/recovery")
    check("Erholungsansicht antwortet", r.status_code, 200)
    body = r.json()
    check("Ohne Daten ein erklaerender Hinweis", bool(body["hint"]), True)
    check("Basislinien vorbereitet", "hrv_avg" in body["baselines"], True)
    check("Keine erfundenen Beobachtungen", body["observations"], [])

    # --- Detaildaten ------------------------------------------------------
    check("Unbekannte Aktivitaet meldet 404",
          client.get("/api/activities/4242/details").status_code, 404)
    client.post("/api/activities", json={"name": "Morgenlauf", "sport": "running",
                                         "start_time": "2026-09-08T06:00:00",
                                         "duration_s": 1500, "distance_m": 5000})
    act_id = client.get("/api/activities").json()[0]["id"]
    d = client.get(f"/api/activities/{act_id}/details").json()
    check("Aktivitaet ohne Details antwortet sauber", d["has_details"], False)
    check("Und erklaert, was zu tun ist", bool(d["hint"]), True)

    # --- Verlaufs-Import --------------------------------------------------
    st = client.get("/api/garmin/backfill/status").json()
    check("Import-Status abrufbar", st["running"], False)

    # --- CSV-Import mit und ohne Uhrzeit ----------------------------------
    csv = ("datum;gewicht;fett;knochen\n"
           "2026-09-01 06:45:00;77,4;15,3;3,15\n"
           "02.09.2026;77,8;15,1;3,10\n")
    r = client.post("/api/body/import",
                    files={"file": ("waage.csv", csv, "text/csv")})
    check("CSV importiert", r.json()["imported"], 2)
    imported = [m for m in client.get("/api/body").json() if m["source"] == "import"]
    with_time = [m for m in imported if m["time_known"]]
    check("Zeile mit Uhrzeit als bekannt gefuehrt", len(with_time), 1)
    check("Zeile ohne Uhrzeit als unbekannt", len(imported) - len(with_time), 1)
    check("Deutsches Datumsformat erkannt",
          any(m["day"] == "2026-09-02" for m in imported), True)
    check("Komma als Dezimaltrenner erkannt",
          any(m["weight_kg"] == 77.4 for m in imported), True)
    check("Knochenmasse aus CSV uebernommen",
          any(m["bone_kg"] == 3.15 for m in imported), True)

    # --- Bestehende Ansichten duerfen nicht kaputtgegangen sein -----------
    for path in ("/api/dashboard", "/api/health", "/api/settings", "/api/exercises",
                 "/api/workouts", "/api/nutrition", "/api/plan/overview",
                 "/api/scale/status", "/api/coach/messages", "/api/running/summary"):
        code = client.get(path).status_code
        check(f"{path} antwortet", code, 200)

if failures:
    print(f"\n{len(failures)} Test(s) fehlgeschlagen:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\nAlle API-Tests bestanden.")
