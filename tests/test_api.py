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
from app.services import run_analysis as ra  # noqa: E402

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

    # --- Supplements -------------------------------------------------------
    st = client.get("/api/supplements").json()
    names = [i["name"] for i in st["items"]]
    check("Kreatin voreingestellt", "Kreatin" in names, True)
    check("Zink voreingestellt", "Zink" in names, True)
    kre = [i for i in st["items"] if i["name"] == "Kreatin"][0]
    check("Noch nicht genommen", kre["taken"], False)
    r = client.post(f"/api/supplements/{kre['id']}/taken")
    check("Abhaken funktioniert",
          [i for i in r.json()["items"] if i["id"] == kre["id"]][0]["taken"], True)
    r = client.post(f"/api/supplements/{kre['id']}/taken?taken=false")
    check("Haken wieder entfernbar",
          [i for i in r.json()["items"] if i["id"] == kre["id"]][0]["taken"], False)

    r = client.post("/api/supplements", json={"name": "Magnesium", "dose": "300 mg",
                                              "trigger_kind": "time", "at_time": "22:00"})
    new_id = r.json()["id"]
    check("Neues Supplement angelegt", r.status_code, 200)
    check("Ohne Namen abgelehnt",
          client.post("/api/supplements", json={"name": "  "}).status_code, 400)
    check("Loeschen funktioniert",
          client.delete(f"/api/supplements/{new_id}").status_code, 200)
    check("Unbekanntes meldet 404",
          client.delete("/api/supplements/999999").status_code, 404)

    # --- Gemuetszustand ----------------------------------------------------
    r = client.post("/api/mood", json={"mood": 3, "energy": 2, "stress": 4,
                                       "note": "Rücken zwickt seit gestern",
                                       "complaints": [{"region": "back_low",
                                                       "kind": "pain", "severity": 3}]})
    check("Eintrag angenommen", r.status_code, 200)
    entry_id = r.json()["id"]

    m = client.get("/api/mood").json()
    check("Eintrag gelistet", len(m["entries"]), 1)
    check("Beschwerde lesbar", m["entries"][0]["complaint_labels"][0],
          "Unterer Rücken: Schmerz")
    check("Regionen mitgeliefert", "back_low" in m["regions"], True)
    check("Anpassung abgeleitet", len(m["adaptations"]["relief_poses"]) > 0, True)
    check("Muskelgruppen zum Schonen benannt",
          "back" in m["adaptations"]["spare_groups"], True)

    r = client.post("/api/mood/suggest", json={"note": "Mein Nacken ist total verspannt"})
    check("Freitext erkennt den Nacken",
          any(c["region"] == "neck" for c in r.json()["complaints"]), True)

    # Der eigentliche Punkt: die Gym-Einheit muss sich ändern
    sess = client.post("/api/plan/gym-session", json={}).json()
    check("Einheit wurde angepasst", sess.get("adapted") is not None, True)

    check("Eintrag loeschbar", client.delete(f"/api/mood/{entry_id}").status_code, 200)
    check("Unbekannter Eintrag meldet 404",
          client.delete("/api/mood/999999").status_code, 404)

    # --- Laufform ------------------------------------------------------------
    tr = client.get("/api/running/trend").json()
    check("Formtrend antwortet", "runs" in tr, True)
    check("Ohne Läufe ein Hinweis statt leerer Zahlen",
          bool(tr["hint"]) or tr["runs"] > 0, True)
    # 5000 m in 1500 s sind 200 m/min; bei Puls 150 also 1,333
    check("Effizienz wird gerechnet", ra.efficiency(5000, 1500, 150), 1.333)
    check("Ohne Puls keine Effizienz", ra.efficiency(5000, 1500, None), None)
    check("Unsinniger Puls wird verworfen", ra.efficiency(5000, 1500, 20), None)
    check("Ohne Distanz keine Effizienz", ra.efficiency(None, 1500, 150), None)

    # --- Zusammenhänge und Mahlzeiten ---------------------------------------
    ins = client.get("/api/insights").json()
    check("Zusammenhänge abrufbar", "findings" in ins, True)
    check("Ohne Daten wird nichts behauptet", ins["findings"], [])

    tg = client.get("/api/nutrition/targets").json()
    check("Zielwerte antworten", "ready" in tg, True)

    r = client.post("/api/nutrition/meals",
                    json={"name": "Testmahlzeit", "kcal": 500, "protein_g": 30})
    check("Mahlzeit eingetragen", r.status_code, 200)
    meal_id = r.json()["id"]
    nd = client.get("/api/nutrition/day").json()
    check("Mahlzeit im Tag", len(nd["meals"]), 1)
    check("Summe gerechnet", nd["total"]["kcal"], 500.0)
    check("Aus Rezept übernehmbar",
          client.post("/api/nutrition/meals/from-recipe",
                      json={"recipe_id": "skyr_beeren"}).status_code, 200)
    check("Unbekanntes Rezept meldet 404",
          client.post("/api/nutrition/meals/from-recipe",
                      json={"recipe_id": "gibtsnicht"}).status_code, 404)
    check("Mahlzeit löschbar",
          client.delete(f"/api/nutrition/meals/{meal_id}").status_code, 200)
    check("Unbekannte Mahlzeit meldet 404",
          client.delete("/api/nutrition/meals/999999").status_code, 404)
    check("Zusammenhänge stehen im Dashboard",
          "insights" in client.get("/api/dashboard").json(), True)

    # --- Schwung, Gedächtnis, Feedback --------------------------------------
    bo = client.get("/api/boosters").json()
    check("Maßnahmen abrufbar", "boosters" in bo and "works" in bo, True)
    check("Unbekannte Maßnahme meldet 404",
          client.post("/api/boosters/gibtsnicht/rate",
                      json={"helpful": True}).status_code, 404)

    r = client.post("/api/memory", json={"topic": "Schicht",
                                         "fact": "Arbeitet oft bis 19 Uhr"})
    check("Merkposten angelegt", r.status_code, 200)
    mem_id = r.json()["id"]
    check("Merkposten gelistet", len(client.get("/api/memory").json()), 1)
    check("Leeres Thema wird abgelehnt",
          client.post("/api/memory", json={"topic": " ", "fact": "x"}).status_code, 400)
    check("Merkposten löschbar", client.delete(f"/api/memory/{mem_id}").status_code, 200)
    check("Unbekannter Merkposten meldet 404",
          client.delete("/api/memory/999999").status_code, 404)

    fb = client.get("/api/feedback/pending").json()
    check("Offene Rückmeldungen abrufbar", "activities" in fb, True)
    check("Muster werden mitgeliefert", "patterns" in fb, True)
    check("Rückmeldung zu unbekannter Aktivität meldet 404",
          client.post("/api/activities/999999/feedback",
                      json={"rating": 4}).status_code, 404)
    check("Analyse liefert vorhandene Rückmeldung mit",
          "feedback" in client.get(f"/api/activities/{act_id}/analysis").json(), True)
    check("Rückmeldung wird angenommen",
          client.post(f"/api/activities/{act_id}/feedback",
                      json={"rating": 4, "effort": 3}).status_code, 200)
    check("Danach nicht mehr offen",
          any(a["id"] == act_id for a in
              client.get("/api/feedback/pending").json()["activities"]), False)

    check("Dashboard führt Maßnahmen und offene Rückmeldungen",
          {"boosters", "pending_feedback"} <= set(client.get("/api/dashboard").json()),
          True)

    # --- Coach-Vorschläge ---------------------------------------------------
    sg = client.get("/api/suggestions").json()
    check("Vorschläge abrufbar", "open" in sg and "history" in sg, True)
    made = client.post("/api/suggestions/refresh").json()
    check("Regeln lassen sich anstoßen", "created" in made, True)
    check("Unbekannter Vorschlag meldet 404",
          client.post("/api/suggestions/999999/dismiss").status_code, 404)
    check("Unbekannter Vorschlag lässt sich nicht übernehmen",
          client.post("/api/suggestions/999999/apply").status_code, 400)
    check("Vorschläge stehen im Dashboard",
          "suggestions" in client.get("/api/dashboard").json(), True)

    # --- Score --------------------------------------------------------------
    sc = client.get("/api/score").json()
    check("Score antwortet", "score" in sc, True)
    check("Fünf Säulen ausgewiesen", len(sc["pillars"]), 5)
    check("Urteil in Worten", bool(sc["verdict"]), True)
    check("Potenzial nach Ertrag sortiert",
          [p["gain"] for p in sc["potential"]] ==
          sorted([p["gain"] for p in sc["potential"]], reverse=True), True)
    check("Jede Säule nennt ihren Grund",
          all("why" in p or "value" in p for p in sc["pillars"]), True)
    check("Score auch im Dashboard", "score" in client.get("/api/dashboard").json(), True)

    # --- Garmin-Diagnose ----------------------------------------------------
    dg = client.get("/api/garmin/diagnose").json()
    check("Diagnose antwortet", len(dg["steps"]) > 0, True)
    check("Zählt die Datenbank aus", "Aktivitäten" in dg["counts"], True)
    check("Ohne Verknüpfung sagt der erste Schritt das",
          dg["steps"][0]["ok"], False)
    check("Import lässt sich zurücksetzen",
          client.post("/api/garmin/backfill/reset").json()["running"], False)

    # --- Rezepte -----------------------------------------------------------
    r = client.get("/api/recipes/suggest").json()
    check("Rezepte vorgeschlagen", len(r["recipes"]), 3)
    check("Begruendung mitgeliefert", bool(r["reason"]), True)
    check("Naehrwerte vorhanden", r["recipes"][0]["kcal"] > 0, True)
    check("Zubereitung vorhanden", len(r["recipes"][0]["steps"]) > 0, True)
    check("Nach Mahlzeit filterbar",
          all("breakfast" in x["tags"]
              for x in client.get("/api/recipes/suggest?meal=breakfast").json()["recipes"]),
          True)
    check("Einzelnes Rezept abrufbar",
          client.get(f"/api/recipes/{r['recipes'][0]['id']}").status_code, 200)
    check("Unbekanntes Rezept meldet 404",
          client.get("/api/recipes/gibtsnicht").status_code, 404)

    # Naehrwerte gegenrechnen: Eiweiss und Kohlenhydrate 4 kcal/g, Fett 9.
    # Die Angaben sind gerundet, deshalb 20 % Toleranz — grobe Tippfehler
    # faengt das trotzdem.
    all_recipes = client.get("/api/recipes").json()
    off = [r["name"] for r in all_recipes
           if abs(r["protein"] * 4 + r["carbs"] * 4 + r["fat"] * 9 - r["kcal"])
           > r["kcal"] * 0.2]
    check(f"Nährwerte aller {len(all_recipes)} Rezepte stimmig", off, [])
    check("Jedes Rezept hat Zutaten und Zubereitung",
          all(r["ingredients"] and r["steps"] for r in all_recipes), True)
    check("Jedes Rezept ist einer Mahlzeit zugeordnet",
          all(any(t in r["tags"] for t in ("breakfast", "main", "snack"))
              for r in all_recipes), True)

    # --- Aktivitaetsprotokoll ----------------------------------------------
    log = client.get("/api/activities/log").json()
    check("Protokoll antwortet", len(log["activities"]) >= 1, True)
    check("Summen gerechnet", len(log["totals"]) >= 1, True)
    check("Nach Sportart filterbar",
          all(a["sport"] == "running"
              for a in client.get("/api/activities/log?sport=running").json()["activities"]),
          True)

    # --- Statistik ---------------------------------------------------------
    metrics = client.get("/api/stats/metrics").json()
    check("Kennzahlen werden aufgelistet", len(metrics) > 20, True)
    check("Jede Kennzahl hat Gruppe und Bezeichnung",
          all(m["group"] and m["label"] for m in metrics), True)
    matrix = client.get("/api/stats/matrix?days=90").json()
    check("Matrix antwortet", "pairs" in matrix, True)
    check("Ohne belastbare Funde wird nichts behauptet",
          all(p.get("robust") is not None for p in matrix["pairs"]), True)
    check("Belastbares steht vor Unsicherem",
          [p["robust"] for p in matrix["pairs"]]
          == sorted([p["robust"] for p in matrix["pairs"]], reverse=True), True)
    one = client.get("/api/stats/metric/hrv_avg?days=90")
    check("Einzelne Kennzahl antwortet", one.status_code, 200)
    check("… mit Verlauf", "series" in one.json(), True)
    check("Unbekannte Kennzahl ergibt 404",
          client.get("/api/stats/metric/gibtsnicht").status_code, 404)
    check("Einschätzung antwortet auch ohne Modell",
          bool(client.post("/api/stats/explain").json()["message"]), True)
    rec = client.get("/api/stats/recommendations?days=90").json()
    check("Empfehlungen antworten", "recommendations" in rec, True)
    check("Jede Empfehlung nennt eine Stellschraube und ein Ziel",
          all(r["lever"] and r["outcome"] and r["text"]
              for r in rec["recommendations"]), True)
    check("Ohne Empfehlung steht ein Hinweis da",
          bool(rec["recommendations"]) or bool(rec["hint"]), True)
    check("Uhrzeiten und Gemüt sind erfasst",
          {"bedtime", "waketime", "sleep_midpoint", "mood_morning",
           "mood_evening"} <= {m["key"] for m in metrics}, True)

    # --- Autopilot ---------------------------------------------------------
    saved = client.post("/api/autopilot", json={
        "enabled": True, "focus": "balanced", "session_minutes": 55,
        "gym_minutes": 70, "gym_days": ["Mo", "Mi", "Fr"], "run_days": ["Di", "Do"],
        "long_run_day": "So", "wishes": "10 km unter 55 Minuten"}).json()
    check("Autopilot speichert den Schwerpunkt", saved["focus"], "balanced")
    check("… und die Dauer", saved["session_minutes"], 55)
    check("… und die Gym-Tage", saved["gym_days"], ["Mo", "Mi", "Fr"])
    check("… und die Lauftage", saved["run_days"], ["Di", "Do"])
    check("… und liest sie zurück",
          client.get("/api/autopilot").json()["gym_days"], ["Mo", "Mi", "Fr"])

    # Trends: die Grundlage, auf der der Coach die Woche baut
    tr = client.get("/api/trends").json()
    check("Trends antworten", {"muscles", "running", "goal"} <= set(tr), True)
    check("Jede Muskelgruppe hat einen Bedarf zwischen 0 und 100",
          all(0 <= g["need"] <= 100 for g in tr["muscles"]["groups"]), True)
    check("Das Ziel wird gelesen", "10-km-Zeit" in tr["goal"]["recognised"], True)
    preview = client.post if False else client.get("/api/autopilot/preview")
    week = preview.json()
    check("Vorschau plant sieben Tage", len(week["days"]), 7)
    on = {d["weekday"] for d in week["days"]
          for se in d["sessions"] if se["sport"] == "strength"}
    check("Kraft liegt auf den gewählten Tagen", on, {"Mo", "Mi", "Fr"})
    on_run = {d["weekday"] for d in week["days"]
              for se in d["sessions"] if se["sport"] == "running"}
    check("Laufen liegt auf den gewählten Tagen", on_run, {"Di", "Do"})
    check("Vorschau legt nichts an", week["applied"], False)
    check("Vorschau nennt den Zustand", bool(week["condition"]["state"]), True)
    before = len(client.get("/api/workouts").json())
    applied = client.post("/api/autopilot/apply").json()
    check("Anwenden legt Einheiten an", len(applied["created"]) > 0, True)
    check("… und sie tauchen in der Planung auf",
          len(client.get("/api/workouts").json()) > before, True)
    check("Begründung antwortet auch ohne Modell",
          bool(client.post("/api/autopilot/explain").json()["message"]), True)

    # --- Tag, Schlaf, Motivation -------------------------------------------
    today = client.get("/api/today").json()
    check("Tagesliste antwortet", len(today["items"]) >= 4, True)
    check("Jeder Punkt hat einen Fortschritt",
          all(0 <= i["progress"] <= 100 for i in today["items"]), True)
    check("Erledigt nie mehr als vorhanden", today["done"] <= today["total"], True)
    check("Anteil passt zu erledigt/gesamt",
          today["percent"], round(today["done"] / max(1, today["total"]) * 100))
    for kind in ("morning", "midday", "evening"):
        check(f"Check-in {kind} antwortet",
              bool(client.post(f"/api/coach/checkin?kind={kind}").json()["message"]),
              True)
    check("Schlaftipps antworten",
          bool(client.post("/api/coach/sleep").json()["message"]), True)

    # --- Bestehende Ansichten duerfen nicht kaputtgegangen sein -----------
    for path in ("/api/dashboard", "/api/health", "/api/settings", "/api/exercises",
                 "/api/workouts", "/api/nutrition", "/api/plan/overview",
                 "/api/scale/status", "/api/coach/messages", "/api/running/summary",
                 "/api/supplements", "/api/supplements/all", "/api/mood",
                 "/api/mood/adaptations", "/api/recovery",
                 "/api/today", "/api/autopilot", "/api/stats/metrics",
                 "/api/stats/recommendations", "/api/trends"):
        code = client.get(path).status_code
        check(f"{path} antwortet", code, 200)

if failures:
    print(f"\n{len(failures)} Test(s) fehlgeschlagen:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\nAlle API-Tests bestanden.")
