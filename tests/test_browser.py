"""Die Oberflaeche im echten Browser — was nur dort auffaellt.

Zwei Fehler haben es frueher bis zum Nutzer geschafft, die kein Zustandstest
sehen konnte: Knoepfe, deren CSS-Regel nicht griff (der Klick kam an, sichtbar
passierte nichts), und ein Lader, der an der falschen Stelle stand (der Reiter
blieb leer, ohne Fehlermeldung). Dieser Test klickt sich deshalb durch.

Wird uebersprungen, wenn Playwright oder Chromium fehlen.

Aufruf:  python3 tests/test_browser.py
"""
import datetime as dt
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

from app.db import get_db, init_db                          # noqa: E402
from app.main import app                                    # noqa: E402

init_db()
with get_db() as _db:
    _db.execute("""INSERT INTO activities(sport, start_time, duration_s,
                       distance_m, avg_hr, source, name)
                   VALUES('running', ?, 2400, 7000, 142, 'manual', 'Testlauf')""",
                (f"{dt.date.today().isoformat()}T07:00:00",))
    for _d in range(0, 14):
        _day = (dt.date.today() - dt.timedelta(days=_d)).isoformat()
        for _h, _m in ((7, 2), (13, 4), (21, 3)):
            _db.execute("""INSERT INTO mood_entries(day, recorded_at, mood,
                               energy, stress) VALUES(?,?,?,?,?)""",
                        (_day, f"{_day}T{_h:02d}:15:00", _m, _m, 3))
    _db.execute("""INSERT INTO daily_metrics(day, sleep_seconds, resting_hr,
                       training_readiness, body_battery_wake)
                   VALUES(?, 27000, 52, 74, 88)""", (dt.date.today().isoformat(),))

PORT = 8899
VIEWS = ("plan", "strength", "running", "mood")
failures: list[str] = []


def ok(name, condition, detail=""):
    print(f"{'OK  ' if condition else 'FAIL'} {name}{(' — ' + detail) if detail else ''}")
    if not condition:
        failures.append(name)


