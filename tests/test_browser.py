"""Die App im echten Browser durchklicken.

Anlass: Ein Aufruf war beim Bearbeiten in einen fremden Klick-Handler
gerutscht. Der Autopilot wurde dadurch nur noch beim Löschen eines Supplements
befüllt — auf der Seite standen leere Auswahlfelder. Kein Python-Test konnte
das sehen, denn die Datei war syntaktisch einwandfrei und jeder Endpunkt
antwortete korrekt. Was fehlte, war der Browser.

Diese Suite braucht Playwright und einen Chromium. Fehlt beides, überspringt
sie sich — auf dem Server soll sie niemanden aufhalten:

    pip install playwright && playwright install chromium

Aufruf:  python3 tests/test_browser.py
"""
import logging
import os
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from playwright.sync_api import sync_playwright
    import uvicorn
except ImportError as e:
    print(f"Übersprungen — {e.name} ist nicht installiert.")
    sys.exit(0)

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

from app.db import get_db, init_db                          # noqa: E402
from app.main import app                                    # noqa: E402

# Eine frische Einheit anlegen, zu der noch nichts gesagt wurde — sonst gibt es
# nichts zu bewerten und der Test prüfte eine leere Karte.
init_db()
with get_db() as _db:
    import datetime as _dt
    _db.execute("""INSERT INTO activities(sport, start_time, duration_s,
                       distance_m, avg_hr, source, name)
                   VALUES('running', ?, 2400, 7000, 142, 'manual', 'Testlauf')""",
                (f"{_dt.date.today().isoformat()}T07:00:00",))
    # Gemütseinträge zu verschiedenen Uhrzeiten — der Verlauf soll sie an
    # ihrer Uhrzeit zeigen, nicht auf einem Tagesraster.
    for _d in range(0, 20):
        _day = (_dt.date.today() - _dt.timedelta(days=_d)).isoformat()
        for _h, _m in ((7, 2), (13, 4), (21, 3)):
            _db.execute("""INSERT INTO mood_entries(day, recorded_at, mood,
                               energy, stress)
                           VALUES(?,?,?,?,?)""",
                        (_day, f"{_day}T{_h:02d}:15:00", _m, _m, 3))

PORT = 8899
VIEWS = ("start", "mood", "plan", "strength", "running", "nutrition",
         "weight", "vital", "stats", "settings")
DAY_NAMES = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")

failures: list[str] = []


def ok(name, condition, detail=""):
    print(f"{'OK  ' if condition else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def find_chromium() -> str | None:
    """Playwright findet den Browser sonst nur unter der eigenen Version."""
    root = Path(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers"))
    if not root.is_dir():
        return None
    hits = sorted(root.glob("chromium-*/chrome-linux/chrome"))
    return str(hits[-1]) if hits else None


server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT,
                                       log_level="error"))
threading.Thread(target=server.run, daemon=True).start()
for _ in range(150):
    if getattr(server, "started", False):
        break
    time.sleep(0.1)
else:
    print("FAIL Server startet nicht")
    sys.exit(1)

