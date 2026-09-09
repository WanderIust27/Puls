"""Eigenschaften, die für die ganze API gelten müssen.

Einzelne Endpunkte prüfen die anderen Suiten. Hier geht es um Regeln, die
überall gelten sollen — und deshalb genau dann brechen, wenn man nicht
hinschaut.

Aufruf:  python3 tests/test_invariants.py
"""
import logging
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")
logging.disable(logging.INFO)

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

from fastapi.testclient import TestClient          # noqa: E402
from app.db import get_db                          # noqa: E402
from app.main import app                           # noqa: E402
from app.routers.api import router                 # noqa: E402

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


TABLES = ("activities", "planned_workouts", "nutrition_log", "body_metrics",
          "daily_metrics", "coach_messages", "exercises", "exercise_sets",
          "supplements", "supplement_log", "mood_entries", "coach_adaptations",
          "coach_memory", "activity_feedback", "tip_log", "meals",
          "research_tips", "activity_details", "progression_log")


def snapshot():
    with get_db() as db:
        return {t: db.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
                for t in TABLES}


# Die Routen hängen am Router, nicht an app.routes — in dieser FastAPI-Version
# tauchen eingebundene Router dort nicht einzeln auf.
get_paths = sorted({r.path for r in router.routes
                    if "GET" in getattr(r, "methods", set()) and "{" not in r.path})

with TestClient(app) as client:
    client.post("/api/mood", json={"mood": 2, "energy": 2, "stress": 4})
    client.post("/api/body", json={"weight_kg": 78.0,
                                   "measured_at": "2026-09-09T06:40:00"})
    # Erster Durchlauf: hier darf sich noch etwas einspielen (Tagesauswahl
    # der Maßnahmen etwa wird einmal je Tag festgelegt).
    for path in get_paths:
        client.get(path)

    before = snapshot()
    codes = {}
    for path in get_paths:
        codes[path] = client.get(path).status_code
    after = snapshot()

check("Alle GET-Endpunkte antworten ohne Fehler",
      sorted(p for p, c in codes.items() if c >= 400), [])
check(f"Keiner der {len(get_paths)} GET-Endpunkte verändert Daten",
      {t: (before[t], after[t]) for t in TABLES if before[t] != after[t]}, {})

# Zweimal dasselbe abfragen muss dasselbe ergeben — sonst springt die
# Oberfläche bei jedem Neuladen.
with TestClient(app) as client:
    for path in ("/api/boosters", "/api/dashboard", "/api/insights",
                 "/api/score", "/api/nutrition/targets"):
        a = client.get(path).json()
        b = client.get(path).json()
        if path == "/api/dashboard":
            # Der Zeitstempel des Scores darf sich ändern, sonst nichts
            for d in (a, b):
                d.get("score", {}).pop("updated", None)
        if path == "/api/score":
            a.pop("updated", None)
            b.pop("updated", None)
        check(f"{path} liefert zweimal dasselbe", a == b, True)

# --- Der Versionsstempel muss bis in die Seite durchkommen --------------
# Sonst laedt der Browser nach einem Update weiter die alte app.js aus
# seinem Cache — die Datei heisst ja gleich.
from app.version import VERSION                  # noqa: E402

with TestClient(app) as client:
    page = client.get("/").text
    check("Kein unersetzter Platzhalter in der Seite", "{{V}}" in page, False)
    check("Stylesheet traegt die Version", f"style.css?v={VERSION}" in page, True)
    check("app.js traegt die Version", f"app.js?v={VERSION}" in page, True)
    check("charts.js traegt die Version", f"charts.js?v={VERSION}" in page, True)

    sw = client.get("/sw.js").text
    check("Kein unersetzter Platzhalter im Service Worker", "{{V}}" in sw, False)
    check("Cache-Name traegt die Version", f'"puls-{VERSION}"' in sw, True)
    check("charts.js gehört zur App-Hülle", "charts.js" in sw, True)

    h = client.get("/api/health").json()
    check("Health meldet die Version", h.get("version"), VERSION)
    check("Health meldet den Stand", bool(h.get("built_at")), True)

if failures:
    print(f"\n{len(failures)} Test(s) fehlgeschlagen:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\nAlle Invarianten erfüllt.")
