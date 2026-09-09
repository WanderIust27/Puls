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

        # --- Autopilot: die Felder muessen befuellt sein ------------------
        page.click('nav.bottom button[data-view="settings"]')
        page.wait_for_timeout(1500)
        focus = page.eval_on_selector("#autoFocus", "el => el.options.length")
        days = page.eval_on_selector("#autoLongDay", "el => el.options.length")
        chips = page.eval_on_selector_all("#autoDays [data-autoday]", "e => e.length")
        minutes = page.eval_on_selector("#autoMinutes", "el => el.value")
        note = page.eval_on_selector("#autoFocusNote", "el => el.textContent.trim()")
        ok("Autopilot: Schwerpunkte wählbar", focus >= 4, f"{focus} Einträge")
        ok("Autopilot: alle Wochentage wählbar", days == 7, f"{days} Einträge")
        ok("Autopilot: Tagesknöpfe da", chips == 7, f"{chips} Knöpfe")
        ok("Autopilot: Dauer vorbelegt", bool(minutes), repr(minutes))
        ok("Autopilot: Schwerpunkt erklärt", bool(note))

        # --- Auswaehlen muss auch wirken ----------------------------------
        page.select_option("#autoFocus", "build_muscle")
        page.wait_for_timeout(300)
        ok("Autopilot: Wechsel ändert die Erklärung",
           page.eval_on_selector("#autoFocusNote", "el => el.textContent.trim()") != note)

        page.click('#autoDays [data-autoday="Mo"]')
        page.wait_for_timeout(200)
        active = page.eval_on_selector_all("#autoDays .chip.on", "e => e.map(x => x.textContent)")
        ok("Autopilot: Tag lässt sich abwählen", "Mo" not in active, str(active))

        page.click("#btnAutoSave")
        page.wait_for_timeout(1200)
        page.reload(wait_until="networkidle")
        page.click('nav.bottom button[data-view="settings"]')
        page.wait_for_timeout(1800)
        kept = page.eval_on_selector("#autoFocus", "el => el.value")
        ok("Autopilot: Auswahl überlebt das Neuladen", kept == "build_muscle", kept)

        page.click("#btnAutoPreview")
        page.wait_for_timeout(10000)
        planned = page.eval_on_selector_all("#autoPreview .auto-day", "e => e.length")
        ok("Autopilot: Vorschau zeigt die Woche", planned == 7, f"{planned} Tage")

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
