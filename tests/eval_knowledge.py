"""
eval_knowledge.py — Testet Retrieval und Antwortqualität der PULS-Wissensdatenbank.

    # nur Retrieval (schnell, kein LLM nötig)
    python eval_knowledge.py retrieval

    # Antworten gegen Ollama, mit A/B gegen "ohne Kontext"
    python eval_knowledge.py antworten --model qwen3:8b

Umgebung:
    PULS_DB      Pfad zur SQLite-Datei (Default: puls.db)
    PULS_KB      Ordner mit den .md-Dateien (für das Playbook)
    PULS_EMBED   Einbettungsprofil: minilm | e5 | stub
    OLLAMA_URL   Default: http://localhost:11434
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.puls_knowledge import KnowledgeBase, PROMPT_TEMPLATE   # noqa: E402

# ---------------------------------------------------------------------------
# Testfragen
#
#   quellen    – mindestens eine dieser Dateien muss unter den Treffern sein
#   muss       – mindestens einer dieser Begriffe muss im Kontext/in der Antwort stehen
#   darf_nicht – kommt einer davon in der Antwort vor, ist sie falsch
#   typ        – normal | falle | negativ
#
# "falle" = Fragen, bei denen die verbreitete Meinung falsch ist. Genau die
# zeigen, ob der Kontext tatsächlich gelesen wird.
# ---------------------------------------------------------------------------

EVAL = [
    # --- Training -----------------------------------------------------------
    dict(frage="Wie viele Sätze pro Muskelgruppe und Woche sind sinnvoll?",
         quellen=["01_Grundlagen_Muskelaufbau.md"], muss=["12", "20"], typ="normal"),
    dict(frage="Wie nah soll ich beim Satz ans Muskelversagen gehen?",
         quellen=["01_Grundlagen_Muskelaufbau.md"], muss=["RIR", "Reserve"], typ="normal"),
    dict(frage="Wie oft pro Woche sollte ich jede Muskelgruppe trainieren?",
         quellen=["01_Grundlagen_Muskelaufbau.md"], muss=["Frequenz", "2"], typ="normal"),
    dict(frage="Wie lange soll ich zwischen den Sätzen pausieren?",
         quellen=["01_Grundlagen_Muskelaufbau.md"], muss=["3 min", "2–3", "Minuten"],
         darf_nicht=["30 Sekunden", "kurze Pausen sind besser"], typ="falle"),
    dict(frage="Sind Maschinen schlechter als freie Gewichte für Muskelaufbau?",
         quellen=["02_Training_Gym.md"], muss=["kein", "nicht"],
         darf_nicht=["deutlich überlegen", "freie Gewichte sind besser"], typ="falle"),
    dict(frage="Kann ich zuhause ohne Geräte überhaupt Muskeln aufbauen?",
         quellen=["03_Training_Zuhause_Calisthenics.md", "01_Grundlagen_Muskelaufbau.md"],
         muss=["Versagen", "progress", "Last"], typ="normal"),
    dict(frage="Wie schaffe ich mehr Klimmzüge?",
         quellen=["03_Training_Zuhause_Calisthenics.md"],
         muss=["negativ", "Band", "Sätze"], typ="normal"),
    dict(frage="Wann brauche ich eine Deload-Woche?",
         quellen=["01_Grundlagen_Muskelaufbau.md"], muss=["Deload", "Leistung"], typ="normal"),

    # --- Ernährung ----------------------------------------------------------
    dict(frage="Wie viel Protein brauche ich pro Tag zum Muskelaufbau?",
         quellen=["05_Ernaehrung_Grundlagen.md"], muss=["1,6", "1.6", "2,0"], typ="normal"),
    dict(frage="Wie schnell sollte ich in der Aufbauphase zunehmen?",
         quellen=["05_Ernaehrung_Grundlagen.md"], muss=["0,25", "0,5"],
         darf_nicht=["1 kg pro Woche", "so viel wie möglich"], typ="falle"),
    dict(frage="Wie schnell kann ich abnehmen ohne Muskeln zu verlieren?",
         quellen=["05_Ernaehrung_Grundlagen.md"], muss=["0,5", "1 %", "1%"], typ="normal"),
    dict(frage="Was ist die günstigste Proteinquelle?",
         quellen=["06_Guenstig_Kochen.md"], muss=["Linsen", "Magerquark", "Quark"],
         typ="normal"),
    dict(frage="Lohnen sich Proteinriegel?",
         quellen=["06_Guenstig_Kochen.md", "07_Supplemente.md"],
         muss=["teuer", "Quark", "Marketing"],
         darf_nicht=["gute Wahl", "empfehlenswert"], typ="falle"),
    dict(frage="Muss ich direkt nach dem Training Protein essen?",
         quellen=["05_Ernaehrung_Grundlagen.md", "10_Mythen.md"],
         muss=["Tagesgesamt", "Fenster", "breiter"],
         darf_nicht=["30 Minuten sind entscheidend", "sonst war es umsonst"], typ="falle"),

    # --- Supplemente --------------------------------------------------------
    dict(frage="Soll ich Kreatin nehmen und wie viel?",
         quellen=["07_Supplemente.md"], muss=["3–5", "3-5", "Monohydrat"], typ="normal"),
    dict(frage="Bringen BCAA etwas für den Muskelaufbau?",
         quellen=["07_Supplemente.md", "10_Mythen.md"],
         muss=["nicht", "kein", "Gruppe C"],
         darf_nicht=["empfehlenswert", "unterstützt den Muskelaufbau", "sinnvoll"],
         typ="falle"),
    dict(frage="Schadet Kreatin den Nieren?",
         quellen=["07_Supplemente.md", "10_Mythen.md"], muss=["kein Beleg", "kein", "nicht"],
         darf_nicht=["ja, Kreatin belastet"], typ="falle"),
    dict(frage="Brauche ich Vitamin D im Winter?",
         quellen=["07_Supplemente.md"], muss=["20", "800", "Winter"], typ="normal"),

    # --- Cardio -------------------------------------------------------------
    dict(frage="Darf ich meine Laufumfänge um 10 Prozent pro Woche steigern?",
         quellen=["04_Cardio_Laufen_HIIT.md", "10_Mythen.md"],
         muss=["110", "einzeln", "30 Tage"],
         darf_nicht=["ja, die 10-Prozent-Regel", "10-%-Regel ist der beste"], typ="falle"),
    dict(frage="Killt Laufen meinen Muskelaufbau?",
         quellen=["04_Cardio_Laufen_HIIT.md"], muss=["Interferenz", "kein", "klein"],
         darf_nicht=["ja, du verlierst Muskeln"], typ="falle"),
    dict(frage="Welches HIIT-Protokoll ist am besten belegt?",
         quellen=["04_Cardio_Laufen_HIIT.md"], muss=["4×4", "4x4", "norweg"], typ="normal"),
    dict(frage="Wie verteile ich Intensitäten beim Laufen über die Woche?",
         quellen=["04_Cardio_Laufen_HIIT.md"], muss=["80", "polaris", "locker"], typ="normal"),

    # --- Regeneration -------------------------------------------------------
    dict(frage="Ist ein Eisbad nach dem Krafttraining gut?",
         quellen=["08_Regeneration_Schlaf_Aufwaermen.md", "10_Mythen.md"],
         muss=["dämpf", "abschwäch", "nicht"],
         darf_nicht=["ja, beschleunigt die Regeneration", "empfehlenswert nach dem Krafttraining"],
         typ="falle"),
    dict(frage="Soll ich mich vor dem Krafttraining statisch dehnen?",
         quellen=["08_Regeneration_Schlaf_Aufwaermen.md"],
         muss=["dynamisch", "60"], typ="falle"),
    dict(frage="Wie viel Schlaf brauche ich als Sportler?",
         quellen=["08_Regeneration_Schlaf_Aufwaermen.md"], muss=["7", "9"], typ="normal"),
    dict(frage="Darf ich mit Erkältung trainieren?",
         quellen=["08_Regeneration_Schlaf_Aufwaermen.md"],
         muss=["Hals", "Fieber"], typ="normal"),

    # --- Körperfett ---------------------------------------------------------
    dict(frage="Wie bekomme ich gezielt Bauchfett weg?",
         quellen=["09_Sixpack_Koerperfett.md", "10_Mythen.md"],
         muss=["punktuell", "nicht", "Energiebilanz"],
         darf_nicht=["diese 5 Übungen", "Bauchtraining reduziert Bauchfett"], typ="falle"),
    dict(frage="Ab welchem Körperfettanteil sieht man ein Sixpack?",
         quellen=["09_Sixpack_Koerperfett.md"], muss=["9", "12", "%"], typ="normal"),

    # --- Negativtests: nicht abgedeckt --------------------------------------
    dict(frage="Wie dosiere ich Testosteron-Enantat für einen Aufbauzyklus?",
         quellen=[], muss=[], darf_nicht=["mg pro Woche", "ml", "Zyklus von"],
         typ="negativ"),
    dict(frage="Welche Laufschuhgröße soll ich bestellen?",
         quellen=[], muss=[], darf_nicht=["eine halbe Größe größer ist Standard"],
         typ="negativ"),
]


# ---------------------------------------------------------------------------


def _treffer(text: str, begriffe: list[str]) -> bool:
    low = text.lower()
    return any(b.lower() in low for b in begriffe)


def test_retrieval(kb: KnowledgeBase, k: int = 5) -> None:
    gesamt = fehler = 0
    print(f"\nRETRIEVAL (Top-{k})\n" + "=" * 72)

    for fall in EVAL:
        if fall["typ"] == "negativ":
            continue
        gesamt += 1
        hits = kb.search(fall["frage"], k=k)
        quellen = [h["source"] for h in hits]
        kontext = "\n".join(h["text"] for h in hits)

        quelle_ok = any(q in quellen for q in fall["quellen"])
        inhalt_ok = (not fall["muss"]) or _treffer(kontext, fall["muss"])

        if quelle_ok and inhalt_ok:
            print(f"  OK    {fall['frage'][:58]}")
        else:
            fehler += 1
            print(f"  FEHL  {fall['frage'][:58]}")
            print(f"        erwartet: {fall['quellen']}")
            print(f"        bekommen: {quellen}")
            if not inhalt_ok:
                print(f"        Begriffe fehlen im Kontext: {fall['muss']}")

    quote = (gesamt - fehler) / gesamt * 100 if gesamt else 0
    print("=" * 72)
    print(f"  Recall@{k}: {gesamt - fehler}/{gesamt}  ({quote:.0f} %)")
    if quote < 85:
        print("  → unter 85 %. Erst das Retrieval fixen, nicht den Prompt.")
        print("    Stellschrauben: k erhöhen, CHUNK_TARGET verkleinern,")
        print("    Überschriften präziser, Synonyme in die .md-Dateien.")


def frage_ollama(model: str, prompt: str, url: str) -> str:
    r = requests.post(
        f"{url}/api/generate",
        json={"model": model, "prompt": prompt, "stream": False,
              "options": {"temperature": 0.2, "num_ctx": 8192}},
        timeout=600,
    )
    r.raise_for_status()
    return r.json().get("response", "")


def test_antworten(kb: KnowledgeBase, model: str, playbook: str,
                   url: str, ab: bool = True) -> None:
    print(f"\nANTWORTEN  (Modell: {model})\n" + "=" * 72)
    stats = {"mit": 0, "ohne": 0, "n": 0}

    for fall in EVAL:
        stats["n"] += 1
        prompt = PROMPT_TEMPLATE.format(
            playbook=playbook,
            kontext=kb.build_context(fall["frage"]) or "(nichts gefunden)",
            berechnet="—",
            frage=fall["frage"],
        )
        antwort = frage_ollama(model, prompt, url)

        if fall["typ"] == "negativ":
            gab_zu = _treffer(antwort, ["steht nicht", "keine", "nicht abgedeckt",
                                        "kann ich nicht", "Arzt", "nicht in den"])
            erfunden = _treffer(antwort, fall.get("darf_nicht", []))
            ok = gab_zu and not erfunden
        else:
            ok = ((not fall["muss"]) or _treffer(antwort, fall["muss"])) and \
                 not _treffer(antwort, fall.get("darf_nicht", []))

        stats["mit"] += int(ok)
        marke = "OK   " if ok else "FEHL "
        tag = {"falle": "[Falle]  ", "negativ": "[Negativ]", "normal": "         "}[fall["typ"]]
        print(f"  {marke} {tag} {fall['frage'][:50]}")
        if not ok:
            print(f"         → {antwort.strip()[:180]}")

        # A/B nur für Fallenfragen – dort ist der Unterschied aussagekräftig
        if ab and fall["typ"] == "falle":
            roh = frage_ollama(model, fall["frage"], url)
            roh_ok = _treffer(roh, fall["muss"]) and \
                not _treffer(roh, fall.get("darf_nicht", []))
            stats["ohne"] += int(roh_ok)

    fallen = sum(1 for f in EVAL if f["typ"] == "falle")
    print("=" * 72)
    print(f"  Mit Wissensdatenbank:  {stats['mit']}/{stats['n']}")
    if ab:
        print(f"  Fallenfragen ohne KB:  {stats['ohne']}/{fallen}")
        print("  → Die Differenz bei den Fallen ist der eigentliche Nutzen.")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("modus", choices=["retrieval", "antworten"])
    p.add_argument("--model", default="qwen3:8b")
    p.add_argument("--k", type=int, default=5)
    p.add_argument("--kein-ab", action="store_true")
    args = p.parse_args()

    kb = KnowledgeBase(os.environ.get("PULS_DB", "puls.db"))

    if args.modus == "retrieval":
        test_retrieval(kb, k=args.k)
        return

    kb_dir = Path(os.environ.get("PULS_KB", "."))
    pb = kb_dir / "11_Coach_Playbook.md"
    if not pb.exists():
        sys.exit(f"Playbook nicht gefunden: {pb}  (PULS_KB setzen)")

    test_antworten(
        kb, args.model, pb.read_text(encoding="utf-8"),
        os.environ.get("OLLAMA_URL", "http://localhost:11434"),
        ab=not args.kein_ab,
    )


if __name__ == "__main__":
    main()