def find_chromium() -> str | None:
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
        page.wait_for_timeout(2500)

        # --- Der Einstieg: die Tagesempfehlung --------------------------
        ok("Die Tagesempfehlung steht da",
           page.inner_text("#todayHeadline").strip() not in ("", "…"),
           page.inner_text("#todayHeadline").strip())
        ok("… mit einem Satz", len(page.inner_text("#todayText").strip()) > 25,
           page.inner_text("#todayText")[:70])
        ok("… und Gründen",
           page.eval_on_selector_all("#todayReasons li", "e => e.length") >= 1)
        ok("Die Belastbarkeit wird gezeigt", page.is_visible("#readyBox"),
           page.inner_text("#readyNum"))

        # --- Jeder Reiter füllt sich ------------------------------------
        for view in VIEWS:
            page.click(f'nav.tabs button[data-view="{view}"]')
            page.wait_for_timeout(1800)
            ok(f"Reiter „{view}“ ist sichtbar", page.is_visible(f"#view-{view}"))
            filled = page.eval_on_selector(
                f"#view-{view}",
                "e => e.innerText.replace(/\\s+/g, ' ').trim().length")
            ok(f"Reiter „{view}“ ist gefüllt", filled > 120, f"{filled} Zeichen")

        # --- Der Kern: ein Training in Worten nachtragen ----------------
        page.click('nav.tabs button[data-view="strength"]')
        page.wait_for_timeout(1200)
        page.fill("#logText", "Heute Beinpresse 3x15 mit 60 kg, dann Latzug "
                              "12/10/8 bei 45 kg und Wadenheben stehend "
                              "3x20 mit 30 kg")
        page.click("#btnRead")
        page.wait_for_timeout(2500)
        items = page.eval_on_selector_all("#logPreview .preview-item", "e => e.length")
        ok("Die Vorschau zeigt die Übungen", items == 3, f"{items} Zeilen")
        ok("Neue Übungen sind als solche markiert",
           page.eval_on_selector_all("#logPreview .tag.new", "e => e.length") == 1)
        ok("Der Eintragen-Knopf erscheint", page.is_visible("#btnCommit"))

        # Jede Zeile muss sich richtigstellen lassen. Eine falsche Zuordnung,
        # die man nur abwaehlen statt korrigieren kann, kostet mehr als sie
        # spart — und genau daran ist die erste Fassung gescheitert.
        pickers = page.eval_on_selector_all("#logPreview select.picker", "e => e.length")
        ok("Jede Zeile hat eine Auswahl", pickers == 3, f"{pickers} Auswahlfelder")
        options = page.eval_on_selector(
            "#logPreview select.picker", "e => e.options.length")
        ok("… mit der ganzen Bibliothek darin", options > 20, f"{options} Einträge")
        first_label = page.inner_text("#logPreview .preview-item .item-title")
        page.select_option("#logPreview select.picker", label="Klimmzüge")
        page.wait_for_timeout(600)
        changed = page.inner_text("#logPreview .preview-item .item-title")
        ok("Eine Korrektur schlägt sofort durch",
           "Klimmzüge" in changed and changed != first_label,
           f"{first_label.strip()} → {changed.strip()}")
        page.select_option("#logPreview select.picker", label="Beinpresse")
        page.wait_for_timeout(600)

        # Satzzahl nachbessern, wenn im Text keine stand.
        boxes = page.eval_on_selector_all("#logPreview .sets-edit input", "e => e.length")
        ok("Gleiche Sätze lassen sich in Zahlen nachbessern", boxes >= 3,
           f"{boxes} Felder")

        # Die Haekchen muessen wirklich schaltbar sein — sonst kann man ein
        # Missverstaendnis sehen, aber nicht abwaehlen.
        box = page.query_selector("#logPreview .preview-item input")
        ok("Die Häkchen sind anklickbar", box is not None and box.is_visible())

        page.click("#btnCommit")
        page.wait_for_timeout(3000)
        ok("Nach dem Eintragen ist das Feld leer",
           page.input_value("#logText") == "")
        ok("Die Vorschläge stehen jetzt da", page.is_visible("#propCard"))
        props = page.eval_on_selector_all("#propList .prop", "e => e.length")
        ok("… für mehrere Übungen", props >= 2, f"{props} Vorschläge")
        ok("Jeder Vorschlag zeigt alt und neu",
           page.eval_on_selector_all("#propList .change .to", "e => e.length") == props)
        ok("Die Einheit taucht im Rückblick auf",
           page.eval_on_selector_all("#sessionList details", "e => e.length") >= 1)

        # Ein Vorschlag muss sich auch uebernehmen lassen.
        page.click("#propList .prop button:not(.ghost)")
        page.wait_for_timeout(2500)
        left = page.eval_on_selector_all("#propList .prop", "e => e.length")
        ok("Ein übernommener Vorschlag verschwindet", left == props - 1,
           f"{left} statt {props}")

        # --- Gemüt: die Zahlen müssen sichtbar reagieren ----------------
        page.click('nav.tabs button[data-view="mood"]')
        page.wait_for_timeout(1500)
        dots = page.eval_on_selector_all('.scale[data-key="mood"] .dot', "e => e.length")
        ok("Fünf Zahlen zur Auswahl", dots == 5, str(dots))
        size = page.eval_on_selector(
            '.scale[data-key="mood"] .dot',
            "e => { const r = e.getBoundingClientRect(); return [r.width, r.height]; }")
        ok("… gross genug zum Treffen", min(size) >= 32, f"{size[0]:.0f}×{size[1]:.0f} px")
        page.click('.scale[data-key="mood"] .dot:nth-child(4)')
        page.wait_for_timeout(300)
        marked = page.eval_on_selector_all('.scale[data-key="mood"] .dot.on',
                                           "e => e.length")
        ok("Der Klick wird sichtbar", marked == 4, f"{marked} markiert")
        # Sichtbar heisst: eine andere Farbe, nicht nur eine andere Klasse.
        colours = page.eval_on_selector_all(
            '.scale[data-key="mood"] .dot',
            "es => es.map(e => getComputedStyle(e).backgroundColor)")
        ok("… und zwar farblich", colours[0] != colours[4],
           f"{colours[0]} / {colours[4]}")

        page.click("#btnMoodSave")
        page.wait_for_timeout(2000)
        ok("Der Eintrag erscheint in der Liste",
           page.eval_on_selector_all("#moodList .item", "e => e.length") >= 1)

        # --- Der Verlauf zeichnet sich ----------------------------------
        ok("Die Kurve wird gezeichnet",
           page.eval_on_selector_all("#moodChart svg path", "e => e.length") >= 1)

        # --- Plan: die Wochentage lassen sich schalten ------------------
        page.click('nav.tabs button[data-view="plan"]')
        page.wait_for_timeout(1500)
        ok("Sieben Tage zur Auswahl",
           page.eval_on_selector_all("#gymDays .day", "e => e.length") == 7)
        on_before = page.eval_on_selector_all("#gymDays .day.on", "e => e.length")
        page.click("#gymDays .day:nth-child(6)")
        page.wait_for_timeout(1200)
        on_after = page.eval_on_selector_all("#gymDays .day.on", "e => e.length")
        ok("Ein Tag lässt sich zuschalten", on_after == on_before + 1,
           f"{on_before} → {on_after}")
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(2500)
        ok("… und bleibt nach dem Neuladen geschaltet",
           page.eval_on_selector_all("#gymDays .day.on", "e => e.length") == on_after)

        # --- Einstellungen öffnen sich ----------------------------------
        page.click("#btnSettings")
        page.wait_for_timeout(1500)
        ok("Die Einstellungen öffnen sich", page.is_visible("#dlgSettings"))
        ok("… und zeigen die Version",
           "Kennung" in page.inner_text("#versionLine"),
           page.inner_text("#versionLine"))

        # --- Auf dem Telefon darf nichts seitlich überstehen ------------
        page.keyboard.press("Escape")
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(1200)
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth - "
            "document.documentElement.clientWidth")
        ok("Kein seitliches Scrollen auf dem Telefon", overflow <= 1,
           f"{overflow} px zu breit")

        browser.close()
finally:
    server.should_exit = True

ok("Keine Fehler in der Konsole", not errors, "; ".join(errors[:3]))

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Browser-Tests bestanden.")
