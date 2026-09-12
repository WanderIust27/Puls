"""Die Verdrahtung der Wissensdatenbank — ohne Modell und ohne Netz.

Was hier geprueft wird, ist nicht die Qualitaet der Treffer: Die misst
tests/eval_knowledge.py, und dafuer braucht es ein echtes Einbettungsmodell.
Hier geht es um die Rohre. Kommt der Ingest durch, landen die Abschnitte in
der Datenbank, steht das Playbook vorne im Prompt, sind die Quellen die
abgerufenen — und passt der Prompt ueberhaupt ins Kontextfenster?

Der letzte Punkt ist der wichtigste. Ollama schneidet einen zu langen Prompt
stillschweigend von vorne ab, und vorne steht das Playbook. Von aussen sieht
man davon nichts.

Aufruf:  python3 tests/test_knowledge.py
"""
import datetime as dt
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["PULS_DATA_DIR"] = tempfile.mkdtemp(prefix="puls-test-")
os.environ["PULS_EMBED"] = "stub"

from app.db import get_db, init_db                              # noqa: E402
from app.puls_knowledge import (PROMPT_TEMPLATE, KnowledgeBase,  # noqa: E402
                                SKIP_FILES, chunk_markdown)
from app.services import facts, logbook                         # noqa: E402
from app.services.ollama_client import context_window           # noqa: E402

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


KB_DIR = ROOT / "knowledge"
init_db()

# ------------------------------------------------------------------ Quellen

files = sorted(p.name for p in KB_DIR.glob("*.md"))
check("Dreizehn Markdown-Dateien", len(files), 13)
ok("Playbook ist dabei", "11_Coach_Playbook.md" in files)
check("Playbook und README bleiben aus dem Index",
      SKIP_FILES, {"11_Coach_Playbook.md", "00_README.md"})

# Chunking: Jeder Abschnitt traegt seinen Ueberschriftenpfad im Text — sonst
# sucht das Embedding nach Inhalt, ohne zu wissen, worueber der Abschnitt
# ueberhaupt spricht.
chunks = chunk_markdown(KB_DIR / "01_Grundlagen_Muskelaufbau.md")
ok("Die Grundlagen zerfallen in mehrere Abschnitte", len(chunks) >= 5, str(len(chunks)))
ok("Jeder Abschnitt nennt seine Herkunft",
   all(c.source == "01_Grundlagen_Muskelaufbau.md" for c in chunks))
ok("… und traegt die Überschrift im Text",
   all(c.text.startswith(c.heading) for c in chunks))

# ------------------------------------------------------------------- Ingest

kb = KnowledgeBase(os.environ["PULS_DATA_DIR"] + "/puls.db")
first = kb.ingest(str(KB_DIR))
check("Elf Dateien indexiert", first["neu"], 11)
check("Zwei übersprungen", first["uebersprungen"], 2)
ok("Reichlich Abschnitte", first["gesamt"] > 80, str(first["gesamt"]))

# Idempotent: Ein zweiter Lauf darf nichts neu lesen, sonst dauert jeder Start
# so lange wie der erste.
again = kb.ingest(str(KB_DIR))
check("Zweiter Lauf liest nichts neu", again["neu"], 0)
check("… erkennt aber alles wieder", again["unveraendert"], 11)
check("… und der Index bleibt gleich gross", again["gesamt"], first["gesamt"])

