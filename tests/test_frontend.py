"""Prueft das Frontend auf Fehler, die die ganze Oberflaeche lahmlegen.

Ein $("#id").onclick auf ein Element, das es nicht gibt, wirft einen
TypeError — und dann bricht app.js komplett ab. Nichts funktioniert mehr,
ohne dass irgendwo eine Fehlermeldung erscheint. Genau das faengt dieser Test.

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
dynamic = set(re.findall(r'id="([A-Za-z0-9_-]+)"', js)) | \
    set(re.findall(r'id="([A-Za-z0-9_-]+)"', charts))
known = html_ids | dynamic

# --- Der teuerste Fehler: ein Handler auf ein fehlendes Element ----------
bound = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)\.on[a-z]+\s*=', js))
check("Kein Handler auf ein fehlendes Element",
      sorted(bound - html_ids), [])

# --- Alle angesprochenen Elemente existieren irgendwo --------------------
used = set(re.findall(r'\$\("#([A-Za-z0-9_-]+)"\)', js))
check("Alle angesprochenen Elemente sind bekannt", sorted(used - known), [])

# --- Jede Ansicht hat einen Knopf und umgekehrt --------------------------
views = set(re.findall(r'id="view-([a-z-]+)"', html))
buttons = set(re.findall(r'data-view="([a-z-]+)"', html))
check("Jede Ansicht ist über die Navigation erreichbar", sorted(views - buttons), [])
check("Jeder Navigationsknopf hat eine Ansicht", sorted(buttons - views), [])
check("Fünf Reiter", len(buttons), 5)

# --- Jede Ansicht wird auch geladen --------------------------------------
loaders = re.search(r"const LOADERS = \{(.*?)\n\};", js, re.S)
mapped = set(re.findall(r"(\w+):", loaders.group(1))) if loaders else set()
check("Jede Ansicht hat eine Ladefunktion", sorted(views - mapped), [])
check("Kein Lader ohne Ansicht", sorted(mapped - views), [])

# --- Diagramm-Funktionen sind definiert, bevor app.js sie ruft -----------
for fn in ("runProfile", "routeMap", "splitChart", "timeChart"):
    check(f"{fn} ist in charts.js definiert", f"function {fn}(" in charts, True)
check("charts.js wird vor app.js geladen",
      html.index("charts.js") < html.index("app.js"), True)

# timeChart liest p.value — p.v waere still falsch und zeichnete eine
# leere Kurve, ohne dass irgendwo ein Fehler erscheint.
for call in re.findall(r"\{ t: [^}]*\}", js):
    if "getTime()" in call:
        check("Kurvenpunkte heissen value, nicht v", "value:" in call, True)
        break

# --- Verwendete CSS-Klassen existieren -----------------------------------
# Klassen, die app.js selbst vergibt: Fehlt eine, ist die Schaltflaeche da,
# sieht aber nach nichts aus — und niemand traut sich, sie zu druecken.
for cls in ("card", "wide", "item", "item-main", "item-title", "item-sub",
            "ready", "ready-num", "reasons", "parts", "steps", "row", "hint",
            "lead", "note", "bar", "bar-row", "bar-wrap", "fill", "day",
            "chip", "dot", "dots", "scale", "kpi", "need", "change",
            "preview-item", "session", "ex-line", "tag", "count", "ghost",
            "small", "danger", "profile", "routemap"):
    check(f"CSS-Klasse .{cls} definiert", f".{cls}" in css, True)

# display:contents schlaegt das display:none von [hidden] — ohne eine eigene
# Regel dafuer stuenden alle vier Reiter gleichzeitig untereinander.
if "display: contents" in css:
    check("Versteckte Abschnitte bleiben versteckt",
          "section[hidden]" in css, True)

# --- Jeder Reiter trägt das, was sein Name verspricht --------------------

def section(name):
    m = re.search(r'<section id="view-%s"[^>]*>' % name, html)
    if not m:
        return ""
    return html[m.end():html.index("\n</section>", m.end())]


def titles_of(name):
    return [t.strip() for t in re.findall(r"<h[23][^>]*>([^<]*)", section(name))]


EXPECTED = {
    "plan": ("Einheit auf Zuruf", "Deine Woche", "Geplante Einheiten"),
    "strength": ("Training nachtragen", "Muskelgruppen", "Letzte Einheiten"),
    "running": ("Form", "Trend", "Läufe"),
    "mood": ("Wie geht es dir?", "Verlauf", "Was daraus folgt"),
    "vital": ("Erholung", "Was gerade ausschlägt", "Deine Werte"),
}
for view, wanted in EXPECTED.items():
    have = [t.strip() for t in titles_of(view)]
    check(f"Reiter „{view}“ vollständig", [w for w in wanted if w not in have], [])

# Die Tagesempfehlung ist der Einstieg: Sie steht im ersten Reiter, ganz oben.
plan = section("plan")
check("Die Tagesempfehlung steht im Plan-Reiter", 'id="todayCard"' in plan, True)
check("… und zwar zuerst",
      plan.index('id="todayCard"') < plan.index('id="wishText"'), True)
first_tab = re.search(r'<nav class="tabs">\s*<button data-view="([a-z]+)"', html)
check("Plan ist der erste Reiter", first_tab.group(1), "plan")

# Das Nachtragen ist der Kern des Kraft-Reiters und steht deshalb obenan.
strength = section("strength")
check("Nachtragen steht oben im Kraft-Reiter",
      strength.index('id="logText"') < strength.index('id="exerciseList"'), True)

# Kein Element darf es zweimal geben.
all_ids = re.findall(r'id="([A-Za-z0-9_-]+)"', html)
doppelt = sorted({i for i in all_ids if all_ids.count(i) > 1})
check("Keine doppelten Element-Kennungen", doppelt, [])

# Jede Version wird in alle drei Dateien gestempelt — sonst holt der Browser
# nach einem Update weiter die alte app.js aus dem Cache.
for asset in ("style.css", "charts.js", "app.js"):
    check(f"{asset} trägt den Versionsstempel", f"{asset}?v={{{{V}}}}" in html, True)

if failures:
    print(f"\n{len(failures)} Test(s) fehlgeschlagen:")
    for name in failures:
        print(f"  - {name}")
    sys.exit(1)
print("\nAlle Frontend-Tests bestanden.")