errors: list[str] = []
try:
    with sync_playwright() as pw:
        launch = {"executable_path": find_chromium()} if find_chromium() else {}
        try:
            browser = pw.chromium.launch(**launch)
        except Exception as e:                              # noqa: BLE001
            print(f"Übersprungen — kein Chromium startbar: {str(e)[:120]}")
            sys.exit(0)

        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        page.on("console", lambda m: errors.append(f"Konsole: {m.text[:200]}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(f"Ausnahme: {str(e)[:200]}"))

        page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle")
        page.wait_for_timeout(1500)

        # --- Bewerten: die Zahlen müssen anklickbar UND sichtbar sein -----
        # Die Regel für die Zahlenknöpfe hing einmal an einem Elternteil, den
        # die Rückmeldungskarte nicht hat. Der Klick kam an, sichtbar passierte
        # nichts — für den Nutzer war das Bewerten schlicht kaputt.
        page.click('nav.bottom button[data-view="start"]')
        page.wait_for_timeout(2000)
        ok("Rückmeldung wird abgefragt", page.is_visible("#feedbackCard"))
        dots = page.eval_on_selector_all('#feedbackBody [data-fb]', "e => e.length")
        ok("Zehn Zahlen zum Anklicken", dots == 10, f"{dots} Knöpfe")
        size = page.eval_on_selector(
            '#feedbackBody [data-fb]',
            "el => { const r = el.getBoundingClientRect();"
            "        return { w: r.width, h: r.height,"
            "                 round: getComputedStyle(el).borderRadius }; }")
        ok("Die Zahlen sind als Knöpfe erkennbar",
           size["w"] >= 24 and size["h"] >= 24 and size["round"] != "0px", str(size))

        page.click('#feedbackBody [data-fb][data-field="rating"][data-value="4"]')
        page.wait_for_timeout(200)
        marked = page.eval_on_selector_all(
            '#feedbackBody [data-field="rating"].on', "e => e.map(x => x.textContent.trim())")
        ok("Die geklickte Zahl wird markiert", marked == ["4"], str(marked))
        highlighted = page.eval_on_selector(
            '#feedbackBody [data-field="rating"].on',
            "el => getComputedStyle(el).backgroundColor")
        plain = page.eval_on_selector(
            '#feedbackBody [data-field="rating"]:not(.on)',
            "el => getComputedStyle(el).backgroundColor")
        ok("… und hebt sich sichtbar ab", highlighted != plain,
           f"{highlighted} vs {plain}")

        page.click('#feedbackBody [data-fb][data-field="effort"][data-value="2"]')
        page.wait_for_timeout(200)
        ok("Beide Skalen lassen sich getrennt setzen",
           page.eval_on_selector_all('#feedbackBody .dot.on', "e => e.length") == 2)
        page.click('#feedbackBody [data-fb][data-field="rating"][data-value="2"]')
        page.wait_for_timeout(200)
        again = page.eval_on_selector_all(
            '#feedbackBody [data-field="rating"].on', "e => e.map(x => x.textContent.trim())")
        ok("Umwählen ersetzt die Wahl, statt sie zu ergänzen", again == ["2"], str(again))

        page.click("#feedbackBody [data-fbsave]")
        page.wait_for_timeout(2500)
        ok("Die Bewertung ist gespeichert",
           not page.is_visible("#feedbackCard")
           or page.eval_on_selector_all("#feedbackBody .fb-item", "e => e.length") == 0,
           "Karte verschwindet nach dem Speichern")

        # --- Jede Ansicht muss sich oeffnen lassen ------------------------
        for view in VIEWS:
            page.click(f'nav.bottom button[data-view="{view}"]')
            page.wait_for_timeout(1000)
            ok(f"Ansicht {view} öffnet", page.is_visible(f"#view-{view}"))

        # --- Diagramme: Zeitraum umschaltbar, Beschriftung passt sich an ---
        page.click('nav.bottom button[data-view="mood"]')
        page.wait_for_timeout(2000)
        tabs = page.eval_on_selector_all("#moodRange [data-range]",
                                         "e => e.map(x => x.textContent.trim())")
        ok("Gemütsverlauf: Zeitraum wählbar",
           tabs == ["Tag", "Woche", "Monat", "3 Monate"], str(tabs))

        def axis_labels():
            return page.eval_on_selector_all(
                "#moodChart svg text",
                "e => e.map(x => x.textContent.trim()).filter(t => t)")

        page.click('#moodRange [data-range="week"]')
        page.wait_for_timeout(600)
        week_labels = axis_labels()
        ok("Woche: Wochentage an der Achse",
           any(l[:2] in ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So") for l in week_labels),
           str(week_labels[:6]))

        page.click('#moodRange [data-range="day"]')
        page.wait_for_timeout(600)
        day_labels = axis_labels()
        ok("Tag: Uhrzeiten an der Achse",
           any(":" in l and l.endswith(":00") for l in day_labels), str(day_labels[:6]))
        ok("Die Beschriftung wechselt mit dem Zeitraum",
           day_labels != week_labels)

        page.click('#moodRange [data-range="month"]')
        page.wait_for_timeout(600)
        ok("Monat: Datumsangaben an der Achse",
           any(l.count(".") == 2 for l in axis_labels()), str(axis_labels()[:6]))
        ok("Der Verlauf zeigt drei Kurven",
           page.eval_on_selector_all("#moodChart svg path", "e => e.length") == 3,
           str(page.eval_on_selector_all("#moodChart svg path", "e => e.length")))
        ok("… mit Legende",
           "Stimmung" in " ".join(axis_labels()) and "Energie" in " ".join(axis_labels()))

        # Punkte müssen an der Uhrzeit sitzen: Drei Einträge um 7, 13 und 21 Uhr
        # dürfen im Tagesbild nicht gleichmäßig verteilt liegen.
        page.click('#moodRange [data-range="day"]')
        page.wait_for_timeout(600)
        xs = sorted(page.eval_on_selector_all(
            "#moodChart svg circle", "e => e.map(c => +c.getAttribute('cx'))"))
        if len(xs) >= 6:
            gaps = [round(xs[i + 1] - xs[i], 1) for i in range(len(xs) - 1)]
            ok("Punkte sitzen an ihrer Uhrzeit, nicht auf einem Raster",
               len({g for g in gaps if g > 1}) > 1, str(gaps[:6]))

        # Die Wahl muss das Neuladen überleben
        page.reload(wait_until="networkidle")
        page.click('nav.bottom button[data-view="mood"]')
        page.wait_for_timeout(2000)
        ok("Der gewählte Zeitraum bleibt gespeichert",
           page.eval_on_selector("#moodRange .on", "el => el.textContent.trim()") == "Tag",
           page.eval_on_selector("#moodRange .on", "el => el.textContent.trim()"))

        # --- Gemüt: dieselben Zahlenknöpfe, gleiche Erwartung -------------
        page.click('nav.bottom button[data-view="mood"]')
        page.wait_for_timeout(1500)
        mood_dots = page.eval_on_selector_all(
            '#view-mood [data-scale-set]', "e => e.length")
        ok("Gemüt: Regler haben Zahlen", mood_dots >= 15, f"{mood_dots} Knöpfe")
        page.click('#view-mood [data-scale-set="mood"][data-value="4"]')
        page.wait_for_timeout(200)
        ok("Gemüt: die Zahl lässt sich wählen",
           page.eval_on_selector_all(
               '#view-mood [data-scale-set="mood"].on', "e => e.length") == 1)
        mood_size = page.eval_on_selector(
            '#view-mood [data-scale-set]',
            "el => el.getBoundingClientRect().width")
        ok("Gemüt: die Knöpfe haben Größe", mood_size >= 24, f"{mood_size} px")

        # --- Plan: das Nächste steht oben ---------------------------------
        page.click('nav.bottom button[data-view="plan"]')
        page.wait_for_timeout(1800)
        dates = page.eval_on_selector_all(
            "#plannedList [data-date]", "e => e.map(x => x.dataset.date)")
        if len(dates) >= 2:
            ok("Plan: nach Datum sortiert, das Nächste oben",
               dates == sorted(dates), str(dates[:5]))

        # --- Coach: Ziel, Woche und Trends stehen auf einer Seite ---------
        page.click('nav.bottom button[data-view="plan"]')
        page.wait_for_timeout(2500)
        focus = page.eval_on_selector("#autoFocus", "el => el.options.length")
        days = page.eval_on_selector("#autoLongDay", "el => el.options.length")
        gym_chips = page.eval_on_selector_all("#gymDayPick [data-gymday]", "e => e.length")
        run_chips = page.eval_on_selector_all("#runDayPick [data-runday]", "e => e.length")
        minutes = page.eval_on_selector("#autoMinutes", "el => el.value")
        note = page.eval_on_selector("#autoFocusNote", "el => el.textContent.trim()")
        ok("Coach: Schwerpunkte wählbar", focus >= 4, f"{focus} Einträge")
        ok("Coach: langer Lauf wählbar", days == 7, f"{days} Einträge")
        ok("Coach: Gym-Tage wählbar", gym_chips == 7, f"{gym_chips} Knöpfe")
        ok("Coach: Lauftage getrennt wählbar", run_chips == 7, f"{run_chips} Knöpfe")
        ok("Coach: Dauer vorbelegt", bool(minutes), repr(minutes))
        ok("Coach: Schwerpunkt erklärt", bool(note))

        # --- Auswaehlen muss auch wirken ----------------------------------
        page.select_option("#autoFocus", "build_muscle")
        page.wait_for_timeout(300)
        ok("Coach: Wechsel ändert die Erklärung",
           page.eval_on_selector("#autoFocusNote", "el => el.textContent.trim()") != note)

        # Genau die Tage wählen, die der Nutzer nennen würde. Erst leeren,
        # dann setzen — sonst hinge der Test an den Vorgabewerten.
        def set_days(picker, attr, wanted):
            for day in DAY_NAMES:
                on = page.eval_on_selector(
                    f'{picker} [data-{attr}="{day}"]',
                    "el => el.classList.contains('on')")
                if on != (day in wanted):
                    page.click(f'{picker} [data-{attr}="{day}"]')
                    page.wait_for_timeout(60)

        set_days("#gymDayPick", "gymday", {"Mo", "Mi", "Fr"})
        set_days("#runDayPick", "runday", {"Di", "Do"})
        page.wait_for_timeout(300)
        gym_on = page.eval_on_selector_all("#gymDayPick .chip.on", "e => e.map(x => x.textContent)")
        run_on = page.eval_on_selector_all("#runDayPick .chip.on", "e => e.map(x => x.textContent)")
        ok("Coach: Gym auf Mo/Mi/Fr", set(gym_on) == {"Mo", "Mi", "Fr"}, str(gym_on))
        ok("Coach: Laufen auf Di/Do", set(run_on) == {"Di", "Do"}, str(run_on))

        page.fill("#goalText", "10 km unter 55 Minuten, dazu stärkere Beine")
        page.click("#btnAutoSave")
        page.wait_for_timeout(2000)
        page.reload(wait_until="networkidle")
        page.click('nav.bottom button[data-view="plan"]')
        page.wait_for_timeout(2500)
        kept = page.eval_on_selector("#autoFocus", "el => el.value")
        ok("Coach: Schwerpunkt überlebt das Neuladen", kept == "build_muscle", kept)
        kept_gym = page.eval_on_selector_all("#gymDayPick .chip.on", "e => e.map(x => x.textContent)")
        ok("Coach: Gym-Tage überleben das Neuladen",
           set(kept_gym) == {"Mo", "Mi", "Fr"}, str(kept_gym))
        ok("Coach: Ziel überlebt das Neuladen",
           "10 km" in page.eval_on_selector("#goalText", "el => el.value"))
        ok("Coach: Ziel wird gelesen",
           "10-km" in page.eval_on_selector("#goalRead", "el => el.textContent"),
           page.eval_on_selector("#goalRead", "el => el.textContent")[:80])
        ok("Coach: Muskeltrends stehen da",
           bool(page.eval_on_selector("#trendMuscles", "el => el.textContent.trim()")))
        ok("Coach: Lauftrends stehen da",
           bool(page.eval_on_selector("#trendRunning", "el => el.textContent.trim()")))

        page.click("#btnAutoPreview")
        page.wait_for_timeout(10000)
        planned = page.eval_on_selector_all("#autoPreview .auto-day", "e => e.length")
        ok("Coach: Vorschau zeigt die Woche", planned == 7, f"{planned} Tage")
        # Die Sportart steht in der ersten Zeile jeder Einheit — im Fließtext
        # darunter kommen "Kraft" und "Laufen" auch vor, deshalb nur die Zeile.
        placed = page.eval_on_selector_all("#autoPreview .auto-day", """els => els.map(el => ({
            day: el.querySelector('.ad').textContent.trim(),
            sports: [...el.querySelectorAll('.as')].map(s => s.textContent.trim().split(' ·')[0])
        }))""")
        gym_days_shown = {d["day"] for d in placed if "Kraft" in d["sports"]}
        run_days_shown = {d["day"] for d in placed if "Laufen" in d["sports"]}
        ok("Coach: Kraft liegt auf den gewählten Tagen",
           gym_days_shown == {"Mo", "Mi", "Fr"}, str(sorted(gym_days_shown)))
        ok("Coach: Laufen liegt auf den gewählten Tagen",
           run_days_shown == {"Di", "Do"}, str(sorted(run_days_shown)))

        # --- Essen: Beschreibung wird zu Nährwerten -----------------------
        page.click('nav.bottom button[data-view="nutrition"]')
        page.wait_for_timeout(1800)
        page.fill("#mealText", "150 g Hähnchenbrust, 80 g Reis und Gemüse")
        page.click("#btnMealEstimate")
        page.wait_for_timeout(3000)
        est = page.eval_on_selector("#mealEstimate", "el => el.textContent")
        ok("Essen: die Aufstellung erscheint", "kcal" in est, est[:90])
        rows = page.eval_on_selector_all("#mealEstimate .est-t tr", "e => e.length")
        ok("Essen: jeder Bestandteil einzeln", rows == 3, f"{rows} Zeilen")
        ok("Essen: als Schätzung gekennzeichnet", "Geschätzt" in est)
        before = page.eval_on_selector_all("#mealList [data-del-meal]", "e => e.length")
        page.click("#btnMealSave")
        page.wait_for_timeout(3000)
        after = page.eval_on_selector_all("#mealList [data-del-meal]", "e => e.length")
        ok("Essen: die Mahlzeit wird eingetragen", after > before,
           f"{before} -> {after}")
        ok("Essen: die Aufstellung verschwindet nach dem Buchen",
           not page.is_visible("#mealEstimate"))
        listed = page.eval_on_selector("#mealList", "el => el.textContent")
        ok("Essen: mit Kalorien in der Liste", "kcal" in listed, listed[:80])

        # --- Schlafenszeit: abends auf der Startseite ---------------------
        page.click('nav.bottom button[data-view="start"]')
        page.wait_for_timeout(2500)
        shown = page.is_visible("#bedtimeCard")
        hour = _dt.datetime.now().hour
        ok("Schlafenszeit erscheint zur richtigen Tageszeit",
           shown == (hour >= 15 or hour < 4), f"{hour} Uhr, sichtbar: {shown}")
        if shown:
            at = page.eval_on_selector("#bedtimeAt", "el => el.textContent.trim()")
            ok("Schlafenszeit nennt eine Uhrzeit",
               len(at) == 5 and at[2] == ":", at)
            facts = page.eval_on_selector("#bedtimeFacts", "el => el.textContent")
            ok("… mit Aufstehziel und Bedarf",
               "Aufstehen" in facts and "Schlafbedarf" in facts, facts[:70])
            ok("… und einer Begründung",
               bool(page.eval_on_selector("#bedtimeNote", "el => el.textContent.trim()")))

        # --- Layout: Karten verschieben und die Reihenfolge behalten ------
        page.click('nav.bottom button[data-view="start"]')
        page.wait_for_timeout(1500)

        def card_titles():
            # Nicht nur die Überschriften vergleichen: Manche Karten haben
            # keine, und ein Tausch mit einer davon bliebe unsichtbar.
            return page.eval_on_selector_all(
                "#view-start .grid-cards > .card",
                "e => e.map(x => x.id || (x.querySelector('h3') || {}).textContent || '?')")

        before_order = card_titles()
        grips = page.eval_on_selector_all("#view-start .grid-cards > .card > .drag", "e => e.length")
        ok("Jede Karte hat einen Griff",
           grips == page.eval_on_selector_all("#view-start .grid-cards > .card", "e => e.length"),
           f"{grips} Griffe")

        # Mit der Tastatur verschieben — dasselbe Ergebnis wie mit der Maus,
        # aber im Test verlässlich reproduzierbar.
        page.eval_on_selector("#view-start .grid-cards > .card:nth-child(3) > .drag", "el => el.focus()")
        page.keyboard.press("ArrowUp")
        page.wait_for_timeout(400)
        after_order = card_titles()
        ok("Eine Karte lässt sich verschieben", after_order != before_order,
           f"{before_order[:3]} -> {after_order[:3]}")

        page.reload(wait_until="networkidle")
        page.wait_for_timeout(2500)
        ok("Die Anordnung überlebt das Neuladen", card_titles() == after_order,
           str(card_titles()[:3]))

        # Sie muss auf dem Server liegen, nicht im Browser: Nach dem Leeren des
        # lokalen Speichers steht sie sonst nur auf diesem Gerät.
        page.evaluate("localStorage.clear()")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(3000)
        ok("Die Anordnung liegt auf dem Server, nicht im Browser",
           card_titles() == after_order, str(card_titles()[:3]))

        # Zurücksetzen muss die ursprüngliche Reihenfolge wiederherstellen.
        page.click('nav.bottom button[data-view="settings"]')
        page.wait_for_timeout(1200)
        page.click('nav.bottom button[data-view="start"]')
        page.wait_for_timeout(800)
        page.evaluate("localStorage.removeItem('puls.layout.start')")
        page.request.delete(f"http://127.0.0.1:{PORT}/api/layout/start")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(2500)
        ok("Zurücksetzen stellt die Vorgabe wieder her",
           card_titles() == before_order, str(card_titles()[:3]))

        # --- Kartenbreite selbst wählen -----------------------------------
        page.click('nav.bottom button[data-view="start"]')
        page.wait_for_timeout(1500)
        sels = page.eval_on_selector_all("#view-start .grid-cards > .card > .wsel",
                                         "e => e.length")
        ok("Jede Karte hat eine Breitenwahl",
           sels == page.eval_on_selector_all("#view-start .grid-cards > .card",
                                             "e => e.length"), f"{sels} Wähler")
        first = "#view-start .grid-cards > .card:nth-child(2)"
        page.click(f'{first} > .wsel [data-w="1"]')
        page.wait_for_timeout(300)
        ok("Die gewählte Breite steht an der Karte",
           page.eval_on_selector(first, "el => el.classList.contains('w1')"))
        ok("… und ist als aktiv markiert",
           page.eval_on_selector(f'{first} > .wsel [data-w="1"]',
                                 "el => el.classList.contains('on')"))
        page.click(f'{first} > .wsel [data-w="3"]')
        page.wait_for_timeout(300)
        ok("Umwählen ersetzt die Breite",
           page.eval_on_selector(first,
             "el => el.classList.contains('w3') && !el.classList.contains('w1')"))

        page.evaluate("localStorage.clear()")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(3000)
        ok("Die Breite liegt auf dem Server, nicht im Browser",
           page.eval_on_selector(first, "el => el.classList.contains('w3')"),
           page.eval_on_selector(first, "el => el.className"))

        # --- Trainingsdaten nachträglich anpassen -------------------------
        page.click('nav.bottom button[data-view="strength"]')
        page.wait_for_timeout(2000)
        page.click("#btnRecalc")
        page.wait_for_timeout(4000)
        ok("Der Anpassen-Knopf antwortet",
           bool(page.eval_on_selector("#changeList", "el => el.textContent.trim()")))

        # --- Vital: Schwelle und Stress -----------------------------------
        page.click('nav.bottom button[data-view="vital"]')
        page.wait_for_timeout(2500)
        ok("Vital: Laktatschwelle antwortet",
           bool(page.eval_on_selector("#thresholdBox", "el => el.textContent.trim()")))
        ok("Vital: Stressmuster antwortet",
           bool(page.eval_on_selector("#stressPattern", "el => el.textContent.trim()")))

        # --- Gewicht: Zielhochrechnung ------------------------------------
        page.click('nav.bottom button[data-view="weight"]')
        page.wait_for_timeout(2500)
        ok("Gewicht: Ziel wird angezeigt",
           bool(page.eval_on_selector("#goalNote", "el => el.textContent.trim()")),
           page.eval_on_selector("#goalNote", "el => el.textContent")[:70])

        # --- Kraft: was angepasst wurde -----------------------------------
        page.click('nav.bottom button[data-view="strength"]')
        page.wait_for_timeout(2500)
        ok("Kraft: Anpassungen werden erklärt",
           bool(page.eval_on_selector("#changeList", "el => el.textContent.trim()")))

        # --- Einheit auf Zuruf --------------------------------------------
        page.click('nav.bottom button[data-view="plan"]')
        page.wait_for_timeout(1800)
        page.fill("#wishText", "60 Minuten zuhause für den Handstand")
        page.click("#btnWish")
        page.wait_for_timeout(4000)
        wish = page.eval_on_selector("#wishPreview", "el => el.textContent")
        ok("Zuruf: es steht da, wie der Satz gelesen wurde",
           "Verstanden als" in wish, wish[:80])
        ok("Zuruf: der Handstand kommt vor", "Handstand" in wish, wish[:120])
        ok("Zuruf: mit Übungen", "Handgelenke" in wish, wish[:200])

        # Aufteilung der Woche
        opts = page.eval_on_selector_all("#autoSplit option",
                                         "e => e.map(x => x.textContent.trim())")
        ok("Aufteilungen wählbar", len(opts) == 4, str(opts))
        page.select_option("#autoSplit", "push_pull")
        page.wait_for_timeout(400)
        ok("Die Aufteilung wird erklärt",
           bool(page.eval_on_selector("#autoSplitNote", "el => el.textContent.trim()")))
        page.click("#btnAutoPreview")
        page.wait_for_timeout(9000)
        preview = page.eval_on_selector("#autoPreview", "el => el.textContent")
        ok("Push und Pull stehen in der Woche",
           "Push" in preview and "Pull" in preview, preview[:120])

        # --- Zuhause: Einheit ohne Geräte ---------------------------------
        page.click('nav.bottom button[data-view="plan"]')
        page.wait_for_timeout(1800)
        chips = page.eval_on_selector_all("#homeGroups [data-homegroup]", "e => e.length")
        ok("Zuhause: Muskelgruppen wählbar", chips == 5, f"{chips} Knöpfe")
        page.select_option("#homeMinutes", "30")
        page.click("#btnHomeSession")
        page.wait_for_timeout(3000)
        text = page.eval_on_selector("#homePreview", "el => el.textContent")
        ok("Zuhause: eine Einheit entsteht", "Zuhause" in text, text[:70])
        ok("Zuhause: mit der gewünschten Dauer", "30 min" in text or "29 min" in text
           or "31 min" in text, text[:70])

        # --- Schritte: Ziel und Tagesverlauf -------------------------------
        page.click('nav.bottom button[data-view="start"]')
        page.wait_for_timeout(2500)
        ok("Schritte: Karte steht da", page.is_visible("#stepCard"))
        ok("Schritte: Ziel wird genannt",
           bool(page.eval_on_selector("#stepGoal", "el => el.textContent.trim()")),
           page.eval_on_selector("#stepGoal", "el => el.textContent"))
        ok("Schritte: ein Satz erklärt den Stand",
           bool(page.eval_on_selector("#stepNote", "el => el.textContent.trim()")))

        page.click('nav.bottom button[data-view="vital"]')
        page.wait_for_timeout(2500)
        ok("Schritte: der typische Tag antwortet",
           bool(page.eval_on_selector("#stepTypicalChart", "el => el.textContent.trim()")
                or page.eval_on_selector_all("#stepTypicalChart svg", "e => e.length")))
        tabs = page.eval_on_selector_all("#stepTypicalRange [data-range]", "e => e.length")
        ok("Schritte: Zeitraum wählbar", tabs == 3, f"{tabs} Knöpfe")

        # --- Statistik: Empfehlungen muessen erscheinen -------------------
        page.click('nav.bottom button[data-view="stats"]')
        page.wait_for_timeout(2500)
        ok("Statistik: Einleitung gefüllt",
           bool(page.eval_on_selector("#statsIntro", "el => el.textContent.trim()")))
        ok("Statistik: Empfehlungsblock antwortet",
           bool(page.eval_on_selector("#statsRecs", "el => el.textContent.trim()")))
        metrics = page.eval_on_selector("#statsMetric", "el => el.options.length")
        ok("Statistik: Größen wählbar", metrics > 20, f"{metrics} Einträge")

        browser.close()
finally:
    server.should_exit = True

ok("Keine Fehler in der Browser-Konsole", not errors,
   " | ".join(dict.fromkeys(errors))[:400])

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Browser-Durchlauf ohne Fehler.")