with get_db() as db:
    tables = {r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
ok("Die kb_-Tabellen liegen in derselben Datei",
   {"kb_chunks", "kb_files", "kb_meta"} <= tables)
ok("… und kollidieren mit keiner PULS-Tabelle",
   {"exercises", "activities", "daily_metrics"} <= tables)

# Ein Modellwechsel macht die Vektoren unvergleichbar — dann muss neu gebaut
# werden, nicht ergaenzt.
kb.embedder.profile = type(kb.embedder.profile)(
    "anders", "anderes-modell", "stub", "", "")
after_switch = kb.ingest(str(KB_DIR))
check("Ein Modellwechsel baut den Index neu", after_switch["neu"], 11)

# ---------------------------------------------------------------- Retrieval

hits = kb.search("Wie viele Sätze pro Muskelgruppe und Woche?", k=5)
check("Fünf Treffer", len(hits), 5)
ok("Jeder Treffer nennt seine Datei", all(h["source"] for h in hits))
ok("Das Playbook taucht nicht auf",
   all(h["source"] not in SKIP_FILES for h in hits),
   str({h["source"] for h in hits}))

context, sources = kb.context_with_sources("Bringen BCAA etwas?")
ok("Der Kontext ist gefüllt", len(context) > 400, f"{len(context)} Zeichen")
ok("Die Quellen sind die abgerufenen",
   all(f"[Quelle: {s}]" in context for s in sources), str(sources))
ok("… und keine doppelt", len(sources) == len(set(sources)))

# ------------------------------------------------------------------- Prompt

playbook = (KB_DIR / "11_Coach_Playbook.md").read_text(encoding="utf-8")
prompt = PROMPT_TEMPLATE.format(playbook=playbook.strip(), kontext=context,
                                berechnet="- Test", frage="Bringen BCAA etwas?")
ok("Das Playbook steht ganz vorne",
   prompt.startswith("# Coach-Playbook"), prompt[:40])
ok("Die Auszüge stehen drin", "## Wissensauszüge" in prompt)
for rule in ("gelten die Auszüge", "haben meine Angaben Vorrang"):
    ok(f"Regel vorhanden: „{rule}“", rule in prompt)

# Der teuerste Fehler der ganzen Integration: Ollamas Vorgabe von 4096 Token
# schneidet diesen Prompt von vorne ab — und vorne steht das Playbook.
window = context_window(prompt)
ok("Der Prompt ist laenger als Ollamas Vorgabe", len(prompt) > 4096 * 3.2,
   f"{len(prompt)} Zeichen")
ok("Das Kontextfenster waechst mit", window >= 8192, str(window))
ok("Ein kurzer Prompt bleibt klein", context_window("Kurze Frage?") == 4096)

# ------------------------------------------------------- Berechnete Werte

today = dt.date.today()
monday = today - dt.timedelta(days=today.weekday())
logbook.commit(monday.isoformat(), logbook.preview(
    "Latzug 3x10 mit 50 kg, Bankdrücken 3x8 mit 60 kg", today)["items"], [])
with get_db() as db:
    for days, km in ((3, 6.0), (9, 9.4)):
        db.execute("INSERT INTO activities(source, sport, start_time, distance_m,"
                   " duration_s) VALUES('garmin','running',?,?,2700)",
                   ((today - dt.timedelta(days=days)).isoformat() + "T07:00:00",
                    km * 1000))
    for i in range(1, 8):
        db.execute("INSERT OR IGNORE INTO daily_metrics(day, sleep_seconds) "
                   "VALUES(?, ?)", ((today - dt.timedelta(days=i)).isoformat(),
                                    6.4 * 3600))

volume = facts.weekly_volume(today)
check("Rücken: drei direkte Sätze", volume["back"], 3.0)
# Latzug zieht den Bizeps mit, Bankdruecken den Trizeps — je zur Haelfte.
check("Arme: nur indirekt, also die Haelfte", volume["arms"], 3.0)
check("Brust: drei direkte", volume["chest"], 3.0)

limit = facts.run_limit(today)
check("Längster Lauf der letzten 30 Tage", limit["longest_km"], 9.4)
check("… und das Limit daraus", limit["limit_km"], 10.3)

block = facts.computed_block(today)
ok("Der Block nennt das Satzvolumen", "Harte Sätze diese Woche" in block)
ok("… das Lauflimit", "höchstens 10,3 km" in block, block)
ok("… und den Schlaf", "6,4 h" in block)
ok("Keine Zeile für Protein, weil nichts getrackt wird",
   "Protein" not in block, block)
ok("Keine Platzhalter im Block",
   not any(w in block for w in ("None", "null", "0 g", "—")), block)

# Ohne Daten bleibt der Block leer statt voller Nullen.
with get_db() as db:
    db.execute("DELETE FROM exercise_sets")
    db.execute("DELETE FROM activities")
    db.execute("DELETE FROM daily_metrics")
check("Ohne Daten bleibt der Block leer", facts.computed_block(today), "")

print()
if failures:
    print(f"{len(failures)} Test(s) fehlgeschlagen: {', '.join(failures)}")
    sys.exit(1)
print("Alle Tests der Wissensdatenbank bestanden.")
