"""Tests fuer den erweiterten Garmin-Sync — mit nachgebautem Client.

Die echte Connect-API ist inoffiziell und hier nicht erreichbar. Getestet wird
deshalb gegen nachgebaute Antworten: dass die Felder richtig ankommen, dass
fehlende Methoden und leere Antworten nichts umwerfen, und dass ein zweiter
Lauf vorhandene Werte nicht leert.

Aufruf:  python3 tests/test_garmin_sync.py
"""
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")

# garminconnect ist nur im Container installiert — hier genuegt eine Attrappe.
stub = types.ModuleType("garminconnect")
stub.Garmin = type("Garmin", (), {})
sys.modules.setdefault("garminconnect", stub)

from app.db import get_db, init_db                       # noqa: E402
from app.services import garmin_sync as gs               # noqa: E402

failures = []


def check(name, actual, expected, tol=0.01):
    ok = (abs(actual - expected) <= tol) if isinstance(expected, (int, float)) \
        and isinstance(actual, (int, float)) and not isinstance(expected, bool) \
        else actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


init_db()


class FakeGarmin:
    """Antwortet wie Garmin Connect — in der Form, die die Bibliothek liefert."""

    def get_sleep_data(self, day):
        return {"dailySleepDTO": {
            "sleepTimeSeconds": 27180, "deepSleepSeconds": 5400,
            "lightSleepSeconds": 16200, "remSleepSeconds": 4500,
            "awakeSleepSeconds": 1080, "sleepStartTimestampLocal": f"{day}T23:12:00",
            "sleepEndTimestampLocal": f"{day}T06:45:00",
            "sleepScores": {"overall": {"value": 78}}},
            "avgOvernightHrv": 61, "averageRespirationValue": 13.4,
            "averageSpO2": 95}

    def get_hrv_data(self, day):
        return {"hrvSummary": {"lastNightAvg": 62, "weeklyAvg": 58,
                               "status": "BALANCED",
                               "baseline": {"lowUpper": 48, "balancedUpper": 71}}}

    def get_all_day_stress(self, day):
        return {
            "avgStressLevel": 34, "maxStressLevel": 91,
            "restStressDuration": 21600, "lowStressDuration": 18000,
            "mediumStressDuration": 9000, "highStressDuration": 3600,
            "stressValuesArray": [[1757000000000 + i * 180000, 20 + i % 60]
                                  for i in range(480)],
            "bodyBatteryValuesArray": [
                [1757000000000 + i * 180000, "MEASURED", 90 - i // 8, 1.0]
                for i in range(480)],
            "bodyBatteryChargedValue": 62, "bodyBatteryDrainedValue": 71}

    def get_heart_rates(self, day):
        return {"minHeartRate": 41, "maxHeartRate": 172, "restingHeartRate": 46}

    def get_training_readiness(self, day):
        return [{"score": 72}]

    def get_daily_steps(self, start, end):
        return [{"totalSteps": 11420}]

    def get_body_composition(self, start, end):
        return {"dateWeightList": [{
            "calendarDate": "2026-09-07", "date": 1788769320000,
            "weight": 78400, "bodyFat": 15.2, "muscleMass": 60100,
            "boneMass": 3200, "bodyWater": 59.1, "visceralFat": 7, "bmi": 23.2}]}


g = FakeGarmin()

# --- Tageswerte -----------------------------------------------------------
entry = gs._collect_day(g, "2026-09-07")
check("Schlafdauer", entry["sleep_seconds"], 27180)
check("Tiefschlaf", entry["sleep_deep_s"], 5400)
check("REM-Schlaf", entry["sleep_rem_s"], 4500)
check("Schlafscore", entry["sleep_score"], 78)
check("HRV letzte Nacht", entry["hrv_avg"], 62)
check("HRV-Basislinie oben", entry["hrv_baseline_high"], 71)
check("HRV-Status", entry["hrv_status"], "BALANCED")
check("Atemfrequenz", entry["respiration_avg"], 13.4)
check("Ruhepuls", entry["resting_hr"], 46)
check("Maximalpuls des Tages", entry["hr_max"], 172)
check("Stressmittel", entry["stress_avg"], 34)
check("Erholungsminuten aus Sekunden umgerechnet", entry["stress_rest_min"], 360)
check("Hohe Belastung in Minuten", entry["stress_high_min"], 60)
check("Trainingsbereitschaft", entry["training_readiness"], 72)
check("Schritte", entry["steps"], 11420)

import json                                              # noqa: E402
stress_series = json.loads(entry["stress_series_json"])
check("Stressverlauf ausgeduennt", len(stress_series) <= 96, True)
bb = json.loads(entry["body_battery_series_json"])
check("Body-Battery-Verlauf ausgeduennt", len(bb) <= 96, True)
check("Body Battery Hoechststand", entry["body_battery_max"], 90)
check("Body Battery beim Aufwachen", entry["body_battery_wake"], 90)
check("Body Battery aufgeladen", entry["body_battery_charged"], 62)

# --- Speichern und Wiederholen -------------------------------------------
check("Ein Tag geschrieben", gs.sync_daily_metrics(g, 1), 1)
with get_db() as db:
    row = dict(db.execute("SELECT * FROM daily_metrics").fetchone())
check("Stress in der Datenbank", row["stress_avg"], 34)
check("Schlafphasen in der Datenbank", row["sleep_rem_s"], 4500)


class SparseGarmin(FakeGarmin):
    """Ein spaeterer Lauf, bei dem Garmin weniger liefert."""

    def get_all_day_stress(self, day):
        return {}

    def get_hrv_data(self, day):
        return {}


gs.sync_daily_metrics(SparseGarmin(), 1)
with get_db() as db:
    row2 = dict(db.execute("SELECT * FROM daily_metrics").fetchone())
check("Zweiter Lauf leert vorhandene Werte nicht", row2["stress_avg"], 34)
check("Schlafphasen ueberleben den zweiten Lauf", row2["sleep_deep_s"], 5400)
# Schweigt der HRV-Endpunkt, springt der Wert aus dem Schlafbericht ein.
# Beide stammen von derselben Nacht und liegen ueblicherweise gleichauf.
check("HRV faellt auf den Schlafbericht zurueck", row2["hrv_avg"], 61)
check("HRV-Status bleibt vom genaueren Lauf stehen", row2["hrv_status"], "BALANCED")


class BrokenGarmin:
    """Alte Bibliotheksversion: die meisten Methoden fehlen, eine wirft."""

    def get_sleep_data(self, day):
        raise RuntimeError("Connect antwortet nicht")

    def get_daily_steps(self, start, end):
        return [{"totalSteps": 8000}]


sparse = gs._collect_day(BrokenGarmin(), "2026-09-06")
check("Fehlende Methoden werfen den Sync nicht um", sparse.get("steps"), 8000)
check("Ausnahme in einer Abfrage bleibt folgenlos", "sleep_seconds" in sparse, False)

# --- Koerperwerte mit dem neuen Zeitstempel-Schema ------------------------
check("Koerperwert uebernommen", gs.sync_body_composition(g, 30), 1)
with get_db() as db:
    b = dict(db.execute("SELECT * FROM body_metrics WHERE source='garmin'").fetchone())
check("Gewicht aus Gramm umgerechnet", b["weight_kg"], 78.4)
check("Muskelmasse umgerechnet", b["muscle_kg"], 60.1)
check("Knochenmasse uebernommen", b["bone_kg"], 3.2)
check("Wasseranteil uebernommen", b["water_pct"], 59.1)
check("Viszeralfett uebernommen", b["visceral_fat"], 7)
check("Zeitstempel aus Garmin uebernommen",
      b["measured_at"].startswith("2026-09-07"), True)
check("Tag wird aus dem Zeitstempel abgeleitet", b["day"], "2026-09-07")
check("Uhrzeit gilt als bekannt", b["time_known"], 1)

# Zweiter Lauf darf keine Dublette anlegen
gs.sync_body_composition(g, 30)
with get_db() as db:
    n = db.execute("SELECT COUNT(*) AS n FROM body_metrics "
                   "WHERE source='garmin'").fetchone()["n"]
check("Kein doppelter Eintrag beim zweiten Sync", n, 1)

# --- Verlaufs-Import: Zustandsmeldung ------------------------------------
state = gs.backfill_state()
check("Import laeuft anfangs nicht", state["running"], False)
check("Fortschritt ist ablesbar",
      {"running", "done", "total", "phase", "percent"} <= set(state), True)



# --- Verlaufs-Import ------------------------------------------------------
# Der Import lief bisher nie in einem Test. Hier wird er komplett
# durchgespielt: mit Zeitfenstern, Fortschritt und Abbruch.

import datetime as dt                                    # noqa: E402

calls: list[tuple[str, str]] = []


class HistoryGarmin(FakeGarmin):
    """Hat Aktivitaeten bis vor 400 Tagen, davor nichts."""

    def get_activities_by_date(self, start, end):
        calls.append((start, end))
        begin = dt.date.fromisoformat(start)
        if (dt.date.today() - begin).days > 400:
            return []
        return [{
            "activityId": f"a-{start}", "activityName": "Lauf",
            "activityType": {"typeKey": "running"},
            "startTimeLocal": f"{start} 07:00:00",
            "duration": 1800, "distance": 5000.0, "averageHR": 148,
        }]

    def get_activity_details(self, aid, maxchart=None, maxpoly=None):
        return {"metricDescriptors": [{"key": "directHeartRate", "metricsIndex": 0},
                                      {"key": "sumDuration", "metricsIndex": 1}],
                "activityDetailMetrics": [{"metrics": [140.0 + i % 20, float(i)]}
                                          for i in range(300)]}

    def get_activity_splits(self, aid):
        return {"lapDTOs": [{"distance": 1000.0, "duration": 300.0, "averageHR": 150}]}


calls.clear()
history = HistoryGarmin()
gs.get_client = lambda: history      # statt einer echten Garmin-Verbindung
gs._backfill.update(running=False, cancel=False)
gs.run_backfill(days=1080)
state = gs.backfill_state()
check("Import beendet", state["running"], False)
check("Kein Fehler aufgetreten", state["error"], None)
check("Zusammenfassung vorhanden", bool(state["summary"]), True)

# Die Fenster muessen sich fortbewegen, nicht immer bei heute anfangen
starts = [c[0] for c in calls]
check("Zeitfenster wandern zurück", len(set(starts)), len(starts))
ends = [c[1] for c in calls]
check("Nicht jedes Fenster endet heute", len(set(ends)) > 1, True)

# Nach zwei leeren Halbjahren muss Schluss sein statt weiter bis zehn Jahre
check("Bricht ab, wenn nichts mehr kommt", len(calls) < 8, True)

with get_db() as db:
    acts = db.execute("SELECT COUNT(*) AS n FROM activities").fetchone()["n"]
    details = db.execute("SELECT COUNT(*) AS n FROM activity_details").fetchone()["n"]
check("Aktivitäten übernommen", acts > 0, True)
check("Detaildaten übernommen", details > 0, True)
check("Zähler gefüllt", state["counts"].get("Aktivitäten", 0) > 0, True)

# Tagesmetriken duerfen nicht ueber die Obergrenze hinausgehen
check("Tagesmetriken gedeckelt",
      gs.MAX_DAILY_BACKFILL_DAYS <= 1000, True)

# Zweiter Lauf: nichts ist mehr neu, aber es darf nicht abstuerzen
gs._backfill.update(running=False, cancel=False)
gs.run_backfill(days=400)
check("Zweiter Lauf ohne Fehler", gs.backfill_state()["error"], None)

# Abbrechen
gs._backfill.update(running=True, cancel=False)
gs.cancel_backfill()
check("Abbruch wird vermerkt", gs._backfill["cancel"], True)
gs._backfill.update(running=False, cancel=False)

# Fortschritt ist ablesbar und in Prozent
gs._backfill.update(done=25, total=50)
check("Prozent werden gerechnet", gs.backfill_state()["percent"], 50)
gs._backfill.update(done=0, total=0)
check("Kein Absturz bei total=0", gs.backfill_state()["percent"], 0)

if failures:
    print(f"\n{len(failures)} Test(s) fehlgeschlagen:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\nAlle Garmin-Sync-Tests bestanden.")
