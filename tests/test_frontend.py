"""Prueft das Frontend auf Fehler, die die ganze Oberflaeche lahmlegen.

Ein $("#id").addEventListener(...) auf oberster Ebene wirft einen TypeError,
wenn es das Element nicht gibt — und dann bricht app.js komplett ab. Nichts
funktioniert mehr, ohne dass irgendwo eine Fehlermeldung erscheint. Genau das
faengt dieser Test.

Aufruf:  python3 tests/test_frontend.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
js = (ROOT / "app/static/app.js").read_text()
charts = (ROOT / "app/static/charts.js").read_text()
html = (ROOT / "app/static/index.html").read_text()
css = (ROOT / "app/static/style.css").read_text()

failures = []


def check(name, actual, expected):
    ok = actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual!r} (erwartet {expected!r})")
    if not ok:
        failures.append(name)


html_ids = set(re.findall(r'id="([^"]+)"', html))
# Elemente, die erst zur Laufzeit in innerHTML entstehen
dynamic = set(re.findall(r'id="([A-Za-z0-9_-]+)"', js)) | \
    set(re.findall(r'id="([A-Za-z0-9_-]+)"', charts))
known = html_ids | dynamic

# --- Der teuerste Fehler: Zugriff beim Laden auf ein fehlendes Element ---
toplevel = [m.group(1) for m in
            re.finditer(r'^\$\("#([A-Za-z0-9_-]+)"\)\.addEventListener', js, re.M)]
check("Kein Top-Level-Zugriff auf fehlende Elemente",
      sorted(i for i in toplevel if i not in html_ids), [])

# --- Alle angesprochenen Elemente existieren irgendwo --------------------
used = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', js))
check("Alle angesprochenen Elemente sind bekannt",
      sorted(used - known), [])

# --- Jede Ansicht hat einen Knopf und umgekehrt --------------------------
views = set(re.findall(r'id="view-([a-z-]+)"', html))
buttons = set(re.findall(r'data-view="([a-z-]+)"', html))
check("Jede Ansicht ist über die Navigation erreichbar", sorted(views - buttons), [])
check("Jeder Navigationsknopf hat eine Ansicht", sorted(buttons - views), [])

# --- Jede Ansicht wird auch geladen --------------------------------------
loaders = re.search(r"\{\s*dashboard:.*?\}", js, re.S)
mapped = set(re.findall(r"(\w+):\s*load", loaders.group(0))) if loaders else set()
check("Jede Ansicht hat eine Ladefunktion", sorted(views - mapped), [])

# --- Diagramm-Funktionen sind definiert, bevor app.js sie ruft -----------
for fn in ("runProfile", "routeMap", "splitChart", "dayCurve", "sparkline"):
    check(f"{fn} ist in charts.js definiert", f"function {fn}(" in charts, True)
check("charts.js wird vor app.js geladen",
      html.index("charts.js") < html.index("app.js"), True)

# --- Verwendete CSS-Klassen existieren -----------------------------------
# Nur die tragenden Klassen; Vollstaendigkeit waere hier eher hinderlich.
for cls in ("score-ring", "pillar", "diag", "supp-row", "mood-row", "body-facts",
            "bf-bar", "gym-ex", "chip", "profile", "routemap", "grid-cards",
            "tile", "mini", "card-link", "bests"):
    check(f"CSS-Klasse .{cls} definiert", f".{cls}" in css, True)

# --- 0 darf nicht als "kein Wert" behandelt werden -----------------------
# Ein Score von 0 ist gueltig; p.value || "–" wuerde ihn verschlucken.
check("Score prüft auf null statt auf Wahrheitswert",
      "p.value != null" in js, True)

# --- Das Dashboard soll das führen, was täglich gebraucht wird -----------
dash = html[html.index('id="view-dashboard"'):html.index('id="view-plan"')]
import re as _re
titles = _re.findall(r"<h3>([^<]+)</h3>", dash)
for wanted in ("Heute dran", "Nächste Workouts", "Zuletzt trainiert",
               "Schlaf", "Herz"):
    check(f"Dashboard zeigt „{wanted}“", wanted in titles, True)
check("Score steht auf dem Dashboard", 'id="scoreRing"' in dash, True)
check("Dashboard nutzt das Raster", 'class="grid-cards"' in dash, True)

# --- Die Verweise am Kartenfuß müssen auf echte Ansichten zeigen --------
gotos = set(_re.findall(r'data-goto="([a-z-]+)"', html)) | \
    set(_re.findall(r'data-goto="([a-z-]+)"', js))
check("Kartenverweise zeigen auf vorhandene Ansichten", sorted(gotos - views), [])

if failures:
    print(f"\n{len(failures)} Test(s) fehlgeschlagen:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\nAlle Frontend-Tests bestanden.")
