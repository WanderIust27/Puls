"""Tests fuers Ausduennen der Laufdetails.

Prueft, dass die reduzierten Daten die Rohdaten noch treu wiedergeben —
und dass die Ersparnis wirklich eintritt.

Aufruf:  python3 tests/test_activity_details.py
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.services import activity_details as ad   # noqa: E402

failures = []


def check(name, actual, expected, tol=0.01):
    ok = (abs(actual - expected) <= tol) if isinstance(expected, (int, float)) \
        and isinstance(actual, (int, float)) and not isinstance(expected, bool) \
        else actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


# --- Einen realistischen Lauf bauen: 45 min, 1 Messpunkt je Sekunde -------
N = 2700
rows = []
for i in range(N):
    # Puls steigt an und pendelt, Tempo schwankt leicht
    hr = 120 + 45 * (1 - math.exp(-i / 600)) + 4 * math.sin(i / 90)
    speed = 3.0 + 0.35 * math.sin(i / 200)
    ele = 100 + 25 * math.sin(i / 500)
    rows.append({"metrics": [i * 1000.0, float(i), hr, speed, ele, 168.0,
                             speed * i]})

details = {
    "metricDescriptors": [
        {"key": "directTimestamp", "metricsIndex": 0},
        {"key": "sumDuration", "metricsIndex": 1},
        {"key": "directHeartRate", "metricsIndex": 2},
        {"key": "directSpeed", "metricsIndex": 3},
        {"key": "directElevation", "metricsIndex": 4},
        {"key": "directDoubleCadence", "metricsIndex": 5},
        {"key": "sumDistance", "metricsIndex": 6},
    ],
    "activityDetailMetrics": rows,
}

# GPS: ein Rundkurs mit einigen Ecken, 1 Punkt je Sekunde
track_raw = []
for i in range(N):
    angle = 2 * math.pi * i / N
    track_raw.append({
        "lat": 48.1372 + 0.012 * math.sin(angle) + 0.0002 * math.sin(angle * 17),
        "lon": 11.5755 + 0.018 * math.cos(angle) + 0.0002 * math.cos(angle * 17),
        "altitude": 100 + 25 * math.sin(i / 500),
    })
details["geoPolylineDTO"] = {"polyline": track_raw}

# --- Kurven ---------------------------------------------------------------
series = ad.extract_series(details)
check("Kurve auf Zielgroesse reduziert", series["points"], 400)
check("Zeitachse vorhanden", len(series["t"]), 400)
check("Puls vorhanden", len(series["hr"]), 400)

raw_hr = [r["metrics"][2] for r in rows]
check("Durchschnittspuls bleibt erhalten",
      sum(series["hr"]) / len(series["hr"]), sum(raw_hr) / len(raw_hr), tol=0.5)
check("Maximalpuls kaum verfaelscht", max(series["hr"]), max(raw_hr), tol=1.5)
check("Anstieg am Anfang bleibt sichtbar", series["hr"][0] < series["hr"][-1], True)

check("Tempo statt Geschwindigkeit ausgegeben", "pace" in series, True)
mid_pace = [p for p in series["pace"] if p]
check("Tempo im plausiblen Bereich (4:00-6:30/km)",
      all(240 <= p <= 390 for p in mid_pace), True)

# Stillstand darf kein Fantasietempo erzeugen
stand = dict(details)
stand["activityDetailMetrics"] = [{"metrics": [0.0, 0.0, 100.0, 0.0, 100.0, 0.0, 0.0]}]
check("Stillstand ergibt kein Tempo", ad.extract_series(stand)["pace"][0], None)

# Fehlende Werte duerfen nicht zu Nullen werden
gaps = dict(details)
gaps["activityDetailMetrics"] = [
    {"metrics": [i * 1000.0, float(i), None if 100 < i < 400 else 150.0,
                 3.0, 100.0, 168.0, 3.0 * i]} for i in range(600)]
gs = ad.extract_series(gaps)
check("Luecken bleiben Luecken statt Null", any(v is None for v in gs["hr"]), True)
check("Vorhandene Werte unveraendert",
      max(v for v in gs["hr"] if v is not None), 150.0)

# --- GPS-Spur -------------------------------------------------------------
track, bounds = ad.extract_track(details)
check("Spur deutlich verkleinert", len(track) < N / 3, True)
check("Obergrenze eingehalten", len(track) <= ad.MAX_TRACK_POINTS, True)
check("Anfang bleibt erhalten", track[0]["lat"], track_raw[0]["lat"], tol=1e-6)
check("Ende bleibt erhalten", track[-1]["lat"], track_raw[-1]["lat"], tol=1e-6)
check("Eckpunkte berechnet", set(bounds), {"min_lat", "max_lat", "min_lon", "max_lon"})

# Die entscheidende Frage: weicht die vereinfachte Linie sichtbar ab?
# Fuer jeden Originalpunkt der Abstand zur naechsten Strecke der Spur.
def max_deviation_m(original, simplified):
    worst = 0.0
    for p in original[::7]:
        best = min(
            ad._perpendicular_distance((p["lat"], p["lon"]),
                                       (a["lat"], a["lon"]), (b["lat"], b["lon"]))
            for a, b in zip(simplified, simplified[1:]))
        worst = max(worst, best)
    return worst * 111_320    # Grad -> Meter

deviation = max_deviation_m(track_raw, track)
check("Groesste Abweichung unter 3 m", deviation < 3.0, True)
print(f"   Groesste Abweichung der Spur: {deviation:.2f} m")

# --- Ersparnis ------------------------------------------------------------
raw_size = len(json.dumps(details))
packed = ad.condense(details)
small = sum(len(v) for v in (packed["series_json"], packed["track_json"],
                             packed["bounds_json"]) if v)
check("Kleiner als 120 kB", small < 120_000, True)
check("Mindestens auf ein Viertel geschrumpft", small < raw_size / 4, True)
print(f"   Roh: {raw_size/1024:.0f} kB -> gespeichert: {small/1024:.0f} kB "
      f"({small/raw_size*100:.0f} %)")

# --- Unvollstaendige Daten duerfen nicht abstuerzen -----------------------
check("Ohne Details leeres Ergebnis", ad.extract_series({}), {})
check("Ohne GPS leere Spur", ad.extract_track({"geoPolylineDTO": {}}), ([], None))
check("Krafttraining ohne Kurven stuerzt nicht ab",
      ad.condense({"activityDetailMetrics": []})["series_json"], None)
short = ad.simplify_track([{"lat": 1.0, "lon": 2.0}])
check("Einzelpunkt bleibt unveraendert", len(short), 1)

if failures:
    print(f"\n{len(failures)} Test(s) fehlgeschlagen:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\nAlle Detaildaten-Tests bestanden.")
