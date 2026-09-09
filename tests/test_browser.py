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

from app.main import app                                    # noqa: E402

PORT = 8899
VIEWS = ("dashboard", "plan", "exercises", "nutrition", "mood",
         "stats", "coach", "settings")
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

        # --- Jede Ansicht muss sich oeffnen lassen ------------------------
        for view in VIEWS:
            page.click(f'nav.bottom button[data-view="{view}"]')
            page.wait_for_timeout(1000)
            ok(f"Ansicht {view} öffnet", page.is_visible(f"#view-{view}"))

        # --- Coach: Ziel, Woche und Trends stehen auf einer Seite ---------
        page.click('nav.bottom button[data-view="coach"]')
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
        page.click('nav.bottom button[data-view="coach"]')
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
