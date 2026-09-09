"""Was der Coach ueber dich behaelt.

Ein Chat, der bei jeder Frage wieder bei null anfaengt, ist anstrengend: Man
erklaert zum dritten Mal, dass das linke Knie empfindlich ist. Deshalb haelt
PULS eine kleine Zahl von Saetzen fest, die dauerhaft gelten — keine
Gespraechshistorie, sondern Merkposten.

Zwei Wege hinein: Du sagst es ausdruecklich ("merk dir, dass ..."), oder das
Modell erkennt nach einem Gespraech etwas, das dauerhaft gilt. Beides landet
sichtbar in der Liste und laesst sich loeschen — nichts wird heimlich behalten.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from ..db import get_db, rows_to_dicts

log = logging.getLogger("puls.memory")

# Mehr als das gibt kein sinnvoller Kontext her, und ein 8B-Modell verliert
# bei langen Listen den Ueberblick. Angeheftetes bleibt immer.
MAX_FACTS = 25


def remember(topic: str, fact: str, source: str = "coach",
             pinned: bool = False) -> int:
    topic = (topic or "").strip()[:60]
    fact = (fact or "").strip()
    if not topic or not fact:
        raise ValueError("Merkposten brauchen Thema und Inhalt.")
    with get_db() as db:
        cur = db.execute(
            """INSERT INTO coach_memory(topic, fact, source, pinned)
               VALUES(?,?,?,?)
               ON CONFLICT(topic) DO UPDATE SET
                 fact=excluded.fact, source=excluded.source,
                 pinned=MAX(coach_memory.pinned, excluded.pinned),
                 updated_at=datetime('now')""",
            (topic, fact, source, 1 if pinned else 0))
        row = db.execute("SELECT id FROM coach_memory WHERE topic=?",
                         (topic,)).fetchone()
        # Aelteste, nicht angeheftete Eintraege verdraengen. Angeheftetes
        # steht schon durch pinned=0 in der WHERE-Klausel ausser Reichweite.
        db.execute(
            """DELETE FROM coach_memory WHERE pinned = 0 AND id NOT IN (
                 SELECT id FROM coach_memory WHERE pinned = 0
                 ORDER BY updated_at DESC LIMIT ?)""", (MAX_FACTS,))
    return int(row["id"] if row else cur.lastrowid or 0)


def forget(memory_id: int) -> bool:
    with get_db() as db:
        return db.execute("DELETE FROM coach_memory WHERE id=?",
                          (memory_id,)).rowcount > 0


def all_facts() -> list[dict[str, Any]]:
    with get_db() as db:
        return rows_to_dicts(db.execute(
            "SELECT * FROM coach_memory ORDER BY pinned DESC, updated_at DESC"
        ).fetchall())


def pin(memory_id: int, pinned: bool = True) -> bool:
    with get_db() as db:
        return db.execute("UPDATE coach_memory SET pinned=?, "
                          "updated_at=datetime('now') WHERE id=?",
                          (1 if pinned else 0, memory_id)).rowcount > 0


def as_context() -> list[str]:
    """Die Merkposten als knappe Zeilen fuer den Prompt."""
    return [f"{r['topic']}: {r['fact']}" for r in all_facts()]


def extract(question: str, answer: str) -> dict[str, Any] | None:
    """Nach einem Gespraech pruefen, ob etwas dauerhaft Gueltiges gefallen ist.

    Bewusst zurueckhaltend: Nur was ueber den Tag hinaus gilt, wird behalten.
    Tagesform, einzelne Trainings und Zahlen stehen ohnehin in der Datenbank.
    """
    text = (question or "").strip()
    if len(text) < 12:
        return None
    try:
        from .ollama_client import generate_json
        data = generate_json(
            prompt=(
                "Aus dieser Nachricht eines Sportlers an seinen Trainer: Gibt es "
                "eine Information, die dauerhaft gilt und die sich der Trainer "
                "merken sollte? Dauerhaft heisst: Vorlieben, Unvertraeglichkeiten, "
                "Verletzungsgeschichte, Ausruestung, Arbeitszeiten, Ziele.\n"
                "NICHT merken: Tagesform, einzelne Trainings, Zahlen, Termine.\n\n"
                "Antworte als JSON: {\"merken\": true/false, \"thema\": \"...\", "
                "\"fakt\": \"...\"}. Bei false thema und fakt leer lassen.\n\n"
                f"Nachricht: {text[:600]}"),
            system="Du extrahierst Daten. Du antwortest ausschliesslich mit JSON.")
        if not isinstance(data, dict) or not data.get("merken"):
            return None
        topic, fact = (data.get("thema") or "").strip(), (data.get("fakt") or "").strip()
        if not topic or not fact or len(fact) > 300:
            return None
        remember(topic, fact, source="coach")
        return {"topic": topic, "fact": fact}
    except Exception as e:
        log.debug("Nichts gemerkt: %s", e)
        return None
