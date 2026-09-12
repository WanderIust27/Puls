"""Smoke-Test der API: sprechen alle Endpunkte, und stimmen die Daten?

Startet die echte FastAPI-Anwendung gegen eine Wegwerf-Datenbank. Deine Daten
werden nicht angefasst. Nicht installierte Bibliotheken (garminconnect,
fit-tool) werden durch Attrappen ersetzt — sie sind nur im Container noetig.

Aufruf:  python3 tests/test_api.py
"""
import datetime as dt
import logging
import os
import sys
import tempfile
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")
# Ohne Modell-Download: Die Verdrahtung prueft tests/test_knowledge.py,
# die Trefferqualitaet tests/eval_knowledge.py mit echtem Modell.
os.environ["PULS_EMBED"] = "stub"
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

from fastapi.testclient import TestClient    # noqa: E402
from app.main import app                     # noqa: E402
from app.db import get_db, get_setting       # noqa: E402

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


with TestClient(app) as client:

    # --- System ---------------------------------------------------------
    h = client.get("/api/health")
    check("Health antwortet", h.status_code, 200)
    ok("… mit einer Version", bool(h.json()["version"]), h.json()["version"])

    check("Die Oberflaeche wird ausgeliefert", client.get("/").status_code, 200)
    check("Der Service Worker auch", client.get("/sw.js").status_code, 200)
    ok("… mit eingesetzter Version", "{{V}}" not in client.get("/sw.js").text)

    # --- Heute ----------------------------------------------------------
    t = client.get("/api/today?phrase=false")
    check("Tagesempfehlung antwortet", t.status_code, 200)
    body = t.json()
    ok("… nennt eine Sportart", body["kind"] in
       ("gym", "run", "home", "mobility", "rest"), body["kind"])
    ok("… mit einem Satz", len(body["plain"]) > 20, body["plain"])
    ok("… und mindestens einem Grund", bool(body["reasons"]),
       str([r["label"] for r in body["reasons"]]))

    # --- Kraft: ein Training in Worten ----------------------------------
    text = ("Heute Beinpresse 3x15 mit 60 kg, dann Latzug 12/10/8 bei 45 kg "
            "und Nackenzieher am Turm 3x20 mit 30 kg")
    pv = client.post("/api/strength/describe", json={"text": text})
    check("Beschreibung wird gelesen", pv.status_code, 200)
    preview = pv.json()
    check("Drei Übungen erkannt", len(preview["items"]), 3)
    ok("Eine davon ist neu", any(not i["known"] for i in preview["items"]),
       str([i["name"] for i in preview["items"] if not i["known"]]))
    ok("Jede Zeile sagt, wie sicher sie ist",
       all(i["confidence"] in ("sicher", "geprüft", "unsicher", "neu")
           for i in preview["items"]),
       str([i["confidence"] for i in preview["items"]]))
    ok("… und bietet Alternativen an",
       all("alternatives" in i for i in preview["items"]))

    # Die schwierige Beschreibung: Sie kam frueher vollstaendig falsch an.
    hard = client.post("/api/strength/describe", json={"text": (
        "Gestern deadlifts mit der langhantel drei sätze 40 kg 15, "
        "Rückenstrecker 3 mal 15 wiederholungen mit eigenkörpergewicht, "
        "Rudern am Kabelzug mit 50 kg 15 wdh")}).json()
    check("Schwierige Beschreibung: Zuordnung",
          [i["name"] for i in hard["items"]],
          ["Kreuzheben (Langhantel)", "Rückenstrecker (Gerät)",
           "Rudern am Kabelzug"])

    # Eine Korrektur muss haengenbleiben.
    fix = client.post("/api/strength/describe",
                      json={"text": "Heute Rückenstrecker 3x12"}).json()
    row = fix["items"][0]
    other = next(a for a in row["alternatives"] if a["id"] != row["exercise_id"])
    row["exercise_id"] = other["id"]
    res = client.post("/api/strength/commit", json={
        "day": fix["day"], "items": [row], "runs": []}).json()
    ok("Die Korrektur wird gemerkt", bool(res["learned"]), str(res["learned"]))
    again = client.post("/api/strength/describe",
                        json={"text": "Heute Rückenstrecker 3x12"}).json()
    check("… und gilt beim nächsten Mal", again["items"][0]["name"], other["name"])

    cm = client.post("/api/strength/commit", json={
        "day": preview["day"], "items": preview["items"], "runs": preview["runs"]})
    check("Eintragen angenommen", cm.status_code, 200)
    result = cm.json()
    check("Sätze geschrieben", result["sets"], 9)
    check("Übung angelegt", result["created"], ["Nackenzieher am Turm"])
    ok("Vorschläge entstanden", bool(result["proposals"]),
       str([p["name"] for p in result["proposals"]]))

    check("Leeres Eintragen wird abgelehnt",
          client.post("/api/strength/commit",
                      json={"day": preview["day"], "items": [], "runs": []}).status_code,
          400)

    s = client.get("/api/strength").json()
    ok("Die Kraftansicht zeigt die Einheit", bool(s["sessions"]), str(len(s["sessions"])))
    ok("… die offenen Vorschläge", bool(s["proposals"]), str(len(s["proposals"])))
    ok("… und die Muskelgruppen", len(s["muscles"]["groups"]) == 6,
       str(len(s["muscles"]["groups"])))

    first = s["proposals"][0]
    acc = client.post(f"/api/strength/proposals/{first['id']}", json={"accept": True})
    check("Vorschlag übernommen", acc.status_code, 200)
    after = client.get("/api/strength").json()
    changed = next(e for e in after["exercises"] if e["id"] == first["exercise_id"])
    check("Das Gewicht ist jetzt das neue", changed["weight_kg"], first["to_weight"])
    check("Und die Wiederholungen auch", changed["target_reps"], first["to_reps"])
    check("Derselbe Vorschlag geht nur einmal",
          client.post(f"/api/strength/proposals/{first['id']}",
                      json={"accept": True}).status_code, 404)

    rc = client.post("/api/strength/proposals/recalculate")
    check("Neu berechnen antwortet", rc.status_code, 200)
    ok("… und prüft Trainingstage", rc.json()["days"] >= 1, str(rc.json()["days"]))

    all_ = client.post("/api/strength/proposals/all", json={"accept": True})
    check("Alle übernehmen antwortet", all_.status_code, 200)

    # --- Übungen --------------------------------------------------------
    new = client.post("/api/exercises", json={"name": "Testübung",
                                              "muscle_group": "core",
                                              "equipment": "bodyweight"})
    check("Übung angelegt", new.status_code, 200)
    ex_id = new.json()["id"]
    check("Umbenennen geht", client.patch(f"/api/exercises/{ex_id}",
                                          json={"name": "Testübung 2"}).status_code, 200)
    check("Verlauf abrufbar",
          client.get(f"/api/exercises/{ex_id}/history").status_code, 200)
    check("Satz eintragen",
          client.post("/api/sets", json={"exercise_id": ex_id, "reps": 12,
                                         "weight_kg": 20}).status_code, 200)
    check("Löschen geht", client.delete(f"/api/exercises/{ex_id}").status_code, 200)
    check("Namen ohne Namen werden abgelehnt",
          client.post("/api/exercises", json={"muscle_group": "core"}).status_code, 400)

    # --- Plan -----------------------------------------------------------
    p = client.get("/api/plan")
    check("Planansicht antwortet", p.status_code, 200)
    ok("… kennt die Wochenstruktur", bool(p.json()["structure"]["gym_days"]),
       str(p.json()["structure"]["gym_days"]))

    w = client.post("/api/plan/week", json={"include_runs": True})
    check("Woche planen antwortet", w.status_code, 200)
    ok("… und legt Einheiten an", len(w.json()["created"]) >= 3,
       str(len(w.json()["created"])))

    planned = client.get("/api/plan").json()["workouts"]
    ok("Geplantes ist nach Datum sortiert",
       [x["planned_date"] for x in planned] == sorted(
           x["planned_date"] for x in planned),
       str([x["planned_date"] for x in planned][:4]))
    ok("Jede Einheit nennt ihre Dauer", all(x["minutes"] for x in planned),
       str([x["minutes"] for x in planned][:4]))

    # Zweimal planen darf nicht stapeln.
    client.post("/api/plan/week", json={"include_runs": True})
    again = client.get("/api/plan").json()["workouts"]
    check("Erneutes Planen ersetzt statt zu stapeln", len(again), len(planned))

    wid = again[0]["id"]
    check("Umbenennen geht", client.patch(f"/api/plan/workouts/{wid}",
                                          json={"name": "Anders"}).status_code, 200)
    check("Löschen geht", client.delete(f"/api/plan/workouts/{wid}").status_code, 200)

    own = client.post("/api/plan/workouts", json={
        "name": "Eigene Einheit", "sport": "strength",
        "planned_date": dt.date.today().isoformat(),
        "steps": [{"type": "work", "name": "Liegestütze", "reps": 12}]})
    check("Eigene Einheit anlegen", own.status_code, 200)

    check("Einheit auf Zuruf", client.post(
        "/api/plan/wish", json={"text": "30 Minuten zuhause Bauch"}).status_code, 200)
    check("Leerer Wunsch wird abgelehnt",
          client.post("/api/plan/wish", json={"text": "  "}).status_code, 400)

    tp = client.post("/api/today/plan")
    ok("Die Tagesempfehlung landet im Plan", tp.status_code in (200, 400),
       str(tp.status_code))

    # --- Laufen ---------------------------------------------------------
    with get_db() as db:
        db.execute("""INSERT INTO activities(source, sport, name, start_time,
                      duration_s, distance_m, avg_hr)
                      VALUES('manual','running','Testlauf',?,1800,5000,142)""",
                   (dt.date.today().isoformat() + "T07:00:00",))
        run_id = db.execute("SELECT MAX(id) AS id FROM activities").fetchone()["id"]

    r = client.get("/api/running")
    check("Laufansicht antwortet", r.status_code, 200)
    ok("… zeigt den Lauf", any(x["id"] == run_id for x in r.json()["runs"]))
    check("Auswertung abrufbar",
          client.get(f"/api/activities/{run_id}/analysis").status_code, 200)
    check("Detaildaten antworten",
          client.get(f"/api/activities/{run_id}/details").status_code, 200)
    check("Unbekannte Einheit meldet sich",
          client.get("/api/activities/99999/details").status_code, 404)
    check("Löschen geht", client.delete(f"/api/activities/{run_id}").status_code, 200)

    # --- Gemüt ----------------------------------------------------------
    m = client.post("/api/mood", json={"mood": 4, "energy": 3, "stress": 2,
                                       "note": "läuft"})
    check("Gemüt eintragen", m.status_code, 200)
    view = client.get("/api/mood").json()
    ok("… erscheint im Verlauf", bool(view["entries"]), str(len(view["entries"])))
    ok("… und in der Kurve", bool(view["trend"]["points"]))
    entry_id = view["entries"][0]["id"]
    check("Löschen geht", client.delete(f"/api/mood/{entry_id}").status_code, 200)
    check("Zweimal löschen nicht",
          client.delete(f"/api/mood/{entry_id}").status_code, 404)

    # --- Waage ----------------------------------------------------------
    token = get_setting("api_token", "")
    ok("Ein Token wurde erzeugt", bool(token))
    check("Ohne Token kein Zugang",
          client.post("/api/body/webhook", json={"weight_kg": 80.0}).status_code, 401)
    good = client.post("/api/body/webhook", json={"weight_kg": 80.0},
                       headers={"X-Puls-Token": token})
    check("Mit Token schon", good.status_code, 200)
    check("Statusmeldung angenommen",
          client.post("/api/scale/report", json={"scanning": True},
                      headers={"X-Puls-Token": token}).status_code, 200)
    st = client.get("/api/scale/status").json()
    ok("Der Zustand wird gedeutet", bool(st["state"]) and bool(st["hint"]), st["state"])

    # --- Einstellungen --------------------------------------------------
    check("Einstellungen speichern", client.post("/api/settings", json={
        "goal_text": "Halbmarathon im Frühjahr", "gym_days": ["Mo", "Do"],
        "run_days": ["Di"], "gym_minutes": 60, "prog_rep_min": 6, "prog_rep_max": 10,
    }).status_code, 200)
    st = client.get("/api/settings").json()
    check("Ziel übernommen", st["goal_text"], "Halbmarathon im Frühjahr")
    check("Gym-Tage übernommen", st["gym_days"], ["Mo", "Do"])
    check("Dauer übernommen", st["gym_minutes"], 60)
    check("Wiederholungsspanne übernommen",
          [st["progression"]["rep_min"], st["progression"]["rep_max"]], [6, 10])

    # Eine Spanne, deren Minimum über dem Maximum liegt, wäre eine Regel, die
    # nie zutrifft.
    client.post("/api/settings", json={"prog_rep_min": 20})
    st = client.get("/api/settings").json()
    ok("Eine verdrehte Spanne wird geradegezogen",
       st["progression"]["rep_max"] > st["progression"]["rep_min"],
       f"{st['progression']['rep_min']}–{st['progression']['rep_max']}")
    client.post("/api/settings", json={"prog_rep_min": 8, "prog_rep_max": 12})

    client.post("/api/settings", json={"gym_days": ["Mo", "Quatsch"], "gym_minutes": 900})
    st = client.get("/api/settings").json()
    check("Unsinnige Tage fallen raus", st["gym_days"], ["Mo"])
    check("Unsinnige Dauer wird begrenzt", st["gym_minutes"], 150)

    # --- Garmin ---------------------------------------------------------
    g = client.get("/api/garmin/status")
    check("Garmin-Status antwortet", g.status_code, 200)
    check("Ohne Verbindung nicht verbunden", g.json()["linked"], False)

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle API-Tests bestanden.")
